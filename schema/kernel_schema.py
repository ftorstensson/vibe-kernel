from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class SovereignRequest(BaseModel):
    """The App sends IDs; the Kernel fetches the Physics."""
    app_id: str
    project_id: str
    milestone_id: str
    user_message: str
    agent_id: Optional[str] = "master_pm"

class SovereignResponse(BaseModel):
    """The Formalized Interface for the App to consume."""
    social_response: str
    status: str  # PROBING | AUTHORIZED | STABLE
    data_patch: Optional[Dict[str, str]] = None

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
