from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder
from schema.kernel_schema import AgentEnvelope

CLERK_SCHEMA = {
    "type": "object",
    "properties": {
        "physics_gate": {"type": "string", "enum": ["RED", "GREEN"]},
        "missing_logic": {"type": "string"},
    },
    "required": ["physics_gate", "missing_logic"],
}


def compose_l1_lines(persona_config):
    """The one canonical place L1 composition happens, for both run_turn and
    run_global_turn. Backend's compile_prompt_preview must mirror this
    exactly -- order and labels included -- so the Test Lab shows the
    literal truth, not a separately-maintained copy that can drift.

    Archetype rules go first: the most load-bearing, hard-compliance content
    (response budget, one-question rule, tone) earns primacy, not the more
    abstract platform framing. Each piece gets a plain, non-jargon label so
    both the model and a human reading it can tell what's what -- no
    markdown, consistent with the archetype's own rule against robot-speak
    formatting. archetype_l0_mother is the one exception: it already opens
    with its own "IDENTITY:" line, so labeling it again would be redundant.

    global_mission is NOT here -- it's context/knowledge about the app, not
    a behavioral rule, so it lives in L3 instead (see compose_l3_lens).
    """
    lines = []
    archetype_rules = persona_config.get("archetype_l0_mother")
    if archetype_rules:
        lines.append(archetype_rules)
    platform_logic = persona_config.get("platform_logic")
    if platform_logic:
        lines.append(f"HOW THIS PLATFORM WORKS: {platform_logic}")
    app_manual = persona_config.get("app_manual")
    if app_manual:
        lines.append(f"HOW THIS APP WORKS: {app_manual}")
    return lines


def compose_l3_lens(persona_config):
    """L3 (Deep Knowledge/Exo-Brain), with an optional MISSION section
    prefixed ahead of it. Mission is context/knowledge about the app, not a
    behavioral rule, so it lives here rather than in the L1 Mandate block --
    core system-prompt constraints (L1) should stay lean; reference material
    belongs with the rest of the domain knowledge."""
    exo_brain = persona_config.get("exo_brain", "Blunt, high-speed facilitator.")
    global_mission = persona_config.get("global_mission")
    if global_mission:
        return f"MISSION:\n{global_mission}\n\n{exo_brain}"
    return exo_brain


class SocialEngine:
    @staticmethod
    async def run_turn(envelope: AgentEnvelope):
        clerk_model, clerk_config = AgentFactory.get_clerk()
        
        # Pull dynamic keys from the ARM (App Registry Map)
        checklist_key = envelope.schema_map["schema_keys"]["pm_checklist"]
        checklist_prompt = envelope.milestone_config.get(checklist_key, "Find the spark.")

        required_questions = envelope.milestone_config.get("required_questions")
        if required_questions:
            numbered_questions = "\n".join(f"{i}. {q}" for i, q in enumerate(required_questions, start=1))
            checklist_prompt = f"{checklist_prompt}\n\nSPECIFIC FACTS TO EXTRACT:\n{numbered_questions}"

        # 1. CLERK AUDIT
        clerk_mandate = "ACT AS A CYNICAL INDUSTRIAL AUDITOR."
        clerk_lens = f"CRITERIA: {checklist_prompt}\nSTRUCTURE_EXPECTED: {envelope.schema_map['schema_keys']['brick_list']}"
        clerk_truth = f"CHAT_HISTORY: {envelope.history[-5:]}"
        
        clerk_work_order = PromptBuilder.assemble(
            mandate=clerk_mandate,
            lens=clerk_lens,
            truth=clerk_truth
        )

        clerk_resp = clerk_model.generate_content(clerk_work_order, generation_config=clerk_config, response_schema=CLERK_SCHEMA)
        clerk_report = hammer_json(get_clean_text(clerk_resp))
        
        # 2. KAISER PHYSICS
        envelope.physics_open = (clerk_report.get("physics_gate") == "GREEN")
        if not envelope.physics_open:
            missing = clerk_report.get("missing_logic", "Proprietary insight.")
            envelope.kaiser_mandate = f"PHYSICS LOCKED. Missing: {missing}. Probe blunt."
        else:
            envelope.kaiser_mandate = "PHYSICS OPEN. Offer to fire Strike Team."

        # 3. PM SOCIAL
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
        pm_mandate_lines.append(f"KAISER MANDATE: {envelope.kaiser_mandate}")
        # Computed once per turn in orchestrator.py (core/coverage.py), not
        # here -- avoids running Coverage twice per turn now that
        # orchestrator.py also needs it for gate-driven ignition.
        if envelope.coverage_whisper:
            pm_mandate_lines.append(f"COVERAGE WHISPER: {envelope.coverage_whisper}")
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
        hand off to. Single PM call, no Clerk audit -- the Clerk/gate/Kaiser
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
