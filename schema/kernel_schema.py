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
