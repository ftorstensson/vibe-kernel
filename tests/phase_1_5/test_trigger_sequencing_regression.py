"""
Phase 1.5 regression safety net: replays real historical turns (fixtures
captured by Backend from real production/test-app data, see
tests/fixtures/phase_1_5/) through the REAL core/orchestrator.py +
core/triggers.py sequencing code, mocking only the genuine non-deterministic
I/O boundaries (assess_coverage, confirm_launch_intent, build_chat_summary,
derive_brief, StrikeEngine.run_industrial_strike, SynthesisEngine.forge_truth,
SocialEngine.run_turn) with each turn's own real historical output.

CORRECTION (found after this file's first merge, PR #29): the initial
version of this harness did NOT mock SocialEngine.run_turn -- process_turn()
calls it unconditionally at the end of BOTH its branches (whether Strike
Team launched or not), so every one of the 8 scenario replays was making a
real, live, paid model call this docstring's own description never
accounted for. Confirmed by grep (core/orchestrator.py lines calling
SocialEngine.run_turn) before fixing, not assumed. Fixed by adding it to
the mock boundary, stubbed to return that turn's own real historical
social_response -- same "replay the exact recorded value" pattern already
used for gate_status/whisper/confirmed, so the fix doesn't change what's
being verified, only removes an unintended real call this test was never
supposed to make.

This deliberately does NOT reimplement or hand-simulate the sequencing logic
-- it calls MasterOrchestrator.process_turn() for real, so what's actually
under test is whether the real GATEKEEPER_ASSESSMENT/KEYMASTER_CONFIRMATION/
STRIKE_TEAM_LAUNCH trigger chain, given the exact same historical inputs and
the exact same historical leaf-call outputs, reproduces the exact same
gating decisions (condition_result/fired/skip_reason per trigger, and what
propagates to the next trigger's condition) that the real turn actually
produced. This is the pre-migration baseline: once Backend's own
reimplementation exists (calling Kernel's individual endpoints one at a
time instead of this one evaluate_triggers chain), the same fixtures are
the reference to check it against -- "identical" there means identical
gating decisions, not a byte-identical trace shape, since Backend's own
trace format won't literally be this dict shape.

Required_questions reconstruction: Backend's data model has no flat
required_questions field -- it's derived from `milestone_input`-type SLOT
entities parented to the milestone (confirmed against the fixtures directly,
then confirmed for real against Backend's own live kernel_projection.py
source: entity_type=="SLOT", parent_id==milestone_id, slot_type==
"milestone_input", not archived, sorted by `order`, text from
data_payload.text). Zero such SLOTs produces the no_required_questions
branch. When a snapshot's own milestone_doc is present (post-processing
state, carrying Coverage's own resolved required_questions/specialists/
research_architecture), that's preferred over re-deriving from entities,
matching Backend's own real resolve-then-persist order.

Known gap, not covered by any of the 8 fixtures: this is the STATIC half
only. Backend's own resolve_required_questions() equivalent also has
derived_requirements -- Gate Maker's own AI-derived output, which
core/coverage.py's real resolve_required_questions() prefers over the
static SLOT-derived list when present. None of these 8 fixtures ever ran
Gate Maker, so that precedence is real but untested here. A future fixture
exercising it would need to distinguish "no required_questions because
none were authored" from "no required_questions because derived_requirements
hasn't been (re-)run yet" -- not the same state, not yet covered."""
import asyncio
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from schema.kernel_schema import AgentEnvelope
from core.orchestrator import MasterOrchestrator
import core.orchestrator as orchestrator_mod
import core.triggers as triggers_mod

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "phase_1_5")

GATING_FIELDS = ("trigger_id", "condition_result", "fired")


def required_questions_from_entities(entities, milestone_id):
    return [
        e["data_payload"]["text"]
        for e in entities
        if e.get("entity_type") == "SLOT"
        and e.get("slot_type") == "milestone_input"
        and e.get("parent_id") == milestone_id
    ]


