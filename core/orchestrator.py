import re
from core.clock import TheClock
from pods.social.engine import SocialEngine
from pods.strike_team.engine import StrikeEngine
from pods.synthesis.engine import SynthesisEngine
from schema.kernel_schema import AgentEnvelope

class MasterOrchestrator:
    @staticmethod
    async def process_turn(envelope: AgentEnvelope, user_input: str):
        # 1. The Clock (Self-Cleaning)
        await TheClock.maintenance_pulse(envelope)
        
        # 2. Add input to internal history
        envelope.history.append({"role": "user", "content": user_input})
        
        # 3. Detect Ignition (regex)
        is_go_signal = any(word in user_input.lower() for word in ["yes", "go", "fire", "start", "launch"])
        
        if is_go_signal and envelope.physics_open:
            print(f"[ORCHESTRATOR] Strike Team Authorized.")
            
            # Turn B: Parallel Hunt
            strike_results = await StrikeEngine.run_industrial_strike(envelope)
            
            # Turn C: Synthesis
            new_truth = await SynthesisEngine.forge_truth(
                specialist_outputs=strike_results['reports'],
                milestone_config=envelope.milestone_config
            )
            
            # The Weld (Inject Links)
            for key, content in new_truth.items():
                if isinstance(content, str):
                    new_truth[key] = MasterOrchestrator.weld_links(content, strike_results['treasure_chest'])
            
            # Update Knowledge
            envelope.knowledge_bricks.update(new_truth)
            envelope.kaiser_mandate = "RESEARCH COMPLETE. Discuss the new findings."
            
            # Social Turn
            response = await SocialEngine.run_turn(envelope)
            return {"social_response": response, "data_patch": new_truth, "status": "STABLE"}

        else:
            # Turn A: Social
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
