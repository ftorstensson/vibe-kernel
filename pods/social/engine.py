from core.agent_factory import AgentFactory
from core.composition import (
    compose_l1_lines, compose_l3_lens, compose_partner_protocols_lens,
    compose_project_map_lens, join_blocks,
)
from core.kernel_utils import get_clean_text
from core.prompt_builder import PromptBuilder
from schema.kernel_schema import AgentEnvelope

# Which envelope field holds a given partner_protocols entry's own
# real-time whisper -- Backend can only send partner_protocols for
# functions that are structurally active this turn (required_questions
# truthy), not for whichever ones actually end up firing a whisper, since
# assemble_envelope() runs entirely before Kernel computes that. This map
# is the real per-turn narrowing step: an entry only ever reaches the PM
# if its own function's whisper is genuinely non-empty right now (see
# _active_partner_protocols below). Extend this when a new function gets
# both a whisper and a Partner Protocol -- an entry whose source isn't
# listed here is dropped, never shown by default, matching "a Partner
# Protocol should never surface without a real, checked reason to."
_WHISPER_FIELD_BY_SOURCE = {
    "Gatekeeper": "gatekeeper_whisper",
    "Chat Manager": "chat_whisper",
}

# Fallback when envelope.tool_law is None -- Backend resolves the real
# registry_docs/tool_law content and sends it (same pattern platform.
# mandate/gatekeeper_mandate/... already use: Backend fetches, Kernel
# never does its own Firestore I/O), but a missing/unresolved doc must
# fail open to this, not silently drop the Tool Law entirely -- it's the
# one piece of L1 that's genuinely load-bearing for output safety (no
# tool-call syntax leaking into prose). Verbatim copy of the text this
# replaces, confirmed byte-identical against the real registry_docs/
# tool_law content (label added at composition time, same as
# platform_logic -- the doc itself stores no "TOOL LAW:" prefix).
DEFAULT_TOOL_LAW = (
    "You have NO callable tools in this context. Never emit tool calls, "
    "function-call syntax, or JSON of any kind as literal text -- prose only, always. "
    "This overrides anything your persona implies about calling tools or delegating to other agents."
)

# Native Gemini function-calling (real litellm tools=[...], not a text-marker
# convention) -- scoped ONLY to run_global_turn, same isolation discipline
# project_map already has: run_turn and every Function never see this.
# Declared only when envelope.project_map is non-empty (see run_global_turn)
# -- offering a tool with nothing real to dispatch to would let the model
# fabricate a milestone_id against an empty map.
START_MILESTONE_WORK_TOOL = {
    "type": "function",
    "function": {
        "name": "start_milestone_work",
        "description": (
            "Begin or continue focused work on ONE specific milestone from the "
            "PROJECT MAP above, when the Director clearly wants to start or "
            "resume work on it now. Only call this with a real milestone id "
            "that actually appears in the PROJECT MAP -- never invent one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "milestone_id": {
                    "type": "string",
                    "description": "The real id of the milestone to dispatch to, exactly as it appears in the PROJECT MAP.",
                }
            },
            "required": ["milestone_id"],
        },
    },
}

# TOOL LAW when start_milestone_work IS being offered this turn -- the
# blanket "you have NO callable tools" text above becomes actively false
# once a real tool is declared, so it can't just stay unconditional here.
# Same anti-hallucination intent as DEFAULT_TOOL_LAW (no fabricated OTHER
# tool calls, no raw JSON leaking into prose for anything else), narrowed
# to name the one real exception instead of denying everything.
DISPATCH_TOOL_LAW = (
    "You have exactly ONE callable tool: start_milestone_work. Call it only "
    "when the Director clearly wants to begin or resume focused work on a "
    "specific milestone from the PROJECT MAP above, with milestone_id set to "
    "that milestone's real id. Never fabricate any other tool call, "
    "function-call syntax, or JSON of any kind as literal text for anything "
    "else -- prose only otherwise. This overrides anything your persona "
    "implies about calling tools or delegating to other agents."
)


