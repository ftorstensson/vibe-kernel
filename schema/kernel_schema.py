from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class SovereignRequest(BaseModel):
    """Kernel is a stateless executor: given a complete input, it composes
    and calls the model and returns a result -- it never reaches into
    Firestore to go get its own inputs. Backend is the sole owner of
    Firestore; it assembles everything Kernel needs (the same real fetches
    core/bootloader.py's now-deleted SovereignBootloader used to do itself)
    and hands it over in one request. This replaces the old
    "the App sends IDs; the Kernel fetches the Physics" contract -- the
    exact pattern being reversed.

    milestone_config/persona_config/knowledge_bricks/history/physics_open
    are what AgentEnvelope already was -- populated by the caller now,
    not fetched. persona_config must already be merged the way
    core/bootloader.py's old BOOTSTRAP 1B merged it: the raw persona doc's
    own fields (system_prompt, exo_brain, ...) plus archetype (the agent's
    own bound archetype, record-wrapped as {mandate: str} -- "One Name,
    Many Records", not the old flat archetype_l0_mother key), app_manual,
    global_mission, and platform (same record-wrapped {mandate: str} shape,
    not the old flat platform_logic key). schema_map is the ARM doc (paths
    + schema_keys) -- genuinely still needed downstream, not just for
    path-resolution: pods/social/engine.py's run_turn() reads
    schema_map["schema_keys"]["pm_checklist"/"brick_list"] to build the
    Clerk's lens, so dropping it would break the live PM turn.

    coverage_mandate/coverage_skill: Coverage's own identity for the live
    turn's gate check (core/orchestrator.py) -- the "judge" archetype's real
    mandate content and the real functions_registry "Coverage" skill text.
    Not derived from persona_config (that's the AGENT's own archetype, e.g.
    "navigator" for a PM persona, a different archetype than Coverage's
    fixed "judge") -- but platform/app_manual/global_mission for Coverage's
    L1/L3 are NOT duplicated here, they're the exact same values already on
    persona_config (platform-wide/app-wide, identical for the agent and for
    Coverage), reused directly. Kept as a flat field here (not record-
    wrapped like persona_config's archetype/platform) since it's Kernel's
    own addition to the contract, not part of the shared persona_config
    shape Backend assembles the same way for every agent.

    milestone_id is Optional -- genuinely unused on the is_global=True path.
    process_turn() returns from that branch (core/orchestrator.py) before
    milestone_config is ever read, and run_global_turn() (pods/social/
    engine.py) only touches persona_config/knowledge_bricks/history --
    confirmed by tracing both, not assumed. Required for a real
    milestone-scoped call (is_global=False); Backend enforces that, not a
    Kernel-side validator, since Kernel has no way to distinguish "caller
    forgot it" from "global call, doesn't apply" from the value alone.

    chat_summary/chat_summary_cursor: Chat Manager's persisted state from
    the last time it ran for this conversation -- Backend sends back
    whatever build_chat_summary() last returned (empty list / 0 on a fresh
    conversation). Closes the real persistence gap that made every turn a
    full recompute: Kernel slices history[cursor:] itself (it already gets
    the full history) rather than Backend computing and sending a delta --
    cursor is the raw ingredient, Kernel does the slicing, same
    Backend-resolves-raw/Kernel-composes principle as everything else in
    this contract. Confirmed with Backend 2: chat_history is genuinely
    append-only/monotonic/transactional, and the cursor they send is read
    from the same snapshot as history, so it can't drift out from under
    this slice."""
    app_id: str
    project_id: str
    milestone_id: Optional[str] = None
    agent_id: Optional[str] = "master_pm"
    is_global: bool = False  # Global Agent conversation: PM-only, no Clerk/gate
    user_message: str
    milestone_config: Dict[str, Any]
    persona_config: Dict[str, Any]
    knowledge_bricks: Dict[str, str] = Field(default_factory=dict)
    history: List[Dict[str, str]] = Field(default_factory=list)
    physics_open: bool = False
    schema_map: Dict[str, Any]
    coverage_mandate: Optional[str] = None
    coverage_skill: Optional[str] = None
    chat_summary: List[Dict[str, Any]] = Field(default_factory=list)
    chat_summary_cursor: int = 0

