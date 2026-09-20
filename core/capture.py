"""
Step 0 capture (doc-26): opt-in, request-scoped record of every model call a
Kernel request makes -- the exact litellm kwargs, the model's output, timing --
returned to the caller on the response. Kernel stores nothing.

The collector lives in a ContextVar, installed by an endpoint only when the
request sets include_briefing=true. With no collector installed (the default)
LiteLLMModel.generate_content does one ContextVar read and behaves exactly as
before. asyncio.to_thread copies the current context, so calls made from worker
threads (Strike Team hounds) reach the same collector.

Segment rules (what Studio renders):
- layer is an open string id: mandate|lens|truth|signal today, l1..l6 later.
- start/end are UTF-16 code units (JavaScript string indices) into the exact
  `prompt` string returned in the same entry, half-open [start, end).
- A segment covers only a block's content, never the "### BLOCK n" headings.
- Segments are ordered, non-overlapping, never zero-length. Each carries `bytes`,
  the UTF-8 size of that block's content. An oversize stub (prompt withheld)
  keeps its segments: offsets then refer to the withheld prompt, and `bytes`
  is what identifies which layer blew the cap.
- GAP RULE: any character not inside a segment is template scaffolding (block
  headings, blank-line separators, the trailing [EXECUTION_START] line) and is
  to be shown as "Unlabelled". Calls composed as raw f-strings (Strike Team
  specialists/hounds) have no segments at all: the whole prompt is Unlabelled.

Known coarseness (segments are Kernel's four blocks, not doc-13's L1-L6; the
per-call builders in Step 3 refine this without changing the shape):
- `lens` of PM calls (run_turn / run_global_turn / run_global_turn_answer /
  synthesize_dispatch) merges the persona's system_prompt (doc-13 L2) with
  L3 context and, appended after it, partner protocols, phase purpose and
  the project map.
- `mandate` of pm.run_turn carries [STATUS: GREEN/RED] (physics_open, a
  Verdict) and KAISER MANDATE (Strike Team output, a Signal) alongside L1
  and TOOL LAW: the known whisper-in-L1 divergence, shown as it actually is.
- `truth` of maintenance.compress_truth ends with a fixed "Return ONLY the
  compressed text summary" instruction (a Task-layer instruction) that is
  appended to the truth value before assembly.
- `truth` of PM calls is knowledge_bricks + the last five history turns
  (+ ancestor_chat_summary on pm.run_turn).
"""
import contextvars
import copy
import hashlib
import hmac
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from core.kernel_utils import get_clean_text, parse_json_lenient

_CAPTURE = contextvars.ContextVar("kernel_capture", default=None)

# Capture hands the caller Kernel's prompt scaffolding, so it is honoured only
# for a request presenting the shared token. Fail closed: an unset OR empty
# KERNEL_CAPTURE_TOKEN means capture is never honoured (two empties never match).
# A missing/wrong token is ignored silently (flag treated as false, no error,
# nothing logged or echoed). The token, the header and the env value must never
# be logged, returned or placed in a capture.
CAPTURE_TOKEN_HEADER = "X-Kernel-Capture-Token"
CAPTURE_TOKEN_ENV = "KERNEL_CAPTURE_TOKEN"
_AUTHORIZED = contextvars.ContextVar("kernel_capture_authorized", default=False)


def capture_token_valid(presented):
    expected = os.environ.get(CAPTURE_TOKEN_ENV) or ""
    if not expected or not presented:
        return False
    return hmac.compare_digest(str(presented).encode("utf-8"), expected.encode("utf-8"))


def set_capture_authorized(authorized):
    _AUTHORIZED.set(bool(authorized))


def current_capture():
    return _CAPTURE.get()


def kernel_version():
    return {"revision": os.getenv("K_REVISION"), "git_sha": os.getenv("KERNEL_GIT_SHA")}


def utf16_len(text):
    return len(text.encode("utf-16-le")) // 2


