from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder

LAUNCH_CONFIRM_SCHEMA = {
    "type": "object",
    "properties": {
        "confirmed": {"type": "boolean"},
    },
    "required": ["confirmed"],
}


def confirm_launch_intent(history):
    """Standalone, Phase 1 only. Replaces the old `"go" in user_input.lower()`
    substring check (real, already-hit bug: "grow"/"good"/etc. false-trigger
    it) with a real model judgment -- Fred's explicit design, tried keyword
    matching before and abandoned it as unreliable.

    Only meaningful once Coverage's gate_status has genuinely reached ready
    (see core/orchestrator.py) -- at that point the PM's own turn already
    declares Strike-Readiness (via Coverage's whisper) and asks the Director
    for the go-ahead. This function classifies whether the Director's latest
    reply, in the context of the last few turns, is a genuine affirmative
    confirmation to launch now -- not a keyword match on any specific word.

    Runs every turn while ready-and-not-yet-launched (cheap, IQ 0.0 tier,
    same as the Clerk) rather than tracking a separate "awaiting
    confirmation" state -- Kernel has no persistence to hold that state in
    anyway, and re-deriving from "still ready, still not fired" each turn is
    simpler and self-correcting if the Director changes their mind."""
    model, config = AgentFactory.get_clerk()

    mandate = (
        "You are a launch-confirmation classifier. The PM has just told the "
        "Director the vision is Strike-Ready and asked for the go-ahead to "
        "launch the AI specialists. Given the recent conversation, decide "
        "whether the Director's LATEST message genuinely confirms launching "
        "now -- real affirmative intent, however phrased ('yes', 'let's do "
        "it', 'sounds good', 'go for it'), not a deflection, a new question, "
        "a request to change something first, or an ambiguous reply. When "
        "genuinely unsure, confirmed must be false -- never launch on a "
        "guess."
    )
    truth = f"RECENT CONVERSATION (last message is the Director's reply to judge):\n{history[-5:]}"

    work_order = PromptBuilder.assemble(mandate=mandate, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=LAUNCH_CONFIRM_SCHEMA)
    return hammer_json(get_clean_text(response)).get("confirmed", False)
