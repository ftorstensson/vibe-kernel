from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder

class MaintenanceEngine:
    @staticmethod
    async def compress_truth(historical_bricks: list):
        """
        The Clock Logic: Compresses old bricks into a dense foundational summary.
        """
        model, config = AgentFactory.get_clerk() # Use Flash
        
        mandate = "ACT AS A KERNEL MAINTENANCE JANITOR."
        lens = "Goal: Compress multiple strategy bricks into one dense FOUNDATIONAL_CONTEXT block. Preserve all Source IDs ([1], [2])."
        truth = f"HISTORICAL_BRICKS: {historical_bricks}"
        
        work_order = PromptBuilder.assemble(mandate=mandate, lens=lens, truth=truth + "\nReturn ONLY the compressed text summary. No JSON. No Markdown.")
        
        response = model.generate_content(work_order, generation_config=config)
        return get_clean_text(response)
