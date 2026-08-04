from fastapi import FastAPI, HTTPException
from schema.kernel_schema import (
    SovereignRequest, SovereignResponse, AgentEnvelope,
    DeriveRequirementsRequest, DeriveRequirementsResponse,
    PreviewFunctionRequest, PreviewFunctionResponse,
    AssessCoverageRequest, AssessCoverageResponse,
    DurableFactsRequest, DurableFactsResponse,
)
from core.bootloader import SovereignBootloader
from core.orchestrator import MasterOrchestrator
from core.requirements import derive_requirements
from core.coverage import assess_coverage
from core.reconcile import build_durable_facts
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
        result = derive_requirements(req.purpose, req.target_structure, identity["l1"], identity["l3"], identity["skill"])
        return result
    except ValueError as ve:
        raise HTTPException(status_code=502, detail=str(ve))
    except Exception as e:
        print(f"[KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Test Lab preview: the real five-layer composition (L1-L5) a Functions
# Library entry's model call would use -- as inspectable text, no model call.
# L2 (persona/voice) is never applicable to a Functions Library entry (no
# agent persona, only a procedure), so it's explicit None, not omitted -- the
# UI renders all five boxes and shows which are empty by design. L3 is real
# when the app has a mission/app_manual (Deep Knowledge, see
# core/composition.py), None otherwise. L4 carries the Skill plus each
# function's own data -- req.l4_data is the generic path (any function);
# purpose/target_structure is Requirements' specific, already-live shape,
# kept unchanged so Backend's proxy and Studio's Requirements Input panel
# don't break. L5 is whatever the caller supplies (e.g. Coverage's
# durable_facts, fetched separately via /kernel/durable_facts since that one
# has a real cost) -- None if nothing's supplied. Reuses
# resolve_function_identity() directly (same function, same fetch path
# derive_requirements() uses above) rather than a second copy of that
# resolution logic.
@app.post("/kernel/functions/preview", response_model=PreviewFunctionResponse)
async def invoke_preview_function(req: PreviewFunctionRequest):
    try:
        identity = await SovereignBootloader.resolve_function_identity(req.app_id, req.function_name)
        if req.l4_data is not None:
            l4 = {**req.l4_data, "skill": identity["skill"]}
        else:
            l4 = {
                "skill": identity["skill"],
                "purpose": req.purpose,
                "target_structure": req.target_structure,
            }
        return {
            "l1": identity["l1"],
            "l2": None,
            "l3": identity["l3"],
            "l4": l4,
            "l5": req.l5_data,
        }
    except ValueError as ve:
        raise HTTPException(status_code=502, detail=str(ve))
    except Exception as e:
        print(f"[KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Coverage's own standalone endpoint, same reasoning as derive_requirements'
# above: Coverage needs no envelope/history of its own, just the milestone's
# required_questions (L4) and the current durable_facts (L5) -- the caller
# already has these, from a live turn or from /kernel/durable_facts below.
# Real identity (L1 judge archetype + L3 mission/app_manual + Skill) via the
# same resolve_function_identity() call the live turn pipeline
# (core/orchestrator.py) already uses -- not a second copy.
@app.post("/kernel/functions/assess_coverage", response_model=AssessCoverageResponse)
async def invoke_assess_coverage(req: AssessCoverageRequest):
    try:
        identity = await SovereignBootloader.resolve_function_identity(req.app_id, "Coverage")
        result = assess_coverage(req.required_questions, req.durable_facts, identity["l1"], identity["l3"], identity["skill"])
        return result
    except ValueError as ve:
        raise HTTPException(status_code=502, detail=str(ve))
    except Exception as e:
        print(f"[KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# A project's real, current durable_facts (L5) on demand -- not a Functions
# Library identity concern (no app_id-driven L1/Skill resolution here), so
# deliberately outside /kernel/functions/. NOT free like preview -- this
# genuinely calls the model (extract_facts, then a reconcile_fact pass per
# fact) -- Studio treats this as a deliberate, on-demand fetch (a button),
# not something that auto-fires on every render.
@app.post("/kernel/durable_facts", response_model=DurableFactsResponse)
async def invoke_durable_facts(req: DurableFactsRequest):
    try:
        history = await SovereignBootloader.fetch_project_history(req.app_id, req.project_id)
        facts = build_durable_facts(history)
        return {"durable_facts": facts}
    except ValueError as ve:
        raise HTTPException(status_code=502, detail=str(ve))
    except Exception as e:
        print(f"[KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
