import uuid

from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder

RECONCILE_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {"type": "string", "enum": ["new", "revision", "contradiction"]},
        "matched_fact_id": {"type": ["string", "null"]},
        "merged_content": {"type": ["string", "null"]},
        "needs_confirmation": {"type": "boolean"},
        "clarifying_question": {"type": ["string", "null"]},
    },
    "required": [
        "classification",
        "matched_fact_id",
        "merged_content",
        "needs_confirmation",
        "clarifying_question",
    ],
}


def reconcile_fact(existing_facts, new_item):
    """Standalone, Phase 1 only -- not wired into any real flow. Given the
    current durable facts/decisions list (each entry an extract_facts()-style
    item plus an `id` and `status`, "current" or "superseded") and one newly
    extracted item, decides how the new item relates to what's already known:

    1. NEW/UNRELATED -- doesn't touch anything existing. Appended as-is
       (status "current", fresh id).
    2. REVISION -- the same underlying decision, more detail. Same lineage:
       the existing entry is enriched in place, not duplicated.
    3. CONTRADICTION -- genuinely conflicts with an existing entry. The old
       entry is marked "superseded" (never deleted) and the new one is added
       as current, both staying in the returned list as a real traceable
       log. Also flags needs_confirmation and a short clarifying question --
       the await-confirmation pattern, not silent auto-resolution.

    Returns {facts, needs_confirmation, clarifying_question}."""
    model, config = AgentFactory.get_summarizer()

    facts_listing = "\n".join(
        f"- id={f['id']} status={f.get('status', 'current')}: [{f['type']}] {f['content']}"
        for f in existing_facts
    )

    mandate = (
        "You are a fact-reconciliation function. Given a list of existing durable "
        "facts/decisions (each with an id) and one newly extracted item, decide "
        "exactly one classification:\n"
        "1. NEW: the item doesn't touch anything existing -- a genuinely separate "
        "fact/decision/preference/story. matched_fact_id: null, merged_content: "
        "null.\n"
        "2. REVISION: the item is the same underlying decision as an existing "
        "entry, just more detail or refinement -- not a change of mind. Set "
        "matched_fact_id to that entry's id, and merged_content to the enriched "
        "content combining the old entry with the new detail.\n"
        "3. CONTRADICTION: the item genuinely conflicts with an existing entry -- "
        "a real change, not an elaboration. Set matched_fact_id to the entry it "
        "conflicts with. merged_content: null.\n"
        "needs_confirmation is true ONLY for CONTRADICTION -- never silently "
        "auto-resolve a real conflict. In that case also give a short "
        "clarifying_question the PM should ask the user, e.g. 'we'd decided X "
        "before, this sounds different -- still the plan, or has it changed?' "
        "For NEW and REVISION, needs_confirmation is false and clarifying_question "
        "is null."
    )
    truth = (
        f"EXISTING FACTS:\n{facts_listing}\n\n"
        f"NEW ITEM: [{new_item['type']}] {new_item['content']} "
        f"(speaker: {new_item['speaker']}, turn {new_item['turn_index']})"
    )

    work_order = PromptBuilder.assemble(mandate=mandate, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=RECONCILE_SCHEMA)
    verdict = hammer_json(get_clean_text(response))

    facts = list(existing_facts)
    classification = verdict["classification"]

    if classification == "new":
        facts.append({**new_item, "id": str(uuid.uuid4()), "status": "current"})
    elif classification == "revision":
        for f in facts:
            if f["id"] == verdict["matched_fact_id"]:
                f["content"] = verdict["merged_content"]
                break
    elif classification == "contradiction":
        for f in facts:
            if f["id"] == verdict["matched_fact_id"]:
                f["status"] = "superseded"
                break
        facts.append({
            **new_item,
            "id": str(uuid.uuid4()),
            "status": "current",
            "supersedes": verdict["matched_fact_id"],
        })

    return {
        "facts": facts,
        "classification": classification,
        "needs_confirmation": verdict["needs_confirmation"],
        "clarifying_question": verdict["clarifying_question"],
    }
