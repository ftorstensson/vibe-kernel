from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text
from core.prompt_builder import PromptBuilder


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
