"""
Phase 4 (doc-16): Chat Manager's real gap -- it currently fails open, and
a genuine crash was indistinguishable from "nothing to extract" (both
produced chat_summary=None with the exception itself silently swallowed,
no logging at all).

Confirmed with PM14 directly before touching core/orchestrator.py (a live,
100%-of-real-traffic file, unlike everything else built tonight): this is
NOT the generic "graceful failure handling" mechanism from doc-13 (that's
explicitly Backend/Shared-Services-owned and explicitly "not built"
anywhere yet) -- it's a small, control-flow-neutral fix scoped to exactly
two things: (1) stop swallowing the exception silently -- log it with real
context; (2) make "Chat Manager crashed" distinguishable from "nothing to
extract" via a new chat_manager_error response field. No new whisper/
Signal to the PM, no retry -- both explicitly deferred.

Real precision finding during design, not an afterthought: the task-scoped
path's own try/except also wraps GATEKEEPER_ASSESSMENT's own
evaluate_triggers() call (assess_coverage, a real model call that can also
throw) -- a genuine pre-existing coupling. A naive fix would mislabel a
real Gatekeeper crash as chat_manager_error. Fixed with an inner try/
except that tags which step actually threw, then re-raises to the same
outer handler -- net effect: IDENTICAL control flow to before this change,
confirmed here by exercising both failure modes and asserting the turn's
observable behavior (physics_open/status/chat_summary/chat_manager_error)
matches exactly what's expected in each case.

Byte-identical regression against every existing real historical scenario
(tests/phase_1_5/test_trigger_sequencing_regression.py's own 92 checks,
re-run unchanged after this edit) is the primary safety net for "did this
change anything it shouldn't have" -- this file adds the scenarios that
harness structurally can't produce on its own (a real exception, forced
deliberately).
"""
import asyncio
import io
import sys
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, "/Users/fred/vibe-kernel/.claude/worktrees/hungry-booth-3d3e83")

from schema.kernel_schema import AgentEnvelope
from core.orchestrator import MasterOrchestrator
import core.orchestrator as orchestrator_mod
import core.triggers as triggers_mod

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def build_envelope(**overrides):
    base = dict(
        app_id="a", project_id="a", milestone_config={"required_questions": ["What's the plan?"]},
        persona_config={}, knowledge_bricks={}, history=[],
    )
    base.update(overrides)
    return AgentEnvelope(**base)


async def run_scenario(envelope, is_global, chat_manager_raises=False, gatekeeper_raises=False):
    def fake_run_chat_manager(env, required_questions=None):
        if chat_manager_raises:
            raise RuntimeError("real simulated Chat Manager crash")
        env.chat_summary = [{"content": "a real fact", "type": "fact", "speaker": "user", "turn_index": 0}]
        env.chat_summary_cursor = 1
        env.chat_whisper = None
        return env.chat_summary

    def fake_assess_coverage(*args, **kwargs):
        if gatekeeper_raises:
            raise RuntimeError("real simulated Gatekeeper crash")
        return {"gate_status": "RED", "whisper": "not ready", "assessments": []}

    def fake_confirm_launch_intent(*args, **kwargs):
        return False

    async def fake_run_turn(envelope):
        return "a real social response"

    async def fake_run_global_turn(envelope):
        return {"social_response": "a real global response", "tool_call": None}

    with patch.object(orchestrator_mod.MasterOrchestrator, "_run_chat_manager", side_effect=fake_run_chat_manager), \
         patch.object(triggers_mod, "assess_coverage", side_effect=fake_assess_coverage), \
         patch.object(triggers_mod, "confirm_launch_intent", side_effect=fake_confirm_launch_intent), \
         patch.object(orchestrator_mod.SocialEngine, "run_turn", side_effect=fake_run_turn), \
         patch.object(orchestrator_mod.SocialEngine, "run_global_turn", side_effect=fake_run_global_turn):
        captured_stdout = io.StringIO()
        with redirect_stdout(captured_stdout):
            result = await MasterOrchestrator.process_turn(envelope, "hello", is_global=is_global)
        return result, captured_stdout.getvalue()


