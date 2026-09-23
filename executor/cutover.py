"""
The M1b cutover (docs/m0 K1 section 7, PM decision 2026-09-21): the nine old Kernel
turn routes answer HTTP 410 with one fixed body. There is no flag: the routes are
gone the moment this code is deployed, which happens only in the Kernel deploy that
ships with the M1b cutover, after Backend's Runner is live.

Nothing is deleted here (deletion is M4). The old handlers stay in main.py but are
unreachable, because this router is registered BEFORE them and FastAPI answers with
the first route that matches. A 410 handler never reads the body, so any request, valid
or garbage, authenticated or not, gets the same answer; it makes no model call and
touches no other service.

The five Publish-time routes (derive_requirements, compile_identity, summarize_for_map,
agents/preview, functions/preview) follow their own Backend replacements and are NOT here.
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

GONE_ROUTES = (
    "/kernel/invoke",
    "/kernel/agents/run_turn",
    "/kernel/agents/run_global_turn",
    "/kernel/agents/run_global_turn_answer",
    "/kernel/synthesize_dispatch",
    "/kernel/chat_summary",
    "/kernel/functions/assess_coverage",
    "/kernel/functions/confirm_launch_intent",
    "/kernel/functions/launch_strike_team",
)
GONE_BODY = {"error": {
    "type": "gone",
    "message": "This Kernel route was retired at the M1b cutover. Send a Briefing to POST /kernel/execute.",
    "replacement": "/kernel/execute",
}}
ROUTE_NAME_PREFIX = "cutover_410:"

router = APIRouter()


async def _gone(request: Request):
    return JSONResponse(GONE_BODY, status_code=410)


for _path in GONE_ROUTES:
    router.add_api_route(_path, _gone, methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                         name=ROUTE_NAME_PREFIX + _path, include_in_schema=False)
