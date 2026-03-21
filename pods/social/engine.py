from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder
from schema.kernel_schema import AgentEnvelope

class SocialEngine:
    @staticmethod
    async def run_turn(envelope: AgentEnvelope):
        clerk_model, clerk_config = AgentFactory.get_clerk()
        
        # 1. THE AUDIT (Clinical)
        checklist_prompt = envelope.manifest.milestone_config.get('pm_checklist_prompt', "")
        structure = envelope.manifest.milestone_config.get('research_summary_structure', [])
        
        clerk_mandate = "ACT AS A CYNICAL INDUSTRIAL AUDITOR."
        clerk_lens = f"""
        CHECKLIST_PROMPT: {checklist_prompt}
        REQUIRED_STRUCTURE: {structure}
        
        RULE: You are looking for 'Proprietary Logic' (The User's Edge).
        RULE: If the user provides only info that a Hound can find on Google, stay RED.
        RULE: If the 'Proprietary' requirements are missing, flag them as missing.
        """
        
        clerk_truth = f"CHAT_HISTORY: {envelope.history[-5:]}"
        clerk_work_order = PromptBuilder.assemble(
            mandate=clerk_mandate, 
            lens=clerk_lens, 
            truth=clerk_truth + "\nReturn ONLY JSON: {\"physics_gate\": \"RED/GREEN\", \"missing_logic\": \"What specific proprietary insight is missing?\"}"
        )
        
        clerk_resp = clerk_model.generate_content(clerk_work_order, generation_config=clerk_config)
        clerk_report = hammer_json(get_clean_text(clerk_resp))
        
        # 2. THE KAISER (Physics Logic)
        envelope.physics_open = (clerk_report.get("physics_gate") == "GREEN")
        
        if not envelope.physics_open:
            missing = clerk_report.get("missing_logic", "Founder-level edge.")
            envelope.kaiser_mandate = f"PHYSICS LOCKED. You are missing proprietary logic regarding: {missing}. Do not start the team. Probe the user for their unique 'Edge'."
        else:
            envelope.kaiser_mandate = "PHYSICS OPEN. The proprietary fuel is present. Stop probing and offer to fire the Strike Team."

        # 3. THE PM (Social Partner)
        pm_model, pm_config = AgentFactory.get_partner_pm()
        
        # Load Persona DNA & Lens
        with open("registry/personas/master_pm/dna.md", "r") as f: dna = f.read()
        with open("registry/personas/master_pm/lens.md", "r") as f: lens = f.read()

        pm_mandate = f"[STATUS: {'GREEN' if envelope.physics_open else 'RED'}]\nKAISER MANDATE: {envelope.kaiser_mandate}"
        pm_truth = f"ESTABLISHED_TRUTH: {envelope.knowledge_bricks}\nCURRENT_CHAT: {envelope.history[-5:]}"

        work_order = PromptBuilder.assemble(mandate=pm_mandate, lens=f"{dna}\n{lens}", truth=pm_truth)
        response = pm_model.generate_content([work_order], generation_config=pm_config)
        
        return get_clean_text(response)
