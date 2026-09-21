import json
import os
from dotenv import load_dotenv
import litellm

from core.capture import current_capture
from core.prompt_builder import AssembledPrompt

load_dotenv()

# Regional Physics (Advisor Mandate)
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "vibe-agent-final")
LOCATION = "us-central1"


class GenerationConfig:
    def __init__(self, temperature=0.0, reasoning_effort=None):
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort


class LiteLLMResponse:
    """Normalizes a litellm ModelResponse to what get_clean_text() and Hound
    expect. tool_calls (real Gemini native function-calling, for
    run_global_turn's start_milestone_work -- see pods/social/engine.py)
    is the one new piece: litellm's own message.tool_calls, each a
    {function: {name, arguments}} object with arguments as a JSON string
    (confirmed empirically against a real Vertex/Gemini 2.5 Pro call, not
    assumed) -- parsed here into plain {name, args: dict} entries so
    nothing downstream (Kernel's own code, or Backend reading
    SovereignResponse.tool_call) ever touches raw JSON-in-a-string.
    text and tool_calls are NOT mutually exclusive -- the same real test
    call returned a genuine acknowledgment string AND a real tool call
    together, so both are always populated from what the model actually
    returned, never one at the expense of the other.

    A single malformed tool call (arguments that don't parse as JSON) is
    dropped, not allowed to crash the whole turn -- same fail-open
    principle as everywhere else a real external response gets parsed in
    this codebase; the rest of a normal, non-tool-calling turn should
    never be at risk because of it."""
    def __init__(self, litellm_response):
        message = litellm_response.choices[0].message
        self.text = message.content or ""
        usage = getattr(litellm_response, "usage", None)
        self.usage = None if usage is None else {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        }
        self.grounding_sources = []
        for annotation in (getattr(message, "annotations", None) or []):
            if annotation.get("type") == "url_citation":
                citation = annotation.get("url_citation", {})
                self.grounding_sources.append({
                    "title": citation.get("title") or "Source",
                    "url": citation.get("url"),
                })
        self.tool_calls = []
        for tool_call in (getattr(message, "tool_calls", None) or []):
            try:
                args = json.loads(tool_call.function.arguments)
            except (TypeError, ValueError):
                continue
            self.tool_calls.append({"name": tool_call.function.name, "args": args})


def _assembled_prompt(prompt):
    """The AssembledPrompt (segments source) behind a prompt argument, which
    callers pass either bare or as a one-element list -- None for raw
    f-string sites, which get no segments."""
    if isinstance(prompt, AssembledPrompt):
        return prompt
    if isinstance(prompt, (list, tuple)) and len(prompt) == 1 and isinstance(prompt[0], AssembledPrompt):
        return prompt[0]
    return None


class LiteLLMModel:
    def __init__(self, model_name, tools=None):
        self.model_name = model_name
        self.tools = tools

    def build_request(self, prompt, generation_config=None, response_schema=None, tools=None, tool_choice=None):
        """The one place litellm's kwargs are built -- pure (no I/O, no model
        call), and exactly what generate_content sends, so a capture of it
        is the real input, not a second copy."""
        content = prompt if isinstance(prompt, str) else "\n".join(str(p) for p in prompt)
        kwargs = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": str(content)}],
            "vertex_project": PROJECT_ID,
            "vertex_location": LOCATION,
        }
        if generation_config is not None:
            kwargs["temperature"] = generation_config.temperature
            if generation_config.reasoning_effort:
                kwargs["reasoning_effort"] = generation_config.reasoning_effort
        effective_tools = tools or self.tools
        if effective_tools:
            kwargs["tools"] = effective_tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if response_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "structured_output", "schema": response_schema, "strict": True},
            }
        return kwargs

    def generate_content(self, prompt, generation_config=None, response_schema=None, tools=None, tool_choice=None, label=None, meta=None):
        """label/meta (Step 0 capture, core/capture.py): a stable call-site id
        and an optional disambiguator, used only when the request opted into
        capture -- they never reach litellm.

        tools (per-call) lets one shared model config (e.g.
        AgentFactory.get_partner_pm(), used by both run_turn and
        run_global_turn) offer a real tool on only SOME calls -- run_turn
        never passes this, run_global_turn does, without needing a second
        factory method just to carry a different fixed tools list.
        Overrides self.tools (construction-time, used by get_hound's
        Google Search grounding) rather than merging with it -- no
        current caller needs both at once, and merging silently would
        make it easy to accidentally combine two unrelated tool sets.

        tool_choice (Phase 2a, core/orchestrator_answer.py): optional,
        None by default so every existing caller is byte-identical to
        before this parameter existed. "required" maps to Gemini's real
        FunctionCallingConfig mode=ANY via litellm's own Vertex adapter
        (confirmed against its source) -- forces the model to call one of
        the offered tools rather than silently returning plain text with
        none. Not parallel_tool_calls -- that param is a real no-op for
        Gemini via litellm once more than one tool is declared, confirmed
        against the same adapter source and empirically against the real
        API -- see core/orchestrator_answer.py's own module docstring for
        the full trace of why tool_choice="required" is used instead."""
        request = self.build_request(prompt, generation_config, response_schema, tools, tool_choice)
        capture = current_capture()
        call = capture.begin(label, meta, request, _assembled_prompt(prompt)) if capture is not None else None
        try:
            response = LiteLLMResponse(litellm.completion(**request))
        except Exception as exc:
            if call is not None:
                capture.fail(call, exc)
            raise
        if call is not None:
            capture.finish(call, response)
        return response


class AgentFactory:
    @staticmethod
    def get_clerk():
        """IQ: 0.0 - Extraction (Gemini 2.5 Flash via LiteLLM)"""
        return LiteLLMModel("vertex_ai/gemini-2.5-flash"), GenerationConfig(temperature=0.0, reasoning_effort="disable")

    @staticmethod
    def get_partner_pm():
        """EQ: 0.4 - Social PM (Gemini 2.5 Pro via LiteLLM)"""
        return LiteLLMModel("vertex_ai/gemini-2.5-pro"), GenerationConfig(temperature=0.4, reasoning_effort="minimal")

    @staticmethod
    def get_hound():
        """IQ: 0.1 - Grounded Specialist (Gemini 2.5 Flash via LiteLLM, Google Search grounding)"""
        return LiteLLMModel(
            "vertex_ai/gemini-2.5-flash",
            tools=[{"googleSearch": {}}]
        ), GenerationConfig(temperature=0.1)

    @staticmethod
    def get_clinical_auditor():
        """IQ: 0.0 - The Deadbolt (Gemini 2.5 Flash via LiteLLM)"""
        return LiteLLMModel("vertex_ai/gemini-2.5-flash"), GenerationConfig(temperature=0.0)

    @staticmethod
    def get_summarizer():
        """IQ: 0.0 - Condensation (Gemini 2.5 Flash via LiteLLM). Accurate
        condensation, not creative work -- same tier and thinking bound as
        the Clerk."""
        return LiteLLMModel("vertex_ai/gemini-2.5-flash"), GenerationConfig(temperature=0.0, reasoning_effort="disable")
