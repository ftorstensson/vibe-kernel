"""
Step 0 token gate (option b): include_briefing / briefing_max_bytes are honoured
ONLY for a request carrying X-Kernel-Capture-Token equal to KERNEL_CAPTURE_TOKEN.

Fail closed (unset or empty env: never honoured, two empties never match); a
missing or wrong token is ignored silently, so the response is IDENTICAL to a
request that never asked for capture; the token never appears in any response,
capture, log line or error body.
"""
import contextvars
import io
import json
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import recording  # noqa: E402
import core.agent_factory as agent_factory  # noqa: E402
import core.capture as capture_mod  # noqa: E402
from core.capture import CAPTURE_TOKEN_HEADER, CAPTURE_TOKEN_ENV, capture_calls, capture_token_valid  # noqa: E402
from endpoint_payloads import ENDPOINTS, EXPECT_LABEL  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

TOKEN = "T0ken-Correct-7c1e9b52a4d8"
WRONG_SAME_LEN = "T0ken-Wrongg-7c1e9b52a4d8"
WRONG_SHORT = "nope"
WRONG_LONG = TOKEN + "-and-more"
results = []
seen_outputs = []          # every response body / log / stdout string produced by any request below
client = TestClient(main.app)


def check(name, ok, detail=""):
    results.append((name, bool(ok), "" if ok else detail))


class LogCatcher(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        try:
            self.lines.append(self.format(record))
        except Exception:
            self.lines.append(str(record.msg))


log_catcher = LogCatcher()
for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "starlette", "litellm"):
    logging.getLogger(name).addHandler(log_catcher)
logging.getLogger().setLevel(logging.DEBUG)


def post(path, body, headers=None, env=TOKEN):
    """One fresh request with the process env set to `env` (None = variable unset)."""
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with patch.dict(os.environ, {}):
        if env is None:
            os.environ.pop(CAPTURE_TOKEN_ENV, None)
        else:
            os.environ[CAPTURE_TOKEN_ENV] = env
        with recording(), redirect_stdout(out_buf), redirect_stderr(err_buf):
            resp = client.post(path, json=body, headers=headers or {})
    seen_outputs.append(resp.text)
    seen_outputs.append(out_buf.getvalue() + err_buf.getvalue())
    return resp


def with_flag(body, max_bytes=None):
    out = {**body, "include_briefing": True}
    if max_bytes is not None:
        out["briefing_max_bytes"] = max_bytes
    return out


AUTH = {CAPTURE_TOKEN_HEADER: TOKEN}

# ------------------------------------------------ per endpoint: the full matrix
for path, body in ENDPOINTS.items():
    baseline = post(path, body)
    check(f"{path}: baseline (no flag, no header) is 200", baseline.status_code == 200, baseline.status_code)
    base_json = baseline.json()

    good = post(path, with_flag(body), AUTH)
    gj = good.json()
    check(f"{path}: correct token + flag -> calls returned, first label {EXPECT_LABEL[path]}",
          good.status_code == 200 and bool(gj.get("calls")) and gj["calls"][0]["label"] == EXPECT_LABEL[path] and set(gj["kernel_version"]) == {"revision", "git_sha"}, gj.get("calls"))

    def identical_to_baseline(resp, why):
        same = resp.status_code == baseline.status_code and resp.json() == base_json and resp.headers.get("content-type") == baseline.headers.get("content-type")
        check(f"{path}: {why} -> response IDENTICAL to a request that never asked (status, body, content-type)", same, (resp.status_code, resp.text[:200]))
        check(f"{path}: {why} -> calls and kernel_version null", resp.json().get("calls") is None and resp.json().get("kernel_version") is None, "")

    identical_to_baseline(post(path, with_flag(body), {CAPTURE_TOKEN_HEADER: WRONG_SAME_LEN}), "wrong token (same length)")
    identical_to_baseline(post(path, with_flag(body), {CAPTURE_TOKEN_HEADER: WRONG_SHORT}), "wrong token (shorter)")
    identical_to_baseline(post(path, with_flag(body), {CAPTURE_TOKEN_HEADER: WRONG_LONG}), "wrong token (longer, correct prefix)")
    identical_to_baseline(post(path, with_flag(body), {CAPTURE_TOKEN_HEADER: TOKEN.upper()}), "token in the wrong letter case (value is case-sensitive)")
    identical_to_baseline(post(path, with_flag(body)), "flag with NO header")
    identical_to_baseline(post(path, with_flag(body, max_bytes=50), {CAPTURE_TOKEN_HEADER: WRONG_SHORT}), "wrong token with briefing_max_bytes")
    identical_to_baseline(post(path, with_flag(body), AUTH, env=None), "env var UNSET, correct-looking header sent")
    identical_to_baseline(post(path, with_flag(body), AUTH, env=""), "env var EMPTY, non-empty header sent")
    identical_to_baseline(post(path, with_flag(body), {CAPTURE_TOKEN_HEADER: ""}, env=""), "env EMPTY and header EMPTY (two empties must not match)")
    identical_to_baseline(post(path, with_flag(body), {CAPTURE_TOKEN_HEADER: ""}), "empty header value with a real env token")
    identical_to_baseline(post(path, body, AUTH), "correct token but flag not set")

