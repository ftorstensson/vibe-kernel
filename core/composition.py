def compose_l1_lines(persona_config):
    """The one canonical place L1 composition happens -- originally lived in
    pods/social/engine.py, shared by run_turn and run_global_turn; moved here
    so core-level callers (Requirements, Coverage, and future Functions) can
    reuse it too without core/ depending on pods/ backwards. Backend sends
    raw ingredients (archetype.mandate, platform.mandate, app_manual,
    global_mission, skill text), never pre-composed L1/L3 strings --
    deliberate, so this stays the one place this composition logic runs, not
    a second copy Backend maintains that can drift from it.

    archetype/platform are each record-wrapped ({mandate: str}), not flat
    archetype_l0_mother/platform_logic keys -- "One Name, Many Records": a
    field's name shouldn't fork depending on which record type it's
    attached to, since the record's own address already tells you the
    context. Exact literal key names confirmed with the architect session
    and Backend 2 during Test Run 1 (Six-Layer OS taxonomy); this reads
    persona_config["archetype"]["mandate"] and
    persona_config["platform"]["mandate"], defensively (.get chains, never
    a bare [] that can KeyError on a partial/missing record).

    Archetype rules go first: the most load-bearing, hard-compliance content
    (response budget, one-question rule, tone) earns primacy, not the more
    abstract platform framing. Each piece gets a plain, non-jargon label so
    both the model and a human reading it can tell what's what -- no
    markdown, consistent with the archetype's own rule against robot-speak
    formatting. The archetype's mandate is the one exception: it already
    opens with its own "IDENTITY:" line, so labeling it again would be
    redundant.

    Distinct pieces are separated by a blank line (not a single newline) so
    it's visually obvious where one source ends and the next begins.

    Neither global_mission nor app_manual are here -- they're context/
    knowledge about the app, not behavioral rules, so they live in L3
    instead (see compose_l3_lens). L1 stays lean, hard-compliance law only.
    """
    lines = []
    archetype_rules = (persona_config.get("archetype") or {}).get("mandate")
    if archetype_rules:
        lines.append(archetype_rules)
    platform_logic = (persona_config.get("platform") or {}).get("mandate")
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
    block -- core system-prompt constraints (L1) should stay lean;
    reference material belongs with the rest of the domain knowledge.

    default_exo_brain lets callers with no real persona/voice concept (e.g.
    compose_function_identity() below, for the Functions Library) suppress
    the legacy agent-voice fallback by passing None -- it should never leak
    into a function's mandate just because the dict it was given has no
    "exo_brain" key. Real agent turns keep the default unchanged.

    No partner_protocols parameter -- moved out to its own
    compose_partner_protocols_lens() (below), composed and appended
    separately by the caller, same pattern compose_project_map_lens()
    already uses. This isn't a style preference: this function's whole
    output is meant to become a value Kernel can read PRE-COMPUTED off a
    compiled record (see CompileIdentityRequest/AgentEnvelope.compiled_l3)
    instead of calling this every turn. partner_protocols is genuinely
    per-turn dynamic content (Backend can only resolve it after Kernel's
    own turn computes which whisper fired -- see
    compose_partner_protocols_lens()'s own docstring) -- folding it into
    THIS function's output would have meant it silently stopped reaching
    the model the moment a live turn started reading compiled_l3 instead
    of calling this live. Caught and fixed as part of the same cutover
    that introduced compiled_l3, not after."""
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


def compose_partner_protocols_lens(partner_protocols):
    """Each active function's standing explanation of what its own dynamic
    per-turn signal means (e.g. Gatekeeper's real functions_registry
    content: "Gates are scored RED, AMBER, or GREEN..."), as opposed to
    gatekeeper_whisper/chat_whisper, the dynamic per-turn VALUE those
    standing explanations describe. The two were designed together but
    are genuinely separate channels -- a whisper without its protocol is
    a value with no frame of reference; a protocol without a whisper is
    instructions with nothing to apply them to.

    Composed and appended separately by the caller (pods/social/
    engine.py), not threaded through compose_l3_lens() as a parameter the
    way it used to be -- pulled out specifically because it can't live
    inside L3's own composition anymore. L1/L3 are now readable pre-
    compiled off AgentEnvelope.compiled_l1/compiled_l3 (see
    CompileIdentityRequest), and once a live turn reads compiled_l3
    instead of calling compose_l3_lens() fresh, there is no live call left
    for a partner_protocols parameter to plug into -- it would have
    silently stopped reaching the model. This function is what makes it
    reach the model either way, compiled L3 or freshly-composed L3,
    identically. Same real per-turn relevance filter as before this
    refactor (this function itself renders whatever list it's handed; the
    caller narrows Backend's structurally-active set down to the
    genuinely-fired set first, via _active_partner_protocols() and the
    same gatekeeper_whisper/chat_whisper truthy checks -- see that
    function's own docstring in pods/social/engine.py for the full two-
    stage reasoning, unchanged by this move).

    Explanatory reference content about how to interpret a signal, not
    behavioral law itself, so it's appended alongside L3 (mission/
    app_manual), not folded into L1 -- same reasoning compose_l1_lines
    already gives for keeping context/knowledge out of the Mandate block.
    Deliberately one general field (not gatekeeper_partner_protocol/
    chat_manager_partner_protocol/... one-off fields per function) --
    exactly the per-function-field-name-drift pattern the
    coverage_*->gatekeeper_* rename already cleaned up elsewhere; a new
    function's protocol needs zero schema changes to show up here, just
    another {source, content} entry (though the caller's own source->
    whisper-field filter map does need extending for a new function to
    ever actually surface -- see pods/social/engine.py).

    Returns "" when the list is empty/absent, same falsy-skip convention
    every other optional appended block (compose_project_map_lens) uses,
    so a caller can unconditionally check truthiness before appending."""
    lines = []
    for protocol in (partner_protocols or []):
        content = protocol.get("content")
        if not content:
            continue
        source = protocol.get("source")
        if lines:
            lines.append("")
        lines.append(f"PARTNER PROTOCOL ({source}): {content}" if source else f"PARTNER PROTOCOL: {content}")
    return "\n".join(lines)


def compose_project_map_lens(project_map):
    """L3 context for the Global PM's own turn specifically
    (pods/social/engine.py's run_global_turn) -- deliberately NOT threaded
    through compose_l3_lens() above, unlike partner_protocols. That
    function is shared by run_turn/run_global_turn/compose_function_
    identity; project_map must reach ONLY the Global PM, never the task-
    scoped agent turn or any Function -- both of those are already
    correctly scoped to one milestone and don't need the whole app's
    structure, and giving compose_l3_lens a parameter that must never
    actually be passed by two of its three callers would be a foot-gun,
    not a convenience. A separate function, called and appended only at
    run_global_turn's own call site, makes "only the Global PM" true by
    construction (nothing to accidentally wire up elsewhere), not by
    caller discipline.

    project_map: Backend's resolved [{phase, milestones: [{id, name,
    status, purpose}]}] tree -- every non-archived phase in order, each
    with its non-archived milestones in order (Backend's job to
    filter/order, not Kernel's -- this function only renders what it's
    given). Gives the Global PM real visibility into what's done and
    what's next across the whole app, instead of only ever seeing one
    milestone in isolation -- the actual gap this exists to close.

    Rendered as a compressed id+name+status+one-line-purpose list, not a
    raw dump: real research on exactly this kind of always-present context
    recommends a compressed full-picture view over dumping full milestone
    records. Plain text, no markdown -- consistent with compose_l1_lines'
    own "no robot-speak formatting" rule; a phase name gets its own line,
    each milestone one line under it. id is rendered (not just used
    internally) because run_global_turn's start_milestone_work tool needs
    a real value here for the model to fill in as the tool call's own
    milestone_id argument -- without it in the text the model sees, there
    is nothing valid to reference.

    Defensive about missing keys (.get chains, never bare [] that can
    KeyError) -- same discipline compose_l1_lines/compose_l3_lens already
    apply to persona_config's own possibly-partial records. Returns "" when
    project_map is empty/absent, same falsy-skip convention as every other
    optional L3 piece, so a caller can unconditionally interpolate the
    result without a separate presence check."""
    if not project_map:
        return ""
    lines = ["PROJECT MAP:"]
    for phase in project_map:
        lines.append("")
        lines.append(phase.get("phase", ""))
        for milestone in phase.get("milestones") or []:
            milestone_id = milestone.get("id", "")
            name = milestone.get("name", "")
            status = milestone.get("status", "")
            purpose = milestone.get("purpose", "")
            # id rendered inline, not a separate line or heavier structure --
            # stays within the compressed-list goal while still giving the
            # model a real, addressable value to fill in as
            # start_milestone_work's own milestone_id argument (see
            # pods/social/engine.py) -- without this, the tool call would
            # have nothing valid to reference.
            tag = f"id: {milestone_id}" if milestone_id else ""
            if status:
                tag = f"{tag}, {status}" if tag else status
            entry = f"- {name} ({tag})" if tag else f"- {name}"
            if purpose:
                entry += f": {purpose}"
            lines.append(entry)
    return "\n".join(lines)


def compose_l4_lens(l3, skill):
    """L4 (Task/Skill), combined with L3 into PromptBuilder's physical LENS
    block -- PromptBuilder has exactly 3 physical blocks (MANDATE/LENS/TRUTH)
    and the six-layer taxonomy maps onto them precisely: MANDATE=L1 alone,
    LENS=L3+L4 together, TRUTH=L5+L6 together (see join_blocks() below).
    Real agent turns fold L2+L3 into their own lens the same way
    (pods/social/engine.py); this is the L3+L4 analog for the Functions
    Library.

    This exact formula (l3+skill, double-newline-joined, or skill alone
    when l3 is empty) used to be copy-pasted identically across
    derive_requirements()/assess_coverage()/extract_facts() -- three
    separate copies of the same one-line rule, exactly the "parallel copies
    that can drift" risk compose_l1_lines/compose_l3_lens already exist to
    avoid. One place now."""
    return f"{l3}\n\n{skill}" if l3 else skill


def join_blocks(*parts):
    """L5 (Signal)/L6 (Memory), and anything else feeding PromptBuilder's
    physical TRUTH block: skip empty pieces, join the rest with a blank
    line -- the same separation convention compose_l1_lines/compose_l3_lens
    already use internally for their own pieces, generalized into one
    shared primitive.

    Deliberately NOT a fixed-shape composer the way compose_l1_lines/
    compose_l3_lens/compose_l4_lens are: L5/L6 genuinely differ in kind per
    caller (Coverage's L6 is chat_summary, Chat Manager's L6 is
    prior_chat_summary, Keymaster has no L6 at all, Requirements' L5 is
    purpose+target_structure which isn't really Coverage-shaped "signal" or
    "memory" at all) -- there's no single real semantic slot shared across
    every caller the way archetype+platform or l3+skill are. Forcing one
    would mean inventing parameters that don't mean the same thing
    everywhere, the same trap L1/L3 avoided by not forcing agents and
    functions through identical persona shapes. What genuinely IS shared is
    the formatting mechanic (label a piece, skip it if empty, blank-line
    join the rest) -- callers build their own labeled pieces and pass them
    through this; this function imposes no shape on what those pieces are.

    Each argument is a caller-built string already carrying its own label
    (e.g. f"REQUIRED QUESTIONS (GATES):\\n{required_questions}") -- pass ""
    for a piece that's conditionally absent, same as the falsy-skip pattern
    compose_l1_lines/compose_l3_lens already use."""
    return "\n\n".join(p for p in parts if p)


def compose_function_identity(archetype_mandate, platform_mandate, app_manual, global_mission):
    """L1/L3 for a Functions Library entry (e.g. Requirements, Coverage),
    composed from raw ingredients the caller (Backend) already resolved --
    the pure-composition half of what used to be core/bootloader.py's
    resolve_function_identity(), with the Firestore fetches stripped out
    (Kernel is a stateless executor: given a complete input, it composes and
    calls the model -- it doesn't fetch its own inputs). Callers needing
    Coverage's identity for a live turn (core/orchestrator.py) and the
    standalone Functions Library endpoints (main.py) both go through this
    one place, so there's exactly one spot this composition logic runs --
    not a second copy that can drift from compose_l1_lines/compose_l3_lens.

    Takes plain mandate strings (not the record-wrapped {mandate: str}
    shape compose_l1_lines reads off persona_config) -- callers unwrap their
    own archetype/platform records before calling this, since a standalone
    Functions Library request has no persona_config to nest inside; this
    stays a simple 4-string function rather than also owning that
    unwrapping.

    No persona/exo_brain concept exists for a Functions Library entry --
    default_exo_brain=None keeps the agent-voice fallback out of a
    function's mandate, same reasoning compose_l3_lens's docstring already
    gives. Returns {l1: str, l3: str|None}."""
    l1 = "\n".join(compose_l1_lines({
        "archetype": {"mandate": archetype_mandate},
        "platform": {"mandate": platform_mandate},
    }))
    l3 = compose_l3_lens(
        {"app_manual": app_manual, "global_mission": global_mission},
        default_exo_brain=None,
    ) or None
    return {"l1": l1, "l3": l3}


def compose_agent_identity(persona_config):
    """L1/L3 for a real agent turn (e.g. the PM), composed from
    persona_config -- the agent-shaped sibling of compose_function_identity()
    above, needed for the same reason: a caller wanting an agent's own
    identity without going through a live turn (Backend's Materialized
    View compile step at publish time; Test Lab's agent preview, see
    AgentPreviewRequest in schema/kernel_schema.py). Both callers need the
    EXACT composition a real turn does, not a close approximation --
    hence this, not a second hand-rolled call to compose_l1_lines/
    compose_l3_lens with slightly different defaults that could drift.

    Deliberately does NOT reuse compose_function_identity() itself even
    though the underlying calls are nearly identical -- that function
    hardcodes default_exo_brain=None (correct for a Function, which has no
    persona/voice concept at all) and takes flat mandate strings instead
    of a persona_config dict. Calling it for an agent would silently
    suppress a real agent's own exo_brain fallback -- a live agent turn
    (pods/social/engine.py) always uses compose_l3_lens's own real
    default ("Blunt, high-speed facilitator."), and this must match that
    exactly, not compose_function_identity's Functions-only shape.

    Takes the persona_config dict directly (not unwrapped mandate
    strings) -- unlike compose_function_identity's callers, which have no
    persona_config to nest inside, an agent identity caller already has
    this exact dict (it's SovereignRequest.persona_config's own shape),
    so there's nothing to unwrap.

    Returns {l1: str, l3: str|None} -- same return shape as
    compose_function_identity(), for a consistent contract across both,
    even though the l3 default_exo_brain differs."""
    l1 = "\n".join(compose_l1_lines(persona_config))
    l3 = compose_l3_lens(persona_config) or None
    return {"l1": l1, "l3": l3}
