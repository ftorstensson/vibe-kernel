"""
Mutation check for the M1a tests: each mutant breaks the executor in one specific way
that the contract forbids, in a throwaway COPY of the repository (the real tree is
never touched). A mutant is KILLED if at least one suite fails. A surviving mutant
means a test is missing.

Run: python3 tests/m1_executor/run_mutations.py [--only N | --from N]
"""
import concurrent.futures
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SUITES = ["tests/m1_executor/test_contract.py", "tests/m1_executor/test_endpoint.py", "tests/m1_executor/test_isolation.py", "tests/m1_executor/conformance/run_conformance.py", "tests/m1_executor/test_cutover.py"]

MUTANTS = [
    ("prompt is stripped before the call", "executor/schema.py", '"messages": [{"role": "user", "content": b.prompt}]', '"messages": [{"role": "user", "content": b.prompt.strip()}]'),
    ("CRLF normalized to LF in the sent prompt", "executor/schema.py", '"messages": [{"role": "user", "content": b.prompt}]', '"messages": [{"role": "user", "content": b.prompt.replace("\\r\\n", "\\n")}]'),
    ("a system message is added", "executor/schema.py", '"messages": [{"role": "user", "content": b.prompt}]', '"messages": [{"role": "system", "content": "be nice"}, {"role": "user", "content": b.prompt}]'),
    ("max_tokens never sent", "executor/schema.py", 'kwargs["max_tokens"] = b.max_output_tokens', 'pass'),
    ("temperature 0.0 dropped (truthiness check)", "executor/schema.py", "if b.temperature is not None:", "if b.temperature:"),
    ("tool_choice never sent", "executor/schema.py", 'kwargs["tool_choice"] = b.tool_choice', 'pass'),
    ("timeout not sent to the provider", "executor/schema.py", '"timeout": b.timeout_s,', ''),
    ("prompt_sha256 check skipped", "executor/schema.py", "if computed != b.prompt_sha256:", "if False:"),
    ("request_sha256 check skipped", "executor/schema.py", "if computed_request != b.request_sha256:", "if False:"),
    ("request sha check happens before the prompt sha check", "executor/schema.py", '    computed = prompt_sha256(b.prompt)\n    if computed != b.prompt_sha256:', '    _r = request_sha256(build_kwargs(b))\n    if _r != b.request_sha256:\n        raise BriefingError("request_sha_mismatch", "request_sha256", {"computed_sha256": _r})\n    computed = prompt_sha256(b.prompt)\n    if computed != b.prompt_sha256:'),
    ("canonical JSON escapes non-ASCII", "executor/schema.py", 'ensure_ascii=False, allow_nan=False).encode("utf-8")\n\n\ndef prompt_sha256', 'ensure_ascii=True, allow_nan=False).encode("utf-8")\n\n\ndef prompt_sha256'),
    ("canonical JSON does not sort keys", "executor/schema.py", "json.dumps(value, sort_keys=True,", "json.dumps(value, sort_keys=False,"),
    ("canonical JSON has whitespace", "executor/schema.py", 'separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")\n\n\ndef prompt_sha256', 'separators=(", ", ": "), ensure_ascii=False, allow_nan=False).encode("utf-8")\n\n\ndef prompt_sha256'),
    ("request sha includes messages", "executor/schema.py", 'if k not in ("messages", "vertex_project", "vertex_location")', 'if k not in ("vertex_project", "vertex_location")'),
    ("unknown fields accepted", "executor/schema.py", '        if key not in FIELDS:\n            raise BriefingError("unknown_field"', '        if False:\n            raise BriefingError("unknown_field"'),
    ("a bool accepted as a number", "executor/schema.py", "return type(value) is int or type(value) is float", "return isinstance(value, (int, float))"),
    ("model allowlist ignored", "executor/schema.py", 'if obj["model"] not in config.ALLOWED_MODELS:', 'if False:'),
    ("tool allowlist ignored", "executor/schema.py", "if not all(_tool_ok(t) for t in tools):", "if False:"),
    ("googleSearch mixed with a function tool is accepted (litellm silently drops the grounding tool)", "executor/schema.py", 'if _has_google_search(tools) and _has_function_tool(tools):', "if False:"),
    ("googleSearch mixed with response_format is accepted (real Vertex 400: controlled generation not supported with Search tool)", "executor/schema.py", 'if tools is not None and obj["response_format"] is not None and _has_google_search(tools):', "if False:"),
    ("prompt cap off by one (allows 4 MiB + 1)", "executor/schema.py", "    if len(encoded) > config.MAX_PROMPT_BYTES:", "    if len(encoded) > config.MAX_PROMPT_BYTES + 1:"),
    ("the cap counts characters, not bytes", "executor/schema.py", "    if len(encoded) > config.MAX_PROMPT_BYTES:", "    if len(prompt) > config.MAX_PROMPT_BYTES:"),
    ("timeout above the maximum accepted", "executor/schema.py", "if not 1 <= timeout <= config.MAX_TIMEOUT_S:", "if not 1 <= timeout:"),
    ("a lone surrogate is accepted", "executor/schema.py", '    except UnicodeEncodeError:\n        raise BriefingError("invalid_prompt", "prompt")', '    except UnicodeEncodeError:\n        encoded = prompt.encode("utf-8", "replace")'),
    ("the model call is retried once on error", "executor/model.py", "        exception = exc\n", "        exception = exc\n        try:\n            response = await asyncio.wait_for(litellm.acompletion(**kwargs), timeout=timeout_s)\n            exception = None\n        except Exception as exc2:\n            exception = exc2\n"),
    ("model calls are serialized behind a lock", "executor/model.py", "        response = await asyncio.wait_for(litellm.acompletion(**kwargs), timeout=timeout_s)", "        async with _LOCK:\n            response = await asyncio.wait_for(litellm.acompletion(**kwargs), timeout=timeout_s)"),
    ("Kernel's own wall-clock timeout not enforced", "executor/model.py", "await asyncio.wait_for(litellm.acompletion(**kwargs), timeout=timeout_s)", "await litellm.acompletion(**kwargs)"),
    ("the sha is of the Briefing's prompt, not of what was sent", "executor/model.py", "    encoded = content.encode(\"utf-8\")\n    sent = Sent()", "    encoded = content.strip().encode(\"utf-8\")\n    sent = Sent()"),
    ("malformed tool calls are dropped", "executor/model.py", "tool_calls = [_tool_call(tc) for tc in (getattr(message, \"tool_calls\", None) or [])]", "tool_calls = [t for t in (_tool_call(tc) for tc in (getattr(message, \"tool_calls\", None) or [])) if t[\"parse_error\"] is None]"),
    ("grounding title default missing", "executor/model.py", 'citation.get("title") or "Source"', 'citation.get("title")'),
    ("reasoning_tokens not reported", "executor/model.py", 'getattr(details, "reasoning_tokens", None) if details is not None else None', 'None'),
    ("finish_reason length becomes an error", "executor/service.py", "            result.update(status=\"ok\", output=output,", "            if finish_reason == \"length\":\n                raise RuntimeError(\"truncated\")\n            result.update(status=\"ok\", output=output,"),
    ("the provider's message is returned in the body", "executor/errors.py", 'return {"type": category, "retryable": retryable, "provider_status": provider_status, "message": message}', 'return {"type": category, "retryable": retryable, "provider_status": provider_status, "message": message + " " + _LAST[0]}'),
    ("a generic message is wrong (timeout wording)", "executor/errors.py", '"The model call timed out."', '"Timed out."'),
    ("provider_auth treated as retryable", "executor/errors.py", '"provider_auth": (False,', '"provider_auth": (True,'),
    ("content policy error classified as bad_request", "executor/errors.py", '    ("ContentPolicyViolationError", "content_blocked"),\n', ""),
    ("the provider status no longer refines a generic BadRequestError", "executor/errors.py", 'if category in ("bad_request", "provider_error") and status in _GENERIC_STATUS:', "if False:"),
    ("a specific class is overridden by the status", "executor/errors.py", 'if category in ("bad_request", "provider_error") and status in _GENERIC_STATUS:', "if status in _GENERIC_STATUS:"),
    ("Kernel's own wall-clock timeout is not classified as a timeout", "executor/errors.py", 'if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):', 'if False:'),
    ("the auth token is compared with ==", "executor/auth.py", "return hmac.compare_digest(presented.encode(\"latin-1\"), expected.encode(\"utf-8\"))", "return presented == expected"),
    ("auth accepts an unconfigured server", "executor/auth.py", "    if expected is None or not presented:\n        return False", "    if expected is None:\n        return True\n    if not presented:\n        return False"),
    ("auth minimum length dropped", "executor/config.py", "MIN_TOKEN_LENGTH = 16", "MIN_TOKEN_LENGTH = 1"),
    ("the presented token is stripped (whitespace tolerated)", "executor/auth.py", "hmac.compare_digest(presented.encode(\"latin-1\")", "hmac.compare_digest(presented.strip().encode(\"latin-1\")"),
    ("capabilities is unauthenticated", "executor/routes.py", "async def kernel_capabilities(request: Request):\n    refusal = _unauthorized(request)\n    if refusal is not None:\n        return refusal\n", "async def kernel_capabilities(request: Request):\n"),
    ("execute validates before it authenticates", "executor/routes.py", "async def kernel_execute(request: Request):\n    refusal = _unauthorized(request)\n    if refusal is not None:\n        return refusal\n    try:", "async def kernel_execute(request: Request):\n    try:"),
    ("health leaks the allowlist", "executor/routes.py", '"auth_configured": auth_configured(),', '"auth_configured": auth_configured(), "allowed_models": list(config.ALLOWED_MODELS),'),
    ("the prompt is logged", "executor/service.py", '        f"prompt_utf8_bytes={sent.prompt_utf8_bytes}",', '        f"prompt_utf8_bytes={sent.prompt_utf8_bytes} prompt={b.prompt}",'),
    ("the output text is logged", "executor/service.py", '    _log_call(b, sent, result["status"], duration_ms,', '    logger.info("out=" + str(result["output"]))\n    _log_call(b, sent, result["status"], duration_ms,'),
    ("the token is logged on an error", "executor/service.py", 'parts.append("provider_text=" + repr(errors.scrub_for_log(raw_error_text, b.prompt, (configured_token(),))))', 'parts.append("provider_text=" + repr(raw_error_text))'),
    ("segments are dropped from the result", "executor/service.py", '"segments": b.segments,', '"segments": [],'),
    ("the strict parse strips fences too", "executor/parse.py", "            parsed = json.loads(text)", "            parsed = parse_json_lenient(text)"),
    ("the lenient parse no longer takes the first list element", "executor/parse.py", "        return parsed[0] if parsed else {}", "        return parsed"),
    ("a non-finite parsed value crashes instead of being reported", "executor/parse.py", "    if not json_safe(parsed):", "    if False:"),
    # ---- the M1b cutover (executor/cutover.py; main.py)
    ("cutover: /kernel/chat_summary left out of the 410 routes", "executor/cutover.py", '    "/kernel/chat_summary",\n', ''),
    ("cutover: /kernel/invoke left out of the 410 routes", "executor/cutover.py", '    "/kernel/invoke",\n', ''),
    ("cutover: a Publish-time route (derive_requirements) is also gone", "executor/cutover.py", '    "/kernel/functions/launch_strike_team",\n', '    "/kernel/functions/launch_strike_team",\n    "/kernel/functions/derive_requirements",\n'),
    ("cutover: the status is 200, not 410", "executor/cutover.py", "JSONResponse(GONE_BODY, status_code=410)", "JSONResponse(GONE_BODY, status_code=200)"),
    ("cutover: the body echoes the request path", "executor/cutover.py", "JSONResponse(GONE_BODY, status_code=410)", "JSONResponse({**GONE_BODY, 'path': str(request.url.path)}, status_code=410)"),
    ("cutover: only POST is gone (GET falls through to a 405)", "executor/cutover.py", 'methods=["GET", "POST", "PUT", "PATCH", "DELETE"]', 'methods=["POST"]'),
    ("cutover: the router is not mounted", "main.py", "app.include_router(cutover_router)\n", "pass\n"),
    ("cutover: the router is mounted AFTER the legacy handlers", "main.py", [("app.include_router(cutover_router)\n", "pass\n"), ('if __name__ == "__main__":', 'app.include_router(cutover_router)\nif __name__ == "__main__":')], None),
]