# ---------------------------------------------------------- header case-insensitivity
path, body = "/kernel/agents/run_turn", ENDPOINTS["/kernel/agents/run_turn"]
for header_name in ("x-kernel-capture-token", "X-KERNEL-CAPTURE-TOKEN", "X-Kernel-Capture-Token", "x-Kernel-capture-TOKEN"):
    r = post(path, with_flag(body), {header_name: TOKEN})
    check(f"header name '{header_name}' is honoured (case-insensitive)", bool(r.json().get("calls")), r.text[:150])
r = post(path, with_flag(body, max_bytes=50), AUTH)
check("correct token also honours briefing_max_bytes (stub returned)", r.json()["calls"][0]["prompt"] is None and r.json()["calls"][0]["oversize"] is True, r.text[:150])

# ------------------------------------------------------------ unit: capture_token_valid
def valid(presented, env):
    with patch.dict(os.environ, {}):
        if env is None:
            os.environ.pop(CAPTURE_TOKEN_ENV, None)
        else:
            os.environ[CAPTURE_TOKEN_ENV] = env
        return capture_token_valid(presented)


check("[unit] correct token is valid", valid(TOKEN, TOKEN) is True, "")
check("[unit] wrong token is invalid", valid(WRONG_SAME_LEN, TOKEN) is False, "")
check("[unit] None presented is invalid", valid(None, TOKEN) is False, "")
check("[unit] empty presented is invalid", valid("", TOKEN) is False, "")
check("[unit] env unset is invalid even with a token presented", valid(TOKEN, None) is False, "")
check("[unit] env empty is invalid even with a token presented", valid(TOKEN, "") is False, "")
check("[unit] env empty and presented empty do NOT match (fail closed)", valid("", "") is False, "")
NON_ASCII = "töken-\U0001F600-日本語-abcdef"
check("[ascii] a non-ASCII configured token is treated as unset: it never authorizes, even with the identical header (Starlette decodes headers as latin-1, so it could never match over HTTP)",
      valid(NON_ASCII, NON_ASCII) is False and valid(NON_ASCII.encode("utf-8").decode("latin-1"), NON_ASCII) is False, "")
SYMBOLS = "aB3$%^&*()_+-=[]{};:,.<>?/~!@#0123456789"
check("[ascii] a printable-ASCII token with symbols is fine", valid(SYMBOLS, SYMBOLS) is True, "")
check("[ascii] a configured token with an INTERIOR space is treated as unset (visible ASCII 0x21-0x7e only, same as Backend)",
      valid("abcdefgh ijklmnop-0123", "abcdefgh ijklmnop-0123") is False and valid("abcdefgh ijklmnop-0123", TOKEN) is False, "")
check("[ascii] interior tab, newline or carriage return also make the configured token unset",
      valid("abcdefgh\tijklmnop-0123", "abcdefgh\tijklmnop-0123") is False and valid("abcdefgh\nijklmnop-0123", "abcdefgh\nijklmnop-0123") is False and valid("abcdefgh\rijklmnop-0123", "abcdefgh\rijklmnop-0123") is False, "")
