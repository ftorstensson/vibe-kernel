import difflib
import re
import uuid

from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder
from core.summarizer import extract_facts


def _resolve_fact_id(claimed_id, facts):
    """Defends against the model echoing matched_fact_id with a dropped or
    altered character -- confirmed to happen for real, not hypothetical (a
    CONTRADICTION's supersedes id came back missing one character live,
    silently failing the old exact-match check and leaving a stale entry
    marked current forever). Exact match first; if that fails, fuzzy-match
    against the real ids and only accept a close, confident match -- UUIDs
    are long enough that a genuine near-miss (1-2 dropped/swapped chars)
    scores far above a truly different, unrelated UUID, so a high cutoff
    stays safe. Returns None (not a guess) if nothing matches confidently."""
    if not claimed_id:
        return None
    real_ids = [f["id"] for f in facts]
    if claimed_id in real_ids:
        return claimed_id
    close = difflib.get_close_matches(claimed_id, real_ids, n=1, cutoff=0.9)
    return close[0] if close else None

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
       the existing entry is enriched in place, not duplicated. turn_index and
       speaker are updated to the newest contributing turn, but nothing is
       dropped: the pre-merge (content, turn_index, speaker) is pushed onto
       the entry's `revision_trail` first, so a fact revised 2-3+ times still
       traces back to the exact raw wording from every turn that shaped it,
       not just the latest.
    3. CONTRADICTION -- genuinely conflicts with an existing entry. The old
       entry is marked "superseded" (never deleted) and the new one is added
       as current, both staying in the returned list as a real traceable
       log. Also flags needs_confirmation and a short clarifying question --
       the await-confirmation pattern, not silent auto-resolution.

    Returns {facts, needs_confirmation, clarifying_question}."""
    model, config = AgentFactory.get_summarizer()

    facts_listing = "\n".join(
        f"- id={f['id']} status={f.get('status', 'current')} type={f['type']}: {f['content']}"
        for f in existing_facts
    )

    mandate = (
        "You are a fact-reconciliation function. Given a list of existing durable "
        "facts/decisions (each with an id) and one newly extracted item, decide "
        "exactly one classification:\n"
        "1. NEW: the item doesn't touch anything existing -- a genuinely separate "
        "fact/decision/preference/story. matched_fact_id: null, merged_content: "
        "null.\n"
        "2. REVISION: the item is about the exact same specific claim as an "
        "existing entry -- correcting it, quantifying it, or adding a missing "
        "detail to that SAME thing -- not a change of mind. Set matched_fact_id "
        "to that entry's id, and merged_content to the enriched content "
        "combining the old entry with the new detail.\n"
        "   NOT ENOUGH FOR REVISION: being about the same broader idea or "
        "project, coming up near each other in the conversation, or sharing a "
        "topic. Two genuinely separate pieces of information about the same "
        "idea -- e.g. the core mechanic, who it's for, and a guiding principle "
        "-- are three separate facts, not revisions of one another, no matter "
        "how related or close together they came up. Test: strip away the "
        "surrounding conversation -- would this item and the existing entry be "
        "answering the exact same specific question? If not, it's NEW. When "
        "genuinely unsure, prefer NEW over REVISION -- a wrongly-split fact "
        "only costs a little redundancy; a wrongly-merged fact permanently "
        "loses the ability to tell which specific thing was actually settled.\n"
        "3. CONTRADICTION: the item genuinely conflicts with an existing entry -- "
        "a real change, not an elaboration. Set matched_fact_id to the entry it "
        "conflicts with. merged_content: null.\n"
        "needs_confirmation is true ONLY for CONTRADICTION -- never silently "
        "auto-resolve a real conflict. In that case also give a short "
        "clarifying_question the PM should ask the user, e.g. 'we'd decided X "
        "before, this sounds different -- still the plan, or has it changed?' "
        "For NEW and REVISION, needs_confirmation is false and clarifying_question "
        "is null.\n"
        "NOTE ON FORMATTING: 'id=... status=... type=...' in EXISTING FACTS below "
        "is metadata for you to read, not literal text -- merged_content must be "
        "clean prose only, never prefixed with a type tag or any of this "
        "bookkeeping notation."
    )
    truth = (
        f"EXISTING FACTS:\n{facts_listing}\n\n"
        f"NEW ITEM: type={new_item['type']}: {new_item['content']} "
        f"(speaker: {new_item['speaker']}, turn {new_item['turn_index']})"
    )

    work_order = PromptBuilder.assemble(mandate=mandate, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=RECONCILE_SCHEMA)
    verdict = hammer_json(get_clean_text(response))
    if verdict.get("merged_content"):
        # Belt-and-suspenders alongside the prompt fix above: strip any leading
        # "[...]"/"type=..." style tag the model echoes from the EXISTING FACTS
        # formatting instead of treating it as read-only metadata.
        verdict["merged_content"] = re.sub(
            r"^\s*(\[[^\]]*\]|type=\S+:)\s*", "", verdict["merged_content"]
        )

    facts = list(existing_facts)
    classification = verdict["classification"]

    resolved_id = _resolve_fact_id(verdict.get("matched_fact_id"), facts) if classification != "new" else None

    if classification == "new":
        facts.append({**new_item, "id": str(uuid.uuid4()), "status": "current"})
    elif classification == "revision" and resolved_id:
        for f in facts:
            if f["id"] == resolved_id:
                # Traceability: merging content into this entry would otherwise
                # silently drop the turn_index/speaker of whichever turn is
                # overwritten, breaking the ability to trace a fact back to its
                # exact raw wording after 2+ revisions. Snapshot the pre-merge
                # state into revision_trail before overwriting, so every turn
                # that ever contributed stays inspectable, not just the latest.
                trail = f.setdefault("revision_trail", [])
                trail.append({
                    "content": f["content"],
                    "turn_index": f["turn_index"],
                    "speaker": f["speaker"],
                })
                f["content"] = verdict["merged_content"]
                f["turn_index"] = new_item["turn_index"]
                f["speaker"] = new_item["speaker"]
                break
    elif classification == "contradiction" and resolved_id:
        for f in facts:
            if f["id"] == resolved_id:
                f["status"] = "superseded"
                break
        facts.append({
            **new_item,
            "id": str(uuid.uuid4()),
            "status": "current",
            "supersedes": resolved_id,
        })
    elif classification in ("revision", "contradiction"):
        # Couldn't confidently resolve which entry the model meant -- rather
        # than silently no-op (losing new_item entirely) or guess wrong,
        # fall back to treating it as its own fact. Same principle as the
        # REVISION-vs-NEW tightening above: an unresolved merge/supersede is
        # exactly the "genuinely unsure" case that should never be guessed.
        facts.append({**new_item, "id": str(uuid.uuid4()), "status": "current"})

    return {
        "facts": facts,
        "classification": classification,
        "needs_confirmation": verdict["needs_confirmation"],
        "clarifying_question": verdict["clarifying_question"],
    }


def build_durable_facts(turns):
    """Standalone, Phase 1 only -- not wired into any real flow except (as of
    this pass) Coverage's own turn. Runs extract_facts() over the full
    conversation (not a trailing window -- an early fact must not disappear
    just because the conversation got long) and folds each item through
    reconcile_fact() in order, so the result is one clean current list: new
    facts appended, revisions merged with lineage preserved, contradictions
    superseded rather than silently overwritten. Recomputed fresh each call
    rather than persisted -- Kernel has no write path to Firestore today, so
    there is nowhere durable to accumulate this across real turns yet; running
    extract_facts() over the whole history each time gets the same *result*
    (a deduplicated current-facts list immune to window loss) without adding
    a new persistence layer this pass didn't ask for."""
    items = extract_facts(turns)
    facts = []
    for item in items:
        result = reconcile_fact(facts, item)
        facts = result["facts"]
    return facts
