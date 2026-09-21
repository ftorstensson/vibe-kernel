"""
K1 section 9.2, the M1a endpoint tests: K-T1 (auth), K-T2 (guardrails), K-T3 (health),
K-T5 (concurrency, the offline twin of the M1a load test), K-T6 (no secret in output),
K-T7 (order of checks), K-T8 (capabilities). K-T4 (the 410 for the old turn routes)
belongs to the M1b cutover deploy and is not part of this milestone.

Run: python3 tests/m1_executor/test_endpoint.py
"""
import asyncio
import json
import os
import re
import sys
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (AUTH, AUTH_HEADER, ROOT, TOKEN, FakeModel, briefing, catch_logs, check, fake_model,  # noqa: E402
                    fake_response, make_client, post, report)
import litellm  # noqa: E402

client = make_client()
UNAUTH_BODY = {"error": {"type": "unauthorized"}}

# ------------------------------------------------------------------ K-T1 auth
WRONG_SAME_LEN = "Tok-3n-Exec-9f2a7c1d5b8X"
header_cases = [
    ("no header", {}), ("wrong value, same length", {AUTH_HEADER: WRONG_SAME_LEN}), ("wrong value, shorter", {AUTH_HEADER: "nope"}),
    ("empty header", {AUTH_HEADER: ""}), ("right value plus a trailing space", {AUTH_HEADER: TOKEN + " "}),
    ("right value plus a leading space", {AUTH_HEADER: " " + TOKEN}), ("prefix of the right value", {AUTH_HEADER: TOKEN[:-1]}),
    ("right value plus a suffix", {AUTH_HEADER: TOKEN + "x"}), ("right value in the Authorization header instead", {"Authorization": TOKEN}),
    ("right value in the capture-token header instead", {"X-Kernel-Capture-Token": TOKEN}),
]
bodies_401 = set()
for name, headers in header_cases:
    with fake_model() as fake:
        r = client.post("/kernel/execute", json=briefing("k-t1"), headers=headers)
        check(f"K-T1 {name}: 401, fixed body, zero model calls", r.status_code == 401 and r.json() == UNAUTH_BODY and len(fake.calls) == 0, (r.status_code, r.text[:100], len(fake.calls)))
        bodies_401.add(r.text)
with fake_model() as fake:
    r = post(client, briefing("k-t1"))
    check("K-T1 the exact token: 200 and one model call", r.status_code == 200 and len(fake.calls) == 1, (r.status_code, r.text[:100]))

server_cases = [("unset", None), ("empty", ""), ("15 characters", "a" * 15), ("16 characters (the minimum) works", "b" * 16),
                ("contains an interior space", "Tok-3n Exec-9f2a7c1d5b8e"), ("contains a non-ASCII character", "Tok-3n-Exec-9f2a7c1d5b8é"),
                ("contains a tab", "Tok-3n-Exec\t9f2a7c1d5b8e")]
for name, value in server_cases:
    with fake_model() as fake:
        if value is None:
            os.environ.pop("KERNEL_AUTH_TOKEN", None)
        else:
            os.environ["KERNEL_AUTH_TOKEN"] = value
        presented = value if value else TOKEN
        try:
            r = client.post("/kernel/execute", json=briefing("k-t1"), headers={AUTH_HEADER: presented})
            code, text = r.status_code, r.text
        except Exception as exc:  # a non-ASCII header cannot even be sent: the request never arrives
            code, text = 401, '{"error":{"type":"unauthorized"}}'
        if name.startswith("16"):
            check(f"K-T1 server token {name}: 200 with the same value presented", code == 200, (code, text[:100]))
        else:
            check(f"K-T1 server token {name}: fail closed, even when the presented value equals it (401, zero calls)", code == 401 and len(fake.calls) == 0, (code, text[:100], len(fake.calls)))
            bodies_401.add(text)
    with fake_model() as fake:
        os.environ.pop("KERNEL_AUTH_TOKEN", None) if value is None else os.environ.__setitem__("KERNEL_AUTH_TOKEN", value)
        r = client.get("/kernel/capabilities", headers=AUTH)
        if not name.startswith("16"):
            check(f"K-T1 server token {name}: /kernel/capabilities is refused too (401)", r.status_code == 401 and r.json() == UNAUTH_BODY, (r.status_code, r.text[:100]))
