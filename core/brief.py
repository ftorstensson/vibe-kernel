from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "identity_narrative": {"type": "string"},
        "founding_voice": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["identity_narrative", "founding_voice"],
}


def derive_brief(purpose, durable_facts):
    """Standalone, Phase 1 only -- not wired into any real flow. The historical
    "Author" role (~/vibe-design-lab/Brain/AI_SYSTEM_MAP.md: "The Author (ID:
    `master_author`)... Synthesizing chat history into the 2-paragraph 'Official
    Brief'"), rebuilt as a function rather than a persona/agent, and updated to
    synthesize from the durable facts list (this pass's build_durable_facts()
    output -- deduplicated, revision-merged) instead of raw chat history, for
    the same reason Coverage was: nothing downstream should be built on
    something that might have scrolled out of view or since been contradicted.

    Runs once coverage is all-clear (a planning step, not per-turn, like
    derive_requirements()).

    Output shape matches content.brief as ~/vibe-design-lab's ExecutivePaperNode
    (StrategyNodes.tsx) actually reads it -- {identity_narrative, founding_voice}
    -- restoring the real "v32.0 Structured Trail Data" contract confirmed still
    live in that component, rather than the plain-string shape this function
    used before that was found. identity_narrative carries the same positive
    anchor + Dual-Brief negative constraints as before (SCAR_TISSUE_v20.md
    Entry 079, "The SaaS Ghost") -- unchanged substance, just one named field
    instead of the whole return value. founding_voice is new: 2-4 short,
    close-to-verbatim quotes lifted from the Director's own durable facts (not
    paraphrased into the Author's voice) -- what the UI's "Founding Voice"
    section is actually for, the conviction in the Director's own words.

    A 2-field schema is a much lighter constraint than the multi-field
    extraction SCAR_TISSUE_v20.md Entry 073 ("Brief Starvation") warned about --
    both fields are prose-shaped, not a deep structured extraction -- but it's
    still a real schema where there was none before, so verify output quality
    empirically rather than assuming the schema is free."""
    model, config = AgentFactory.get_summarizer()

    current_facts = [f for f in durable_facts if f.get("status", "current") == "current"]
    facts_listing = "\n".join(
        f"- [{f['type']}, speaker={f['speaker']}] {f['content']}" for f in current_facts
    ) or "(none yet)"

    mandate = (
        "You are the Author: a dedicated brief-writing function. Given the "
        "milestone's purpose and the Director's durable, settled facts for it "
        "(already deduplicated and revision-merged -- treat this as the "
        "complete, current truth), produce two things for the AI Specialists "
        "who will research this milestone next. They will never see the raw "
        "conversation -- this is the only context they get, so it must carry "
        "the real substance forward, not a thin restatement.\n"
        "1. identity_narrative: exactly two paragraphs of plain prose. No "
        "bullet points, no headers, no bolding, no JSON, no meta-commentary "
        "about being a brief -- just the brief itself.\n"
        "   POSITIVE ANCHOR: state plainly what this actually is -- the "
        "specific idea, the audience, the twist, the model. Keep the "
        "Director's own grit and specificity; do not sand it down into a "
        "generic pitch.\n"
        "   NEGATIVE CONSTRAINTS (THE DUAL-BRIEF): also state what this is "
        "explicitly NOT -- the nearby generic category a model would default "
        "to if left unconstrained (e.g. 'this is NOT a generic B2B SaaS "
        "tool'), named directly from what actually distinguishes this idea. "
        "Skip this only if there is truly nothing in the facts to draw a "
        "negative constraint from.\n"
        "2. founding_voice: 2-4 short quotes taken close to verbatim from the "
        "Director's OWN durable facts (speaker=user only) -- not paraphrased "
        "into your own voice, not invented. Pick the lines that carry the "
        "real personal conviction or grit behind the idea. If fewer than 2 "
        "user-spoken facts genuinely qualify, return fewer rather than "
        "padding with weak material."
    )
    truth = f"MILESTONE PURPOSE:\n{purpose}\n\nDURABLE FACTS:\n{facts_listing}"

    work_order = PromptBuilder.assemble(mandate=mandate, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=BRIEF_SCHEMA)
    return hammer_json(get_clean_text(response))
