from core.agent_factory import AgentFactory
from core.composition import compose_l4_lens, join_blocks
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


def resolve_required_questions(milestone_config):
    """Prefers Requirements' real derived output over the static
    hand-authored required_questions list, once it exists. Backend writes
    derived_requirements onto the milestone doc (Requirements' real
    ignition_inputs) whenever Requirements is run for real, replacing
    whatever was there before -- re-running is the only way it changes. A
    genuine fallback, not a hard requirement: a milestone with no
    derived_requirements yet (Requirements never run for it) keeps working
    exactly as it does today, off the original required_questions field.

    Defensive about the exact shape rather than assuming one, since
    derived_requirements doesn't exist on any real milestone doc as of this
    pass (Backend hasn't shipped the write yet) -- handles it being the raw
    ignition_inputs list ([{question, why_irreplaceable}, ...], the literal
    shape derive_requirements() already returns), the full
    {rationale, ignition_inputs} response object, or a flat list of question
    strings, without crashing on whichever one Backend lands on."""
    derived = milestone_config.get("derived_requirements")
    if isinstance(derived, dict):
        derived = derived.get("ignition_inputs")
    if derived:
        return [item.get("question", "") if isinstance(item, dict) else item for item in derived]
    return milestone_config.get("required_questions")


def assess_coverage(required_questions, chat_summary, l1, l3, skill):
    """Runs every real turn (core/orchestrator.py): given the milestone's
    required_questions (L4 -- the gates being checked) and chat_summary
    (L5 -- this turn's core/reconcile.py output, formerly durable_facts,
    deduplicated, revision-merged, one entry per real thing the Director has
    said, NOT raw chat history -- Coverage never sees that), produces a
    RED/AMBER/GREEN status per question. Checking against chat_summary
    rather than a trailing window of raw turns is deliberate: a fact
    established early in a long conversation must stay counted even after it
    scrolls out of any fixed window -- coverage should only regress if the
    Director actually contradicts themselves (a real reconcile_fact()
    CONTRADICTION), never because the conversation got long.

    l1, l3, and skill are real, not a hand-written mandate string -- Backend
    resolves the raw ingredients (the real "judge" archetype -- Traffic
    Lights, Zero-Delta Law, the Nudge -- and the real functions_registry
    "Coverage" entry's skill, the assessment procedure and whisper tone),
    the caller (main.py's endpoint, or core/orchestrator.py's live turn)
    composes l1/l3 from them via core/composition.py's
    compose_function_identity() (the same compose_l1_lines/compose_l3_lens
    path real agent turns and derive_requirements() use). l3 (mission +
    app_manual, when the app has them) folds into the LENS block alongside
    skill, same pattern derive_requirements() uses. This function does no
    Firestore I/O itself -- it only assembles the prompt from what it's
    given and calls the model."""
    model, config = AgentFactory.get_summarizer()

    current_facts = [f for f in chat_summary if f.get("status", "current") == "current"]
    facts_listing = "\n".join(
        f"- [{f['type']}] {f['content']} (turn {f['turn_index']}, {f['speaker']})"
        for f in current_facts
    ) or "(none yet)"

    # L5 (Signal): required_questions, the gates currently being checked --
    # per-milestone current data, not accumulated state. L6 (Memory):
    # chat_summary, the real reconciled fact record built up across turns --
    # genuinely accumulated memory, correctly placed. Taxonomy checked, not
    # assumed: this is the one function where L6 is unambiguous (it's
    # literally named for it -- chat_summary IS the memory layer).
    truth = join_blocks(f"REQUIRED QUESTIONS (GATES):\n{required_questions}", f"CHAT SUMMARY:\n{facts_listing}")
    lens = compose_l4_lens(l3, skill)

    work_order = PromptBuilder.assemble(mandate=l1, lens=lens, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=COVERAGE_SCHEMA)
    return hammer_json(get_clean_text(response))
