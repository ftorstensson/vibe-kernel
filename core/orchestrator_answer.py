"""
Phase 2a (doc-16): the Orchestrator's Answer as a real structured choice --
Reply | Dispatch | Completion -- modeled as native tool calls, not one JSON
schema with a discriminator field (Vertex/Gemini can't reliably do true
unions in structured output).

Additive only, standalone -- not wired into pods/social/engine.py's real
run_turn()/run_global_turn() yet. Those keep working unchanged; this module
exists to be called from a NEW path once the wire contract with Backend is
agreed (see this session's own coordination on the allowed_actions
question).

parallel_tool_calls=False, doc-16's own cited mechanism for preventing a
model from emitting a handoff and a reply at once, does NOT work for
Gemini via litellm once more than one tool is declared -- confirmed
against litellm's real Vertex/Gemini adapter source (llms/vertex_ai/gemini/
vertex_and_google_ai_studio_gemini.py): the param is either rejected
(UnsupportedParamsError) or, on the code path that actually runs, silently
dropped and never sent to Gemini at all. Verified empirically too, not
just read about: 3 real Gemini 2.5 Flash calls with three tools declared
(reply/dispatch/completion) and parallel_tool_calls=False all returned
exactly one clean tool call with zero accompanying prose content --
Gemini's own natural behavior already resolves the ambiguity once Reply
itself is a real tool (the old text+tool_call-together problem existed
specifically because Reply wasn't a tool, so it manifested as bonus prose
alongside whatever real tool got called). Not a hard API guarantee though,
so this module still defends against a multi-tool-call response instead of
assuming it can never happen.

Used instead: tool_choice="required" (maps to Gemini's real
FunctionCallingConfig mode=ANY -- confirmed against the same litellm
source), guaranteeing the model always picks one of the offered actions
rather than silently producing neither. Combined with a defensive
first-tool-call fallback, matching pods/social/engine.py's own existing
precedent in run_global_turn ("only the first tool call is ever used,
extras silently ignored... which real testing never actually produced" --
same fail-open principle, now written down as an actual guard instead of
an unenforced assumption).
"""

REPLY_TOOL = {
    "type": "function",
    "function": {
        "name": "reply",
        "description": (
            "Send a plain conversational reply. Use this for the overwhelming "
            "majority of turns -- responding, asking a question, continuing the "
            "conversation -- whenever you are not dispatching work to a "
            "milestone or signaling that this unit of work is complete."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The reply to send to the Director.",
                },
            },
            "required": ["message"],
        },
    },
}

COMPLETION_TOOL = {
    "type": "function",
    "function": {
        "name": "completion",
        "description": (
            "Signal that this unit of work is genuinely finished -- there is "
            "nothing further for you to do here, and whoever is waiting on "
            "this result should be told it's done. Only call this when the "
            "work is actually complete, never as a substitute for a plain "
            "reply or to end a conversation early."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "A short, real summary of what was accomplished, for whoever receives this completion.",
                },
            },
            "required": ["summary"],
        },
    },
}


# The real dispatch tool is pods/social/engine.py's own existing
# START_MILESTONE_WORK_TOOL (deliberately reused, not a new "dispatch"
# tool -- same underlying capability run_global_turn already offers, no
# reason for two different tool identities for one real action), whose
# own function name is "start_milestone_work", not "dispatch" -- doc-16's
# clean three-way vocabulary. Normalized here so answer_type is always
# exactly one of "reply"/"dispatch"/"completion" regardless of which
# underlying tool name actually produced it -- callers get a stable
# discriminator, not an implementation detail that would silently change
# if the real tool were ever renamed or generalized. Falls back to the
# raw tool name for anything unrecognized (fail-open, not a crash) --
# should never happen given the fixed set of tools this module declares,
# but an unrecognized name reaching the caller as-is is safer than
# silently mislabeling it as one of the three known categories.
_ANSWER_TYPE_BY_TOOL_NAME = {
    "reply": "reply",
    "start_milestone_work": "dispatch",
    "completion": "completion",
}


def resolve_orchestrator_answer(response):
    """Normalizes a real model response (already made with tool_choice=
    "required" and the appropriate subset of REPLY_TOOL/
    pods/social/engine.py's START_MILESTONE_WORK_TOOL/COMPLETION_TOOL
    offered -- this function does no model-calling itself, same
    "compose vs decide" separation as everywhere else in Kernel) into
    one real Answer: {"answer_type": "reply"|"dispatch"|"completion", "args": {...}}.

    Defensive, not trusting tool_choice="required" as an absolute
    guarantee:
    - Multiple tool calls in one response: only the first is ever used,
      matching run_global_turn's own existing precedent for this exact
      situation. Real, not hypothetical to guard against even though
      Gemini's own behavior hasn't produced it in testing so far --
      the same principle this codebase applies everywhere a real external
      response gets parsed.
    - Zero tool calls despite tool_choice="required" (a genuine contract
      violation from the provider, not expected but not impossible):
      fails open to answer_type="reply" using whatever raw text content
      the model did return, rather than crashing the turn -- the Director
      still gets a response, from a Director's-eye-view no different from
      today's plain-text reply."""
    tool_calls = response.tool_calls or []
    if not tool_calls:
        return {"answer_type": "reply", "args": {"message": response.text or ""}}

    call = tool_calls[0]
    answer_type = _ANSWER_TYPE_BY_TOOL_NAME.get(call["name"], call["name"])
    return {"answer_type": answer_type, "args": call["args"]}
