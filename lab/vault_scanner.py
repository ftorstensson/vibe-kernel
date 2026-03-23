from google.cloud import firestore
import os

db = firestore.Client(project="vibe-agent-final")

def scan():
    print("\n--- 🔍 VAULT SCANNER: LOCATING SOVEREIGN DATA ---")
    
    # Check Personas
    print("\n[CHECK] Looking in 'agency_roster'...")
    roster = db.collection("agency_roster").stream()
    ids = [d.id for d in roster]
    print(f"Found IDs: {ids if ids else 'EMPTY'}")

    # Check Milestones (The complex path)
    print("\n[CHECK] Looking in 'agency_registry/milestones/definitions'...")
    try:
        m_col = db.collection("agency_registry").document("milestones").collection("definitions").stream()
        m_ids = [d.id for d in m_col]
        print(f"Found Milestone IDs: {m_ids if m_ids else 'EMPTY'}")
    except Exception as e:
        print(f"Path invalid: {e}")

    # Check for common alternative paths
    print("\n[CHECK] Looking for top-level 'milestones' or 'milestone_definitions'...")
    alt1 = [d.id for d in db.collection("milestones").stream()]
    print(f"milestones (top-level): {alt1 if alt1 else 'EMPTY'}")
    
    alt2 = [d.id for d in db.collection("milestone_definitions").stream()]
    print(f"milestone_definitions: {alt2 if alt2 else 'EMPTY'}")

if __name__ == "__main__":
    scan()
