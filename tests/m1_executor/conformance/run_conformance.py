#!/usr/bin/env python3
"""
Executor conformance harness (K1e): exercises a Kernel executor the way Backend's client must.

It is a REFERENCE CLIENT: it uses only the Python standard library, and the functions
at the top (`canonical_json`, `prompt_sha256`, `request_sha256`, `make_briefing`) are a
compact, independent implementation of docs/m0 C1 sections 2 and 5 that Backend may diff
its own against. Checks are numbered and cite the C1/K1 section they come from.

Default mode starts a local executor with a deterministic fake model (serve_fake.py; no
network, no credentials, no cost) and a throwaway random token that is never printed:

    python3 tests/m1_executor/conformance/run_conformance.py

Against another server (a deployed Kernel, or your own launch of serve_fake.py):

    KERNEL_AUTH_TOKEN=... python3 tests/m1_executor/conformance/run_conformance.py --url http://127.0.0.1:8899
    (add --allow-model-calls if the server is a REAL Kernel and you accept real, cheap model calls;
     add --fake if the server IS serve_fake.py, so the provider-error and parse checks run too)

Exit code 0 when every check that ran passed; 1 otherwise. --json PATH writes a report.
"""
import argparse
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
AUTH_HEADER = "X-Kernel-Auth-Token"


