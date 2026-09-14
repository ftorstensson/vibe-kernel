"""
Phase 2a (doc-16): the Orchestrator's Answer as a real structured choice --
Reply | Dispatch | Completion, native tool calls.

Two sections, run together but genuinely different in kind:
1. Defensive-path unit tests (no cost, no network) -- resolve_orchestrator_
   answer()'s own handling of a multi-tool-call or zero-tool-call response,
   cases a real model won't reliably produce on demand.
2. Real-API verification (real, cheap Gemini 2.5 Flash calls -- run
   deliberately, same convention as lab/test_clock.py, not wired into any
   CI-style automatic suite) -- confirms the actual mechanism against real
   model behavior: exactly one clean tool call, zero accompanying prose,
   across varied realistic scenarios, plus the allowed_actions gating and
   the dispatch-only-with-a-real-project_map guard working end-to-end
   through the real SocialEngine.run_global_turn_answer() and the real
   /kernel/agents/run_global_turn_answer endpoint handler.

Why real calls matter here specifically: doc-16's own cited mechanism
(parallel_tool_calls=False) turned out not to work for Gemini via litellm
once more than one tool is declared (confirmed against litellm's own
Vertex/Gemini adapter source) -- a mocked test would never have caught
that, since a mock just returns whatever it's told to. tool_choice=
"required" is the real, verified replacement; this file is the evidence,
not just an assertion.
"""
import asyncio
import sys
from types import SimpleNamespace

sys.path.insert(0, "/Users/fred/vibe-kernel/.claude/worktrees/hungry-booth-3d3e83")

from core.orchestrator_answer import resolve_orchestrator_answer
from core.agent_factory import LiteLLMModel, GenerationConfig
from core.orchestrator_answer import REPLY_TOOL, COMPLETION_TOOL
from pods.social.engine import START_MILESTONE_WORK_TOOL, SocialEngine
from schema.kernel_schema import AgentEnvelope
import main as main_mod
from schema.kernel_schema import GlobalAgentAnswerRequest

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


async def run_defensive_unit_tests():
    r1 = resolve_orchestrator_answer(SimpleNamespace(text="", tool_calls=[{"name": "reply", "args": {"message": "hi"}}]))
    check("single tool call normalizes correctly", r1 == {"answer_type": "reply", "args": {"message": "hi"}}, r1)

    r2 = resolve_orchestrator_answer(SimpleNamespace(text="", tool_calls=[
        {"name": "start_milestone_work", "args": {"milestone_id": "m1", "reasoning": "why"}},
        {"name": "reply", "args": {"message": "also this"}},
    ]))
    check("multiple tool calls: only the first is used, and normalized to 'dispatch'",
          r2 == {"answer_type": "dispatch", "args": {"milestone_id": "m1", "reasoning": "why"}}, r2)

    r3 = resolve_orchestrator_answer(SimpleNamespace(text="fallback text", tool_calls=[]))
    check("zero tool calls fails open to reply with raw text", r3 == {"answer_type": "reply", "args": {"message": "fallback text"}}, r3)

    r4 = resolve_orchestrator_answer(SimpleNamespace(text=None, tool_calls=None))
    check("zero tool calls and no text -- fails open to empty reply, no crash", r4 == {"answer_type": "reply", "args": {"message": ""}}, r4)

    r5 = resolve_orchestrator_answer(SimpleNamespace(text="", tool_calls=[{"name": "start_milestone_work", "args": {"milestone_id": "m1", "reasoning": "why"}}]))
    check("dispatch's real tool name (start_milestone_work) normalizes to answer_type='dispatch'",
          r5["answer_type"] == "dispatch", r5)

    # Real correction, caught by Backend before this shipped: an earlier
    # draft dropped tool_law entirely, reasoning that tool_choice=
    # "required" makes the generic "you have no callable tools" framing
    # wrong -- true, but registry_docs/tool_law is real, Backend-
    # maintained, safety-critical content, not just tool-mechanics text.
    # Confirms Backend's real content is composed ALONGSIDE the new
    # tool-choice-specific instruction, never silently dropped.
    from unittest.mock import patch
    import pods.social.engine as engine_mod

    class _FakeReplyResponse:
        text = ""
        tool_calls = [{"name": "reply", "args": {"message": "ok"}}]

    class _FakeModel:
        def __init__(self):
            self.captured = None

        def generate_content(self, work_order, generation_config=None, tools=None, tool_choice=None):
            self.captured = work_order
            return _FakeReplyResponse()

    async def _check_tool_law():
        fake_with_law = _FakeModel()
        with patch.object(engine_mod.AgentFactory, "get_partner_pm", return_value=(fake_with_law, None)):
            env = AgentEnvelope(app_id="a", project_id="a", milestone_config={}, persona_config={}, tool_law="REAL BACKEND SAFETY CONTENT XYZ")
            await SocialEngine.run_global_turn_answer(env)
        check("real Backend tool_law content reaches the composed prompt, not dropped",
              "REAL BACKEND SAFETY CONTENT XYZ" in str(fake_with_law.captured), fake_with_law.captured)
        check("real Backend tool_law content composed ALONGSIDE the tool-choice instruction, not instead of it",
              "must respond by calling exactly one" in str(fake_with_law.captured), fake_with_law.captured)

        fake_default = _FakeModel()
        with patch.object(engine_mod.AgentFactory, "get_partner_pm", return_value=(fake_default, None)):
            env2 = AgentEnvelope(app_id="a", project_id="a", milestone_config={}, persona_config={})
            await SocialEngine.run_global_turn_answer(env2)
        from pods.social.engine import DEFAULT_TOOL_LAW
        check("no tool_law provided: falls back to the real DEFAULT_TOOL_LAW text",
              DEFAULT_TOOL_LAW in str(fake_default.captured), fake_default.captured)

    await _check_tool_law()


