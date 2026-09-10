from core.brief import derive_brief
from core.composition import compose_function_identity
from core.coverage import assess_coverage
from core.ignition import confirm_launch_intent
from core.reconcile import filter_facts_by_scope
from pods.social.engine import SocialEngine
from pods.strike_team.engine import StrikeEngine
from pods.synthesis.engine import SynthesisEngine
import re


class Trigger:
    """One real, named step in a turn's trigger-decision chain -- a
    declarative record (id, scope, firing pattern, condition, action)
    instead of a hand-written `if` branch inline in core/orchestrator.py.

    Deliberately NOT a fully generic, independently-evaluable rule table
    (the classic OPA/Step-Functions shape): the real triggers here form a
    genuine sequential pipeline where each one's condition depends on the
    PREVIOUS one's actual output (Keymaster's condition needs Gatekeeper's
    own `ready`; Strike Team's condition needs Keymaster's own
    `confirmed`, itself only produced by a real model call). A flat
    independent-rule table can't represent that dependency chain. What
    this is instead: one shared `context` dict threaded through an
    ordered list, each trigger's condition checked against the CURRENT
    state of that context before its action runs and updates it --
    genuinely closer to a small state machine than an independent rule
    set, while still being "declarative" in the sense that actually
    matters here: named steps, named firing patterns, one evaluator loop,
    not five hand-written `if` blocks scattered through process_turn().

    condition(context) -> bool: whether this trigger's action should run
    this turn, given the context built up by everything evaluated so far.

    action(context) -> dict | awaitable[dict]: does the real work (may
    read/write `context` and `context["envelope"]`) and returns an
    outcome dict for the trace log. An action's own outcome dict may
    include a "fired" key to override the default "condition passed ==
    fired" assumption -- needed for start_milestone_work specifically,
    whose condition is trivially always-true (its "evaluation" IS the
    model call) and whose real fire/no-fire signal only exists in what
    that call actually returned. Every other trigger here leaves "fired"
    to its default (condition_result), since for them, condition passing
    and the action running really are the same thing.

    skip_reason(context) -> str | None: optional, for triggers where "the
    condition was false" isn't self-explanatory enough for real
    debugging value -- Gatekeeper's own skip can mean either "this
    milestone has no required_questions at all" or "the Strike Team
    already fired, this gate is permanently moot" (see Item 2's own
    stated purpose: catching a stuck permanent guard means being able to
    tell those two apart, not just seeing condition_result=False)."""
    def __init__(self, trigger_id, scope, pattern, condition, action, is_async=False, skip_reason=None):
        self.trigger_id = trigger_id
        self.scope = scope
        self.pattern = pattern
        self.condition = condition
        self.action = action
        self.is_async = is_async
        self.skip_reason = skip_reason


async def evaluate_triggers(triggers, context):
    """Runs one ordered trigger list once against a shared `context`,
    returning the list of trace entries Item 2 asks for -- one per
    trigger, real data about what was actually evaluated and what
    happened, not a generic app log. Each entry:
    {trigger_id, scope, pattern, condition_result, fired, outcome,
    skip_reason (only present when the trigger didn't fire and its own
    skip_reason callable returned something real)}.

    Deliberately does not itself decide what process_turn() does with
    the result -- this only runs the chain and reports what happened;
    the caller (core/orchestrator.py) still owns building the final
    response shape from context, same separation of concerns as
    everywhere else in this codebase (compose vs. decide)."""
    trace = []
    for trigger in triggers:
        entry = {"trigger_id": trigger.trigger_id, "scope": trigger.scope, "pattern": trigger.pattern}
        condition_result = trigger.condition(context)
        entry["condition_result"] = condition_result
        if condition_result:
            outcome = await trigger.action(context) if trigger.is_async else trigger.action(context)
            entry["fired"] = outcome.get("fired", True) if isinstance(outcome, dict) else True
            entry["outcome"] = outcome
        else:
            entry["fired"] = False
            entry["outcome"] = None
            if trigger.skip_reason:
                reason = trigger.skip_reason(context)
                if reason:
                    entry["skip_reason"] = reason
        trace.append(entry)
    return trace


def resolve_already_fired(envelope):
    """Whether the Strike Team has already fired for this milestone --
    knowledge_bricks round-trips through Backend's real ledger sync, so a
    non-empty knowledge_bricks on a fresh read is a real, already-
    persisted signal, not a guess. Still the same underlying proxy
    check as before this rework (Kernel is stateless and has no other
    persisted memory of past turns to query) -- what changes is that
    it's now a named, explicit context fact both Gatekeeper's and
    Keymaster's conditions read by name, and its own evaluation is
    visible in the trace log, instead of being an inline local variable
    invisible to anything outside process_turn()."""
    return bool(envelope.knowledge_bricks)


def _gatekeeper_condition(context):
    return bool(context["required_questions"]) and not context["strike_team_already_fired"]


