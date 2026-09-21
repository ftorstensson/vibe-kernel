"""
Step 0 golden runner.

  python3 tests/step0_capture/run_goldens.py --record   write goldens from the CURRENT code
  python3 tests/step0_capture/run_goldens.py            compare current code against the goldens
  python3 tests/step0_capture/run_goldens.py --only pm.run_turn   filter scenarios by substring

Each scenario is also run twice and the two runs are compared with each other
first, so a nondeterministic input (a stray uuid/time/set ordering) is caught
here rather than showing up as a fake regression later.
"""
import asyncio
import difflib
import io
import json
import os
import sys
import traceback
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import recording, detect_site, ALL_SITES, dumps  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "goldens")


def golden_path(name):
    return os.path.join(GOLDEN_DIR, name.replace("/", "__") + ".json")


def run_once(scenario):
    buf = io.StringIO()
    with recording(scenario["responses"]) as rec:
        with redirect_stdout(buf):
            asyncio.run(scenario["run"]())
    return rec.requests, buf.getvalue()


def canonical(requests, order_insensitive):
    if not order_insensitive:
        return requests
    return sorted(requests, key=lambda r: json.dumps(r, sort_keys=True))


def show_diff(want, got):
    a, b = dumps(want).splitlines(), dumps(got).splitlines()
    diff = list(difflib.unified_diff(a, b, "golden", "current", lineterm="", n=2))
    return "\n".join(diff[:40])


def main():
    record = "--record" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    os.makedirs(GOLDEN_DIR, exist_ok=True)

    checks = []
    sites_seen = set()
    for scenario in SCENARIOS:
        name = scenario["name"]
        if only and only not in name:
            continue
        try:
            first, _ = run_once(scenario)
            second, _ = run_once(scenario)
        except Exception:
            checks.append((f"{name}: scenario runs without error", False, traceback.format_exc(limit=6)))
            continue
        oi = scenario["order_insensitive"]
        first, second = canonical(first, oi), canonical(second, oi)
        checks.append((f"{name}: deterministic across two runs ({len(first)} requests)", first == second, show_diff(first, second)))
        checks.append((f"{name}: records at least one request", len(first) > 0, "no model call recorded"))
        for r in first:
            sites_seen.add(detect_site(r))
        path = golden_path(name)
        payload = {"scenario": name, "order_insensitive": oi, "request_count": len(first), "requests": first}
        if record:
            with open(path, "w") as f:
                f.write(dumps(payload))
            checks.append((f"{name}: golden written", True, ""))
        else:
            if not os.path.exists(path):
                checks.append((f"{name}: golden exists", False, path))
                continue
            with open(path) as f:
                want = json.load(f)
            checks.append((f"{name}: request count matches golden ({want['request_count']})", want["request_count"] == len(first), f"got {len(first)}"))
            checks.append((f"{name}: requests byte-identical to golden (order-sensitive)", dumps(want["requests"]) == dumps(json.loads(json.dumps(first))), show_diff(want["requests"], first)))

    if not only:
        missing = [s for s in ALL_SITES if s not in sites_seen]
        checks.append((f"coverage: all {len(ALL_SITES)} call sites exercised by at least one scenario", not missing, f"missing: {missing}"))
        checks.append(("coverage: no recorded request is an unrecognized site", "unknown" not in sites_seen, "an unidentified prompt was recorded"))

    all_pass = True
    for name, ok, detail in checks:
        if not ok:
            all_pass = False
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n{detail}" if not ok and detail else ""))
    print(f"\n{len(checks)} checks, {'ALL PASS' if all_pass else 'SOME FAILED'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
