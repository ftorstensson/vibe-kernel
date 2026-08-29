from core.agent_factory import AgentFactory
from core.kernel_utils import get_clean_text, hammer_json
from core.prompt_builder import PromptBuilder

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "type": {"type": "string", "enum": ["preference", "decision", "fact", "story", "agreement"]},
                    "speaker": {"type": "string", "enum": ["user", "assistant"]},
                    "turn_index": {"type": "integer"},
                    "bucket": {"type": "string", "enum": ["Core Topic", "Sub Topics", "Miscellaneous"]},
                    "resolution_status": {"type": "string", "enum": ["unresolved", "settled"]},
                },
                "required": ["content", "type", "speaker", "turn_index", "bucket", "resolution_status"],
            },
        }
    },
    "required": ["items"],
}


def extract_facts(turns, required_questions=None, purpose=None):
    """Standalone, Phase 1 only -- not wired into run_turn/run_global_turn or
    any real conversation flow. Structured fact extraction instead of prose
    summarization: research shows prose summaries silently drop specific
    details because every item competes for space in one narrative.
    Returns a list of discrete items, each with its type and the index of
    the source turn it came from -- so the original wording is always
    traceable, not just paraphrased away.

    bucket/status are Chat Manager's Sorter Step (Test Run 1 / Phase 1 of
    the Six-Layer OS taxonomy pass, confirmed by Fred against the Chat
    Manager canvas board's "CHAT SUMMARY NEW" spec): required_questions and
    purpose are the milestone context needed to judge bucket (relevance),
    optional since not every caller has milestone scope (e.g. a bare
    conversation with no milestone yet) -- bucket defaults to whatever the
    model judges without that context (Miscellaneous is the safe default
    absent any milestone to be relevant TO)."""
    model, config = AgentFactory.get_summarizer()

    numbered_turns = "\n".join(f"{i}: [{t['role']}] {t['content']}" for i, t in enumerate(turns))

    mandate = (
        "You are a fact-extraction function. Given a numbered conversation, extract "
        "only what's genuinely worth remembering -- skip anything fungible or "
        "distillable later. Do NOT extract small talk, the assistant's own process "
        "narration, or its questions and acknowledgments -- those are replaceable, "
        "not worth preserving.\n"
        "Extract only:\n"
        "1. Anything the user stated as a preference, decision, fact, or story -- "
        "keep close to their own words, never dropped or softened. This is the "
        "Non-Googleable stuff: the specific intent, the twist, the grit -- not "
        "something that could be reconstructed later. A hedge in the phrasing "
        "does NOT disqualify it -- a tentative suggestion that still contains "
        "real proposed content (a number, a mechanism, a direction) counts just "
        "as much as a confident one. When capturing a hedged item, keep the "
        "hedge in the wording itself (e.g. 'floated the idea that...', "
        "'suggested, without committing, that...') rather than restating it as "
        "settled -- your job is to capture content faithfully, including how "
        "firm or tentative it was, not to judge how settled it is. But do NOT "
        "extract turns where the user "
        "explicitly withholds or defers the content itself ('not sure yet, "
        "let's come back to that', 'I don't have an opinion', 'no preference "
        "either way') or is doing session bookkeeping ('that's it for today', "
        "'let's move on') -- unlike a hedged-but-substantive suggestion, these "
        "offer no actual content to preserve.\n"
        "2. A genuine conclusion or agreement actually reached in the conversation "
        "(e.g. the team agreeing on a direction) -- not a rhetorical question or a "
        "mid-argument remark.\n"
        "Requests to do something later (reminders, follow-ups, 'check X next "
        "week') are neither preferences nor decisions -- do not extract them. If "
        "an item doesn't genuinely fit one of the categories above, leave it out "
        "rather than forcing it into the closest-sounding type.\n"
        "For each item, give its type, which turn number it came from, and the "
        "speaker of that turn (read the speaker directly off the turn's own role "
        "label -- do not guess).\n"
        "Also give each item a bucket and a resolution_status, two independent "
        "judgments, neither one determined by the other:\n"
        "BUCKET -- relevance to the milestone's own required questions and purpose "
        "(given below, if any):\n"
        "  Core Topic: directly answers or bears on one of the required questions.\n"
        "  Sub Topics: related to the milestone's purpose/domain, adds context or "
        "elaboration, but doesn't map onto any single required question directly.\n"
        "  Miscellaneous: doesn't relate to the milestone's purpose or required "
        "questions at all -- a genuine aside that still cleared the bar above (a "
        "real preference/decision/fact/story, not small talk).\n"
        "  If no required questions or purpose are given below, judge Core Topic "
        "vs. Sub Topics by whether the item is central to the main thread of the "
        "conversation itself; Miscellaneous still means a genuine aside.\n"
        "RESOLUTION_STATUS -- whether the conversation actually resolved this, "
        "never assumed just because something was extracted:\n"
        "  unresolved: raised, floated, discussed, or proposed -- but not actually "
        "settled. A hedge in the wording (see above) is a strong signal for "
        "unresolved, but judge the actual content, not just the phrasing -- a "
        "firmly-stated fact can still be unresolved if the conversation moved on "
        "without confirming it, and a hedged suggestion can still be settled if a "
        "later turn confirms it.\n"
        "  settled: the conversation shows a genuine resolution or confirmation of "
        "this specific thing -- not just that it was said once."
    )
    truth = f"CONVERSATION (numbered):\n{numbered_turns}"
    if required_questions:
        truth += f"\n\nMILESTONE REQUIRED QUESTIONS:\n{required_questions}"
    if purpose:
        truth += f"\n\nMILESTONE PURPOSE:\n{purpose}"

    work_order = PromptBuilder.assemble(mandate=mandate, truth=truth)
    response = model.generate_content(work_order, generation_config=config, response_schema=EXTRACTION_SCHEMA)
    return hammer_json(get_clean_text(response)).get("items", [])
