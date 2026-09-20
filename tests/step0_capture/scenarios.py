"""
Scenario matrix for the Step 0 golden harness. Every scenario runs REAL Kernel
code with only litellm.completion faked (see harness.py). Inputs are fixed, so
the recorded request lists are deterministic (uuid4 is patched; hounds that
run in parallel threads are compared order-insensitively).
"""
import copy
import importlib.util
import json
import os

from harness import ROOT
from schema.kernel_schema import AgentEnvelope
from core.orchestrator import MasterOrchestrator
from core.coverage import assess_coverage, COVERAGE_SCHEMA
from core.ignition import confirm_launch_intent, LAUNCH_CONFIRM_SCHEMA
from core.requirements import derive_requirements
from core.summarizer import extract_facts
from core.reconcile import reconcile_fact, build_chat_summary
from core.brief import derive_brief
from core.map_summary import summarize_for_map
from core.strike_launch import execute_strike_team_launch
from pods.social.engine import SocialEngine
from pods.synthesis.engine import SynthesisEngine
from pods.strike_team.engine import StrikeEngine
from pods.strike_team.specialist import Specialist
from pods.strike_team.hound import Hound
from pods.maintenance.engine import MaintenanceEngine

FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures", "phase_1_5")

PERSONA = {
    "system_prompt": "You are Ada, a blunt, high-speed co-founder.",
    "archetype": {"mandate": "IDENTITY: THE PARTNER PM. Keep replies under 80 words. One question at a time."},
    "platform": {"mandate": "Every conversation happens inside a project map of phases and milestones."},
    "app_manual": "Fable Coffee is a pour-over subscription app.",
    "global_mission": "Help independent coffee roasters reach loyal subscribers.",
    "exo_brain": "Deep knowledge: single-origin sourcing, roast profiles, subscription churn.",
}

PROJECT_MAP = [
    {"phase": "Phase 1: Foundations", "purpose": "Settle the idea", "milestones": [
        {"id": "m1", "name": "The Big Idea", "status": "DONE", "purpose": "Pin down the concept"},
        {"id": "m2", "name": "Pricing Page", "status": "ACTIVE", "purpose": "Decide pricing tiers"},
    ]},
]

CHAT_SUMMARY = [
    {"id": "f1", "content": "Target customer is small landlords", "type": "fact", "speaker": "user", "turn_index": 0, "status": "current", "bucket": "Core Topic"},
    {"id": "f2", "content": "Pricing is $20 per month", "type": "decision", "speaker": "user", "turn_index": 1, "status": "current", "bucket": "Sub Topics"},
]

HISTORY = [
    {"role": "user", "content": "I want to sell pour-over coffee subscriptions."},
    {"role": "assistant", "content": "Nice. Who is it for?"},
    {"role": "user", "content": "Cafe owners in Fremont, café ☕ 😀 lovers."},
]


def env(**overrides):
    base = dict(
        app_id="app1", project_id="app1", milestone_id="m1",
        milestone_config={"required_questions": ["Who is the customer?", "What is the price?"], "output": "A pricing page"},
        persona_config=copy.deepcopy(PERSONA), knowledge_bricks={"brick_a": "Brick A prose"},
        history=copy.deepcopy(HISTORY),
    )
    base.update(overrides)
    return AgentEnvelope(**base)


SCENARIOS = []


def scenario(name, order_insensitive=False, responses=None):
    def deco(fn):
        SCENARIOS.append({"name": name, "run": fn, "order_insensitive": order_insensitive, "responses": responses})
        return fn
    return deco


# ---------------------------------------------------------------- PM: run_turn

RUN_TURN_CASES = {
    "base": {},
    "physics_open": {"physics_open": True},
    "kaiser": {"kaiser_mandate": "RESEARCH COMPLETE. Present the findings."},
    "gatekeeper_whisper": {"gatekeeper_whisper": "Gate is RED: pricing is unclear."},
    "chat_whisper": {"chat_whisper": "Ask the Director to confirm the audience."},
    "all_signals": {"physics_open": True, "kaiser_mandate": "RESEARCH COMPLETE.", "gatekeeper_whisper": "Gate GREEN.", "chat_whisper": "Confirm audience."},
    "ancestor_chat_summary": {"ancestor_chat_summary": [{"content": "Global agreed audience is small landlords", "type": "fact"}]},
    "compiled_l1_l3": {"compiled_l1": "COMPILED L1 TEXT", "compiled_l3": "COMPILED L3 TEXT"},
    "partner_protocols": {"gatekeeper_whisper": "Gate RED", "chat_whisper": "Confirm",
                          "partner_protocols": [{"source": "Gatekeeper", "content": "RED means blocked."}, {"source": "Chat Manager", "content": "A chat whisper is the top open question."}, {"source": "Keymaster", "content": "inactive protocol"}]},
    "phase_purpose": {"phase_purpose": "This phase settles the core idea."},
    "tool_law": {"tool_law": "CUSTOM BACKEND TOOL LAW"},
    "kitchen_sink": {"physics_open": True, "kaiser_mandate": "RESEARCH COMPLETE.", "gatekeeper_whisper": "Gate GREEN.", "chat_whisper": "Confirm audience.",
                     "ancestor_chat_summary": [{"content": "ancestor fact", "type": "fact"}], "compiled_l1": "COMPILED L1", "compiled_l3": "COMPILED L3",
                     "partner_protocols": [{"source": "Gatekeeper", "content": "RED means blocked."}], "phase_purpose": "Phase purpose.", "tool_law": "CUSTOM TOOL LAW"},
    "unicode": {"history": [{"role": "user", "content": "naïve café ☕ 日本語 😀   line-sep"}], "ancestor_chat_summary": [{"content": "emoji 😀 fact", "type": "fact"}]},
}