def _byte_len(text):
    return len(text.encode("utf-8")) if text is not None else 0


class _Call:
    __slots__ = ("seq", "label", "meta", "started_at", "t0", "request", "segment_source", "duration_ms", "output", "error", "usage")

    def __init__(self, seq, label, meta, request, segment_source):
        self.seq = seq
        self.label = label
        self.meta = meta
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.t0 = time.monotonic()
        self.request = request
        self.segment_source = segment_source
        self.duration_ms = None
        self.output = None
        self.error = None
        self.usage = None


class CallCapture:
    def __init__(self, max_bytes=None):
        self.max_bytes = max_bytes
        self._calls = []
        self._seq = 0
        self._lock = threading.Lock()

    def begin(self, label, meta, request, segment_source):
        with self._lock:
            call = _Call(self._seq, label or "unlabeled", meta, copy.deepcopy(request), segment_source)
            self._seq += 1
            self._calls.append(call)
        return call

    def finish(self, call, response):
        call.duration_ms = int((time.monotonic() - call.t0) * 1000)
        parsed, parse_error = None, None
        if "response_format" in call.request:
            try:
                parsed = parse_json_lenient(get_clean_text(response))
            except Exception as exc:
                parse_error = str(exc)
        call.usage = getattr(response, "usage", None)
        call.output = {
            "text": response.text,
            "parsed": parsed,
            "parse_error": parse_error,
            "tool_calls": list(response.tool_calls),
            "grounding_sources": list(response.grounding_sources),
        }

    def fail(self, call, exc):
        call.duration_ms = int((time.monotonic() - call.t0) * 1000)
        call.error = {"type": type(exc).__name__, "message": str(exc)}

    def to_list(self):
        with self._lock:
            calls = sorted(self._calls, key=lambda c: c.seq)
        return [self._entry(c) for c in calls]

    def _entry(self, call):
        request = call.request
        prompt = request["messages"][0]["content"]
        prompt_bytes = _byte_len(prompt)
        output_text = call.output["text"] if call.output else None
        output_bytes = _byte_len(output_text)
        segments = call.segment_source.segments if call.segment_source is not None else []

        oversize = self.max_bytes is not None and prompt_bytes > self.max_bytes
        output_oversize = self.max_bytes is not None and output_bytes > self.max_bytes
        output = None
        if call.output:
            output = dict(call.output)
            if output_oversize:
                output["text"] = None
                output["parsed"] = None

        return {
            "seq": call.seq,
            "label": call.label,
            "meta": call.meta,
            "started_at": call.started_at,
            "duration_ms": call.duration_ms,
            "model": request.get("model"),
            "temperature": request.get("temperature"),
            "reasoning_effort": request.get("reasoning_effort"),
            "vertex_project": request.get("vertex_project"),
            "vertex_location": request.get("vertex_location"),
            "prompt": None if oversize else prompt,
            "tools": request.get("tools"),
            "tool_choice": request.get("tool_choice"),
            "response_format": request.get("response_format"),
            "output": output,
            "usage": call.usage,
            "error": call.error,
            "segments": segments,
            "size": {"prompt_bytes": prompt_bytes, "output_bytes": output_bytes},
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "oversize": oversize,
            "output_oversize": output_oversize,
        }


@contextmanager
def capture_calls(enabled, max_bytes=None):
    """Installs a collector for the duration of one request when enabled AND the
    request was authorized by the token gate; yields None (and installs
    nothing) otherwise."""
    if not enabled or not _AUTHORIZED.get():
        yield None
        return
    capture = CallCapture(max_bytes)
    token = _CAPTURE.set(capture)
    try:
        yield capture
    finally:
        _CAPTURE.reset(token)


def attach_capture(response, capture):
    """Adds calls/kernel_version to a response dict only when capture ran;
    otherwise returns the response untouched."""
    if capture is None:
        return response
    response = dict(response)
    response["calls"] = capture.to_list()
    response["kernel_version"] = kernel_version()
    return response
