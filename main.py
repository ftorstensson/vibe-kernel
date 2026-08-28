from fastapi import FastAPI, HTTPException
from schema.kernel_schema import (
    SovereignRequest, SovereignResponse, AgentEnvelope,
    DeriveRequirementsRequest, DeriveRequirementsResponse,
    PreviewFunctionRequest, PreviewFunctionResponse,
    AssessCoverageRequest, AssessCoverageResponse,
    ChatSummaryRequest, ChatSummaryResponse,
)
from core.orchestrator import MasterOrchestrator
from core.requirements import derive_requirements
from core.coverage import assess_coverage, resolve_required_questions
from core.reconcile import build_chat_summary
from core.composition import compose_function_identity
import uvicorn
import os

app = FastAPI(title="Vibe Kernel: Sovereign Cartography v21.1")

# Stateless executor: given a complete input, Kernel composes/calls the
# model/returns a result -- it never reaches into Firestore for its own
# inputs (core/bootloader.py's SovereignBootloader, which used to do that,
# is deleted). req already carries everything AgentEnvelope needs -- this
# is a straight field-copy, no fetch in between.
@app.post("/kernel/invoke", response_model=SovereignResponse)
async def invoke(req: SovereignRequest):
    try:
        envelope = AgentEnvelope(
            app_id=req.app_id,
            project_id=req.project_id,
            milestone_config=req.milestone_config,
            persona_config=req.persona_config,
            knowledge_bricks=req.knowledge_bricks,
            history=req.history,
            physics_open=req.physics_open,
            schema_map=req.schema_map,
            coverage_mandate=req.coverage_mandate,
            coverage_skill=req.coverage_skill,
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
# route is a conversational turn. derive_requirements() needs no
# conversation state (no project_id/milestone_id, no history), but it does
# need real L1/Skill -- composed here from raw ingredients Backend already
# resolved (functions_registry, archetype_registry, the app's own ARM), not
# fetched by Kernel and not a hand-written mandate baked into the function.
@app.post("/kernel/functions/derive_requirements", response_model=DeriveRequirementsResponse)
async def invoke_derive_requirements(req: DeriveRequirementsRequest):
    try:
        identity = compose_function_identity(
            (req.archetype or {}).get("mandate"), (req.platform or {}).get("mandate"),
            req.app_manual, req.global_mission,
        )
        result = derive_requirements(req.purpose, req.target_structure, identity["l1"], identity["l3"], req.skill)
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
# chat_summary, fetched separately via /kernel/chat_summary since that one
# has a real cost) -- None if nothing's supplied. Composes L1/L3 from raw
# ingredients via compose_function_identity() (same call
# derive_requirements() uses above) rather than a second copy of that logic.
#
# Ground truth, no double wiring: if l4_data carries a "required_questions"
# key, it's resolved through resolve_required_questions() right here -- the
# one real place that decision is made (core/coverage.py, also used by
# assess_coverage's endpoint and the live turn pipeline) -- not echoed back
# raw for the caller to re-decide. Studio sends the raw ingredients
# (required_questions + derived_requirements) and prints whatever comes back
# verbatim; it never re-implements "which one wins."
@app.post("/kernel/functions/preview", response_model=PreviewFunctionResponse)
async def invoke_preview_function(req: PreviewFunctionRequest):
    try:
        identity = compose_function_identity(
            (req.archetype or {}).get("mandate"), (req.platform or {}).get("mandate"),
            req.app_manual, req.global_mission,
        )
        if req.l4_data is not None:
            l4 = dict(req.l4_data)
            if "required_questions" in l4:
                l4["required_questions"] = resolve_required_questions({
                    "required_questions": l4.get("required_questions", []),
                    "derived_requirements": l4.get("derived_requirements"),
                })
            l4["skill"] = req.skill
        else:
            l4 = {
                "skill": req.skill,
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
# own raw fields and the current chat_summary (L5) -- the caller already
# has these, from a live turn or from /kernel/chat_summary below. Real
# identity (L1 judge archetype + L3 mission/app_manual + Skill) composed
# from raw ingredients via compose_function_identity() -- the same
# composition the live turn pipeline (core/orchestrator.py) uses for
# Coverage's own gate check, not a second copy. Calls
# resolve_required_questions() itself (same helper orchestrator.py already
# uses, a pure function -- no I/O, so no stateless-executor violation)
# rather than trusting the caller to pre-resolve -- that's what drifted:
# Test Lab's Coverage panel built required_questions from the static list
# only, never knowing derived_requirements should take precedence, while
# the live turn pipeline got it right. Making this endpoint the single
# source of truth for that precedence removes the duplication every caller
# would otherwise need to get right independently.
@app.post("/kernel/functions/assess_coverage", response_model=AssessCoverageResponse)
async def invoke_assess_coverage(req: AssessCoverageRequest):
    try:
        identity = compose_function_identity(
            (req.archetype or {}).get("mandate"), (req.platform or {}).get("mandate"),
            req.app_manual, req.global_mission,
        )
        milestone_config = {
            "required_questions": req.required_questions,
            "derived_requirements": req.derived_requirements,
        }
        required_questions = resolve_required_questions(milestone_config)
        result = assess_coverage(required_questions, req.chat_summary, identity["l1"], identity["l3"], req.skill)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=502, detail=str(ve))
    except Exception as e:
        print(f"[KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# A conversation's real chat_summary (L5) on demand, from history the
# caller already has -- Kernel no longer fetches a project's stored
# chat_history itself. NOT free like preview -- this genuinely calls the
# model (extract_facts, then a reconcile_fact pass per fact) -- Studio
# treats this as a deliberate, on-demand fetch (a button), not something
# that auto-fires on every render.
@app.post("/kernel/chat_summary", response_model=ChatSummaryResponse)
async def invoke_chat_summary(req: ChatSummaryRequest):
    try:
        chat_summary = build_chat_summary(req.history)
        return {"chat_summary": chat_summary}
    except ValueError as ve:
        raise HTTPException(status_code=502, detail=str(ve))
    except Exception as e:
        print(f"[KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