def _active_partner_protocols(envelope: AgentEnvelope):
    """Narrows envelope.partner_protocols (Backend's structurally-active
    set) down to entries whose own function's whisper actually fired this
    turn -- the real-time half of a two-stage relevance filter (Backend
    can only send the coarse structurally-active set ahead of Kernel's own
    turn; this is the fine-grained narrowing that happens after, once a
    real whisper either did or didn't fire). Uses the exact same truthy
    check run_turn already applies to gatekeeper_whisper/chat_whisper
    before injecting them into pm_mandate_lines, so a Partner Protocol can
    never appear without its whisper also appearing, and vice versa -- the
    two channels stay in lockstep by construction, not by convention. See
    compose_partner_protocols_lens()'s own docstring (core/composition.py)
    for how the result of this gets rendered and appended."""
    active = []
    for protocol in envelope.partner_protocols:
        field = _WHISPER_FIELD_BY_SOURCE.get(protocol.get("source"))
        if field and getattr(envelope, field, None):
            active.append(protocol)
    return active


def _compiled_l1_lines(envelope: AgentEnvelope):
    """L1, the Materialized View cutover: reads envelope.compiled_l1
    directly when Backend's compile step has attached one, instead of
    calling compose_l1_lines(persona_config) fresh -- the actual cutover,
    not new capability. Falls back to live composition when compiled_l1
    is absent/empty, mirroring Backend's own compiled-record fallback
    exactly, so an app that hasn't republished under the new scheme keeps
    working unchanged. Returns a list either way (compiled_l1 wrapped as
    the list's one element) so the caller's existing
    .append()-then-"\\n".join() pattern needs no changes downstream --
    compiled_l1 is already the fully-joined string a live
    compose_l1_lines() call would produce."""
    if envelope.compiled_l1:
        return [envelope.compiled_l1]
    return compose_l1_lines(envelope.persona_config)


def _compiled_l3(envelope: AgentEnvelope):
    """L3, same cutover as _compiled_l1_lines above: reads
    envelope.compiled_l3 directly when present, falls back to live
    compose_l3_lens(persona_config) otherwise."""
    if envelope.compiled_l3:
        return envelope.compiled_l3
    return compose_l3_lens(envelope.persona_config)


