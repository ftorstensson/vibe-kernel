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
        
        sources = []
        try:
            # Native SDK Metadata Harvest
            for candidate in response.candidates:
                if hasattr(candidate, 'grounding_metadata'):
                    for chunk in candidate.grounding_metadata.grounding_chunks:
                        if chunk.web:
                            sources.append({
                                "title": chunk.web.title or "Source", 
                                "url": chunk.web.uri
                            })
        except Exception as e:
            print(f"[HOUND ERROR] Metadata harvest failed: {e}")
            
        return {
            "raw_research": get_clean_text(response),
            "sources": sources
        }
