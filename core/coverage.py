from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder

COVERAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "status": {"type": "string", "enum": ["RED", "AMBER", "GREEN"]},
                    "is_satisfied": {"type": "boolean"},
                },
                "required": ["question", "status", "is_satisfied"],
            },
        },
        "gate_status": {"type": "string", "enum": ["RED", "GREEN"]},
        "whisper": {"type": "string"},
    },
    "required": ["assessments", "gate_status", "whisper"],
}


def assess_coverage(requirements, facts):
    """Standalone, Phase 1 only -- not wired into the real Clerk/gate mechanism.
    Runs every turn, like today's Clerk does: given Requirements' derived
    ignition_inputs list (core/requirements.py's distilled 3-4 broad questions,
    no target_id or human/ai bucket anymore) and the durable facts list (this
    turn's core/reconcile.py output -- deduplicated, revision-merged, one entry
    per real thing the Director has said, not a raw N-turn scrollback window),
    produces a RED/AMBER/GREEN status per ignition input. Checking against the
    durable list rather than a trailing window of raw turns is deliberate: a
    fact established early in a long conversation must stay counted even after
    it scrolls out of any fixed window -- coverage should only regress if the
    Director actually contradicts themselves (a real reconcile_fact()
    CONTRADICTION), never because the conversation got long. Draws directly on
    registry/prompts/kaiser_mandate.md's real Traffic Lights, Zero-Delta Law,
    Whisper Protocol, and Mirror Law (echo the literal question text back,
    same spirit as mirroring literal ID slugs) -- a traffic-light gate, not
    today's live binary GREEN/RED Clerk."""
    model, config = AgentFactory.get_summarizer()

    current_facts = [f for f in facts if f.get("status", "current") == "current"]
    facts_listing = "\n".join(
        f"- [{f['type']}] {f['content']} (turn {f['turn_index']}, {f['speaker']})"
        for f in current_facts
    ) or "(none yet)"

    mandate = (
        "You are a coverage-audit function, running every turn. Given a list of "
        "Ignition Inputs (broad questions only a human can answer -- there is no "
        "human/ai bucket anymore, every one of these is human-required by "
        "definition) and the current durable facts list (already deduplicated and "
        "revision-merged -- treat this as the complete, current truth, not a "
        "partial window), assess each question using the Traffic Lights:\n"
        "- RED: no specific intent provided yet. is_satisfied: false.\n"
        "- AMBER: the Seed. The intent is clear enough for an AI Specialist to "
        "research. is_satisfied: true.\n"
        "- GREEN: the Meat. The Director has provided specific vision, "
        "integrations, or unique constraints. is_satisfied: true.\n"
        "THE ZERO-DELTA LAW: if the remaining detail is something an AI Specialist "
        "can research or draft once a seed exists, the Delta is ZERO -- mark it "
        "AMBER as soon as any seed of an idea is planted. Do not demand exhaustive "
        "detail before marking AMBER.\n"
        "MIRROR LAW: echo the literal question text back in each assessment's "
        "'question' field, unchanged.\n"
        "gate_status is GREEN if there are no RED items (every item is AMBER or "
        "GREEN) and RED if any item is RED. There is no separate AMBER gate_status "
        "-- individual items can be AMBER, but the overall gate is a binary "
        "readiness signal, and it must always agree with the whisper below.\n"
        "WHISPER: if gate_status is GREEN, the whisper MUST be exactly 'The vision "
        "is Strike-Ready. Signal the launch of the AI specialists.' If gate_status "
        "is RED, identify the single most critical RED item and nudge focus onto "
        "just that one. Exactly one sentence, no brackets."
    )
    truth = f"IGNITION INPUTS:\n{requirements}\n\nDURABLE FACTS:\n{facts_listing}"

    work_order = PromptBuilder.assemble(mandate=mandate, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=COVERAGE_SCHEMA)
    return hammer_json(get_clean_text(response))
