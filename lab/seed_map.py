from google.cloud import firestore
import os

db = firestore.Client(project="vibe-agent-final")

def seed():
    print("\n--- 🗺️ SEEDING MASTER MAP: VIBE_DESIGN_LAB ---")
    map_data = {
        "paths": {
            "milestones": "agency_registry/milestones/definitions",
            "personas": "agency_roster",
            "user_projects": "cofounder_boards"
        },
        "schema_keys": {
            "manifest_root": "vibe_manifest",
            "clerk_facts": "mission_manifesto",
            "ledger_root": "strategyLedger",
            "brick_list": "research_architecture",
            "pm_checklist": "checklist_prompt"
        }
    }
    db.collection("_kernel_registry").document("vibe_design_lab").set(map_data)
    print("✅ SUCCESS: App Registry Map (ARM) seeded to Firestore.")

if __name__ == "__main__":
    seed()
