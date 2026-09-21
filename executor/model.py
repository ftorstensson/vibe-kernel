"""
The executor's single choke point: the ONE place litellm is called.

`call_model` hashes the exact string it is about to hand to litellm as
messages[0]["content"] and calls litellm once, with no retry, repair or
re-ask. The hash and the call use the same string object; there is no code
path between them. Nothing else in the executor calls litellm.

This is a new async function, not core/agent_factory.py's synchronous
LiteLLMModel.generate_content, which stays untouched for the legacy routes until
M4: generate_content is synchronous (it would block the event loop and
serialize requests, measured in docs/m0/K1 section 5) and is coupled to legacy
modules (capture, prompt_builder) the executor must not import.
"""
import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone

import litellm

from executor.schema import utf16_units


class Sent:
    """What was actually handed to litellm, measured at the choke point."""
    __slots__ = ("prompt_sha256", "prompt_utf8_bytes", "prompt_utf16_units", "started_at")


async def call_model(kwargs, timeout_s):
    """One model call. Returns (sent, response, exception, duration_ms): exactly
    one of response / exception is not None. asyncio.CancelledError (the client
    went away) is never swallowed."""
    content = kwargs["messages"][0]["content"]
    encoded = content.encode("utf-8")
    sent = Sent()
    sent.prompt_sha256 = hashlib.sha256(encoded).hexdigest()
    sent.prompt_utf8_bytes = len(encoded)
    sent.prompt_utf16_units = utf16_units(content)
    sent.started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    started = time.perf_counter()
    response = exception = None
    try:
        response = await asyncio.wait_for(litellm.acompletion(**kwargs), timeout=timeout_s)
    except Exception as exc:  # noqa: BLE001 -- classified by executor.errors.classify
        exception = exc
    duration_ms = int(round((time.perf_counter() - started) * 1000))
    return sent, response, exception, duration_ms


def _tool_call(raw):
    """One provider tool call as {name, args, arguments_raw, parse_error}. A
    malformed call is kept and reported, never dropped (C1 flag F7)."""
    function = getattr(raw, "function", None)
    name = getattr(function, "name", None)
    arguments = getattr(function, "arguments", None)
    if arguments is None:
        arguments_raw = ""
    elif isinstance(arguments, str):
        arguments_raw = arguments
    else:
        try:
            arguments_raw = json.dumps(arguments, ensure_ascii=False)
        except (TypeError, ValueError):
            arguments_raw = str(arguments)
    args, parse_error = None, None
    try:
        parsed = json.loads(arguments_raw)
        if not isinstance(parsed, dict):
            parse_error = "arguments are not a JSON object"
        else:
            json.dumps(parsed, allow_nan=False, ensure_ascii=False).encode("utf-8")
            args = parsed
    except json.JSONDecodeError as exc:
        parse_error = str(exc)
    except (ValueError, RecursionError, UnicodeEncodeError):
        parse_error = "arguments are not representable as JSON"
    return {"name": name, "args": args, "arguments_raw": arguments_raw, "parse_error": parse_error}


def normalize(response):
    """A litellm ModelResponse to (output_without_parse, usage, finish_reason,
    effective_model). Defensive: every provider field may be missing."""
    choice = response.choices[0]
    message = choice.message
    text = getattr(message, "content", None) or ""

    grounding_sources = []
    for annotation in (getattr(message, "annotations", None) or []):
        if annotation.get("type") == "url_citation":
            citation = annotation.get("url_citation", {})
            grounding_sources.append({"title": citation.get("title") or "Source", "url": citation.get("url")})

    tool_calls = [_tool_call(tc) for tc in (getattr(message, "tool_calls", None) or [])]

    usage = None
    raw_usage = getattr(response, "usage", None)
    if raw_usage is not None:
        details = getattr(raw_usage, "completion_tokens_details", None)
        usage = {
            "prompt_tokens": getattr(raw_usage, "prompt_tokens", None),
            "completion_tokens": getattr(raw_usage, "completion_tokens", None),
            "reasoning_tokens": getattr(details, "reasoning_tokens", None) if details is not None else None,
        }

    output = {"text": text, "tool_calls": tool_calls, "grounding_sources": grounding_sources}
    return output, usage, getattr(choice, "finish_reason", None), getattr(response, "model", None)

