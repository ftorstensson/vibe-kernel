import asyncio
from pods.strike_team.hound import Hound
from pods.strike_team.specialist import Specialist
from schema.kernel_schema import AgentEnvelope

class StrikeEngine:
    @staticmethod
    async def run_industrial_strike(envelope: AgentEnvelope):
        """
        Turn B: The Parallel Strike.
        1. Scout Queries
        2. Parallel Hunt
        3. Specialist Analysis with Sidecar URLs
        """
        print("--- 🛠️ STRIKE TEAM: INITIALIZING PARALLEL HUNT ---")
        
        # 1. SCOUTING (Generating 3 Queries)
        # For speed, we'll derive these from the milestone goals
        queries = [
            f"Market growth and competitors for {envelope.manifest.project_id}",
            f"Commercial revenue models for {envelope.manifest.project_id}",
            f"Technical feasibility and risks for {envelope.manifest.project_id}"
        ]

        # 2. THE PARALLEL HUNT (Hounds)
        # This fires all searches at once
        hunt_tasks = [asyncio.to_thread(Hound.hunt, q) for q in queries]
        hunt_results = await asyncio.gather(*hunt_tasks)

        # 3. CONSOLIDATE THE TREASURE CHEST (URLs)
        treasure_chest = {}
        all_raw_data = ""
        source_counter = 1
        
        for result in hunt_results:
            all_raw_data += f"\n{result['raw_research']}"
            for source in result['sources']:
                treasure_chest[str(source_counter)] = source
                source_counter += 1

        # 4. SPECIALIST ANALYSIS
        # Each specialist receives the SAME data and the SAME Treasure Chest IDs
        specialists = envelope.manifest.milestone_config.get('specialists', [])
        reports = []
        
        for role in specialists:
            print(f" -> {role} is analyzing data...")
            analysis = Specialist.analyze(
                role_name=role,
                research_data={"raw_research": all_raw_data, "sources": treasure_chest},
                milestone_goal=envelope.manifest.current_milestone
            )
            reports.append({"role": role, "content": analysis})
            
        return {"reports": reports, "treasure_chest": treasure_chest}