PROJECT_MAP = [{"phase": "Launch", "milestones": [{"id": "m1", "name": "Landing Page Copy", "status": "ACTIVE", "purpose": "Write the copy."}]}]


async def run_real_api_tests():
    model = LiteLLMModel("vertex_ai/gemini-2.5-flash", tools=[REPLY_TOOL, START_MILESTONE_WORK_TOOL, COMPLETION_TOOL])
    config = GenerationConfig(temperature=0.0)
    scenarios = [
        ("simple greeting", "Director says: hey, how's it going?"),
        ("clear dispatch", "PROJECT MAP:\n- milestone_id=m1, name=Landing Page Copy, status=ACTIVE\n\nDirector says: yeah let's start on the landing page copy now"),
        ("ambiguous thanks", "Director says: thanks, that all sounds good, appreciate the update!"),
        ("clear question", "Director says: what's the current status of the audit?"),
        ("milestone truly finished", "You are wrapping up the 'Rotation Schedule Audit' milestone. All required questions have been answered and the final schedule was recorded. Nothing further is needed on this milestone."),
        ("vague, no map", "Director says: ok"),
    ]
    for name, prompt in scenarios:
        response = model.generate_content(prompt, generation_config=config, tool_choice="required")
        answer = resolve_orchestrator_answer(response)
        num_calls = len(response.tool_calls or [])
        has_content = bool(response.text)
        clean = num_calls == 1 and not has_content
        check(f"real API [{name}]: exactly one clean tool call, no prose", clean,
              f"answer_type={answer['answer_type']!r} tool_calls={num_calls} had_prose={has_content}")

    base_kwargs = dict(
        app_id="a", project_id="a", milestone_config={}, persona_config={"system_prompt": "Direct, asks for concrete specifics."},
        knowledge_bricks={},
    )

    env1 = AgentEnvelope(**base_kwargs, history=[{"role": "user", "content": "yeah let's start on the landing page copy now"}], project_map=PROJECT_MAP)
    answer1 = await SocialEngine.run_global_turn_answer(env1)
    check("default allowed_actions + real project_map: dispatch reachable, normalized name, real milestone_id",
          answer1["answer_type"] == "dispatch" and answer1["args"].get("milestone_id") == "m1", answer1)

    env2 = AgentEnvelope(**base_kwargs, history=[{"role": "user", "content": "yeah let's start on the landing page copy now"}], project_map=[])
    answer2 = await SocialEngine.run_global_turn_answer(env2)
    check("default allowed_actions, no project_map: dispatch never offered, falls back to reply",
          answer2["answer_type"] == "reply", answer2)

    env3 = AgentEnvelope(**base_kwargs, history=[{"role": "user", "content": "great, that's everything for this milestone"}], project_map=[])
    answer3 = await SocialEngine.run_global_turn_answer(env3, allowed_actions=["reply", "completion"])
    check("completion explicitly allowed: real completion or reply, never dispatch (not offered)",
          answer3["answer_type"] in ("reply", "completion"), answer3)

    env4 = AgentEnvelope(**base_kwargs, history=[{"role": "user", "content": "yeah let's start on the landing page copy now"}], project_map=PROJECT_MAP)
    answer4 = await SocialEngine.run_global_turn_answer(env4, allowed_actions=["reply"])
    check("allowed_actions=['reply'] only: always reply, even with dispatch-shaped intent and a real project_map",
          answer4["answer_type"] == "reply", answer4)

    # Full round trip through the actual FastAPI endpoint handler, not just
    # SocialEngine directly -- confirms request/response schema wiring too.
    req = GlobalAgentAnswerRequest(
        app_id="a", project_id="a", persona_config={"system_prompt": "Direct, asks for concrete specifics."},
        history=[{"role": "user", "content": "yeah let's start on the landing page copy now"}],
        project_map=PROJECT_MAP,
    )
    endpoint_resp = await main_mod.invoke_agent_run_global_turn_answer(req)
    check("real endpoint round trip: /kernel/agents/run_global_turn_answer returns a real dispatch answer",
          endpoint_resp["answer_type"] == "dispatch" and endpoint_resp["args"].get("milestone_id") == "m1", endpoint_resp)


async def main():
    await run_defensive_unit_tests()
    await run_real_api_tests()

    print("\n=== Phase 2a orchestrator-answer verification ===")
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
