"""
Step 0 token gate (option b): include_briefing / briefing_max_bytes are honoured
ONLY for a request carrying X-Kernel-Capture-Token equal to KERNEL_CAPTURE_TOKEN.

Fail closed (unset or empty env: never honoured, two empties never match); a
missing or wrong token is ignored silently, so the response is IDENTICAL to a
request that never asked for capture; the token never appears in any response,
capture, log line or error body.
"""
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
check("[unit] non-ASCII token works (encoded before compare, no TypeError)", valid("töken-\U0001F600", "töken-\U0001F600") is True and valid("töken-\U0001F600", "token") is False, "")
check("[unit] very long token works", valid("x" * 100000, "x" * 100000) is True, "")

calls = []
real_cd = capture_mod.hmac.compare_digest
with patch.object(capture_mod.hmac, "compare_digest", side_effect=lambda a, b: calls.append(1) or real_cd(a, b)):
    valid(TOKEN, TOKEN)
    valid(WRONG_SAME_LEN, TOKEN)
    n_with_env = len(calls)
    valid(TOKEN, None)
    valid(TOKEN, "")
check("[unit] comparison goes through hmac.compare_digest (constant time), and is skipped when env is unset/empty", n_with_env == 2 and len(calls) == 2, (n_with_env, len(calls)))

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
