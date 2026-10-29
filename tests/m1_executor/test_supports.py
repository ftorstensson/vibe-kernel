"""
Grounding supports (executor/supports.py, docs/m0 C1 section 4.1): the byte-to-character offset
conversion with the "never wrong offsets" rule, and the extraction of the provider's supports.

The second half runs the whole executor through /kernel/execute with a fake provider response
(`grounding_chunks`, `grounding_supports`, and which links get resolved).

Offline: no network, no model. Provider offsets are computed here INDEPENDENTLY from the text
(`len(text[:i].encode("utf-8"))`), never by the code under test.

Run: python3 tests/m1_executor/test_supports.py
"""
import copy
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import AUTH, FakeModel, briefing, catch_logs, check, fake_model, fake_response, make_client, post, report  # noqa: E402
import httpx  # noqa: E402
from executor import supports  # noqa: E402

GR = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"


def byte_offsets(text, piece, nth=0):
    """(startIndex, endIndex) in UTF-8 bytes, as the provider reports them, for the nth occurrence of piece."""
    i = -1
    for _ in range(nth + 1):
        i = text.index(piece, i + 1)
    return len(text[:i].encode("utf-8")), len(text[:i + len(piece)].encode("utf-8"))


def sup(text, piece, chunks, nth=0, **segment_overrides):
    a, b = byte_offsets(text, piece, nth)
    segment = {"startIndex": a, "endIndex": b, "text": piece}
    segment.update(segment_overrides)
    return {"segment": segment, "groundingChunkIndices": list(chunks)}


def meta(supports_list, n_chunks=10):
    return {"groundingChunks": [{"web": {"uri": f"https://vertexaisearch.cloud.google.com/grounding-api-redirect/C{i}", "title": f"site{i}.example"}} for i in range(n_chunks)],
            "groundingSupports": supports_list}


def run(text, supports_list, n_chunks=10):
    return supports.extract_supports(text, meta(supports_list, n_chunks))


# ------------------------------------------------------------------ ASCII text: offsets unchanged
T = "Canberra is the capital. Sydney is the largest city. Melbourne is second."
out = run(T, [sup(T, "Canberra is the capital.", [0, 1]), sup(T, "Sydney is the largest city.", [2]), sup(T, "Melbourne is second.", [3])])
check("S1 plain ASCII: three supports, in the provider's order, with start/end equal to the character positions",
      [(s["start"], s["end"]) for s in out] == [(0, 24), (25, 52), (53, 73)] and all(T[s["start"]:s["end"]] == s["text"] for s in out), out)
check("S1 each support keeps its text and its chunk indices", [s["text"] for s in out] == ["Canberra is the capital.", "Sydney is the largest city.", "Melbourne is second."] and [s["source_indices"] for s in out] == [[0, 1], [2], [3]], out)
check("S1 every support has exactly the keys text, start, end, source_indices", all(set(s) == {"text", "start", "end", "source_indices"} for s in out), out)

# ------------------------------------------------------------------ multi-byte text before and inside a segment
CASES = {
    "an accented letter (2 bytes)": "Café prices rose. Zürich is dearer. The Señor agreed.",
    "a euro sign (3 bytes)": "A coffee costs € 4.50 in Paris. Tea costs € 3.00 in Lyon. Water is free.",
    "an emoji (4 bytes, 2 UTF-16 units)": "Great start \U0001F600 everyone. The second point stands. A third follows.",
    "Japanese text (3 bytes each)": "コーヒー is coffee. ¥150 is the price. Convenience stores sell it.",
    "an em dash and curly quotes": "Prices rose — sharply — in “most” cities. Wages did not. Nobody was surprised.",
    "a combining accent (e + U+0301)": "Café society endured. The next sentence follows. And one more.",
}
for label, text in CASES.items():
    sentences = [s.strip() + "." for s in text.split(".") if s.strip()]
    sl = [sup(text, s, [i]) for i, s in enumerate(sentences)]
    out = run(text, sl)
    byte_start_of_last = byte_offsets(text, sentences[-1])[0]
    check(f"S2 {label}: all {len(sentences)} segments convert and text[start:end] equals the segment",
          all(o["start"] is not None and text[o["start"]:o["end"]] == o["text"] == sentences[i] for i, o in enumerate(out)), out)
    check(f"S2 {label}: the provider's byte offset differs from the character offset for a later segment (so the test would catch treating bytes as characters)",
          byte_start_of_last != out[-1]["start"], (byte_start_of_last, out[-1]["start"]))
