from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder


def _build_synthesis_schema(architecture: list):
    """research_architecture entries are {id, headline, intent_blurb,
    is_archived, type} -- matches how vibe-design-lab's ExecutivePaperNode
    actually reads paper content (content[brick.id]), replacing the old
    research_summary_structure's plain key/name shape. One string value per
    id (prose or Markdown)."""
    ids = [
        b["id"] for b in architecture
        if isinstance(b, dict) and b.get("id") and not b.get("is_archived")
    ]
    if not ids:
        return None
    return {
        "type": "object",
        "properties": {i: {"type": "string"} for i in ids},
        "required": ids,
    }


class SynthesisEngine:
    @staticmethod
    async def forge_truth(specialist_outputs: list, milestone_config: dict):
        """Turn C: Synthesis. Two genuinely different outputs, not one:

        1. bricks -- the Editor-in-Chief actually welds the specialists' raw
           research into the named paper sections (research_architecture),
           one real LLM synthesis call, TYPE-aware (TEXT vs VISUAL_SPEC) same
           as before.
        2. appendix -- each specialist's own raw report and own real sources,
           untouched, one {role, content, sources} entry per specialist. Not
           re-synthesized -- it already exists after the Strike phase
           (StrikeEngine now threads `sources` through per report instead of
           discarding it) and matches what ExecutivePaperNode's "Deep
           Research" tab actually reads (content.appendix[i].{role, content,
           sources}), restoring the real v32.0-era trail-data contract.

        Returns {bricks, appendix} -- callers should update knowledge_bricks
        from `bricks` only (the flat brick_id->prose contract callers already
        depend on) and carry `appendix` separately, not merge it in."""
        model, config = AgentFactory.get_partner_pm()

        architecture = milestone_config.get('research_architecture', [])

        structure_listing = "\n".join(
            f"- id={b['id']} type={b.get('type', 'TEXT')}: {b.get('headline', '')} -- {b.get('intent_blurb', '')}"
            for b in architecture
            if isinstance(b, dict) and b.get("id") and not b.get("is_archived")
        ) or "(no defined sections -- use your own judgment on what to name each finding)"

        mandate = """
        ACT AS THE EDITOR-IN-CHIEF.
        Synthesize the raw specialist research into the named sections below.
        Write real content for every section id listed, grounded in its
        headline and intent -- not a generic restatement of the brief.

        LAW: You MUST check the TYPE of each section.
        - If TYPE is 'TEXT': Write a dense, strategic summary.
        - If TYPE is 'VISUAL_SPEC': Write a high-fidelity TECHNICAL SPECIFICATION (Markdown) that a designer or UI agent can use to build an image/component.

        LAW: Preserve [ID] citations. Return ONLY JSON.
        """

        lens = f"SECTIONS:\n{structure_listing}\nTONE: Goldsmith (Venture-Grade)."
        truth = f"RAW_SPECIALIST_REPORTS: {specialist_outputs}"

        work_order = PromptBuilder.assemble(mandate=mandate, lens=lens, truth=truth)
        response = model.generate_content(
            work_order,
            generation_config=config,
            response_schema=_build_synthesis_schema(architecture)
        )
        bricks = hammer_json(get_clean_text(response))

        appendix = [
            {
                "role": report.get("role"),
                "content": report.get("content"),
                "sources": report.get("sources", {}),
            }
            for report in specialist_outputs
        ]

        return {"bricks": bricks, "appendix": appendix}
