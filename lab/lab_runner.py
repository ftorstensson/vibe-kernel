import asyncio
import json
import os
import sys

# Ensure the root directory is in the python path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schema.kernel_schema import AgentEnvelope, ProjectManifest
from pods.social.engine import SocialEngine

async def start_vibe_lab():
    # 1. LOAD THE BIG IDEA MILESTONE AS THE DEFAULT LAB SETTING
    with open("registry/milestones/the_big_idea.json", "r") as f:
        milestone_data = json.load(f)

    manifest = ProjectManifest(
        project_id="lab-test-session",
        current_milestone="THE_BIG_IDEA",
        milestone_config=milestone_data,
        persona_config={"name": "Master PM", "optimization_target": "Momentum", "loss_function": "Wank Factor"}
    )
    
    envelope = AgentEnvelope(manifest=manifest, history=[], physics_open=False)

    print("\n--- 🧪 VIBE LAB: PERSONA SANDBOX ---")
    print("LOGIC: Only the Social Pod is active. No Strike Team.")
    print("TIP: Edit registry/personas/master_pm/lens.md to change behavior.")
    print("------------------------------------\n")

    while True:
        user_input = input("\n[YOU]: ")
        if user_input.lower() in ["exit", "quit", "bye"]:
            break

        # Append to history
        envelope.history.append({"role": "user", "content": user_input})

        # Run the Social Engine (Turn A)
        print("\n[THINKING...]")
        response = await SocialEngine.run_turn(envelope)

        print("-" * 30)
        print(f"GATE STATUS: {'GREEN' if envelope.physics_open else 'RED'}")
        print(f"KAISER MANDATE: {envelope.kaiser_mandate}")
        print("-" * 30)
        print(f"\n[PM]: {response}")

if __name__ == "__main__":
    asyncio.run(start_vibe_lab())
