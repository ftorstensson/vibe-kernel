from core.clock import TheClock
from core.composition import compose_function_identity
from core.coverage import resolve_required_questions
from core.reconcile import build_chat_summary
from core.triggers import (
    evaluate_triggers, resolve_already_fired,
    GATEKEEPER_ASSESSMENT, KEYMASTER_CONFIRMATION, STRIKE_TEAM_LAUNCH,
    GLOBAL_DISPATCH_CHOICE,
)
from pods.social.engine import SocialEngine
from schema.kernel_schema import AgentEnvelope


def _resolve_active_scope_path(envelope: AgentEnvelope):
    """The real scope this turn's own facts belong to (markdown-6.md §5's
    Memory resolution: "keyed by scope path (app/phase/milestone)") --
    app_id alone when no milestone is active this turn, app_id/
    milestone_id once one is. phase_id folds in as a real middle segment
    once Kernel has one on the envelope -- it doesn't yet (no phase_id
    field exists anywhere in this contract today, only phase_purpose's
    own text, see SovereignRequest's docstring); flagged to Backend as a
    real, separate follow-up, not silently worked around here. Used for
    both jobs scope_path exists to do: TAGGING new facts
    (build_chat_summary()'s own scope_path param, called from
    _run_chat_manager() below) and FILTERING them back out at read time
    (core/reconcile.py's filter_facts_by_scope(), called from
    core/triggers.py's _gatekeeper_action()) -- same value, computed once
    per call site, not two independent copies that could drift."""
    if envelope.milestone_id:
        return f"{envelope.app_id}/{envelope.milestone_id}"
    return envelope.app_id


