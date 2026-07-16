from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text
import os

class Hound:
    @staticmethod
    def hunt(query: str):
        protocol_path = "registry/protocols/global/research_v1_2.md"
        research_protocol = ""
        if os.path.exists(protocol_path):
            with open(protocol_path, "r") as f:
                research_protocol = f.read()

        model, config = AgentFactory.get_hound()
        prompt = f"{research_protocol}\n\nTASK: Find evidence for: {query}"
        
        response = model.generate_content(prompt, generation_config=config)

        return {
            "raw_research": get_clean_text(response),
            "sources": getattr(response, "grounding_sources", [])
        }