check("S2 the converted offsets are Python code points, not UTF-16 units: after one emoji the start is 1 less than in UTF-16",
      run(CASES["an emoji (4 bytes, 2 UTF-16 units)"], [sup(CASES["an emoji (4 bytes, 2 UTF-16 units)"], "The second point stands.", [0])])[0]["start"] == CASES["an emoji (4 bytes, 2 UTF-16 units)"].index("The second"), "")
ee = "Zürich: Café."
check("S2 a segment that itself contains multi-byte characters converts both ends", run(ee, [sup(ee, "Café", [0])])[0]["text"] == "Café" and run(ee, [sup(ee, "Café", [0])])[0]["start"] == 8, run(ee, [sup(ee, "Café", [0])]))

# ------------------------------------------------------------------ never wrong offsets: null, but the segment is kept
T = "Café is nice. Tea is too."
a, b = byte_offsets(T, "Café is nice.")
BAD = {
    "text does not match the slice": {"segment": {"startIndex": a, "endIndex": b, "text": "Something else."}, "groundingChunkIndices": [0]},
    "offsets treated as characters would match but bytes do not (shifted by one)": {"segment": {"startIndex": a + 1, "endIndex": b + 1, "text": "Café is nice."}, "groundingChunkIndices": [0]},
    "end inside a multi-byte character": {"segment": {"startIndex": 0, "endIndex": 4, "text": "Café"}, "groundingChunkIndices": [0]},
    "start inside a multi-byte character": {"segment": {"startIndex": 4, "endIndex": b, "text": "is nice."}, "groundingChunkIndices": [0]},
    "end beyond the text": {"segment": {"startIndex": 0, "endIndex": 9999, "text": "Café is nice."}, "groundingChunkIndices": [0]},
    "start beyond the text": {"segment": {"startIndex": 9998, "endIndex": 9999, "text": "x"}, "groundingChunkIndices": [0]},
    "end before start": {"segment": {"startIndex": 10, "endIndex": 5, "text": "Café is nice."}, "groundingChunkIndices": [0]},
    "negative start": {"segment": {"startIndex": -1, "endIndex": b, "text": "Café is nice."}, "groundingChunkIndices": [0]},
    "end missing": {"segment": {"startIndex": 0, "text": "Café is nice."}, "groundingChunkIndices": [0]},
    "end is null": {"segment": {"startIndex": 0, "endIndex": None, "text": "Café is nice."}, "groundingChunkIndices": [0]},
    "start is a string": {"segment": {"startIndex": "0", "endIndex": b, "text": "Café is nice."}, "groundingChunkIndices": [0]},
    "end is a float": {"segment": {"startIndex": 0, "endIndex": float(b), "text": "Café is nice."}, "groundingChunkIndices": [0]},
    "end is a bool": {"segment": {"startIndex": 0, "endIndex": True, "text": "C"}, "groundingChunkIndices": [0]},
    "segment text missing": {"segment": {"startIndex": 0, "endIndex": b}, "groundingChunkIndices": [0]},
    "segment is not an object": {"segment": "Café is nice.", "groundingChunkIndices": [0]},
    "segment missing": {"groundingChunkIndices": [0]},
}
for label, support in BAD.items():
    out = run(T, [support])
    check(f"S3 {label}: start and end are null, the support is still kept with its chunk indices", len(out) == 1 and out[0]["start"] is None and out[0]["end"] is None and out[0]["source_indices"] == [0], out)
    check(f"S3 {label}: never a wrong offset (any non-null offset must slice to the segment text)", all(o["start"] is None or T[o["start"]:o["end"]] == o["text"] for o in out), out)