def build_milestone_config(entities, milestone_id, milestone_doc):
    milestone_entity = next(e for e in entities if e["system_id"] == milestone_id)
    if milestone_doc:
        required_questions = milestone_doc.get("required_questions") or required_questions_from_entities(entities, milestone_id)
        specialists = milestone_doc.get("specialists", [])
        research_architecture = milestone_doc.get("research_architecture", [])
    else:
        required_questions = required_questions_from_entities(entities, milestone_id)
        specialists = []
        research_architecture = []
    return {
        "required_questions": required_questions,
        "derived_requirements": None,
        "output": milestone_entity.get("output", ""),
        "specialists": specialists,
        "research_architecture": research_architecture,
    }


def build_envelope(app_id, milestone_id, entities, snapshot_before):
    pm = snapshot_before["project_manifest"]
    milestone_doc = snapshot_before.get("milestone_doc")
    return AgentEnvelope(
        app_id=app_id,
        project_id=app_id,
        milestone_id=milestone_id,
        milestone_config=build_milestone_config(entities, milestone_id, milestone_doc),
        persona_config={},
        knowledge_bricks=dict(pm.get("knowledge_bricks") or {}),
        history=list(pm.get("chat_history") or []),
        chat_summary=list(pm.get("chat_summary") or []),
        chat_summary_cursor=pm.get("chat_summary_cursor") or 0,
        physics_open=pm.get("physics_open") or False,
    )


def find_entry(trigger_log, trigger_id):
    return next((e for e in trigger_log if e["trigger_id"] == trigger_id), None)


async def replay_scenario(name, app_id, milestone_id, entities, trigger_message, snapshot_before, kernel_result):
    envelope = build_envelope(app_id, milestone_id, entities, snapshot_before)
    expected_log = kernel_result["trigger_log"]

    gatekeeper_entry = find_entry(expected_log, "gatekeeper_assessment")
    keymaster_entry = find_entry(expected_log, "keymaster_confirmation")

    def fake_assess_coverage(*args, **kwargs):
        return gatekeeper_entry["outcome"]

    def fake_confirm_launch_intent(*args, **kwargs):
        return bool(keymaster_entry["outcome"]["confirmed"]) if keymaster_entry and keymaster_entry.get("outcome") else False

    def fake_build_chat_summary(*args, **kwargs):
        return {
            "chat_whisper": kernel_result.get("chat_whisper"),
            "chat_summary": kernel_result.get("chat_summary") or [],
            "chat_summary_cursor": kernel_result.get("chat_summary_cursor") or 0,
        }

    def fake_derive_brief(*args, **kwargs):
        return {"identity_narrative": "[stubbed -- sequencing test, not content test]", "founding_voice": []}

    async def fake_run_industrial_strike(*args, **kwargs):
        return {"reports": [], "treasure_chest": {}}

    async def fake_forge_truth(*args, **kwargs):
        return {"bricks": dict(kernel_result.get("data_patch") or {}), "appendix": list(kernel_result.get("appendix") or [])}

    async def fake_run_turn(*args, **kwargs):
        return kernel_result.get("social_response") or "[stubbed -- sequencing test, not content test]"

    with patch.object(triggers_mod, "assess_coverage", side_effect=fake_assess_coverage) as m_coverage, \
         patch.object(triggers_mod, "confirm_launch_intent", side_effect=fake_confirm_launch_intent) as m_confirm, \
         patch.object(orchestrator_mod, "build_chat_summary", side_effect=fake_build_chat_summary), \
         patch.object(triggers_mod, "derive_brief", side_effect=fake_derive_brief), \
         patch.object(triggers_mod.StrikeEngine, "run_industrial_strike", side_effect=fake_run_industrial_strike), \
         patch.object(triggers_mod.SynthesisEngine, "forge_truth", side_effect=fake_forge_truth), \
         patch.object(orchestrator_mod.SocialEngine, "run_turn", side_effect=fake_run_turn) as m_run_turn:
        result = await MasterOrchestrator.process_turn(envelope, trigger_message, is_global=False)

    return {
        "name": name,
        "result_log": result["trigger_log"],
        "expected_log": expected_log,
        "mocked_coverage_calls": m_coverage.call_count,
        "mocked_confirm_calls": m_confirm.call_count,
        "mocked_run_turn_calls": m_run_turn.call_count,
        "envelope_after": envelope,
    }


