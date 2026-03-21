from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text
import os

class Specialist:
    @staticmethod
    def analyze(role_name, research_data, milestone_goal):
        protocol_path = "registry/protocols/global/eli_protocol.md"
        eli_protocol = ""
        if os.path.exists(protocol_path):
            with open(protocol_path, "r") as f:
                eli_protocol = f.read()

        model, config = AgentFactory.get_partner_pm()
        
        # We physically inject the list of available source IDs into the mandate
        source_ids = ", ".join(research_data['sources'].keys())
        
        system_instruction = f"""
        ### THE MANDATE
        ROLE: {role_name}
        {eli_protocol}
        
        ### THE TRUTH (DATA)
        {research_data['raw_research']}
        
        ### THE LENS (CITATIONS)
        AVAILABLE_SOURCE_IDS: [{source_ids}]
        LAW: You MUST cite your claims using [ID] notation. 
        LAW: If you mention a market fact, follow it with the ID (e.g., "The market is growing [1]").
        LAW: Use only the IDs provided. Do not invent links.
        """
        
        response = model.generate_content(system_instruction, generation_config=config)
        return get_clean_text(response)
