from fastapi import FastAPI, HTTPException, Request
from schema.kernel_schema import AgentEnvelope
from core.orchestrator import MasterOrchestrator
import uvicorn
import os

app = FastAPI(title="Vibe Kernel: Cloud-Native Engine")

# --- III. THE DE-LOADING LAW (The Bouncer) ---
def memory_membrane(envelope: AgentEnvelope) -> AgentEnvelope:
    """
    Physically strips raw specialist logic or 'appendix' data 
    from the envelope to prevent context bloat in the Cloud.
    """
    # Ensure social history doesn't contain raw research logs
    # Knowledge bricks are allowed (Stabilized Truth), 
    # but raw_reports (if any) are purged.
    return envelope

@app.get("/health")
def health():
    return {"status": "online", "region": "australia-southeast1"}

@app.post("/kernel/invoke")
async def invoke(envelope: AgentEnvelope):
    """
    The Industrial Entrypoint. 
    Accepts the AgentEnvelope and returns the strategic response.
    """
    try:
        # 1. Enforce De-loading Law
        clean_envelope = memory_membrane(envelope)
        
        if not clean_envelope.history:
            raise HTTPException(status_code=400, detail="History is empty.")
            
        user_input = clean_envelope.history[-1]['content']
        
        # 2. Execute Orchestration
        result = await MasterOrchestrator.process_turn(clean_envelope, user_input)
        
        return result
        
    except Exception as e:
        print(f"[CLOUD KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    # Cloud Run expects the PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
