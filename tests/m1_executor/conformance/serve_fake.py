"""
Runs the REAL executor (the same main.app that is deployed) with ONE thing replaced:
litellm.acompletion is a deterministic fake, so a conformance run needs no network,
no Google credentials and costs nothing. The fake decides what to do from the
Briefing's `call_label` (Backend never uses these labels in production), so the
executor under test is unchanged.

    KERNEL_AUTH_TOKEN=<throwaway> python3 tests/m1_executor/conformance/serve_fake.py --port 8899

Fake behaviors (by call_label):
    conf.echo                 the model returns the prompt text it received, byte for byte
    conf.tool_calls           no text; two tool calls, the second one malformed
    conf.length               finish_reason "length"
    conf.grounded             url_citation annotations (one without a title)
    conf.json.plain           text {"a": 1}
    conf.json.fenced          text in a ```json fence
    conf.json.list            text [{"a": 1}, {"a": 2}]
    conf.json.invalid         text that is not JSON
    conf.slow                 sleeps 5 s (use timeout_s 1)
    conf.error.<category>     raises the litellm exception for that category, whose text
                              contains SECRET-PROVIDER-TEXT and a projects/<id> path
    anything else             echo
"""
import argparse
import asyncio
import contextvars
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

import httpx  # noqa: E402
import litellm  # noqa: E402

RAW = "SECRET-PROVIDER-TEXT: Publisher Model `projects/vibe-agent-final/locations/us-central1/x` failed"


def _exc(cls, **extra):
    try:
        return cls(message=RAW, model="vertex_ai/gemini-2.5-flash", llm_provider="vertex_ai", **extra)
    except TypeError:
        response = httpx.Response(400, request=httpx.Request("POST", "https://provider.invalid"))
        return cls(message=RAW, model="vertex_ai/gemini-2.5-flash", llm_provider="vertex_ai", response=response)


def error_for(category):
    e = litellm.exceptions
    table = {
        "timeout": lambda: _exc(e.Timeout),
        "model_not_found": lambda: _exc(e.NotFoundError),
        "bad_request": lambda: _exc(e.BadRequestError),
        "rate_limited": lambda: _exc(e.RateLimitError),
        "provider_unavailable": lambda: _exc(e.ServiceUnavailableError),
        "context_too_long": lambda: _exc(e.ContextWindowExceededError),
        "content_blocked": lambda: _exc(e.ContentPolicyViolationError),
        "provider_auth": lambda: _exc(e.AuthenticationError),
        "provider_error": lambda: e.APIError(status_code=418, message=RAW, llm_provider="vertex_ai", model="m"),
    }
    return table[category]()


def response(text="", tool_calls=None, annotations=None, finish_reason="stop", usage=(6, 1, 0), model="gemini-2.5-flash"):
    tcs = None
    if tool_calls is not None:
        tcs = [types.SimpleNamespace(function=types.SimpleNamespace(name=n, arguments=a)) for n, a in tool_calls]
    message = types.SimpleNamespace(content=text, tool_calls=tcs, annotations=annotations)
    choice = types.SimpleNamespace(message=message, finish_reason=finish_reason)
    u = types.SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1],
                              completion_tokens_details=types.SimpleNamespace(reasoning_tokens=usage[2]))
    return types.SimpleNamespace(choices=[choice], usage=u, model=model)


async def fake_acompletion(**kwargs):
    prompt = kwargs["messages"][0]["content"]
    label = _current_label(kwargs)
    if label.startswith("conf.error."):
        raise error_for(label[len("conf.error."):])
    if label == "conf.slow":
        await asyncio.sleep(5)
    if label == "conf.tool_calls":
        return response("", tool_calls=[("reply", '{"message": "hi"}'), ("broken", "{not json")], finish_reason="tool_calls")
    if label == "conf.length":
        return response("cut off mid-sen", finish_reason="length", usage=(6, 3, 0))
    if label == "conf.grounded":
        return response("grounded", annotations=[
            {"type": "url_citation", "url_citation": {"title": "Alpha", "url": "https://a.example"}},
            {"type": "url_citation", "url_citation": {"url": "https://b.example"}}])
    if label == "conf.json.plain":
        return response('{"a": 1}')
    if label == "conf.json.fenced":
        return response('```json\n{"a": 1}\n```')
    if label == "conf.json.list":
        return response('[{"a": 1}, {"a": 2}]')
    if label == "conf.json.invalid":
        return response("this is not json")
    if label == "conf.reasoning":
        return response("thought about it", usage=(120, 81, 80), model="gemini-2.5-pro")
    return response(prompt)          # conf.echo and anything else: the prompt text as received


# The executor never passes call_label to litellm, so the fake reads it from a
# ContextVar set by a thin wrapper around the executor's own service.execute
# (per request, so concurrent requests never see each other's label).
_LABEL = contextvars.ContextVar("conformance_label", default="conf.echo")


def _current_label(kwargs):
    return _LABEL.get()


def install():
    import executor.routes as routes
    import executor.service as service
    original = service.execute

    async def execute_with_label(b, kwargs):
        _LABEL.set(b.call_label)
        return await original(b, kwargs)

    service.execute = execute_with_label
    routes.execute = execute_with_label
    litellm.acompletion = fake_acompletion


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    args = ap.parse_args()
    if not os.environ.get("KERNEL_AUTH_TOKEN"):
        sys.exit("KERNEL_AUTH_TOKEN is not set")
    install()
    import uvicorn
    import main
    uvicorn.run(main.app, host="127.0.0.1", port=args.port, log_level="warning")
