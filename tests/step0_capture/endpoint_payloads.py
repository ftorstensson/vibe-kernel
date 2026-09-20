"""Shared endpoint payloads for the Step 0 HTTP tests (one valid request per capturing endpoint)."""
from scenarios import PERSONA, HISTORY, CHAT_SUMMARY, PROJECT_MAP

IDENT = {"archetype": {"mandate": "ARCH"}, "platform": {"mandate": "PLAT"}, "app_manual": "MAN", "global_mission": "MISSION"}
ENDPOINTS = {
    "/kernel/invoke": {"app_id": "a", "project_id": "a", "user_message": "hi", "persona_config": PERSONA, "milestone_config": {"output": "x"}, "history": [], "schema_map": {}},
    "/kernel/functions/derive_requirements": {"app_id": "a", **IDENT, "purpose": "p", "target_structure": ["headline"], "skill": "s"},
    "/kernel/functions/confirm_launch_intent": {"app_id": "a", **IDENT, "history": HISTORY, "skill": "s"},
    "/kernel/synthesize_dispatch": {"app_id": "a", "persona_config": PERSONA, "trigger_message": "t", "global_response": "g", "milestone_name": "m", "milestone_purpose": "p", "dispatch_status": "DONE", "dispatch_response": "r"},
    "/kernel/summarize_for_map": {"app_id": "a", "text": "condense me"},
    "/kernel/functions/assess_coverage": {"app_id": "a", **IDENT, "required_questions": ["Q"], "chat_summary": CHAT_SUMMARY, "skill": "s"},
    "/kernel/chat_summary": {"app_id": "a", **IDENT, "history": HISTORY, "required_questions": ["Q"], "skill": "s"},
    "/kernel/functions/launch_strike_team": {"app_id": "a", "purpose": "p", "chat_summary": CHAT_SUMMARY, "milestone_config": {"specialists": ["Analyst"]}},
    "/kernel/agents/run_turn": {"app_id": "a", "project_id": "a", "persona_config": PERSONA, "history": HISTORY},
    "/kernel/agents/run_global_turn": {"app_id": "a", "project_id": "a", "persona_config": PERSONA, "history": HISTORY, "project_map": PROJECT_MAP},
    "/kernel/agents/run_global_turn_answer": {"app_id": "a", "project_id": "a", "persona_config": PERSONA, "history": HISTORY, "project_map": PROJECT_MAP},
}
EXPECT_LABEL = {
    "/kernel/invoke": "pm.run_turn", "/kernel/functions/derive_requirements": "gate_maker.derive_requirements",
    "/kernel/functions/confirm_launch_intent": "keymaster.confirm_launch_intent", "/kernel/synthesize_dispatch": "pm.synthesize_dispatch",
    "/kernel/summarize_for_map": "map_summary.summarize_for_map", "/kernel/functions/assess_coverage": "gatekeeper.assess_coverage",
    "/kernel/chat_summary": "chat_manager.extract_facts", "/kernel/functions/launch_strike_team": "strike.derive_brief",
    "/kernel/agents/run_turn": "pm.run_turn", "/kernel/agents/run_global_turn": "pm.run_global_turn", "/kernel/agents/run_global_turn_answer": "pm.run_global_turn_answer",
}

