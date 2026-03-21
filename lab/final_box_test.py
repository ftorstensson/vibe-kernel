import asyncio
import json
import os
import sys

# Ensure imports work from root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from schema.kernel_schema import AgentEnvelope, ProjectManifest
from core.orchestrator import MasterOrchestrator

async def run_full_integration_test():
    print("\n--- 🏁 STARTING FULL-SYSTEM INTEGRATION TEST (v2.1) ---")

    # 1. LOAD THE MILESTONE (The VHS Tape)
    with open("registry/milestones/the_big_idea.json", "r") as f:
        milestone_data = json.load(f)

    # 2. INITIALIZE MANIFEST
    manifest = ProjectManifest(
        project_id="final-v21-test",
        current_milestone="THE_BIG_IDEA",
        milestone_config=milestone_data,
        persona_config={"name": "Master PM", "optimization_target": "Momentum", "loss_function": "Wank Factor"}
    )
    
    # Start with an empty briefcase
    envelope = AgentEnvelope(manifest=manifest, history=[], knowledge_bricks={}, physics_open=False)

    # --- TURN 1: THE VAGUE SPARK ---
    print("\n[USER]: I want to build a beer app for tradies.")
    turn_1 = await MasterOrchestrator.process_turn(envelope, "I want to build a beer app for tradies.")
    print(f"\n[GATE]: {turn_1['status']}")
    print(f"[PM]: {turn_1['social_response']}")

    # --- TURN 2: THE PROPRIETARY EDGE ---
    print("\n[USER]: My edge is my 15 years on site. The revenue is a pub subscription for 'Friday Specials' pushed to site crews.")
    turn_2 = await MasterOrchestrator.process_turn(envelope, "My edge is my 15 years on site. The revenue is a pub subscription for 'Friday Specials' pushed to site crews.")
    print(f"\n[GATE]: {turn_2['status']}")
    print(f"[PM]: {turn_2['social_response']}")

    # --- TURN 3: THE ACTION (Strike Team + Synthesis + Clock) ---
    if turn_2['status'] == "AUTHORIZED":
        print("\n[USER]: Yes, fire the team. Do it.")
        print("[SYSTEM] Parallel Hounds and Goldsmith activated... (This will take ~40s)")
        
        turn_3 = await MasterOrchestrator.process_turn(envelope, "Yes, fire the team. Do it.")
        
        print("\n--- 🏗️ ASSEMBLY COMPLETE ---")
        print(f"[PM RESPONSE]: {turn_3['social_response']}")
        
        print("\n[DATA PATCH (Stabilized Bricks)]: ")
        for key, brick in turn_3['data_patch'].items():
            # Check for Markdown links [Title](URL)
            has_links = "[" in brick and "](" in brick
            print(f"\n>> {key} (Links Detected: {has_links}):")
            print(f"{brick[:250]}...")

    print("\n--- ✅ FULL SYSTEM TEST COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(run_full_integration_test())
