from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List
from core.orchestrator import MasterOrchestrator
from schema.kernel_schema import AgentEnvelope
import uvicorn

app = FastAPI(title="Vibe Kernel v1.0")

@app.get("/health")
def health():
    return {"status": "online", "engine": "Vibe Kernel 1.0"}

@app.post("/process")
async def process_turn(envelope: AgentEnvelope):
    """
    The Master Entrypoint for the Vibe Kernel.
    Takes an envelope, runs the necessary Pods, and returns the result.
    """
    try:
        if not envelope.history:
            raise HTTPException(status_code=400, detail="Chat history is empty.")
            
        user_input = envelope.history[-1]['content']
        
        # Pass to the Orchestrator (Turn A/B/C logic)
        result = await MasterOrchestrator.process_turn(envelope, user_input)
        
        return result
        
    except Exception as e:
        print(f"[KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