for _case, _overrides in RUN_TURN_CASES.items():
    def _make(overrides):
        async def run():
            await SocialEngine.run_turn(env(**overrides))
        return run
    scenario(f"pm.run_turn/{_case}")(_make(_overrides))

# ------------------------------------------------------- PM: run_global_turn

GLOBAL_CASES = {
    "with_project_map": {"project_map": PROJECT_MAP},
    "without_project_map": {},
    "chat_whisper_and_protocol": {"project_map": PROJECT_MAP, "chat_whisper": "Confirm audience.", "partner_protocols": [{"source": "Chat Manager", "content": "A chat whisper is the top open question."}]},
    "compiled_l1_l3": {"project_map": PROJECT_MAP, "compiled_l1": "COMPILED L1", "compiled_l3": "COMPILED L3"},
    "custom_tool_law_no_map": {"tool_law": "CUSTOM TOOL LAW"},
}

for _case, _overrides in GLOBAL_CASES.items():
    def _make(overrides):
        async def run():
            await SocialEngine.run_global_turn(env(**overrides))
        return run
    scenario(f"pm.run_global_turn/{_case}")(_make(_overrides))

# ---------------------------------------------------- PM: run_global_turn_answer

ANSWER_CASES = {
    "default": ({"project_map": PROJECT_MAP}, {}),
    "reply_only": ({"project_map": PROJECT_MAP}, {"allowed_actions": ["reply"]}),
    "reply_completion": ({"project_map": PROJECT_MAP}, {"allowed_actions": ["reply", "completion"]}),
    "dispatch_without_map": ({}, {"allowed_actions": ["reply", "dispatch"]}),
    "retry_full": ({"project_map": PROJECT_MAP}, {"rejected_answer": {"answer_type": "dispatch", "args": {"milestone_id": "m1", "reasoning": "x"}}, "rejection_reason": "m1 is already DONE"}),
    "retry_reason_only": ({"project_map": PROJECT_MAP}, {"rejection_reason": "not allowed"}),
    "custom_tool_law_chat_whisper": ({"project_map": PROJECT_MAP, "tool_law": "CUSTOM TOOL LAW", "chat_whisper": "Confirm."}, {}),
    "compiled": ({"project_map": PROJECT_MAP, "compiled_l1": "COMPILED L1", "compiled_l3": "COMPILED L3"}, {}),
}

for _case, (_env_over, _kw) in ANSWER_CASES.items():
    def _make(env_over, kw):
        async def run():
            await SocialEngine.run_global_turn_answer(env(**env_over), **kw)
        return run
    scenario(f"pm.run_global_turn_answer/{_case}")(_make(_env_over, _kw))

# ------------------------------------------------------ PM: synthesize_dispatch


@scenario("pm.synthesize_dispatch/full")
async def _sd_full():
    await SocialEngine.synthesize_dispatch(copy.deepcopy(PERSONA), "Let's do the pricing page", "On it.", "Pricing Page", "Decide tiers", "DONE", "We chose 3 tiers.")


@scenario("pm.synthesize_dispatch/no_initial_reaction_no_milestone")
async def _sd_min():
    await SocialEngine.synthesize_dispatch(copy.deepcopy(PERSONA), "Go", "", "", "", "DONE", "Result text.")


# ------------------------------------------------------------- Functions

@scenario("gatekeeper.assess_coverage/default_schema")
async def _cov_default():
    assess_coverage(["Who is the customer?", "What is the price?"], copy.deepcopy(CHAT_SUMMARY), "GK L1", "GK L3", "GK SKILL")


@scenario("gatekeeper.assess_coverage/custom_shape_no_facts")
async def _cov_custom():
    assess_coverage(["Q1"], [], "GK L1", None, "", output_shape=dict(COVERAGE_SCHEMA, title="custom"))


