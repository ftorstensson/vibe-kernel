import asyncio
from pods.strike_team.hound import Hound
from pods.strike_team.specialist import Specialist
from schema.kernel_schema import AgentEnvelope

class StrikeEngine:
    @staticmethod
    async def run_industrial_strike(envelope: AgentEnvelope, brief: str):
        """
        Turn B: The Parallel Strike, per specialist:
        1. This specialist generates its own real research questions from the
           settled brief (Specialist.generate_questions() -- finishes what
           the-co-founder/industrial_sandbox.py's Step 4 started but never
           actually wired up).
        2. Parallel Hunt, one Hound per question this specialist asked.
        3. This specialist analyzes only the research it asked for.

        Replaces the previous design (3 hardcoded generic queries shared by
        the whole team) -- every specialist now asks its own questions and
        reasons over its own answers, not a pooled, undifferentiated dataset.
        treasure_chest stays global (unique source IDs across every
        specialist) since weld_links() resolves citations across the whole
        final synthesis, but each specialist's own analyze() call only sees
        the sources its own questions actually returned. Each report also
        carries its own `sources` slice through untouched -- forge_truth()
        threads this into the appendix (content.appendix[i].sources) instead
        of discarding it, matching what ExecutivePaperNode's "Sources" tab
        actually reads.
        """
        print("--- 🛠️ STRIKE TEAM: INITIALIZING PER-SPECIALIST HUNT ---")

        specialists = envelope.milestone_config.get('specialists', [])
        reports = []
        treasure_chest = {}
        source_counter = 1

        for entry in specialists:
            # Backward compatible: a bare role-name string (today's shape) gets
            # no identity. A dict {"role_name": ..., "identity": {...}} (the
            # richer shape Backend is resolving from real AGENT entities) gets
            # its archetype/persona/exobrain composed into the mandate.
            if isinstance(entry, dict):
                role = entry.get("role_name") or entry.get("role") or "SPECIALIST"
                identity = entry.get("identity")
            else:
                role = entry
                identity = None

            # 1. SCOUTING -- this specialist's own real questions
            questions = Specialist.generate_questions(role, brief, identity=identity)
            print(f" -> {role} asked: {questions}")

            # 2. PARALLEL HUNT for this specialist's own questions
            hunt_tasks = [asyncio.to_thread(Hound.hunt, q) for q in questions]
            hunt_results = await asyncio.gather(*hunt_tasks)

            # 3. CONSOLIDATE this specialist's own slice of the treasure chest
            specialist_sources = {}
            all_raw_data = ""
            for result in hunt_results:
                all_raw_data += f"\n{result['raw_research']}"
                for source in result['sources']:
                    sid = str(source_counter)
                    specialist_sources[sid] = source
                    treasure_chest[sid] = source
                    source_counter += 1

            # 4. SPECIALIST ANALYSIS over only its own research
            print(f" -> {role} is analyzing data...")
            analysis = Specialist.analyze(
                role_name=role,
                research_data={"raw_research": all_raw_data, "sources": specialist_sources},
                identity=identity
            )
            reports.append({
                "role": role,
                "content": analysis,
                "questions": questions,
                "sources": specialist_sources,
            })

        return {"reports": reports, "treasure_chest": treasure_chest}
