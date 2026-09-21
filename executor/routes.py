"""
The executor routes (docs/m0/K1 section 1):

  POST /kernel/execute       Briefing -> ExecutionResult         (authenticated)
  GET  /kernel/capabilities  allowed models, tools and limits    (authenticated)
  GET  /kernel/health        minimal, open

Check order on /kernel/execute (K1 section 2): auth (401), then the body is
read and parsed, then Briefing validation and guardrails (422), then the two
sha checks (422), then the one model call. Nothing about the schema is parsed
or revealed before auth passes. The auth check is a plain function call at the
top of each handler, not a body-parameter dependency, so nothing can be
validated ahead of it.
"""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from executor import config
from executor.auth import auth_configured, authorized
from executor.schema import BriefingError, parse_body, validate, verify_shas
from executor.service import execute

router = APIRouter()
logger = logging.getLogger("uvicorn.error")

_UNAUTHORIZED = {"error": {"type": "unauthorized"}}


def _unauthorized(request):
    if authorized(request.headers.get(config.AUTH_HEADER)):
        return None
    # The same body whether the header is missing, wrong or the server has no
    # valid token configured: a caller cannot tell which.
    return JSONResponse(_UNAUTHORIZED, status_code=401)


def _refuse(error):
    logger.info(f"executor.refused code={error.code} field={error.field}")
    return JSONResponse(error.body(), status_code=422)


@router.post("/kernel/execute")
async def kernel_execute(request: Request):
    refusal = _unauthorized(request)
    if refusal is not None:
        return refusal
    try:
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > config.MAX_BODY_BYTES:
            raise BriefingError("body_too_large")
        raw = await request.body()
        if len(raw) > config.MAX_BODY_BYTES:
            raise BriefingError("body_too_large")
        briefing = validate(parse_body(raw))
        kwargs = verify_shas(briefing)
    except BriefingError as error:
        return _refuse(error)
    result = await execute(briefing, kwargs)
    return JSONResponse(result)


@router.get("/kernel/capabilities")
async def kernel_capabilities(request: Request):
    refusal = _unauthorized(request)
    if refusal is not None:
        return refusal
    return {
        "contract_version": config.CONTRACT_VERSION,
        "allowed_models": list(config.ALLOWED_MODELS),
        "allowed_tools": list(config.ALLOWED_TOOL_SHAPES),
        "max_prompt_bytes": config.MAX_PROMPT_BYTES,
        "max_timeout_s": config.MAX_TIMEOUT_S,
    }


@router.get("/kernel/health")
async def kernel_health():
    version = config.kernel_version()
    return {
        "revision": version["revision"],
        "git_sha": version["git_sha"],
        "contract_version": config.CONTRACT_VERSION,
        "auth_configured": auth_configured(),
    }
