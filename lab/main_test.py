import asyncio
import json
from schema.kernel_schema import AgentEnvelope, ProjectManifest
from core.orchestrator import MasterOrchestrator

async def run_opportunity_test():
    # 1. LOAD THE OPPORTUNITY CONTRACT
    with open("registry/milestones/the_opportunity.json", "r") as f:
        milestone_data = json.load(f)

    manifest = ProjectManifest(
        project_id="tradie-beer-opportunity",
        current_milestone="THE_OPPORTUNITY",
        milestone_config=milestone_data,
        # Load PM Persona from Registry
        persona_config={"name": "Master PM", "optimization_target": "Momentum", "loss_function": "Wank Factor"}
    )
    
    envelope = AgentEnvelope(manifest=manifest, history=[], physics_open=False)

    print(f"\n--- 🚀 SWITCHING TO MILESTONE: {milestone_data['label']} ---")
    
    # User provides a semi-detailed spark to see if the Cynical Clerk is satisfied
    user_input = "The timing is right because craft beer is peaking but nobody is talking to the tradie segment authentically. Our edge is my 15 years in construction and my partnership with a micro-brewery."
    
    print(f"[USER]: {user_input}")
    turn = await MasterOrchestrator.process_turn(envelope, user_input)
    
    print(f"\n[CLERK GATE]: {turn['status']}")
    print(f"[PM]: {turn['social_response']}")

if __name__ == "__main__":
    asyncio.run(run_opportunity_test())
