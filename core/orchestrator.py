import re
from core.clock import TheClock
from pods.social.engine import SocialEngine
from pods.strike_team.engine import StrikeEngine
from pods.synthesis.engine import SynthesisEngine
from schema.kernel_schema import AgentEnvelope

class MasterOrchestrator:
    @staticmethod
    async def process_turn(envelope: AgentEnvelope, user_input: str):
        # --- THE CLOCK (Automatic Maintenance) ---
        await TheClock.maintenance_pulse(envelope)
        
        # 1. UPDATE SOCIAL HISTORY
        envelope.history.append({"role": "user", "content": user_input})
        
        # Identify "Go" signal
        is_go_signal = any(word in user_input.lower() for word in ["yes", "go", "do it", "fire", "start", "launch"])
        
        if is_go_signal and envelope.physics_open:
            print("[ORCHESTRATOR] Strike Team Authorized.")
            
            # 2. RUN STRIKE TEAM (Turn B) 
            strike_results = await StrikeEngine.run_industrial_strike(envelope)
            
            # 3. RUN SYNTHESIS (Turn C)
            new_truth = await SynthesisEngine.forge_truth(
                specialist_outputs=strike_results['reports'],
                milestone_config=envelope.manifest.milestone_config
            )
            
            # 4. THE WELD (Citations)
            for key, content in new_truth.items():
                if isinstance(content, str):
                    new_truth[key] = MasterOrchestrator.weld_links(content, strike_results['treasure_chest'])
            
            # 5. THE CONTEXT CHOKE (De-loading)
            envelope.knowledge_bricks.update(new_truth)
            envelope.kaiser_mandate = "RESEARCH COMPLETE. Discuss the new findings."
            
            # 6. SOCIAL RESPONSE
            response = await SocialEngine.run_turn(envelope)
            return {"social_response": response, "data_patch": new_truth, "status": "STABLE"}

        else:
            # Standard social turn
            response = await SocialEngine.run_turn(envelope)
            status = "AUTHORIZED" if envelope.physics_open else "PROBING"
            return {"social_response": response, "status": status}

    @staticmethod
    def weld_links(text, treasure_chest):
        def replace(match):
            source_id = match.group(1)
            if source_id in treasure_chest:
                s = treasure_chest[source_id]
                return f"[{s['title']}]({s['url']})"
            return f"[{source_id}]"
        return re.sub(r'\[(\d+)\]', replace, text)
