from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class SovereignRequest(BaseModel):
    """The minimalist v21.1 Sovereign Contract."""
    app_id: str
    project_id: str
    milestone_id: str
    user_message: str
    agent_id: Optional[str] = "master_pm"

class AgentEnvelope(BaseModel):
    """Internal briefcase containing the Map and the Data."""
    app_id: str
    project_id: str
    milestone_config: Dict[str, Any]
    persona_config: Dict[str, Any]
    knowledge_bricks: Dict[str, str] = Field(default_factory=dict)
    history: List[Dict[str, str]] = Field(default_factory=list)
    schema_map: Dict[str, Any] = Field(default_factory=dict) # The ARM
    physics_open: bool = False
    kaiser_mandate: str = ""
