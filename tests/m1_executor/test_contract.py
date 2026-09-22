"""
C1 section 6, the M1a contract tests: T1, T3, T4, T8, T9, T10, T11, T12, T14, T15
(T6 is in test_isolation.py; T2, T5, T7 and T13 are AFTER THE CORE).

Run: python3 tests/m1_executor/test_contract.py
"""
import asyncio
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (AUTH, TOKEN, FakeModel, ROOT, briefing, catch_logs, check, fake_model, fake_response,  # noqa: E402
                    make_client, post, report, request_params, request_sha, sha)
import litellm  # noqa: E402

client = make_client()


def mk(cls, message="raw provider text"):
    import httpx
    try:
        return cls(message=message, model="vertex_ai/gemini-2.5-flash", llm_provider="vertex_ai")
    except TypeError:
        response = httpx.Response(400, request=httpx.Request("POST", "https://provider.invalid"))
        return cls(message=message, model="vertex_ai/gemini-2.5-flash", llm_provider="vertex_ai", response=response)


TOOL = {"type": "function", "function": {"name": "reply", "description": "Send a reply.",
        "parameters": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}}}
TOOL2 = {"type": "function", "function": {"name": "refuse", "description": "Decline.",
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}}
SCHEMA = {"type": "json_schema", "json_schema": {"name": "structured_output", "strict": True,
          "schema": {"type": "object", "properties": {"confirmed": {"type": "boolean"}}, "required": ["confirmed"]}}}

# ------------------------------------------------------------------ T1 one in, one out
# Two function tools, not one function tool plus googleSearch: a Briefing may not mix a
# function tool with googleSearch in the same call (section 2, "not_allowed"; T8 below).
full = briefing("Prompt A\nline two", model="vertex_ai/gemini-2.5-pro", temperature=0.4, reasoning_effort="minimal",
                max_output_tokens=2048, tools=[TOOL, TOOL2], tool_choice="required",
                response_format=SCHEMA, parse_mode="json_strict", timeout_s=120,
                segments=[{"start": 0, "end": 8, "scaffold": False, "layer": "l1", "provenance": None}],
                attempt_id="a-full", call_label="t.full")
with fake_model() as fake:
    r = post(client, full)
    body = r.json()
    check("T1 full Briefing: HTTP 200, status ok", r.status_code == 200 and body["status"] == "ok", r.text[:200])
    check("T1 the fake was called exactly once", len(fake.calls) == 1, len(fake.calls))
    expected = {
        "model": "vertex_ai/gemini-2.5-pro", "messages": [{"role": "user", "content": "Prompt A\nline two"}],
        "vertex_project": os.getenv("GOOGLE_CLOUD_PROJECT", "vibe-agent-final"), "vertex_location": "us-central1",
        "timeout": 120, "temperature": 0.4, "reasoning_effort": "minimal", "max_tokens": 2048,
        "tools": [TOOL, TOOL2], "tool_choice": "required", "response_format": SCHEMA,
    }
    check("T1 kwargs deep-equal exactly the C1 2.1 mapping (same keys, same values)", fake.calls[0] == expected, fake.calls[0])
    check("T1 messages is exactly one user message with the prompt", fake.calls[0]["messages"] == [{"role": "user", "content": "Prompt A\nline two"}], "")
    check("T1 attempt_id / call_label / segments echoed", body["attempt_id"] == "a-full" and body["call_label"] == "t.full" and body["segments"] == full["segments"], "")

OPTIONAL = {"temperature": 0.0, "reasoning_effort": "low", "max_output_tokens": 5, "tools": [TOOL], "tool_choice": "auto", "response_format": SCHEMA}
LITELLM_NAME = {"max_output_tokens": "max_tokens"}
for field, value in OPTIONAL.items():
    only = {k: None for k in OPTIONAL}
    only[field] = value
    with fake_model() as fake:
        post(client, briefing("x", **only))
        sent = fake.calls[0]
        present = {k for k in ("temperature", "reasoning_effort", "max_tokens", "tools", "tool_choice", "response_format") if k in sent}
        check(f"T1 optional key `{field}` is sent iff non-null (only it present)", present == {LITELLM_NAME.get(field, field)}, present)
with fake_model() as fake:
    post(client, briefing("x", **{k: None for k in OPTIONAL}))
    check("T1 all optionals null: only model, messages, vertex_*, timeout are sent",
          set(fake.calls[0]) == {"model", "messages", "vertex_project", "vertex_location", "timeout"}, set(fake.calls[0]))

# ------------------------------------------------------------------ T3 pre-call sha checks
def refused(body, code, field, name):
    with fake_model() as fake:
        r = post(client, body)
        err = r.json().get("error", {})
        check(f"{name}: HTTP 422 code {code}", r.status_code == 422 and err.get("type") == "invalid_briefing" and err.get("code") == code and err.get("field") == field, (r.status_code, err))
        check(f"{name}: zero model calls", len(fake.calls) == 0, len(fake.calls))
        return err

