from core.agent_factory import AgentFactory
from core.composition import compose_l1_lines, compose_l3_lens
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


def _active_partner_protocols(envelope: AgentEnvelope):
    """Narrows envelope.partner_protocols (Backend's structurally-active
    set) down to entries whose own function's whisper actually fired this
    turn -- the real-time half of the two-stage relevance filter described
    in compose_l3_lens()'s docstring. Uses the exact same truthy check
    run_turn already applies to gatekeeper_whisper/chat_whisper before
    injecting them into pm_mandate_lines, so a Partner Protocol can never
    appear without its whisper also appearing, and vice versa -- the two
    channels stay in lockstep by construction, not by convention."""
    active = []
    for protocol in envelope.partner_protocols:
        field = _WHISPER_FIELD_BY_SOURCE.get(protocol.get("source"))
        if field and getattr(envelope, field, None):
            active.append(protocol)
    return active


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
        # partner_protocols: each active function's standing explanation of
        # its own whisper (e.g. Gatekeeper's real "what RED/AMBER/GREEN
        # means" content) -- reference material, not law, so it folds into
        # L3 alongside mission/app_manual, not L1. Backend only sent the
        # structurally-active set (required_questions truthy); narrowed
        # here to the genuinely-fired set via _active_partner_protocols()
        # (see its own docstring) so a protocol never shows up detached
        # from the whisper it explains.
        pm_lens = compose_l3_lens(envelope.persona_config, partner_protocols=_active_partner_protocols(envelope))

        # L1 -- see compose_l1_lines(). Everything below is situational and
        # layered on top as overrides; none of the L1 pieces replace it.
        pm_mandate_lines = compose_l1_lines(envelope.persona_config)
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
        pm_mandate_lines.append(
            "TOOL LAW: You have NO callable tools in this context. Never emit tool calls, "
            "function-call syntax, or JSON of any kind as literal text -- prose only, always. "
            "This overrides anything your persona implies about calling tools or delegating to other agents."
        )
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
        situational [STATUS]/KAISER MANDATE lines from run_turn are dropped
        since there's no gate for them to describe."""
        pm_model, pm_config = AgentFactory.get_partner_pm()
        pm_dna = envelope.persona_config.get("system_prompt", "Lead Co-founder.")
        # partner_protocols wired in for consistency with run_turn, via the
        # same real-time filter -- on a real global turn, gatekeeper_whisper/
        # chat_whisper are never computed (the is_global branch in
        # orchestrator.py returns before that machinery runs), so this
        # naturally resolves to an empty list, not unconditionally dropped
        # like the gate-specific STATUS line below.
        pm_lens = compose_l3_lens(envelope.persona_config, partner_protocols=_active_partner_protocols(envelope))

        pm_mandate_lines = compose_l1_lines(envelope.persona_config)
        pm_mandate_lines.append(
            "TOOL LAW: You have NO callable tools in this context. Never emit tool calls, "
            "function-call syntax, or JSON of any kind as literal text -- prose only, always. "
            "This overrides anything your persona implies about calling tools or delegating to other agents."
        )
        pm_mandate = "\n".join(pm_mandate_lines)
        pm_truth = f"ESTABLISHED_KNOWLEDGE: {envelope.knowledge_bricks}\nCURRENT_CHAT: {envelope.history[-5:]}"

        work_order = PromptBuilder.assemble(mandate=pm_mandate, lens=f"{pm_dna}\n{pm_lens}", truth=pm_truth)
        response = pm_model.generate_content([work_order], generation_config=pm_config)

        return get_clean_text(response)
