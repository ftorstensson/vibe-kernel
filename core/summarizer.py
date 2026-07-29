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
                    "type": {"type": "string", "enum": ["preference", "decision", "fact", "story"]},
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
        "every distinct item worth remembering as its own separate entry -- do not "
        "blend items into a single narrative. For each item, give its type, which "
        "turn number it came from, and the speaker of that turn (read the speaker "
        "directly off the turn's own role label -- do not guess). Priority order "
        "for what to extract:\n"
        "1. Anything the user stated as a preference or decision -- keep close to "
        "their own words, never dropped or softened.\n"
        "2. Concrete facts or stories.\n"
        "3. General topic/context.\n"
        "No commentary."
    )
    truth = f"CONVERSATION (numbered):\n{numbered_turns}"

    work_order = PromptBuilder.assemble(mandate=mandate, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=EXTRACTION_SCHEMA)
    return hammer_json(get_clean_text(response)).get("items", [])