# ----------------------------------------------------------------- reference implementation (C1 2, 5)
def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value):
    """C1 5.2: sorted keys at every level, no whitespace, non-ASCII as itself, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def request_params(b):
    """The object whose canonical JSON is hashed: litellm names, non-null values only,
    `max_output_tokens` sent as `max_tokens`, `timeout_s` as `timeout`; no messages, no vertex_*."""
    r = {"model": b["model"], "timeout": b["timeout_s"]}
    for src, dst in (("temperature", "temperature"), ("reasoning_effort", "reasoning_effort"), ("max_output_tokens", "max_tokens"),
                     ("tools", "tools"), ("tool_choice", "tool_choice"), ("response_format", "response_format")):
        if b.get(src) is not None:
            r[dst] = b[src]
    return r


def request_sha256(b):
    return hashlib.sha256(canonical_json(request_params(b))).hexdigest()


def make_briefing(prompt, **fields):
    """A complete, valid Briefing with both shas computed. Every key is present (null where unused)."""
    b = {"contract_version": 1, "attempt_id": "conf-1", "call_label": "conf.echo", "prompt": prompt,
         "prompt_sha256": None, "request_sha256": None, "model": "vertex_ai/gemini-2.5-flash", "temperature": 0.0,
         "reasoning_effort": "disable", "max_output_tokens": None, "tools": None, "tool_choice": None,
         "response_format": None, "parse_mode": "text", "timeout_s": 60, "segments": []}
    b.update(fields)
    if b["prompt_sha256"] is None:
        b["prompt_sha256"] = sha256_hex(b["prompt"])
    if b["request_sha256"] is None:
        b["request_sha256"] = request_sha256(b)
    return b


# ----------------------------------------------------------------- the literal vectors (C1 5.2)
V1_PROMPT = "## L1 \u2014 MANDATE\r\nHello \U0001F600 caf\u00e9\n\n"
V1_SHA = "8ead1c076d6f8ee14f20f81eb0156b2bd657d5ea66628fe32a4baf77e840836e"
VECTORS = [
    ("V2", dict(model="vertex_ai/gemini-2.5-flash", temperature=0.0, reasoning_effort="disable", timeout_s=60,
                response_format={"type": "json_schema", "json_schema": {"name": "structured_output", "schema": {"type": "object", "properties": {"confirmed": {"type": "boolean"}}, "required": ["confirmed"]}, "strict": True}}),
     "4c8c68ffefe4246158e374cb499267ee44af8a628a9470a8bc99f2275e38a9fa"),
    ("V3", dict(model="vertex_ai/gemini-2.5-pro", temperature=0.4, reasoning_effort="minimal", max_output_tokens=2048, timeout_s=120, tool_choice="required",
                tools=[{"type": "function", "function": {"name": "refuse", "description": "Decline \u2014 not a reply.", "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}}]),
     "114c3ba17d05955933c47eba61147afec42a829648f4b438bcde263bb5587217"),
    ("V4", dict(model="vertex_ai/gemini-2.5-flash", temperature=0.1, reasoning_effort=None, timeout_s=90, tools=[{"googleSearch": {}}]),
     "43176cefaf19373f48ea5eead671117f023477d03daa11a5be9fe38014457668"),
]

# C1 4.4: category -> (retryable, fixed generic message, provider status the fake produces)
ERRORS = {
    "timeout": (True, "The model call timed out.", 408),
    "model_not_found": (False, "The requested model was not found.", 404),
    "bad_request": (False, "The provider rejected the request as invalid.", 400),
    "rate_limited": (True, "The provider rate limit was reached.", 429),
    "provider_unavailable": (True, "The provider was unavailable.", 503),
    "context_too_long": (False, "The prompt is longer than the model accepts.", 400),
    "content_blocked": (False, "The provider blocked the request for policy reasons.", 400),
    "provider_auth": (False, "Kernel's credentials or permissions were refused by the provider.", 401),
    "provider_error": (None, "The provider returned an error.", 418),
}
RESULT_KEYS = {"contract_version", "attempt_id", "call_label", "status", "prompt_sha256", "prompt_utf8_bytes", "prompt_utf16_units",
               "request_sha256", "output", "usage", "finish_reason", "effective_model", "error", "timing", "kernel", "segments"}


# ----------------------------------------------------------------- tiny HTTP client (stdlib)
class Client:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip("/"), token

    def request(self, method, path, body=None, headers=None, raw=None, auth=True):
        h = {"Content-Type": "application/json"}
        if auth and self.token:
            h[AUTH_HEADER] = self.token
        h.update(headers or {})
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")
        except (urllib.error.URLError, OSError) as e:
            # For example: the server refused (401) without reading a very large body and closed the
            # connection while this client was still sending it. Reported as status 0, not a crash.
            return 0, f"transport error: {type(e).__name__}"

    def json(self, *a, **k):
        status, text = self.request(*a, **k)
        try:
            return status, json.loads(text)
        except ValueError:
            return status, {"_unparseable": text[:200]}


class Report:
    def __init__(self):
        self.rows = []
        self.skipped = []

    def check(self, cid, ref, name, ok, detail=""):
        self.rows.append({"id": cid, "ref": ref, "name": name, "ok": bool(ok), "detail": "" if ok else str(detail)[:300]})
        print(f"{'PASS' if ok else 'FAIL'} {cid:<6} [{ref}] {name}" + ("" if ok else f"\n         -> {str(detail)[:300]}"))

    def skip(self, cid, why):
        self.skipped.append((cid, why))
        print(f"SKIP {cid:<6} {why}")


def run_checks(c, rep, fake, model_calls):
    """fake: the server is serve_fake.py (conf.* labels work). model_calls: successful executions are allowed."""
    can_exec = fake or model_calls

    # ---- A. health and capabilities (K1 1)
    s, j = c.json("GET", "/kernel/health", auth=False)
    rep.check("A1", "K1 1", "GET /kernel/health is open (no header) and returns exactly revision, git_sha, contract_version, auth_configured",
              s == 200 and set(j) == {"revision", "git_sha", "contract_version", "auth_configured"} and j["contract_version"] == 1 and j["auth_configured"] is True, (s, j))
    s, j = c.json("GET", "/kernel/capabilities", auth=False)
    s2, j2 = c.json("GET", "/kernel/capabilities", headers={AUTH_HEADER: "wrong-wrong-wrong-wrong"}, auth=False)
    rep.check("A2", "K1 1", "GET /kernel/capabilities without the token, or with a wrong one: 401 and the same fixed body", s == 401 and s2 == 401 and j == j2 == {"error": {"type": "unauthorized"}}, (s, j, s2, j2))
    s, j = c.json("GET", "/kernel/capabilities")
    rep.check("A3", "K1 1", "capabilities with the token returns exactly the five keys",
              s == 200 and set(j) == {"contract_version", "allowed_models", "allowed_tools", "max_prompt_bytes", "max_timeout_s"} and j["contract_version"] == 1
              and j["max_prompt_bytes"] == 4194304 and j["max_timeout_s"] == 280 and j["allowed_tools"] == ["function", "googleSearch"]
              and "vertex_ai/gemini-2.5-flash" in j["allowed_models"] and "vertex_ai/gemini-2.5-pro" in j["allowed_models"], (s, j))

    if s == 401:
        rep.check("A0", "K1 4", "the server accepts the token this run was given (every later check needs it)", False,
                  "capabilities answered 401 with the token; check KERNEL_AUTH_TOKEN and the header name X-Kernel-Auth-Token")
        return

    # ---- B. authentication (K1 4)
    b = make_briefing("auth check")
    bodies = set()
    for label, headers, auth in (("no header", {}, False), ("a wrong token", {AUTH_HEADER: "wrong-wrong-wrong-wrong"}, False),
                                 ("the token in Authorization instead", {"Authorization": c.token or "x"}, False), ("an empty header", {AUTH_HEADER: ""}, False)):
        s, text = c.request("POST", "/kernel/execute", body=b, headers=headers, auth=auth)
        bodies.add(text)
        rep.check("B1", "K1 2", f"POST /kernel/execute with {label}: 401", s == 401 and json.loads(text) == {"error": {"type": "unauthorized"}}, (s, text[:100]))
    rep.check("B2", "K1 2", "every 401 body is byte-identical (missing and wrong cannot be told apart)", len(bodies) == 1, bodies)
    s, j = c.json("POST", "/kernel/execute", body={"junk": 1}, auth=False)
    rep.check("B3", "K1 9.2 K-T7", "an unauthenticated garbage body gets 401, not 422 (nothing about the schema leaks before auth)", s == 401, (s, j))

    # ---- C. literal sha vectors (C1 5.2)
    rep.check("C0", "C1 5.2", "V1: the prompt is 31 code points, 32 UTF-16 units, 37 UTF-8 bytes and hashes to the literal", (len(V1_PROMPT), len(V1_PROMPT.encode("utf-16-le")) // 2, len(V1_PROMPT.encode())) == (31, 32, 37) and sha256_hex(V1_PROMPT) == V1_SHA, sha256_hex(V1_PROMPT))
    for name, fields, expected in VECTORS:
        b = make_briefing(V1_PROMPT, **fields)
        rep.check(f"C-{name}a", "C1 5.2", f"{name}: this client's request_sha256 equals the literal vector (fix your canonicalization if not)", b["request_sha256"] == expected and b["prompt_sha256"] == V1_SHA, (b["request_sha256"], expected))
        s, j = c.json("POST", "/kernel/execute", body={**b, "request_sha256": "0" * 64})
        rep.check(f"C-{name}b", "C1 5.2", f"{name}: a wrong request_sha256 is refused with 422 request_sha_mismatch and Kernel reports the literal vector as its computed value",
                  s == 422 and j["error"]["type"] == "invalid_briefing" and j["error"]["code"] == "request_sha_mismatch" and j["error"]["computed_sha256"] == expected, (s, j))
        s, j = c.json("POST", "/kernel/execute", body={**b, "prompt_sha256": "0" * 64})
        rep.check(f"C-{name}c", "C1 5.1", f"{name}: a wrong prompt_sha256 is refused with 422 prompt_sha_mismatch and Kernel reports the literal V1 sha, byte count and UTF-16 length",
                  s == 422 and j["error"]["code"] == "prompt_sha_mismatch" and j["error"]["computed_sha256"] == V1_SHA and j["error"]["prompt_utf8_bytes"] == 37 and j["error"]["prompt_utf16_units"] == 32, (s, j))
        if can_exec:
            s, j = c.json("POST", "/kernel/execute", body=b)
            rep.check(f"C-{name}d", "C1 5.1", f"{name}: the Briefing with the literal shas is accepted (200) and the RETURNED prompt_sha256 / request_sha256 equal the literals",
                      s == 200 and j.get("prompt_sha256") == V1_SHA and j.get("request_sha256") == expected, (s, str(j)[:200]))
        else:
            rep.skip(f"C-{name}d", "needs a model call (use --fake or --allow-model-calls)")

    # ---- D. every 422 code (C1 2, 5.4; K1 2)
    good = make_briefing("d")
    cases = [
        ("unknown_field", "extra", {**good, "extra": 1}), ("unknown_field", "max_prompt_bytes", {**good, "max_prompt_bytes": 9}),
        ("unknown_field", "vertex_project", {**good, "vertex_project": "x"}),
        ("missing_field", "timeout_s", {k: v for k, v in good.items() if k != "timeout_s"}),
        ("missing_field", "prompt_sha256", {k: v for k, v in good.items() if k != "prompt_sha256"}),
        ("missing_field", "request_sha256", {k: v for k, v in good.items() if k != "request_sha256"}),
        ("invalid_type", "prompt", {**good, "prompt": 5}), ("invalid_type", "temperature", {**good, "temperature": True}),
        ("invalid_type", "timeout_s", {**good, "timeout_s": None}), ("invalid_type", "segments", {**good, "segments": [1]}),
        ("invalid_value", "contract_version", {**good, "contract_version": 2}), ("invalid_value", "parse_mode", {**good, "parse_mode": "json"}),
        ("invalid_value", "reasoning_effort", {**good, "reasoning_effort": "extreme"}), ("invalid_value", "tool_choice", {**good, "tool_choice": "any"}),
        ("invalid_format", "attempt_id", {**good, "attempt_id": ""}), ("invalid_format", "call_label", {**good, "call_label": "caf\u00e9"}),
        ("invalid_format", "prompt_sha256", {**good, "prompt_sha256": good["prompt_sha256"].upper()}),
        ("invalid_format", "request_sha256", {**good, "request_sha256": "xyz"}),
        ("out_of_range", "prompt", {**good, "prompt": ""}), ("out_of_range", "temperature", {**good, "temperature": 2.5}),
        ("out_of_range", "timeout_s", {**good, "timeout_s": 281}), ("out_of_range", "max_output_tokens", {**good, "max_output_tokens": 0}),
        ("out_of_range", "tools", {**good, "tools": []}),
        ("not_allowed", "model", {**good, "model": "vertex_ai/gemini-1.5-pro"}), ("not_allowed", "tools", {**good, "tools": [{"codeExecution": {}}]}),
        ("not_allowed", "tools", {**good, "tools": [{"googleSearch": {"x": 1}}]}),
        ("too_large", "prompt", make_briefing("a" * (4 * 1024 * 1024 + 1))), ("too_large", "segments", {**good, "segments": [{}] * 2001}),
        ("prompt_sha_mismatch", "prompt_sha256", {**good, "prompt_sha256": sha256_hex("other")}),
        ("request_sha_mismatch", "request_sha256", {**good, "request_sha256": "0" * 64}),
    ]
    for code, field, body in cases:
        s, j = c.json("POST", "/kernel/execute", body=body)
        e = j.get("error", {}) if isinstance(j, dict) else {}
        rep.check("D1", "C1 2", f"422 {code} on {field}", s == 422 and e.get("type") == "invalid_briefing" and e.get("code") == code and e.get("field") == field, (s, e))
    for code, label, raw in (("invalid_json", "not JSON", b"nope"), ("invalid_json", "a NaN literal", b'{"a": NaN}'), ("invalid_json", "duplicate keys", b'{"a": 1, "a": 2}'),
                             ("invalid_json", "empty body", b""), ("not_an_object", "a JSON array", b"[]"),
                             ("invalid_prompt", "an unpaired surrogate in the prompt", json.dumps({**good, "prompt": "bad \ud800 x"}).encode("ascii")),
                             ("invalid_text", "an unpaired surrogate in a tool name", json.dumps({**good, "tools": [{"type": "function", "function": {"name": "a\ud800", "parameters": {}}}]}).encode("ascii"))):
        s, j = c.json("POST", "/kernel/execute", raw=raw)
        e = j.get("error", {}) if isinstance(j, dict) else {}
        rep.check("D2", "C1 5.4", f"422 {code} for {label}", s == 422 and e.get("type") == "invalid_briefing" and e.get("code") == code, (s, e))

    # ---- E..H need the fake model (deterministic behaviors keyed by call_label)
    if not can_exec:
        rep.skip("E-H", "result-shape, error, parse and byte-exactness checks need a model call (use --fake or --allow-model-calls)")
        return
    if model_calls and not fake:
        # against a real Kernel only the label-independent checks make sense
        s, j = c.json("POST", "/kernel/execute", body=make_briefing("Reply with the single word: ok"))
        rep.check("E0", "C1 4", "a real call returns a full ExecutionResult with all sixteen keys", s == 200 and set(j) == RESULT_KEYS and j["status"] == "ok", (s, str(j)[:200]))
        rep.skip("E-H", "provider-error, parse and echo checks need serve_fake.py (use --fake)")
        return

    # ---- E. result shape (C1 4)
    seg = [{"start": 0, "end": 4, "scaffold": True, "layer": None, "provenance": None, "note": "extra key kept", "f": 1.0}]
    s, j = c.json("POST", "/kernel/execute", body=make_briefing("shape", segments=seg, attempt_id="att-shape", call_label="conf.echo"))
    rep.check("E1", "C1 4", "a full ExecutionResult: all sixteen keys, status ok, contract_version 1", s == 200 and set(j) == RESULT_KEYS and j["status"] == "ok" and j["contract_version"] == 1, (s, sorted(j)))
    rep.check("E2", "C1 4", "attempt_id, call_label and segments are echoed verbatim (extra segment keys and the float 1.0 included)", j["attempt_id"] == "att-shape" and j["call_label"] == "conf.echo" and j["segments"] == seg and json.dumps(j["segments"], sort_keys=True) == json.dumps(seg, sort_keys=True), j["segments"])
    rep.check("E3", "C1 4", "timing has started_at (UTC ISO 8601) and an integer duration_ms; kernel has revision and git_sha; the prompt is never returned",
              j["timing"]["started_at"].endswith("Z") and isinstance(j["timing"]["duration_ms"], int) and set(j["kernel"]) == {"revision", "git_sha"} and '"shape"' not in json.dumps({k: v for k, v in j.items() if k != "output"}), j["timing"])
    s, j = c.json("POST", "/kernel/execute", body=make_briefing("x", call_label="conf.reasoning"))
    rep.check("E4", "C1 4", "usage carries reasoning_tokens (completion_tokens INCLUDES them) and effective_model has no vertex_ai/ prefix", j["usage"] == {"prompt_tokens": 120, "completion_tokens": 81, "reasoning_tokens": 80} and j["effective_model"] == "gemini-2.5-pro", (j["usage"], j["effective_model"]))
    s, j = c.json("POST", "/kernel/execute", body=make_briefing("x", call_label="conf.tool_calls"))
    tc = j["output"]["tool_calls"]
    rep.check("E5", "C1 4.1", "tool calls are returned in order, none dropped: a valid one parsed, a malformed one kept with args null, arguments_raw and a parse_error",
              j["finish_reason"] == "tool_calls" and [t["name"] for t in tc] == ["reply", "broken"] and tc[0]["args"] == {"message": "hi"} and tc[0]["parse_error"] is None
              and tc[1]["args"] is None and tc[1]["arguments_raw"] == "{not json" and tc[1]["parse_error"], tc)
    s, j = c.json("POST", "/kernel/execute", body=make_briefing("x", call_label="conf.grounded"))
    rep.check("E6", "C1 4.1", "grounding_sources come from url_citation annotations; a missing title becomes \"Source\"", j["output"]["grounding_sources"] == [{"title": "Alpha", "url": "https://a.example"}, {"title": "Source", "url": "https://b.example"}], j["output"]["grounding_sources"])
    s, j = c.json("POST", "/kernel/execute", body=make_briefing("x", call_label="conf.length"))
    rep.check("E7", "C1 4", "finish_reason length is status ok with the field set (Backend's Runner decides whether that is a failure)", s == 200 and j["status"] == "ok" and j["finish_reason"] == "length", (s, j.get("status"), j.get("finish_reason")))

    # ---- F. provider errors: category, status, FIXED generic message, no provider text (C1 4.4)
    for category, (retryable, message, status) in ERRORS.items():
        s, j = c.json("POST", "/kernel/execute", body=make_briefing("x", call_label=f"conf.error.{category}"))
        text = json.dumps(j)
        e = j.get("error") or {}
        rep.check("F1", "C1 4.4", f"{category}: HTTP 200, status error, output null, the fixed generic message, retryable {retryable}, provider_status {status}",
                  s == 200 and j["status"] == "error" and j["output"] is None and e == {"type": category, "retryable": retryable, "provider_status": status, "message": message}, (s, e))
        rep.check("F2", "C1 4.4", f"{category}: no provider text in the body (no SECRET-PROVIDER-TEXT, no projects/ path); the failed call still has its shas and timing",
                  "SECRET-PROVIDER-TEXT" not in text and "projects/" not in text and j["prompt_sha256"] == sha256_hex("x") and j["timing"]["duration_ms"] >= 0, text[:200])
    s, j = c.json("POST", "/kernel/execute", body=make_briefing("x", call_label="conf.slow", timeout_s=1))
    rep.check("F3", "C1 4.4", "Kernel's own wall-clock limit: a call slower than timeout_s returns 200 with type timeout and provider_status null", s == 200 and j["error"] == {"type": "timeout", "retryable": True, "provider_status": None, "message": "The model call timed out."}, (s, j.get("error")))

    # ---- G. parse modes (C1 4.3)
    def parsed(label, mode):
        return c.json("POST", "/kernel/execute", body=make_briefing("x", call_label=label, parse_mode=mode))[1]["output"]
    o = parsed("conf.json.plain", "json_strict")
    rep.check("G1", "C1 4.3", "json_strict on plain JSON: parsed set, parse_error null", o["parsed"] == {"a": 1} and o["parse_error"] is None, o)
    o = parsed("conf.json.fenced", "json_strict")
    rep.check("G2", "C1 4.3", "json_strict on a fenced reply: parsed null, parse_error set, the text is returned untouched (strict does not repair)", o["parsed"] is None and o["parse_error"] and o["text"].startswith("```json"), o)
    o = parsed("conf.json.fenced", "json_lenient")
    rep.check("G3", "C1 4.3", "json_lenient strips the fence", o["parsed"] == {"a": 1} and o["parse_error"] is None, o)
    o = parsed("conf.json.list", "json_lenient")
    rep.check("G4", "C1 4.3", "json_lenient on a list returns its first element; json_strict returns the whole list",
              o["parsed"] == {"a": 1} and parsed("conf.json.list", "json_strict")["parsed"] == [{"a": 1}, {"a": 2}], o)
    o = parsed("conf.json.invalid", "json_strict")
    o2 = parsed("conf.json.invalid", "json_lenient")
    rep.check("G5", "C1 4.3", "unparseable text: status stays ok, parsed null, parse_error set (no repair, no second call)", o["parsed"] is None and o["parse_error"] and o2["parsed"] is None and o2["parse_error"], (o, o2))
    o = parsed("conf.json.plain", "text")
    rep.check("G6", "C1 4.3", "text mode: parsed null, parse_error null", o["parsed"] is None and o["parse_error"] is None, o)

    # ---- H. byte exactness: what reached the model equals the prompt (C1 2.2, 5.4)
    six = ("## L1 \u2014 MANDATE\r\nYou are careful.\r\n\r\n## L2 \u2014 PERSONA\nWarm. \U0001F600  \n\n## L3 \u2014 CONTEXT\ncaf\u00e9 \u201cquotes\u201d\n\n"
           "## L4 \u2014 TASK\nSummarize.\n\n## L5 \u2014 INPUT\n{\"json\": \"looking\", \"path\": \"C:\\\\x\"}\n\n## L6 \u2014 MEMORY\n- fact\n\n"
           "### BLOCK 3: THE TRUTH\n[EXECUTION_START: now]\n\tclose \u2028 \u2029 \x00 end\n")
    for name, prompt in (("six-layer prompt (CRLF, emoji, NUL, U+2028/2029, stale BLOCK heading)", six), ("leading and trailing whitespace", "  \n padded \n\n "), ("a JSON-hostile string", '{"a": "b\\"c"} \\ \' "')):
        s, j = c.json("POST", "/kernel/execute", body=make_briefing(prompt, call_label="conf.echo"))
        rep.check("H1", "C1 2.2", f"{name}: the model received EXACTLY the prompt (echoed text equals it), untrimmed and unnormalized", s == 200 and j["output"]["text"] == prompt, (s, repr(j.get("output", {}).get("text"))[:120]))
        rep.check("H2", "C1 5", f"{name}: the returned prompt_sha256, byte count and UTF-16 length equal this client's", j["prompt_sha256"] == sha256_hex(prompt) and j["prompt_utf8_bytes"] == len(prompt.encode("utf-8")) and j["prompt_utf16_units"] == len(prompt.encode("utf-16-le", "surrogatepass")) // 2, (j.get("prompt_sha256"), j.get("prompt_utf8_bytes"), j.get("prompt_utf16_units")))
    b60 = make_briefing("num", timeout_s=60)
    s, j = c.json("POST", "/kernel/execute", body={**b60, "timeout_s": 60.0})
    rep.check("H3", "C1 5.2", "the number kind matters: a request_sha256 computed for timeout_s 60 is refused when timeout_s is sent as 60.0", s == 422 and j["error"]["code"] == "request_sha_mismatch", (s, j))
    s, j = c.json("POST", "/kernel/execute", body=make_briefing("num", timeout_s=60.0))
    rep.check("H4", "C1 5.2", "...and a request_sha256 computed for 60.0 is accepted for 60.0 (hash the same JSON number you send)", s == 200, (s, j))
    s, j = c.json("POST", "/kernel/execute", body=make_briefing("x" * (4 * 1024 * 1024), call_label="conf.echo"))
    rep.check("H5", "K1 4", "a prompt of exactly 4 MiB is accepted", s == 200 and j["prompt_utf8_bytes"] == 4 * 1024 * 1024, (s, str(j)[:100]))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="test this server instead of starting a local one with the fake model")
    ap.add_argument("--fake", action="store_true", help="with --url: the server is serve_fake.py, so the conf.* labels work")
    ap.add_argument("--allow-model-calls", action="store_true", help="with --url: allow the checks that make real model calls")
    ap.add_argument("--json", help="write a JSON report to this path")
    args = ap.parse_args()

    proc = None
    if args.url:
        token = os.environ.get("KERNEL_AUTH_TOKEN", "")
        if not token:
            sys.exit("KERNEL_AUTH_TOKEN is not set (the token of the server under test; it is never printed)")
        base, fake, model_calls = args.url, args.fake, args.allow_model_calls
    else:
        token = secrets.token_urlsafe(24)
        port = free_port()
        env = dict(os.environ, KERNEL_AUTH_TOKEN=token)
        proc = subprocess.Popen([sys.executable, os.path.join(HERE, "serve_fake.py"), "--port", str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        base, fake, model_calls = f"http://127.0.0.1:{port}", True, False
        for _ in range(120):
            try:
                urllib.request.urlopen(base + "/kernel/health", timeout=1).read()
                break
            except Exception:
                if proc.poll() is not None:
                    sys.exit("the local executor did not start:\n" + proc.stderr.read().decode()[-1500:])
                time.sleep(0.5)
        else:
            proc.kill()
            sys.exit("the local executor did not become ready in 60 s")
    rep = Report()
    try:
        run_checks(Client(base, token), rep, fake, model_calls)
    except Exception as exc:   # a malformed response must fail the run, not crash it
        rep.check("X0", "-", "the harness completed without an unexpected error", False, f"{type(exc).__name__}: {exc}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    failed = [r for r in rep.rows if not r["ok"]]
    print(f"\n{len(rep.rows)} checks, {len(failed)} failed, {len(rep.skipped)} skipped -> {'CONFORMANT' if not failed else 'NOT CONFORMANT'}")
    if args.json:
        json.dump({"checks": rep.rows, "skipped": rep.skipped}, open(args.json, "w"), indent=1)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
