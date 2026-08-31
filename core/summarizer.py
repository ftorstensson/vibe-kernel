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
                    "bucket": {"type": "string", "enum": ["Core Topic", "Sub Topics", "Miscellaneous"]},
                    "resolution_status": {"type": "string", "enum": ["unresolved", "settled"]},
                },
                "required": ["content", "type", "speaker", "turn_index", "bucket", "resolution_status"],
            },
        }
    },
    "required": ["items"],
}


def extract_facts(turns, required_questions=None, purpose=None, offset=0, prior_chat_summary=None, l1=None, l3=None, skill=""):
    """Chat Manager's real extraction step. l1/l3/skill are real, not a
    hand-written mandate string -- Backend resolves the raw ingredients (the
    real functions_registry "Chat Manager" skill, the "scribe" archetype's
    mandate, the app's platform/app-manual/mission), main.py's endpoint (or
    core/orchestrator.py's live-turn identity resolution) composes l1/l3 via
    core/composition.py's compose_function_identity(), same as Gate Maker
    (derive_requirements)/Gatekeeper (assess_coverage). This function does no
    composition or I/O itself, and -- as of this pass -- no embedded
    procedure text either: the entire extraction spec (what counts as
    extractable, hedging rules, bucket/resolution_status definitions, how to
    use ALREADY-ESTABLISHED FACTS context) now lives in skill, not hardcoded
    here. That content used to be an inline mandate string in this file;
    moved to Firestore verbatim, not rewritten, since the exact wording is
    what made the turn_index/back-reference fixes verified in the prior pass
    actually work -- paraphrasing it loosely would risk quietly regressing
    already-tested behavior.

    Structured fact extraction instead of prose summarization is a real
    design decision skill's real content should preserve: prose summaries
    silently drop specific details because every item competes for space in
    one narrative. Returns a list of discrete items, each with its type and
    the index of the source turn it came from -- so the original wording is
    always traceable, not just paraphrased away.

    offset/prior_chat_summary support incremental compute (build_chat_summary()
    passing history[cursor:] instead of the full conversation, closing Chat
    Manager's persistence gap):

    offset: turns may be a slice starting partway through the real
    conversation, not the whole thing -- turn_index must still reflect true
    position (enumerate(turns, start=offset), not enumerate(turns)), since
    it's shown back to the model in reconcile_fact()'s own prompt and
    Coverage's facts_listing, and is what revision_trail preserves as
    traceable history. Getting this wrong doesn't crash anything, it just
    silently mislabels every fact's turn number from here on -- worth
    getting right the first time, not caught by a type error.

    prior_chat_summary: when turns is a slice, the model can't see whatever
    came before offset -- but a real conversation routinely references it
    ("yeah let's go with that", "the second option you mentioned"). Passed
    as lightweight already-established-facts context (not the raw
    pre-cursor turns -- prior_chat_summary is already condensed, cheaper,
    and is exactly the same context reconcile_fact() itself works from) so
    the model can resolve those references without re-reading everything
    it already distilled once. skill's own text carries the instruction not
    to re-extract anything already in this list; Kernel only assembles the
    data block itself (the listing below), unconditionally available in the
    truth block whenever prior_chat_summary is non-empty."""
    model, config = AgentFactory.get_summarizer()

    numbered_turns = "\n".join(f"{i}: [{t['role']}] {t['content']}" for i, t in enumerate(turns, start=offset))

    truth = f"CONVERSATION (numbered):\n{numbered_turns}"
    if required_questions:
        truth += f"\n\nMILESTONE REQUIRED QUESTIONS:\n{required_questions}"
    if purpose:
        truth += f"\n\nMILESTONE PURPOSE:\n{purpose}"
    if prior_chat_summary:
        established = "\n".join(
            f"- [{f['type']}] {f['content']} (turn {f['turn_index']}, {f['speaker']})"
            for f in prior_chat_summary if f.get("status", "current") == "current"
        )
        truth += f"\n\nALREADY-ESTABLISHED FACTS:\n{established}"
    lens = f"{l3}\n\n{skill}" if l3 else skill

    work_order = PromptBuilder.assemble(mandate=l1, lens=lens, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=EXTRACTION_SCHEMA)
    return hammer_json(get_clean_text(response)).get("items", [])