out = run(T, [{"segment": {"startIndex": a, "endIndex": b, "text": "Café is nice."}, "groundingChunkIndices": [0]}])
check("S3 control: the same support with correct offsets converts", out[0]["start"] == 0 and out[0]["end"] == 13, out)

T = "Café is nice. Tea is too."
a0, b0 = byte_offsets(T, "é is nice.")
out = supports.extract_supports(T, meta([{"segment": {"startIndex": a0 + 1, "endIndex": b0, "text": "é is nice."}, "groundingChunkIndices": [0]}]))
check("S4 a start offset inside a multi-byte character is not rounded to the character, even when rounding would make the text match: null, segment kept",
      out[0]["start"] is None and out[0]["end"] is None and out[0]["text"] == "é is nice.", out)
out = supports.extract_supports(T, meta([{"segment": {"startIndex": a0, "endIndex": b0, "text": "é is nice."}, "groundingChunkIndices": [0]}]))
check("S4 ...while the same segment with the true byte offsets converts", out[0]["start"] == 3 and T[out[0]["start"]:out[0]["end"]] == "é is nice.", out)

# ------------------------------------------------------------------ the provider omits startIndex when it is 0
T = "Canberra is the capital. Sydney is big."
out = run(T, [{"segment": {"endIndex": 24, "text": "Canberra is the capital."}, "groundingChunkIndices": [0]}])
check("S4 a missing startIndex means 0 (the provider omits a zero)", out[0]["start"] == 0 and out[0]["end"] == 24, out)
out = run(T, [{"segment": {"endIndex": 5, "text": "Sydney"}, "groundingChunkIndices": [0]}])
check("S4 a missing startIndex with a segment that does not start at 0 is not trusted: null", out[0]["start"] is None and out[0]["end"] is None, out)

# ------------------------------------------------------------------ empty and unusual segments
out = run("abc", [{"segment": {"startIndex": 1, "endIndex": 1, "text": ""}, "groundingChunkIndices": [0]}])
check("S5 an empty segment at a valid position converts to an empty slice", out[0]["start"] == 1 and out[0]["end"] == 1 and out[0]["text"] == "", out)
T = "Alpha beta gamma delta."
out = run(T, [sup(T, "Alpha beta gamma", [0]), sup(T, "beta gamma delta.", [1]), sup(T, "Alpha beta gamma", [2])])
check("S5 overlapping and identical segments are all kept, in the provider's order, each with its own offsets",
      [(o["start"], o["end"], o["source_indices"]) for o in out] == [(0, 16, [0]), (6, 23, [1]), (0, 16, [2])], out)
out = run(T, [sup(T, "Alpha beta gamma", [])])
check("S5 a support with no chunk indices is kept with an empty list", len(out) == 1 and out[0]["source_indices"] == [] and out[0]["start"] == 0, out)
out = run(T, [{"segment": {"startIndex": 0, "endIndex": 5, "text": "Alpha"}}])
check("S5 a support with no groundingChunkIndices key at all is kept with an empty list", out[0]["source_indices"] == [], out)

# ------------------------------------------------------------------ chunk indices
out = run(T, [sup(T, "Alpha", [3, 1, 3, 2, 1, 0])], n_chunks=5)
check("S6 duplicate chunk indices within a support are removed, first occurrence kept, the provider's order kept", out[0]["source_indices"] == [3, 1, 2, 0], out)
out = run(T, [sup(T, "Alpha", [0, 4, 5, 99, -1, "2", 1.0, None, True, 1])], n_chunks=5)
check("S6 indices that are out of range, negative, or not integers are dropped (never left dangling)", out[0]["source_indices"] == [0, 4, 1], out)
out = supports.extract_supports(T, {"groundingSupports": [sup(T, "Alpha", [0, 1])]})
check("S6 with no groundingChunks at all every index is dangling, so none is kept", out[0]["source_indices"] == [] and out[0]["start"] == 0, out)

