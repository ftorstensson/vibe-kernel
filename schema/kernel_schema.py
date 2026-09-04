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

    gatekeeper_mandate/gatekeeper_skill: Gatekeeper's own identity for the live
    turn's gate check (core/orchestrator.py) -- the "judge" archetype's real
    mandate content and the real functions_registry "Coverage" skill text
    (renamed from coverage_mandate/coverage_skill -- "Coverage" was the old
    function name; the fields now match the function's real name,
    Gatekeeper). Not derived from persona_config (that's the AGENT's own
    archetype, e.g. "navigator" for a PM persona, a different archetype
    than Gatekeeper's fixed "judge") -- but platform/app_manual/
    global_mission for Gatekeeper's L1/L3 are NOT duplicated here, they're
    the exact same values already on persona_config (platform-wide/app-
    wide, identical for the agent and for Gatekeeper), reused directly.
    Kept as a flat field here (not record-wrapped like persona_config's
    archetype/platform) since it's Kernel's own addition to the contract,
    not part of the shared persona_config shape Backend assembles the same
    way for every agent.

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
    this slice.

    chat_manager_mandate/chat_manager_skill: Chat Manager's own identity for
    the live turn's extraction step (core/orchestrator.py) -- the "scribe"
    archetype's real mandate content and the real functions_registry
    "Chat Manager" skill text, same pattern as gatekeeper_mandate/
    gatekeeper_skill above (Kernel's own addition to the contract, not part
    of the shared persona_config shape, kept flat not record-wrapped).

    keymaster_mandate/keymaster_skill: same pattern again, for
    confirm_launch_intent()'s real identity (core/ignition.py). Keymaster
    never had a donor archetype -- Backend resolves whatever real mandate
    content it has for Keymaster regardless of where it lives in Firestore;
    Kernel just receives the raw string, agnostic to that. No l3 for
    Keymaster -- confirmed no genuine mission/app_manual use for this
    function's narrow intent-classification task, unlike Coverage's/Chat
    Manager's topic-relevance judgments.

    partner_protocols: general, not per-function -- a list of
    {source: str, content: str} entries, each one function's standing
    explanation of what its own dynamic signal means (e.g. Gatekeeper's
    real functions_registry Partner Protocol content: "Gates are scored
    RED, AMBER, or GREEN..."), separate from gatekeeper_whisper/
    chat_whisper (the dynamic per-turn VALUES those explanations describe).
    Backend sends one entry per function that's structurally active this
    turn (required_questions truthy) -- the coarsest-grained thing it can
    know ahead of time, since assemble_envelope() runs entirely before
    Kernel's own turn and whether a whisper actually fires is computed
    later, inside Kernel's orchestrator, on data Backend hasn't seen yet.
    Kernel narrows structurally-active down to genuinely-fired at real
    composition time (pods/social/engine.py's _active_partner_protocols(),
    checked against the same gatekeeper_whisper/chat_whisper this turn
    already computed) before composing into L3 (see compose_l3_lens). One
    shared field rather than gatekeeper_partner_protocol/chat_manager_
    partner_protocol/... deliberately, so a new function's protocol needs
    no schema change to reach the PM -- same per-function-field-drift
    pattern the coverage_*->gatekeeper_* rename above just cleaned up.

    tool_law: Backend resolves the real registry_docs/tool_law content
    (content: JSON-stringified string, matching platform_logic's own
    convention exactly -- no "TOOL LAW:" label stored, added at
    composition time) and sends the parsed raw string, same pattern as
    platform.mandate/gatekeeper_mandate/... -- Kernel never fetches this
    itself. Optional/fail-open: pods/social/engine.py falls back to its
    own hardcoded DEFAULT_TOOL_LAW (verbatim copy of the real content) when
    this is None, since Tool Law is genuinely load-bearing for output
    safety (no tool-call syntax leaking into prose) and must never
    silently disappear just because Backend's resolve failed or hasn't
    shipped yet.

    project_map: [{phase, milestones: [{id, name, status, purpose}]}] --
    Backend's resolved view of the whole app's structure (every
    non-archived phase in order, each with its non-archived milestones in
    order, status the real execution_status), giving the Global PM actual
    visibility into what's done and what's next across the whole app
    instead of only ever seeing one milestone in isolation. Sent on every
    envelope, not just global calls, but composed into L3 only for the
    Global PM's own turn (pods/social/engine.py's run_global_turn via
    core/composition.py's compose_project_map_lens()) -- the task-scoped
    agent turn and every Function are already correctly scoped to one
    milestone and don't need the whole tree. Optional/fail-open, same
    pattern as partner_protocols/tool_law: default empty, a missing/
    unresolved project_map just means the Global PM composes without that
    context this turn, not a crash.

    Each milestone's real id is required, not optional decoration:
    run_global_turn's start_milestone_work tool (see pods/social/
    engine.py) needs a real, addressable id to fill in as the tool call's
    own milestone_id argument -- without it rendered somewhere in the
    composed PROJECT MAP text, the model has nothing valid to reference
    and can only guess or fabricate one. compose_project_map_lens()
    renders it inline per milestone.

    compiled_l1/compiled_l3: the Materialized View cutover -- Backend's
    compile step (see CompileIdentityRequest) now attaches these to every
    envelope as a dormant additive superset alongside the same raw
    ingredients (persona_config) Kernel has always composed from. When
    present, run_turn/run_global_turn read them directly instead of
    calling compose_l1_lines()/compose_l3_lens() -- the actual cutover,
    not a new capability. Optional/fail-open, same pattern as everything
    else in this contract: an app that hasn't republished under the new
    scheme sends these as None, and Kernel falls back to live composition
    from persona_config exactly as it always has, unchanged behavior.
    This mirrors Backend's own compiled-record fallback deliberately --
    same safety pattern on both sides of the same cutover, not two
    independent ones that could disagree.

    Scoped to the agent turn only (run_turn/run_global_turn), not the
    four Functions -- Gatekeeper/Chat Manager/Keymaster/Gate Maker still
    compose via compose_function_identity() from raw ingredients every
    turn, unchanged. Extending compilation to Functions is a real,
    separate future question, not assumed to fall out of this for free."""
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
    gatekeeper_mandate: Optional[str] = None
    gatekeeper_skill: Optional[str] = None
    chat_summary: List[Dict[str, Any]] = Field(default_factory=list)
    chat_summary_cursor: int = 0
    chat_manager_mandate: Optional[str] = None
    chat_manager_skill: Optional[str] = None
    partner_protocols: List[Dict[str, str]] = Field(default_factory=list)
    tool_law: Optional[str] = None
    project_map: List[Dict[str, Any]] = Field(default_factory=list)
    compiled_l1: Optional[str] = None
    compiled_l3: Optional[str] = None
    keymaster_mandate: Optional[str] = None
    keymaster_skill: Optional[str] = None

class SovereignResponse(BaseModel):
    """The Formalized Interface for the App to consume.

    chat_summary/chat_summary_cursor: the advanced state after this turn's
    Chat Manager pass, for Backend to persist forward as next turn's
    chat_summary/chat_summary_cursor input -- None when Chat Manager didn't
    run (or failed) this turn, meaning "nothing changed, keep what you
    already have," not "reset to empty." Chat Manager runs on BOTH the
    task-scoped path (when the milestone has required_questions) and the
    Global Agent path (is_global=True, unconditionally -- Fred's product
    call: continuous conversational awareness isn't gated behind milestone
    scope, see core/orchestrator.py's _run_chat_manager()); None is only
    the task-scoped-milestone-with-no-required_questions case, or a
    genuine Chat Manager failure on either path (both fail open).

    tool_call: {name, args} when the Global PM's own turn calls
    start_milestone_work (native Gemini function-calling, real litellm
    tool_calls parsed and json.loads()'d in core/agent_factory.py's
    LiteLLMResponse -- Backend never touches raw JSON-in-a-string).
    status is "TOOL_CALL" whenever this is set, same branch-on-status-
    first pattern as PROBING/AUTHORIZED/STABLE/GLOBAL. social_response is
    STILL populated on a TOOL_CALL turn (the model's own real
    acknowledgment text, litellm returns both together in one response --
    confirmed empirically, not assumed) -- real raw material for
    Backend's synthesis step, not meant to be shown to the Director
    directly as its own message (Fred's call: one synthesized final reply,
    not two)."""
    social_response: str
    status: str  # PROBING | AUTHORIZED | STABLE | GLOBAL | TOOL_CALL
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
    tool_call: Optional[Dict[str, Any]] = None
    # gate_status/whisper/assessments: the same real Gatekeeper output
    # (core/coverage.py's assess_coverage()) a task-scoped turn already
    # computes internally every time -- previously discarded except for
    # gate_status folded into physics_open and whisper folded into the
    # PM's own L1. Same field names as AssessCoverageResponse
    # (Test Lab's standalone endpoint) deliberately, so Backend's existing
    # persistence function for that shape needs no translation, just a
    # second real caller. All three None whenever Gatekeeper genuinely
    # didn't run this turn (no required_questions, already-launched and
    # correctly skipped, or a real exception) -- "nothing to report," not
    # a guess, same semantics chat_summary's own None already uses. Never
    # populated on a GLOBAL/TOOL_CALL turn -- there's no gate concept on
    # that path at all.
    gate_status: Optional[str] = None
    whisper: Optional[str] = None
    assessments: Optional[List[Dict[str, Any]]] = None

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

class ConfirmLaunchIntentRequest(BaseModel):
    """Functions Library, Keymaster's own standalone endpoint -- same
    reasoning as DeriveRequirementsRequest: confirm_launch_intent() needs no
    envelope/milestone state, just the recent conversation history, which
    the caller (Studio) already has.

    archetype/platform/skill are raw ingredients Backend already resolved
    -- Kernel composes L1 from them via compose_function_identity(), same
    as every other function. No app_manual/global_mission fields at all
    (not just unused) -- Keymaster's own design (core/ignition.py) has no
    L3 concept, confirmed no genuine mission/app_manual use for this
    narrow intent-classification task, so this request doesn't carry two
    fields that would always be None. app_id is identification only."""
    app_id: str
    history: List[Dict[str, Any]] = Field(default_factory=list)
    archetype: Optional[Dict[str, Any]] = None
    platform: Optional[Dict[str, Any]] = None
    skill: str = ""

class ConfirmLaunchIntentResponse(BaseModel):
    confirmed: bool

class SynthesizeDispatchRequest(BaseModel):
    """The last step of start_milestone_work's real round-trip (see
    pods/social/engine.py's run_global_turn / START_MILESTONE_WORK_TOOL):
    once Backend has resolved the dispatched milestone's own data and run
    it through its own turn (the same Gatekeeper->Keymaster->Strike-Team
    pipeline every task-scoped turn already uses), this turns the two raw
    pieces -- the Global PM's own initial reaction, and what actually
    happened at the milestone -- into ONE natural reply for the Director
    to see. Fred's explicit call: one synthesized message, never two
    separate chat bubbles for what should read as one continuous thought.

    persona_config: the blob, not raw archetype/platform records like
    other Functions Library endpoints use -- Backend's own choice,
    confirmed with them directly: they've never computed L1/L3 themselves
    (that composition has stayed entirely Kernel's job all session), and
    this is literally the same object their own execute_global call
    already built via assemble_envelope() -- passing raw l1/l3 strings
    instead would mean Backend taking on work it's never done, for zero
    benefit. Composed via compose_l1_lines/compose_l3_lens, same as every
    real agent turn.

    trigger_message: the Director's own real message that caused the tool
    call -- not a derived summary.

    global_response: the Global PM's own text from that SAME call
    (litellm returns it alongside the tool call itself -- see
    core/agent_factory.py's LiteLLMResponse). Optional/can be genuinely
    empty: confirmed by real testing, not assumed -- a real Vertex/Gemini
    call returned a tool call with EMPTY accompanying text, not always
    the non-empty acknowledgment an earlier test happened to produce. This
    function must compose sensibly either way, not assume it's always
    there.

    milestone_name/milestone_purpose: light grounding only, not the full
    PROJECT MAP entry -- this call needs just enough to talk about the
    right thing, not the whole map again.

    dispatch_status/dispatch_response: the dispatched milestone's own real
    turn result -- status (PROBING/AUTHORIZED/STABLE) and its own
    social_response. Deliberately NOT separate gate_status/whisper/brief
    fields: SovereignResponse has no gatekeeper_whisper/gate_status field
    today (checked, not assumed -- Backend confirmed by reading
    orchestrator.py's own return dicts), and dispatch_response already
    narratively reflects it -- Gatekeeper's whisper is folded into the
    milestone's own L1 mandate before that response is ever generated
    (see pods/social/engine.py's run_turn), and knowledge_bricks are
    updated before run_turn generates its response on a STABLE turn, so
    the brief's findings are already reflected in dispatch_response's own
    prose too. One real result string carries what would otherwise be
    three separate fields."""
    app_id: str
    persona_config: Dict[str, Any]
    trigger_message: str
    global_response: str = ""
    milestone_name: str = ""
    milestone_purpose: str = ""
    dispatch_status: str
    dispatch_response: str

class SynthesizeDispatchResponse(BaseModel):
    social_response: str

class CompileIdentityRequest(BaseModel):
    """The Materialized View scoping pass's first build item: wraps
    compose_l1_lines/compose_l3_lens/compose_function_identity (all
    unchanged) behind one endpoint Backend can call at publish time
    instead of only mid-turn, so the L1/L3 an agent or Function's identity
    actually resolves to can be written into a compiled record once,
    rather than recomposed from raw ingredients on every real turn.

    Kernel does zero new work here -- same composition logic, same
    "Backend resolves raw ingredients, Kernel composes" split this whole
    session has protected, just triggered from a new entry point. Kernel
    still writes nothing to Firestore itself; this returns strings,
    Backend persists them.

    Two raw-ingredient shapes, matching the two real shapes this
    contract's ingredients already come in elsewhere -- persona_config is
    the discriminator, not an explicit type flag, same "which fields are
    populated decides the path" precedent PreviewFunctionRequest's own
    l4_data already sets:

    persona_config given -> agent shape. The exact dict SovereignRequest.
    persona_config already is (archetype/platform record-wrapped,
    app_manual, global_mission, system_prompt, exo_brain). Composed via
    compose_l1_lines(persona_config)/compose_l3_lens(persona_config) with
    the real agent default_exo_brain -- NOT compose_function_identity,
    which deliberately suppresses that fallback for Functions Library
    entries (default_exo_brain=None) and would silently break an agent's
    real voice fallback if reused here by mistake. This is the same
    dispatch a real agent turn (pods/social/engine.py) already does today,
    just called at compile time instead of live-turn time.

    persona_config absent, archetype/platform/app_manual/global_mission
    given instead -> Functions Library shape, same flat raw-ingredient
    fields DeriveRequirementsRequest/AssessCoverageRequest/... already
    use. Composed via compose_function_identity(), identical to every
    other Functions Library endpoint's own identity resolution.

    L2 (persona/voice, an agent's own system_prompt) and L4 (skill, a
    Function's own functions_registry text) are NOT returned here --
    deliberately, not an oversight: neither one is actually composed by
    Kernel at all, in either the live-turn path or here. Both are already-
    resolved Firestore content Backend passes straight through unchanged;
    the only real composition work Kernel ever does is L1 and L3.
    Combining L2+L3 (an agent's own physical lens block) or L3+L4 (a
    Function's own physical lens block, compose_l4_lens) happens at
    prompt-assembly time on the live-turn path, not here -- this endpoint
    hands back the two layers Kernel actually transforms, not a
    pre-assembled block that would need re-splitting later."""
    app_id: str
    persona_config: Optional[Dict[str, Any]] = None
    archetype: Optional[Dict[str, Any]] = None
    platform: Optional[Dict[str, Any]] = None
    app_manual: Optional[str] = None
    global_mission: Optional[str] = None

class CompileIdentityResponse(BaseModel):
    l1: str
    l3: Optional[str] = None

class AgentPreviewRequest(BaseModel):
    """The agent-side sibling of PreviewFunctionRequest -- Test Lab has
    never had a way to preview an agent's own L1+L2+L3 composition
    without a live /kernel/invoke turn, unlike Functions (which have had
    /kernel/functions/preview all along). Same real gap CompileIdentityRequest's
    own docstring names for the compile step; this is the same gap
    surfacing again for Studio's Test Lab specifically, not a
    coincidence -- both need the identical composition Kernel already
    does for a real agent turn, just without an actual model call or a
    milestone-scoped envelope."""
    app_id: str
    agent_id: str
    persona_config: Dict[str, Any]

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
    "the second option") can resolve against already-established facts.

    archetype/platform/app_manual/global_mission/skill: raw ingredients
    Backend already resolved -- Kernel composes L1/L3 itself via
    compose_function_identity(), same as Gate Maker's/Gatekeeper's own
    endpoints. This endpoint no longer has any embedded extraction
    procedure of its own -- skill carries all of it."""
    history: List[Dict[str, Any]] = Field(default_factory=list)
    required_questions: Optional[List[str]] = None
    purpose: Optional[str] = None
    prior_chat_summary: List[Dict[str, Any]] = Field(default_factory=list)
    cursor: int = 0
    archetype: Optional[Dict[str, Any]] = None
    platform: Optional[Dict[str, Any]] = None
    app_manual: Optional[str] = None
    global_mission: Optional[str] = None
    skill: str = ""

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
    no Firestore fetch in between. kaiser_mandate/gatekeeper_whisper are pure
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
    # Computed once per turn in orchestrator.py (Gatekeeper's real gate_status
    # and whisper), read by pods/social/engine.py's run_turn -- same scratch
    # pattern as kaiser_mandate, avoids computing Gatekeeper twice per turn.
    # Renamed from coverage_whisper -- "Coverage" was the old function name.
    gatekeeper_whisper: Optional[str] = None
    # Same pattern, Chat Manager's real output (core/reconcile.py's
    # build_chat_summary()): the single most pressing thing it couldn't
    # confidently classify as new/update/conflict, surfaced so the PM asks
    # the Director to clarify instead of guessing or silently dropping it.
    chat_whisper: Optional[str] = None
    # Gatekeeper's own identity for the live turn's gate check -- see
    # SovereignRequest's docstring for why these two specifically (everything
    # else Gatekeeper's L1/L3 needs is already on persona_config). Renamed
    # from coverage_mandate/coverage_skill.
    gatekeeper_mandate: Optional[str] = None
    gatekeeper_skill: Optional[str] = None
    # Chat Manager's persisted state -- prior state in from SovereignRequest,
    # overwritten in place with this turn's advanced state during
    # process_turn(), same dual-purpose input/output pattern physics_open
    # and knowledge_bricks already use.
    chat_summary: List[Dict[str, Any]] = Field(default_factory=list)
    chat_summary_cursor: int = 0
    # Chat Manager's own identity for the live turn's extraction step -- see
    # SovereignRequest's docstring for why these two specifically (everything
    # else Chat Manager's L1/L3 needs is already on persona_config).
    chat_manager_mandate: Optional[str] = None
    chat_manager_skill: Optional[str] = None
    # See SovereignRequest's docstring -- straight copy-through, read by
    # pods/social/engine.py's compose_l3_lens() call, same pattern
    # persona_config's own fields already use.
    partner_protocols: List[Dict[str, str]] = Field(default_factory=list)
    # See SovereignRequest's docstring -- straight copy-through, read by
    # pods/social/engine.py at both run_turn/run_global_turn call sites,
    # falling back to DEFAULT_TOOL_LAW there when None.
    tool_law: Optional[str] = None
    # See SovereignRequest's docstring -- straight copy-through, read ONLY
    # by pods/social/engine.py's run_global_turn (via core/composition.py's
    # compose_project_map_lens()), not run_turn or any Function -- those
    # stay correctly scoped to one milestone.
    project_map: List[Dict[str, Any]] = Field(default_factory=list)
    # See SovereignRequest's docstring -- the Materialized View cutover.
    # Straight copy-through, read by pods/social/engine.py's run_turn/
    # run_global_turn in place of a live compose_l1_lines()/
    # compose_l3_lens() call whenever present.
    compiled_l1: Optional[str] = None
    compiled_l3: Optional[str] = None
    # Keymaster's own identity for confirm_launch_intent() -- see
    # SovereignRequest's docstring. No l3 field: confirmed no genuine
    # mission/app_manual use for this function.
    keymaster_mandate: Optional[str] = None
    keymaster_skill: Optional[str] = None
