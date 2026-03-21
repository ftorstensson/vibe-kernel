from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder

class SynthesisEngine:
    @staticmethod
    async def forge_truth(specialist_outputs: list, milestone_config: dict):
        model, config = AgentFactory.get_partner_pm()
        
        # Pull the structure from the milestone (now supporting dynamic types)
        structure = milestone_config.get('research_summary_structure', [])
        
        mandate = """
        ACT AS THE EDITOR-IN-CHIEF.
        Synthesize raw research into the RESEARCH_STRUCTURE.
        
        LAW: You MUST check the TYPE of each requirement in the structure.
        - If TYPE is 'TEXT': Write a dense, strategic summary.
        - If TYPE is 'VISUAL_SPEC': Write a high-fidelity TECHNICAL SPECIFICATION (Markdown) that a designer or UI agent can use to build an image/component.
        
        LAW: Preserve [ID] citations. Return ONLY JSON.
        """
        
        lens = f"STRUCTURE: {structure}\nTONE: Goldsmith (Venture-Grade)."
        truth = f"RAW_SPECIALIST_REPORTS: {specialist_outputs}"
        
        work_order = PromptBuilder.assemble(mandate=mandate, lens=lens, truth=truth)
        response = model.generate_content(work_order, generation_config=config)
        return hammer_json(get_clean_text(response))