# ------------------------------------------------------------------ nothing to report
for label, m in (("None", None), ("an empty dict", {}), ("supports missing", {"groundingChunks": []}), ("supports null", {"groundingSupports": None}),
                 ("supports empty", {"groundingSupports": []}), ("supports not a list", {"groundingSupports": {"a": 1}}), ("metadata is a string", "x"), ("metadata is a list", [])):
    check(f"S7 {label}: an empty list, no error", supports.extract_supports("some text", m) == [], "")
out = supports.extract_supports("abc", {"groundingChunks": [], "groundingSupports": [None, 5, "x", [], {"segment": {"startIndex": 0, "endIndex": 3, "text": "abc"}, "groundingChunkIndices": []}]})
check("S7 non-object entries in the supports list are skipped, valid ones kept", len(out) == 1 and out[0]["text"] == "abc" and out[0]["start"] == 0, out)
check("S7 empty answer text with a support: the segment is kept with null offsets", supports.extract_supports("", meta([{"segment": {"startIndex": 0, "endIndex": 3, "text": "abc"}, "groundingChunkIndices": [0]}]))[0]["start"] is None, "")

# ------------------------------------------------------------------ a lone surrogate in the text cannot be measured in UTF-8
bad_text = "Fine start \ud800 broken. Then more text."
out = supports.extract_supports(bad_text, meta([{"segment": {"startIndex": 0, "endIndex": 4, "text": "Fine"}, "groundingChunkIndices": [0, 1]}]))
check("S8 a lone surrogate in the answer text: no error, offsets null, text and indices kept", len(out) == 1 and out[0]["start"] is None and out[0]["end"] is None and out[0]["source_indices"] == [0, 1], out)

# ------------------------------------------------------------------ raw_metadata: where litellm puts it
M = {"groundingChunks": [], "groundingSupports": []}
check("S9 raw_metadata reads response.vertex_ai_grounding_metadata (a list, one dict per candidate): the first", supports.raw_metadata(types.SimpleNamespace(vertex_ai_grounding_metadata=[M, {"x": 1}])) is M, "")
check("S9 raw_metadata accepts a dict", supports.raw_metadata(types.SimpleNamespace(vertex_ai_grounding_metadata=M)) is M, "")
check("S9 raw_metadata falls back to _hidden_params", supports.raw_metadata(types.SimpleNamespace(_hidden_params={"vertex_ai_grounding_metadata": [M]})) is M, "")
for label, r in (("no attribute", types.SimpleNamespace()), ("None", types.SimpleNamespace(vertex_ai_grounding_metadata=None)), ("an empty list", types.SimpleNamespace(vertex_ai_grounding_metadata=[])),
                 ("a list of non-dicts", types.SimpleNamespace(vertex_ai_grounding_metadata=["x"])), ("a string", types.SimpleNamespace(vertex_ai_grounding_metadata="x"))):
    check(f"S9 raw_metadata with {label}: None", supports.raw_metadata(r) is None, "")

# ------------------------------------------------------------------ robustness and cost
T = "Alpha beta. Gamma delta. Epsilon zeta."
original = meta([sup(T, "Alpha beta.", [0, 1]), {"segment": {"startIndex": 1}, "groundingChunkIndices": [1, 1]}])
snapshot = copy.deepcopy(original)
supports.extract_supports(T, original)
check("S10 the provider's metadata is never modified", original == snapshot, "")
GARBAGE = [None, 0, 1.5, True, "", "x", [], [1], {}, {"a": 1}, {"segment": None}, {"segment": {"startIndex": [], "endIndex": {}, "text": 5}, "groundingChunkIndices": "abc"}, {"groundingChunkIndices": {"a": 1}}]
for g in GARBAGE:
    try:
        supports.extract_supports(T, {"groundingChunks": g, "groundingSupports": [g, {"segment": g, "groundingChunkIndices": g}]})
        ok = True
    except Exception as exc:  # noqa: BLE001
        ok = repr(exc)
    check(f"S10 garbage {str(g)[:30]!r} in every field: never raises", ok is True, ok)
