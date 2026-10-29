"""
execute(briefing): one Briefing in, one model call, one ExecutionResult out
(docs/m0/C1 section 4). Composes nothing, sequences nothing, retries nothing,
reads no file. Every Briefing that passed validation and the sha checks gets a
result with HTTP 200, whether the model succeeded or the provider failed, so
the failed call's sha, timing and error are never lost.
"""
import logging

import time

from executor import config, errors, links, supports
from executor.auth import configured_token
from executor.model import call_model, normalize
from executor.parse import parse_output
from executor.schema import Briefing

logger = logging.getLogger("uvicorn.error")


def _log_call(b, sent, status, duration_ms, usage, error_type, provider_status, raw_error_text, link_stats=None):
    """One line per call: identifiers, sha, sizes, duration, usage and outcome.
    Never the prompt, the output, tool arguments or a credential. Raw provider
    text appears ONLY here, scrubbed and capped (C1 4.4)."""
    parts = [
        "executor.call",
        f"attempt_id={b.attempt_id}",
        f"call_label={b.call_label}",
        f"prompt_sha256={sent.prompt_sha256}",
        f"prompt_utf8_bytes={sent.prompt_utf8_bytes}",
        f"duration_ms={duration_ms}",
        f"status={status}",
    ]
    if usage is not None:
        parts.append(f"usage={usage}")
    if link_stats is not None:
        parts.append(f"links_resolved={link_stats[0]}/{link_stats[1]} links_ms={link_stats[2]}")   # counts only, never a URL
    if error_type is not None:
        parts.append(f"error_type={error_type}")
        parts.append(f"provider_status={provider_status}")
        parts.append("provider_text=" + repr(errors.scrub_for_log(raw_error_text, b.prompt, (configured_token(),))))
    logger.info(" ".join(parts))


async def execute(b: Briefing, kwargs):
    sent, response, exception, duration_ms = await call_model(kwargs, b.timeout_s)

    result = {
        "contract_version": config.CONTRACT_VERSION,
        "attempt_id": b.attempt_id,
        "call_label": b.call_label,
        "status": None,
        "prompt_sha256": sent.prompt_sha256,
        "prompt_utf8_bytes": sent.prompt_utf8_bytes,
        "prompt_utf16_units": sent.prompt_utf16_units,
        "request_sha256": b.request_sha256,
        "output": None,
        "usage": None,
        "finish_reason": None,
        "effective_model": None,
        "error": None,
        "timing": {"started_at": sent.started_at, "duration_ms": duration_ms},
        "kernel": config.kernel_version(),
        "segments": b.segments,
    }

    error_type = provider_status = raw_error_text = None
    if exception is None:
        try:
            output, usage, finish_reason, effective_model = normalize(response)
            output["parsed"], output["parse_error"] = parse_output(b.parse_mode, output["text"])
        except Exception as exc:  # noqa: BLE001 -- a malformed provider response is a provider error
            exception = exc
        else:
            result.update(status="ok", output=output, usage=usage, finish_reason=finish_reason, effective_model=effective_model)
    if exception is not None:
        category, provider_status = errors.classify(exception)
        error_type, raw_error_text = category, f"{type(exception).__name__}: {exception}"
        result.update(status="error", error=errors.error_object(category, provider_status))

    link_stats = None
    if result["status"] == "ok":
        output = result["output"]
        wanted = supports.referenced_indices(output["grounding_supports"])
        if output["grounding_sources"] or wanted:
            # Not a model call and not part of timing.duration_ms (the model call only). One pass over
            # the sources, then the chunks some support points at (C1 4.5): the sources come first, so
            # the per-call cap treats them exactly as before. resolve_sources never raises and never
            # takes longer than links.TOTAL_TIMEOUT_S; a link it cannot resolve keeps its redirect.
            started = time.perf_counter()
            n_sources = len(output["grounding_sources"])
            answered = await links.resolve_sources(output["grounding_sources"] + [output["grounding_chunks"][i] for i in wanted])
            output["grounding_sources"] = answered[:n_sources]
            for i, chunk in zip(wanted, answered[n_sources:]):
                output["grounding_chunks"][i] = chunk
            resolved, total = links.summary(answered)
            link_stats = (resolved, total, int(round((time.perf_counter() - started) * 1000)))

    _log_call(b, sent, result["status"], duration_ms, result["usage"], error_type, provider_status, raw_error_text, link_stats)
    return result
