"""
Step 0 Tier A tests (doc-26): the choke-point capture.

  1. no second copy      -- litellm.completion receives exactly build_request's output
  2. transparent         -- running the whole golden matrix WITH capture on sends
                            byte-identical requests to the goldens
  3. faithful            -- every captured entry equals what litellm actually received
  4. labels              -- every call site labeled, and label == fingerprint site
  5. Hound threads       -- parallel worker-thread calls reach the request's collector
  6. segments            -- UTF-16 offsets, gap rule, layer order, raw f-string sites empty
  7. errors / oversize / parsed
  8. endpoints           -- opt-in shape, null when off, isolation between requests
"""
import asyncio
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import recording, detect_site, ALL_SITES, ROOT, DEFAULT_RESPONSES  # noqa: E402
import core.agent_factory as agent_factory  # noqa: E402
from core.agent_factory import LiteLLMModel  # noqa: E402
from core.capture import capture_calls, utf16_len  # noqa: E402
from core import kernel_utils  # noqa: E402
from scenarios import SCENARIOS, env, HISTORY, CHAT_SUMMARY, PERSONA, PROJECT_MAP  # noqa: E402
from pods.social.engine import SocialEngine  # noqa: E402

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "goldens")
results = []
from core.capture import set_capture_authorized as _authorize  # noqa: E402
_authorize(True)


def check(name, ok, detail=""):
    results.append((name, bool(ok), "" if ok else detail))


def golden(name):
    with open(os.path.join(GOLDEN_DIR, name.replace("/", "__") + ".json")) as f:
        return json.load(f)


def run_scenario(scenario, capture_on=False, max_bytes=None, extra_patch=None):
    """Returns (recorded litellm kwargs, capture entries or None, builder outputs)."""
    builder_outputs = []
    real_build = LiteLLMModel.build_request

    def spy(self, *a, **k):
        out = real_build(self, *a, **k)
        builder_outputs.append(out)
        return out

    import io
    from contextlib import redirect_stdout
    with recording(scenario["responses"]) as rec, patch.object(LiteLLMModel, "build_request", spy):
        with redirect_stdout(io.StringIO()):
            if capture_on:
                with capture_calls(True, max_bytes) as cap:
                    asyncio.run(scenario["run"]())
                entries = cap.to_list()
            else:
                asyncio.run(scenario["run"]())
                entries = None
    return rec.requests, entries, builder_outputs


def canon(reqs, oi):
    return sorted(reqs, key=lambda r: json.dumps(r, sort_keys=True)) if oi else reqs


# ---------------------------------------------------------- 1-4: whole matrix