class MasterOrchestrator:
    @staticmethod
    def _run_chat_manager(envelope: AgentEnvelope, required_questions=None):
        """Chat Manager's real extraction+reconcile pass for this turn --
        updates envelope.chat_summary/chat_summary_cursor/chat_whisper in
        place, matching the dual-purpose input/output pattern
        knowledge_bricks/physics_open already use. Shared by the task-
        scoped path (inside `if required_questions:` below, passing the
        milestone's real required_questions) and the Global Agent path
        (unconditional -- Fred's product call: staying continuously aware
        of the conversation is core to the PM's job regardless of
        milestone state, so required_questions stays None there, no
        milestone to gate against) -- genuinely the same logic needed in
        two places now, extracted rather than kept as a second copy that
        can drift.

        required_questions=None (the global path) degrades gracefully, not
        as a new capability added for this -- confirmed directly against
        build_chat_summary()/extract_facts()'s own signatures and
        docstrings: both already default required_questions/purpose to
        None and explicitly document "optional, since not every caller has
        milestone scope." purpose is always envelope.milestone_config.get(
        "output", ""), which is naturally "" on the global path (empty
        milestone_config) -- also falsy, also already handled, no
        special-casing needed here either.

        Composed from raw ingredients already on the envelope -- same
        pattern Gatekeeper's identity resolution uses right below in
        process_turn(). platform.mandate/app_manual/global_mission are the
        exact same values already on persona_config; only the scribe
        archetype's mandate and Chat Manager's skill text are genuinely
        its own."""
        chat_manager_identity = compose_function_identity(
            envelope.chat_manager_mandate,
            (envelope.persona_config.get("platform") or {}).get("mandate"),
            envelope.persona_config.get("app_manual"),
            envelope.persona_config.get("global_mission"),
        )
        # prior_chat_summary/cursor are envelope state Backend sent (empty/0
        # on a fresh conversation) -- Kernel slices envelope.history[cursor:]
        # itself inside build_chat_summary(), it already has the full
        # history, so there's no reason to make Backend compute and send a
        # delta.
        chat_result = build_chat_summary(
            envelope.history,
            required_questions=required_questions,
            purpose=envelope.milestone_config.get("output", ""),
            prior_chat_summary=envelope.chat_summary,
            cursor=envelope.chat_summary_cursor,
            l1=chat_manager_identity["l1"],
            l3=chat_manager_identity["l3"],
            skill=envelope.chat_manager_skill or "",
            # See _resolve_active_scope_path()'s own docstring -- tags
            # every newly-extracted fact with the real scope this turn
            # belongs to, app-level at minimum, milestone-level once one's
            # active. Applies to every caller of this function, not just
            # the new Global gate-loop -- markdown-6.md §5 doesn't carve
            # out an exception for the task-scoped path, and a fact with
            # no scope tag isn't a state anything should keep producing
            # going forward, just a migration-compatibility shim for
            # facts extracted before this pass.
            scope_path=_resolve_active_scope_path(envelope),
        )
        envelope.chat_whisper = chat_result["chat_whisper"]
        envelope.chat_summary = chat_result["chat_summary"]
        envelope.chat_summary_cursor = chat_result["chat_summary_cursor"]
        return chat_result["chat_summary"]

    @staticmethod
    async def process_turn(envelope: AgentEnvelope, user_input: str, is_global: bool = False):
        # 1. The Clock (Self-Cleaning)
        await TheClock.maintenance_pulse(envelope)

        # 2. Add input to internal history
        envelope.history.append({"role": "user", "content": user_input})

        if is_global:
            # Global Agent: free-form chat, no scoped milestone, no second agent to
            # hand off to. The Clerk/gate/Strike-Team machinery below exists to
            # arbitrate handoff between agents -- there's nothing here to arbitrate,
            # so it doesn't run. Chat Manager DOES run here though, unconditionally
            # (Fred's product call -- see _run_chat_manager()'s own docstring):
            # reset chat_whisper fresh each turn first (same "not a stale value
            # from an earlier turn" pattern the task-scoped path below uses),
            # then run it wrapped in try/except so a Chat Manager failure fails
            # open -- the Global Agent should still respond even if extraction
            # breaks, just without this turn's chat_summary update, same as the
            # task-scoped path already fails open on Gatekeeper/ignition errors.
            envelope.chat_whisper = None
            chat_computed = False
            try:
                MasterOrchestrator._run_chat_manager(envelope)
                chat_computed = True
            except Exception:
                pass
            # GLOBAL_DISPATCH_CHOICE (core/triggers.py) runs run_global_turn
            # for real -- tool_call is real native function-calling output
            # (Gemini's start_milestone_work), not something Kernel resolves
            # further itself (stateless: only Backend has the dispatched
            # milestone's real data). status flips to TOOL_CALL so Backend
            # can branch on it the same way it already does for
            # PROBING/AUTHORIZED/STABLE/GLOBAL -- social_response is still
            # returned either way (the model's own real acknowledgment text
            # when a tool call fires too, confirmed both come back together)
            # as raw material for Backend's own synthesis step, not dropped
            # just because a tool call also happened.
            context = {"envelope": envelope}
            trigger_log = await evaluate_triggers([GLOBAL_DISPATCH_CHOICE], context)
            tool_call = context.get("tool_call")
            status = "TOOL_CALL" if tool_call else "GLOBAL"
            social_response = context.get("social_response")
            data_patch = brief = appendix = None
            gate_status = None
            assessments = None

            # The automatic Gatekeeper/Keymaster/Strike-Team loop, taking
            # over on every turn after a milestone's been dispatched
            # (PM14's explicit resolution: Test Run 0 decommissioned the
            # separate Task-scoped conversation this used to run inside --
            # same chain, same firing patterns, GATEKEEPER_ASSESSMENT/
            # KEYMASTER_CONFIRMATION/STRIKE_TEAM_LAUNCH unchanged from
            # core/triggers.py, just riding the Global conversation now).
            # Only attempted when Backend's active_milestone_already_fired
            # is not None -- None means this milestone has never been
            # dispatched at all (see SovereignRequest's own docstring for
            # the real three-state meaning), which is exactly today's
            # original unconditional skip, preserved for that real case.
            if envelope.milestone_id and envelope.active_milestone_already_fired is not None:
                gate_context = {
                    "envelope": envelope,
                    "required_questions": resolve_required_questions(envelope.milestone_config),
                    "chat_summary": envelope.chat_summary,
                    "active_scope_path": _resolve_active_scope_path(envelope),
                    # Deliberately NOT envelope.knowledge_bricks -- Backend
                    # traced a real conflict: on a Global turn that field is
                    # the whole App's own accumulated findings across every
                    # milestone (what ESTABLISHED_KNOWLEDGE shows the PM),
                    # not this one milestone's launch state. This explicit
                    # field is why already_fired never has to touch it here.
                    "strike_team_already_fired": envelope.active_milestone_already_fired,
                    "ready": False,
                    "gate_status": None,
                    "assessments": None,
                    "confirmed": False,
                }
                try:
                    if gate_context["strike_team_already_fired"]:
                        # Same shortcut the task-scoped path already uses --
                        # the gate's already permanently passed, nothing
                        # left for Gatekeeper to say. Its own trigger still
                        # runs right after regardless (condition correctly
                        # evaluates False), so the trace log gets a real
                        # skip_reason entry, not silence.
                        gate_context["ready"] = True
                    trigger_log += await evaluate_triggers([GATEKEEPER_ASSESSMENT], gate_context)
                except Exception:
                    gate_context["ready"] = False
                envelope.physics_open = gate_context["ready"]
                # Keymaster/Strike-Team run unprotected, exactly matching
                # the task-scoped path's own error-handling scope (see that
                # branch's own comment on this asymmetry) -- deliberately
                # NOT unified into one shared try/except here either, same
                # reasoning, not a new inconsistency introduced by this pass.
                trigger_log += await evaluate_triggers([KEYMASTER_CONFIRMATION, STRIKE_TEAM_LAUNCH], gate_context)
                gate_status = gate_context["gate_status"]
                assessments = gate_context["assessments"]

                if gate_context.get("strike_team_launched"):
                    # Strike Team fired directly from this Global turn's own
                    # automatic loop. Deliberately calls run_turn(), not
                    # run_global_turn() again -- the latter would re-declare
                    # start_milestone_work and risk a second, spurious
                    # dispatch on the exact turn Strike Team just launched
                    # from. Same STABLE shape the task-scoped path already
                    # uses for this moment, same social_response mechanism,
                    # proven and tested there already.
                    status = "STABLE"
                    data_patch = gate_context["bricks"]
                    brief = gate_context["brief"]
                    appendix = gate_context["appendix"]
                    social_response = await SocialEngine.run_turn(envelope)

            return {
                "social_response": social_response,
                "status": status,
                "data_patch": data_patch,
                "brief": brief,
                "appendix": appendix,
                "tool_call": tool_call,
                "chat_summary": envelope.chat_summary if chat_computed else None,
                "chat_summary_cursor": envelope.chat_summary_cursor if chat_computed else None,
                "trigger_log": trigger_log,
                "chat_whisper": envelope.chat_whisper,
                "gate_status": gate_status,
                "whisper": envelope.gatekeeper_whisper,
                "assessments": assessments,
            }

        # 3. Detect readiness -- gate-driven, not keyword matching. Fred's
        # explicit design: he tried "go"/"yes"/etc. substring matching before
        # and abandoned it as unreliable (real bug: "grow"/"good" false-
        # trigger it). Gatekeeper is computed once here (not duplicated inside
        # run_turn) and threaded through envelope.gatekeeper_whisper for the PM
        # to read -- same scratch-field pattern as kaiser_mandate.
        # resolve_required_questions() prefers Requirements' real derived
        # output (milestone_config's derived_requirements) once it exists,
        # falling back to the static required_questions field otherwise.
        #
        # Gatekeeper is the one real declared gate mechanism now -- it used to
        # run alongside a separate, undeclared "Clerk" audit inside
        # run_turn() (its own LLM call, its own criteria, its own
        # physics_open, reading the static required_questions field only,
        # never Requirements' derived output) that independently drove
        # envelope.physics_open/status. Retired: physics_open is now always
        # exactly `ready` (Gatekeeper's own gate_status == GREEN), computed
        # once here, not carried over from a stale prior value on a
        # transient failure -- "ground truth" means this turn's honest
        # answer, not a cached guess.
        required_questions = resolve_required_questions(envelope.milestone_config)
        chat_computed = False
        envelope.gatekeeper_whisper = None
        envelope.chat_whisper = None

        # Guard against re-firing the Strike Team every subsequent turn once
        # already launched -- and against re-running Gatekeeper's gate check
        # post-launch too. No new persistence needed: knowledge_bricks
        # already round-trips through Backend's real ledger sync, so a
        # non-empty knowledge_bricks on a fresh read is a real, already-
        # persisted signal that the Strike Team has fired for this milestone
        # before. Now a named context fact (core/triggers.py's
        # resolve_already_fired()) both Gatekeeper's and Keymaster's real
        # trigger conditions read by name, rather than an inline local
        # variable each branch checked separately -- see that function's
        # own docstring for why the underlying check itself is unchanged.
        already_fired = resolve_already_fired(envelope)

        # The shared state threaded through this turn's trigger chain (see
        # core/triggers.py's Trigger/evaluate_triggers docstrings for the
        # full reasoning behind this shape -- an ordered, stateful
        # evaluator, not a flat independent-rule table, because Keymaster's
        # own condition genuinely needs Gatekeeper's real output, and Strike
        # Team's needs Keymaster's). Chat Manager is deliberately NOT one of
        # these triggers, on purpose, not an oversight: it runs every turn
        # unconditionally regardless of readiness state (Fred's product
        # call -- see _run_chat_manager()'s own docstring), which doesn't
        # fit any of the four real gated firing patterns (once-at-creation /
        # every-turn-until-satisfied-then-never-again / bound-to-one-piece-
        # of-work / live-in-the-moment-choice) this rework represents --
        # it's a fifth, genuinely different shape (always-on, never gated),
        # so it stays a plain unconditional call below instead.
        context = {
            "envelope": envelope,
            "required_questions": required_questions,
            "chat_summary": [],
            "strike_team_already_fired": already_fired,
            "ready": False,
            "gate_status": None,
            "assessments": None,
            "confirmed": False,
        }
        trigger_log = []

        if required_questions:
            try:
                # Always runs, launched or not -- Fred's product call:
                # staying continuously aware of the conversation is core to
                # the PM's job regardless of milestone state, unlike the
                # real triggers below. Shared with the Global Agent path --
                # see _run_chat_manager()'s own docstring.
                context["chat_summary"] = MasterOrchestrator._run_chat_manager(envelope, required_questions)
                chat_computed = True

                if already_fired:
                    # The gate has already permanently passed -- Gatekeeper's
                    # whole job (deciding whether the Strike Team should
                    # fire) is moot once it already has, so there's nothing
                    # left for it to say; gatekeeper_whisper stays None
                    # (already set above), not a stale value from some
                    # earlier turn. ready=True directly here, not re-derived
                    # via GATEKEEPER_ASSESSMENT's own action, is what keeps
                    # physics_open genuinely correct post-launch instead of
                    # silently reverting to its False default just because
                    # Gatekeeper didn't run this turn -- physics_open used
                    # to be a pure byproduct of Gatekeeper running; this is
                    # the one place that's no longer true, so it has to be
                    # set explicitly. GATEKEEPER_ASSESSMENT's own condition
                    # still runs right after regardless (required_questions
                    # is truthy here) -- its condition correctly evaluates
                    # False (already_fired), so it won't overwrite this, but
                    # the trace log still gets a real entry explaining why
                    # it didn't run this turn, not silence.
                    context["ready"] = True
                trigger_log += await evaluate_triggers([GATEKEEPER_ASSESSMENT], context)
            except Exception:
                context["ready"] = False
        envelope.physics_open = context["ready"]

        # Keymaster's and Strike Team's own triggers run unprotected by the
        # try/except above, exactly matching the pre-refactor code's own
        # error-handling scope: today, an exception inside
        # confirm_launch_intent() itself was never caught either (it sits
        # outside the try block that wraps Chat Manager/Gatekeeper) -- a
        # real, pre-existing gap, not something this refactor introduces or
        # silently changes. Unifying that scope is a genuine, separate
        # decision for later, not folded in here.
        trigger_log += await evaluate_triggers([KEYMASTER_CONFIRMATION, STRIKE_TEAM_LAUNCH], context)

        chat_summary = context["chat_summary"]

        if context.get("strike_team_launched"):
            # Social Turn
            response = await SocialEngine.run_turn(envelope)
            return {
                "social_response": response,
                "data_patch": context["bricks"],
                "brief": context["brief"],
                "appendix": context["appendix"],
                "status": "STABLE",
                "chat_summary": chat_summary if chat_computed else None,
                "chat_summary_cursor": envelope.chat_summary_cursor if chat_computed else None,
                "gate_status": context["gate_status"],
                "whisper": envelope.gatekeeper_whisper,
                "assessments": context["assessments"],
                "trigger_log": trigger_log,
                "chat_whisper": envelope.chat_whisper,
            }

        else:
            # Turn A: Social
            response = await SocialEngine.run_turn(envelope)
            status = "AUTHORIZED" if envelope.physics_open else "PROBING"
            return {
                "social_response": response,
                "status": status,
                "chat_summary": chat_summary if chat_computed else None,
                "chat_summary_cursor": envelope.chat_summary_cursor if chat_computed else None,
                "gate_status": context["gate_status"],
                "whisper": envelope.gatekeeper_whisper,
                "assessments": context["assessments"],
                "trigger_log": trigger_log,
                "chat_whisper": envelope.chat_whisper,
            }
