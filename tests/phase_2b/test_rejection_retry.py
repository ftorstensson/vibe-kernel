"""
Phase 2b (doc-16): Validator legality checks + bounded retry.

Confirmed directly against doc-13 (sections 4 and 6) before building
anything: the Validator, legality checking, and the retry loop (including
its own count/cap -- "a build parameter, not an architecture decision")
are entirely Backend's job. Kernel never checks whether an Answer is legal
and never loops internally -- section 6 rules out an in-call loop "by
construction" (Kernel is handed a Briefing, answers once, forgets
everything immediately). So Kernel's only real piece of Phase 2b is
accepting a rejection ("the rejection reason appended as a fresh L5
Signal", doc-13 section 4) as two new optional parameters on the existing
Phase 2a endpoint -- SocialEngine.run_global_turn_answer(rejected_answer=,
rejection_reason=) / POST /kernel/agents/run_global_turn_answer's matching
request fields. No new endpoint, no legality logic, no retry-count
tracking of any kind on Kernel's side.

The refusal branch ("a model can legitimately decline to answer at all...
goes straight to graceful failure, not another retry") is a genuinely
separate, still-open question -- doc-13 has no defined mechanism for it,
under discussion with Backend/PM14, not built here.

Two sections, same convention as tests/phase_2a/: defensive unit tests
(no cost), then real-API verification (real, cheap Gemini calls, run
deliberately).
"""
import asyncio
import sys
from unittest.mock import patch

sys.path.insert(0, "/Users/fred/vibe-kernel/.claude/worktrees/hungry-booth-3d3e83")

from schema.kernel_schema import AgentEnvelope
from pods.social.engine import SocialEngine, DEFAULT_TOOL_LAW
import pods.social.engine as engine_mod

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


class _FakeReplyResponse:
    text = ""
    tool_calls = [{"name": "reply", "args": {"message": "ok"}}]


class _FakeModel:
    def __init__(self):
        self.captured = None

    def generate_content(self, work_order, generation_config=None, tools=None, tool_choice=None):
        self.captured = work_order
        return _FakeReplyResponse()


async def run_unit_tests():
    # No rejection fields passed at all -- byte-identical to Phase 2a's
    # own behavior before this pair of parameters existed (no REJECTED
    # ANSWER/REJECTION REASON block in the Signal at all).
    fake_no_rejection = _FakeModel()
    with patch.object(engine_mod.AgentFactory, "get_partner_pm", return_value=(fake_no_rejection, None)):
        env = AgentEnvelope(app_id="a", project_id="a", milestone_config={}, persona_config={})
        await SocialEngine.run_global_turn_answer(env)
    check("no rejection fields: no REJECTED ANSWER/REJECTION REASON block appears at all",
          "REJECTED ANSWER" not in str(fake_no_rejection.captured) and "REJECTION REASON" not in str(fake_no_rejection.captured),
          fake_no_rejection.captured)

    # Both rejection fields provided -- real content reaches the composed
    # Signal, alongside (not instead of) the base tool_law content.
    fake_with_rejection = _FakeModel()
    with patch.object(engine_mod.AgentFactory, "get_partner_pm", return_value=(fake_with_rejection, None)):
        env2 = AgentEnvelope(app_id="a", project_id="a", milestone_config={}, persona_config={})
        await SocialEngine.run_global_turn_answer(
            env2,
            rejected_answer={"answer_type": "dispatch", "args": {"milestone_id": "m1", "reasoning": "why"}},
            rejection_reason="m1 is already complete, cannot dispatch to it again.",
        )
    captured_str = str(fake_with_rejection.captured)
    check("rejected_answer content reaches the composed Signal", "'milestone_id': 'm1'" in captured_str, captured_str)
    check("rejection_reason content reaches the composed Signal", "already complete" in captured_str, captured_str)
    check("tool_law still present alongside the rejection Signal, not replaced by it",
          DEFAULT_TOOL_LAW in captured_str, captured_str)

    # rejection_reason alone, no rejected_answer -- still composes
    # something real rather than silently no-op'ing.
    fake_reason_only = _FakeModel()
    with patch.object(engine_mod.AgentFactory, "get_partner_pm", return_value=(fake_reason_only, None)):
        env3 = AgentEnvelope(app_id="a", project_id="a", milestone_config={}, persona_config={})
        await SocialEngine.run_global_turn_answer(env3, rejection_reason="a real reason with no echoed answer")
    check("rejection_reason alone (no rejected_answer) still composes a real Signal block",
          "a real reason with no echoed answer" in str(fake_reason_only.captured), fake_reason_only.captured)


