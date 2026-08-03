def compose_l1_lines(persona_config):
    """The one canonical place L1 composition happens -- originally lived in
    pods/social/engine.py, shared by run_turn and run_global_turn; moved here
    so core-level callers (Requirements, and future Functions) can reuse it
    too without core/ depending on pods/ backwards. Backend's
    compile_prompt_preview must mirror this exactly -- order and labels
    included -- so the Test Lab shows the literal truth, not a
    separately-maintained copy that can drift.

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
