from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "type": {"type": "string", "enum": ["preference", "decision", "fact", "story", "agreement"]},
                    "speaker": {"type": "string", "enum": ["user", "assistant"]},
                    "turn_index": {"type": "integer"},
                },
                "required": ["content", "type", "speaker", "turn_index"],
            },
        }
    },
    "required": ["items"],
}


def summarize_history(turns):
    """Standalone, Phase 1 only -- not wired into run_turn/run_global_turn or
    any real conversation flow. Given a list of {role, content} turns,
    returns a condensed running summary preserving key facts, decisions,
    and context."""
    model, config = AgentFactory.get_summarizer()

    mandate = (
        "You are a summarization function. Given a portion of a conversation, "
        "produce a concise running summary. Preserve, in order of priority:\n"
        "1. Anything the user stated as a preference or decision -- keep these "
        "precisely, close to their own words. They are already settled and must "
        "never be dropped or softened.\n"
        "2. Concrete facts or stories.\n"
        "3. The general narrative and topic thread.\n"
        "No commentary, no meta-talk -- just the summary."
    )
    truth = f"CONVERSATION:\n{turns}"

    work_order = PromptBuilder.assemble(mandate=mandate, truth=truth)
    response = model.generate_content(work_order, generation_config=config)
    return get_clean_text(response)


def extract_facts(turns):
    """Standalone, Phase 1 only -- not wired into run_turn/run_global_turn or
    any real conversation flow. Structured fact extraction instead of prose
    summarization: research shows prose summaries silently drop specific
    details because every item competes for space in one narrative.
    Returns a list of discrete items, each with its type and the index of
    the source turn it came from -- so the original wording is always
    traceable, not just paraphrased away."""
    model, config = AgentFactory.get_summarizer()

    numbered_turns = "\n".join(f"{i}: [{t['role']}] {t['content']}" for i, t in enumerate(turns))

    mandate = (
        "You are a fact-extraction function. Given a numbered conversation, extract "
        "only what's genuinely worth remembering -- skip anything fungible or "
        "distillable later. Do NOT extract small talk, the assistant's own process "
        "narration, or its questions and acknowledgments -- those are replaceable, "
        "not worth preserving.\n"
        "Extract only:\n"
        "1. Anything the user stated as a preference, decision, fact, or story -- "
        "keep close to their own words, never dropped or softened. This is the "
        "Non-Googleable stuff: the specific intent, the twist, the grit -- not "
        "something that could be reconstructed later. A hedge in the phrasing "
        "does NOT disqualify it -- a tentative suggestion that still contains "
        "real proposed content (a number, a mechanism, a direction) counts just "
        "as much as a confident one. When capturing a hedged item, keep the "
        "hedge in the wording itself (e.g. 'floated the idea that...', "
        "'suggested, without committing, that...') rather than restating it as "
        "settled -- your job is to capture content faithfully, including how "
        "firm or tentative it was, not to judge how settled it is. But do NOT "
        "extract turns where the user "
        "explicitly withholds or defers the content itself ('not sure yet, "
        "let's come back to that', 'I don't have an opinion', 'no preference "
        "either way') or is doing session bookkeeping ('that's it for today', "
        "'let's move on') -- unlike a hedged-but-substantive suggestion, these "
        "offer no actual content to preserve.\n"
        "2. A genuine conclusion or agreement actually reached in the conversation "
        "(e.g. the team agreeing on a direction) -- not a rhetorical question or a "
        "mid-argument remark.\n"
        "Requests to do something later (reminders, follow-ups, 'check X next "
        "week') are neither preferences nor decisions -- do not extract them. If "
        "an item doesn't genuinely fit one of the categories above, leave it out "
        "rather than forcing it into the closest-sounding type.\n"
        "For each item, give its type, which turn number it came from, and the "
        "speaker of that turn (read the speaker directly off the turn's own role "
        "label -- do not guess). No commentary."
    )
    truth = f"CONVERSATION (numbered):\n{numbered_turns}"

    work_order = PromptBuilder.assemble(mandate=mandate, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=EXTRACTION_SCHEMA)
    return hammer_json(get_clean_text(response)).get("items", [])
