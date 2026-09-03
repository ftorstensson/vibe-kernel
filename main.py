from fastapi import FastAPI, HTTPException
from schema.kernel_schema import (
    SovereignRequest, SovereignResponse, AgentEnvelope,
    DeriveRequirementsRequest, DeriveRequirementsResponse,
    PreviewFunctionRequest, PreviewFunctionResponse,
    AssessCoverageRequest, AssessCoverageResponse,
    ChatSummaryRequest, ChatSummaryResponse,
    ConfirmLaunchIntentRequest, ConfirmLaunchIntentResponse,
    SynthesizeDispatchRequest, SynthesizeDispatchResponse,
)
from core.orchestrator import MasterOrchestrator
from core.requirements import derive_requirements
from core.coverage import assess_coverage, resolve_required_questions
from core.reconcile import build_chat_summary
from core.ignition import confirm_launch_intent
from core.composition import compose_function_identity
from pods.social.engine import SocialEngine
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
            gatekeeper_mandate=req.gatekeeper_mandate,
            gatekeeper_skill=req.gatekeeper_skill,
            chat_summary=req.chat_summary,
            chat_summary_cursor=req.chat_summary_cursor,
            chat_manager_mandate=req.chat_manager_mandate,
            chat_manager_skill=req.chat_manager_skill,
            partner_protocols=req.partner_protocols,
            tool_law=req.tool_law,
            # Real bug fix, found while wiring tool_call below: this field
            # was added to SovereignRequest/AgentEnvelope and to
            # run_global_turn's own composition in an earlier pass, but
            # never actually copied from req to envelope here -- so
            # envelope.project_map was always [] regardless of what
            # Backend sent, and the whole PROJECT MAP feature has been a
            # silent no-op since it shipped. Confirmed by grep (zero
            # occurrences of "project_map" anywhere in this file before
            # this line) before concluding it was missing, not just hard
            # to spot.
            project_map=req.project_map,
            keymaster_mandate=req.keymaster_mandate,
            keymaster_skill=req.keymaster_skill,
        )

        result = await MasterOrchestrator.process_turn(envelope, req.user_message, is_global=req.is_global)

        # This return matches the SovereignResponse schema
        return {
            "social_response": result.get("social_response"),
            "status": result.get("status"),
            "data_patch": result.get("data_patch"),
            "brief": result.get("brief"),
            "appendix": result.get("appendix"),
            "chat_summary": result.get("chat_summary"),
            "chat_summary_cursor": result.get("chat_summary_cursor"),
            "tool_call": result.get("tool_call"),
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


# Functions Library, Keymaster's own standalone endpoint -- same reasoning
# as derive_requirements' above: confirm_launch_intent() needs no envelope/
# milestone state, just the recent conversation history, which the caller
# (Studio) already has. app_manual/global_mission are NOT passed to
# compose_function_identity() here (unlike derive_requirements' call above)
# -- Keymaster's own design has no L3 concept at all (core/ignition.py),
# confirmed no genuine mission/app_manual use for this narrow intent-
# classification task, so this endpoint composes L1 only and discards l3
# rather than threading two fields through that would always be None.
@app.post("/kernel/functions/confirm_launch_intent", response_model=ConfirmLaunchIntentResponse)
async def invoke_confirm_launch_intent(req: ConfirmLaunchIntentRequest):
    try:
        identity = compose_function_identity(
            (req.archetype or {}).get("mandate"), (req.platform or {}).get("mandate"),
            None, None,
        )
        result = confirm_launch_intent(req.history, l1=identity["l1"], skill=req.skill)
        return {"confirmed": result}
    except ValueError as ve:
        raise HTTPException(status_code=502, detail=str(ve))
    except Exception as e:
        print(f"[KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# start_milestone_work's real round-trip, final step -- see
# SynthesizeDispatchRequest's own docstring (schema/kernel_schema.py) and
# pods/social/engine.py's synthesize_dispatch() for the full trace. Not
# under /kernel/functions/ despite the standalone-no-envelope shape (same
# as confirm_launch_intent/assess_coverage above) -- this isn't a Functions
# Library identity/skill composition, it's the PM's own voice finishing a
# turn, so it lives with the rest of the PM's endpoints conceptually even
# though the URL doesn't need to say so for routing purposes.
@app.post("/kernel/synthesize_dispatch", response_model=SynthesizeDispatchResponse)
async def invoke_synthesize_dispatch(req: SynthesizeDispatchRequest):
    try:
        result = await SocialEngine.synthesize_dispatch(
            req.persona_config, req.trigger_message, req.global_response,
            req.milestone_name, req.milestone_purpose, req.dispatch_status, req.dispatch_response,
        )
        return {"social_response": result}
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
# chat_history itself. Incremental when prior_chat_summary/cursor are given
# (Kernel slices history[cursor:] itself, same as /kernel/invoke); a full
# recompute when they're omitted, same as before this pass. NOT free like
# preview -- this genuinely calls the model (extract_facts, then a
# reconcile_fact pass per fact) -- Studio treats this as a deliberate,
# on-demand fetch (a button), not something that auto-fires on every render.
@app.post("/kernel/chat_summary", response_model=ChatSummaryResponse)
async def invoke_chat_summary(req: ChatSummaryRequest):
    try:
        identity = compose_function_identity(
            (req.archetype or {}).get("mandate"), (req.platform or {}).get("mandate"),
            req.app_manual, req.global_mission,
        )
        result = build_chat_summary(
            req.history, required_questions=req.required_questions, purpose=req.purpose,
            prior_chat_summary=req.prior_chat_summary, cursor=req.cursor,
            l1=identity["l1"], l3=identity["l3"], skill=req.skill,
        )
        return result
    except ValueError as ve:
        raise HTTPException(status_code=502, detail=str(ve))
    except Exception as e:
        print(f"[KERNEL CRASH] {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