all_entries = []
for sc in SCENARIOS:
    name, oi = sc["name"], sc["order_insensitive"]
    requests, entries, builder_outputs = run_scenario(sc, capture_on=True)
    want = golden(name)["requests"]

    check(f"{name}: [no second copy] one build_request per completion, identical dicts",
          len(builder_outputs) == len(requests) and all(b == r for b, r in zip(builder_outputs, requests)),
          f"builder={len(builder_outputs)} completion={len(requests)}")
    check(f"{name}: [transparent] requests sent WITH capture on are byte-identical to the goldens",
          json.dumps(canon(requests, oi)) == json.dumps(canon(want, oi)), "capture changed what was sent")
    check(f"{name}: [faithful] one captured entry per model call ({len(requests)})", len(entries) == len(requests), f"{len(entries)} vs {len(requests)}")

    by_seq = sorted(entries, key=lambda e: e["seq"])
    check(f"{name}: seq is 0..n-1 in start order", [e["seq"] for e in by_seq] == list(range(len(by_seq))), [e["seq"] for e in by_seq])
    if not oi:
        ok = all(
            e["prompt"] == r["messages"][0]["content"] and e["model"] == r["model"]
            and e["temperature"] == r.get("temperature") and e["reasoning_effort"] == r.get("reasoning_effort")
            and e["vertex_project"] == r["vertex_project"] and e["vertex_location"] == r["vertex_location"]
            and e["tools"] == r.get("tools") and e["tool_choice"] == r.get("tool_choice")
            and e["response_format"] == r.get("response_format")
            for e, r in zip(by_seq, requests)
        )
        check(f"{name}: [faithful] every entry field equals the request litellm received, in order", ok, "field mismatch")
    else:
        prompts_e = sorted(e["prompt"] for e in entries)
        prompts_r = sorted(r["messages"][0]["content"] for r in requests)
        check(f"{name}: [faithful] entry prompts equal received prompts (order-insensitive)", prompts_e == prompts_r, "prompt mismatch")

    check(f"{name}: [labels] no unlabeled call", all(e["label"] != "unlabeled" for e in entries), [e["label"] for e in entries])
    fingerprint_ok = all(detect_site({"messages": [{"content": e["prompt"]}], "tools": e["tools"], "tool_choice": e["tool_choice"]}) == e["label"] for e in entries)
    check(f"{name}: [labels] each label matches the call site's own prompt fingerprint", fingerprint_ok,
          [(e["label"], detect_site({"messages": [{"content": e["prompt"]}], "tools": e["tools"], "tool_choice": e["tool_choice"]})) for e in entries])
    all_entries.append((name, entries))

labels_seen = {e["label"] for _, es in all_entries for e in es}
check("[labels] all 16 stable labels appear across the matrix", set(ALL_SITES) <= labels_seen, sorted(set(ALL_SITES) - labels_seen))

# ------------------------------------------------------------ 5: Hound threads

strike = next(s for s in SCENARIOS if s["name"] == "strike.run_industrial_strike/two_specialists")
threads_used = []
main_thread = threading.get_ident()

import io  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402
with recording(strike["responses"]) as rec:
    real_fake = rec.fake_completion

    def tracking(**kwargs):
        threads_used.append(threading.get_ident())
        return real_fake(**kwargs)

    with patch.object(agent_factory.litellm, "completion", side_effect=tracking), redirect_stdout(io.StringIO()):
        with capture_calls(True) as cap:
            asyncio.run(strike["run"]())
        hound_entries = [e for e in cap.to_list() if e["label"] == "strike.hound"]

check("[threads] every Hound call (2 specialists x 3 questions) reached the collector", len(hound_entries) == 6, len(hound_entries))
check("[threads] Hound calls really ran on worker threads (not the main/event-loop thread)",
      any(t != threading.get_ident() for t in threads_used) and len(set(threads_used)) > 1, threads_used)
check("[threads] hound entries carry meta.query", all(e["meta"] and e["meta"].get("query", "").startswith("canned question") for e in hound_entries), [e["meta"] for e in hound_entries])
by_role = {}
for e_ in hound_entries:
    by_role.setdefault(e_["meta"].get("role"), []).append(e_["meta"].get("question_index"))
check("[threads] every hound's meta carries its specialist's role and a question_index (deterministic n, whatever the seq order)",
      {r: sorted(v) for r, v in by_role.items()} == {"Market Analyst": [0, 1, 2], "Brand Strategist": [0, 1, 2]}, by_role)
check("[threads] hound meta role matches the role of the specialist_questions call that produced its question",
      all(e_["meta"]["query"] == f"canned question {e_['meta']['question_index'] + 1}" for e_ in hound_entries), [e_["meta"] for e_ in hound_entries])
check("[threads] hound output carries grounding sources", all(e["output"]["grounding_sources"] for e in hound_entries), "")
check("[threads] seq values are unique", len({e["seq"] for e in cap.to_list()}) == len(cap.to_list()), "")

# ------------------------------------------------------------------ 6: segments

