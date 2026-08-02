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


def derive_requirements(purpose, target_structure):
    """Standalone, Phase 1 only -- not wired into the real Clerk/gate mechanism.
    Runs once per milestone (a planning step, not per-turn). Does NOT classify
    each target_structure item individually -- that was the first version's
    mistake, a mechanical 1:1 map that missed the point. Instead, looks at the
    whole purpose + target structure holistically and distills it down to the
    small handful of broad "Ignition Inputs" only a human can provide.
    Everything else in the target structure is implicitly AI-researchable once
    those few inputs exist -- not enumerated, because it doesn't need to be.

    Returns {rationale, ignition_inputs}. rationale comes before ignition_inputs
    in both the schema and the mandate so the model reasons through the task
    before committing to a list, not after -- mirrors
    registry/prompts/foreman_mandate.md's own [STRATEGIC_THOUGHTS] step (2-3
    sentences of internal logic) ahead of its final memo, dropped in the first
    rebuild and restored here for the same reason the original had it: legible
    to a human reviewing the output, and reasoning-first tends to produce a
    better derivation than jumping straight to a list.

    Draws directly on registry/prompts/foreman_mandate.md's real language:
    "Identify 3-4 Ignition Inputs (essential human context) required to start
    the AI Specialists' work", plus its Substance Law (ask for the Meat/Grit,
    not a distilled pitch; only the Non-Googleable stuff)."""
    model, config = AgentFactory.get_summarizer()

    mandate = (
        "You are a requirements-derivation function, running once per milestone as "
        "a planning step, not per-turn. Given the milestone's purpose and its full "
        "target output structure, first reason through it in a `rationale` field: "
        "2-3 plain-prose sentences covering what the milestone needs overall, what "
        "AI Specialists can research or draft on their own, what's left that only "
        "the human can provide, and therefore why these particular questions. "
        "Plain sentences, not a poetic label.\n"
        "Then, in `ignition_inputs`, do NOT classify each output field "
        "individually. Instead, distill the whole picture down to 3-4 broad "
        "'Ignition Inputs' -- the small set of essential things only the human can "
        "provide to get the AI Specialists started. Everything else in the target "
        "structure can be researched, drafted, or synthesized by AI Specialists "
        "once these few inputs exist -- that's implicit, don't enumerate it.\n"
        "THE SUBSTANCE LAW: only ask for the Non-Googleable stuff -- the specific "
        "intent, the Twist, the Grit. Never ask for a distilled 'one-sentence' or "
        "'clean' summary -- ask for the Meat, any length; AI Specialists will "
        "distill it into the full structure later. Minimize what you ask the human "
        "for.\n"
        "For each ignition input, phrase it as a genuinely broad question or topic "
        "-- not tied to any single output field -- and give a short note on why "
        "it's irreplaceable: something an AI could not infer or research on its "
        "own."
    )
    truth = f"PURPOSE:\n{purpose}\n\nTARGET OUTPUT STRUCTURE:\n{target_structure}"

    work_order = PromptBuilder.assemble(mandate=mandate, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=REQUIREMENTS_SCHEMA)
    return hammer_json(get_clean_text(response))
