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
# derive_requirements() needs none of that, just purpose + target_structure,
# so this is its own stateless route: no app_id/project_id/milestone_id, no
# Firestore read on Kernel's side at all. Caller (Studio/Backend) already has
# the real content and supplies it directly.
@app.post("/kernel/functions/derive_requirements", response_model=DeriveRequirementsResponse)
async def invoke_derive_requirements(req: DeriveRequirementsRequest):
    try:
        result = derive_requirements(req.purpose, req.target_structure)
        return result
    except Exception as e:
        print(f"[KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