prompt = "Sha check prompt \u2014 caf\u00e9 \U0001F600"
b = briefing(prompt)
err = refused({**b, "prompt_sha256": sha("different")}, "prompt_sha_mismatch", "prompt_sha256", "T3 wrong prompt_sha256")
check("T3 mismatch reports Kernel's computed sha, bytes and UTF-16 length",
      err.get("computed_sha256") == sha(prompt) and err.get("prompt_utf8_bytes") == len(prompt.encode()) and err.get("prompt_utf16_units") == len(prompt.encode("utf-16-le")) // 2, err)
missing = dict(b); del missing["prompt_sha256"]
refused(missing, "missing_field", "prompt_sha256", "T3 missing prompt_sha256")
for label, bad in (("uppercase hex", sha(prompt).upper()), ("63 chars", sha(prompt)[:63]), ("not a string", 12345), ("null", None)):
    refused({**b, "prompt_sha256": bad}, "invalid_format", "prompt_sha256", f"T3 malformed prompt_sha256 ({label})")
err = refused({**b, "request_sha256": "0" * 64}, "request_sha_mismatch", "request_sha256", "T3 wrong request_sha256")
check("T3 request mismatch reports Kernel's computed sha", err.get("computed_sha256") == request_sha(b), err)
missing = dict(b); del missing["request_sha256"]
refused(missing, "missing_field", "request_sha256", "T3 missing request_sha256")
refused({**b, "request_sha256": "xyz"}, "invalid_format", "request_sha256", "T3 malformed request_sha256")
refused({**b, "temperature": 0.7}, "request_sha_mismatch", "request_sha256", "T3 one changed parameter (temperature) with the old request sha")
refused({**b, "prompt": prompt + "."}, "prompt_sha_mismatch", "prompt_sha256", "T3 one-character prompt change with the old prompt sha")
refused({**b, "prompt_sha256": sha("z"), "request_sha256": "0" * 64}, "prompt_sha_mismatch", "prompt_sha256", "T3 both wrong: the prompt sha is reported first")
tb = briefing("x", tools=[{**TOOL, "function": {**TOOL["function"], "description": "Send a reply!"}}])
tb_changed = {**tb, "tools": [TOOL]}
refused(tb_changed, "request_sha_mismatch", "request_sha256", "T3 one changed tool description")
b60 = briefing("x", timeout_s=60)
refused({**b60, "timeout_s": 60.0}, "request_sha_mismatch", "request_sha256", "T3 timeout_s 60 vs 60.0 hash differently")
b600 = briefing("x", timeout_s=60.0)
with fake_model() as fake:
    r = post(client, b600)
    check("T3 a request sha computed for 60.0 is accepted for 60.0", r.status_code == 200, r.text[:200])

# ------------------------------------------------------------------ T4 no sequencing, no retry
def one_call(behavior, mode="text", name="", **extra):
    with fake_model(FakeModel(behavior)) as fake:
        r = post(client, briefing("t4", parse_mode=mode, **extra))
        check(f"T4 {name}: HTTP 200 and exactly one model call", r.status_code == 200 and len(fake.calls) == 1, (r.status_code, len(fake.calls)))
        return r.json()

body = one_call(fake_response("", tool_calls=[("reply", '{"message":"hi"}')], finish_reason="tool_calls"), name="tool call returned")
check("T4 a returned tool call is reported, not run (no second call)", body["status"] == "ok" and body["output"]["tool_calls"][0]["name"] == "reply", body)
for mode in ("json_strict", "json_lenient"):
    body = one_call(fake_response("this is not json"), mode=mode, name=f"unparseable text under {mode}")
    check(f"T4 {mode} parse failure: status ok, parsed null, parse_error set", body["status"] == "ok" and body["output"]["parsed"] is None and body["output"]["parse_error"], body)
body = one_call(fake_response("cut off", finish_reason="length"), name="finish_reason length")
check("T4 finish_reason length is status ok with the field set", body["status"] == "ok" and body["finish_reason"] == "length", body)
body = one_call(fake_response("", finish_reason="content_filter"), name="finish_reason content_filter")
check("T4 finish_reason content_filter is status ok with the field set", body["status"] == "ok" and body["finish_reason"] == "content_filter", body)

ERROR_CASES = [
    ("Timeout", mk(litellm.exceptions.Timeout), "timeout", True),
    ("NotFoundError", mk(litellm.exceptions.NotFoundError), "model_not_found", False),
    ("BadRequestError", mk(litellm.exceptions.BadRequestError), "bad_request", False),
    ("RateLimitError", mk(litellm.exceptions.RateLimitError), "rate_limited", True),
    ("ServiceUnavailableError", mk(litellm.exceptions.ServiceUnavailableError), "provider_unavailable", True),
    ("InternalServerError", mk(litellm.exceptions.InternalServerError), "provider_unavailable", True),
    ("BadGatewayError", mk(litellm.exceptions.BadGatewayError), "provider_unavailable", True),
    ("APIConnectionError", mk(litellm.exceptions.APIConnectionError), "provider_unavailable", True),
    ("ContextWindowExceededError", mk(litellm.exceptions.ContextWindowExceededError), "context_too_long", False),
    ("ContentPolicyViolationError", mk(litellm.exceptions.ContentPolicyViolationError), "content_blocked", False),
    ("AuthenticationError", mk(litellm.exceptions.AuthenticationError), "provider_auth", False),
    ("PermissionDeniedError", mk(litellm.exceptions.PermissionDeniedError), "provider_auth", False),
    ("APIError", litellm.exceptions.APIError(status_code=418, message="raw provider text", llm_provider="vertex_ai", model="m"), "provider_error", None),
    ("plain ValueError", ValueError("raw provider text"), "provider_error", None),
]
for label, exc, category, retryable in ERROR_CASES:
    body = one_call(exc, name=f"{label} raised")
    err = body.get("error") or {}
    check(f"T4 {label}: status error, output null, category {category}", body["status"] == "error" and body["output"] is None and err.get("type") == category, body)
    check(f"T4 {label}: retryable {retryable}", err.get("retryable") is retryable, err)

# the provider's status decides when the litellm class is generic (real Vertex 403 arrives as a BadRequestError)
for status, category, retryable in ((403, "provider_auth", False), (401, "provider_auth", False), (404, "model_not_found", False), (429, "rate_limited", True), (503, "provider_unavailable", True), (400, "bad_request", False)):
    exc = mk(litellm.exceptions.BadRequestError)
    exc.status_code = status
    body = one_call(exc, name=f"BadRequestError carrying status {status}")
    check(f"T4 a BadRequestError with provider status {status} is category {category} (retryable {retryable}), status kept", body["error"]["type"] == category and body["error"]["retryable"] is retryable and body["error"]["provider_status"] == status, body["error"])
exc = litellm.exceptions.APIError(status_code=502, message="raw", llm_provider="vertex_ai", model="m")
body = one_call(exc, name="APIError carrying status 502")
check("T4 a generic APIError with provider status 502 is provider_unavailable", body["error"]["type"] == "provider_unavailable" and body["error"]["provider_status"] == 502, body["error"])
exc = mk(litellm.exceptions.ContentPolicyViolationError)
exc.status_code = 403
body = one_call(exc, name="ContentPolicyViolationError carrying status 403")
check("T4 a specific class is NOT overridden by status (content policy stays content_blocked)", body["error"]["type"] == "content_blocked", body["error"])

# a timeout: Kernel's own wall-clock limit (fake sleeps past timeout_s)
async def slow(kw):
    await asyncio.sleep(5)
    return fake_response("late")

with fake_model(FakeModel(slow)) as fake:
    import time
    t0 = time.perf_counter()
    r = post(client, briefing("t4 slow", timeout_s=1))
    elapsed = time.perf_counter() - t0
    body = r.json()
    check("T4 Kernel's own wall-clock limit: 200 with a structured timeout, provider_status null, one call, ~1 s",
          r.status_code == 200 and body["error"]["type"] == "timeout" and body["error"]["provider_status"] is None and len(fake.calls) == 1 and 0.9 < elapsed < 2.5,
          (r.status_code, body.get("error"), len(fake.calls), elapsed))

# ------------------------------------------------------------------ T8 strict validation (zero calls)
good = briefing("t8")
cases = [
    ("unknown top-level field", {**good, "extra": 1}, "unknown_field"),
    ("max_prompt_bytes is not a Briefing field", {**good, "max_prompt_bytes": 99}, "unknown_field"),
    ("vertex_project is not a Briefing field", {**good, "vertex_project": "x"}, "unknown_field"),
    ("vertex_location is not a Briefing field", {**good, "vertex_location": "x"}, "unknown_field"),
    ("contract_version 2", {**good, "contract_version": 2}, "invalid_value"),
    ("contract_version true", {**good, "contract_version": True}, "invalid_value"),
    ("contract_version as string", {**good, "contract_version": "1"}, "invalid_value"),
    ("attempt_id empty", {**good, "attempt_id": ""}, "invalid_format"),
    ("attempt_id 129 chars", {**good, "attempt_id": "a" * 129}, "invalid_format"),
    ("attempt_id non-ASCII", {**good, "attempt_id": "caf\u00e9"}, "invalid_format"),
    ("call_label with newline", {**good, "call_label": "a\nb"}, "invalid_format"),
    ("prompt not a string", {**good, "prompt": 5}, "invalid_type"),
    ("prompt empty", {**good, "prompt": ""}, "out_of_range"),
    ("model not on the allowlist", {**good, "model": "vertex_ai/gemini-1.5-pro"}, "not_allowed"),
    ("model not a string", {**good, "model": 5}, "invalid_type"),
    ("temperature 2.1", {**good, "temperature": 2.1}, "out_of_range"),
    ("temperature -0.1", {**good, "temperature": -0.1}, "out_of_range"),
    ("temperature true", {**good, "temperature": True}, "invalid_type"),
    ("temperature string", {**good, "temperature": "0.4"}, "invalid_type"),
    ("reasoning_effort unknown", {**good, "reasoning_effort": "extreme"}, "invalid_value"),
    ("max_output_tokens 0", {**good, "max_output_tokens": 0}, "out_of_range"),
    ("max_output_tokens 1.5", {**good, "max_output_tokens": 1.5}, "invalid_type"),
    ("max_output_tokens true", {**good, "max_output_tokens": True}, "invalid_type"),
    ("empty tools array", {**good, "tools": []}, "out_of_range"),
    ("tools not a list", {**good, "tools": {"googleSearch": {}}}, "invalid_type"),
    ("tool that is not a function tool or googleSearch", {**good, "tools": [{"codeExecution": {}}]}, "not_allowed"),
    ("googleSearch with a body", {**good, "tools": [{"googleSearch": {"x": 1}}]}, "not_allowed"),
    ("function tool with an extra key", {**good, "tools": [{**TOOL, "extra": 1}]}, "not_allowed"),
    ("function tool without parameters", {**good, "tools": [{"type": "function", "function": {"name": "x"}}]}, "not_allowed"),
    ("googleSearch mixed with a function tool (litellm silently drops googleSearch for this shape)", {**good, "tools": [TOOL, {"googleSearch": {}}]}, "not_allowed"),
    ("googleSearch mixed with a function tool, reverse order", {**good, "tools": [{"googleSearch": {}}, TOOL]}, "not_allowed"),
    ("googleSearch mixed with two function tools", {**good, "tools": [TOOL, {**TOOL, "function": {**TOOL["function"], "name": "other"}}, {"googleSearch": {}}]}, "not_allowed"),
    ("tool_choice unknown", {**good, "tool_choice": "any"}, "invalid_value"),
    ("response_format not an object", {**good, "response_format": "json"}, "invalid_type"),
    ("parse_mode unknown", {**good, "parse_mode": "json"}, "invalid_value"),
    ("timeout_s 0.5", {**good, "timeout_s": 0.5}, "out_of_range"),
    ("timeout_s 281 (above max_timeout_s)", {**good, "timeout_s": 281}, "out_of_range"),
    ("timeout_s null", {**good, "timeout_s": None}, "invalid_type"),
    ("segments not a list", {**good, "segments": {}}, "invalid_type"),
    ("segments with a non-object", {**good, "segments": [1]}, "invalid_type"),
    ("2001 segments", {**good, "segments": [{}] * 2001}, "too_large"),
    ("segments over 256 KiB serialized", {**good, "segments": [{"provenance": "x" * 300000}]}, "too_large"),
]
for name, body_, code in cases:
    with fake_model() as fake:
        r = post(client, body_)
        err = r.json().get("error", {})
        check(f"T8 {name}: 422 {code}, zero calls", r.status_code == 422 and err.get("code") == code and len(fake.calls) == 0, (r.status_code, err, len(fake.calls)))
with fake_model() as fake:
    for key in ("contract_version", "attempt_id", "call_label", "prompt", "model", "temperature", "reasoning_effort", "max_output_tokens", "tools", "tool_choice", "response_format", "parse_mode", "timeout_s", "segments"):
        incomplete = {k: v for k, v in good.items() if k != key}
        r = post(client, incomplete)
        check(f"T8 missing key `{key}` (every key must be present, null where unused): 422 missing_field", r.status_code == 422 and r.json()["error"]["code"] == "missing_field", (r.status_code, r.text[:120]))
    check("T8 no model call for any missing-key case", len(fake.calls) == 0, len(fake.calls))
with fake_model() as fake:
    over = "a" * (4 * 1024 * 1024 + 1)
    r = client.post("/kernel/execute", json=briefing(over), headers=AUTH)
    check("T8 prompt of 4 MiB + 1 byte: 422 too_large, zero calls", r.status_code == 422 and r.json()["error"]["code"] == "too_large" and len(fake.calls) == 0, (r.status_code, r.text[:100]))
    multibyte = "\u00e9" * (2 * 1024 * 1024 + 1)   # 2 bytes each: 4 MiB + 2 bytes
    r = client.post("/kernel/execute", json=briefing(multibyte), headers=AUTH)
    check("T8 the cap is bytes, not characters (multibyte prompt over 4 MiB in bytes)", r.status_code == 422 and r.json()["error"]["code"] == "too_large", (r.status_code, r.text[:100]))
    one_over = "\u00e9" * (2 * 1024 * 1024) + "a"   # 2 MiB two-byte characters + 1 byte = 4 MiB + 1 byte, fewer characters than the cap
    r = client.post("/kernel/execute", json=briefing(one_over), headers=AUTH)
    check("T8 a multibyte prompt of exactly 4 MiB + 1 byte is refused (the byte cap has no off-by-one)", r.status_code == 422 and r.json()["error"]["code"] == "too_large", (r.status_code, r.text[:100]))
    exact_multibyte = "\u00e9" * (2 * 1024 * 1024)      # exactly 4 MiB in bytes
    r = client.post("/kernel/execute", json=briefing(exact_multibyte), headers=AUTH)
    check("T8 a multibyte prompt of exactly 4 MiB passes", r.status_code == 200, (r.status_code, r.text[:100]))
    exact = "a" * (4 * 1024 * 1024)
    r = client.post("/kernel/execute", json=briefing(exact), headers=AUTH)
    check("T8 a prompt of exactly 4 MiB passes and reaches the model unchanged", r.status_code == 200 and fake.calls[-1]["messages"][0]["content"] == exact, (r.status_code, r.text[:100]))
with fake_model() as fake:
    lone = client.post("/kernel/execute", content=json.dumps({**briefing("x"), "prompt": "bad \ud800 surrogate"}).encode("ascii"),
                       headers={**AUTH, "content-type": "application/json"})
    check("T8 a prompt with an unpaired surrogate: 422 invalid_prompt, zero calls", lone.status_code == 422 and lone.json()["error"]["code"] == "invalid_prompt" and len(fake.calls) == 0, (lone.status_code, lone.text[:120]))
    for label, raw in (("not JSON", b"nope"), ("empty body", b""), ("a JSON array", b"[]"), ("NaN literal", b'{"a": NaN}'),
                       ("duplicate keys", b'{"a": 1, "a": 2}'), ("invalid UTF-8", b'\xff\xfe{}')):
        r = client.post("/kernel/execute", content=raw, headers={**AUTH, "content-type": "application/json"})
        check(f"T8 body that is {label}: 422, zero calls", r.status_code == 422 and len(fake.calls) == 0, (r.status_code, r.text[:100]))
    r = client.post("/kernel/execute", content=json.dumps({**briefing("x"), "tools": [{"type": "function", "function": {"name": "a\ud800", "parameters": {}}}]}).encode("ascii"),
                    headers={**AUTH, "content-type": "application/json"})
    check("T8 a surrogate inside a tool name: 422 invalid_text, zero calls", r.status_code == 422 and r.json()["error"]["code"] == "invalid_text" and len(fake.calls) == 0, (r.status_code, r.text[:100]))
    r = client.post("/kernel/execute", content=json.dumps({**briefing("x"), "response_format": {"a": 1e999}}).replace("Infinity", "1e999").encode("ascii"),
                    headers={**AUTH, "content-type": "application/json"})
    check("T8 a non-finite number (1e999) in response_format: 422, zero calls", r.status_code == 422 and len(fake.calls) == 0, (r.status_code, r.text[:100]))

# ------------------------------------------------------------------ T9 parse modes
sys.path.insert(0, ROOT)
from core.kernel_utils import parse_json_lenient as legacy_lenient  # noqa: E402

TEXTS = {
    "object": '{"a": 1, "b": [1, 2]}', "fenced object": '```json\n{"a": 1}\n```', "fenced with spaces": '  ```json\n{"a": 1}\n```  ',
    "list of objects": '[{"a": 1}, {"a": 2}]', "empty list": "[]", "fenced empty list": '```json\n[]\n```', "scalar number": "5",
    "scalar string": '"hi"', "null": "null", "invalid json": "{a:1}", "empty text": "", "whitespace only": "   \n",
    "text before": 'Here you go: {"a": 1}', "text after": '{"a": 1} hope this helps', "plain prose": "hello there",
    "fence without json tag": '```\n{"a": 1}\n```', "trailing fence only": '{"a": 1}\n```',
}
for label, text in TEXTS.items():
    strict_expected = None
    try:
        strict_expected = ("ok", json.loads(text))
    except Exception:
        strict_expected = ("err", None)
    try:
        lenient_expected = ("ok", legacy_lenient(text))
    except Exception:
        lenient_expected = ("err", None)
    for mode, expected in (("json_strict", strict_expected), ("json_lenient", lenient_expected)):
        with fake_model(FakeModel(fake_response(text))) as fake:
            body = post(client, briefing("t9", parse_mode=mode)).json()
            out = body["output"]
            got = ("ok", out["parsed"]) if out["parse_error"] is None else ("err", None)
            check(f"T9 {mode} on {label}: matches {'json.loads' if mode == 'json_strict' else 'the legacy parse_json_lenient'} (differential)", got == expected and (out["parse_error"] is None) == (expected[0] == "ok"), (got, expected, out["parse_error"]))
            check(f"T9 {mode} on {label}: status ok and text untouched", body["status"] == "ok" and out["text"] == text, body)
    with fake_model(FakeModel(fake_response(text))) as fake:
        out = post(client, briefing("t9", parse_mode="text")).json()["output"]
        check(f"T9 text mode on {label}: parsed null, parse_error null", out["parsed"] is None and out["parse_error"] is None, out)
with fake_model(FakeModel(fake_response("", tool_calls=[("reply", '{"message":"hi"}')], finish_reason="tool_calls"))) as fake:
    body = post(client, briefing("t9", parse_mode="json_strict")).json()
    check("T9 empty text plus a tool call under json_strict: parse_error set, tool call kept, status ok", body["status"] == "ok" and body["output"]["parse_error"] and body["output"]["tool_calls"][0]["args"] == {"message": "hi"}, body)
for label, text in (("NaN", '{"a": NaN}'), ("Infinity", "[Infinity]"), ("1e999", '{"a": 1e999}')):
    for mode in ("json_strict", "json_lenient"):
        with fake_model(FakeModel(fake_response(text))) as fake:
            r = post(client, briefing("t9", parse_mode=mode))
            out = r.json()["output"]
            check(f"T9 {mode} on {label}: a value that cannot be returned as JSON is a parse_error, not a crash (HTTP 200)", r.status_code == 200 and out["parsed"] is None and out["parse_error"], (r.status_code, out))
for depth in (5000, 300000):
    with fake_model(FakeModel(fake_response("[" * depth + "]" * depth))) as fake:
        r = post(client, briefing("t9", parse_mode="json_strict"))
        ok_shape = r.status_code == 200 and r.json()["status"] == "ok" and (r.json()["output"]["parsed"] is not None or r.json()["output"]["parse_error"])
        check(f"T9 absurdly nested JSON (depth {depth}): HTTP 200 with a parsed value or a parse_error, never a crash", ok_shape, (r.status_code, r.text[:120]))

# ------------------------------------------------------------------ T10 result echo
segments = [{"start": 0, "end": 4, "scaffold": True, "layer": None, "provenance": None, "note": "extra key kept"},
            {"start": 4, "end": 9, "scaffold": False, "layer": "l3", "provenance": {"scope": "App", "id": "x1"}, "n": 7, "f": 1.0}]
annotations = [{"type": "url_citation", "url_citation": {"title": "Alpha", "url": "https://a.example"}},
               {"type": "url_citation", "url_citation": {"url": "https://b.example"}},
               {"type": "other", "url_citation": {"title": "no", "url": "https://c.example"}}]
tcs = [("reply", '{"message": "hi"}'), ("bad", "{not json"), ("nested", "[1, 2]"), ("noargs", "")]
with fake_model(FakeModel(fake_response("some text", tool_calls=tcs, annotations=annotations, finish_reason="tool_calls", usage=(120, 81, 80), model="gemini-2.5-pro")),
                extra_env={"K_REVISION": "vibe-kernel-00099-abc", "KERNEL_GIT_SHA": "deadbeef"}) as fake:
    body = post(client, briefing("t10 prompt", segments=segments, attempt_id="att-x", call_label="lbl.x")).json()
check("T10 segments returned deep-equal, extra keys and int/float kinds included", body["segments"] == segments and json.dumps(body["segments"], sort_keys=True) == json.dumps(segments, sort_keys=True), body["segments"])
check("T10 kernel.revision / git_sha come from the environment", body["kernel"] == {"revision": "vibe-kernel-00099-abc", "git_sha": "deadbeef"}, body["kernel"])
check("T10 usage includes reasoning_tokens", body["usage"] == {"prompt_tokens": 120, "completion_tokens": 81, "reasoning_tokens": 80}, body["usage"])
check("T10 finish_reason and effective_model map exactly", body["finish_reason"] == "tool_calls" and body["effective_model"] == "gemini-2.5-pro", body)
tc = body["output"]["tool_calls"]
check("T10 all four tool calls returned in order, none dropped", [t["name"] for t in tc] == ["reply", "bad", "nested", "noargs"], tc)
check("T10 a valid tool call: args parsed, raw kept, no parse_error", tc[0]["args"] == {"message": "hi"} and tc[0]["arguments_raw"] == '{"message": "hi"}' and tc[0]["parse_error"] is None, tc[0])
check("T10 a malformed tool call is kept with args null, raw kept and a parse_error", tc[1]["args"] is None and tc[1]["arguments_raw"] == "{not json" and tc[1]["parse_error"], tc[1])
check("T10 tool arguments that are not an object: args null with a parse_error", tc[2]["args"] is None and tc[2]["parse_error"], tc[2])
check("T10 empty arguments: args null with a parse_error", tc[3]["args"] is None and tc[3]["parse_error"], tc[3])
check("T10 grounding sources: url_citation only, title defaults to Source",
      body["output"]["grounding_sources"] == [{"title": "Alpha", "url": "https://a.example"}, {"title": "Source", "url": "https://b.example"}], body["output"]["grounding_sources"])
check("T10 text returned as the model sent it", body["output"]["text"] == "some text", body["output"])
check("T10 every ExecutionResult key is present", set(body) == {"contract_version", "attempt_id", "call_label", "status", "prompt_sha256", "prompt_utf8_bytes", "prompt_utf16_units", "request_sha256", "output", "usage", "finish_reason", "effective_model", "error", "timing", "kernel", "segments"}, sorted(body))
check("T10 timing has started_at (UTC ISO 8601) and duration_ms", body["timing"]["started_at"].endswith("Z") and isinstance(body["timing"]["duration_ms"], int), body["timing"])
check("T10 the result never contains the prompt", "t10 prompt" not in json.dumps(body), "")
with fake_model(FakeModel(fake_response(None, usage=None, model=None, finish_reason=None))) as fake:
    body = post(client, briefing("t10 sparse")).json()
check("T10 a sparse provider response (no content, usage, model or finish_reason) is still status ok with nulls", body["status"] == "ok" and body["output"]["text"] == "" and body["usage"] is None and body["finish_reason"] is None and body["effective_model"] is None, body)

# ------------------------------------------------------------------ T11 error mapping (no provider text in the body)
from executor import errors  # noqa: E402

GENERIC = {
    "timeout": "The model call timed out.", "model_not_found": "The requested model was not found.",
    "bad_request": "The provider rejected the request as invalid.", "rate_limited": "The provider rate limit was reached.",
    "provider_unavailable": "The provider was unavailable.", "context_too_long": "The prompt is longer than the model accepts.",
    "content_blocked": "The provider blocked the request for policy reasons.",
    "provider_auth": "Kernel's credentials or permissions were refused by the provider.", "provider_error": "The provider returned an error.",
}
check("T11 the nine generic messages are exactly the accepted wordings", {k: v[1] for k, v in errors.CATEGORIES.items()} == GENERIC, errors.CATEGORIES)
PROMPT_T11 = "Confidential prompt text that must never be echoed back to anyone, anywhere."
LEAKY = [
    ("the project path", "Publisher Model `projects/vibe-agent-final/locations/us-central1/publishers/google/models/nope` not found."),
    ("the Kernel auth token", f"upstream said token={TOKEN}"),
    ("a Bearer token", "header Authorization: Bearer abc123.def456-ghi789 rejected"),
    ("an AIza key", "key AIza" + "A" * 35 + " invalid"),
    ("a ya29 token", "token ya29.a0AfH6SMBxyz-123_abc expired"),
    ("a JWT-like string", "jwt eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl bad"),
    ("a PEM block", "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----"),
    ("the prompt", f"Invalid request near: {PROMPT_T11}"),
]
for what, raw_text in LEAKY:
    for label, cls in (("NotFoundError", litellm.exceptions.NotFoundError), ("BadRequestError", litellm.exceptions.BadRequestError), ("APIError", None)):
        exc = mk(cls, raw_text) if cls else litellm.exceptions.APIError(status_code=500, message=raw_text, llm_provider="vertex_ai", model="m")
        with fake_model(FakeModel(exc)) as fake, catch_logs() as logs:
            r = post(client, briefing(PROMPT_T11))
            text = r.text
            body = r.json()
            log_text = "\n".join(logs.lines)
        markers = ("projects/vibe-agent-final", TOKEN, "abc123.def456", "AIza", "ya29.", "eyJhbGci", "PRIVATE KEY", "MIIEvQ", PROMPT_T11[:25], "Publisher Model", "Invalid request near", "upstream said")
        check(f"T11 {label} carrying {what}: the body has the fixed generic message and no provider text",
              r.status_code == 200 and body["error"]["message"] in GENERIC.values() and not any(m in text for m in markers) and set(body["error"]) == {"type", "retryable", "provider_status", "message"}, text[:300])
        secret_markers = {"the Kernel auth token": TOKEN, "a Bearer token": "abc123.def456", "an AIza key": "AIza" + "A" * 35, "a ya29 token": "ya29.a0AfH6", "a JWT-like string": "eyJhbGciOiJSUzI1NiJ9", "a PEM block": "MIIEvQIBADANBg", "the prompt": PROMPT_T11[:30], "the project path": "projects/vibe-agent-final"}
        check(f"T11 {label} carrying {what}: the log line has the raw category and the scrubbed text, without the secret",
              "executor.call" in log_text and "error_type=" in log_text and secret_markers[what] not in log_text, [l for l in logs.lines if "executor.call" in l][:1])
for a, b_ in (("model not found A", "Publisher Model `projects/p1/locations/x/models/a` not found."), ("model not found B", "totally different provider wording")):
    with fake_model(FakeModel(mk(litellm.exceptions.NotFoundError, b_))):
        first = post(client, briefing("same", attempt_id="fixed")).json()
    with fake_model(FakeModel(mk(litellm.exceptions.NotFoundError, "other raw text 12345"))):
        second = post(client, briefing("same", attempt_id="fixed")).json()
    first["timing"] = second["timing"] = None
    check(f"T11 two different raw texts for the same category give identical bodies ({a})", first == second, (first["error"], second["error"]))
# log scrubbing unit checks
scrubbed = errors.scrub_for_log("x" * 5000)
check("T11 log text is capped at 2000 characters", len(scrubbed) == 2000, len(scrubbed))
check("T11 a prompt echo of 20+ characters is removed from the log text; a shorter one is not",
      "MUSTNOTLEAK" not in errors.scrub_for_log("a MUSTNOTLEAK-MUSTNOTLEAK-1234 b", prompt="zz MUSTNOTLEAK-MUSTNOTLEAK-1234 zz") and "short one" in errors.scrub_for_log("a short one b", prompt="a short one b"), "")

# ------------------------------------------------------------------ T12 logs
SECRET_OUTPUT = "MODEL-OUTPUT-MARKER-77"
SECRET_PROMPT = "PROMPT-MARKER-99 " * 4
with fake_model(FakeModel(fake_response(SECRET_OUTPUT, tool_calls=[("reply", '{"message":"ARG-MARKER-55"}')]))) as fake, catch_logs() as logs:
    body = post(client, briefing(SECRET_PROMPT, attempt_id="att-log", call_label="lbl.log")).json()
    post(client, briefing(SECRET_PROMPT, attempt_id="att-bad"), headers={"X-Kernel-Auth-Token": "WRONG-TOKEN-VALUE-1234567"})
    post(client, {**briefing(SECRET_PROMPT), "prompt_sha256": "1" * 64})
log_text = "\n".join(logs.lines)
call_lines = [l for l in logs.lines if "executor.call" in l]
check("T12 one log line per executed call with attempt_id, call_label, sha, duration and status",
      len(call_lines) == 1 and all(k in call_lines[0] for k in ("attempt_id=att-log", "call_label=lbl.log", f"prompt_sha256={body['prompt_sha256']}", "duration_ms=", "status=ok")), call_lines)
check("T12 no prompt text in any log line", "PROMPT-MARKER-99" not in log_text, "")
check("T12 no output text in any log line", SECRET_OUTPUT not in log_text, "")
check("T12 no tool arguments in any log line", "ARG-MARKER-55" not in log_text, "")
check("T12 no credential in any log line (the token, and the header name with a value)", TOKEN not in log_text and "WRONG-TOKEN-VALUE-1234567" not in log_text, "")

# ------------------------------------------------------------------ T14 headings and scaffold are just text
SIX_LAYER = (
    "## L1 \u2014 MANDATE\r\nYou are a careful assistant.\r\n\r\n## L2 \u2014 PERSONA\nWarm, brief. \U0001F600  \n\n"
    "## L3 \u2014 CONTEXT\nApp: caf\u00e9 \u201cquotes\u201d\n\n## L4 \u2014 TASK\nSummarize.\n\n## L5 \u2014 INPUT\n{\"json\": \"looking\", \"path\": \"C:\\\\x\"}\n\n"
    "## L6 \u2014 MEMORY\n- fact one\n\n### BLOCK 3: THE TRUTH\n[EXECUTION_START: now]\nClose.\n"
)
for variant, text in (("CRLF", SIX_LAYER.replace("\n", "\r\n")), ("LF", SIX_LAYER.replace("\r\n", "\n")), ("mixed", SIX_LAYER)):
    b = briefing(text, segments=[{"start": 0, "end": 10, "scaffold": True, "layer": None, "provenance": None}])
    with fake_model() as fake:
        body = post(client, b).json()
    sent = fake.calls[0]
    check(f"T14 ({variant}) one message, role user, content byte-identical to the prompt", sent["messages"] == [{"role": "user", "content": text}] and sent["messages"][0]["content"].encode("utf-8") == text.encode("utf-8"), sent["messages"][:1])
    check(f"T14 ({variant}) no other message, no system message, no extra key beyond the mapping", len(sent["messages"]) == 1 and set(sent) == {"model", "messages", "vertex_project", "vertex_location", "timeout", "temperature", "reasoning_effort"}, set(sent))
    check(f"T14 ({variant}) segments echoed and prompt_sha256 equals the test's own sha", body["segments"] == b["segments"] and body["prompt_sha256"] == sha(text), body["prompt_sha256"])

# ------------------------------------------------------------------ T15 sha vectors
V1_PROMPT = "## L1 \u2014 MANDATE\r\nHello \U0001F600 caf\u00e9\n\n"
V1_SHA = "8ead1c076d6f8ee14f20f81eb0156b2bd657d5ea66628fe32a4baf77e840836e"
V2 = dict(model="vertex_ai/gemini-2.5-flash", temperature=0.0, reasoning_effort="disable", timeout_s=60,
          response_format={"type": "json_schema", "json_schema": {"name": "structured_output", "schema": {"type": "object", "properties": {"confirmed": {"type": "boolean"}}, "required": ["confirmed"]}, "strict": True}})
V2_SHA = "4c8c68ffefe4246158e374cb499267ee44af8a628a9470a8bc99f2275e38a9fa"
V3 = dict(model="vertex_ai/gemini-2.5-pro", temperature=0.4, reasoning_effort="minimal", max_output_tokens=2048, timeout_s=120, tool_choice="required",
          tools=[{"type": "function", "function": {"name": "refuse", "description": "Decline \u2014 not a reply.", "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}}])
V3_SHA = "114c3ba17d05955933c47eba61147afec42a829648f4b438bcde263bb5587217"
V4 = dict(model="vertex_ai/gemini-2.5-flash", temperature=0.1, reasoning_effort=None, timeout_s=90, tools=[{"googleSearch": {}}])
V4_SHA = "43176cefaf19373f48ea5eead671117f023477d03daa11a5be9fe38014457668"

check("T15 V1 prompt: 31 code points, 32 UTF-16 units, 37 UTF-8 bytes", (len(V1_PROMPT), len(V1_PROMPT.encode("utf-16-le")) // 2, len(V1_PROMPT.encode())) == (31, 32, 37), "")
check("T15 the independent test helper reproduces the four literal vectors", sha(V1_PROMPT) == V1_SHA and request_sha(briefing(**V2)) == V2_SHA and request_sha(briefing(**V3)) == V3_SHA and request_sha(briefing(**V4)) == V4_SHA,
      (request_sha(briefing(**V2)), request_sha(briefing(**V3)), request_sha(briefing(**V4))))
for name, fields, expected in (("V2", V2, V2_SHA), ("V3", V3, V3_SHA), ("V4", V4, V4_SHA)):
    b = briefing(V1_PROMPT, prompt_sha256=V1_SHA, request_sha256=expected, **fields)
    with fake_model() as fake:
        r = post(client, b)
        body = r.json()
        check(f"T15 {name}: the Briefing with the literal vector shas is accepted (200)", r.status_code == 200, r.text[:200])
        check(f"T15 {name}: Kernel's returned prompt_sha256 and request_sha256 equal the literal vectors", body.get("prompt_sha256") == V1_SHA and body.get("request_sha256") == expected, (body.get("prompt_sha256"), body.get("request_sha256")))
    with fake_model() as fake:
        r = post(client, {**b, "request_sha256": "0" * 64})
        check(f"T15 {name}: a wrong request_sha256 is refused with request_sha_mismatch and Kernel's computed value is the vector", r.status_code == 422 and r.json()["error"]["code"] == "request_sha_mismatch" and r.json()["error"]["computed_sha256"] == expected, r.text[:200])
        check(f"T15 {name}: zero model calls on the refusal", len(fake.calls) == 0, len(fake.calls))
    with fake_model() as fake:
        r = post(client, {**b, "prompt_sha256": "0" * 64})
        check(f"T15 {name}: a wrong prompt_sha256 is refused with prompt_sha_mismatch and Kernel's computed value is V1", r.status_code == 422 and r.json()["error"]["code"] == "prompt_sha_mismatch" and r.json()["error"]["computed_sha256"] == V1_SHA, r.text[:200])
# a one-character change to the prompt or to any parameter changes the respective sha
base = briefing(V1_PROMPT, **V3)
mutations = {
    "temperature": {"temperature": 0.41}, "model": {"model": "vertex_ai/gemini-2.5-flash"}, "reasoning_effort": {"reasoning_effort": "low"},
    "max_output_tokens": {"max_output_tokens": 2049}, "tool_choice": {"tool_choice": "auto"}, "timeout_s": {"timeout_s": 121},
    "tool description": {"tools": [{"type": "function", "function": {**V3["tools"][0]["function"], "description": "Decline \u2014 not a reply"}}]},
    "response_format added": {"response_format": {"type": "json_object"}},
}
for name, change in mutations.items():
    changed = briefing(V1_PROMPT, **{**V3, **change})
    check(f"T15 changing {name} changes request_sha256 (and not prompt_sha256)", changed["request_sha256"] != base["request_sha256"] and changed["prompt_sha256"] == base["prompt_sha256"], "")
check("T15 changing one prompt character changes prompt_sha256 (and not request_sha256)", briefing(V1_PROMPT + ".", **V3)["prompt_sha256"] != base["prompt_sha256"] and briefing(V1_PROMPT + ".", **V3)["request_sha256"] == base["request_sha256"], "")
check("T15 non-ASCII text is hashed as itself, not as \\uXXXX escapes", request_sha(briefing("x", **V3)) == V3_SHA and "\\u2014" not in json.dumps(request_params(briefing("x", **V3)), sort_keys=True, separators=(",", ":"), ensure_ascii=False), "")

sys.exit(report("M1a contract tests (C1 T1, T3, T4, T8, T9, T10, T11, T12, T14, T15)"))
