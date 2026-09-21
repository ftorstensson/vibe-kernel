"""
The Briefing (docs/m0/C1 section 2): request validation, the model-call
mapping (section 2.1) and the two sha256 rules (section 5).

Validation is hand-written rather than pydantic on purpose: the two hashes
depend on the exact JSON number kind (`60` and `60.0` hash differently), and
pydantic's coercions (int to float, bool to int) would silently change what is
hashed and sent. Every check here is `type(x) is ...`, never `isinstance`.

Nothing in this module reads a file, an environment variable other than through
executor.config, or any state. It composes nothing: `prompt` is one string and
becomes the one user message unchanged.
"""
import hashlib
import json
import re
from dataclasses import dataclass

from executor import config

_HEX64 = re.compile(r"[0-9a-f]{64}")
_PRINTABLE_ASCII = re.compile(r"[\x20-\x7e]{1,128}")
REASONING_EFFORTS = ("disable", "minimal", "low", "medium", "high", "none")
TOOL_CHOICES = ("auto", "required", "none")
PARSE_MODES = ("text", "json_strict", "json_lenient")

# Order matters: it is the order errors are reported in (first failure wins).
FIELDS = (
    "contract_version", "attempt_id", "call_label", "prompt", "prompt_sha256",
    "request_sha256", "model", "temperature", "reasoning_effort", "max_output_tokens",
    "tools", "tool_choice", "response_format", "parse_mode", "timeout_s", "segments",
)


class BriefingError(Exception):
    """A contract violation: HTTP 422, zero model calls. `code` says why,
    `field` says where, `extra` carries the sha diagnostics."""

    def __init__(self, code, field=None, extra=None):
        super().__init__(code)
        self.code = code
        self.field = field
        self.extra = extra or {}

    def body(self):
        error = {"type": "invalid_briefing", "code": self.code, "field": self.field}
        error.update(self.extra)
        return {"error": error}


@dataclass(frozen=True)
class Briefing:
    contract_version: int
    attempt_id: str
    call_label: str
    prompt: str
    prompt_sha256: str
    request_sha256: str
    model: str
    temperature: object
    reasoning_effort: object
    max_output_tokens: object
    tools: object
    tool_choice: object
    response_format: object
    parse_mode: str
    timeout_s: object
    segments: list


def _is_int(value):
    return type(value) is int


def _is_number(value):
    return type(value) is int or type(value) is float


def _function_tool_ok(tool):
    if set(tool) != {"type", "function"} or tool["type"] != "function":
        return False
    function = tool["function"]
    if type(function) is not dict:
        return False
    if not {"name", "parameters"} <= set(function) or not set(function) <= {"name", "description", "parameters"}:
        return False
    if type(function["name"]) is not str or not function["name"]:
        return False
    if "description" in function and type(function["description"]) is not str:
        return False
    return type(function["parameters"]) is dict


def _tool_ok(tool):
    """Allowlist: an OpenAI-style function tool, or the provider-native
    grounding tool {"googleSearch": {}}. Kernel never interprets, runs or loops
    on a tool."""
    if type(tool) is not dict:
        return False
    if set(tool) == {"googleSearch"}:
        return tool["googleSearch"] == {} and type(tool["googleSearch"]) is dict
    return _function_tool_ok(tool)


def canonical_json(value):
    """The one serialization both sides hash (C1 5.2). ensure_ascii=False so
    non-ASCII text hashes as itself; allow_nan=False so a non-finite number is
    an error, not `Infinity`."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def prompt_sha256(prompt):
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def utf16_units(text):
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def request_sha256(kwargs):
    """sha256 of the canonical JSON of every litellm parameter EXCEPT messages
    (covered by prompt_sha256) and vertex_project/vertex_location (Kernel
    configuration). Computed from the kwargs actually handed to litellm."""
    params = {k: v for k, v in kwargs.items() if k not in ("messages", "vertex_project", "vertex_location")}
    return hashlib.sha256(canonical_json(params)).hexdigest()


def build_kwargs(b):
    """C1 2.1 -- the entire mapping from a Briefing to the model call. Every
    optional key is set iff its Briefing field is non-null, and
    messages[0]["content"] is the Briefing's prompt string itself."""
    kwargs = {
        "model": b.model,
        "messages": [{"role": "user", "content": b.prompt}],
        "vertex_project": config.project_id(),
        "vertex_location": config.LOCATION,
        "timeout": b.timeout_s,
    }
    if b.temperature is not None:
        kwargs["temperature"] = b.temperature
    if b.reasoning_effort is not None:
        kwargs["reasoning_effort"] = b.reasoning_effort
    if b.max_output_tokens is not None:
        kwargs["max_tokens"] = b.max_output_tokens
    if b.tools is not None:
        kwargs["tools"] = b.tools
    if b.tool_choice is not None:
        kwargs["tool_choice"] = b.tool_choice
    if b.response_format is not None:
        kwargs["response_format"] = b.response_format
    return kwargs


def parse_body(raw):
    """Bytes to a Python object. Strict: valid UTF-8, no duplicate keys, no NaN
    or Infinity literals. Raises BriefingError(invalid_json)."""
    def no_duplicates(pairs):
        keys = [k for k, _ in pairs]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate key")
        return dict(pairs)

    def no_constants(name):
        raise ValueError("non-finite number")

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates, parse_constant=no_constants)
    except (ValueError, RecursionError):
        raise BriefingError("invalid_json")


