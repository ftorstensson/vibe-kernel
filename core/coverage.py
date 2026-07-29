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
                    "target_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["RED", "AMBER", "GREEN"]},
                    "is_satisfied": {"type": "boolean"},
                },
                "required": ["target_id", "status", "is_satisfied"],
            },
        },
        "gate_status": {"type": "string", "enum": ["RED", "AMBER", "GREEN"]},
        "whisper": {"type": "string"},
    },
    "required": ["assessments", "gate_status", "whisper"],
}


def assess_coverage(requirements, turns):
    """Standalone, Phase 1 only -- not wired into the real Clerk/gate mechanism.
    Runs every turn, like today's Clerk does: given Requirements' derived
    list (each item tagged human/ai) and the live conversation, produces a
    RED/AMBER/GREEN status per item. Draws directly on
    registry/prompts/kaiser_mandate.md's real Traffic Lights, Zero-Delta Law,
    and Whisper Protocol -- a traffic-light gate, not today's live binary
    GREEN/RED Clerk."""
    model, config = AgentFactory.get_summarizer()

    numbered_turns = "\n".join(f"{i}: [{t['role']}] {t['content']}" for i, t in enumerate(turns))

    mandate = (
        "You are a coverage-audit function, running every turn. Given a "
        "Requirements list (each item tagged human or ai) and the live "
        "conversation, assess each item using the Traffic Lights:\n"
        "- RED: no specific intent provided yet. is_satisfied: false.\n"
        "- AMBER: the Seed. The intent is clear enough for an AI Specialist to "
        "research. is_satisfied: true.\n"
        "- GREEN: the Meat. The Director has provided specific vision, "
        "integrations, or unique constraints. is_satisfied: true.\n"
        "THE ZERO-DELTA LAW: if the missing info is something an AI Specialist can "
        "research or draft, the Delta is ZERO -- mark it AMBER as soon as any seed "
        "of an idea is planted, especially for items tagged 'ai'. Do not demand "
        "human-level specificity on ai-bucket items.\n"
        "gate_status is the lowest status among all assessments (RED is lowest, "
        "then AMBER, then GREEN).\n"
        "WHISPER: if ALL items are AMBER or GREEN, the whisper MUST be exactly "
        "'The vision is Strike-Ready. Signal the launch of the AI specialists.' If "
        "ANY item is RED, identify the single most critical RED item and nudge "
        "focus onto just that one. Exactly one sentence, no brackets."
    )
    truth = f"REQUIREMENTS:\n{requirements}\n\nCONVERSATION (numbered):\n{numbered_turns}"

    work_order = PromptBuilder.assemble(mandate=mandate, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=COVERAGE_SCHEMA)
    return hammer_json(get_clean_text(response))