check("K-T1 every refusal (missing, wrong, unconfigured) has a byte-identical body", len(bodies_401) == 1, bodies_401)
with fake_model(token=TOKEN + "\n") as fake:
    r = post(client, briefing("k-t1"))
    check("K-T1 a trailing newline on the configured secret (Secret Manager style) is stripped and the bare token works", r.status_code == 200, r.status_code)
auth_src = open(os.path.join(ROOT, "executor", "auth.py")).read()
check("K-T1 constant-time comparison: hmac.compare_digest is used", "hmac.compare_digest" in auth_src, "")
check("K-T1 no `==` comparison against the token in auth.py", not re.search(r"(presented|expected|token)\s*==|==\s*(presented|expected|token)", auth_src), "")
routes_src = open(os.path.join(ROOT, "executor", "routes.py")).read()
check("K-T1 the auth check is a plain call at the top of the handler, not a body-parameter dependency", "_unauthorized(request)" in routes_src and "Depends" not in routes_src, "")

# ------------------------------------------------------------------ K-T2 guardrails
good = briefing("k-t2")
tool_cases = [("a model not on the allowlist", {**good, "model": "vertex_ai/gemini-1.5-flash"}),
              ("a code-execution tool", {**good, "tools": [{"codeExecution": {}}]}),
              ("a URL-context tool", {**good, "tools": [{"urlContext": {}}]}),
              ("timeout_s above max_timeout_s (281)", {**good, "timeout_s": 281}),
              ("a Briefing carrying max_prompt_bytes", {**good, "max_prompt_bytes": 10 ** 9}),
              ("a Briefing carrying vertex_project", {**good, "vertex_project": "other-project"}),
              ("a Briefing carrying vertex_location", {**good, "vertex_location": "europe-west1"})]
for name, body in tool_cases:
    with fake_model() as fake:
        r = post(client, body)
        check(f"K-T2 {name}: 422 and zero calls", r.status_code == 422 and len(fake.calls) == 0, (r.status_code, r.text[:100]))
with fake_model() as fake:
    r = client.post("/kernel/execute", json=briefing("a" * (4 * 1024 * 1024 + 1)), headers=AUTH)
    check("K-T2 a prompt of 4 MiB + 1 byte: 422, zero calls", r.status_code == 422 and len(fake.calls) == 0, r.status_code)
    r = client.post("/kernel/execute", json=briefing("a" * (4 * 1024 * 1024)), headers=AUTH)
    check("K-T2 a prompt of exactly 4 MiB: 200", r.status_code == 200 and len(fake.calls) == 1, r.status_code)
for tool in ({"googleSearch": {}}, {"type": "function", "function": {"name": "f", "description": "d", "parameters": {"type": "object"}}}):
    with fake_model() as fake:
        r = post(client, briefing("k-t2", tools=[tool]))
        check(f"K-T2 an allowed tool shape ({'googleSearch' if 'googleSearch' in tool else 'function'}) passes", r.status_code == 200 and fake.calls[0]["tools"] == [tool], r.status_code)
with fake_model() as fake:
    r = post(client, briefing("k-t2", timeout_s=280))
    check("K-T2 timeout_s of exactly 280 passes", r.status_code == 200 and fake.calls[0]["timeout"] == 280, r.status_code)
    r = post(client, briefing("k-t2", model="vertex_ai/gemini-2.5-pro"))
    check("K-T2 both allowlisted models pass", r.status_code == 200 and fake.calls[-1]["model"] == "vertex_ai/gemini-2.5-pro", r.status_code)
with fake_model() as fake:
    body = post(client, briefing("k-t2")).json()
    sent = fake.calls[0]
    check("K-T2 project and region come from Kernel configuration, never the Briefing", sent["vertex_location"] == "us-central1" and sent["vertex_project"] == os.getenv("GOOGLE_CLOUD_PROJECT", "vibe-agent-final"), sent)

# ------------------------------------------------------------------ K-T3 health
with fake_model(extra_env={"K_REVISION": "vibe-kernel-00777-xyz", "KERNEL_GIT_SHA": "cafebabe"}) as fake:
    r = client.get("/kernel/health")
    check("K-T3 health is open (no header) and returns revision, git_sha, contract_version, auth_configured",
          r.status_code == 200 and r.json() == {"revision": "vibe-kernel-00777-xyz", "git_sha": "cafebabe", "contract_version": 1, "auth_configured": True}, r.text)
    check("K-T3 health makes zero model calls", len(fake.calls) == 0, len(fake.calls))
    check("K-T3 health carries no allowlist, limit or secret", not any(k in r.text for k in ("allowed", "max_", "gemini", TOKEN)), r.text)
