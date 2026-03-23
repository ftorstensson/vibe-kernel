from fastapi import FastAPI, HTTPException
from schema.kernel_schema import SovereignRequest, AgentEnvelope
from core.bootloader import SovereignBootloader
from core.orchestrator import MasterOrchestrator
import uvicorn
import os

app = FastAPI(title="Vibe Kernel: Sovereign Cartography v21.1")

@app.get("/health")
def health():
    return {"status": "online", "mode": "sovereign_cartography"}

@app.post("/kernel/invoke")
async def invoke(req: SovereignRequest):
    try:
        # 1. Cartography Handshake
        data = await SovereignBootloader.assemble_envelope(req)
        
        # 2. Package Envelope
        envelope = AgentEnvelope(
            app_id=req.app_id,
            project_id=req.project_id,
            milestone_config=data['milestone_config'],
            persona_config=data['persona_config'],
            knowledge_bricks=data['knowledge_bricks'],
            history=data['history'],
            schema_map=data['schema_map']
        )
        
        # 3. Execute
        result = await MasterOrchestrator.process_turn(envelope, req.user_message)
        return result
        
    except ValueError as ve:
        # v21.1 Safety Valve for Blind Kernel
        print(f"[MAP ERROR] {ve}")
        raise HTTPException(status_code=502, detail=str(ve))
    except Exception as e:
        print(f"[KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