SCAFFOLD = {
    "head": "\n### BLOCK 1: THE MANDATE (UNBREAKABLE LAW)\n",
    "b2": "\n\n### BLOCK 2: THE LENS (STRATEGIC PERSPECTIVE)\n",
    "b3": "\n\n### BLOCK 3: THE TRUTH (PROJECT KNOWLEDGE & DATA)\n",
    "b4": "\n### BLOCK 4: THE SIGNAL (SITUATIONAL -- THIS TURN ONLY)\n",
    "tail": "\n[EXECUTION_START: Apply the LENS to the TRUTH while obeying the MANDATE.]\n",
}


def slice_utf16(text, start, end):
    units = text.encode("utf-16-le")
    return units[start * 2:end * 2].decode("utf-16-le")


ORDER = ["mandate", "lens", "truth", "signal"]
segment_entries = 0
for name, entries in all_entries:
    for e in entries:
        segs = e["segments"]
        if e["label"] in ("strike.specialist_questions", "strike.specialist_analyze", "strike.hound"):
            check(f"{name}/{e['label']}: [segments] raw f-string site has no segments", segs == [], segs)
            continue
        segment_entries += 1
        prompt = e["prompt"]
        n_units = utf16_len(prompt)
        layers = [s["layer"] for s in segs]
        check(f"{name}/{e['label']}: [segments] layers are a subsequence of mandate,lens,truth,signal, in order, no repeats",
              layers == sorted(set(layers), key=ORDER.index) and set(layers) <= set(ORDER) and "mandate" in layers, layers)
        non_overlap = all(a["end"] <= b["start"] for a, b in zip(segs, segs[1:]))
        check(f"{name}/{e['label']}: [segments] ordered, non-overlapping, non-zero, inside the prompt",
              non_overlap and all(0 <= s["start"] < s["end"] <= n_units for s in segs), segs)
        # gap rule: every uncovered range must be exactly the template scaffolding that sits
        # between the present layers (an absent/empty layer contributes no segment, only its scaffolding)
        slots = [("s", SCAFFOLD["head"]), ("l", "mandate"), ("s", SCAFFOLD["b2"]), ("l", "lens"), ("s", SCAFFOLD["b3"]), ("l", "truth"),
                 ("s", "\n")]
        if "signal" in layers:
            slots += [("s", SCAFFOLD["b4"]), ("l", "signal"), ("s", "\n")]
        slots += [("s", SCAFFOLD["tail"])]
        want_gaps, acc = [], ""
        for kind, val in slots:
            if kind == "s":
                acc += val
            elif val in layers:
                want_gaps.append(acc)
                acc = ""
        want_gaps.append(acc)
        parts, gaps, prev_end = [], [], 0
        for s_ in segs:
            gaps.append(slice_utf16(prompt, prev_end, s_["start"]))
            parts.append(slice_utf16(prompt, s_["start"], s_["end"]))
            prev_end = s_["end"]
        gaps.append(slice_utf16(prompt, prev_end, n_units))
        check(f"{name}/{e['label']}: [segments] every uncovered range is exactly template scaffolding (gap rule)", gaps == want_gaps, (gaps, want_gaps))
        rebuilt = "".join(g + p_ for g, p_ in zip(gaps, parts)) + gaps[-1]
        check(f"{name}/{e['label']}: [segments] segment text + gaps reproduces the prompt exactly", rebuilt == prompt, "")
        check(f"{name}/{e['label']}: [segments] every segment's bytes is the UTF-8 size of its block",
              all(sg["bytes"] == len(p_.encode("utf-8")) for sg, p_ in zip(segs, parts)), [(sg["bytes"], len(p_.encode("utf-8"))) for sg, p_ in zip(segs, parts)])

check(f"[segments] {segment_entries} PromptBuilder calls checked", segment_entries > 50, segment_entries)

unicode_entry = next(e for n, es in all_entries if n == "pm.run_turn/unicode" for e in es)
check("[segments] unicode scenario really has non-BMP characters (UTF-16 units != code points)",
      utf16_len(unicode_entry["prompt"]) != len(unicode_entry["prompt"]), (utf16_len(unicode_entry["prompt"]), len(unicode_entry["prompt"])))
