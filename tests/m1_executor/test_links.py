"""
Grounding-link resolution (executor/links.py, docs/m0 C1 section 4.1): the Hound's Google
redirect links are resolved to the real page address inside the call.

NO test here touches the real network: every request goes to an httpx.MockTransport (the
resolver's test hook `links._transport`, installed by common.fake_model for the endpoint tests
and by `net()` below for the direct ones). A live example is a separate, manual step.

Run: python3 tests/m1_executor/test_links.py
"""
import asyncio
import os
import sys
import time
from contextlib import contextmanager
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (AUTH, FakeModel, briefing, catch_logs, check, fake_model, fake_response,  # noqa: E402
                    make_client, post, report)
import httpx  # noqa: E402
from executor import links  # noqa: E402

GR = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"
REAL = "https://www.example.org/a%20b?x=1&y=%E2%9C%93#frag"


def src(name, tail="AAA"):
    return links.source(name, GR + tail)


@contextmanager
def net(handler):
    """Direct-resolver tests: the resolver's network is a MockTransport around `handler`, and every
    requested URL is recorded in the returned list."""
    seen = []

    async def wrapped(request):
        seen.append((request.method, str(request.url), dict(request.headers), request.content))
        out = handler(request)
        if hasattr(out, "__await__"):
            out = await out
        return out

    with patch.object(links, "_transport", httpx.MockTransport(wrapped)):
        yield seen


def redirect(location, status=302):
    return lambda request: httpx.Response(status, headers={"location": location})


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ the happy path and its exact shape
with net(redirect(REAL)) as seen:
    original = [src("example.org")]
    snapshot = [dict(s) for s in original]
    out = run(links.resolve_sources(original))
check("L1 a Google redirect resolves: url = the Location exactly as sent, redirect_url = the original, resolved true, title kept",
      out == [{"title": "example.org", "url": REAL, "redirect_url": GR + "AAA", "resolved": True}], out)
check("L1 the input list is not mutated", original == snapshot, original)
check("L1 exactly one request, a GET to the redirect URL, and it was NOT followed (no second request for the target)",
      len(seen) == 1 and seen[0][0] == "GET" and seen[0][1] == GR + "AAA", seen)
headers = {k.lower() for k in seen[0][2]}
check("L1 the request carries no credentials: no Authorization, Cookie or Kernel token header", not ({"authorization", "cookie", "x-kernel-auth-token"} & headers), headers)
check("L1 the request carries no body", seen[0][3] == b"", seen[0][3])

for status in (301, 302, 303, 307, 308):
    with net(redirect("https://ok.example/p", status)):
        out = run(links.resolve_sources([src("t")]))
    check(f"L2 a {status} redirect resolves", out[0]["resolved"] is True and out[0]["url"] == "https://ok.example/p", out)

for label, resp in (("200 OK", httpx.Response(200, text="<html>js redirect</html>")), ("404", httpx.Response(404)), ("500", httpx.Response(500)),
                    ("304 Not Modified with a Location", httpx.Response(304, headers={"location": "https://x.example/"})),
                    ("302 with no Location", httpx.Response(302)), ("302 with an empty Location", httpx.Response(302, headers={"location": ""}))):
    with net(lambda request, resp=resp: resp):
        out = run(links.resolve_sources([src("t")]))
    check(f"L3 {label}: unresolved, the source keeps its redirect", out == [{"title": "t", "url": GR + "AAA", "redirect_url": GR + "AAA", "resolved": False}], out)

BAD_LOCATIONS = {
    "javascript: scheme": "javascript:alert(1)", "data: scheme": "data:text/html,<b>x</b>", "ftp scheme": "ftp://x.example/f",
    "file scheme": "file:///etc/passwd", "relative path": "/some/page", "relative without slash": "page.html", "scheme-relative": "//x.example/p",
    "whitespace inside": "https://x.example/a b", "tab inside": "https://x.example/a\tb", "no host": "https://", "over 8192 characters": "https://x.example/" + "a" * 9000,
    "another Google redirect": GR + "BBB", "any path on Google's redirect host": "https://vertexaisearch.cloud.google.com/other",
}
for label, location in BAD_LOCATIONS.items():
    with net(redirect(location)):
        out = run(links.resolve_sources([src("t")]))
    check(f"L4 Location is {label}: unresolved", out[0]["resolved"] is False and out[0]["url"] == GR + "AAA", out)
with net(redirect("  https://padded.example/p  ")):
    out = run(links.resolve_sources([src("t")]))
check("L4 a Location padded with spaces is trimmed and accepted", out[0]["resolved"] is True and out[0]["url"] == "https://padded.example/p", out)
with net(redirect("HTTP://Mixed.Example/Path?Q=1")):
    out = run(links.resolve_sources([src("t")]))
