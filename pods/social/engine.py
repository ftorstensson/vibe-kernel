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
        pm_lens = envelope.persona_config.get("exo_brain", "Blunt, high-speed facilitator.")
        
        # L1 -- platform-wide logic (whole platform) + archetype rules (per
        # archetype) + global mission (app vision) + app manual (app
        # structure), in that order, when present. Everything below is
        # situational and layered on top as overrides; none of these four
        # replace it. Fails open: absent whenever a lookup didn't resolve.
        platform_logic = envelope.persona_config.get("platform_logic")
        archetype_rules = envelope.persona_config.get("archetype_l0_mother")
        global_mission = envelope.persona_config.get("global_mission")
        app_manual = envelope.persona_config.get("app_manual")
        pm_mandate_lines = []
        if platform_logic:
            pm_mandate_lines.append(platform_logic)
        if archetype_rules:
            pm_mandate_lines.append(archetype_rules)
        if global_mission:
            pm_mandate_lines.append(global_mission)
        if app_manual:
            pm_mandate_lines.append(app_manual)
        pm_mandate_lines.append(f"[STATUS: {'GREEN' if envelope.physics_open else 'RED'}]")
        pm_mandate_lines.append(f"KAISER MANDATE: {envelope.kaiser_mandate}")
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
        pm_lens = envelope.persona_config.get("exo_brain", "Blunt, high-speed facilitator.")

        platform_logic = envelope.persona_config.get("platform_logic")
        archetype_rules = envelope.persona_config.get("archetype_l0_mother")
        global_mission = envelope.persona_config.get("global_mission")
        app_manual = envelope.persona_config.get("app_manual")
        pm_mandate_lines = []
        if platform_logic:
            pm_mandate_lines.append(platform_logic)
        if archetype_rules:
            pm_mandate_lines.append(archetype_rules)
        if global_mission:
            pm_mandate_lines.append(global_mission)
        if app_manual:
            pm_mandate_lines.append(app_manual)
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
