from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class ProjectManifest(BaseModel):
    """The 'Software' configuration for the current project."""
    project_id: str
    current_milestone: str
    milestone_config: Dict[str, Any]
    persona_config: Dict[str, Any]

class AgentEnvelope(BaseModel):
    """The Universal 'Briefcase' that moves between pods."""
    manifest: ProjectManifest
    history: List[Dict[str, str]] = Field(default_factory=list)
    knowledge_bricks: List[Dict[str, Any]] = Field(default_factory=list)
    physics_open: bool = False
    kaiser_mandate: str = "Proceed with discovery."
    internal_thought: str = ""
