import re
from core.bootloader import SovereignBootloader
from core.brief import derive_brief
from core.clock import TheClock
from core.coverage import assess_coverage, resolve_required_questions
from core.ignition import confirm_launch_intent
from core.reconcile import build_durable_facts
from pods.social.engine import SocialEngine
from pods.strike_team.engine import StrikeEngine
from pods.synthesis.engine import SynthesisEngine
from schema.kernel_schema import AgentEnvelope

class MasterOrchestrator:
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
            # so it doesn't run. Nothing below this block is touched by this branch.
            response = await SocialEngine.run_global_turn(envelope)
            return {"social_response": response, "status": "GLOBAL"}

        # 3. Detect readiness -- gate-driven, not keyword matching. Fred's
        # explicit design: he tried "go"/"yes"/etc. substring matching before
        # and abandoned it as unreliable (real bug: "grow"/"good" false-
        # trigger it). Coverage is computed once here (not duplicated inside
        # run_turn) and threaded through envelope.coverage_whisper for the PM
        # to read -- same scratch-field pattern as kaiser_mandate.
        # resolve_required_questions() prefers Requirements' real derived
        # output (milestone_config's derived_requirements) once it exists,
        # falling back to the static required_questions field otherwise.
        required_questions = resolve_required_questions(envelope.milestone_config)
        durable_facts = []
        ready = False
        envelope.coverage_whisper = None
        if required_questions:
            try:
                durable_facts = build_durable_facts(envelope.history)
                # Coverage's real L1 (judge archetype)/L3 (mission+app_manual)/
                # skill (the assessment procedure), the same resolution path
                # Requirements uses -- not a hand-written mandate baked into
                # assess_coverage() itself.
                identity = await SovereignBootloader.resolve_function_identity(envelope.app_id, "Coverage")
                coverage = assess_coverage(
                    required_questions, durable_facts,
                    identity["l1"], identity["l3"], identity["skill"],
                )
                envelope.coverage_whisper = coverage.get("whisper")
                ready = coverage.get("gate_status") == "GREEN"
            except Exception:
                ready = False

        # Guard against re-firing every subsequent turn once already
        # launched. No new persistence needed: knowledge_bricks already
        # round-trips through Backend's real ledger sync, so a non-empty
        # knowledge_bricks on a fresh read is a real, already-persisted
        # signal that the Strike Team has fired for this milestone before.
        already_fired = bool(envelope.knowledge_bricks)

        if ready and not already_fired and confirm_launch_intent(envelope.history):
            print(f"[ORCHESTRATOR] Strike Team Authorized (gate-driven).")

            # The settled brief -- Phase 1 (core/brief.py), not gated/fail-open
            # like Coverage's whisper since firing at all already implies
            # gate_status GREEN; built from the same durable facts pipeline
            # as Coverage, so it can't be built on a fact that already
            # scrolled out of view. Already computed above for the readiness
            # check -- reused here, not recomputed.
            brief = derive_brief(envelope.milestone_config.get("output", ""), durable_facts)

            # Specialists/Hound only need the brief as readable text -- the
            # structured {identity_narrative, founding_voice} shape below is
            # for the final response/UI (content.brief), a separate concern.
            brief_text = brief.get("identity_narrative", "")
            if brief.get("founding_voice"):
                quotes = "\n".join(f'- "{q}"' for q in brief["founding_voice"])
                brief_text = f"{brief_text}\n\nIN THE DIRECTOR'S OWN WORDS:\n{quotes}"

            # Turn B: Parallel Hunt
            strike_results = await StrikeEngine.run_industrial_strike(envelope, brief_text)

            # Turn C: Synthesis -- bricks (the paper sections) and appendix
            # (each specialist's own raw report + sources) are genuinely
            # different things now, not one blended dict.
            synthesis = await SynthesisEngine.forge_truth(
                specialist_outputs=strike_results['reports'],
                milestone_config=envelope.milestone_config
            )
            bricks = synthesis['bricks']
            appendix = synthesis['appendix']

            # The Weld (Inject Links) -- both the synthesized sections and
            # each specialist's own raw report can carry [N] citations back
            # to the same global treasure_chest.
            for key, content in bricks.items():
                if isinstance(content, str):
                    bricks[key] = MasterOrchestrator.weld_links(content, strike_results['treasure_chest'])
            for entry in appendix:
                if isinstance(entry.get('content'), str):
                    entry['content'] = MasterOrchestrator.weld_links(entry['content'], strike_results['treasure_chest'])

            # Update Knowledge -- only the flat brick_id->prose bricks belong
            # in knowledge_bricks (bootloader.py's de-loading and TheClock's
            # compression both assume that flat shape); appendix/brief are
            # carried in the response instead, not folded in here -- same
            # reasoning as why they can't be smuggled into data_patch either.
            envelope.knowledge_bricks.update(bricks)
            envelope.kaiser_mandate = "RESEARCH COMPLETE. Discuss the new findings."

            # Social Turn
            response = await SocialEngine.run_turn(envelope)
            return {
                "social_response": response,
                "data_patch": bricks,
                "brief": brief,
                "appendix": appendix,
                "status": "STABLE"
            }

        else:
            # Turn A: Social
            response = await SocialEngine.run_turn(envelope)
            status = "AUTHORIZED" if envelope.physics_open else "PROBING"
            return {"social_response": response, "status": status}

    @staticmethod
    def weld_links(text, treasure_chest):
        def replace(match):
            source_id = match.group(1)
            if source_id in treasure_chest:
                s = treasure_chest[source_id]
                return f"[{s['title']}]({s['url']})"
            return f"[{source_id}]"
        return re.sub(r'\[(\d+)\]', replace, text)