big = ("The quick brown fox é jumps over the lazy dog. " * 5000)
sl = [sup(big, "jumps over the lazy dog.", [i % 10], nth=i) for i in range(0, 2000)]
t0 = time.perf_counter()
out = run(big, sl)
took = time.perf_counter() - t0
check("S10 a 225 KB answer with 2000 supports converts in well under a second", took < 1.0 and sum(1 for o in out if o["start"] is not None) == 2000, took)

# ====================================================================== extract_chunks
M2 = {"groundingChunks": [{"web": {"uri": GR + "A", "title": "a.example"}}, {"web": {"uri": GR + "B"}}, {"retrievedContext": {"uri": "gs://x/y", "title": "ctx"}},
                          "junk", None, {"web": {"uri": "", "title": 5}}, {"web": "x"}]}
ch = supports.extract_chunks(M2)
check("S11 extract_chunks keeps every chunk in the provider's order, so an index into the provider's list is an index into this one", len(ch) == 7, ch)
check("S11 a web chunk is {title, url, redirect_url, resolved:false}, the url and redirect_url both the provider's address", ch[0] == {"title": "a.example", "url": GR + "A", "redirect_url": GR + "A", "resolved": False}, ch[0])
check("S11 a web chunk without a title gets \"Source\" (as grounding_sources does)", ch[1] == {"title": "Source", "url": GR + "B", "redirect_url": GR + "B", "resolved": False}, ch[1])
NOWEB = {"title": "Source", "url": None, "redirect_url": None, "resolved": False}
check("S11 a chunk that is not a web page, or is malformed, keeps its place with a null url", ch[2:] == [NOWEB] * 5, ch[2:])
for g in (None, 0, "x", [], {}, {"groundingChunks": None}, {"groundingChunks": "x"}, {"groundingChunks": {}}):
    check(f"S11 extract_chunks of {str(g)[:30]!r}: [] and no error", supports.extract_chunks(g) == [], "")
check("S11 referenced_indices: sorted, distinct, only what some support points at", supports.referenced_indices([{"source_indices": [5, 1]}, {"source_indices": []}, {"source_indices": [1, 9]}]) == [1, 5, 9], "")

# ====================================================================== through /kernel/execute
client = make_client()
HOUND = dict(model="vertex_ai/gemini-2.5-flash", temperature=0.1, reasoning_effort=None, tools=[{"googleSearch": {}}], timeout_s=150)
TEXT = "Café prices rose across Europe. Wages in Zürich did not. Nobody was surprised by € 4.50 coffee."
N = 12


def chunk_uri(i):
    return GR + f"CH{i}"


def real_page(i):
    return f"https://pages.example/{i}"


def metadata(n=N, supports_list=None, uri=chunk_uri):
    return {"groundingChunks": [{"web": {"uri": uri(i), "title": f"site{i}.example"}} for i in range(n)],
            "groundingSupports": supports_list if supports_list is not None else [], "webSearchQueries": ["q"]}


def annotations_for(meta_):
    """What litellm builds from the same metadata: ONE annotation per support, from its FIRST chunk only."""
    out = []
    for sp in meta_["groundingSupports"]:
        idx = sp.get("groundingChunkIndices") or []
        if idx:
            w = meta_["groundingChunks"][idx[0]]["web"]
            out.append({"type": "url_citation", "url_citation": {"title": w["title"], "url": w["uri"]}})
    return out


