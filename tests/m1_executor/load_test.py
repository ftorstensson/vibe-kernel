"""
The M1a load test against a RUNNING executor with the REAL model (docs/m0/K1 section 5).

Pass rule (PM decision 2026-09-21): 6 concurrent Briefings finish in at most 1.5x the
slowest single call, where "slowest single call" is the slowest of the same six
Briefings run one after another on the same instance immediately beforehand.

The token comes from the KERNEL_AUTH_TOKEN environment variable and is never printed.
Usage:
    KERNEL_AUTH_TOKEN=... python3 tests/m1_executor/load_test.py --url http://127.0.0.1:8891 [--hound] [--rounds 3]
--hound uses the Hound shape (Flash, 0.1, googleSearch grounding); the default is plain Flash.
"""
import argparse
import asyncio
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import briefing  # noqa: E402  (its hashing is an independent copy of the C1 5.2 rule)

TOPICS = ["how bees communicate", "why the sky is blue", "how a refrigerator works", "the history of the bicycle",
          "how vaccines train the immune system", "why tides happen"]


def make(i, hound):
    prompt = f"Write about 150 words on {TOPICS[i]}. Plain prose, no headings."
    fields = dict(model="vertex_ai/gemini-2.5-flash", temperature=0.1, reasoning_effort=None if hound else "disable",
                  tools=[{"googleSearch": {}}] if hound else None, timeout_s=120, parse_mode="text")
    return briefing(prompt, attempt_id=f"load-{i}", call_label="load.test", **fields)


async def call(client, body, token):
    t0 = time.perf_counter()
    r = await client.post("/kernel/execute", json=body, headers={"X-Kernel-Auth-Token": token})
    wall = time.perf_counter() - t0
    j = r.json() if r.status_code == 200 else {}
    return wall, r.status_code, j.get("status"), (j.get("timing") or {}).get("duration_ms"), (j.get("error") or {}).get("type")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--hound", action="store_true")
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()
    token = os.environ.get("KERNEL_AUTH_TOKEN", "")
    if not token:
        print("KERNEL_AUTH_TOKEN is not set")
        return 2
    bodies = [make(i, args.hound) for i in range(6)]
    all_ok = True
    async with httpx.AsyncClient(base_url=args.url, timeout=300) as client:
        for rnd in range(1, args.rounds + 1):
            singles = [await call(client, b, token) for b in bodies]      # one after another
            slowest = max(s[0] for s in singles)
            t0 = time.perf_counter()
            conc = await asyncio.gather(*[call(client, b, token) for b in bodies])
            total = time.perf_counter() - t0
            ok = all(s[1] == 200 and s[2] == "ok" for s in singles + list(conc))
            ratio = total / slowest
            passed = ok and ratio <= 1.5
            all_ok &= passed
            print(f"round {rnd}: singles wall (s) {[round(s[0], 2) for s in singles]}  slowest {slowest:.2f}  server-side model-call ms {[s[3] for s in singles]}")
            print(f"         concurrent wall (s) {[round(c[0], 2) for c in conc]}  total {total:.2f}  ratio {ratio:.2f}  "
                  f"server-side ms {[c[3] for c in conc]}  all 200/ok: {ok}  -> {'PASS' if passed else 'FAIL'} (limit 1.5)")
            if not ok:
                print("         non-ok:", [(c[1], c[2], c[4]) for c in singles + list(conc) if not (c[1] == 200 and c[2] == 'ok')])
    print("LOAD TEST", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
