from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder
from schema.kernel_schema import AgentEnvelope

class SocialEngine:
    @staticmethod
    async def run_turn(envelope: AgentEnvelope):
        clerk_model, clerk_config = AgentFactory.get_clerk()
        
        # Pull dynamic keys from the ARM (App Registry Map)
        checklist_key = envelope.schema_map["schema_keys"]["pm_checklist"]
        checklist_prompt = envelope.milestone_config.get(checklist_key, "Find the spark.")
        
        # 1. CLERK AUDIT
        clerk_mandate = "ACT AS A CYNICAL INDUSTRIAL AUDITOR."
        clerk_lens = f"CRITERIA: {checklist_prompt}\nSTRUCTURE_EXPECTED: {envelope.schema_map['schema_keys']['brick_list']}"
        clerk_truth = f"CHAT_HISTORY: {envelope.history[-5:]}"
        
        clerk_work_order = PromptBuilder.assemble(
            mandate=clerk_mandate,
            lens=clerk_lens,
            truth=clerk_truth + "\nReturn ONLY JSON: {\"physics_gate\": \"RED/GREEN\", \"missing_logic\": \"string\"}"
        )
        
        clerk_resp = clerk_model.generate_content(clerk_work_order, generation_config=clerk_config)
        clerk_report = hammer_json(get_clean_text(clerk_resp))
        
        # 2. KAISER PHYSICS
        envelope.physics_open = (clerk_report.get("physics_gate") == "GREEN")
        if not envelope.physics_open:
            missing = clerk_report.get("missing_logic", "Proprietary insight.")
            envelope.kaiser_mandate = f"PHYSICS LOCKED. Missing: {missing}. Probe blunt."
        else:
            envelope.kaiser_mandate = "PHYSICS OPEN. Offer to fire Strike Team."

        # 3. PM SOCIAL
        pm_model, pm_config = AgentFactory.get_partner_pm()
        pm_dna = envelope.persona_config.get("dna", "Lead Co-founder.")
        pm_lens = envelope.persona_config.get("lens", "Blunt, high-speed facilitator.")
        
        pm_mandate = f"[STATUS: {'GREEN' if envelope.physics_open else 'RED'}]\nKAISER MANDATE: {envelope.kaiser_mandate}"
        pm_truth = f"ESTABLISHED_KNOWLEDGE: {envelope.knowledge_bricks}\nCURRENT_CHAT: {envelope.history[-5:]}"

        work_order = PromptBuilder.assemble(mandate=pm_mandate, lens=f"{pm_dna}\n{pm_lens}", truth=pm_truth)
        response = pm_model.generate_content([work_order], generation_config=pm_config)
        
        return get_clean_text(response)