class SovereignResponse(BaseModel):
    """The Formalized Interface for the App to consume.

    chat_summary/chat_summary_cursor: the advanced state after this turn's
    Chat Manager pass, for Backend to persist forward as next turn's
    chat_summary/chat_summary_cursor input -- None when Chat Manager didn't
    run this turn (no required_questions, or is_global), meaning "nothing
    changed, keep what you already have," not "reset to empty."."""
    social_response: str
    status: str  # PROBING | AUTHORIZED | STABLE | GLOBAL
    data_patch: Optional[Dict[str, str]] = None
    # Restores the real v32.0-era API contract (confirmed still expected by
    # the-co-founder's app/agency/architect.py and rendered by
    # vibe-design-lab's ExecutivePaperNode) rather than inventing a new shape.
    # brief: {identity_narrative, founding_voice} from core/brief.py.
    # appendix: one {role, content, sources} entry per specialist, their own
    # raw report and their own real sources, not re-synthesized.
    brief: Optional[Dict[str, Any]] = None
    appendix: Optional[List[Dict[str, Any]]] = None
    chat_summary: Optional[List[Dict[str, Any]]] = None
    chat_summary_cursor: Optional[int] = None

class DeriveRequirementsRequest(BaseModel):
    """Functions Library, entry 1: derive_requirements() needs no conversation
    state -- no project_id/milestone_id, no envelope, no chat history -- just
    the milestone's own purpose and target output structure, which the caller
    (Studio) already has. Kept separate from SovereignRequest deliberately:
    this isn't a conversational turn.

    archetype/platform/app_manual/global_mission/skill are raw ingredients
    Backend already resolved (functions_registry, archetype_registry, the
    app's own ARM) -- Kernel composes L1/L3 from them itself via
    core/composition.py's compose_function_identity() (the same
    compose_l1_lines/compose_l3_lens real agent turns use), it doesn't
    fetch them. archetype/platform are each record-wrapped ({mandate: str}),
    not flat archetype_l0_mother/platform_logic keys -- "One Name, Many
    Records", same as persona_config's shape on SovereignRequest. app_id is
    kept for identification/error messages only, it no longer drives a
    Firestore lookup."""
    app_id: str
    purpose: str
    target_structure: List[Any] = Field(default_factory=list)
    archetype: Optional[Dict[str, Any]] = None
    platform: Optional[Dict[str, Any]] = None
    app_manual: Optional[str] = None
    global_mission: Optional[str] = None
    skill: str = ""

class DeriveRequirementsResponse(BaseModel):
    rationale: str
    ignition_inputs: List[Dict[str, str]]

class PreviewFunctionRequest(BaseModel):
    """Test Lab preview -- function-agnostic composition, but each function's
    L4/L5 data has its own shape, so this request carries both a legacy,
    Requirements-specific path and a generic one:

    purpose/target_structure: Requirements' real, already-live shape --
    Backend's proxy and Studio's Requirements Input panel consume this in
    production today. Kept exactly as-is, not touched, so that integration
    doesn't break.

    l4_data/l5_data: generic pass-through for any other function (e.g.
    Coverage's required_questions/chat_summary) -- echoed straight into the
    response's l4/l5 alongside the resolved skill, no function-specific
    field names hardcoded. l4_data is the discriminator: if a caller sends
    it, the generic path is used instead of the legacy purpose/target_structure
    one (see main.py's invoke_preview_function).

    archetype/platform/app_manual/global_mission/skill: raw ingredients
    Backend already resolved -- Kernel composes L1/L3 itself via
    compose_function_identity(), same as derive_requirements'/
    assess_coverage's own endpoints, so there's exactly one place this
    composition runs. archetype/platform are each record-wrapped
    ({mandate: str}), matching the same shape everywhere else this
    session's ingredients travel. app_id/function_name are identification
    only now, they no longer drive a Firestore lookup.

    This endpoint does no model call itself -- composition is cheap, and
    l4_data/l5_data are just echoed back, same as purpose/target_structure
    always were -- cheap to fetch purely for display. (A real L5 fetch, e.g.
    Coverage's chat_summary, is a separate concern with a real cost -- see
    /kernel/chat_summary -- the caller fetches it first, then optionally
    passes the result in here via l5_data for display alongside L1/L3.)"""
    app_id: str
    function_name: str
    purpose: Optional[str] = None
    target_structure: List[Any] = Field(default_factory=list)
    l4_data: Optional[Dict[str, Any]] = None
    l5_data: Optional[List[Any]] = None
    archetype: Optional[Dict[str, Any]] = None
    platform: Optional[Dict[str, Any]] = None
    app_manual: Optional[str] = None
    global_mission: Optional[str] = None
    skill: str = ""

