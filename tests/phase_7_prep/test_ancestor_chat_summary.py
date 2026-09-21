"""
Phase 7 prep (doc-16): a new, additive, guarded field -- ancestor_chat_summary --
on AgentEnvelope/AgentTurnRequest, letting Backend send a filtered, ordered
ancestor-scope (Global/parent-Phase) view of chat_summary facts alongside the
milestone's own separate chat_summary, replacing a one-time destructive copy.

Truth-shaped (doc-13 L6/Memory), not Signal -- composed into pm_truth by
run_turn, never pm_signal_lines. Absent/empty is the real, common case (every
turn before Backend starts sending this) -- confirmed here as a genuine no-op,
same discipline as every other optional ingredient in this function.
"""
import sys
sys.path.insert(0, "/Users/fred/vibe-kernel/.claude/worktrees/hungry-booth-3d3e83")

from unittest.mock import patch, MagicMock

from schema.kernel_schema import AgentEnvelope
from pods.social.engine import SocialEngine

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def build_envelope(**overrides):
    base = dict(
        app_id="a", project_id="a", milestone_config={}, persona_config={},
        knowledge_bricks={}, history=[],
    )
    base.update(overrides)
    return AgentEnvelope(**base)


async def run_and_capture_prompt(envelope):
    captured = {}

    def fake_generate_content(contents, generation_config=None, **kwargs):
        captured["prompt"] = contents[0]
        response = MagicMock()
        response.text = "ok"
        return response

    with patch("pods.social.engine.get_clean_text", return_value="ok"), \
         patch("pods.social.engine.AgentFactory.get_partner_pm", return_value=(MagicMock(generate_content=fake_generate_content), {})):
        await SocialEngine.run_turn(envelope)
    return captured["prompt"]


import asyncio


async def main():
    # 1. Default (no override): field defaults to empty list, not required.
    env_default = build_envelope()
    check("AgentEnvelope: ancestor_chat_summary defaults to []",
          env_default.ancestor_chat_summary == [], env_default.ancestor_chat_summary)

    # 2. Absent/empty: real no-op -- no ANCESTOR_CHAT_CONTEXT line in the prompt at all.
    prompt_absent = await run_and_capture_prompt(env_default)
    check("empty ancestor_chat_summary: no ANCESTOR_CHAT_CONTEXT line in the real composed prompt",
          "ANCESTOR_CHAT_CONTEXT" not in prompt_absent, prompt_absent)

    # 3. Present: real content lands in the Truth block, not the Signal block.
    real_facts = [{"content": "the Global agent already scoped this to Q4", "type": "fact"}]
    env_present = build_envelope(ancestor_chat_summary=real_facts)
    prompt_present = await run_and_capture_prompt(env_present)
    check("non-empty ancestor_chat_summary: ANCESTOR_CHAT_CONTEXT line present with real content",
          "ANCESTOR_CHAT_CONTEXT" in prompt_present and "already scoped this to Q4" in prompt_present,
          prompt_present)
    truth_idx = prompt_present.find("BLOCK 3: THE TRUTH")
    signal_idx = prompt_present.find("BLOCK") if truth_idx == -1 else -1
    ancestor_idx = prompt_present.find("ANCESTOR_CHAT_CONTEXT")
    check("ANCESTOR_CHAT_CONTEXT lands after the TRUTH block header (Truth-shaped, not Signal)",
          truth_idx != -1 and ancestor_idx != -1 and ancestor_idx > truth_idx, prompt_present)
    established_idx = prompt_present.find("ESTABLISHED_KNOWLEDGE")
    check("ANCESTOR_CHAT_CONTEXT is appended after ESTABLISHED_KNOWLEDGE, same Truth block",
          established_idx != -1 and ancestor_idx > established_idx, prompt_present)

    print("\n=== Phase 7 prep: ancestor_chat_summary verification ===")
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
