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


def confirm_launch_intent(history, l1=None, skill=""):
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
    simpler and self-correcting if the Director changes their mind.

    l1/skill are real, not a hand-written mandate string -- Keymaster's own
    functions_registry skill (the confirmation criteria) and mandate (the
    classifier role + "never guess" law), same Test Run 1 pattern as Gate
    Maker/Gatekeeper/Chat Manager. Keymaster never had a donor archetype
    (unlike the other three) -- Backend resolves whatever real mandate
    content it has for Keymaster regardless of where it lives in Firestore,
    Kernel just composes and calls the model, agnostic to that.

    No l3 param: checked whether mission/app_manual context genuinely
    applies here, the way it does for Coverage's/Chat Manager's topic-
    relevance judgments -- it doesn't. This is a narrow, self-contained
    intent classification on the last few turns, not a topic/relevance
    judgment that benefits from broader app context. Adding an always-None
    l3 param here would be unused indirection, not real support."""
    model, config = AgentFactory.get_clerk()

    truth = f"RECENT CONVERSATION (last message is the Director's reply to judge):\n{history[-5:]}"

    work_order = PromptBuilder.assemble(mandate=l1, lens=skill, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=LAUNCH_CONFIRM_SCHEMA)
    return hammer_json(get_clean_text(response)).get("confirmed", False)