def _gatekeeper_skip_reason(context):
    if context["strike_team_already_fired"]:
        return "already_fired"
    if not context["required_questions"]:
        return "no_required_questions"
    return None


def _gatekeeper_action(context):
    """Gatekeeper's real L1 (judge archetype)/L3 (mission+app_manual)/
    skill (the assessment procedure), composed from raw ingredients
    already on the envelope -- not fetched here, and not a hand-written
    mandate baked into assess_coverage() itself. platform.mandate/
    app_manual/global_mission are the exact same values already on
    persona_config (identical for the agent and for Gatekeeper); only the
    judge archetype's mandate and Gatekeeper's skill text are genuinely
    Gatekeeper's own (see SovereignRequest's docstring).

    filter_facts_by_scope() runs here, right before assess_coverage(),
    not earlier -- context["chat_summary"] itself stays the caller's real
    full value (needed unfiltered elsewhere, e.g. Strike Team's own brief
    derivation reads the whole thing); only what Gatekeeper actually SEES
    gets narrowed. context.get("active_scope_path") is None on the task-
    scoped path (never set there -- that context dict has no such key at
    all, see core/orchestrator.py), which the filter treats as "no active
    scope, don't filter" -- so this is a genuine no-op for every existing
    caller, confirmed by that same fallback, not just assumed safe."""
    envelope = context["envelope"]
    identity = compose_function_identity(
        envelope.gatekeeper_mandate,
        (envelope.persona_config.get("platform") or {}).get("mandate"),
        envelope.persona_config.get("app_manual"),
        envelope.persona_config.get("global_mission"),
    )
    scoped_chat_summary = filter_facts_by_scope(context["chat_summary"], context.get("active_scope_path"))
    coverage = assess_coverage(
        context["required_questions"], scoped_chat_summary,
        identity["l1"], identity["l3"], envelope.gatekeeper_skill or "",
    )
    envelope.gatekeeper_whisper = coverage.get("whisper")
    gate_status = coverage.get("gate_status")
    assessments = coverage.get("assessments")
    context["gate_status"] = gate_status
    context["assessments"] = assessments
    context["ready"] = gate_status == "GREEN"
    return {"gate_status": gate_status, "whisper": envelope.gatekeeper_whisper, "assessments": assessments}


GATEKEEPER_ASSESSMENT = Trigger(
    trigger_id="gatekeeper_assessment",
    scope="milestone",
    # Bound to strike_team_launch firing, not to its own satisfaction --
    # a RED gate keeps re-running every turn forever (correctly; it's
    # supposed to), a GREEN one also keeps re-running every turn right up
    # until the Strike Team actually launches, at which point it's the
    # already_fired check (not gate_status) that permanently stops it.
    pattern="every_turn_until_bound_event",
    condition=_gatekeeper_condition,
    action=_gatekeeper_action,
    skip_reason=_gatekeeper_skip_reason,
)


def _keymaster_condition(context):
    return context["ready"] and not context["strike_team_already_fired"]


def _keymaster_action(context):
    """Keymaster's real L1/skill (the classifier role + confirmation
    criteria), composed from raw ingredients already on the envelope --
    same pattern as Gatekeeper's identity resolution above. No l3:
    confirmed no genuine mission/app_manual use for this function's
    narrow intent-classification task.

    Unlike current pre-refactor code, this identity is now composed only
    when the condition (ready and not already_fired) actually holds,
    not unconditionally every turn -- a deliberate, behavior-neutral
    simplification: it was always pure, cheap string composition with no
    I/O or side effects, kept unconditional before only so the old
    inline short-circuit `if ready and not already_fired and
    confirm_launch_intent(...)` read as one clean condition. That reason
    no longer applies once this is its own named action, gated by its
    own named condition."""
    envelope = context["envelope"]
    keymaster_identity = compose_function_identity(
        envelope.keymaster_mandate,
        (envelope.persona_config.get("platform") or {}).get("mandate"),
        None, None,
    )
    confirmed = confirm_launch_intent(
        envelope.history, l1=keymaster_identity["l1"], skill=envelope.keymaster_skill or "",
    )
    context["confirmed"] = confirmed
    return {"confirmed": confirmed}


KEYMASTER_CONFIRMATION = Trigger(
    trigger_id="keymaster_confirmation",
    scope="milestone",
    pattern="every_turn_until_bound_event",
    condition=_keymaster_condition,
    action=_keymaster_action,
)


def weld_links(text, treasure_chest):
    def replace(match):
        source_id = match.group(1)
        if source_id in treasure_chest:
            s = treasure_chest[source_id]
            return f"[{s['title']}]({s['url']})"
        return f"[{source_id}]"
    return re.sub(r'\[(\d+)\]', replace, text)


