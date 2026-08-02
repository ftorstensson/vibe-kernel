from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
import os

QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["questions"],
}


class Specialist:
    @staticmethod
    def generate_questions(role_name, brief, identity=None):
        """Finishes what the-co-founder/industrial_sandbox.py's Step 4 started:
        that prototype had a specialist generate questions via a real LLM call,
        but never actually parsed the result -- it fell back to a hardcoded
        stand-in list regardless of what the model said. Here the call is
        parsed for real via response_schema, same pattern as every other Phase
        1 function in this codebase (extract_facts, assess_coverage, etc).

        Shares registry/protocols/research_v1_2.md with Hound.hunt() -- the
        same "Intent-First: state your specific question before searching"
        standard applies to writing a question as to answering one. Takes the
        settled brief (derive_brief() output) rather than raw chat, so a
        question is grounded in the same settled truth every other Phase 1
        step now works from, not a scrollback window. identity shapes the
        questions toward what THIS role specifically needs verified, not a
        shared checklist every specialist would ask the same way."""
        protocol_path = "registry/protocols/research_v1_2.md"
        research_protocol = ""
        if os.path.exists(protocol_path):
            with open(protocol_path, "r") as f:
                research_protocol = f.read()

        model, config = AgentFactory.get_partner_pm()

        identity = identity or {}
        identity_block = "\n\n".join(filter(None, [
            identity.get("l0_mother"),
            identity.get("system_prompt"),
            identity.get("exo_brain"),
        ]))

        system_instruction = f"""
        ### THE MANDATE
        ROLE: {role_name}
        {research_protocol}

        Given the settled brief below, identify the 3 most critical, specific
        questions the Hounds must go research to ground your analysis in real
        evidence. State the specific intent before searching, per the protocol
        above -- each question must be concrete and search-optimized, not
        generic market-research boilerplate, and grounded in what THIS role
        specifically needs verified, not a shared checklist every specialist
        would ask the same way.

        ### THE IDENTITY (WHO YOU ARE)
        {identity_block or "No specific identity provided. Act as a generic specialist."}

        ### THE TRUTH (THE SETTLED BRIEF)
        {brief}
        """
        response = model.generate_content(system_instruction, generation_config=config, response_schema=QUESTIONS_SCHEMA)
        result = hammer_json(get_clean_text(response))
        return result.get("questions", [])

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