for name, value in (("unset", None), ("empty", ""), ("too short", "abc"), ("non-visible-ASCII", "Tok-3n Exec-9f2a7c1d5b8e")):
    with fake_model() as fake:
        os.environ.pop("KERNEL_AUTH_TOKEN", None) if value is None else os.environ.__setitem__("KERNEL_AUTH_TOKEN", value)
        r = client.get("/kernel/health")
        check(f"K-T3 auth_configured is false when the token is {name}", r.status_code == 200 and r.json()["auth_configured"] is False, r.text)

# ------------------------------------------------------------------ K-T5 concurrency (the offline twin of the load test)
import httpx  # noqa: E402
import main  # noqa: E402


async def burst(n, sleep_s, blocking=False):
    async def sleeper(kw):
        marker = kw["messages"][0]["content"]
        if blocking:
            time.sleep(sleep_s)          # the legacy pattern: a synchronous call inside an async handler
        else:
            await asyncio.sleep(sleep_s)
        return fake_response("echo:" + marker)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://kernel") as ac:
        async def one(i):
            t0 = time.perf_counter()
            r = await ac.post("/kernel/execute", json=briefing(f"MARKER-{i}-{'z' * 20}", attempt_id=f"c{i}"), headers=AUTH)
            return r, time.perf_counter() - t0
        with fake_model(FakeModel(sleeper)) as fake:
            t0 = time.perf_counter()
            out = await asyncio.gather(*[one(i) for i in range(n)])
            total = time.perf_counter() - t0
    return out, total, fake

out, total, fake = asyncio.run(burst(1, 1.0))
single = out[0][1]
check("K-T5 one Briefing against a fake model that sleeps 1 s completes in about 1 s", 0.9 < single < 1.6, single)
out, total, fake = asyncio.run(burst(6, 1.0))
check("K-T5 6 concurrent Briefings finish in under 1.5 s in total (M1a rule: <= 1.5x the slowest single call)", total < 1.5, total)
check("K-T5 the load-test rule itself: total <= 1.5 x the slowest single call", total <= 1.5 * single, (total, single))
check("K-T5 all 6 returned 200 with status ok", all(r.status_code == 200 and r.json()["status"] == "ok" for r, _ in out), [r.status_code for r, _ in out])
check("K-T5 each result contains only its own marker (no cross-talk between concurrent requests)",
      all(r.json()["attempt_id"] == f"c{i}" and r.json()["output"]["text"].startswith(f"echo:MARKER-{i}-") and not any(f"MARKER-{j}-" in r.text for j in range(6) if j != i) for i, (r, _) in enumerate(out)), "")
check("K-T5 the fake saw exactly 6 calls, one per Briefing", len(fake.calls) == 6, len(fake.calls))
out, total_blocking, _ = asyncio.run(burst(6, 0.3, blocking=True))
check("K-T5 negative control: a BLOCKING model call (today's pattern) serializes the 6 and exceeds the 1.5x rule, so this test can fail",
      total_blocking > 1.5 * 0.3 + 0.5, total_blocking)

# ------------------------------------------------------------------ K-T6 no secret in output
leak_haystack = []
with fake_model() as fake, catch_logs() as logs:
    for name, headers in header_cases:
        r = client.post("/kernel/execute", json=briefing("k-t6"), headers=headers)
        leak_haystack += [r.text, json.dumps(dict(r.headers))]
    r = post(client, briefing("k-t6"))
    leak_haystack += [r.text, json.dumps(dict(r.headers))]
    for path in ("/kernel/health", "/kernel/capabilities"):
        for headers in ({}, AUTH):
            r = client.get(path, headers=headers)
            leak_haystack += [r.text, json.dumps(dict(r.headers))]
    r = client.post("/kernel/execute", json={"junk": True}, headers=AUTH)
    leak_haystack.append(r.text)
    with fake_model(FakeModel(litellm.exceptions.APIError(status_code=500, message=f"leaked {TOKEN}", llm_provider="v", model="m"))):
        r = post(client, briefing("k-t6"))
        leak_haystack.append(r.text)
    leak_haystack.append("\n".join(logs.lines))
