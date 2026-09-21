"""
Shared helpers for the Milestone 1 executor tests (docs/m0/C1 section 6, K1 9.2).

Plain scripts, like tests/step0_capture (the repo has no pytest): each test file
collects `check(name, ok, detail)` results, prints failures and exits non-zero.
Every test patches litellm.acompletion at the module boundary the executor calls,
so no network and no real model is ever used; a guard also fails the run if the
synchronous litellm.completion is touched.

The hashes here are computed by an INDEPENDENT copy of the C1 5.2 rule (not by
executor.schema), so a bug in the executor's hashing cannot hide behind itself;
test_contract.py T15 additionally pins the four literal vectors.
"""
import hashlib
import json
import logging
import os
import sys
import types
from contextlib import contextmanager
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import litellm  # noqa: E402

TOKEN = "Tok-3n-Exec-9f2a7c1d5b8e"
AUTH_HEADER = "X-Kernel-Auth-Token"
AUTH = {AUTH_HEADER: TOKEN}

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), "" if ok else str(detail)))


def report(title):
    print(f"\n=== {title} ===")
    failed = [(n, d) for n, ok, d in results if not ok]
    for name, detail in failed:
        print(f"[FAIL] {name} -- {detail}")
    print(f"{len(results)} checks, {'ALL PASS' if not failed else str(len(failed)) + ' FAILED'}")
    return 0 if not failed else 1


# ---------------------------------------------------------------- hashing (independent)
def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def request_params(b):
    """The R object of C1 5.2 from a Briefing dict: litellm names, non-null only,
    no messages / vertex_*."""
    r = {"model": b["model"], "timeout": b["timeout_s"]}
    for src, dst in (("temperature", "temperature"), ("reasoning_effort", "reasoning_effort"),
                     ("max_output_tokens", "max_tokens"), ("tools", "tools"),
                     ("tool_choice", "tool_choice"), ("response_format", "response_format")):
        if b.get(src) is not None:
            r[dst] = b[src]
    return r


def request_sha(b):
    return hashlib.sha256(json.dumps(request_params(b), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def briefing(prompt="Say hello.", **overrides):
    """A valid Briefing dict. Shas are computed from the final fields unless
    given explicitly."""
    b = {
        "contract_version": 1, "attempt_id": "att-1", "call_label": "test.call",
        "prompt": prompt, "prompt_sha256": None, "request_sha256": None,
        "model": "vertex_ai/gemini-2.5-flash", "temperature": 0.0, "reasoning_effort": "disable",
        "max_output_tokens": None, "tools": None, "tool_choice": None, "response_format": None,
        "parse_mode": "text", "timeout_s": 60, "segments": [],
    }
    b.update(overrides)
    if b["prompt_sha256"] is None:
        b["prompt_sha256"] = sha(b["prompt"])
    if b["request_sha256"] is None:
        b["request_sha256"] = request_sha(b)
    return b


# ---------------------------------------------------------------- fake model
def fake_response(text="ok", tool_calls=None, annotations=None, finish_reason="stop",
                  usage=(6, 1, 0), model="gemini-2.5-flash"):
    tcs = None
    if tool_calls is not None:
        tcs = [types.SimpleNamespace(function=types.SimpleNamespace(name=n, arguments=a)) for n, a in tool_calls]
    message = types.SimpleNamespace(content=text, tool_calls=tcs, annotations=annotations)
    choice = types.SimpleNamespace(message=message, finish_reason=finish_reason)
    u = None
    if usage is not None:
        u = types.SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1],
                                  completion_tokens_details=types.SimpleNamespace(reasoning_tokens=usage[2]))
    return types.SimpleNamespace(choices=[choice], usage=u, model=model)


class FakeModel:
    """Stands in for litellm.acompletion. `behavior` may be a response, an
    exception instance (raised), or a callable(kwargs) returning either (it may
    be async)."""

    def __init__(self, behavior=None):
        self.calls = []
        self.behavior = behavior if behavior is not None else (lambda kw: fake_response("ok"))

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        behavior = self.behavior
        if callable(behavior):
            behavior = behavior(kwargs)
            if hasattr(behavior, "__await__"):
                behavior = await behavior
        if isinstance(behavior, BaseException):
            raise behavior
        return behavior


def _no_sync_completion(*a, **k):
    raise AssertionError("the executor must never call the synchronous litellm.completion")


@contextmanager
def fake_model(fake=None, token=TOKEN, extra_env=None):
    fake = fake or FakeModel()
    env = {"KERNEL_AUTH_TOKEN": token if token is not None else ""}
    env.update(extra_env or {})
    with patch.object(litellm, "acompletion", fake), patch.object(litellm, "completion", _no_sync_completion), \
            patch.dict(os.environ, env):
        yield fake


# ---------------------------------------------------------------- logs
class LogCatcher(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []
        self._seen = set()
        self._keep = []          # keep records alive so id() values are never reused

    def emit(self, record):
        if id(record) in self._seen:      # one record reaches every attached logger
            return
        self._seen.add(id(record))
        self._keep.append(record)
        try:
            self.lines.append(self.format(record))
        except Exception:
            self.lines.append(str(record.msg))


@contextmanager
def catch_logs():
    handler = LogCatcher()
    names = ("", "uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "starlette", "litellm")
    saved = []
    for n in names:
        lg = logging.getLogger(n)
        saved.append((lg, lg.level))
        lg.addHandler(handler)
        lg.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        for lg, level in saved:
            lg.removeHandler(handler)
            lg.setLevel(level)


def make_client():
    import warnings
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def post(client, body, headers=None):
    return client.post("/kernel/execute", json=body, headers=AUTH if headers is None else headers)