check("[ascii] the boundary characters 0x21 (!) and 0x7e (~) are allowed; 0x20 (space) and 0x7f (DEL) are not",
      valid("!" * 16, "!" * 16) is True and valid("~" * 16, "~" * 16) is True and valid("a" * 15 + " ", "a" * 15 + " ") is False and valid("a" * 8 + " " + "a" * 8, "a" * 8 + " " + "a" * 8) is False and valid("a" * 15 + "\x7f", "a" * 15 + "\x7f") is False, "")
check("[ascii] a configured token containing a control character is treated as unset", valid("tok\x01en-0123456789abcdef", "tok\x01en-0123456789abcdef") is False and valid("tok\ten-0123456789abcdef", "tok\ten-0123456789abcdef") is False, "")
check("[ascii] a configured token containing DEL (0x7f) is treated as unset (a NUL cannot exist in a real env var; the OS rejects it)", valid("tok\x7fen-0123456789abcdef", "tok\x7fen-0123456789abcdef") is False, "")
check("[unit] very long token works", valid("x" * 100000, "x" * 100000) is True, "")

calls = []
real_cd = capture_mod.hmac.compare_digest
with patch.object(capture_mod.hmac, "compare_digest", side_effect=lambda a, b: calls.append(1) or real_cd(a, b)):
    valid(TOKEN, TOKEN)
    valid(WRONG_SAME_LEN, TOKEN)
    n_with_env = len(calls)
    valid(TOKEN, None)
    valid(TOKEN, "")
check("[unit] hmac.compare_digest is what runs (an invocation spy, not a timing test), and it is skipped when the env is unset/empty", n_with_env == 2 and len(calls) == 2, (n_with_env, len(calls)))

# --- whitespace stripping (Secret Manager values carry a trailing newline; an HTTP header cannot)
for label_, env_val in (("trailing \\n", TOKEN + "\n"), ("trailing \\r\\n", TOKEN + "\r\n"), ("leading and trailing whitespace", "  " + TOKEN + " \t\n"), ("several trailing newlines", TOKEN + "\n\n")):
    check(f"[strip] env value with {label_} + the stripped header value -> valid", valid(TOKEN, env_val) is True, repr(env_val))
check("[strip] the presented value is stripped the same way (trailing newline on the header side)", valid(TOKEN + "\n", TOKEN) is True and valid("  " + TOKEN + "  ", TOKEN + "\n") is True, "")
check("[strip] stripping is only for the ends: interior whitespace still has to match", valid(TOKEN[:5] + " " + TOKEN[5:], TOKEN) is False and valid(TOKEN, TOKEN[:5] + " " + TOKEN[5:]) is False, "")
check("[strip] a wrong token is still wrong when the env has a trailing newline", valid(WRONG_SAME_LEN, TOKEN + "\n") is False, "")
check("[strip] a whitespace-only env value is treated as unset (never authorizes)", valid("   ", "  \n") is False and valid(TOKEN, "  \n\t") is False, "")
check("[strip] a whitespace-only presented value is not valid", valid("  \n", TOKEN) is False, "")

# --- minimum length: a configured token shorter than 16 after stripping fails closed
from core.capture import MIN_TOKEN_LENGTH  # noqa: E402
check("[min-length] the minimum is 16", MIN_TOKEN_LENGTH == 16, MIN_TOKEN_LENGTH)
t15, t16 = "a" * 15, "a" * 16
check("[min-length] a 15-character token never authorizes, even with a matching header", valid(t15, t15) is False, "")
check("[min-length] a 16-character token authorizes with a matching header (boundary)", valid(t16, t16) is True, "")
check("[min-length] length is measured AFTER stripping: 16 chars + newline is valid, 15 chars + newline is not", valid(t16, t16 + "\n") is True and valid(t15, t15 + "\n") is False, "")
check("[min-length] padding a short token with whitespace does not get past the minimum", valid("short", "short" + " " * 30) is False and valid("short", " " * 30 + "short") is False, "")
check("[min-length] a short token does not authorize a longer-prefix header either", valid(t16, t15) is False, "")

