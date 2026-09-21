"""
Interim shared-secret gate for the executor routes (docs/m0/K1 section 4).

Fail closed: an unset, empty, too-short or non-visible-ASCII KERNEL_AUTH_TOKEN
means EVERY request is refused, and the refusal is the same whether the header
is missing, wrong or the server is unconfigured, so a caller cannot tell which.
The presented value is compared exactly (no stripping) with hmac.compare_digest;
the configured value is stripped first because Secret Manager values often
carry a trailing newline. Neither value is ever logged or returned.
"""
import hmac
import os

from executor.config import AUTH_ENV, MIN_TOKEN_LENGTH


def _visible_ascii(value):
    return all(0x21 <= ord(ch) <= 0x7E for ch in value)


def configured_token():
    """The usable server token, or None when unset or invalid (fail closed)."""
    value = (os.environ.get(AUTH_ENV) or "").strip()
    if len(value) < MIN_TOKEN_LENGTH or not _visible_ascii(value):
        return None
    return value


def auth_configured():
    return configured_token() is not None


def authorized(presented):
    expected = configured_token()
    if expected is None or not presented:
        return False
    try:
        return hmac.compare_digest(presented.encode("latin-1"), expected.encode("utf-8"))
    except Exception:
        return False