def go(meta_, text=TEXT, redirects=None, handler=None, annotations="auto", **kw):
    ann = annotations_for(meta_) if annotations == "auto" and meta_ else annotations if annotations != "auto" else None
    model = FakeModel(fake_response(text, annotations=ann, grounding_metadata=meta_))
    with fake_model(model) as fake:
        fake.redirects = redirects if redirects is not None else {chunk_uri(i): real_page(i) for i in range(60)}
        fake.net_handler = handler
        with catch_logs() as logs:
            r = post(client, briefing("Hound question", **dict(HOUND, **kw)))
    return r, r.json(), fake, logs


MANY = [sup(TEXT, "Café prices rose across Europe.", list(range(9))), sup(TEXT, "Wages in Zürich did not.", [3, 9]), sup(TEXT, "Nobody was surprised by € 4.50 coffee.", [])]
r, body, fake, logs = go(metadata(supports_list=MANY))
o = body["output"]
check("S12 the call is a success and the output has exactly the documented keys",
      r.status_code == 200 and body["status"] == "ok" and set(o) == {"text", "tool_calls", "grounding_sources", "grounding_chunks", "grounding_supports", "parsed", "parse_error"}, sorted(o))
check("S12 grounding_chunks has every chunk the provider returned, in the provider's order", [c["title"] for c in o["grounding_chunks"]] == [f"site{i}.example" for i in range(N)], [c["title"] for c in o["grounding_chunks"]])
check("S12 THE 26% CASE: a sentence citing nine pages keeps all nine (source_indices 0..8)", o["grounding_supports"][0]["source_indices"] == list(range(9)), o["grounding_supports"][0])
check("S12 ...whereas grounding_sources, one entry per sentence from its first page only, cannot carry them: two entries for those three sentences", len(o["grounding_sources"]) == 2, o["grounding_sources"])
check("S12 supports: provider order, [3, 9] and [] kept, and every index points at a real entry of grounding_chunks",
      [x["source_indices"] for x in o["grounding_supports"]] == [list(range(9)), [3, 9], []] and all(0 <= i < len(o["grounding_chunks"]) for x in o["grounding_supports"] for i in x["source_indices"]), o["grounding_supports"])
check("S12 offsets are character offsets into output.text (the text has accents and a euro sign before later segments)",
      all(o["text"][x["start"]:x["end"]] == x["text"] for x in o["grounding_supports"]) and [x["start"] for x in o["grounding_supports"]] == [0, 32, 57], [(x["start"], x["end"]) for x in o["grounding_supports"]])
referenced = list(range(10))
check("S13 every chunk some support points at is resolved to its real page; its redirect_url is kept",
      all(o["grounding_chunks"][i] == {"title": f"site{i}.example", "url": real_page(i), "redirect_url": chunk_uri(i), "resolved": True} for i in referenced), o["grounding_chunks"][:3])
check("S13 a chunk no support points at is returned unresolved and is never looked up",
      all(o["grounding_chunks"][i] == {"title": f"site{i}.example", "url": chunk_uri(i), "redirect_url": chunk_uri(i), "resolved": False} for i in (10, 11)) and chunk_uri(10) not in fake.fetches and chunk_uri(11) not in fake.fetches, fake.fetches)
check("S13 each referenced link is requested exactly once although sources and chunks share them", sorted(fake.fetches) == sorted(chunk_uri(i) for i in referenced), fake.fetches)
check("S13 exactly one model call", len(fake.calls) == 1, len(fake.calls))
log_text = "\n".join(logs.lines)
check("S13 the log records counts only (links_resolved=a/b) and no address", "links_resolved=" in log_text and "vertexaisearch" not in log_text and "pages.example" not in log_text, [l for l in logs.lines if "executor.call" in l])

