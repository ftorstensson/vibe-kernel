import os
from typing import Dict, Any

class MilestoneContract:
    """The dynamic 'VHS Tape' we slide into the Kernel."""
    def __init__(self, milestone_id: str, data: Dict[str, Any]):
        self.id = milestone_id
        self.label = data.get("label", "Untitled Milestone")
        
        # Turn A Logic: What the PM needs to extract (Kaiser's Checklist)
        self.input_goals = data.get("pm_checklist", [])
        
        # Turn B/C Logic: What the Strike Team needs to build (Insight Blocks)
        self.output_goals = data.get("research_structure", [])
        
        # The Strike Team configuration
        self.specialists = data.get("specialists", ["GENERALIST"])

def load_milestone(milestone_id: str, source: str = "LOCAL") -> MilestoneContract:
    """
    In the future, 'source' can be 'FIRESTORE'.
    For now, we use a local dictionary to get the engine running.
    """
    # This represents the data that would come from your Agency Lab UI
    MOCK_DB = {
        "THE_BIG_IDEA": {
            "label": "The Big Idea",
            "pm_checklist": [
                "The visceral soul/spark of the idea",
                "The specific problem being solved",
                "How it makes money (Commercial Logic)"
            ],
            "research_structure": [
                "THE_INSIGHT",
                "THE_ONE_SENTENCE",
                "THE_MONEY",
                "THE_ANTI_VISION"
            ],
            "specialists": ["COMMERCIAL_LEAD", "PRODUCT_REALIST", "SYNTHESIZER"]
        }
    }
    
    data = MOCK_DB.get(milestone_id, {})
    return MilestoneContract(milestone_id, data)
