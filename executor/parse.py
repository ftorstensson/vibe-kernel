"""
Parse modes (docs/m0/C1 section 4.3). Parsing only fills output.parsed; it
never changes what was sent to the model and never triggers a second call.
The lenient mode is core/kernel_utils.parse_json_lenient, copied rather than
imported so the executor has no dependency on legacy code (T9 keeps the two
identical until the legacy copy is deleted at M4).
"""
import json
import re


def parse_json_lenient(raw_text):
    clean_json = re.sub(r'^\`\`\`json\s*|\`\`\`$', '', raw_text.strip(), flags=re.MULTILINE).strip()
    parsed = json.loads(clean_json)
    if isinstance(parsed, list):
        return parsed[0] if parsed else {}
    return parsed


def _error_message(exc):
    # JSON errors describe a position, never the model's text. Anything else
    # (for example RecursionError on absurd nesting) is reported by class only.
    if isinstance(exc, json.JSONDecodeError):
        return str(exc)
    return f"{type(exc).__name__} while parsing"


def json_safe(value):
    """A value json.loads accepted but that cannot be sent back as valid JSON
    (NaN, Infinity, a float like 1e999) is a parse failure, not a crash."""
    try:
        json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    except (ValueError, RecursionError, UnicodeEncodeError):
        return False
    return True


def parse_output(parse_mode, text):
    """Returns (parsed, parse_error)."""
    if parse_mode == "text":
        return None, None
    try:
        if parse_mode == "json_strict":
            parsed = json.loads(text)
        else:
            parsed = parse_json_lenient(text)
    except Exception as exc:
        return None, _error_message(exc)
    if not json_safe(parsed):
        return None, "parsed value is not representable as JSON (NaN, Infinity or too deeply nested)"
    return parsed, None