async def main():
    # 1. Task-scoped: Chat Manager itself crashes.
    env1 = build_envelope()
    result1, logs1 = await run_scenario(env1, is_global=False, chat_manager_raises=True)
    check("task-scoped Chat Manager crash: chat_manager_error is the real exception message",
          result1.get("chat_manager_error") == "real simulated Chat Manager crash", result1.get("chat_manager_error"))
    check("task-scoped Chat Manager crash: chat_summary is None (unchanged fail-open behavior)",
          result1.get("chat_summary") is None, result1)
    check("task-scoped Chat Manager crash: status falls back to PROBING (physics_open False, unchanged)",
          result1.get("status") == "PROBING", result1.get("status"))
    check("task-scoped Chat Manager crash: real [CHAT MANAGER CRASH] log line present",
          "[CHAT MANAGER CRASH] real simulated Chat Manager crash" in logs1, logs1)
    check("task-scoped Chat Manager crash: no [GATEKEEPER ASSESSMENT CRASH] log (Gatekeeper never actually ran)",
          "[GATEKEEPER ASSESSMENT CRASH]" not in logs1, logs1)

    # 2. Task-scoped: Chat Manager succeeds, Gatekeeper's own step crashes --
    #    must NOT be mislabeled as chat_manager_error.
    env2 = build_envelope()
    result2, logs2 = await run_scenario(env2, is_global=False, chat_manager_raises=False, gatekeeper_raises=True)
    check("task-scoped Gatekeeper crash: chat_manager_error stays None (not mislabeled)",
          result2.get("chat_manager_error") is None, result2.get("chat_manager_error"))
    check("task-scoped Gatekeeper crash: status still falls back to PROBING (same turn behavior as before this fix)",
          result2.get("status") == "PROBING", result2.get("status"))
    check("task-scoped Gatekeeper crash: real [GATEKEEPER ASSESSMENT CRASH] log line present",
          "[GATEKEEPER ASSESSMENT CRASH] real simulated Gatekeeper crash" in logs2, logs2)
    check("task-scoped Gatekeeper crash: no [CHAT MANAGER CRASH] log (Chat Manager genuinely succeeded)",
          "[CHAT MANAGER CRASH]" not in logs2, logs2)

    # 3. Task-scoped: happy path, no exceptions at all -- chat_manager_error
    #    stays None, byte-identical to before this field existed.
    env3 = build_envelope()
    result3, logs3 = await run_scenario(env3, is_global=False)
    check("task-scoped happy path: chat_manager_error is None", result3.get("chat_manager_error") is None, result3)
    check("task-scoped happy path: no crash logs of either kind",
          "[CHAT MANAGER CRASH]" not in logs3 and "[GATEKEEPER ASSESSMENT CRASH]" not in logs3, logs3)

    # 4. Task-scoped: "nothing to extract" (no required_questions at all) --
    #    also produces chat_summary=None, but must NOT populate
    #    chat_manager_error (that's a real, expected state, not a crash).
    env4 = build_envelope(milestone_config={})
    result4, logs4 = await run_scenario(env4, is_global=False)
    check("task-scoped no-required-questions: chat_summary is None (as before)", result4.get("chat_summary") is None, result4)
    check("task-scoped no-required-questions: chat_manager_error stays None -- distinguishable from a real crash by definition (both None here, but this is the 'expected' None, not the crash path)",
          result4.get("chat_manager_error") is None, result4)

    # 5. Global path: Chat Manager crashes.
    env5 = build_envelope()
    result5, logs5 = await run_scenario(env5, is_global=True, chat_manager_raises=True)
    check("Global Chat Manager crash: chat_manager_error is the real exception message",
          result5.get("chat_manager_error") == "real simulated Chat Manager crash", result5.get("chat_manager_error"))
    check("Global Chat Manager crash: chat_summary is None (unchanged fail-open behavior)",
          result5.get("chat_summary") is None, result5)
    check("Global Chat Manager crash: turn still produces a real social_response (fails open, doesn't crash the turn)",
          result5.get("social_response") == "a real global response", result5.get("social_response"))
    check("Global Chat Manager crash: real [CHAT MANAGER CRASH] log line present",
          "[CHAT MANAGER CRASH] real simulated Chat Manager crash" in logs5, logs5)

    # 6. Global path: happy path -- chat_manager_error None.
    env6 = build_envelope()
    result6, logs6 = await run_scenario(env6, is_global=True)
    check("Global happy path: chat_manager_error is None", result6.get("chat_manager_error") is None, result6)


    print("\n=== Phase 4 Chat Manager graceful-failure verification ===")
    all_pass = True
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"[{status}] {name}" + (f" -- {detail}" if not ok else ""))
    print(f"\n{len(results)} checks, {'ALL PASS' if all_pass else 'SOME FAILED'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
