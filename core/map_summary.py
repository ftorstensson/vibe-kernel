from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text
from core.prompt_builder import PromptBuilder

MANDATE = (
    "You are a text-condensation function. Given a real purpose/output "
    "description, produce a genuine 1-2 sentence summary suitable for a "
    "compressed project map view -- someone scanning many of these at once "
    "needs to immediately understand what this specific item is about, not "
    "read the full original text. Preserve the real substance and specific "
    "content of the input -- never generic filler like \"this covers "
    "important work.\" Plain prose, no markdown, no restating the input "
    "verbatim, no meta-commentary about summarizing."
)


def summarize_for_map(text):
    """Test Run 1, items 6/7: the real summarization half of the Global Map
    split -- Backend already separated the static skeleton (names/purpose/
    structure) from the live position (execution_status, read fresh) at
    the Materialized View layer; this is the piece that turns a
    milestone's or phase's real purpose/output text into an actual
    1-2 sentence summary at compile/publish time, replacing a crude
    140-char truncation with a genuine condensation call. Same trigger
    timing as compile_identity (called once per milestone/phase at
    publish), cached in the compiled record the same way L1/L3 are --
    Kernel does no caching itself, it's stateless, this just returns the
    summary string for Backend to persist.

    Same model tier as Chat Manager's own extraction (AgentFactory.
    get_summarizer(), IQ 0.0/Gemini 2.5 Flash) -- "accurate condensation,
    not creative work" is exactly this task's own shape too, not a
    coincidence.

    No L1/persona identity here, deliberately -- this isn't spoken in any
    agent's voice and never reaches the Director as PM dialogue; it's
    neutral, compressed structural content Backend renders straight into
    project_map (see core/composition.py's compose_project_map_lens(),
    which treats it as plain informational text, not anything persona-
    flavored). Threading L1/archetype context through it would risk the
    summary picking up voice characteristics that don't belong in map
    data -- same reasoning core/reconcile.py's reconcile_fact() and
    core/brief.py's derive_brief() already establish for a narrowly-
    scoped internal utility that needs accuracy, not personality.

    Hardcoded mandate above, not Firestore-sourced like the four declared
    Functions' skill text -- this is Kernel's own internal composition
    step, not Studio-editable content, same precedent
    core/reconcile.py's reconcile_fact() and pods/social/engine.py's
    synthesize_dispatch() already set for exactly this kind of narrowly-
    scoped, non-agent-facing internal mandate.

    Not batched -- one call per milestone/phase, matching how
    compile_identity itself is already called (once per agent, once per
    Function, individually), not a new pattern. Takes just the raw text,
    no additional context -- Backend controls exactly what it wants
    condensed; Kernel doesn't fetch or assume anything beyond what it's
    given, same stateless-executor principle as everywhere else."""
    model, config = AgentFactory.get_summarizer()
    truth = f"TEXT TO SUMMARIZE:\n{text}"
    work_order = PromptBuilder.assemble(mandate=MANDATE, truth=truth)
    response = model.generate_content(work_order, generation_config=config)
    return get_clean_text(response)
