"""
K-T4 (K1 section 9.2): the nine old Kernel turn routes answer HTTP 410. This suite exists
ONLY on the m1-cutover-410 branch; it ships in the Kernel deploy that goes with the M1b
cutover, never with the executor.

Run: python3 tests/m1_executor/test_cutover.py
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "step0_capture"))
from common import AUTH, TOKEN, FakeModel, briefing, check, fake_model, fake_response, make_client, report  # noqa: E402
from endpoint_payloads import ENDPOINTS  # noqa: E402
import litellm  # noqa: E402

client = make_client()

# The nine "old turn routes" of K1 R4, written out independently of executor/cutover.py.
NINE = [
    "/kernel/invoke", "/kernel/agents/run_turn", "/kernel/agents/run_global_turn", "/kernel/agents/run_global_turn_answer",
    "/kernel/synthesize_dispatch", "/kernel/chat_summary", "/kernel/functions/assess_coverage",
    "/kernel/functions/confirm_launch_intent", "/kernel/functions/launch_strike_team",
]
NOT_TURN_ROUTES = ["/kernel/functions/derive_requirements", "/kernel/compile_identity", "/kernel/summarize_for_map",
                   "/kernel/agents/preview", "/kernel/functions/preview"]

from executor import cutover  # noqa: E402
check("K-T4 the cutover router carries exactly the nine routes of K1 R4", sorted(cutover.GONE_ROUTES) == sorted(NINE), sorted(cutover.GONE_ROUTES))
check("K-T4 the five Publish-time routes are NOT in the cutover", not set(NOT_TURN_ROUTES) & set(cutover.GONE_ROUTES), "")

model_calls = []


def boom(*a, **k):
    model_calls.append(1)
    raise AssertionError("a model call was made from a 410 route")


bodies = set()
with patch.object(litellm, "completion", boom), patch.object(litellm, "acompletion", boom):
    for path in NINE:
        legacy_payload = ENDPOINTS[path]
        attempts = [
            ("a valid legacy payload", dict(json=legacy_payload)),
            ("the payload with include_briefing and the capture header", dict(json={**legacy_payload, "include_briefing": True}, headers={"X-Kernel-Capture-Token": TOKEN})),
            ("garbage bytes", dict(content=b"not json at all", headers={"content-type": "application/json"})),
            ("an empty body", dict()),
            ("an authenticated executor token", dict(json=legacy_payload, headers=AUTH)),
            ("a body that would fail the old validation", dict(json={"nonsense": True})),
        ]
        for name, kw in attempts:
            r = client.post(path, **kw)
            bodies.add(r.text)
            check(f"K-T4 POST {path} ({name}): 410 with the fixed body", r.status_code == 410 and r.json() == cutover.GONE_BODY and r.headers["content-type"].startswith("application/json"), (r.status_code, r.text[:120]))
        for method in ("GET", "PUT", "PATCH", "DELETE"):
            r = client.request(method, path)
            check(f"K-T4 {method} {path}: 410 too", r.status_code == 410 and r.json() == cutover.GONE_BODY, (r.status_code, r.text[:80]))
check("K-T4 every 410 response body is byte-identical (one fixed body, nothing request-dependent)", len(bodies) == 1, len(bodies))
check("K-T4 zero model calls from any 410 route (litellm.completion and acompletion were rigged to fail)", model_calls == [], len(model_calls))
check("K-T4 no Firestore client was ever imported", "google.cloud.firestore" not in sys.modules and "google.cloud.firestore_v1" not in sys.modules, "")
check("K-T4 the body names the replacement and never a request value", cutover.GONE_BODY["error"]["replacement"] == "/kernel/execute" and cutover.GONE_BODY["error"]["type"] == "gone", cutover.GONE_BODY)

# the other routes are untouched
fake_completion = lambda **kw: fake_response('{"items": [], "questions": [], "confirmed": false, "mapped": ""}')  # noqa: E731
from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
tolerant = TestClient(main.app, raise_server_exceptions=False)   # a fake reply may not satisfy a legacy response model; only "not 410" matters here
with patch.object(litellm, "completion", fake_completion):
    for path in ("/kernel/functions/derive_requirements", "/kernel/summarize_for_map"):
        r = tolerant.post(path, json=ENDPOINTS[path])
        check(f"K-T4 {path} (a Publish-time route) is NOT gone: status {r.status_code}, not 410", r.status_code != 410, (r.status_code, r.text[:100]))
for path in ("/kernel/compile_identity", "/kernel/agents/preview", "/kernel/functions/preview"):
    r = tolerant.post(path, json={})
    check(f"K-T4 {path} (a Publish-time route) is NOT gone: status {r.status_code}, not 410", r.status_code != 410, (r.status_code, r.text[:100]))

# the executor is unaffected
with fake_model() as fake:
    r = client.post("/kernel/execute", json=briefing("after the cutover"), headers=AUTH)
    check("K-T4 POST /kernel/execute still works after the cutover", r.status_code == 200 and r.json()["status"] == "ok" and len(fake.calls) == 1, (r.status_code, r.text[:100]))
    check("K-T4 POST /kernel/execute without the token is still 401", client.post("/kernel/execute", json=briefing("x")).status_code == 401, "")
    check("K-T4 /kernel/health and /kernel/capabilities are unaffected", client.get("/kernel/health").status_code == 200 and client.get("/kernel/capabilities", headers=AUTH).status_code == 200, "")
check("K-T4 the docs and OpenAPI document are still served", client.get("/openapi.json").status_code == 200 and client.get("/docs").status_code == 200, "")
schema_paths = set(client.get("/openapi.json").json()["paths"])
check("K-T4 the OpenAPI document lists the executor routes", {"/kernel/execute", "/kernel/health", "/kernel/capabilities"} <= schema_paths, sorted(schema_paths))

sys.exit(report("K-T4 the nine old turn routes answer 410"))
