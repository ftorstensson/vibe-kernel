from fastapi import FastAPI, HTTPException
from schema.kernel_schema import SovereignRequest, SovereignResponse, AgentEnvelope
from core.bootloader import SovereignBootloader
from core.orchestrator import MasterOrchestrator
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
            schema_map=data['schema_map']
        )
        
        result = await MasterOrchestrator.process_turn(envelope, req.user_message)
        
        # This return matches the SovereignResponse schema
        return {
            "social_response": result.get("social_response"),
            "status": result.get("status"),
            "data_patch": result.get("data_patch")
        }
        
    except ValueError as ve:
        raise HTTPException(status_code=502, detail=str(ve))
    except Exception as e:
        print(f"[KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