# mutants that need a helper name to exist
PRE = {
    "executor/model.py": "\n_LOCK = asyncio.Lock()\n",
    "executor/errors.py": "\n_LAST = ['']\n",
    "executor/service.py": "\n_LASTOUT = None\n",
}


def run_suites(workdir):
    procs = [subprocess.Popen([sys.executable, s], cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for s in SUITES]
    codes = []
    for p in procs:
        try:
            p.communicate(timeout=300)
            codes.append(p.returncode)
        except subprocess.TimeoutExpired:
            p.kill()
            codes.append(-9)
    return codes


def main():
    only = None
    first = 1
    if "--only" in sys.argv:
        only = int(sys.argv[sys.argv.index("--only") + 1])
    if "--from" in sys.argv:
        first = int(sys.argv[sys.argv.index("--from") + 1])
    tmp = tempfile.mkdtemp(prefix="m1_mut_")
    work = os.path.join(tmp, "repo")
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "docs", "__pycache__", ".claude", "node_modules"))
    baseline = run_suites(work)
    print(f"baseline (no mutation): suite exit codes {baseline}")
    if any(c != 0 for c in baseline):
        print("baseline is not green; aborting")
        return 1
    survivors = []
    for i, (name, rel, old, new) in enumerate(MUTANTS, 1):
        if (only is not None and i != only) or i < first:
            continue
        path = os.path.join(work, rel)
        original = open(path).read()
        pairs = old if isinstance(old, list) else [(old, new)]
        mutated, bad = original, None
        for o, n in pairs:
            if mutated.count(o) != 1:
                bad = mutated.count(o)
                break
            mutated = mutated.replace(o, n)
        if bad is not None:
            print(f"[{i:02d}] SKIPPED (pattern matches {bad}x): {name}")
            survivors.append((i, name + " (pattern)"))
            continue
        if rel in PRE:
            mutated = mutated + PRE[rel] if not mutated.endswith(PRE[rel]) else mutated
        open(path, "w").write(mutated)
        try:
            codes = run_suites(work)
        finally:
            open(path, "w").write(original)
        killed = any(c != 0 for c in codes)
        print(f"[{i:02d}] {'KILLED  ' if killed else 'SURVIVED'} {name}   exit codes {codes}")
        if not killed:
            survivors.append((i, name))
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{1 if only is not None else len(MUTANTS) - first + 1} mutants, {len(survivors)} survived")
    for i, name in survivors:
        print(f"  SURVIVOR [{i:02d}] {name}")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