# --- over HTTP: a trailing-newline env value (as Secret Manager delivers it) with the stripped header
for path_, body_ in (("/kernel/agents/run_turn", ENDPOINTS["/kernel/agents/run_turn"]), ("/kernel/functions/assess_coverage", ENDPOINTS["/kernel/functions/assess_coverage"]), ("/kernel/invoke", ENDPOINTS["/kernel/invoke"])):
    baseline_ = post(path_, body_)
    with_nl = post(path_, with_flag(body_), AUTH, env=TOKEN + "\n")
    check(f"{path_}: env value with a trailing newline + the stripped header -> capture honoured", bool(with_nl.json().get("calls")), with_nl.text[:150])
    short_env = "s3cret-15-chars"
    short = post(path_, with_flag(body_), {CAPTURE_TOKEN_HEADER: short_env}, env=short_env + "\n")
    check(f"{path_}: a 15-character configured token (matching header) -> ignored, response identical to a request that never asked",
          len(short_env) == 15 and short.status_code == baseline_.status_code and short.json() == baseline_.json() and short.json().get("calls") is None, short.text[:150])

# --- (ASCII, over HTTP) a non-ASCII configured token fails closed, visibly identical to "never asked"
NON_ASCII_ENV = "töken-日本語-0123456789abcdef"
for path_, body_ in (("/kernel/agents/run_turn", ENDPOINTS["/kernel/agents/run_turn"]), ("/kernel/invoke", ENDPOINTS["/kernel/invoke"])):
    baseline_ = post(path_, body_)
    for how, header_value in (("UTF-8 bytes", NON_ASCII_ENV.encode("utf-8")), ("latin-1 decoded text", NON_ASCII_ENV.encode("utf-8").decode("latin-1").encode("latin-1"))):
        r_ = post(path_, with_flag(body_), {CAPTURE_TOKEN_HEADER: header_value}, env=NON_ASCII_ENV)
        check(f"{path_}: non-ASCII configured token, header sent as {how} -> fails closed, response identical to a request that never asked",
              r_.status_code == baseline_.status_code and r_.json() == baseline_.json() and r_.json().get("calls") is None, r_.text[:150])
space_env = "abcdefgh ijklmnop-0123456789"
sp_ = post("/kernel/agents/run_turn", with_flag(ENDPOINTS["/kernel/agents/run_turn"]), {CAPTURE_TOKEN_HEADER: space_env}, env=space_env)
sp_base = post("/kernel/agents/run_turn", ENDPOINTS["/kernel/agents/run_turn"])
check("/kernel/agents/run_turn: a configured token with an interior space (matching header) -> fails closed, response identical to a request that never asked",
      sp_.status_code == sp_base.status_code and sp_.json() == sp_base.json() and sp_.json().get("calls") is None, sp_.text[:150])
symbol_token = "Tk-aB3$%^&*_+~.abcdefgh"
sym_ = post("/kernel/agents/run_turn", with_flag(ENDPOINTS["/kernel/agents/run_turn"]), {CAPTURE_TOKEN_HEADER: symbol_token}, env=symbol_token)
check("[ascii] over HTTP a printable-ASCII token with symbols is honoured", bool(sym_.json().get("calls")), sym_.text[:150])

# --- (duplicate headers) Starlette's headers.get returns the FIRST value; pin that behaviour
dup_path, dup_body = "/kernel/agents/run_turn", ENDPOINTS["/kernel/agents/run_turn"]
r_wc = post(dup_path, with_flag(dup_body), [(CAPTURE_TOKEN_HEADER, WRONG_SAME_LEN), (CAPTURE_TOKEN_HEADER, TOKEN)])
r_cw = post(dup_path, with_flag(dup_body), [(CAPTURE_TOKEN_HEADER, TOKEN), (CAPTURE_TOKEN_HEADER, WRONG_SAME_LEN)])
check("[duplicate headers] [wrong, correct]: the first value wins, so NOT honoured", r_wc.json().get("calls") is None, r_wc.text[:120])
check("[duplicate headers] [correct, wrong]: the first value wins, so honoured", bool(r_cw.json().get("calls")), r_cw.text[:120])

# --- (scope) the authorization is removed when the request ends, on success, on error, and even from another context
import asyncio  # noqa: E402
from core.capture import _AUTHORIZED, reset_capture_authorized  # noqa: E402


