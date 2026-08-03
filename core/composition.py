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

    Distinct pieces are separated by a blank line (not a single newline) so
    it's visually obvious where one source ends and the next begins.

    Neither global_mission nor app_manual are here -- they're context/
    knowledge about the app, not behavioral rules, so they live in L3
    instead (see compose_l3_lens). L1 stays lean, hard-compliance law only.
    """
    lines = []
    archetype_rules = persona_config.get("archetype_l0_mother")
    if archetype_rules:
        lines.append(archetype_rules)
    platform_logic = persona_config.get("platform_logic")
    if platform_logic:
        if lines:
            lines.append("")
        lines.append(f"HOW THIS PLATFORM WORKS: {platform_logic}")
    return lines


def compose_l3_lens(persona_config, default_exo_brain="Blunt, high-speed facilitator."):
    """L3 (Deep Knowledge/Exo-Brain): mission, app_manual, and exo_brain, in
    that order, each its own clearly labeled piece separated by a blank
    line. Mission and app_manual are both context/knowledge about the app,
    not behavioral rules, so they live here rather than in the L1 Mandate
    block -- core system-prompt constraints (L1) should stay lean; reference
    material belongs with the rest of the domain knowledge.

    default_exo_brain lets callers with no real persona/voice concept (e.g.
    core/bootloader.py's resolve_function_identity(), for the Functions
    Library) suppress the legacy agent-voice fallback by passing None --
    it should never leak into a function's mandate just because the dict it
    was given has no "exo_brain" key. Real agent turns keep the default
    unchanged."""
    lines = []
    global_mission = persona_config.get("global_mission")
    if global_mission:
        lines.append(f"MISSION:\n{global_mission}")
    app_manual = persona_config.get("app_manual")
    if app_manual:
        if lines:
            lines.append("")
        lines.append(f"HOW THIS APP WORKS: {app_manual}")
    exo_brain = persona_config.get("exo_brain", default_exo_brain)
    if exo_brain:
        if lines:
            lines.append("")
        lines.append(exo_brain)
    return "\n".join(lines)
