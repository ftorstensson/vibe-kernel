"""
M1a measurement M1 (docs/m0/C1 section 4.3): how often does structured output
(response_format) come back fenced or with text around it, i.e. how often does
json_strict fail where json_lenient would have succeeded?

For every call label that sends response_format, the distinct real requests
recorded in the golden baseline (tests/step0_capture/goldens, 57 scenarios, which
include the replayed Phase 1.5 real-turn fixtures) become Briefings with
parse_mode=json_strict, and N runs per label (default 20) are sent to a RUNNING
executor with the REAL model, round-robin over that label's distinct requests.
Prompts are today's legacy prompts (Backend's six-layer builder does not exist yet).

Counted per label: strict OK; strict failed but lenient succeeded (fenced block,
text before, text after, other); both failed; and strict OK where the legacy lenient
parse would have returned a DIFFERENT value (a top-level list).

The token comes from KERNEL_AUTH_TOKEN and is never printed. Usage:
    KERNEL_AUTH_TOKEN=... python3 tests/m1_executor/measure_parse_modes.py --url http://127.0.0.1:8891 [--n 20] [--cost-cap 1.0]
"""
import argparse
import asyncio
import collections
import glob
import json
import os
import sys

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tests", "step0_capture"))
sys.path.insert(0, ROOT)
from common import briefing  # noqa: E402
from harness import detect_site  # noqa: E402
from executor.parse import parse_json_lenient  # noqa: E402
import litellm  # noqa: E402


def load_labels():
    labels = collections.OrderedDict()
    for f in sorted(glob.glob(os.path.join(ROOT, "tests", "step0_capture", "goldens", "*.json"))):
        for r in json.load(open(f))["requests"]:
            if "response_format" not in r or r.get("tools"):
                continue
            key = json.dumps([r["messages"][0]["content"], r["response_format"]], sort_keys=True)
            labels.setdefault(detect_site(r), collections.OrderedDict())[key] = r
    return labels


def classify_failure(text):
    stripped = text.strip()
    if stripped.startswith("```"):
        return "fenced block"
    if stripped[:1] in ("{", "["):
        return "text after"
    if "{" in stripped or "[" in stripped:
        return "text before"
    return "other"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--cost-cap", type=float, default=1.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    token = os.environ.get("KERNEL_AUTH_TOKEN", "")
    if not token:
        print("KERNEL_AUTH_TOKEN is not set")
        return 2
    labels = load_labels()
    stats = collections.OrderedDict()
    raw = []
    spent = 0.0
    sem = asyncio.Semaphore(6)

    async with httpx.AsyncClient(base_url=args.url, timeout=300) as client:
        async def one(label, i, r):
            nonlocal spent
            if spent > args.cost_cap:
                return
            body = briefing(r["messages"][0]["content"], attempt_id=f"m1-{label}-{i}"[:128], call_label=label,
                            model=r["model"], temperature=r.get("temperature"), reasoning_effort=r.get("reasoning_effort"),
                            response_format=r["response_format"], parse_mode="json_strict", timeout_s=120)
            async with sem:
                resp = await client.post("/kernel/execute", json=body, headers={"X-Kernel-Auth-Token": token})
            s = stats[label]
            s["runs"] += 1
            if resp.status_code != 200 or resp.json().get("status") != "ok":
                s["call_failed"] += 1
                return
            j = resp.json()
            out, usage = j["output"], j.get("usage") or {}
            try:
                p, c = litellm.cost_per_token(model=r["model"].split("/", 1)[1], custom_llm_provider="vertex_ai", prompt_tokens=usage.get("prompt_tokens") or 0, completion_tokens=usage.get("completion_tokens") or 0)
                spent += p + c
                s["cost"] += p + c
            except Exception:
                pass
            if j.get("finish_reason") not in ("stop", None):
                s["finish_" + str(j["finish_reason"])] += 1
            if out["parse_error"] is None:
                s["strict_ok"] += 1
                try:
                    if parse_json_lenient(out["text"]) != out["parsed"]:
                        s["strict_ok_but_lenient_value_differs"] += 1
                except Exception:
                    pass
            else:
                try:
                    parse_json_lenient(out["text"])
                    s["strict_failed_lenient_ok: " + classify_failure(out["text"])] += 1
                    raw.append({"label": label, "text": out["text"][:400]})
                except Exception:
                    s["both_failed"] += 1
                    raw.append({"label": label, "text": out["text"][:400], "both_failed": True})

        tasks = []
        for label, distinct in labels.items():
            stats[label] = collections.Counter()
            stats[label]["distinct_prompts"] = len(distinct)
            reqs = list(distinct.values())
            for i in range(args.n):
                tasks.append(one(label, i, reqs[i % len(reqs)]))
        await asyncio.gather(*tasks)

    print(f"{'label':34s} {'runs':>4s} {'strict ok':>9s}  failures")
    total_runs = total_ok = 0
    for label, s in stats.items():
        fails = {k: v for k, v in s.items() if k.startswith(("strict_failed", "both_failed", "call_failed", "finish_", "strict_ok_but"))}
        print(f"{label:34s} {s['runs']:4d} {s['strict_ok']:9d}  distinct prompts {s['distinct_prompts']}  {fails or 'none'}  cost ${s['cost']:.4f}")
        total_runs += s["runs"]
        total_ok += s["strict_ok"]
    print(f"\nTOTAL {total_runs} runs, strict OK {total_ok}, estimated cost ${spent:.4f}")
    if raw:
        print("\nreplies where strict failed (first 400 chars):")
        for r in raw[:12]:
            print(" -", r["label"], repr(r["text"][:200]))
    if args.out:
        json.dump({"stats": {k: dict(v) for k, v in stats.items()}, "raw": raw}, open(args.out, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
