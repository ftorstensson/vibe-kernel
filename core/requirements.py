from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder

REQUIREMENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "string"},
                    "bucket": {"type": "string", "enum": ["human", "ai"]},
                    "reason": {"type": "string"},
                },
                "required": ["target_id", "bucket", "reason"],
            },
        }
    },
    "required": ["items"],
}


def derive_requirements(purpose, target_structure):
    """Standalone, Phase 1 only -- not wired into the real Clerk/gate mechanism.
    Runs once per milestone (a planning step, not per-turn): given the
    milestone's purpose and its target output structure, splits what's
    needed into "must come from the human" vs "AI can find/research itself".
    Draws directly on registry/prompts/foreman_mandate.md's real AI-First
    Audit / Substance Law language."""
    model, config = AgentFactory.get_summarizer()

    mandate = (
        "You are a requirements-derivation function, running once per milestone as "
        "a planning step, not per-turn. Given the milestone's purpose and its "
        "target output structure, decide what's actually needed to move forward, "
        "split into two buckets:\n"
        "1. MUST COME FROM THE HUMAN -- the Seed of conviction. Only the "
        "Non-Googleable stuff: the specific intent, the Twist, the Grit. Never ask "
        "for a distilled 'one-sentence' or 'clean' summary -- ask for the Meat, any "
        "length; an AI Specialist will distill it later.\n"
        "2. AI CAN FIND/RESEARCH ITSELF -- AI Specialists are experts at research "
        "and creative wordsmithing. If the missing info is something they can find "
        "or draft, it belongs here, not on the human. Minimize what you ask the "
        "human for.\n"
        "For each target output item, decide which bucket it belongs to and give a "
        "short reason."
    )
    truth = f"PURPOSE:\n{purpose}\n\nTARGET OUTPUT STRUCTURE:\n{target_structure}"

    work_order = PromptBuilder.assemble(mandate=mandate, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=REQUIREMENTS_SCHEMA)
    return hammer_json(get_clean_text(response)).get("items", [])
