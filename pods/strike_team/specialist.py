from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text
import os

class Specialist:
    @staticmethod
    def analyze(role_name, research_data, identity=None):
        """identity (optional): {"l0_mother": archetype function text,
        "system_prompt": persona voice text, "exo_brain": knowledge-base text}.
        The FUNCTION (eli_protocol.md, how to produce an ELI report) is shared
        and generic; identity is the specialist's actual voice -- both compose
        into one mandate, neither replaces the other."""
        protocol_path = "registry/protocols/eli_protocol.md"
        eli_protocol = ""
        if os.path.exists(protocol_path):
            with open(protocol_path, "r") as f:
                eli_protocol = f.read()

        model, config = AgentFactory.get_partner_pm()

        identity = identity or {}
        identity_block = "\n\n".join(filter(None, [
            identity.get("l0_mother"),
            identity.get("system_prompt"),
            identity.get("exo_brain"),
        ]))

        # We physically inject the list of available source IDs into the mandate
        source_ids = ", ".join(research_data['sources'].keys())

        system_instruction = f"""
        ### THE MANDATE
        ROLE: {role_name}
        {eli_protocol}

        ### THE IDENTITY (WHO YOU ARE)
        {identity_block or "No specific identity provided. Act as a generic specialist."}

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