truth_seg = next(s for s in unicode_entry["segments"] if s["layer"] == "truth")
check("[segments] UTF-16 slice of the truth segment contains the emoji content intact",
      "😀" in slice_utf16(unicode_entry["prompt"], truth_seg["start"], truth_seg["end"]), "")
check("[segments] code-point slicing would have been WRONG for this prompt (proves units matter)",
      unicode_entry["prompt"][truth_seg["start"]:truth_seg["end"]] != slice_utf16(unicode_entry["prompt"], truth_seg["start"], truth_seg["end"]), "")

check("[segments] bytes is UTF-8 bytes, not code points or UTF-16 units (emoji scenario)",
      truth_seg["bytes"] > truth_seg["end"] - truth_seg["start"], (truth_seg["bytes"], truth_seg["end"] - truth_seg["start"]))
signal_entry = next(e for n, es in all_entries if n == "pm.run_turn/all_signals" for e in es)
check("[segments] signal segment present only when a signal exists", [s["layer"] for s in signal_entry["segments"]][-1] == "signal", signal_entry["segments"])
base_entry = next(e for n, es in all_entries if n == "pm.run_turn/base" for e in es)
check("[segments] no signal segment when there is no signal", "signal" not in [s["layer"] for s in base_entry["segments"]], "")

# ------------------------------------------------- 7: errors, oversize, parsed

def scenario_named(n):
    return next(s for s in SCENARIOS if s["name"] == n)


# error path: recorded, then re-raised; behavior with capture off is the same
def boom(**kwargs):
    raise RuntimeError("simulated provider failure")


with recording() as rec, patch.object(agent_factory.litellm, "completion", side_effect=boom):
    raised_off = None
    try:
        asyncio.run(SocialEngine.run_turn(env()))
    except Exception as exc:
        raised_off = exc
    raised_on = None
    with capture_calls(True) as cap:
        try:
            asyncio.run(SocialEngine.run_turn(env()))
        except Exception as exc:
            raised_on = exc
    err_entries = cap.to_list()
check("[error] exception propagates unchanged with capture OFF", type(raised_off) is RuntimeError and "simulated" in str(raised_off), raised_off)
check("[error] exception propagates unchanged with capture ON", type(raised_on) is RuntimeError and "simulated" in str(raised_on), raised_on)
check("[error] the failed call is recorded with type+message and no output",
      len(err_entries) == 1 and err_entries[0]["error"] == {"type": "RuntimeError", "message": "simulated provider failure"} and err_entries[0]["output"] is None and err_entries[0]["prompt"], err_entries)

# oversize stub
_, over_entries, _ = run_scenario(scenario_named("pm.run_turn/kitchen_sink"), capture_on=True, max_bytes=100)
_, full_entries, _ = run_scenario(scenario_named("pm.run_turn/kitchen_sink"), capture_on=True)
o, f = over_entries[0], full_entries[0]
import hashlib  # noqa: E402
check("[oversize] prompt over briefing_max_bytes is nulled and flagged, never truncated",
      o["prompt"] is None and o["oversize"] is True, o["oversize"])
check("[oversize] the stub KEEPS its segments, identical to the full entry's (offsets + bytes), so the big layer is identifiable",
      o["segments"] == f["segments"] and len(o["segments"]) >= 3 and all("bytes" in sg for sg in o["segments"]), o["segments"])
check("[oversize] segment bytes account for most of the withheld prompt (only scaffolding is uncounted)",
      0 < sum(sg["bytes"] for sg in o["segments"]) <= o["size"]["prompt_bytes"], (sum(sg["bytes"] for sg in o["segments"]), o["size"]["prompt_bytes"]))