class PreviewFunctionResponse(BaseModel):
    """The real, literal prompt inputs a Functions Library entry's model call
    would use -- composition only, no model call, no rationale/ignition_inputs.
    Named by layer (L1-L5) to match the same five-layer shape real agent turns
    are composed from (see core/composition.py, pods/social/engine.py), so the
    Test Lab can render all five boxes consistently across agents and
    functions -- with L2/L5 explicitly present-but-empty for a stateless
    function like Requirements, not silently missing.

    l1: Mandate -- archetype.mandate + platform.mandate, via
        compose_function_identity()/compose_l1_lines(). Real.
    l2: Persona/voice (an agent's own system_prompt/dna). Not applicable to a
        Functions Library entry -- there's no agent persona here, only a
        procedure. None by design, not a missing fetch.
    l3: Deep Knowledge/Exo-Brain -- app_manual, via compose_l3_lens() (same
        layer agents' mission/app_manual live in). Real whenever the app has
        one; None when it doesn't -- not hardcoded to always-empty, a
        function's app_manual is exactly as real as an agent's.
    l4: Active Task/Signal -- what this specific unit of work actually is:
        the Skill (functions_registry's real procedure text, fixed per
        function) plus the function's own data, echoed straight back from
        the request -- purpose/target_structure for Requirements,
        required_questions for Coverage, whatever a future function needs.
        Both the Skill and the data define the task, so both live here
        together.
    l5: History/distilled-memory layer. None for a function with no
        conversation state (e.g. Requirements). Real when the caller
        supplies it (e.g. Coverage's chat_summary, fetched separately via
        /kernel/chat_summary and passed through here for display)."""
    l1: str
    l2: Optional[str] = None
    l3: Optional[str] = None
    l4: Dict[str, Any]
    l5: Optional[List[Any]] = None

class AssessCoverageRequest(BaseModel):
    """Coverage's own standalone endpoint, same reasoning as
    DeriveRequirementsRequest: Coverage needs no envelope/history of its
    own -- just the milestone's own raw fields and the current chat_summary
    (L5, the caller already has these -- from a live turn, or fetched
    standalone via /kernel/chat_summary).

    archetype/platform/app_manual/global_mission/skill: raw ingredients
    Backend already resolved (the "judge" archetype's mandate content, the
    app's platform mandate/app_manual/global_mission, and the real
    functions_registry "Coverage" skill text) -- Kernel composes L1/L3
    itself via compose_function_identity(), the same call the live turn
    pipeline (core/orchestrator.py) uses for Coverage's own gate check. This
    endpoint no longer fetches its own identity. archetype/platform are
    each record-wrapped ({mandate: str}), matching the same shape
    everywhere else this session's ingredients travel.

    required_questions and derived_requirements are the milestone's raw
    fields, NOT pre-resolved by the caller -- the endpoint builds a
    milestone_config-shaped dict from them and calls
    resolve_required_questions() (core/coverage.py) itself -- a pure
    function, no I/O, so this doesn't violate the stateless-executor
    principle. This is the fix for a real drift bug: Test Lab's Coverage
    panel was pre-resolving required_questions client-side and never knew
    derived_requirements should take precedence, so it always audited the
    static sheet even for milestones with a real Requirements run already
    persisted -- the live turn pipeline got this right (it already calls
    resolve_required_questions()) but every other caller had to duplicate
    that logic correctly to not regress it. Making the endpoint itself the
    single source of truth removes that duplication risk entirely.
    derived_requirements accepts any of the shapes resolve_required_questions()
    already tolerates (raw ignition_inputs list, the full
    {rationale, ignition_inputs} object, or flat strings) -- None/absent
    when the milestone has never had Requirements run for it."""
    app_id: str
    required_questions: List[str] = Field(default_factory=list)
    derived_requirements: Optional[Any] = None
    chat_summary: List[Dict[str, Any]] = Field(default_factory=list)
    archetype: Optional[Dict[str, Any]] = None
    platform: Optional[Dict[str, Any]] = None
    app_manual: Optional[str] = None
    global_mission: Optional[str] = None
    skill: str = ""