check("L4 an http (not only https) page is accepted, returned as sent", out[0]["resolved"] is True and out[0]["url"] == "HTTP://Mixed.Example/Path?Q=1", out)

# ------------------------------------------------------------------ only Google's grounding redirect is ever requested
NOT_FETCHED = {
    "a normal page": "https://example.com/x", "http, not https": "http://vertexaisearch.cloud.google.com/grounding-api-redirect/x",
    "a look-alike subdomain": "https://vertexaisearch.cloud.google.com.evil.example/grounding-api-redirect/x",
    "the redirect URL inside a query": "https://evil.example/?u=https://vertexaisearch.cloud.google.com/grounding-api-redirect/x",
    "userinfo trick (the host is really evil.example)": "https://vertexaisearch.cloud.google.com@evil.example/grounding-api-redirect/x",
    "credentials on the real host (would be sent as Basic auth)": "https://user:pass@vertexaisearch.cloud.google.com/grounding-api-redirect/x",
    "a username alone on the real host": "https://user@vertexaisearch.cloud.google.com/grounding-api-redirect/x",
    "another port": "https://vertexaisearch.cloud.google.com:8443/grounding-api-redirect/x", "another path": "https://vertexaisearch.cloud.google.com/other/x",
    "no trailing slash": "https://vertexaisearch.cloud.google.com/grounding-api-redirect", "path traversal": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/../admin",
    "a sibling Google host": "https://www.google.com/grounding-api-redirect/x", "None": None, "empty string": "", "a number": 5,
}
for label, url in NOT_FETCHED.items():
    with net(redirect("https://leak.example/")) as seen:
        out = run(links.resolve_sources([{"title": "t", "url": url, "redirect_url": url, "resolved": False}]))
    check(f"L5 {label}: no request is made and the source is returned unchanged", seen == [] and out == [{"title": "t", "url": url, "redirect_url": url, "resolved": False}], (seen, out))
check("L5 is_google_redirect accepts the real shape, including an upper-case scheme and host", links.is_google_redirect(GR + "x") and links.is_google_redirect("HTTPS://VERTEXAISEARCH.CLOUD.GOOGLE.COM/grounding-api-redirect/x"), "")
check("L5 is_google_redirect accepts the explicit default port 443", links.is_google_redirect("https://vertexaisearch.cloud.google.com:443/grounding-api-redirect/x"), "")

# ------------------------------------------------------------------ parallel, bounded, never raising
async def slow_then(seconds, location):
    await asyncio.sleep(seconds)
    return httpx.Response(302, headers={"location": location})


with net(lambda request: slow_then(1.0, "https://p.example/" + request.url.path.rsplit("/", 1)[1])) as seen:
    t0 = time.perf_counter()
    out = run(links.resolve_sources([src(f"s{i}", f"P{i}") for i in range(6)]))
    took = time.perf_counter() - t0
check("L6 six sources of 1 s each resolve in parallel: about 1 s in total, not 6 s", took < 1.8 and all(s["resolved"] for s in out), took)
check("L6 each source got its own answer, in the original order", [s["url"] for s in out] == [f"https://p.example/P{i}" for i in range(6)], [s["url"] for s in out])

def mixed(request):
    tail = request.url.path.rsplit("/", 1)[1]
    if tail == "SLOW":
        return slow_then(30, "https://never.example/")
    return httpx.Response(302, headers={"location": "https://fast.example/" + tail})


with net(mixed):
    t0 = time.perf_counter()
    out = run(links.resolve_sources([src("a", "ONE"), src("b", "SLOW"), src("c", "TWO")]))
    took = time.perf_counter() - t0
check("L7 one source that never answers is cut at 3 s; the others are resolved and unaffected",
      [s["resolved"] for s in out] == [True, False, True] and out[1]["url"] == GR + "SLOW" and 2.7 < took < 3.8, (took, out))
check("L7 the per-source timeout is 3 s and the total cap 5 s", links.PER_SOURCE_TIMEOUT_S == 3.0 and links.TOTAL_TIMEOUT_S == 5.0, "")

with patch.object(links, "PER_SOURCE_TIMEOUT_S", 30.0), patch.object(links, "TOTAL_TIMEOUT_S", 0.6), net(mixed):
    t0 = time.perf_counter()
    out = run(links.resolve_sources([src("a", "ONE"), src("b", "SLOW"), src("c", "TWO")]))
    took = time.perf_counter() - t0
check("L8 the total cap cuts what is still waiting (0.6 s here) and keeps what already answered", [s["resolved"] for s in out] == [True, False, True] and 0.5 < took < 1.3, (took, out))

