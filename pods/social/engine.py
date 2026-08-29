from core.agent_factory import AgentFactory
from core.composition import compose_l1_lines, compose_l3_lens
from core.kernel_utils import get_clean_text
from core.prompt_builder import PromptBuilder
from schema.kernel_schema import AgentEnvelope


class SocialEngine:
    @staticmethod
    async def run_turn(envelope: AgentEnvelope):
        """The PM's own social turn. Gating (physics_open, the readiness
        signal, and coverage_whisper, the PM-facing directive) is Coverage's
        job -- computed once in core/orchestrator.py before this runs and
        threaded through the envelope. This function used to also run its
        own separate "Clerk" audit here: its own LLM call, its own criteria
        (a static checklist_prompt + the milestone's schema_keys), its own
        physics_open/KAISER MANDATE derivation -- independent of, and
        sometimes disagreeing with, Coverage's real gate_status (Clerk read
        the static required_questions field directly, never Requirements'
        derived output). Retired entirely, not just its output: Coverage
        (assess_coverage/resolve_required_questions) is the one real
        declared gate mechanism now -- nothing about gating logic lives
        here."""
        pm_model, pm_config = AgentFactory.get_partner_pm()
        # L2 (Agent Persona) + L3 (Deep Knowledge/Exo-Brain) -- these are the real
        # field names agency_roster docs actually have; "dna"/"lens" never existed
        # on any real agent doc, so this always fell back to generic placeholders.
        pm_dna = envelope.persona_config.get("system_prompt", "Lead Co-founder.")
        pm_lens = compose_l3_lens(envelope.persona_config)
        
        # L1 -- see compose_l1_lines(). Everything below is situational and
        # layered on top as overrides; none of the L1 pieces replace it.
        pm_mandate_lines = compose_l1_lines(envelope.persona_config)
        pm_mandate_lines.append(f"[STATUS: {'GREEN' if envelope.physics_open else 'RED'}]")
        # kaiser_mandate is turn-local scratch state for concerns unrelated
        # to gating now (e.g. orchestrator.py's post-Strike-Team-fire
        # "RESEARCH COMPLETE" directive) -- not always set, so guarded like
        # coverage_whisper below, not unconditional.
        if envelope.kaiser_mandate:
            pm_mandate_lines.append(f"KAISER MANDATE: {envelope.kaiser_mandate}")
        # Computed once per turn in orchestrator.py (core/coverage.py), not
        # here -- avoids running Coverage twice per turn now that
        # orchestrator.py also needs it for gate-driven ignition. Carries
        # both the gate assessment's nuance AND the PM-facing directive
        # (what Clerk's now-retired KAISER MANDATE used to separately
        # provide) in one real signal, not two.
        if envelope.coverage_whisper:
            pm_mandate_lines.append(f"COVERAGE WHISPER: {envelope.coverage_whisper}")
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
        hand off to. Single PM call, no gate audit -- Coverage/gate/Kaiser
        mandate exist to arbitrate handoff between agents, and there's nothing
        here to arbitrate. Real L1 (archetype_rules) and TOOL LAW stay; the
        situational [STATUS]/KAISER MANDATE lines from run_turn are dropped
        since there's no gate for them to describe."""
        pm_model, pm_config = AgentFactory.get_partner_pm()
        pm_dna = envelope.persona_config.get("system_prompt", "Lead Co-founder.")
        pm_lens = compose_l3_lens(envelope.persona_config)

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
