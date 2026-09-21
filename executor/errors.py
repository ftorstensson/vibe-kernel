"""
Provider errors (docs/m0/C1 section 4.4).

The response body carries only the error CATEGORY, the provider status code
and a FIXED GENERIC message per category, never any text from the provider or
the exception (the read API is unauthenticated until after the core, and a
provider not-found error echoes the GCP project path). The raw provider text
goes only to Kernel's own log line, scrubbed by scrub_for_log().
"""
import asyncio
import re

import litellm

from executor import config

# category -> (retryable, fixed generic message). The wording is part of the
# contract: Backend may match on `type`, never on `message`.
CATEGORIES = {
    "timeout": (True, "The model call timed out."),
    "model_not_found": (False, "The requested model was not found."),
    "bad_request": (False, "The provider rejected the request as invalid."),
    "rate_limited": (True, "The provider rate limit was reached."),
    "provider_unavailable": (True, "The provider was unavailable."),
    "context_too_long": (False, "The prompt is longer than the model accepts."),
    "content_blocked": (False, "The provider blocked the request for policy reasons."),
    "provider_auth": (False, "Kernel's credentials or permissions were refused by the provider."),
    "provider_error": (None, "The provider returned an error."),
}

# Subclasses first: in litellm, ContextWindowExceededError and
# ContentPolicyViolationError are BadRequestErrors, and Timeout is an
# APITimeoutError / APIConnectionError. Names are looked up defensively (a
# litellm release that renames or drops one must not stop Kernel from
# starting: requirements.txt does not pin litellm); a missing class simply
# falls through to the next rule and finally to provider_error.
_ORDERED_NAMES = (
    ("Timeout", "timeout"),
    ("ContextWindowExceededError", "context_too_long"),
    ("ContentPolicyViolationError", "content_blocked"),
    ("NotFoundError", "model_not_found"),
    ("BadRequestError", "bad_request"),
    ("RateLimitError", "rate_limited"),
    ("AuthenticationError", "provider_auth"),
    ("PermissionDeniedError", "provider_auth"),
    ("ServiceUnavailableError", "provider_unavailable"),
    ("InternalServerError", "provider_unavailable"),
    ("BadGatewayError", "provider_unavailable"),
    ("APIConnectionError", "provider_unavailable"),
)
_ORDERED = tuple((cls, category) for name, category in _ORDERED_NAMES
                 if isinstance(cls := getattr(litellm.exceptions, name, None), type))


_GENERIC_STATUS = {
    401: "provider_auth", 403: "provider_auth", 404: "model_not_found", 408: "timeout", 429: "rate_limited",
    500: "provider_unavailable", 502: "provider_unavailable", 503: "provider_unavailable", 504: "provider_unavailable",
}


def classify(exc):
    """(category, provider_status) for an exception raised by the model call."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout", None  # Kernel's own wall-clock limit fired
    status = getattr(exc, "status_code", None)
    if type(status) is not int:
        status = None
    category = "provider_error"
    for cls, matched in _ORDERED:
        if isinstance(exc, cls):
            category = matched
            break
    # The class is not always specific: real Vertex answers a 403 (permission
    # denied on the project) as a litellm.BadRequestError, observed 2026-09-21.
    # For the two generic categories the provider's own status decides.
    if category in ("bad_request", "provider_error") and status in _GENERIC_STATUS:
        category = _GENERIC_STATUS[status]
    return category, status


def error_object(category, provider_status):
    retryable, message = CATEGORIES[category]
    return {"type": category, "retryable": retryable, "provider_status": provider_status, "message": message}


# --------------------------------------------------------------- log scrubbing
_CREDENTIAL_PATTERNS = (
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.S), "[redacted-key]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.I), "Bearer [redacted]"),
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), "[redacted-key]"),
    (re.compile(r"ya29\.[0-9A-Za-z._-]+"), "[redacted-token]"),
    (re.compile(r"eyJ[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+"), "[redacted-jwt]"),
    (re.compile(r"projects/[^/\s\"']+"), "projects/[redacted]"),
)
_MIN_ECHO = 20


def _redact_prompt_echoes(text, prompt):
    """Removes every stretch of `text` that is a 20-character-or-longer piece of
    `prompt`. Exact at stride 1 up to 256 KiB of prompt; above that the scan
    steps by 4 characters (an echo of 24 or more characters is still found),
    to bound the cost of an error on a very large prompt."""
    if not prompt or len(text) < _MIN_ECHO:
        return text
    stride = 1 if len(prompt) <= 256 * 1024 else 4
    spans = []
    for i in range(0, len(text) - _MIN_ECHO + 1, stride):
        if text[i:i + _MIN_ECHO] in prompt:
            spans.append([i, i + _MIN_ECHO])
    if not spans:
        return text
    merged = [spans[0]]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out, cursor = [], 0
    for start, end in merged:
        out.append(text[cursor:start])
        out.append("[redacted-prompt]")
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def scrub_for_log(text, prompt="", secrets=()):
    """The raw provider text as it may appear in Kernel's own log: capped,
    with prompt echoes, the Kernel auth token and credential shapes removed."""
    text = str(text)[: config.LOG_PROVIDER_TEXT_CAP]
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted-secret]")
    text = _redact_prompt_echoes(text, prompt)
    for pattern, replacement in _CREDENTIAL_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
