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
    """Test Lab preview: same fields as DeriveRequirementsRequest, plus
    function_name -- resolve_function_identity() is already function-agnostic
    (app_id, function_name), so this isn't scoped to Requirements alone, even
    though Requirements is the only Functions Library entry that exists today.
    purpose/target_structure are caller-supplied (same as
    DeriveRequirementsRequest) and just echoed back alongside the resolved
    l1/skill -- this endpoint does no model call, so it's cheap to fetch
    purely for display."""
    app_id: str
    function_name: str
    purpose: str
    target_structure: List[Any] = Field(default_factory=list)

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
        function) plus the data (the real purpose + target_structure for the
        milestone, echoed straight back from the request). Both define the
        task, so both live here together.
    l5: History (prior chat turns). Not applicable -- derive_requirements()
        runs once per milestone as a planning step, no conversation state.
        None by design, not a missing fetch."""
    l1: str
    l2: Optional[str] = None
    l3: Optional[str] = None
    l4: Dict[str, Any]
    l5: Optional[List[Any]] = None

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