def validate(obj):
    """Validates a parsed JSON value and returns a Briefing, or raises
    BriefingError. Does NOT check the shas (see verify_shas)."""
    if type(obj) is not dict:
        raise BriefingError("not_an_object")
    for key in obj:
        if key not in FIELDS:
            raise BriefingError("unknown_field", key if len(str(key)) <= 64 else None)
    for key in FIELDS:
        if key not in obj:
            raise BriefingError("missing_field", key)

    if not _is_int(obj["contract_version"]) or obj["contract_version"] != config.CONTRACT_VERSION:
        raise BriefingError("invalid_value", "contract_version")
    for key in ("attempt_id", "call_label"):
        if type(obj[key]) is not str or not _PRINTABLE_ASCII.fullmatch(obj[key]):
            raise BriefingError("invalid_format", key)

    prompt = obj["prompt"]
    if type(prompt) is not str:
        raise BriefingError("invalid_type", "prompt")
    if len(prompt) > config.MAX_PROMPT_BYTES:
        raise BriefingError("too_large", "prompt")
    try:
        encoded = prompt.encode("utf-8")
    except UnicodeEncodeError:
        raise BriefingError("invalid_prompt", "prompt")
    if len(encoded) < 1:
        raise BriefingError("out_of_range", "prompt")
    if len(encoded) > config.MAX_PROMPT_BYTES:
        raise BriefingError("too_large", "prompt")

    for key in ("prompt_sha256", "request_sha256"):
        if type(obj[key]) is not str or not _HEX64.fullmatch(obj[key]):
            raise BriefingError("invalid_format", key)

    if type(obj["model"]) is not str:
        raise BriefingError("invalid_type", "model")
    if obj["model"] not in config.ALLOWED_MODELS:
        raise BriefingError("not_allowed", "model")

    temperature = obj["temperature"]
    if temperature is not None:
        if not _is_number(temperature):
            raise BriefingError("invalid_type", "temperature")
        if not 0 <= temperature <= 2:
            raise BriefingError("out_of_range", "temperature")

    effort = obj["reasoning_effort"]
    if effort is not None and (type(effort) is not str or effort not in REASONING_EFFORTS):
        raise BriefingError("invalid_value", "reasoning_effort")

    max_tokens = obj["max_output_tokens"]
    if max_tokens is not None:
        if not _is_int(max_tokens):
            raise BriefingError("invalid_type", "max_output_tokens")
        if max_tokens < 1:
            raise BriefingError("out_of_range", "max_output_tokens")

    tools = obj["tools"]
    if tools is not None:
        if type(tools) is not list:
            raise BriefingError("invalid_type", "tools")
        if not tools:
            raise BriefingError("out_of_range", "tools")
        if not all(_tool_ok(t) for t in tools):
            raise BriefingError("not_allowed", "tools")

    choice = obj["tool_choice"]
    if choice is not None and (type(choice) is not str or choice not in TOOL_CHOICES):
        raise BriefingError("invalid_value", "tool_choice")

    if obj["response_format"] is not None and type(obj["response_format"]) is not dict:
        raise BriefingError("invalid_type", "response_format")

    if type(obj["parse_mode"]) is not str or obj["parse_mode"] not in PARSE_MODES:
        raise BriefingError("invalid_value", "parse_mode")

    timeout = obj["timeout_s"]
    if not _is_number(timeout):
        raise BriefingError("invalid_type", "timeout_s")
    if not 1 <= timeout <= config.MAX_TIMEOUT_S:
        raise BriefingError("out_of_range", "timeout_s")

    segments = obj["segments"]
    if type(segments) is not list:
        raise BriefingError("invalid_type", "segments")
    if len(segments) > config.MAX_SEGMENTS:
        raise BriefingError("too_large", "segments")
    if not all(type(s) is dict for s in segments):
        raise BriefingError("invalid_type", "segments")

    # Everything except the prompt must serialize to UTF-8 and to valid JSON
    # (a lone surrogate or a 1e999 would otherwise crash the response).
    try:
        segments_bytes = len(json.dumps(segments, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8"))
        rest = {k: obj[k] for k in ("tools", "response_format", "attempt_id", "call_label")}
        json.dumps(rest, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeEncodeError, RecursionError):
        raise BriefingError("invalid_text", None)
    if segments_bytes > config.MAX_SEGMENTS_BYTES:
        raise BriefingError("too_large", "segments")

    return Briefing(**{k: obj[k] for k in FIELDS})


def verify_shas(b):
    """The pre-call check (C1 5.1): the shas Backend saved must equal what
    Kernel computes from what it received. Order: prompt, then the rest.
    Returns the kwargs to send; raises BriefingError (HTTP 422, zero model
    calls) on a mismatch."""
    computed = prompt_sha256(b.prompt)
    if computed != b.prompt_sha256:
        raise BriefingError("prompt_sha_mismatch", "prompt_sha256", {
            "computed_sha256": computed,
            "prompt_utf8_bytes": len(b.prompt.encode("utf-8")),
            "prompt_utf16_units": utf16_units(b.prompt),
        })
    kwargs = build_kwargs(b)
    try:
        computed_request = request_sha256(kwargs)
    except (ValueError, UnicodeEncodeError, RecursionError):
        raise BriefingError("invalid_text", None)
    if computed_request != b.request_sha256:
        raise BriefingError("request_sha_mismatch", "request_sha256", {"computed_sha256": computed_request})
    return kwargs