def run_turn_call_checks(r):
    """process_turn() calls SocialEngine.run_turn exactly once at the end of
    every real turn (both branches -- Strike Team launched or not). Checking
    call_count == 1 confirms the mock is actually being exercised (not
    silently unused because a patch target was wrong), which is exactly the
    class of mistake that let the original unmocked-run_turn bug ship."""
    return [(f"{r['name']}: SocialEngine.run_turn called exactly once (mocked)", r["mocked_run_turn_calls"] == 1, r["mocked_run_turn_calls"])]


def compare_trigger_logs(name, result_log, expected_log):
    checks = []
    if len(result_log) != len(expected_log):
        checks.append((f"{name}: trigger_log length matches ({len(expected_log)})", False,
                        f"got {len(result_log)}: {[e['trigger_id'] for e in result_log]}"))
        return checks
    for got, want in zip(result_log, expected_log):
        for field in GATING_FIELDS:
            ok = got.get(field) == want.get(field)
            checks.append((f"{name}: {want['trigger_id']}.{field}", ok, f"got={got.get(field)!r} want={want.get(field)!r}"))
        got_skip = got.get("skip_reason")
        want_skip = want.get("skip_reason")
        checks.append((f"{name}: {want['trigger_id']}.skip_reason", got_skip == want_skip, f"got={got_skip!r} want={want_skip!r}"))
        got_outcome = got.get("outcome")
        want_outcome = want.get("outcome")
        checks.append((f"{name}: {want['trigger_id']}.outcome echoes historical value", got_outcome == want_outcome,
                        f"got={got_outcome!r} want={want_outcome!r}"))
    return checks


async def main():
    all_checks = []

    with open(os.path.join(FIXTURE_DIR, "gatekeeper_keymaster_real_turns.json")) as f:
        gk = json.load(f)
    for turn_key in ("turn_1", "turn_2", "turn_3"):
        t = gk[turn_key]
        r = await replay_scenario(
            f"gatekeeper_keymaster_real_turns/{turn_key}",
            gk["app_id"], gk["milestone_id"], gk["entities"],
            t["trigger_message"], t["snapshot_before"], t["kernel_result"],
        )
        all_checks += compare_trigger_logs(r["name"], r["result_log"], r["expected_log"])
        all_checks += run_turn_call_checks(r)

    with open(os.path.join(FIXTURE_DIR, "gatekeeper_skip_branches_real_turns.json")) as f:
        skip = json.load(f)
    for branch_key in ("branch_5_no_required_questions", "branch_6_already_fired"):
        b = skip[branch_key]
        r = await replay_scenario(
            f"gatekeeper_skip_branches/{branch_key}",
            b["app_id"], b["milestone_id"], b["entities"],
            b["trigger_message"], b["snapshot_before"], b["kernel_result"],
        )
        all_checks += compare_trigger_logs(r["name"], r["result_log"], r["expected_log"])
        all_checks += run_turn_call_checks(r)

    with open(os.path.join(FIXTURE_DIR, "strike_team_launch_real_turn.json")) as f:
        st = json.load(f)
    t = st["turn_1"]
    r = await replay_scenario(
        "strike_team_launch_real_turn/turn_1",
        st["app_id"], st["milestone_id"], st["entities"],
        t["trigger_message"], t["snapshot_before"], t["kernel_result"],
    )
    all_checks += compare_trigger_logs(r["name"], r["result_log"], r["expected_log"])
    all_checks += run_turn_call_checks(r)
    # Bonus check beyond trigger_log itself: the real side effect a launch
    # must produce -- envelope.knowledge_bricks actually updated with the
    # (stubbed) bricks, matching how a real launch's data_patch reaches
    # Backend's own ledger.
    all_checks.append((
        "strike_team_launch_real_turn/turn_1: envelope.knowledge_bricks updated after launch",
        bool(r["envelope_after"].knowledge_bricks),
        r["envelope_after"].knowledge_bricks,
    ))

    print("\n=== Phase 1.5 trigger-sequencing regression results ===")
    all_pass = True
    for name, ok, detail in all_checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"[{status}] {name}" + (f" -- {detail}" if not ok else ""))

    print(f"\n{len(all_checks)} checks, {'ALL PASS' if all_pass else 'SOME FAILED'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