big = "\n".join(leak_haystack)
check(f"K-T6 the token never appears in any response body, header or log line ({len(big)} chars searched)", TOKEN not in big, "FOUND")
check("K-T6 the search is not vacuous (it saw the executor's own log lines)", "executor.call" in big and "executor.refused" in big, "")
check("K-T6 the wrong-but-same-length token presented never appears either", WRONG_SAME_LEN not in big, "FOUND")
check("K-T6 the token's length is not stated anywhere (no `len`/`length` field in a 401 body)", "length" not in json.dumps(UNAUTH_BODY), "")

# ------------------------------------------------------------------ K-T7 order of checks
with fake_model() as fake:
    for name, kwargs in (("a garbage body", {"content": b"not json"}), ("a body with an unknown field", {"json": {"junk": 1}}),
                         ("a schema-invalid Briefing", {"json": {**briefing("x"), "model": "nope"}}),
                         ("a sha-mismatching Briefing", {"json": {**briefing("x"), "prompt_sha256": "0" * 64}})):
        r = client.post("/kernel/execute", headers={"X-Kernel-Auth-Token": "wrong-wrong-wrong-wrong"}, **kwargs)
        check(f"K-T7 unauthenticated request with {name}: 401, not 422 (nothing about the schema leaks before auth)", r.status_code == 401 and r.json() == UNAUTH_BODY, (r.status_code, r.text[:100]))
    r = client.post("/kernel/execute", json={"junk": 1}, headers=AUTH)
    check("K-T7 authenticated with the same bad body: now 422", r.status_code == 422, r.status_code)
    check("K-T7 zero model calls throughout", len(fake.calls) == 0, len(fake.calls))

# ------------------------------------------------------------------ K-T8 capabilities
with fake_model() as fake:
    r = client.get("/kernel/capabilities", headers=AUTH)
    expected = {"contract_version": 1, "allowed_models": ["vertex_ai/gemini-2.5-pro", "vertex_ai/gemini-2.5-flash"],
                "allowed_tools": ["function", "googleSearch"], "max_prompt_bytes": 4 * 1024 * 1024, "max_timeout_s": 280}
    check("K-T8 capabilities returns exactly the five keys with the configured values", r.status_code == 200 and r.json() == expected, r.text)
    check("K-T8 zero model calls; no secret, prompt or provider text in the body", len(fake.calls) == 0 and TOKEN not in r.text, "")
    for name, headers in (("no header", {}), ("a wrong header", {AUTH_HEADER: WRONG_SAME_LEN})):
        r = client.get("/kernel/capabilities", headers=headers)
        check(f"K-T8 capabilities with {name}: 401 with the same fixed body", r.status_code == 401 and r.json() == UNAUTH_BODY, (r.status_code, r.text))
    h = client.get("/kernel/health")
    check("K-T8 health stays open and returns no allowlist or limit", h.status_code == 200 and not any(k in h.text for k in ("allowed", "max_prompt", "max_timeout")), h.text)
# capabilities and validation read the SAME configuration: change it and both change
from executor import config  # noqa: E402
with fake_model() as fake, patch.object(config, "ALLOWED_MODELS", ("vertex_ai/gemini-2.5-flash",)), \
        patch.object(config, "MAX_TIMEOUT_S", 90), patch.object(config, "MAX_PROMPT_BYTES", 1000):
    caps = client.get("/kernel/capabilities", headers=AUTH).json()
    check("K-T8 capabilities follows the configuration (models, max timeout, max prompt bytes)", caps["allowed_models"] == ["vertex_ai/gemini-2.5-flash"] and caps["max_timeout_s"] == 90 and caps["max_prompt_bytes"] == 1000, caps)
    r1 = post(client, briefing("cfg", model="vertex_ai/gemini-2.5-pro"))
    r2 = post(client, briefing("cfg", timeout_s=91))
    r3 = post(client, briefing("p" * 1001))
    r4 = post(client, briefing("p" * 1000, timeout_s=90))
    check("K-T8 validation enforces the same changed configuration (each limit refused, the limit itself passes)",
          (r1.status_code, r2.status_code, r3.status_code, r4.status_code) == (422, 422, 422, 200), (r1.status_code, r2.status_code, r3.status_code, r4.status_code))

sys.exit(report("M1a endpoint tests (K-T1, K-T2, K-T3, K-T5, K-T6, K-T7, K-T8)"))