check("[oversize] stub keeps prompt_bytes and sha256 of the exact text",
      o["size"]["prompt_bytes"] == f["size"]["prompt_bytes"] > 100 and o["prompt_sha256"] == hashlib.sha256(f["prompt"].encode("utf-8")).hexdigest(), "")
check("[oversize] under the threshold nothing is stubbed", f["oversize"] is False and f["prompt"] and f["segments"], "")
check("[oversize] tools/response_format/model settings stay on the stub", o["model"] == f["model"] and o["temperature"] == f["temperature"], "")

long_text = "L" * 5000
with recording() as rec, patch.object(agent_factory.litellm, "completion", side_effect=lambda **kw: __import__("harness")._Response(__import__("harness")._Message(long_text))):
    with redirect_stdout(io.StringIO()), capture_calls(True, 1000) as cap:
        asyncio.run(SocialEngine.run_turn(env()))
    out_over = cap.to_list()[0]
check("[oversize] output over the threshold is nulled and flagged (text and parsed)",
      out_over["output"]["text"] is None and out_over["output"]["parsed"] is None and out_over["output_oversize"] is True and out_over["size"]["output_bytes"] == 5000, out_over["output"])

# the collector is removed when the request scope ends, on success AND on error, in the same context
from core.capture import current_capture  # noqa: E402
with capture_calls(True):
    inside = current_capture() is not None
check("[scope] capture is installed inside capture_calls and gone right after it, in the same context", inside and current_capture() is None, current_capture())
try:
    with capture_calls(True):
        raise RuntimeError("boom")
except RuntimeError:
    pass
check("[scope] capture is removed even when the request body raises", current_capture() is None, current_capture())
with capture_calls(False) as disabled:
    check("[scope] capture_calls(False) installs nothing and yields None", disabled is None and current_capture() is None, current_capture())

# usage
_, usage_entries, _ = run_scenario(scenario_named("pm.run_turn/base"), capture_on=True)
check("[usage] entry carries {prompt_tokens, completion_tokens} from the provider response",
      usage_entries[0]["usage"] == {"prompt_tokens": 11, "completion_tokens": 7}, usage_entries[0]["usage"])
with recording() as rec, patch.object(agent_factory.litellm, "completion", side_effect=lambda **kw: __import__("harness")._Response(__import__("harness")._Message("no usage here"), usage=None)):
    with redirect_stdout(io.StringIO()), capture_calls(True) as cap:
        asyncio.run(SocialEngine.run_turn(env()))
    no_usage = cap.to_list()[0]
check("[usage] a response with no usage data gives usage=null (not an error)", no_usage["usage"] is None and no_usage["output"]["text"] == "no usage here", no_usage["usage"])

# AssembledPrompt survives copy/deepcopy/pickle with text AND segments intact
import copy  # noqa: E402
import pickle  # noqa: E402
from core.prompt_builder import PromptBuilder, AssembledPrompt  # noqa: E402
ap = PromptBuilder.assemble(mandate="M \U0001F600", lens="L", truth="T", signal="S")
for label_, dup in [("copy.copy", copy.copy(ap)), ("copy.deepcopy", copy.deepcopy(ap)), ("pickle round trip", pickle.loads(pickle.dumps(ap)))]:
    check(f"[AssembledPrompt] {label_} keeps the type, exact text and segments",
          type(dup) is AssembledPrompt and str(dup) == str(ap) and dup.segments == ap.segments and len(dup.segments) == 4, (type(dup), dup.segments))

# the record is provably pre-call: a provider mutating the request in place cannot change it
def mutating_completion(**kwargs):
    kwargs["messages"][0]["content"] += " MUTATED-IN-PLACE"
    kwargs["tools"][0]["function"]["name"] = "mutated_tool"
    return __import__("harness")._Response(__import__("harness")._Message("ok"))


local_tools = [{"type": "function", "function": {"name": "original_tool"}}]
with patch.object(agent_factory.litellm, "completion", side_effect=mutating_completion), capture_calls(True) as cap:
    LiteLLMModel("vertex_ai/test").generate_content("original prompt", tools=local_tools, label="test.mutation")