PROJECT_MAP = [{"phase": "Launch", "milestones": [
    {"id": "m1", "name": "Landing Page Copy", "status": "ACTIVE", "purpose": "Write the copy."},
    {"id": "m2", "name": "Pricing Page", "status": "ACTIVE", "purpose": "Design pricing."},
]}]


async def run_real_api_test():
    base = dict(
        app_id="a", project_id="a", milestone_config={}, persona_config={"system_prompt": "Direct, asks for concrete specifics."},
        knowledge_bricks={}, project_map=PROJECT_MAP,
    )
    history = [{"role": "user", "content": "let's work on the landing page copy"}]

    env1 = AgentEnvelope(**base, history=list(history))
    first = await SocialEngine.run_global_turn_answer(env1)
    check("real API: first call dispatches to a real milestone",
          first["answer_type"] == "dispatch" and first["args"].get("milestone_id") in ("m1", "m2"), first)

    # Real, honest finding from running this multiple times, not a single
    # lucky sample: the model does NOT reliably comply with a single
    # rejection. Across 5 real trials during development, only 2 changed
    # their answer -- 3 repeated the exact rejected dispatch verbatim.
    # Asserting "must comply" here would be a flaky test masquerading as a
    # mechanism check -- compliance is a genuine model-judgment question,
    # not something the wiring controls. What IS reliably true, and what
    # this actually asserts: the Signal reaches the model and a real,
    # well-formed Answer comes back every time, never a crash or a
    # malformed response. The compliance RATE is reported as real data,
    # not pass/fail -- it's exactly why doc-13 specifies a retry CAP
    # greater than one with a graceful-failure fallback for exhausted
    # retries, not a single "correct and done" attempt. Worth surfacing
    # to Backend/PM14 as real input to what that cap should actually be,
    # not something to hide behind a test that only asserts the happy case.
    trials = 4
    complied = 0
    for _ in range(trials):
        env2 = AgentEnvelope(**base, history=list(history))
        retried = await SocialEngine.run_global_turn_answer(
            env2,
            rejected_answer=first,
            rejection_reason=f"Milestone {first['args'].get('milestone_id')} is already complete and cannot be dispatched to again. Pick a different real action.",
        )
        same_illegal_dispatch = (
            retried["answer_type"] == "dispatch"
            and retried["args"].get("milestone_id") == first["args"].get("milestone_id")
        )
        check(f"real API: retried call {_ + 1}/{trials} returns a real, well-formed Answer (not a crash)",
              retried.get("answer_type") in ("reply", "dispatch", "completion"), retried)
        if not same_illegal_dispatch:
            complied += 1
    print(f"\n[DATA, not pass/fail] single-attempt rejection compliance: {complied}/{trials} trials changed their answer "
          f"rather than repeating the exact rejected dispatch -- real signal for what Backend's retry cap should be, "
          f"not a mechanism defect.")


async def main():
    await run_unit_tests()
    await run_real_api_test()

    print("\n=== Phase 2b rejection-retry verification ===")
    all_pass = True
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"[{status}] {name}" + (f" -- {detail}" if not ok else f" -- {detail}"))
    print(f"\n{len(results)} checks, {'ALL PASS' if all_pass else 'SOME FAILED'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