# grounding_sources behaves exactly as before: same entries with and without the new metadata
r2, body2, fake2, _ = go(None, annotations=annotations_for(metadata(supports_list=MANY)))
check("S14 grounding_sources is identical to what the same annotations give without any metadata (same shape, order, resolution)", body2["output"]["grounding_sources"] == o["grounding_sources"], (body2["output"]["grounding_sources"], o["grounding_sources"]))
check("S14 ...and without metadata the new fields are empty lists, not missing", body2["output"]["grounding_chunks"] == [] and body2["output"]["grounding_supports"] == [], body2["output"])
check("S14 grounding_sources keeps one entry per support with a first chunk, repeated pages included", [x["title"] for x in o["grounding_sources"]] == ["site0.example", "site3.example"], o["grounding_sources"])

# a call with no search at all
r3, body3, fake3, _ = go(None, annotations=None)
check("S15 no search: both new fields are [] and nothing is requested", body3["output"]["grounding_chunks"] == [] and body3["output"]["grounding_supports"] == [] and body3["output"]["grounding_sources"] == [] and fake3.fetches == [], body3["output"])

# the provider reports chunks but no supports
r4, body4, fake4, _ = go(metadata(supports_list=[]), annotations=None)
o4 = body4["output"]
check("S16 chunks but no supports: all chunks returned unresolved, supports [], and no link is looked up",
      len(o4["grounding_chunks"]) == N and not any(c["resolved"] for c in o4["grounding_chunks"]) and o4["grounding_supports"] == [] and fake4.fetches == [], (fake4.fetches, o4["grounding_supports"]))
r4b, body4b, fake4b, _ = go({"groundingSupports": [sup(TEXT, "Café prices rose across Europe.", [0])]}, annotations=None)
check("S16 supports but no chunk list: the support is kept with no indices, and nothing is requested", body4b["output"]["grounding_chunks"] == [] and body4b["output"]["grounding_supports"][0]["source_indices"] == [] and fake4b.fetches == [], body4b["output"])

# referenced chunks that are not the first ones: each resolved link lands on ITS chunk
gap = metadata(n=8, supports_list=[sup(TEXT, "Café prices rose across Europe.", [5, 2]), sup(TEXT, "Wages in Zürich did not.", [7])])
r4c, body4c, fake4c, _ = go(gap)
ch4c = body4c["output"]["grounding_chunks"]
check("S16 referenced chunks 2, 5 and 7 are resolved, each to its own page, and the others (0, 1, 3, 4, 6) are untouched",
      [c["resolved"] for c in ch4c] == [False, False, True, False, False, True, False, True] and [ch4c[i]["url"] for i in (2, 5, 7)] == [real_page(2), real_page(5), real_page(7)]
      and sorted(fake4c.fetches) == sorted(chunk_uri(i) for i in (2, 5, 7)), (fake4c.fetches, [(c["url"][-12:], c["resolved"]) for c in ch4c]))

# a de-duplicated source: two chunks, one address
same = lambda i: GR + ("SAME" if i in (0, 1) else f"CH{i}")
dup = metadata(n=3, supports_list=[sup(TEXT, "Café prices rose across Europe.", [0, 1, 2])], uri=same)
r5, body5, fake5, _ = go(dup, redirects={GR + "SAME": real_page(0), GR + "CH2": real_page(2)})
check("S17 two chunks with the same address both keep their place and both resolve, from one request",
      [c["resolved"] for c in body5["output"]["grounding_chunks"]] == [True, True, True] and body5["output"]["grounding_chunks"][1]["url"] == real_page(0)
      and sorted(fake5.fetches) == sorted([GR + "SAME", GR + "CH2"]), (fake5.fetches, body5["output"]["grounding_chunks"]))

# a chunk that is not a web page, an index outside the list, and a repeated index
odd = {"groundingChunks": [{"web": {"uri": chunk_uri(0), "title": "site0.example"}}, {"retrievedContext": {"uri": "gs://bucket/doc"}}],
       "groundingSupports": [sup(TEXT, "Café prices rose across Europe.", [1, 0, 0, 7, -1, "x"])]}
