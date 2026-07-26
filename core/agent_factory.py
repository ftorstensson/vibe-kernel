import os
from dotenv import load_dotenv
import litellm

load_dotenv()

# Regional Physics (Advisor Mandate)
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "vibe-agent-final")
LOCATION = "us-central1"


class GenerationConfig:
    def __init__(self, temperature=0.0, reasoning_effort=None):
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort


class LiteLLMResponse:
    """Normalizes a litellm ModelResponse to what get_clean_text() and Hound expect."""
    def __init__(self, litellm_response):
        message = litellm_response.choices[0].message
        self.text = message.content or ""
        self.grounding_sources = []
        for annotation in (getattr(message, "annotations", None) or []):
            if annotation.get("type") == "url_citation":
                citation = annotation.get("url_citation", {})
                self.grounding_sources.append({
                    "title": citation.get("title") or "Source",
                    "url": citation.get("url"),
                })


class LiteLLMModel:
    def __init__(self, model_name, tools=None):
        self.model_name = model_name
        self.tools = tools

    def generate_content(self, prompt, generation_config=None, response_schema=None):
        content = prompt if isinstance(prompt, str) else "\n".join(str(p) for p in prompt)
        kwargs = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": content}],
            "vertex_project": PROJECT_ID,
            "vertex_location": LOCATION,
        }
        if generation_config is not None:
            kwargs["temperature"] = generation_config.temperature
            if generation_config.reasoning_effort:
                kwargs["reasoning_effort"] = generation_config.reasoning_effort
        if self.tools:
            kwargs["tools"] = self.tools
        if response_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "structured_output", "schema": response_schema, "strict": True},
            }
        response = litellm.completion(**kwargs)
        return LiteLLMResponse(response)


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
