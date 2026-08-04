from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class SovereignRequest(BaseModel):
    """The App sends IDs; the Kernel fetches the Physics."""
    app_id: str
    project_id: str
    milestone_id: str
    user_message: str
    agent_id: Optional[str] = "master_pm"
    is_global: bool = False  # Global Agent conversation: PM-only, no Clerk/gate

class SovereignResponse(BaseModel):
    """The Formalized Interface for the App to consume."""
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

class DeriveRequirementsRequest(BaseModel):
    """Functions Library, entry 1: derive_requirements() needs no conversation
    state -- no project_id/milestone_id, no envelope, no chat history -- just
    the milestone's own purpose and target output structure, which the caller
    (Studio) already has. Kept separate from SovereignRequest deliberately:
    this isn't a conversational turn.

    app_id is real, not optional: it resolves the function's actual identity
    (L1 via core/bootloader.py's resolve_function_identity -- functions_registry,
    archetype_registry, and the app's own app_manual), not a hand-written
    mandate baked into the function itself. Everything but app_manual is
    platform-wide, but app_manual is genuinely app-specific, so app_id is
    still required."""
    app_id: str
    purpose: str
    target_structure: List[Any] = Field(default_factory=list)

class DeriveRequirementsResponse(BaseModel):
    rationale: str
    ignition_inputs: List[Dict[str, str]]

class PreviewFunctionRequest(BaseModel):
    """Test Lab preview -- function-agnostic (resolve_function_identity() only
    needs app_id/function_name), but each function's L4/L5 data has its own
    shape, so this request carries both a legacy, Requirements-specific path
    and a generic one:

    purpose/target_structure: Requirements' real, already-live shape --
    Backend's proxy and Studio's Requirements Input panel consume this in
    production today. Kept exactly as-is, not touched, so that integration
    doesn't break.

    l4_data/l5_data: generic pass-through for any other function (e.g.
    Coverage's required_questions/durable_facts) -- echoed straight into the
    response's l4/l5 alongside the resolved skill, no function-specific
    field names hardcoded. l4_data is the discriminator: if a caller sends
    it, the generic path is used instead of the legacy purpose/target_structure
    one (see main.py's invoke_preview_function).

    This endpoint does no model call itself -- l4_data/l5_data are just
    echoed back, same as purpose/target_structure always were -- cheap to
    fetch purely for display. (A real L5 fetch, e.g. Coverage's durable_facts,
    is a separate concern with a real cost -- see /kernel/durable_facts --
    the caller fetches it first, then optionally passes the result in here
    via l5_data for display alongside L1/L3.)"""
    app_id: str
    function_name: str
    purpose: Optional[str] = None
    target_structure: List[Any] = Field(default_factory=list)
    l4_data: Optional[Dict[str, Any]] = None
    l5_data: Optional[List[Any]] = None

class PreviewFunctionResponse(BaseModel):
    """The real, literal prompt inputs a Functions Library entry's model call
    would use -- composition only, no model call, no rationale/ignition_inputs.
    Named by layer (L1-L5) to match the same five-layer shape real agent turns
    are composed from (see core/composition.py, pods/social/engine.py), so the
    Test Lab can render all five boxes consistently across agents and
    functions -- with L2/L5 explicitly present-but-empty for a stateless
    function like Requirements, not silently missing.

    l1: Mandate -- archetype_l0_mother + platform_logic, via
        resolve_function_identity()/compose_l1_lines(). Real.
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
        supplies it (e.g. Coverage's durable_facts, fetched separately via
        /kernel/durable_facts and passed through here for display)."""
    l1: str
    l2: Optional[str] = None
    l3: Optional[str] = None
    l4: Dict[str, Any]
    l5: Optional[List[Any]] = None

class AssessCoverageRequest(BaseModel):
    """Coverage's own standalone endpoint, same reasoning as
    DeriveRequirementsRequest: Coverage needs no envelope/history of its
    own -- just the milestone's required_questions (L4) and the current
    durable_facts (L5, the caller already has these -- from a live turn, or
    fetched standalone via /kernel/durable_facts). app_id resolves the real
    identity (L1 judge archetype + L3 mission/app_manual + Skill) via
    resolve_function_identity(app_id, "Coverage") -- same call the live turn
    pipeline (core/orchestrator.py) already uses."""
    app_id: str
    required_questions: List[str] = Field(default_factory=list)
    durable_facts: List[Dict[str, Any]] = Field(default_factory=list)

class AssessCoverageResponse(BaseModel):
    assessments: List[Dict[str, Any]]
    gate_status: str
    whisper: str

class DurableFactsRequest(BaseModel):
    """Fetches a project's real, current durable_facts (L5) on demand --
    NOT free like PreviewFunctionResponse's other layers: build_durable_facts()
    genuinely calls the model (extract_facts, then a reconcile_fact pass per
    fact), so this is a deliberate, on-demand fetch, not something to poll or
    auto-fire on every render. Lives outside /kernel/functions/ -- this isn't
    a Functions Library identity concern, it's a real cost operation over a
    project's stored history. project_id is the same value Studio calls
    task_id for task-scoped conversations (confirmed 1:1, no separate
    mapping)."""
    app_id: str
    project_id: str

class DurableFactsResponse(BaseModel):
    durable_facts: List[Dict[str, Any]]

class AgentEnvelope(BaseModel):
    """Internal briefcase containing the Map and the Data."""
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
