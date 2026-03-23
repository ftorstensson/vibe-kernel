import asyncio
from google.cloud import firestore
import os

db = firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT", "vibe-agent-final"))

class SovereignBootloader:
    @staticmethod
    async def assemble_envelope(req):
        # --- BOOTSTRAP 0: THE MAP (CARTOGRAPHY) ---
        map_ref = db.collection("_kernel_registry").document(req.app_id)
        arm_doc = map_ref.get()
        
        if not arm_doc.exists:
            # Mandate v21.1: Safety Valve
            raise ValueError(f"502 Map Error: Kernel is Blind. No App Registry Map found for {req.app_id}")
        
        arm = arm_doc.to_dict()
        paths = arm.get("paths", {})
        keys = arm.get("schema_keys", {})

        # --- BOOTSTRAP 1: PARALLEL CONFIG FETCH ---
        # IDs are normalized to lowercase per v21.0 audit
        m_id = req.milestone_id.lower()
        a_id = (req.agent_id or "master_pm").lower()
        
        milestone_ref = db.collection(paths["milestones"]).document(m_id)
        persona_ref = db.collection(paths["personas"]).document(a_id)
        project_ref = db.collection(paths["user_projects"]).document(req.project_id)

        m_task = asyncio.to_thread(milestone_ref.get)
        p_task = asyncio.to_thread(persona_ref.get)
        proj_task = asyncio.to_thread(project_ref.get)

        m_doc, p_doc, proj_doc = await asyncio.gather(m_task, p_task, proj_task)

        if not m_doc.exists or not p_doc.exists:
            raise Exception(f"Sovereign Fetch Failed: Milestone ({m_id}) or Persona ({a_id}) missing at mapped paths.")

        # --- BOOTSTRAP 2: STATE EXTRACTION (DE-LOADING) ---
        project_data = proj_doc.to_dict() if proj_doc.exists else {}
        
        # Traverse the doc using the ARM's schema_keys
        manifest = project_data.get(keys["manifest_root"], {})
        ledger = manifest.get(keys["ledger_root"], {})
        
        knowledge_bricks = {}
        for brick_id, entry in ledger.items():
            if entry.get("status") == "STABLE":
                history = entry.get("history", [])
                if history:
                    # De-loading: Keep only prose
                    knowledge_bricks[brick_id] = history[-1].get("summary_prose", "Stabilized.")

        return {
            "milestone_config": m_doc.to_dict(),
            "persona_config": p_doc.to_dict(),
            "knowledge_bricks": knowledge_bricks,
            "history": manifest.get("chat_history", []),
            "schema_map": arm
        }