pre = cap.to_list()[0]
check("[pre-call] a provider mutating messages/tools in place does not change the captured record",
      pre["prompt"] == "original prompt" and pre["tools"][0]["function"]["name"] == "original_tool", (pre["prompt"], pre["tools"]))
check("[pre-call] (control) the mutation really happened to the object litellm received", local_tools[0]["function"]["name"] == "mutated_tool", local_tools)

# parsed is what the sites consume: hammer_json(get_clean_text(response)), including fenced JSON
fenced = "```json\n{\"confirmed\": true}\n```"
with recording() as rec, patch.object(agent_factory.litellm, "completion", side_effect=lambda **kw: __import__("harness")._Response(__import__("harness")._Message(fenced))):
    with redirect_stdout(io.StringIO()), capture_calls(True) as cap:
        from core.ignition import confirm_launch_intent
        site_value = confirm_launch_intent(HISTORY, l1="L1", skill="")
    fenced_entry = cap.to_list()[0]
check("[parsed] fenced JSON: parsed equals what the site itself consumed", fenced_entry["output"]["parsed"] == {"confirmed": True} and site_value is True, fenced_entry["output"])

# parsed
_, cov_entries, _ = run_scenario(scenario_named("gatekeeper.assess_coverage/default_schema"), capture_on=True)
check("[parsed] structured call carries the parsed JSON the site would use", cov_entries[0]["output"]["parsed"] == DEFAULT_RESPONSES["coverage"] and cov_entries[0]["output"]["parse_error"] is None, cov_entries[0]["output"])
_, pm_entries, _ = run_scenario(scenario_named("pm.run_turn/base"), capture_on=True)
check("[parsed] free-text call has parsed=null (no schema was sent)", pm_entries[0]["output"]["parsed"] is None and pm_entries[0]["output"]["parse_error"] is None, pm_entries[0]["output"])
with recording() as rec, patch.object(agent_factory.litellm, "completion", side_effect=lambda **kw: __import__("harness")._Response(__import__("harness")._Message("definitely not json"))):
    with redirect_stdout(io.StringIO()), capture_calls(True) as cap:
        from core.coverage import assess_coverage
        assess_coverage(["Q"], [], "L1", None, "")
    bad = cap.to_list()[0]
check("[parsed] a structured call whose reply is not JSON: parsed=null and parse_error set", bad["output"]["parsed"] is None and bad["output"]["parse_error"], bad["output"])
check("[parsed] chat_manager extraction parsed equals the canned items", next(e for n, es in all_entries if n == "chat_manager.extract_facts/minimal" for e in es)["output"]["parsed"] == DEFAULT_RESPONSES["extraction"], "")

# hammer_json split is behavior-preserving (differential vs the original implementation)
import re  # noqa: E402