r6, body6, fake6, _ = go(odd, annotations=None)
o6 = body6["output"]
check("S18 an index of a non-web chunk is kept (the chunk keeps its place, url null); a repeated, out-of-range, negative or non-integer index is dropped",
      o6["grounding_supports"][0]["source_indices"] == [1, 0] and o6["grounding_chunks"][1] == {"title": "Source", "url": None, "redirect_url": None, "resolved": False}
      and o6["grounding_chunks"][0]["resolved"] is True and fake6.fetches == [chunk_uri(0)], (o6["grounding_supports"], o6["grounding_chunks"], fake6.fetches))

# the per-call cap is shared; the sources come first, so they are resolved exactly as before
many = metadata(n=45, supports_list=[sup(TEXT, "Café prices rose across Europe.", list(range(45)))])
r7, body7, fake7, _ = go(many, annotations=[{"type": "url_citation", "url_citation": {"title": "site44.example", "url": chunk_uri(44)}}])
o7 = body7["output"]
check("S19 at most 30 distinct addresses are requested per call; the source is among them (sources come first)", len(set(fake7.fetches)) == 30 and chunk_uri(44) in fake7.fetches, len(set(fake7.fetches)))
check("S19 ...the source is resolved, chunks past the cap stay unresolved with their redirect, and the call is still a success",
      body7["status"] == "ok" and o7["grounding_sources"][0]["resolved"] is True and sum(c["resolved"] for c in o7["grounding_chunks"]) == 30 and o7["grounding_chunks"][-2]["resolved"] is False, sum(c["resolved"] for c in o7["grounding_chunks"]))


# lookups failing never fail the call
def boom(request):
    raise RuntimeError("network exploded")


r8, body8, fake8, _ = go(metadata(supports_list=MANY), handler=boom)
check("S20 every lookup failing: still a success, chunks keep their redirect, supports and offsets intact",
      r8.status_code == 200 and body8["status"] == "ok" and not any(c["resolved"] for c in body8["output"]["grounding_chunks"])
      and body8["output"]["grounding_chunks"][0]["url"] == chunk_uri(0) and len(body8["output"]["grounding_supports"]) == 3, body8["output"]["grounding_chunks"][:1])

# a Google redirect that answers with a redirect to Google again, or to a bad address, is not accepted for a chunk either
r9, body9, fake9, _ = go(metadata(n=2, supports_list=[sup(TEXT, "Café prices rose across Europe.", [0, 1])]), redirects={chunk_uri(0): GR + "ELSEWHERE", chunk_uri(1): "javascript:alert(1)"})
check("S20 the same Location rules apply to chunks: a Google or non-http(s) Location leaves the chunk unresolved", [c["resolved"] for c in body9["output"]["grounding_chunks"]] == [False, False], body9["output"]["grounding_chunks"])

# a malformed provider metadata never turns a good answer into an error
for label, bad in (("a string", "x"), ("supports not a list", {"groundingChunks": [], "groundingSupports": "x"}), ("supports with junk", {"groundingChunks": [{"web": {"uri": chunk_uri(0)}}], "groundingSupports": [None, 5, {"segment": 3}]})):
    rb, bb, _, _ = go(bad, annotations=None)
    check(f"S21 malformed metadata ({label}): the call is still status ok with the text", rb.status_code == 200 and bb["status"] == "ok" and bb["output"]["text"] == TEXT, bb.get("error"))

# structured output and parse_mode are untouched
r10, body10, _, _ = go(metadata(supports_list=MANY), text='{"a": 1}', parse_mode="json_strict")
check("S22 parse_mode still works next to the new fields", body10["output"]["parsed"] == {"a": 1} and body10["output"]["parse_error"] is None, body10["output"])

sys.exit(report("Grounding supports (executor/supports.py): offsets and extraction"))
