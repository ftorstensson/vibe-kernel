import asyncio
import json
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

        # --- BOOTSTRAP 1B: ARCHETYPE RULES (L1) ---
        # Fail open: an agent without archetype_id, or a lookup that fails for any
        # reason, must never break the turn -- it just means no archetype content
        # gets layered in, same as today's behavior.
        persona_config = p_doc.to_dict()
        archetype_id = persona_config.get("archetype_id")
        if archetype_id:
            try:
                archetype_doc = await asyncio.to_thread(
                    db.collection("archetype_registry").document(archetype_id).get
                )
                if archetype_doc.exists:
                    persona_config["archetype_l0_mother"] = archetype_doc.to_dict().get("l0_mother")
            except Exception:
                pass

        # App-specific Manual (L1) -- one value per app, lives on the ARM doc
        # already fetched above, so no extra read. .get() defaults to None,
        # same fail-open behavior as archetype_l0_mother.
        persona_config["app_manual"] = arm.get("app_manual")

        # Global Mission (L1) -- app-level vision, same ARM doc as app_manual,
        # no extra read. Same fail-open behavior; likely missing until Backend's
        # sync_projection write lands.
        persona_config["global_mission"] = arm.get("global_mission")

        # Platform-wide Logic (L1) -- one value for the whole platform, not
        # per-app or per-archetype, so it's an independent fetch (not on the
        # ARM). Likely missing today since nothing's authored it yet -- same
        # fail-open principle: a missing/empty doc contributes nothing to L1.
        try:
            platform_doc = await asyncio.to_thread(
                db.collection("registry_docs").document("vibe_studio_logic").get
            )
            raw = platform_doc.to_dict().get("content") if platform_doc.exists else None
            # registry_docs is a generic store: Studio always JSON.stringify()s on
            # save and JSON.parse()s on read, by design (same as platform_manual/
            # dtl_manual) -- so the raw field must be parsed the same way here.
            persona_config["platform_logic"] = json.loads(raw) if raw else None
        except Exception:
            persona_config["platform_logic"] = None

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
            "persona_config": persona_config,
            "knowledge_bricks": knowledge_bricks,
            "history": manifest.get("chat_history", []),
            "physics_open": manifest.get("physics_open", False),
            "schema_map": arm
        }
