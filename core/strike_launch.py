from core.brief import derive_brief
from pods.strike_team.engine import StrikeEngine
from pods.synthesis.engine import SynthesisEngine
from core.triggers import weld_links
from schema.kernel_schema import AgentEnvelope

# The exact fixed string core/triggers.py's _strike_team_action() sets on
# envelope.kaiser_mandate after a real launch -- duplicated here (not
# imported) since triggers.py has no constant to import, only the inline
# string. Returned to the caller in LaunchStrikeTeamResponse rather than
# left for Backend to hardcode a second copy, so the exact wording stays
# traceable to one place if it ever needs to change.
KAISER_MANDATE_RESEARCH_COMPLETE = "RESEARCH COMPLETE. Discuss the new findings."


async def execute_strike_team_launch(app_id, purpose, chat_summary, milestone_config):
    """Phase 1.5 migration pass: the real Strike Team launch sequence,
    exposed as a standalone, callable unit for Backend's own new
    orchestration (see LaunchStrikeTeamRequest's own docstring, schema/
    kernel_schema.py, for why this deliberately duplicates rather than
    refactors core/triggers.py's _strike_team_action() -- that file is
    off-limits for this pass).

    Sequence matches _strike_team_action exactly, minus the context/envelope
    mutation side effects (context["bricks"]/["brief"]/["appendix"]/
    ["strike_team_launched"], envelope.knowledge_bricks.update(),
    envelope.kaiser_mandate = ...) that only make sense inside
    core/orchestrator.py's own turn -- this function just returns the three
    real outputs plus the fixed kaiser_mandate string; the caller (Backend)
    does its own persistence and decides what to pass forward.

    StrikeEngine.run_industrial_strike(envelope, brief) takes an
    AgentEnvelope, not milestone_config directly -- its signature can't
    change without breaking core/triggers.py's own untouched call site, so
    a minimal AgentEnvelope is constructed here purely to satisfy that
    parameter; run_industrial_strike only ever reads envelope.milestone_config
    off it, confirmed against its own source before relying on this."""
    brief = derive_brief(purpose, chat_summary)

    brief_text = brief.get("identity_narrative", "")
    if brief.get("founding_voice"):
        quotes = "\n".join(f'- "{q}"' for q in brief["founding_voice"])
        brief_text = f"{brief_text}\n\nIN THE DIRECTOR'S OWN WORDS:\n{quotes}"

    strike_envelope = AgentEnvelope(
        app_id=app_id, project_id=app_id, milestone_config=milestone_config, persona_config={},
    )
    strike_results = await StrikeEngine.run_industrial_strike(strike_envelope, brief_text)

    synthesis = await SynthesisEngine.forge_truth(
        specialist_outputs=strike_results["reports"],
        milestone_config=milestone_config,
    )
    bricks = synthesis["bricks"]
    appendix = synthesis["appendix"]

    for key, content in bricks.items():
        if isinstance(content, str):
            bricks[key] = weld_links(content, strike_results["treasure_chest"])
    for entry in appendix:
        if isinstance(entry.get("content"), str):
            entry["content"] = weld_links(entry["content"], strike_results["treasure_chest"])

    return {
        "bricks": bricks,
        "brief": brief,
        "appendix": appendix,
        "kaiser_mandate": KAISER_MANDATE_RESEARCH_COMPLETE,
    }