async def _strike_team_action(context):
    """Everything that used to run inline inside process_turn()'s own
    `if ready and not already_fired and confirm_launch_intent(...):`
    branch -- unchanged logic, moved here as this trigger's own action.
    Condition (see STRIKE_TEAM_LAUNCH below) checks context["confirmed"]
    alone, not a re-check of ready/already_fired -- confirmed can only
    ever be True if Keymaster's own action ran, which itself required
    ready and not already_fired to be true, so checking confirmed alone
    is equivalent to re-checking all three, given Keymaster's trigger
    runs strictly before this one in the ordered list."""
    envelope = context["envelope"]
    chat_summary = context["chat_summary"]
    print("[ORCHESTRATOR] Strike Team Authorized (gate-driven).")

    # The settled brief -- Phase 1 (core/brief.py), not gated/fail-open
    # like Gatekeeper's whisper since firing at all already implies
    # gate_status GREEN; built from the same chat_summary pipeline as
    # Gatekeeper, so it can't be built on a fact that already scrolled
    # out of view.
    brief = derive_brief(envelope.milestone_config.get("output", ""), chat_summary)

    # Specialists/Hound only need the brief as readable text -- the
    # structured {identity_narrative, founding_voice} shape below is for
    # the final response/UI (content.brief), a separate concern.
    brief_text = brief.get("identity_narrative", "")
    if brief.get("founding_voice"):
        quotes = "\n".join(f'- "{q}"' for q in brief["founding_voice"])
        brief_text = f"{brief_text}\n\nIN THE DIRECTOR'S OWN WORDS:\n{quotes}"

    # Turn B: Parallel Hunt
    strike_results = await StrikeEngine.run_industrial_strike(envelope, brief_text)

    # Turn C: Synthesis -- bricks (the paper sections) and appendix (each
    # specialist's own raw report + sources) are genuinely different
    # things now, not one blended dict.
    synthesis = await SynthesisEngine.forge_truth(
        specialist_outputs=strike_results["reports"],
        milestone_config=envelope.milestone_config,
    )
    bricks = synthesis["bricks"]
    appendix = synthesis["appendix"]

    # The Weld (Inject Links) -- both the synthesized sections and each
    # specialist's own raw report can carry [N] citations back to the
    # same global treasure_chest.
    for key, content in bricks.items():
        if isinstance(content, str):
            bricks[key] = weld_links(content, strike_results["treasure_chest"])
    for entry in appendix:
        if isinstance(entry.get("content"), str):
            entry["content"] = weld_links(entry["content"], strike_results["treasure_chest"])

    # Update Knowledge -- only the flat brick_id->prose bricks belong in
    # knowledge_bricks (Backend's ledger extraction and TheClock's
    # compression both assume that flat shape); appendix/brief are
    # carried in the response instead, not folded in here -- same
    # reasoning as why they can't be smuggled into data_patch either.
    envelope.knowledge_bricks.update(bricks)
    envelope.kaiser_mandate = "RESEARCH COMPLETE. Discuss the new findings."

    context["bricks"] = bricks
    context["brief"] = brief
    context["appendix"] = appendix
    # Explicit, not inferred from context["bricks"] being present -- the
    # caller (process_turn()) needs one unambiguous signal to branch its
    # own final response shape on (STABLE vs. AUTHORIZED/PROBING), and an
    # explicit flag says so directly rather than asking the caller to
    # infer "did this fire" from a side effect of what it happened to set.
    context["strike_team_launched"] = True
    return {"launched": True}


STRIKE_TEAM_LAUNCH = Trigger(
    trigger_id="strike_team_launch",
    scope="milestone",
    pattern="once_per_milestone",
    condition=lambda context: context.get("confirmed", False),
    action=_strike_team_action,
    is_async=True,
)


async def _global_dispatch_action(context):
    """Runs the Global PM's own turn (pods/social/engine.py's
    run_global_turn) -- the "action" and the "evaluation" are the same
    real model call here, unlike the other three triggers: whether
    start_milestone_work fires is the model's own live judgment, not a
    deterministic check Kernel makes ahead of time. See
    GLOBAL_DISPATCH_CHOICE's own condition below for why it's trivially
    always-true, and this action's own "fired" override in its returned
    outcome for how the real fire/no-fire signal actually reaches the
    trace log."""
    envelope = context["envelope"]
    turn = await SocialEngine.run_global_turn(envelope)
    tool_call = turn.get("tool_call")
    context["social_response"] = turn.get("social_response")
    context["tool_call"] = tool_call
    return {"fired": tool_call is not None, "tool_call": tool_call}


GLOBAL_DISPATCH_CHOICE = Trigger(
    trigger_id="global_dispatch_choice",
    scope="global",
    # The one genuine judgment call among these -- Kernel has no
    # deterministic condition to check ahead of the model call itself,
    # so the condition is trivially always-true (this trigger is always
    # attempted on the global path); the real fire/no-fire signal comes
    # from the action's own "fired" override, not from condition_result.
    pattern="live_in_the_moment_choice",
    condition=lambda context: True,
    action=_global_dispatch_action,
    is_async=True,
)