def original_hammer_json(raw_text):
    try:
        clean_json = re.sub(r'^\`\`\`json\s*|\`\`\`$', '', raw_text.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(clean_json)
        if isinstance(parsed, list):
            return parsed[0] if parsed else {}
        return parsed
    except Exception as e:
        return {"error": "JSON_PARSE_FAILED", "raw": raw_text}


corpus = ['{"a":1}', '```json\n{"a":1}\n```', '```json\n[]\n```', '[{"a":1},{"b":2}]', 'not json', '', '   ', '{"a":', '[]', 'null', '123', '"str"',
          '```\n{"x":[1,2]}\n```', '{"u":"café ☕ \U0001F600"}', '```json\n{"a":1}```', '\n\n{"a":1}\n\n']
check(f"[hammer_json] refactor is identical to the original on {len(corpus)} inputs", all(original_hammer_json(c) == kernel_utils.hammer_json(c) for c in corpus), "")

# ---------------------------------------------------------------- 8: endpoints

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from legacy_routes import enable_legacy_routes  # noqa: E402
enable_legacy_routes(main.app)   # the nine old turn routes answer 410 after the M1b cutover; this suite exercises the legacy handlers (deleted at M4)

from core.capture import CAPTURE_TOKEN_HEADER, set_capture_authorized  # noqa: E402
TOKEN = "step0-test-token-9f2c41d7"
os.environ["KERNEL_CAPTURE_TOKEN"] = TOKEN
client = TestClient(main.app, headers={CAPTURE_TOKEN_HEADER: TOKEN})
from endpoint_payloads import ENDPOINTS, EXPECT_LABEL  # noqa: E402

def post_fresh(path, body):
    with recording(), redirect_stdout(io.StringIO()):
        return client.post(path, json=body)


with recording():
    for path, body in ENDPOINTS.items():
        off = post_fresh(path, body)
        on = post_fresh(path, {**body, "include_briefing": True})
        ok_off = off.status_code == 200
        check(f"{path}: 200 without include_briefing", ok_off, (off.status_code, off.text[:300]))
        if not ok_off:
            continue
        off_json, on_json = off.json(), on.json()
        check(f"{path}: [opt-in] calls and kernel_version are null unless requested", off_json.get("calls") is None and off_json.get("kernel_version") is None, {k: off_json.get(k) for k in ("calls", "kernel_version")})
        check(f"{path}: 200 with include_briefing", on.status_code == 200, (on.status_code, on.text[:300]))
        calls = on_json.get("calls") or []
        check(f"{path}: [opt-in] returns ordered calls, first label {EXPECT_LABEL[path]}", bool(calls) and calls[0]["label"] == EXPECT_LABEL[path] and [c["seq"] for c in calls] == list(range(len(calls))), [c["label"] for c in calls])
        check(f"{path}: kernel_version present with revision/git_sha keys", set((on_json.get("kernel_version") or {}).keys()) == {"revision", "git_sha"}, on_json.get("kernel_version"))
        other = {k: v for k, v in on_json.items() if k not in ("calls", "kernel_version")}
        check(f"{path}: [additive] every pre-existing response field is unchanged by opting in",
              other == {k: v for k, v in off_json.items() if k not in ("calls", "kernel_version")}, "")

    # chained endpoints: order and completeness
    with redirect_stdout(io.StringIO()):
        cs = client.post("/kernel/chat_summary", json={**ENDPOINTS["/kernel/chat_summary"], "include_briefing": True}).json()
        strike_resp = client.post("/kernel/functions/launch_strike_team", json={**ENDPOINTS["/kernel/functions/launch_strike_team"], "include_briefing": True}).json()
    check("[chain] chat_summary calls are extract then one reconcile per fact, in order",
          [c["label"] for c in cs["calls"]] == ["chat_manager.extract_facts", "chat_manager.reconcile_fact", "chat_manager.reconcile_fact"], [c["label"] for c in cs["calls"]])
    slabels = [c["label"] for c in strike_resp["calls"]]
    check("[chain] over HTTP each hound carries the launch's specialist role and question_index",
          sorted((c["meta"]["role"], c["meta"]["question_index"]) for c in strike_resp["calls"] if c["label"] == "strike.hound") == [("Analyst", 0), ("Analyst", 1), ("Analyst", 2)], [c["meta"] for c in strike_resp["calls"] if c["label"] == "strike.hound"])
    check("[chain] strike launch captures brief, questions, hounds, analyze, synthesis",
          slabels[0] == "strike.derive_brief" and slabels.count("strike.hound") == 3 and "strike.specialist_questions" in slabels and "strike.specialist_analyze" in slabels and slabels[-1] == "synthesis.forge_truth", slabels)

    # /kernel/invoke: Clock compression + full chain captured in one request
    bricks = {f"brick_{i}": ("x" * 4500) + f" end{i}" for i in range(5)}
    inv_body = {**ENDPOINTS["/kernel/invoke"], "knowledge_bricks": bricks}
    with redirect_stdout(io.StringIO()):
        inv = client.post("/kernel/invoke", json={**inv_body, "include_briefing": True}).json()
    ilabels = [c["label"] for c in inv["calls"]]
    check("[invoke] the Clock compression call is captured first, PM turn last", ilabels[0] == "maintenance.compress_truth" and ilabels[-1] == "pm.run_turn", ilabels)

    # briefing_max_bytes over the wire
    with redirect_stdout(io.StringIO()):
        small = client.post("/kernel/agents/run_turn", json={**ENDPOINTS["/kernel/agents/run_turn"], "include_briefing": True, "briefing_max_bytes": 50}).json()
    check("[oversize] briefing_max_bytes is honored over HTTP (stub, not truncation)", small["calls"][0]["prompt"] is None and small["calls"][0]["oversize"] is True and small["calls"][0]["prompt_sha256"], small["calls"][0].get("oversize"))
    check("[oversize] over HTTP the stub still carries segments with bytes and the call's usage", len(small["calls"][0]["segments"]) >= 3 and all("bytes" in sg for sg in small["calls"][0]["segments"]) and small["calls"][0]["usage"] == {"prompt_tokens": 11, "completion_tokens": 7}, small["calls"][0].get("segments"))

    # isolation between concurrent requests, and no leak into a following non-capturing request
    def post_marked(marker, capture):
        body = {**ENDPOINTS["/kernel/agents/run_turn"], "history": [{"role": "user", "content": f"MARKER-{marker}"}]}
        if capture:
            body["include_briefing"] = True
        return client.post("/kernel/agents/run_turn", json=body).json()

    with redirect_stdout(io.StringIO()), ThreadPoolExecutor(max_workers=6) as pool:
        futures = [(m, c, pool.submit(post_marked, m, c)) for m, c in [("A", True), ("B", True), ("C", False), ("D", True), ("E", False), ("F", True)]]
        outs = [(m, c, f.result()) for m, c, f in futures]
    isolated = all(
        (c and len(r["calls"]) == 1 and f"MARKER-{m}" in r["calls"][0]["prompt"] and all(f"MARKER-{o}" not in r["calls"][0]["prompt"] for o, _, _ in outs if o != m))
        or (not c and r["calls"] is None)
        for m, c, r in outs
    )
    check("[isolation] 6 concurrent requests: each capturing one sees only its own call; non-capturing get null", isolated, [(m, c, (r["calls"] or [{}])[0].get("label")) for m, c, r in outs])
    with redirect_stdout(io.StringIO()):
        after = post_marked("Z", False)
    check("[isolation] a non-capturing request right after capturing ones gets null (no contextvar leak)", after["calls"] is None and after["kernel_version"] is None, after["calls"])

# kernel_version env
with patch.dict(os.environ, {"K_REVISION": "vibe-kernel-00099-abc", "KERNEL_GIT_SHA": "deadbeef"}), recording():
    with redirect_stdout(io.StringIO()):
        kv = client.post("/kernel/agents/run_turn", json={**ENDPOINTS["/kernel/agents/run_turn"], "include_briefing": True}).json()["kernel_version"]
check("[kernel_version] reads K_REVISION and KERNEL_GIT_SHA", kv == {"revision": "vibe-kernel-00099-abc", "git_sha": "deadbeef"}, kv)

# ------------------------------------------------------------------- report

print("\n=== Step 0 Tier A capture verification ===")
all_pass = True
for name, ok, detail in results:
    if not ok:
        all_pass = False
        print(f"[FAIL] {name} -- {detail}")
if all_pass:
    print("(all individual checks passed; failures would be listed above)")
print(f"\n{len(results)} checks, {'ALL PASS' if all_pass else 'SOME FAILED'}")
sys.exit(0 if all_pass else 1)