@scenario("keymaster.confirm_launch_intent/default_schema")
async def _key_default():
    confirm_launch_intent(copy.deepcopy(HISTORY), l1="KM L1", skill="KM SKILL")


@scenario("keymaster.confirm_launch_intent/custom_shape")
async def _key_custom():
    confirm_launch_intent(copy.deepcopy(HISTORY), l1=None, skill="", output_shape=dict(LAUNCH_CONFIRM_SCHEMA, title="custom"))


@scenario("gate_maker.derive_requirements/default")
async def _req():
    derive_requirements("Decide pricing tiers", {"tiers": "list"}, "GM L1", "GM L3", "GM SKILL")


@scenario("chat_manager.extract_facts/with_prior_facts")
async def _extract():
    extract_facts(copy.deepcopy(HISTORY), required_questions=["Who?"], purpose="Pin down the idea", offset=2,
                  prior_chat_summary=copy.deepcopy(CHAT_SUMMARY), l1="CM L1", l3="CM L3", skill="CM SKILL")


@scenario("chat_manager.extract_facts/minimal")
async def _extract_min():
    extract_facts(copy.deepcopy(HISTORY))


@scenario("chat_manager.reconcile_fact/existing_and_new")
async def _reconcile():
    reconcile_fact(copy.deepcopy(CHAT_SUMMARY), {"content": "Pricing is now $25", "type": "decision", "speaker": "user", "turn_index": 3})


@scenario("chat_manager.build_chat_summary/extract_then_reconcile_per_fact")
async def _chat_summary():
    build_chat_summary(copy.deepcopy(HISTORY), required_questions=["Who?"], purpose="Idea", prior_chat_summary=copy.deepcopy(CHAT_SUMMARY),
                       cursor=1, l1="CM L1", l3="CM L3", skill="CM SKILL", scope_path="app/m1")


@scenario("strike.derive_brief/default")
async def _brief():
    derive_brief("Pin down the concept", copy.deepcopy(CHAT_SUMMARY) + [{"id": "f3", "content": "old", "type": "fact", "speaker": "user", "turn_index": 2, "status": "superseded"}])


@scenario("map_summary.summarize_for_map/default")
async def _map():
    summarize_for_map("A long milestone purpose that needs condensing for the map.")


ARCH = [{"id": "b1", "type": "TEXT", "headline": "Market", "intent_blurb": "size the market"},
        {"id": "b2", "type": "VISUAL_SPEC", "headline": "Logo", "intent_blurb": "logo spec"},
        {"id": "b3", "type": "TEXT", "headline": "Old", "intent_blurb": "archived", "is_archived": True}]
REPORTS = [{"role": "Market Analyst", "content": "Analysis [1]", "sources": {"1": {"title": "S", "url": "https://x"}}}]


@scenario("synthesis.forge_truth/default")
async def _forge():
    await SynthesisEngine.forge_truth(copy.deepcopy(REPORTS), {"research_architecture": copy.deepcopy(ARCH)})


@scenario("synthesis.forge_truth/no_architecture")
async def _forge_none():
    await SynthesisEngine.forge_truth(copy.deepcopy(REPORTS), {})


IDENTITY = {"l0_mother": "ARCHETYPE: analyst", "system_prompt": "Voice: dry.", "exo_brain": "KB: markets"}


@scenario("strike.specialist_questions/with_identity")
async def _sq():
    Specialist.generate_questions("Market Analyst", "The settled brief.", identity=copy.deepcopy(IDENTITY))


@scenario("strike.specialist_questions/no_identity")
async def _sq_none():
    Specialist.generate_questions("Market Analyst", "The settled brief.")


@scenario("strike.specialist_analyze/with_identity")
async def _sa():
    Specialist.analyze("Market Analyst", {"raw_research": "raw findings", "sources": {"1": {}, "2": {}}}, identity=copy.deepcopy(IDENTITY))


@scenario("strike.hound/hunt")
async def _hound():
    Hound.hunt("What is the specialty coffee market size in Seattle?")


@scenario("maintenance.compress_truth/direct")
async def _compress():
    await MaintenanceEngine.compress_truth(["old brick one", "old brick two"])


# ---------------------------------------------- Strike Team (multi-call chains)

SPECIALISTS = ["Market Analyst", {"role_name": "Brand Strategist", "identity": copy.deepcopy(IDENTITY)}]


@scenario("strike.run_industrial_strike/two_specialists", order_insensitive=True)
async def _strike():
    e = env(milestone_config={"specialists": copy.deepcopy(SPECIALISTS)})
    await StrikeEngine.run_industrial_strike(e, "The settled brief text.")


