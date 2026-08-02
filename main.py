from fastapi import FastAPI, HTTPException
from schema.kernel_schema import (
    SovereignRequest, SovereignResponse, AgentEnvelope,
    DeriveRequirementsRequest, DeriveRequirementsResponse,
)
from core.bootloader import SovereignBootloader
from core.orchestrator import MasterOrchestrator
from core.requirements import derive_requirements
import uvicorn
import os

app = FastAPI(title="Vibe Kernel: Sovereign Cartography v21.1")

@app.post("/kernel/invoke", response_model=SovereignResponse)
async def invoke(req: SovereignRequest):
    try:
        data = await SovereignBootloader.assemble_envelope(req)
        
        envelope = AgentEnvelope(
            app_id=req.app_id,
            project_id=req.project_id,
            milestone_config=data['milestone_config'],
            persona_config=data['persona_config'],
            knowledge_bricks=data['knowledge_bricks'],
            history=data['history'],
            physics_open=data['physics_open'],
            schema_map=data['schema_map']
        )
        
        result = await MasterOrchestrator.process_turn(envelope, req.user_message, is_global=req.is_global)
        
        # This return matches the SovereignResponse schema
        return {
            "social_response": result.get("social_response"),
            "status": result.get("status"),
            "data_patch": result.get("data_patch"),
            "brief": result.get("brief"),
            "appendix": result.get("appendix")
        }
        
    except ValueError as ve:
        raise HTTPException(status_code=502, detail=str(ve))
    except Exception as e:
        print(f"[KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Functions Library, entry 1. Deliberately NOT under /kernel/invoke -- that
# route is a conversational turn (bootloader fetch, envelope, orchestrator).
# derive_requirements() needs no conversation state (no project_id/
# milestone_id, no history), but it does need app_id -- its real L1/Skill
# come from the same live sources (functions_registry, archetype_registry,
# the app's own app_manual) real agent turns compose from, not a hand-written
# mandate baked into the function.
@app.post("/kernel/functions/derive_requirements", response_model=DeriveRequirementsResponse)
async def invoke_derive_requirements(req: DeriveRequirementsRequest):
    try:
        identity = await SovereignBootloader.resolve_function_identity(req.app_id, "Requirements")
        result = derive_requirements(req.purpose, req.target_structure, identity["l1"], identity["skill"])
        return result
    except ValueError as ve:
        raise HTTPException(status_code=502, detail=str(ve))
    except Exception as e:
        print(f"[KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