class _FakeRequest:
    def __init__(self, value):
        self.headers = {CAPTURE_TOKEN_HEADER: value} if value is not None else {}


async def gate_lifecycle(header_value, raise_inside=False):
    with patch.dict(os.environ, {CAPTURE_TOKEN_ENV: TOKEN}):
        gen = main.capture_gate(_FakeRequest(header_value))
        await gen.__anext__()
        inside = _AUTHORIZED.get()
        try:
            if raise_inside:
                await gen.athrow(RuntimeError("request body failed"))
            else:
                await gen.__anext__()
        except (StopAsyncIteration, RuntimeError):
            pass
    return inside, _AUTHORIZED.get()


ok_in, ok_after = asyncio.run(gate_lifecycle(TOKEN))
bad_in, bad_after = asyncio.run(gate_lifecycle(WRONG_SAME_LEN))
err_in, err_after = asyncio.run(gate_lifecycle(TOKEN, raise_inside=True))
check("[scope] gate: authorized while the request runs, and the flag is False again after it ends", ok_in is True and ok_after is False, (ok_in, ok_after))
check("[scope] gate: a wrong token is never authorized, and the flag stays False after", bad_in is False and bad_after is False, (bad_in, bad_after))
check("[scope] gate: the flag is False after the request even when the request body raised", err_in is True and err_after is False, (err_in, err_after))

foreign = contextvars.Context().run(lambda: _AUTHORIZED.set(True))
_AUTHORIZED.set(True)
reset_capture_authorized(foreign)
check("[scope] a token that cannot be reset (from another context) falls back to DENY, never leaving the flag set", _AUTHORIZED.get() is False, _AUTHORIZED.get())

from fastapi import Depends, FastAPI  # noqa: E402
probe_app = FastAPI(dependencies=[Depends(main.capture_gate)])


@probe_app.get("/probe")
async def probe():
    return {"authorized": _AUTHORIZED.get()}


probe_client = TestClient(probe_app)
with patch.dict(os.environ, {CAPTURE_TOKEN_ENV: TOKEN}):
    p_good = probe_client.get("/probe", headers=AUTH).json()["authorized"]
    p_bad = probe_client.get("/probe", headers={CAPTURE_TOKEN_HEADER: WRONG_SAME_LEN}).json()["authorized"]
    p_none = probe_client.get("/probe").json()["authorized"]
check("[scope] inside a real request the gate authorizes only the right token", p_good is True and p_bad is False and p_none is False, (p_good, p_bad, p_none))
check("[scope] the test process's own context was never authorized by those requests", _AUTHORIZED.get() is False, _AUTHORIZED.get())

# primitive: default deny without the gate
from core.capture import set_capture_authorized  # noqa: E402
import contextvars  # noqa: E402


def in_fresh_context(fn):
    return contextvars.Context().run(fn)


def try_capture():
    with capture_calls(True) as cap:
        return cap


check("[unit] capture_calls(True) is DENIED when the request was never authorized (default deny)", in_fresh_context(try_capture) is None, "")


def try_capture_authorized():
    set_capture_authorized(True)
    with capture_calls(True) as cap:
        return cap is not None


check("[unit] capture_calls(True) is honoured once the gate authorized the request", in_fresh_context(try_capture_authorized) is True, "")

# ---------------------------------------------- concurrency: authorization is per request
def one(i):
    authorized = i % 2 == 0
    headers = AUTH if authorized else {CAPTURE_TOKEN_HEADER: WRONG_SAME_LEN}
    body = {**ENDPOINTS["/kernel/agents/run_turn"], "history": [{"role": "user", "content": f"MARK-{i}"}], "include_briefing": True}
    r = client.post("/kernel/agents/run_turn", json=body, headers=headers)
    return i, authorized, r.json()


# ONE fake-model patch and ONE stdout redirect around the whole pool (patching per thread races and
# can let a request through to the real model)
with patch.dict(os.environ, {CAPTURE_TOKEN_ENV: TOKEN}), recording(), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), ThreadPoolExecutor(max_workers=8) as pool:
    outs = list(pool.map(one, range(16)))