@scenario("strike.execute_strike_team_launch/full_chain", order_insensitive=True)
async def _launch():
    await execute_strike_team_launch("app1", "Pin down the concept", copy.deepcopy(CHAT_SUMMARY),
                                     {"specialists": copy.deepcopy(SPECIALISTS), "research_architecture": copy.deepcopy(ARCH), "output": "The concept"})


# ---------------------------------------------------- Full turns (process_turn)

def _load_phase15_helpers():
    path = os.path.join(ROOT, "tests", "phase_1_5", "test_trigger_sequencing_regression.py")
    spec = importlib.util.spec_from_file_location("phase15_regression", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fixture(name):
    with open(os.path.join(FIXTURE_DIR, name)) as f:
        return json.load(f)


def _enrich(envelope):
    envelope.persona_config = copy.deepcopy(PERSONA)
    envelope.gatekeeper_mandate = "GK ARCHETYPE MANDATE"
    envelope.gatekeeper_skill = "GK SKILL"
    envelope.keymaster_mandate = "KM ARCHETYPE MANDATE"
    envelope.keymaster_skill = "KM SKILL"
    envelope.chat_manager_mandate = "CM ARCHETYPE MANDATE"
    envelope.chat_manager_skill = "CM SKILL"
    return envelope


def _replay_responses(kernel_result):
    log = kernel_result.get("trigger_log") or []
    gk = next((e for e in log if e["trigger_id"] == "gatekeeper_assessment"), None)
    km = next((e for e in log if e["trigger_id"] == "keymaster_confirmation"), None)
    responses = {}
    if gk and gk.get("outcome") and "gate_status" in (gk["outcome"] or {}):
        responses["coverage"] = {"assessments": gk["outcome"].get("assessments") or [], "gate_status": gk["outcome"]["gate_status"], "whisper": gk["outcome"].get("whisper") or ""}
    if km and km.get("outcome") is not None:
        responses["ignition"] = {"confirmed": bool(km["outcome"].get("confirmed"))}
    return responses


def _register_replay(name, fixture_file, key, top_level=True):
    fx = _fixture(fixture_file)
    src = fx if top_level else fx[key]
    turn = src[key] if top_level else src
    app_id, milestone_id, entities = src.get("app_id", fx.get("app_id")), src.get("milestone_id", fx.get("milestone_id")), src.get("entities", fx.get("entities"))
    responses = _replay_responses(turn["kernel_result"])

    async def run():
        helpers = _load_phase15_helpers()
        envelope = _enrich(helpers.build_envelope(app_id, milestone_id, entities, turn["snapshot_before"]))
        after = (turn.get("snapshot_after") or {}).get("milestone_doc")
        if after:
            envelope.milestone_config = helpers.build_milestone_config(entities, milestone_id, after)
        await MasterOrchestrator.process_turn(envelope, turn["trigger_message"], is_global=False)

    SCENARIOS.append({"name": name, "run": run, "order_insensitive": True, "responses": responses})


for _k in ("turn_1", "turn_2", "turn_3"):
    _register_replay(f"process_turn/gatekeeper_keymaster_real_turns/{_k}", "gatekeeper_keymaster_real_turns.json", _k)
for _k in ("branch_5_no_required_questions", "branch_6_already_fired"):
    _register_replay(f"process_turn/gatekeeper_skip_branches/{_k}", "gatekeeper_skip_branches_real_turns.json", _k, top_level=False)
_register_replay("process_turn/strike_team_launch_real_turn/turn_1", "strike_team_launch_real_turn.json", "turn_1")


@scenario("process_turn/global_with_project_map")
async def _pt_global():
    e = _enrich(env(project_map=PROJECT_MAP, milestone_id=None))
    await MasterOrchestrator.process_turn(e, "Let's start on the pricing page", is_global=True)


@scenario("process_turn/global_dispatched_milestone_gate_loop", order_insensitive=True,
          responses={"coverage": {"assessments": [{"question": "Who is the customer?", "status": "GREEN", "is_satisfied": True}], "gate_status": "GREEN", "whisper": "Ready."}})
async def _pt_global_gate():
    e = _enrich(env(project_map=PROJECT_MAP, active_milestone_already_fired=False,
                    milestone_config={"required_questions": ["Who is the customer?"], "output": "Concept", "specialists": ["Market Analyst"], "research_architecture": copy.deepcopy(ARCH)}))
    await MasterOrchestrator.process_turn(e, "Yes, go ahead and launch it", is_global=True)


@scenario("process_turn/task_scoped_no_required_questions_clock_compression")
async def _pt_clock():
    bricks = {f"brick_{i}": ("x" * 4500) + f" end{i}" for i in range(5)}
    e = _enrich(env(milestone_config={"output": "x"}, knowledge_bricks=bricks))
    await MasterOrchestrator.process_turn(e, "Anything new?", is_global=False)
