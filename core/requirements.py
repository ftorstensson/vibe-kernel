from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder

REQUIREMENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "rationale": {"type": "string"},
        "ignition_inputs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "why_irreplaceable": {"type": "string"},
                },
                "required": ["question", "why_irreplaceable"],
            },
        },
    },
    "required": ["rationale", "ignition_inputs"],
}


def derive_requirements(purpose, target_structure, l1, l3, skill):
    """Standalone, Phase 1 only -- not wired into the real Clerk/gate mechanism.
    Runs once per milestone (a planning step, not per-turn). Does NOT classify
    each target_structure item individually -- that was the first version's
    mistake, a mechanical 1:1 map that missed the point. Instead, looks at the
    whole purpose + target structure holistically and distills it down to the
    small handful of broad "Ignition Inputs" only a human can provide.
    Everything else in the target structure is implicitly AI-researchable once
    those few inputs exist -- not enumerated, because it doesn't need to be.

    l1, l3, and skill are real, not a hand-written mandate string -- Backend
    resolves the raw ingredients (the real Functions Library skill from
    registry_docs/functions_registry, the actual live archetype/platform-
    logic/app-manual sources), main.py's endpoint composes l1/l3 from them
    via core/composition.py's compose_function_identity() (the same
    compose_l1_lines/compose_l3_lens path real agent turns use) -- this
    function does no composition or I/O itself. l3 (app_manual, when the app
    has one) is None for apps without one -- folded into the LENS block
    alongside skill, same pattern real agent turns use to combine L2+L3 into
    their own LENS block.
    This function does no Firestore I/O itself and has no embedded procedure
    text -- it only assembles the prompt from what it's given and calls the
    model, matching the pure-function shape every other Phase 1 function
    already has.

    Returns {rationale, ignition_inputs}. rationale comes before
    ignition_inputs in both the schema and the mandate so the model reasons
    through the task before committing to a list, not after -- legible to a
    human reviewing the output, and reasoning-first tends to produce a
    better derivation than jumping straight to a list."""
    model, config = AgentFactory.get_summarizer()

    truth = f"PURPOSE:\n{purpose}\n\nTARGET OUTPUT STRUCTURE:\n{target_structure}"
    lens = f"{l3}\n\n{skill}" if l3 else skill

    work_order = PromptBuilder.assemble(mandate=l1, lens=lens, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=REQUIREMENTS_SCHEMA)
    return hammer_json(get_clean_text(response))
