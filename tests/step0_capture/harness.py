"""
Step 0 golden harness (doc-26): records the exact kwargs handed to
litellm.completion for every Kernel model-call site, from a given commit of
the code, using a fake litellm.completion. No model is ever called.

What is compared is INPUT only (messages/tools/tool_choice/response_format/
temperature/reasoning_effort/vertex settings) -- model output is canned by
this harness, so it is not part of the proof.
"""
import copy
import json
import os
import sys
import uuid
from contextlib import contextmanager
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import core.agent_factory as agent_factory  # noqa: E402


class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, name, arguments):
        self.function = _Fn(name, json.dumps(arguments))


class _Message:
    def __init__(self, content, tool_calls=None, annotations=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.annotations = annotations or []


class _Choice:
    def __init__(self, message):
        self.message = message


class _Usage:
    prompt_tokens = 11
    completion_tokens = 7


class _Response:
    def __init__(self, message, usage=_Usage):
        self.choices = [_Choice(message)]
        if usage is not None:
            self.usage = usage


def _schema_props(kwargs):
    rf = kwargs.get("response_format")
    if not rf:
        return None
    return (rf.get("json_schema") or {}).get("schema", {}).get("properties", {})


DEFAULT_RESPONSES = {
    "coverage": {"assessments": [{"question": "q1", "status": "RED", "is_satisfied": False}], "gate_status": "RED", "whisper": "canned gatekeeper whisper"},
    "ignition": {"confirmed": True},
    "requirements": {"rationale": "canned rationale", "ignition_inputs": [{"question": "canned q", "why_irreplaceable": "canned why"}]},
    "reconcile": {"classification": "new", "matched_fact_id": None, "merged_content": None, "needs_confirmation": False, "clarifying_question": None},
    "extraction": {"items": [
        {"content": "canned fact one", "type": "fact", "speaker": "user", "turn_index": 0, "bucket": "Core Topic", "resolution_status": "settled"},
        {"content": "canned fact two", "type": "decision", "speaker": "user", "turn_index": 1, "bucket": "Sub Topics", "resolution_status": "unresolved"},
    ]},
    "brief": {"identity_narrative": "canned narrative paragraph one.\n\ncanned paragraph two.", "founding_voice": ["canned quote a", "canned quote b"]},
    "questions": {"questions": ["canned question 1", "canned question 2", "canned question 3"]},
}


def _kind(props):
    if props is None:
        return None
    if "gate_status" in props:
        return "coverage"
    if "confirmed" in props:
        return "ignition"
    if "ignition_inputs" in props:
        return "requirements"
    if "classification" in props:
        return "reconcile"
    if "items" in props:
        return "extraction"
    if "identity_narrative" in props:
        return "brief"
    if "questions" in props:
        return "questions"
    return "synthesis"


class Recorder:
    def __init__(self, responses=None):
        self.requests = []
        self.responses = copy.deepcopy(DEFAULT_RESPONSES)
        if responses:
            self.responses.update(copy.deepcopy(responses))

    def fake_completion(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        props = _schema_props(kwargs)
        kind = _kind(props)
        if kind == "synthesis":
            return _Response(_Message(json.dumps({p: f"canned synthesized text for {p}" for p in props})))
        if kind is not None:
            return _Response(_Message(json.dumps(self.responses[kind])))
        tools = kwargs.get("tools") or []
        if "EDITOR-IN-CHIEF" in kwargs["messages"][0]["content"]:
            return _Response(_Message("{}"))
        if kwargs.get("tool_choice") == "required" and tools:
            name = tools[0]["function"]["name"]
            params = tools[0]["function"]["parameters"]
            args = {k: f"canned {k}" for k in params.get("required", [])}
            return _Response(_Message("", tool_calls=[_ToolCall(name, args)]))
        if tools and tools[0] == {"googleSearch": {}}:
            return _Response(_Message(
                "canned grounded research text",
                annotations=[{"type": "url_citation", "url_citation": {"title": "Canned Source", "url": "https://example.com/canned"}}],
            ))
        return _Response(_Message("canned model text"))


def _deterministic_uuid():
    counter = {"n": 0}

    def fake_uuid4():
        counter["n"] += 1
        return uuid.UUID(int=counter["n"])

    return fake_uuid4


@contextmanager
def recording(responses=None):
    recorder = Recorder(responses)
    previous_cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        with patch.object(agent_factory.litellm, "completion", side_effect=recorder.fake_completion), \
             patch("uuid.uuid4", side_effect=_deterministic_uuid()):
            yield recorder
    finally:
        os.chdir(previous_cwd)


def detect_site(kwargs):
    """Identifies the call site from a recorded request, by fingerprints that
    exist in CURRENT main's prompts. Used only to prove every one of the 16
    sites is exercised by at least one scenario."""
    text = kwargs["messages"][0]["content"]
    tools = kwargs.get("tools") or []
    names = [t.get("function", {}).get("name") for t in tools if isinstance(t, dict)]
    if kwargs.get("tool_choice") == "required":
        return "pm.run_global_turn_answer"
    if "start_milestone_work" in names:
        return "pm.run_global_turn"
    if "[STATUS: " in text:
        return "pm.run_turn"
    if "SYNTHESIS TASK:" in text:
        return "pm.synthesize_dispatch"
    if "REQUIRED QUESTIONS (GATES)" in text:
        return "gatekeeper.assess_coverage"
    if "RECENT CONVERSATION (last message" in text:
        return "keymaster.confirm_launch_intent"
    if "TARGET OUTPUT STRUCTURE" in text:
        return "gate_maker.derive_requirements"
    if "CONVERSATION (numbered)" in text:
        return "chat_manager.extract_facts"
    if "fact-reconciliation function" in text:
        return "chat_manager.reconcile_fact"
    if "brief-writing function" in text:
        return "strike.derive_brief"
    if "TEXT TO SUMMARIZE" in text:
        return "map_summary.summarize_for_map"
    if "EDITOR-IN-CHIEF" in text:
        return "synthesis.forge_truth"
    if "KERNEL MAINTENANCE JANITOR" in text:
        return "maintenance.compress_truth"
    if "most critical, specific" in text:
        return "strike.specialist_questions"
    if "AVAILABLE_SOURCE_IDS" in text:
        return "strike.specialist_analyze"
    if "TASK: Find evidence for" in text:
        return "strike.hound"
    if "BLOCK 1: THE MANDATE" in text and "TOOL LAW:" in text:
        return "pm.run_global_turn"
    return "unknown"


ALL_SITES = [
    "pm.run_turn", "pm.run_global_turn", "pm.run_global_turn_answer", "pm.synthesize_dispatch",
    "gatekeeper.assess_coverage", "keymaster.confirm_launch_intent", "gate_maker.derive_requirements",
    "chat_manager.extract_facts", "chat_manager.reconcile_fact", "strike.derive_brief",
    "map_summary.summarize_for_map", "synthesis.forge_truth", "strike.specialist_questions",
    "strike.specialist_analyze", "strike.hound", "maintenance.compress_truth",
]


def dumps(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False)