async def leak_check():
    with patch.object(links, "PER_SOURCE_TIMEOUT_S", 30.0), patch.object(links, "TOTAL_TIMEOUT_S", 0.3), net(mixed):
        await links.resolve_sources([src("b", "SLOW"), src("b2", "SLOW2")])
    return [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]


check("L8 no task outlives the call after the total cap", run(leak_check()) == [], "")

for label, boom in (("a connection error", httpx.ConnectError("no route")), ("a read timeout", httpx.ReadTimeout("slow")),
                    ("a TLS error", httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]")), ("an unexpected RuntimeError", RuntimeError("boom"))):
    def raiser(request, boom=boom):
        raise boom
    with net(raiser):
        out = run(links.resolve_sources([src("t")]))
    check(f"L9 {label}: never raised, the source keeps its redirect", out == [{"title": "t", "url": GR + "AAA", "redirect_url": GR + "AAA", "resolved": False}], out)

with patch.object(links, "_transport", object()):     # an unusable transport fails while the client is being built, before any lookup
    original = [src("t")]
    out = run(links.resolve_sources(original))
check("L9 even a failure before any lookup is swallowed: never raised, the sources come back unchanged", out == [src("t")] and out is not original, out)

async def cancelled():
    with net(lambda request: slow_then(30, "https://never.example/")):
        task = asyncio.ensure_future(links.resolve_sources([src("a", "X1"), src("b", "X2")]))
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
            raised = False
        except asyncio.CancelledError:
            raised = True
        await asyncio.sleep(0.05)
        return raised, [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]


raised, leftover = run(cancelled())
check("L10 cancelling the request cancels the lookups: CancelledError propagates and nothing is left running", raised and leftover == [], (raised, leftover))

with net(redirect(REAL)) as seen:
    out = run(links.resolve_sources([src("a", "DUP"), src("b", "DUP"), src("c", "OTHER")]))
check("L11 two sources with the same redirect cause one request, and both are resolved", len(seen) == 2 and [s["resolved"] for s in out] == [True, True, True], (len(seen), out))

with net(redirect(REAL)) as seen:
    out = run(links.resolve_sources([src(f"s{i}", f"M{i}") for i in range(35)]))
check("L12 at most 30 distinct redirects are requested; the 5 beyond the cap stay unresolved (no error)",
      len(seen) == 30 and sum(1 for s in out if s["resolved"]) == 30 and [s["resolved"] for s in out[30:]] == [False] * 5, (len(seen), out[30:]))

with net(redirect(REAL)) as seen:
    mixed_in = [links.source("plain", "https://direct.example/p"), src("g", "G1"), links.source("noUrl", None), src("g2", "G2")]
    out = run(links.resolve_sources(mixed_in))
check("L13 a mixed list keeps its order and shape: only the Google redirects are resolved",
      [s["title"] for s in out] == ["plain", "g", "noUrl", "g2"] and [s["resolved"] for s in out] == [False, True, False, True]
      and out[0]["url"] == "https://direct.example/p" and out[2]["url"] is None and len(seen) == 2, out)
with net(redirect(REAL)) as seen:
    out = run(links.resolve_sources([]))
check("L13 an empty list makes no request and returns an empty list", out == [] and seen == [], out)
check("L13 summary() returns counts only", links.summary([{"resolved": True}, {"resolved": False}, {}]) == (1, 3), "")

# ------------------------------------------------------------------ through the endpoint
client = make_client()
G_ANN = [{"type": "url_citation", "url_citation": {"title": "example.org", "url": GR + "ONE"}},
         {"type": "url_citation", "url_citation": {"title": "other.example", "url": GR + "TWO"}},
         {"type": "url_citation", "url_citation": {"url": "https://direct.example/x"}}]
HOUND = dict(model="vertex_ai/gemini-2.5-flash", temperature=0.1, reasoning_effort=None, tools=[{"googleSearch": {}}], timeout_s=150)

model = FakeModel(fake_response("Findings with sources.", annotations=G_ANN, usage=(40, 12, 0)))
with fake_model(model) as fake:
    fake.redirects = {GR + "ONE": "https://www.example.org/real-page", GR + "TWO": "https://other.example/article?id=7"}
    with catch_logs() as logs:
        r = post(client, briefing("Hound question", attempt_id="att-h", **HOUND))
    body = r.json()
sources = body["output"]["grounding_sources"]
check("L14 through /kernel/execute: each source is {title, url, redirect_url, resolved}, resolved where it could be, in order",
      r.status_code == 200 and body["status"] == "ok" and sources == [
          {"title": "example.org", "url": "https://www.example.org/real-page", "redirect_url": GR + "ONE", "resolved": True},
          {"title": "other.example", "url": "https://other.example/article?id=7", "redirect_url": GR + "TWO", "resolved": True},
          {"title": "Source", "url": "https://direct.example/x", "redirect_url": "https://direct.example/x", "resolved": False}], sources)
check("L14 no model call is added by resolution: exactly one", len(fake.calls) == 1, len(fake.calls))
check("L14 only the two Google redirects were requested; the direct URL never was", sorted(fake.fetches) == sorted([GR + "ONE", GR + "TWO"]), fake.fetches)
check("L14 nothing else in the response changed: same keys, text, usage, finish_reason, shas, echo",
      set(body) == {"contract_version", "attempt_id", "call_label", "status", "prompt_sha256", "prompt_utf8_bytes", "prompt_utf16_units", "request_sha256", "output", "usage", "finish_reason", "effective_model", "error", "timing", "kernel", "segments"}
      and set(body["output"]) == {"text", "tool_calls", "grounding_sources", "parsed", "parse_error"} and body["output"]["text"] == "Findings with sources."
      and body["usage"] == {"prompt_tokens": 40, "completion_tokens": 12, "reasoning_tokens": 0} and body["finish_reason"] == "stop" and body["attempt_id"] == "att-h", body)
log_text = "\n".join(logs.lines)
check("L14 the log line records the counts (links_resolved=2/3) and no URL", "links_resolved=2/3" in log_text and "vertexaisearch" not in log_text and "example.org" not in log_text, [l for l in logs.lines if "executor.call" in l])

model = FakeModel(fake_response("ok", annotations=G_ANN))
with fake_model(model) as fake:   # the network answers 404 for everything: resolution fails, the call does not
    r = post(client, briefing("q", **HOUND))
    body = r.json()
check("L15 when every lookup fails the call is still a success with the same text; sources keep their redirects",
      r.status_code == 200 and body["status"] == "ok" and body["output"]["text"] == "ok" and [s["resolved"] for s in body["output"]["grounding_sources"]] == [False, False, False]
      and body["output"]["grounding_sources"][0]["url"] == GR + "ONE" and body["error"] is None, body["output"]["grounding_sources"])

def explode(request):
    raise RuntimeError("network exploded")


model = FakeModel(fake_response("ok", annotations=G_ANN))
with fake_model(model) as fake:
    fake.net_handler = explode
    r = post(client, briefing("q", **HOUND))
check("L15 a transport that raises still leaves a successful call (no 500, no provider_error)", r.status_code == 200 and r.json()["status"] == "ok" and r.json()["error"] is None, r.text[:200])

model = FakeModel(fake_response("slow links", annotations=[G_ANN[0]]))
with fake_model(model) as fake:
    async def one_second(request):
        await asyncio.sleep(1.0)
        return httpx.Response(302, headers={"location": "https://late.example/p"})
    fake.net_handler = one_second
    t0 = time.perf_counter()
    r = post(client, briefing("q", **HOUND))
    wall = time.perf_counter() - t0
    body = r.json()
check("L16 resolution time is not in timing.duration_ms (the model call only): the request took >= 1 s, duration_ms is far smaller",
      body["output"]["grounding_sources"][0]["resolved"] is True and wall >= 0.95 and body["timing"]["duration_ms"] < 500, (wall, body["timing"]))

model = FakeModel(fake_response("no sources"))
with fake_model(model) as fake:
    r = post(client, briefing("q", **HOUND))
check("L17 a call with no grounding sources makes no request at all", r.json()["output"]["grounding_sources"] == [] and fake.fetches == [], fake.fetches)

model = FakeModel(RuntimeError("provider down"))
with fake_model(model) as fake:
    r = post(client, briefing("q", **HOUND))
check("L17 a failed provider call returns no output and makes no request", r.json()["status"] == "error" and r.json()["output"] is None and fake.fetches == [], fake.fetches)

with fake_model(FakeModel(fake_response("x", annotations=[{"type": "url_citation", "url_citation": {"title": "T", "url": GR + "ONE"}}]))) as fake:
    fake.redirects = {GR + "ONE": "https://real.example/p"}
    first = post(client, briefing("same prompt", attempt_id="same", **HOUND)).json()
    again = post(client, briefing("same prompt", attempt_id="same", **HOUND)).json()
check("L18 the hashes are about the request, not the sources: prompt_sha256 and request_sha256 equal the Briefing's, and a repeat is identical",
      first["prompt_sha256"] == again["prompt_sha256"] and first["request_sha256"] == again["request_sha256"]
      and first["output"]["grounding_sources"] == again["output"]["grounding_sources"], "")
check("L18 the executor holds no state between calls: the repeat made its own lookup", len(fake.fetches) == 2, fake.fetches)

sys.exit(report("Grounding-link resolution (executor/links.py)"))