class SocialEngine:
    @staticmethod
    async def run_turn(envelope: AgentEnvelope):
        """The PM's own social turn. Gating (physics_open, the readiness
        signal, and gatekeeper_whisper, the PM-facing directive) is
        Gatekeeper's job -- computed once in core/orchestrator.py before
        this runs and threaded through the envelope. This function used to
        also run its own separate "Clerk" audit here: its own LLM call, its
        own criteria (a static checklist_prompt + the milestone's
        schema_keys), its own physics_open/KAISER MANDATE derivation --
        independent of, and sometimes disagreeing with, Gatekeeper's real
        gate_status (Clerk read the static required_questions field
        directly, never Requirements' derived output). Retired entirely,
        not just its output: Gatekeeper (assess_coverage/
        resolve_required_questions) is the one real declared gate mechanism
        now -- nothing about gating logic lives here."""
        pm_model, pm_config = AgentFactory.get_partner_pm()
        # L2 (Agent Persona) + L3 (Deep Knowledge/Exo-Brain) -- these are the real
        # field names agency_roster docs actually have; "dna"/"lens" never existed
        # on any real agent doc, so this always fell back to generic placeholders.
        pm_dna = envelope.persona_config.get("system_prompt", "Lead Co-founder.")
        # L3: reads Backend's precompiled envelope.compiled_l3 when present
        # (the Materialized View cutover), falls back to a live
        # compose_l3_lens() call otherwise -- see _compiled_l3()'s own
        # docstring. partner_protocols is appended separately, not
        # threaded through either path -- each active function's standing
        # explanation of its own whisper (e.g. Gatekeeper's real "what
        # RED/AMBER/GREEN means" content), narrowed to the genuinely-fired
        # set via _active_partner_protocols() (see its own docstring) so a
        # protocol never shows up detached from the whisper it explains.
        # Composed and appended here rather than folded into compiled_l3
        # itself because it's genuinely per-turn dynamic -- Backend
        # resolves it before this turn even runs, but whether it's
        # RELEVANT is only known once this turn's own whisper fires.
        pm_lens = _compiled_l3(envelope)
        partner_protocols_block = compose_partner_protocols_lens(_active_partner_protocols(envelope))
        if partner_protocols_block:
            pm_lens = f"{pm_lens}\n\n{partner_protocols_block}" if pm_lens else partner_protocols_block

        # L1: same cutover as L3 above -- see _compiled_l1_lines()'s own
        # docstring. Everything below is situational and layered on top as
        # overrides; none of the L1 pieces replace it.
        pm_mandate_lines = _compiled_l1_lines(envelope)
        pm_mandate_lines.append(f"[STATUS: {'GREEN' if envelope.physics_open else 'RED'}]")
        # kaiser_mandate is turn-local scratch state for concerns unrelated
        # to gating now (e.g. orchestrator.py's post-Strike-Team-fire
        # "RESEARCH COMPLETE" directive) -- not always set, so guarded like
        # gatekeeper_whisper below, not unconditional.
        if envelope.kaiser_mandate:
            pm_mandate_lines.append(f"KAISER MANDATE: {envelope.kaiser_mandate}")
        # Computed once per turn in orchestrator.py (core/coverage.py), not
        # here -- avoids running Gatekeeper twice per turn now that
        # orchestrator.py also needs it for gate-driven ignition. Carries
        # both the gate assessment's nuance AND the PM-facing directive
        # (what Clerk's now-retired KAISER MANDATE used to separately
        # provide) in one real signal, not two. Renamed from coverage_whisper
        # -- "Coverage" was the old function name.
        if envelope.gatekeeper_whisper:
            pm_mandate_lines.append(f"GATEKEEPER WHISPER: {envelope.gatekeeper_whisper}")
        # Chat Manager's own signal, same scratch-field pattern -- when it
        # couldn't confidently classify something as new/update/conflict,
        # this is the single most pressing thing to ask the Director to
        # clarify, not a guess or a silent drop (core/reconcile.py's
        # build_chat_summary()/_pick_chat_whisper()).
        if envelope.chat_whisper:
            pm_mandate_lines.append(f"CHAT WHISPER: {envelope.chat_whisper}")
        pm_mandate_lines.append(f"TOOL LAW: {envelope.tool_law or DEFAULT_TOOL_LAW}")
        pm_mandate = "\n".join(pm_mandate_lines)
        pm_truth = f"ESTABLISHED_KNOWLEDGE: {envelope.knowledge_bricks}\nCURRENT_CHAT: {envelope.history[-5:]}"

        work_order = PromptBuilder.assemble(mandate=pm_mandate, lens=f"{pm_dna}\n{pm_lens}", truth=pm_truth)
        response = pm_model.generate_content([work_order], generation_config=pm_config)

        return get_clean_text(response)

    @staticmethod
    async def run_global_turn(envelope: AgentEnvelope):
        """Global Agent: free-form chat, no scoped milestone, no second agent to
        hand off to. Single PM call, no gate audit -- Gatekeeper/gate/Kaiser
        mandate exist to arbitrate handoff between agents, and there's nothing
        here to arbitrate. Real L1 (archetype_rules) and TOOL LAW stay; the
        gate-specific situational [STATUS]/KAISER MANDATE lines from run_turn
        are dropped since there's no gate for them to describe.

        CHAT WHISPER stays, unlike those -- it's Chat Manager's own signal,
        not gate-specific, and orchestrator.py's is_global branch now runs
        Chat Manager unconditionally (Fred's product call: continuous
        conversational awareness isn't gated behind milestone scope, see
        core/orchestrator.py's _run_chat_manager()). Checked, not assumed:
        this line was genuinely missing here even after partner_protocols
        wiring added the L3 side (_active_partner_protocols below) to both
        run_turn and run_global_turn -- the two channels are related but
        separate; L3's Partner Protocol explains what a whisper means, this
        L1 line is the whisper itself, and only run_turn had it.

        PROJECT MAP is new here and here only -- see
        compose_project_map_lens()'s own docstring for why it's appended
        directly rather than folded into L3's own composition: it must
        reach ONLY the Global PM, and a separate function makes that true
        by construction rather than by every future caller remembering
        not to pass it. partner_protocols (below) is appended the same
        way now too, for a related but distinct reason -- see
        compose_partner_protocols_lens()'s own docstring.

        start_milestone_work is offered here too, and here only -- real
        native function-calling (litellm's tools=[...], parsed back out
        in core/agent_factory.py's LiteLLMResponse), not a text-marker
        convention. Only declared when project_map is non-empty (nothing
        real to dispatch to otherwise -- see START_MILESTONE_WORK_TOOL's
        own comment). Confirmed empirically, not assumed: a real Vertex/
        Gemini 2.5 Pro call returns genuine acknowledgment text AND a real
        tool call together in one response, so this function always
        returns BOTH social_response and tool_call (the latter None when
        no call happened) -- the caller (core/orchestrator.py) decides
        what to do with each; this function's own job stays "compose and
        call the model," same as everywhere else in Kernel.

        Returns {social_response: str, tool_call: {name, args} | None}."""
        pm_model, pm_config = AgentFactory.get_partner_pm()
        pm_dna = envelope.persona_config.get("system_prompt", "Lead Co-founder.")
        # L3: same compiled-first, live-fallback cutover as run_turn -- see
        # _compiled_l3()'s own docstring. partner_protocols wired in for
        # consistency with run_turn, via the same real-time filter and the
        # same appended-not-folded-in reasoning -- gatekeeper_whisper is
        # never computed on this path (no gate to check), but chat_whisper
        # now genuinely can be, so a Chat Manager Partner Protocol entry
        # can surface here too.
        pm_lens = _compiled_l3(envelope)
        partner_protocols_block = compose_partner_protocols_lens(_active_partner_protocols(envelope))
        if partner_protocols_block:
            pm_lens = f"{pm_lens}\n\n{partner_protocols_block}" if pm_lens else partner_protocols_block
        # Appended, not folded into L3's own composition -- see this
        # function's own docstring above. compose_project_map_lens()
        # returns "" when project_map is empty/absent, so this is a no-op
        # (identical output to before this field existed) whenever Backend
        # hasn't sent one.
        project_map_block = compose_project_map_lens(envelope.project_map)
        if project_map_block:
            pm_lens = f"{pm_lens}\n\n{project_map_block}" if pm_lens else project_map_block

        # Only offered when there's a real map to dispatch against -- an
        # empty project_map means TOOL LAW reverts to the plain "no
        # callable tools" text, accurately, since none is being declared.
        tools = [START_MILESTONE_WORK_TOOL] if envelope.project_map else None

        # L1: same cutover as run_turn -- see _compiled_l1_lines()'s own
        # docstring.
        pm_mandate_lines = _compiled_l1_lines(envelope)
        if envelope.chat_whisper:
            pm_mandate_lines.append(f"CHAT WHISPER: {envelope.chat_whisper}")
        pm_mandate_lines.append(f"TOOL LAW: {DISPATCH_TOOL_LAW if tools else (envelope.tool_law or DEFAULT_TOOL_LAW)}")
        pm_mandate = "\n".join(pm_mandate_lines)
        pm_truth = f"ESTABLISHED_KNOWLEDGE: {envelope.knowledge_bricks}\nCURRENT_CHAT: {envelope.history[-5:]}"

        work_order = PromptBuilder.assemble(mandate=pm_mandate, lens=f"{pm_dna}\n{pm_lens}", truth=pm_truth)
        response = pm_model.generate_content([work_order], generation_config=pm_config, tools=tools)

        # Defensive against a hypothetical multiple-tool-calls response --
        # the schema only ever declares one function, and the design is
        # one dispatch per turn, so only the first is ever used; extras
        # (which real testing never actually produced) are silently
        # ignored rather than crashing or dispatching more than once.
        tool_call = response.tool_calls[0] if response.tool_calls else None
        return {"social_response": get_clean_text(response), "tool_call": tool_call}

    @staticmethod
    async def synthesize_dispatch(
        persona_config, trigger_message, global_response,
        milestone_name, milestone_purpose, dispatch_status, dispatch_response,
    ):
        """The last step of start_milestone_work's real round-trip (see
        run_global_turn/START_MILESTONE_WORK_TOOL above, and
        SynthesizeDispatchRequest's own docstring in schema/kernel_schema.py
        for the full trace). Backend has already: seen the tool call, resolved
        the dispatched milestone's real data, run it through the existing
        Gatekeeper->Keymaster->Strike-Team pipeline (unchanged, a second
        /kernel/invoke call scoped to that milestone). This is the one final
        model call that turns the Global PM's own initial reaction and that
        real result into ONE coherent reply -- Fred's explicit call: one
        synthesized message, never two separate chat bubbles.

        No tool declared here -- deliberately not recursive; v1 dispatches
        once per turn, synthesis is where that resolves, not where another
        dispatch begins. TOOL LAW here is the plain DEFAULT_TOOL_LAW, same
        as any turn where no tool is being offered.

        global_response can be genuinely empty (confirmed by real testing --
        litellm/Gemini doesn't always return accompanying text alongside a
        tool call, only sometimes) -- join_blocks() drops it cleanly rather
        than this function assuming it's always there.

        Mandate content (the SYNTHESIS TASK instruction below) is
        hardcoded, not Firestore-sourced like the four declared Functions'
        skill text -- this is Kernel's own internal composition step, not
        Studio-editable content, same precedent core/reconcile.py's
        reconcile_fact() already sets for a narrowly-scoped internal
        mandate that stays hardcoded on purpose."""
        pm_model, pm_config = AgentFactory.get_partner_pm()
        pm_dna = persona_config.get("system_prompt", "Lead Co-founder.")
        pm_lens = compose_l3_lens(persona_config)

        pm_mandate_lines = compose_l1_lines(persona_config)
        pm_mandate_lines.append(
            "SYNTHESIS TASK: The Director just asked you to focus on a specific "
            "milestone. You already began reacting to that (see YOUR INITIAL "
            "REACTION below, if present) before the real work happened. Write ONE "
            "natural, coherent reply that continues that same thought and folds in "
            "the real result below -- as if this is one continuous response, never "
            "two separate messages stitched together. Never mention dispatching, "
            "tool calls, or any internal mechanism -- speak as their co-founder, "
            "naturally, about the milestone and what you actually found."
        )
        pm_mandate_lines.append(f"TOOL LAW: {DEFAULT_TOOL_LAW}")
        pm_mandate = "\n".join(pm_mandate_lines)

        pm_truth = join_blocks(
            f"THE DIRECTOR SAID:\n{trigger_message}",
            f"YOUR INITIAL REACTION:\n{global_response}" if global_response else "",
            f"MILESTONE: {milestone_name}\n{milestone_purpose}" if milestone_name else "",
            f"WORK RESULT ({dispatch_status}):\n{dispatch_response}",
        )

        work_order = PromptBuilder.assemble(mandate=pm_mandate, lens=f"{pm_dna}\n{pm_lens}", truth=pm_truth)
        response = pm_model.generate_content([work_order], generation_config=pm_config)

        return get_clean_text(response)