class AssessCoverageResponse(BaseModel):
    assessments: List[Dict[str, Any]]
    gate_status: str
    whisper: str

class ChatSummaryRequest(BaseModel):
    """Computes chat_summary (L5, renamed from durable_facts -- matching
    Gatekeeper's own canvas board target display name) from a real
    conversation history the caller already has -- Kernel no longer fetches
    a project's stored chat_history itself (that was core/bootloader.py's
    fetch_project_history(), now deleted; Backend fetches it and sends
    history directly). NOT free like PreviewFunctionResponse's other layers:
    build_chat_summary() genuinely calls the model (extract_facts, then a
    reconcile_fact pass per fact), so this is a deliberate, on-demand
    computation, not something to poll or auto-fire on every render. Lives
    outside /kernel/functions/ -- this isn't a Functions Library identity
    concern.

    required_questions/purpose are optional milestone context for bucket
    classification (Core Topic/Sub Topics/Miscellaneous) -- omit for a
    bare, milestone-agnostic call.

    prior_chat_summary/cursor: the same incremental-compute inputs
    /kernel/invoke takes -- omit (empty list / 0) for a full recompute from
    scratch, same as before this pass. When given, history is sliced
    [cursor:] internally; prior_chat_summary is folded with the newly
    extracted items via reconcile_fact() and also given to extract_facts()
    as lightweight context so backward references in the new turns ("that",
    "the second option") can resolve against already-established facts."""
    history: List[Dict[str, Any]] = Field(default_factory=list)
    required_questions: Optional[List[str]] = None
    purpose: Optional[str] = None
    prior_chat_summary: List[Dict[str, Any]] = Field(default_factory=list)
    cursor: int = 0

class ChatSummaryResponse(BaseModel):
    """chat_whisper: the single most pressing thing Chat Manager couldn't
    confidently classify as new/update/conflict this call, or None if
    nothing needs the Director's clarification -- see
    core/reconcile.py's build_chat_summary().

    chat_summary_cursor: the advanced cursor (len(history) at this call) --
    the caller persists this alongside chat_summary and sends both back as
    prior_chat_summary/cursor on the next call."""
    chat_summary: List[Dict[str, Any]]
    chat_whisper: Optional[str] = None
    chat_summary_cursor: int

class AgentEnvelope(BaseModel):
    """Internal briefcase containing the Map and the Data -- populated
    directly from SovereignRequest's fields now (main.py's /kernel/invoke),
    no Firestore fetch in between. kaiser_mandate/coverage_whisper are pure
    turn-local scratch state, always computed fresh within the turn, never
    part of the incoming request."""
    app_id: str
    project_id: str
    milestone_config: Dict[str, Any]
    persona_config: Dict[str, Any]
    knowledge_bricks: Dict[str, str] = Field(default_factory=dict)
    history: List[Dict[str, str]] = Field(default_factory=list)
    schema_map: Dict[str, Any] = Field(default_factory=dict)
    physics_open: bool = False
    kaiser_mandate: str = ""
    # Computed once per turn in orchestrator.py (Coverage's real gate_status
    # and whisper), read by pods/social/engine.py's run_turn -- same scratch
    # pattern as kaiser_mandate, avoids computing Coverage twice per turn.
    coverage_whisper: Optional[str] = None
    # Same pattern, Chat Manager's real output (core/reconcile.py's
    # build_chat_summary()): the single most pressing thing it couldn't
    # confidently classify as new/update/conflict, surfaced so the PM asks
    # the Director to clarify instead of guessing or silently dropping it.
    chat_whisper: Optional[str] = None
    # Coverage's own identity for the live turn's gate check -- see
    # SovereignRequest's docstring for why these two specifically (everything
    # else Coverage's L1/L3 needs is already on persona_config).
    coverage_mandate: Optional[str] = None
    coverage_skill: Optional[str] = None
    # Chat Manager's persisted state -- prior state in from SovereignRequest,
    # overwritten in place with this turn's advanced state during
    # process_turn(), same dual-purpose input/output pattern physics_open
    # and knowledge_bricks already use.
    chat_summary: List[Dict[str, Any]] = Field(default_factory=list)
    chat_summary_cursor: int = 0
