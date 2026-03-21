import asyncio
import json
import os
import sys

# Ensure imports work
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schema.kernel_schema import AgentEnvelope, ProjectManifest
from core.orchestrator import MasterOrchestrator

async def run_pressure_test():
    print("\n--- 🛠️ CLOCK PRESSURE TEST: FORCING TRIGGER ---")
    
    # GENERATE MEGA-JUNK (80,000 chars = ~20,000 tokens)
    # This will DEFINITELY smash the 4,000 token threshold
    mega_junk = "STRATEGIC_NOISE_DATA_FOR_COMPRESSION_TESTING " * 2000
    
    bricks = {
        "BRICK_1_OLD": "Historical data about 2024 beer market. " + mega_junk[:30000],
        "BRICK_2_OLD": "Historical data about tradie demographics. " + mega_junk[:30000],
        "BRICK_3_RECENT": "Current pricing strategy for the pilot. [3]",
        "BRICK_4_RECENT": "Partnership terms with Dan Murphy's. [4]",
        "BRICK_5_RECENT": "Initial user feedback from the site visit. [5]"
    }
    
    manifest = ProjectManifest(
        project_id="pressure-test-999",
        current_milestone="THE_BIG_IDEA",
        milestone_config={"pm_checklist_prompt": "Test clock.", "research_summary_structure": []},
        persona_config={"name": "Master PM", "optimization_target": "Momentum", "loss_function": "Wank Factor"}
    )
    
    envelope = AgentEnvelope(
        manifest=manifest, 
        history=[{"role": "user", "content": "Keep going."}], 
        knowledge_bricks=bricks,
        physics_open=True
    )

    initial_len = len(str(envelope.knowledge_bricks))
    print(f"INITIAL TEXT LENGTH: {initial_len} chars (~{initial_len // 4} tokens)")
    
    print("\n[SYSTEM] Triggering MasterOrchestrator...")
    result = await MasterOrchestrator.process_turn(envelope, "Just a social check.")
    
    final_bricks = envelope.knowledge_bricks
    print("\n--- 🔍 POST-COMPRESSION AUDIT ---")
    print(f"FINAL BRICK KEYS: {list(final_bricks.keys())}")
    
    if "FOUNDATIONAL_CONTEXT" in final_bricks:
        print("\n✅ SUCCESS: 'FOUNDATIONAL_CONTEXT' created.")
        print(f"COMPRESSED SUMMARY PREVIEW: {final_bricks['FOUNDATIONAL_CONTEXT'][:300]}...")
    else:
        print("\n❌ FAILURE: Compression did not trigger. Check Clock.THRESHOLD.")

    preserved = all(k in final_bricks for k in ["BRICK_3_RECENT", "BRICK_4_RECENT", "BRICK_5_RECENT"])
    if preserved:
        print("✅ SUCCESS: Last 3 bricks were kept verbatim.")
    else:
        print("❌ FAILURE: Recent bricks were accidentally compressed.")

if __name__ == "__main__":
    asyncio.run(run_pressure_test())