ok = all((a and o["calls"] and f"MARK-{i}" in o["calls"][0]["prompt"]) or (not a and o["calls"] is None) for i, a, o in outs)
check("[isolation] 16 concurrent requests, alternating correct/wrong token: only the authorized ones get calls, each only its own", ok, [(i, a, o["calls"] is not None) for i, a, o in outs])
after = post("/kernel/agents/run_turn", with_flag(ENDPOINTS["/kernel/agents/run_turn"]))
check("[isolation] a request with no header right after authorized ones is not authorized", after.json()["calls"] is None, after.text[:120])

# ------------------------------------------------ the token never leaks anywhere
error_bodies = []
bad_body = {"include_briefing": True, "not_a_real_field": 1}
r422 = post("/kernel/agents/run_turn", bad_body, AUTH)                                   # validation error, correct token
r422b = post("/kernel/agents/run_turn", bad_body, {CAPTURE_TOKEN_HEADER: WRONG_SAME_LEN})  # same body, wrong token
check("[leak] validation errors are 422 and identical with a correct vs wrong token", r422.status_code == 422 and r422.text == r422b.text, (r422.status_code, r422b.status_code))
error_bodies += [r422.text, r422b.text]


def boom(**kwargs):
    raise RuntimeError("simulated provider failure")


for label_, headers_ in (("correct token", AUTH), ("wrong token", {CAPTURE_TOKEN_HEADER: WRONG_SAME_LEN}), ("no token", {})):
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with patch.dict(os.environ, {CAPTURE_TOKEN_ENV: TOKEN}), patch.object(agent_factory.litellm, "completion", side_effect=boom), redirect_stdout(out_buf), redirect_stderr(err_buf):
        r500 = client.post("/kernel/agents/run_turn", json=with_flag(ENDPOINTS["/kernel/agents/run_turn"]), headers=headers_)
    seen_outputs.append(r500.text)
    seen_outputs.append(out_buf.getvalue() + err_buf.getvalue())
    check(f"[leak] 500 error path ({label_}): status 500 with the plain provider message, no calls key content", r500.status_code == 500 and "simulated provider failure" in r500.text, (r500.status_code, r500.text[:150]))
    error_bodies.append(r500.text)

all_captured_calls = []
for path, body in ENDPOINTS.items():
    all_captured_calls.append(json.dumps(post(path, with_flag(body), AUTH).json().get("calls")))

haystacks = {
    "response bodies / stdout / stderr": "\n".join(seen_outputs),
    "captured calls (all 11 endpoints, all fields incl. prompts)": "\n".join(all_captured_calls),
    "log records (root, uvicorn, fastapi, starlette, litellm)": "\n".join(log_catcher.lines),
    "error bodies (422 and 500)": "\n".join(error_bodies),
}
for what, text in haystacks.items():
    for needle_name, needle in (("correct token", TOKEN), ("wrong token (same length)", WRONG_SAME_LEN), ("wrong token (longer)", WRONG_LONG)):
        check(f"[leak] the {needle_name} never appears in {what} ({len(text)} chars searched)", needle not in text, f"FOUND in {what}")
check("[leak] the env var NAME's value is not echoed as a header/field anywhere either (header name may not appear in bodies)",
      CAPTURE_TOKEN_HEADER.lower() not in haystacks["response bodies / stdout / stderr"].lower() and CAPTURE_TOKEN_HEADER.lower() not in haystacks["captured calls (all 11 endpoints, all fields incl. prompts)"].lower(), "")
check("[leak] log catcher actually saw traffic (the search above is not vacuous)", len(log_catcher.lines) > 0 or len(haystacks["response bodies / stdout / stderr"]) > 1000, len(log_catcher.lines))

# ------------------------------------------------------------------- report
print("\n=== Step 0 token gate verification ===")
all_pass = True
for name, ok, detail in results:
    if not ok:
        all_pass = False
        print(f"[FAIL] {name} -- {detail}")
if all_pass:
    print("(all individual checks passed; failures would be listed above)")
print(f"\n{len(results)} checks, {'ALL PASS' if all_pass else 'SOME FAILED'}")
sys.exit(0 if all_pass else 1)
