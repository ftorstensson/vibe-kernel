# C1 — The Briefing contract (Backend → Kernel)

**Status:** Milestone 0 design document, Kernel 3, 2026-09-21. DESIGN ONLY: no product code, nothing committed or pushed.
**Match statement:** this matches "The Big Picture" (Backend writes every prompt including headings and scaffold, saves an exact copy before the call, sends one finished Briefing; Kernel takes it, calls the model, returns the answer, forgets everything, writes no prompts, sequences nothing) and Markdown 27 (rule 4 "saved equals sent", rule 5 "one Briefing in, one model call, one result out", work package K1). I found nothing that differs from an approved visual or from the plan. Revision 1's nine open questions were answered by the PM on 2026-09-21 (section 9.1); the four small details in section 9.2 were answered as well, so nothing in C1 remains open.
**Evidence base:** Kernel code at deployed commit `6fa822e` (tree identical to the worktree HEAD `925235b`, so all `file:line` citations are valid for the deployed code); the 16 model-call sites; `core/agent_factory.py`; measurements against the real model taken 2026-09-21 (section 8). Anything not verified is marked UNVERIFIED.

**Revision 2, 2026-09-21.** The PM's Milestone 0 decisions are folded in and marked "PM decision 2026-09-21" wherever they change or settle something. The nine open questions of revision 1 are now decisions (section 9); the four small details in section 9.2 were answered as well, so nothing in C1 remains open. Fable reviews C1, C2 and C3 together; Backend 2 cross-reviews C1 against C2 and C3.

**Revision 3, 2026-09-21** (Backend's cross-review and Fable's review; Fable confirms Kernel/Big-Picture conformance and rates C1 "ready after the listed changes"). Changes, each marked "PM decision 2026-09-21": (1) `request_sha256` is now a REQUEST field with its own 422 code `request_sha_mismatch` (section 2, 5.2, T3/T13/T15); (2) provider errors return the CATEGORY, the provider status and a FIXED GENERIC message; raw provider text stays only in Kernel's logs (section 4.4, T11, R1); (3) timeout wording corrected: Kernel's maximum MODEL timeout is 280 s and Backend's HTTP timeout is the call's `timeout_s` + 15 (R4); (4) tests are split into M1a and AFTER THE CORE (section 6); (5) a measurement of fenced or trailing-text structured output during M1a (section 4.3).

---

## 1. What the contract is

One HTTP request carries ONE Briefing. One Briefing = ONE string of prompt text plus the parameters needed to make exactly one model call. Kernel makes exactly one model call and returns one result. The prompt string is sent to the model verbatim as the only message. Kernel does not build, edit, normalize, split, join, template or "fix" it, does not read any file or registry, does not look at any other request, and does not call the model a second time for any reason.

The Briefing schema below is derived only from what the 16 call sites and `core/agent_factory.py` actually pass to the model today (section 3 shows the derivation), plus the extra fields the plan requires (attempt id, call label, segments, parse mode, timeout) and the flagged additions in section 7.

## 2. Request: `Briefing` (exact schema)

JSON object. Unknown top-level keys are rejected (HTTP 422). `null` means "do not send this parameter to the model". Every key below must be present (explicit `null` where not used) so that a missing key is a Backend bug, not an implicit default.

| Field | Type | Rule | Derived from |
|---|---|---|---|
| `contract_version` | integer, literal `1` | any other value is rejected | new |
| `attempt_id` | string, 1–128 chars, printable ASCII | opaque; Kernel echoes it unchanged; never interpreted, never used for de-duplication | plan C1 |
| `call_label` | string, 1–128 chars, printable ASCII | opaque; echoed; the label vocabulary is Backend's (Kernel's 16 labels `pm.run_turn` … `maintenance.compress_truth` are retired with Kernel's composition) | plan C1; today `label=` at every site |
| `prompt` | string, 1 byte … `max_prompt_bytes` (Kernel config, **4 MiB, PM decision 2026-09-21**; Backend cannot raise it, and a Briefing carrying a `max_prompt_bytes` key is rejected as an unknown field) | sent verbatim as `messages=[{"role":"user","content": prompt}]`; must be a valid sequence of Unicode scalar values (no unpaired surrogates); no normalization of any kind; CR/LF, tabs, NUL, U+2028/2029 preserved exactly | `core/agent_factory.py:90` (today the sole message is one `user` string) |
| `prompt_sha256` | string, 64 lowercase hex | **REQUIRED (PM decision 2026-09-21).** Backend's saved sha256 of the UTF-8 bytes of `prompt`. Kernel recomputes it before calling the model and refuses (HTTP 422, zero model calls) on a mismatch or when the field is missing | new |
| `request_sha256` | string, 64 lowercase hex | **REQUIRED (PM decision 2026-09-21, from Fable's review).** Backend's sha256 of the canonical JSON of every other parameter Kernel will hand to litellm (rule and test vectors in section 5.2). Kernel recomputes it from the Briefing it received and refuses (HTTP 422, code `request_sha_mismatch`, zero model calls) on a mismatch. A missing or malformed value is `invalid_briefing` | new |
| `model` | string | must be in Kernel's model allowlist (Kernel config, initially `vertex_ai/gemini-2.5-pro`, `vertex_ai/gemini-2.5-flash`); passed verbatim as litellm `model` | `agent_factory.py:154,159,164-167,172,179` |
| `temperature` | number 0–2, or null | passed as `temperature` when not null. Values in use today: 0.0, 0.1, 0.4 | `agent_factory.py:154,159,167,172,179` |
| `reasoning_effort` | `"disable"`, `"minimal"`, `"low"`, `"medium"`, `"high"`, `"none"`, or null | passed when not null (null or empty = omitted, identical to today's `if generation_config.reasoning_effort:` at `agent_factory.py:96`). Values in use: `"disable"`, `"minimal"`, none. Accepted values verified in litellm's Gemini mapper (`vertex_and_google_ai_studio_gemini.py`, `_map_reasoning_effort_to_thinking_budget`) | same |
| `max_output_tokens` | integer ≥ 1, or null | passed as `max_tokens` when not null. NOT used today (see flag F2) | new (flagged) |
| `tools` | non-empty array, or null | passed verbatim as `tools`. Allowed element shapes (Kernel allowlist): OpenAI-style function tool `{"type":"function","function":{name,description,parameters}}` and the provider-native grounding tool `{"googleSearch": {}}`. Kernel never interprets, runs or loops on a tool. An empty array is rejected (today `tools or self.tools` treats it as absent, `agent_factory.py:98-100`). **`{"googleSearch": {}}` cannot be combined with "controlled generation": not with a function tool in `tools`, and not with `response_format` — both 422 `not_allowed`, zero model calls; see section 2.3** | `pods/social/engine.py:319,415-424`; `agent_factory.py:164-167` (hound, never combined with a function tool today) |
| `tool_choice` | `"auto"`, `"required"`, `"none"`, or null | passed when not null. Only `"required"` is used today (`engine.py:481`); litellm maps it to Gemini `FunctionCallingConfig mode=ANY` (`core/orchestrator_answer.py` module docstring, verified earlier against litellm's source) | `engine.py:481` |
| `response_format` | object, or null | passed verbatim as `response_format`. Today the only shape sent is `{"type":"json_schema","json_schema":{"name":"structured_output","schema":<schema>,"strict":true}}` (`agent_factory.py:103-107`); Backend now sends this whole object, including the name and `strict`. Kernel does not build or validate the schema | `agent_factory.py:103-107` |
| `parse_mode` | `"text"`, `"json_strict"`, `"json_lenient"` | how Kernel fills `output.parsed` (section 4.3). It never changes what is sent to the model and never triggers a second call | plan C1; today `get_clean_text` / `hammer_json` at each site (section 3) |
| `timeout_s` | number, 1 … `max_timeout_s` (Kernel config, 280; see R4) | passed as litellm `timeout` and also enforced as a hard wall-clock limit by Kernel (see K1 §5). Today NO timeout is set at any site (litellm default `request_timeout` is 6000 s; Cloud Run kills the request at 300 s) | `agent_factory.py` (none); verified 2026-09-21 |
| `segments` | array of `Segment`, ≤ 2,000 entries, ≤ 256 KiB serialized | Backend-computed; **opaque to Kernel, echoed back verbatim** in the result (section 4). **Kernel only echoes them (PM decision 2026-09-21); Backend tests its own offsets.** | plan C1 |

`Segment` (defined by Backend, echoed by Kernel; extra keys inside a segment are allowed and echoed):

| Key | Type | Meaning |
|---|---|---|
| `start` | integer ≥ 0 | UTF-16 code unit offset into `prompt`, inclusive |
| `end` | integer > `start` | UTF-16 code unit offset, exclusive |
| `scaffold` | boolean | true for headings/joiners Backend wrote (no layer) |
| `layer` | `"l1"`…`"l6"` or null | null iff `scaffold` is true |
| `provenance` | object or null | Backend-defined: authored scope (Platform, App, Agent, Job) or computed producer (run id, call label) |

Kernel configuration that is NEVER part of a Briefing (PM decision 2026-09-21): `vertex_project` (env `GOOGLE_CLOUD_PROJECT`, `agent_factory.py:12`), `vertex_location` (fixed by Kernel config, today hard-coded `us-central1`, `agent_factory.py:13`), the model allowlist, the tool allowlist (function tools and `googleSearch` only), `max_prompt_bytes` (4 MiB), `max_timeout_s` (280, see R4). Backend cannot change any of these per request.

**Where the per-call values come from (PM decision 2026-09-21, answers revision 1's Q1).** `model`, `temperature`, `reasoning_effort`, `parse_mode` and `timeout_s` are authored as `call_settings` per Function (Functions Registry) and per Agent (Manifest), with platform defaults in a registry doc `call_defaults` (added to C2 by the PM). Backend resolves `call_settings` over `call_defaults` when it builds a Briefing and sends EXPLICIT values; Kernel receives no defaults and knows nothing about `call_settings`. Two related Backend-side items are not in the PM's list and are not Kernel fields: whether `call_settings` also carries `max_output_tokens` (my flag F2) and a per-call "allows truncation" switch (needed because Backend's Runner treats `finish_reason` `length` and `content_filter` as failures unless the call allows truncation, section 4). See R3 (closed: both are now in `call_settings`).

### 2.1 Exact mapping to the model call (the entire body of the executor)

```
kwargs = {
  "model": B.model,
  "messages": [{"role": "user", "content": B.prompt}],
  "vertex_project": CONFIG.project, "vertex_location": CONFIG.location,
  "timeout": B.timeout_s,
}
if B.temperature      is not None: kwargs["temperature"]      = B.temperature
if B.reasoning_effort is not None: kwargs["reasoning_effort"] = B.reasoning_effort
if B.max_output_tokens is not None: kwargs["max_tokens"]      = B.max_output_tokens
if B.tools            is not None: kwargs["tools"]            = B.tools
if B.tool_choice      is not None: kwargs["tool_choice"]      = B.tool_choice
if B.response_format  is not None: kwargs["response_format"]  = B.response_format
```

This is today's `build_request` (`core/agent_factory.py:83-108`) with the composition removed: every optional key is set iff its Briefing field is non-null, and `messages[0]["content"]` is the Briefing's `prompt` string itself.

### 2.2 Confirmation: a Briefing whose prompt already contains the layer headings and scaffold

**Confirmed: yes.** Backend can write the six-layer headings, the scaffold, blank lines and any closing line into the `prompt` string itself; the executor sends that ONE string as the only message and adds nothing: no system message, no heading, no wrapper, no template, no trailing text, no re-joining. From the executor's point of view a heading such as `## L1 — MANDATE` is ordinary text, exactly like the prose around it (the strings `### BLOCK 3: THE TRUTH` or `[EXECUTION_START: ...]` inside a Backend prompt are equally just text). Layer identity is carried only by `segments`, which Backend computes and Kernel echoes.

Evidence, run 2026-09-21 against `LiteLLMModel.build_request` (`core/agent_factory.py:83-108`, the request builder the executor keeps; the executor's mapping in section 2.1 is the same code with the composition removed). A 405-code-point prompt with `## L1` … `## L5` headings, CRLF line endings, emoji, a JSON-looking line, a backslash, trailing spaces and a stale Kernel `### BLOCK` heading produced: one message with role `user`; `content` byte-identical to the prompt (UTF-8 bytes equal); no other message; the only keys sent were `messages`, `model`, `reasoning_effort`, `response_format`, `temperature`, `vertex_location`, `vertex_project`; sha256 of the string handed to litellm equal to sha256 of the prompt. The contract test T14 makes this a permanent check.

### 2.3 `googleSearch` cannot be combined with "controlled generation"

**`{"googleSearch": {}}` may not appear in `tools` together with a function tool, and may not appear in `tools` while `response_format` is also set.** Either combination is 422 `not_allowed` (on `tools` for the first form, on `response_format` for the second), zero model calls (PM decision 2026-09-23 for the first form; extended 2026-09-25 to the second after a live M2 production failure, below).

This is ONE real Vertex/Gemini constraint with two faces, both verified:
- **Function tool + googleSearch (found 2026-09-23, static analysis only).** litellm's real Vertex/Gemini adapter silently DROPS the search tool when function declarations are also present, unless `include_server_side_tool_invocations` is set (Kernel does not set it) — verified against litellm 1.99.0's `_drop_search_tools_mixed_with_functions` (`vertex_and_google_ai_studio_gemini.py`). The call still succeeds, but the model receives no grounding tool at all, silently.
- **`response_format` + googleSearch (found 2026-09-25, from a REAL production failure — design_lab_sandbox, Milestone Desk run `46e1c79a345c`, every one of Research Agent `a_17847709250997`'s six Hound calls `hunt_0`–`hunt_5` failed).** Here litellm does NOT intervene: it maps `response_format` to `response_mime_type`/`response_json_schema` and sends both that and `tools:[{"googleSearch":{}}]` straight through (confirmed by exercising `litellm.get_optional_params` with this exact combination). The real Vertex API then REJECTS the whole call: `litellm.BadRequestError`, HTTP 400, `"Unable to submit request because controlled generation is not supported with Search tool."` (reproduced against the real API 2026-09-25, one call, using this project's default credentials; no secret touched). Hound's own call had `call_settings.grounding: true` (so `tools:[{"googleSearch":{}}]`) AND `response_format` set from its output_contract's `{findings: string}` schema — Backend's builder appends the grounding tool whenever `grounding: true` without checking whether `response_format` is also set. This stalled the Milestone Desk run silently from the end user's view (the PM had already said "kicking things off" with nothing more happening) until Backend's own `run_in_flight` bookkeeping was checked.

Because `request_sha256` is computed from the Briefing's own `tools`/`response_format` fields before the call (section 5.2), an unguarded mixed Briefing would otherwise either report false success (the function-tool case: the sha says "grounding was sent" while nothing was) or burn a real, billed, doomed API call before failing deep and unhelpfully inside Backend's Runner (the response_format case) — either way, exactly the silent or wasteful failure the sha/echo guarantees and Kernel's guardrails exist to prevent (section 5.3). Kernel refuses both combinations outright at validation instead, before any model call: a Function wanting both grounding and constrained output needs either two separate calls, or must drop `response_format` and get its structure by asking for it in the prompt text with a `parse_mode` that extracts it (`json_lenient`/`json_strict`) — in fact already Hound's OWN pattern (its L4 task text already asks in prose for "a single JSON object that conforms to this JSON Schema": Backend's `render_shape_text` output is baked into the prompt), so removing the redundant `response_format` when `grounding` is true is a straightforward Backend fix, not a capability loss.

One separate Backend-side content issue noted in passing, not a Kernel contract matter: Hound's L4 text tells the model to "Return your findings as plain prose" one paragraph before the auto-appended "Respond with a single JSON object..." instruction — those two sentences contradict each other regardless of the `response_format` fix, and this call's `parse_mode` was `"text"`, so even a successful call's JSON would never have been parsed by Kernel either.

## 3. Derivation: what each of the 16 calls needs (file:line at `6fa822e`)

"Model" is the factory tier used today: `get_clerk` (`agent_factory.py:152-154`, flash, 0.0, `"disable"`), `get_summarizer` (`:175-179`, flash, 0.0, `"disable"`), `get_partner_pm` (`:157-159`, pro, 0.4, `"minimal"`), `get_hound` (`:162-167`, flash, 0.1, no reasoning, tools `[{"googleSearch": {}}]`). `get_clinical_auditor` (`:170-172`) has no caller (dead code). Today's parse step is quoted from the call site.

| # | Call (today's label) | Model call at | Factory at | Briefing values (model / temp / reasoning) | tools / tool_choice | `response_format` (source) | Today's parse | `parse_mode` |
|---|---|---|---|---|---|---|---|---|
| 1 | `pm.run_turn` | `pods/social/engine.py:246` | `:167` | pro / 0.4 / minimal | null / null | null | `get_clean_text` `:248` | `text` |
| 2 | `pm.run_global_turn` | `engine.py:337` | `:294` | pro / 0.4 / minimal | `[start_milestone_work]` only when `project_map` non-empty (`:319`) / null | null | `get_clean_text` + first tool call (`:344-345`) | `text` (+ `tool_calls`) |
| 3 | `pm.run_global_turn_answer` | `engine.py:481` | `:426` | pro / 0.4 / minimal | subset of {reply, start_milestone_work, completion} plus always `refuse` (`:415-424`) / `"required"` | null | `resolve_orchestrator_answer` `:483` (first tool call; zero tool calls falls back to a reply from the text, `core/orchestrator_answer.py:176-178`) | `text` (+ `tool_calls`) |
| 4 | `pm.synthesize_dispatch` | `engine.py:543` | `:517` | pro / 0.4 / minimal | null / null | null | `get_clean_text` `:545` | `text` |
| 5 | `gatekeeper.assess_coverage` | `core/coverage.py:106` | `:88` | flash / 0.0 / disable | null / null | `output_shape or COVERAGE_SCHEMA` (`coverage.py:6`) | `hammer_json` `:107` | `json_lenient` |
| 6 | `keymaster.confirm_launch_intent` | `core/ignition.py:65` | `:56` (clerk) | flash / 0.0 / disable | null / null | `output_shape or LAUNCH_CONFIRM_SCHEMA` (`ignition.py:6`) | `hammer_json(...).get("confirmed")` `:66` | `json_lenient` |
| 7 | `gate_maker.derive_requirements` | `core/requirements.py:86` | `:65` | flash / 0.0 / disable | null / null | `output_shape or REQUIREMENTS_SCHEMA` (`requirements.py:6`) | `hammer_json` `:87` | `json_lenient` |
| 8 | `chat_manager.extract_facts` | `core/summarizer.py:113` | `:86` | flash / 0.0 / disable | null / null | `output_shape or EXTRACTION_SCHEMA` (`summarizer.py:6`) | `hammer_json(...).get("items", [])` `:114` | `json_lenient` |
| 9 | `chat_manager.reconcile_fact` | `core/reconcile.py:121` | `:70` | flash / 0.0 / disable | null / null | `RECONCILE_SCHEMA` (`reconcile.py:29`) | `hammer_json` `:122` | `json_lenient` |
| 10 | `strike.derive_brief` | `core/brief.py:87` | `:49` | flash / 0.0 / disable | null / null | `BRIEF_SCHEMA` (`brief.py:5`) | `hammer_json` `:88` | `json_lenient` |
| 11 | `map_summary.summarize_for_map` | `core/map_summary.py:62` | `:59` | flash / 0.0 / disable | null / null | null | `get_clean_text` `:63` | `text` |
| 12 | `synthesis.forge_truth` | `pods/synthesis/engine.py:72` | `:45` (pm) | pro / 0.4 / minimal | null / null | `_build_synthesis_schema(architecture)` (`synthesis/engine.py:6-26`), **null when the milestone has no active section** | `hammer_json` `:78` | `json_lenient` |
| 13 | `strike.specialist_questions` | `pods/strike_team/specialist.py:69` | `:41` (pm) | pro / 0.4 / minimal | null / null | `QUESTIONS_SCHEMA` (`specialist.py:5`) | `hammer_json` `:70` | `json_lenient` |
| 14 | `strike.specialist_analyze` | `specialist.py:116` | `:86` (pm) | pro / 0.4 / minimal | null / null | null | `get_clean_text` `:117` | `text` |
| 15 | `strike.hound` | `pods/strike_team/hound.py:17` | `:14` (hound) | flash / 0.1 / null | `[{"googleSearch": {}}]` / null | null | `get_clean_text` + `grounding_sources` (`hound.py:20-21`) | `text` (+ `grounding_sources`) |
| 16 | `maintenance.compress_truth` | `pods/maintenance/engine.py:19` | `:11` (clerk) | flash / 0.0 / disable | null / null | null | `get_clean_text` `:20` | `text` (call is being deleted, decision M0-D2) |

What the table shows:
- **Every parameter any call sends is covered by section 2.** The only model parameters ever set are `model`, `temperature`, `reasoning_effort`, `tools`, `tool_choice`, `response_format`, plus the two Kernel-config values. No call sets `max_tokens`, `top_p`, `top_k`, `seed`, `stop`, safety settings, a system message, streaming, or a timeout.
- **All five model-tier facts are today welded to the call site** (the factory picks model, temperature and reasoning per role, not per Briefing). In the new design they are Briefing fields, so Backend must author them somewhere (decided: `call_settings`, PM decision 2026-09-21, see section 2).
- **`parse_mode` today is either "plain text" or `hammer_json` (lenient); no site uses strict JSON.** `json_strict` is a new mode requested by the plan.
- **Tool count today:** `tools` is only ever a function tool (calls 2, 3) or the native grounding tool (call 15); `tool_choice` is only ever `"required"` (call 3).
- **Post-processing that follows the parse is NOT part of the contract** (it moves to Backend): `.get("items")`, `.get("confirmed")`, reconcile's `re.sub` cleanup of `merged_content` (`reconcile.py:123-129`), fact merging (`reconcile.py:131-231`), `weld_links` (`core/triggers.py:222-229`), brief assembly (`triggers.py:256-260`).

### 3.1 Proof of sufficiency (a test, section 6 T13)
All 230 requests in the golden baseline (`tests/step0_capture/goldens/`, 57 scenarios) must convert mechanically into a valid Briefing using only fields in section 2, and executing that Briefing must reproduce the golden litellm kwargs byte for byte. If any golden request cannot be expressed, the contract is missing a field. I have verified by inspection that every key present in the goldens (`model`, `messages`, `vertex_project`, `vertex_location`, `temperature`, `reasoning_effort`, `tools`, `tool_choice`, `response_format`) is covered; the test makes that mechanical.

## 4. Response: `ExecutionResult` (exact schema)

Always returned with HTTP 200 for any Briefing that passed validation, whether the model succeeded or the provider failed (**PM decision 2026-09-21**: provider failures return a structured result so the prompt is never lost). Contract violations, authentication failures and Kernel crashes use HTTP error codes (K1 §3). This means a failed call still returns its sha256, timing and structured error, so Test Lab can show the failed call's prompt (the case doc-26 marks as the one Test Lab needs most).

| Field | Type | Meaning |
|---|---|---|
| `contract_version` | integer | `1` |
| `attempt_id`, `call_label` | string | echoed from the request |
| `status` | `"ok"` or `"error"` | `"ok"` iff the model returned a response (even an empty or truncated one) |
| `prompt_sha256` | string, 64 lowercase hex | sha256 of the UTF-8 bytes of the EXACT string handed to litellm as `messages[0]["content"]`, computed at the single choke point immediately before the call (section 5) |
| `prompt_utf8_bytes`, `prompt_utf16_units` | integer | sizes of that string, for diagnosing mismatches |
| `request_sha256` | string, 64 hex | **adopted (PM decision 2026-09-21).** Kernel's computed value, always equal to the request's (a mismatch never reaches the model). sha256 of the canonical JSON of every other parameter handed to litellm (exact rule and test vectors in section 5.2). Covers tools, response_format, model, temperature, reasoning_effort, tool_choice, max_tokens, timeout |
| `output` | object or null | null when `status` is `"error"` (section 4.1) |
| `usage` | object or null | `{prompt_tokens, completion_tokens, reasoning_tokens}` from the provider response (null fields when the provider gives none). Verified 2026-09-21: for Gemini Pro with `reasoning_effort="minimal"` `completion_tokens` (81) INCLUDES `reasoning_tokens` (80) |
| `finish_reason` | string or null | the provider's `finish_reason` (`"stop"`, `"length"`, `"tool_calls"`, `"content_filter"`, …). See flag F1. **PM decision 2026-09-21:** `length` and `content_filter` return `status:"ok"` with `finish_reason` set; Backend's Runner treats them as failures unless the call allows truncation |
| `effective_model` | string or null | the model name the provider reports (e.g. `gemini-2.5-flash`, without the `vertex_ai/` prefix) |
| `error` | object or null | structured error (section 4.4) |
| `timing` | object | `{started_at, duration_ms}` (UTC ISO 8601; duration of the model call only) |
| `kernel` | object | `{revision, git_sha}`: `K_REVISION` (set by Cloud Run) and `KERNEL_GIT_SHA` (set at deploy) |
| `segments` | array | the request's `segments`, verbatim |

### 4.1 `output`

| Field | Type | Meaning |
|---|---|---|
| `text` | string | the model's text (`message.content or ""`, `agent_factory.py:44`). May be empty when the model answers with a tool call only |
| `tool_calls` | array | every tool call the model returned, in order: `{name, args, arguments_raw, parse_error}` where `args` is the parsed JSON object (null if unparseable), `arguments_raw` is the string the provider returned, and `parse_error` is a string or null. **Today a malformed tool call is silently dropped** (`agent_factory.py:59-64`, the `continue` at `:63`); the contract keeps it visible (flag F7). Kernel does not choose "the first" or judge legality (`engine.py:344`, `orchestrator_answer.py:180` do that today; that is the Validator's job) |
| `grounding_sources` | array | `[{title, url, redirect_url, resolved}]` from the provider's `url_citation` annotations; `title` defaults to `"Source"` when missing and is only the site name. **Google redirect links are resolved inside the call (2026-10-22, PM 14 on Fred's approval; section 4.5).** `url` is the real page when `resolved` is true, otherwise the original; `redirect_url` is always the original; `resolved` says whether the lookup succeeded. Empty when the call used no grounding. **litellm builds this list with one entry per supported sentence, from that sentence's FIRST page only**, so it is not a list of the pages the search cited and cannot carry sentence-to-page links; those are `grounding_chunks` and `grounding_supports`. Unchanged in shape, order and resolution |
| `grounding_chunks` | array | **Added 2026-10-29 (PM 14 on Fred's decision; additive and optional for readers).** Every page (chunk) the search service returned for the call, in the provider's order, each `{title, url, redirect_url, resolved}` exactly like a `grounding_sources` entry (`title` defaults to `"Source"`). This is the list `grounding_supports[].source_indices` index into. Only the chunks some support points at are resolved (section 4.5); the others are returned with `url` = `redirect_url` and `resolved: false`. A chunk that is not a web page (or is malformed) keeps its place as `{"title": "Source", "url": null, "redirect_url": null, "resolved": false}` so indices stay aligned. `[]` when the call used no grounding or the provider returned none |
| `grounding_supports` | array | **Added 2026-10-29 (additive and optional for readers).** Which sentence of `text` came from which pages, from the provider's own `groundingSupports`, in the provider's order, each `{text, start, end, source_indices}`: `text` is the supported segment; `start` / `end` are offsets into `output.text` in **characters (Python code points), end exclusive**, so `output.text[start:end] == text`; `source_indices` are indices into `grounding_chunks`, in the provider's order, duplicates within one support removed (first kept), anything not a whole number inside the chunk list dropped. A segment with no chunks keeps `source_indices: []`. **Never wrong offsets:** the provider counts UTF-8 BYTES (verified 2026-10-29 on real non-ASCII output: the segment matched as byte offsets 8 of 8 and as character offsets 0 of 8); Kernel converts them and checks that the slice equals `text`; if it does not (or the offsets are unusable), `start` and `end` are `null` and the segment is still returned. The provider omits `startIndex` when it is 0; a missing start is read as 0. Overlapping segments are kept as given. `[]` when the call used no grounding or the provider reported no supports. **For readers:** both fields are new keys; a Backend that does not know them is unaffected, and a Backend must tolerate a Kernel that does not send them (an older revision): treat an absent key as `[]` |
| `parsed` | any JSON value or null | per `parse_mode` (section 4.3) |
| `parse_error` | string or null | why `parsed` is null, when `parse_mode` is not `text` |

`text` and `tool_calls` are not mutually exclusive: a real call returned acknowledgment text AND a tool call together (`agent_factory.py:22-41`, the `LiteLLMResponse` docstring).

### 4.2 What Kernel guarantees about the call
Exactly one MODEL call per request. No retry, no repair, no re-ask on parse failure, no second model call to fetch anything. `attempt_id` is only echoed. The one other thing that leaves Kernel is the grounding-link lookup of section 4.5: plain GETs to Google's own redirect host, never a model call.

### 4.3 Parse modes (exact semantics)

| `parse_mode` | `output.parsed` | on failure |
|---|---|---|
| `text` | null | `parse_error` null |
| `json_strict` | `json.loads(output.text)` on the exact text; any JSON value | `parsed` null, `parse_error` = the exception message. NEW mode: no site does this today |
| `json_lenient` | `parse_json_lenient(output.text)` exactly as today (`core/kernel_utils.py:34-42`): `text.strip()`, strip a leading ```` ```json ```` fence and a trailing ```` ``` ```` (regex `^```json\s*|```$`, MULTILINE), `json.loads`; if the value is a list, the first element, or `{}` for an empty list; otherwise the value | `parsed` null, `parse_error` = the message. **Behavior change from today:** `hammer_json` returns the dict `{"error":"JSON_PARSE_FAILED","raw":...}` on failure (`kernel_utils.py:29-31`) and the callers keep going with it; the contract reports the failure explicitly and lets Backend's Failure Handler decide (this removes the "junk error/raw keys reach the ledger" path found in the synthesis no-schema case) |

`parse_mode` other than `text` on a response with only tool calls and empty text simply yields a parse error; it is not a Kernel failure.

**Default and one M1a measurement (PM decision 2026-09-21).** Backend's default `parse_mode` is `json_strict` (in `call_defaults`); `json_lenient` stays a per-call option, and Kernel has no default of its own (the field is required). Whether that default holds is unmeasured: today every JSON site uses the lenient `hammer_json`, so no one knows how often a structured-output reply (with `response_format`) comes back fenced or with text around it. **M1a measurement M1:** on the Phase 1.5 fixtures, for every call label that sends `response_format`, run the real Briefing N times (proposed N = 20 per label, on the real model; a few cents) and count, per label, replies where `json.loads(text)` succeeds, replies where it fails but the lenient parse succeeds (categorized: fenced block, text before, text after, other), and replies where both fail. Kernel returns `parse_error` per call already; the counts come from the `parse_mode: json_strict` results of these runs. Reported per label, with no threshold set here: a label with any strict failure is a candidate for `json_lenient` in its `call_settings`. The PM's outbound call keeps tools with `tool_choice` `required` (as C1 assumes); no oneOf structured output is used, so nothing is measured there.

### 4.5 Grounding-link resolution (added 2026-10-22; `executor/links.py`)

A grounded Gemini call returns each source as a Google redirect (`https://vertexaisearch.cloud.google.com/grounding-api-redirect/...`) with only the site name as its title. After the model call, Kernel asks each redirect where it leads, so Backend can show and number real pages (board anchor: Backend frame, HOUND & LINK LOGIC; Doc 13 "Sources and links").

- **What is requested:** one `GET` per distinct redirect, `follow_redirects` off, the body never read, no credentials, no cookies kept. The `Location` header is read.
- **Only Google's redirect is ever requested.** The URL must be exactly `https` on host `vertexaisearch.cloud.google.com`, default port, no userinfo, path starting `/grounding-api-redirect/`. Any other URL (including a direct page URL from the model) is returned untouched and nothing is fetched, so a URL in a model response can never make Kernel call an arbitrary host.
- **Bounds:** all lookups in parallel; 3 s per source; 5 s in total; at most 30 distinct redirects per call (any beyond stay unresolved). Measured on 14 real sources: 1.2 s in total.
- **Accepted answers:** status 301/302/303/307/308 with an absolute `http(s)` `Location` of at most 8192 characters without whitespace or control characters, not on Google's redirect host. It is returned exactly as sent.
- **Chunks (2026-10-29).** The chunks a support points at (`grounding_supports[].source_indices`) are resolved in the same pass as the sources: the sources first, then those chunks, one request per distinct address (the same page is not requested twice), under the same bounds. The 30-distinct cap is shared per call and the sources come first, so they resolve exactly as before; a chunk past the cap stays unresolved. A chunk no support points at is never requested. The log line counts the entries of both lists.
- **Failure never fails the call.** A timeout, network error, non-redirect status, or an unusable `Location` leaves that source as it was: `url` = the redirect, `resolved: false`. The resolver never raises into the call; the model call's `status`, `output.text`, `usage`, `finish_reason` and both shas are unaffected.
- **Not a model call; not in `timing.duration_ms`** (which stays the model call only). It adds at most 5 s after the model call, so the call still finishes inside Backend's `timeout_s + 15`. The log line records only the counts (`links_resolved=14/14 links_ms=1206`), never a URL.
- **A direct (non-redirect) URL** keeps `url` = itself, `redirect_url` = itself, `resolved: false`: nothing was resolved. A consumer that wants "is this a real page address" should not rely on `resolved` alone for those (rare for Gemini).
- **One entry per citation.** Several citations of the same page appear as separate entries with the same `url` (seen on real calls: 14 sources, 9 distinct pages); numbering and de-duplication are Backend's.
- **Tests:** `tests/m1_executor/test_links.py` (77 checks) and `tests/m1_executor/test_supports.py` (133 checks: offsets, chunks, supports, resolution through the endpoint); the network is a mock; no test makes a live request. Real example (2026-10-22, local executor, real Vertex, `gemini-2.5-flash` + `googleSearch`): title `australianunions.org.au`, redirect `https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQGc94lftllN6iY9bxhdpq5dHGhnH8VsBySKhzM776p09s4_...`, resolved `https://www.australianunions.org.au/factsheet/minimum-wage/`.

### 4.4 `error`

`{type, retryable, provider_status, message}`. **PM decision 2026-09-21 (from Backend's cross-review; replaces the earlier "500 characters, secrets scrubbed" return):** the body carries the error CATEGORY (`type`), the provider status code and a FIXED GENERIC `message` per category, and NEVER any text from the provider or from the exception. Reason: the read API is unauthenticated until after the core, and a provider not-found error echoes the GCP project path (measured, below). The raw provider text stays only in Kernel's own logs, keyed by `attempt_id` and `call_label` (so an operator can look it up), with the prompt-substring and credential scrubbing described in K1 §8 applied to the log line as well (my addition; the PM said the scrubbing "may stay for Kernel's own logs"). Measured 2026-09-21 against the real provider (litellm 1.99.0):

| Case | litellm class (observed) | `provider_status` | `type` | fixed generic `message` | `retryable` |
|---|---|---|---|---|---|
| request timeout, or Kernel's own wall-clock limit fired | `litellm.Timeout` (raw: "Connection timed out after None seconds"); or `asyncio.TimeoutError` from Kernel's `wait_for` | 408 (null for Kernel's own limit) | `timeout` | "The model call timed out." | true |
| unknown model id | `litellm.NotFoundError` (raw echoes `projects/<project>/locations/...`) | 404 | `model_not_found` | "The requested model was not found." | false |
| bad `response_format` schema | `litellm.BadRequestError` (raw: "Invalid response_json_schema: ...") | 400 | `bad_request` | "The provider rejected the request as invalid." | false |
| rate limit (seen earlier in this project as `RESOURCE_EXHAUSTED`) | `RateLimitError` | 429 | `rate_limited` | "The provider rate limit was reached." | true |
| provider 5xx / connection failure | `ServiceUnavailableError`, `InternalServerError`, `BadGatewayError`, `APIConnectionError` | 502/503/500/null | `provider_unavailable` | "The provider was unavailable." | true |
| prompt too long | `ContextWindowExceededError` | 400 | `context_too_long` | "The prompt is longer than the model accepts." | false |
| safety / policy block raised as an exception | `ContentPolicyViolationError` | 400 | `content_blocked` | "The provider blocked the request for policy reasons." | false |
| credentials or permission | `AuthenticationError`, `PermissionDeniedError` | 401/403 | `provider_auth` | "Kernel's credentials or permissions were refused by the provider." | false |
| anything else from litellm | `APIError` and others | any | `provider_error` | "The provider returned an error." | null (unknown) |

**Built in M1 (K1a), from a real observation on 2026-09-21:** real Vertex answers a 403 (permission denied on the project) as a `litellm.BadRequestError`, so when the litellm class is one of the two generic ones (`bad_request`, `provider_error`) the provider's own status decides the category (401 and 403 → `provider_auth`, 404 → `model_not_found`, 408 → `timeout`, 429 → `rate_limited`, 500/502/503/504 → `provider_unavailable`). A specific class (for example `ContentPolicyViolationError`) is never overridden by its status.

The generic strings are part of the contract (Backend may match on `type`, never on `message`); the exact wording above is my proposal for the PM to accept or reword, and once fixed it never varies per request. Backend's Failure Handler and Test Lab show `type`, `provider_status`, the message and the `attempt_id`.

Not an error: **truncation.** With `max_output_tokens=3` the provider returned success with `finish_reason="length"` and 3 tokens (verified 2026-09-21). A safety block that comes back as an empty response with a `finish_reason` instead of an exception is UNVERIFIED.

## 5. The sha256 rule (acceptance rule from plan rule 4)

### 5.1 Definition
`prompt_sha256 = sha256( UTF-8 bytes of the exact string passed to the model as messages[0]["content"] )`, lowercase hex, no salt, no framing. It is computed at ONE place: the single function that calls litellm (today `LiteLLMModel.generate_content`, `agent_factory.py:110`; in the executor, the function that builds `kwargs` in 2.1 and calls litellm). The hash and the call use the same string object; there is no code path between hashing and calling.

**Acceptance rule:** for every call, Backend's saved sha256 must equal Kernel's returned `prompt_sha256`; a mismatch fails loudly in Test Lab. Because the Briefing carries Backend's sha (a REQUIRED request field, PM decision 2026-09-21), the check happens twice: before the call (Kernel refuses a corrupted string without spending a model call) and after (Backend compares the returned value to its saved value). The same holds for `request_sha256` (PM decision 2026-09-21): a required request field, verified before the call with its own 422 code `request_sha_mismatch`, and returned for Backend's comparison.

### 5.2 `request_sha256` (adopted, PM decision 2026-09-21: proves tools and schema too)
The plan's rule covers the prompt. The other parameters the model receives (tools, response_format, model, temperature, reasoning_effort, tool_choice, max_tokens, timeout) are also "what was sent".

**Definition (normative).** Build an object `R` whose keys are the litellm parameter names and whose values are the Briefing's values, containing ONLY the parameters that are non-null in the Briefing and that Kernel passes to litellm: `model`, `temperature`, `reasoning_effort`, `max_tokens` (from `max_output_tokens`), `tools`, `tool_choice`, `response_format`, `timeout` (from `timeout_s`). Exclude `messages`, `vertex_project`, `vertex_location` (the first is covered by `prompt_sha256`, the others are Kernel config). Then
`request_sha256 = sha256( json.dumps(R, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") ).hexdigest()`.
Rules that keep both sides equal: keys are sorted at every nesting level; no whitespace; non-ASCII characters are written as themselves (not `\uXXXX`); numbers are serialized as Python's `json` does, so the integer `60` and the float `60.0` hash differently (Backend must hash the same kind it sends); booleans are `true`/`false`. Kernel computes it from the Briefing it received, before the call, compares it with the request's `request_sha256`, and returns its value; Backend computes it from the Briefing it saved. A JSON number that Backend writes as `1e2` or `0.10` parses to the same value Kernel canonicalizes, so the text form does not matter; what matters is integer versus float (`60` is not `60.0`).

**Test vectors** (computed 2026-09-21; both sides must reproduce these exactly):

| # | Input | Expected |
|---|---|---|
| V1 | `prompt` = `"## L1 \u2014 MANDATE\r\nHello \U0001F600 caf\u00e9\n\n"` (31 code points, 32 UTF-16 units, 37 UTF-8 bytes) | `prompt_sha256` = `8ead1c076d6f8ee14f20f81eb0156b2bd657d5ea66628fe32a4baf77e840836e` |
| V2 | `R` = `{"model":"vertex_ai/gemini-2.5-flash","temperature":0.0,"reasoning_effort":"disable","response_format":{"type":"json_schema","json_schema":{"name":"structured_output","schema":{"type":"object","properties":{"confirmed":{"type":"boolean"}},"required":["confirmed"]},"strict":true}},"timeout":60}`; canonical string starts `{"model":"vertex_ai/gemini-2.5-flash","reasoning_effort":"disable","response_format":{"json_schema":{"name":"structured_output","schema":{"properties":` | `request_sha256` = `4c8c68ffefe4246158e374cb499267ee44af8a628a9470a8bc99f2275e38a9fa` |
| V3 | `R` = `{"model":"vertex_ai/gemini-2.5-pro","temperature":0.4,"reasoning_effort":"minimal","max_tokens":2048,"tools":[{"type":"function","function":{"name":"refuse","description":"Decline \u2014 not a reply.","parameters":{"type":"object","properties":{"reason":{"type":"string"}},"required":["reason"]}}}],"tool_choice":"required","timeout":120}` (note the non-ASCII em dash inside a tool description) | `request_sha256` = `114c3ba17d05955933c47eba61147afec42a829648f4b438bcde263bb5587217` |
| V4 | `R` = `{"model":"vertex_ai/gemini-2.5-flash","temperature":0.1,"tools":[{"googleSearch":{}}],"timeout":90}` (the Hound shape) | `request_sha256` = `43176cefaf19373f48ea5eead671117f023477d03daa11a5be9fe38014457668` |

### 5.3 What the hash does and does not prove
It proves the string Kernel handed to litellm equals the string Backend saved. It does not prove what reached Gemini after litellm's own adapter (UNVERIFIED that litellm does not alter a single-message text prompt on the wire; the goldens show the kwargs it receives, not the HTTP body it sends).

### 5.4 Transport rules that keep the hash exact
- JSON strings preserve every code point; Kernel must not normalize Unicode (NFC/NFD), trim, strip BOM, or translate `\r\n`.
- A prompt containing an unpaired surrogate cannot be UTF-8 encoded; Kernel rejects it (HTTP 422, error `invalid_prompt`, zero model calls) rather than replacing characters.
- Kernel does not compress, truncate or split the prompt. Prompts over `max_prompt_bytes` are rejected (HTTP 422), never cut.

## 6. The contract test (proves "one Briefing in, one model call out, no sequencing, no file reads, no composition")

DESIGN ONLY: these are specifications, not committed tests. **Sequencing (PM decision 2026-09-21, from Fable's review):** each test is tagged. M1a keeps T1, T3, T4, T6, T8, T9, T14 and T15 plus the load test (K1 §5); T2 (property corpus), T5 (audit hooks), T7 (state snapshots) and T13 (golden bridge) are AFTER THE CORE. Note: the PM's list did not name T10, T11 and T12; I tagged them M1a because T10 and T11 test the result and error body every Backend call reads and T12 is what keeps prompts out of logs, and T11 is rewritten by this revision. Confirmed by the PM on 2026-09-21: T10, T11 and T12 are M1a; the nine generic error wordings, `request_sha256` REQUIRED, the scrubbed 2,000-character log line and the M1a parse-mode measurement (no threshold) are accepted as written. All tests patch litellm at the module boundary Kernel calls (so no network and no litellm internals run) and drive the real HTTP app (FastAPI TestClient).

**T1 one in, one out.** [M1a] POST a Briefing. Assert the fake litellm callable was invoked exactly once; its kwargs equal exactly the mapping in 2.1 (same keys, same values, deep-equal), with each optional key present iff its Briefing field is non-null; `messages == [{"role":"user","content": prompt}]`; response `attempt_id`/`call_label`/`segments` equal the request's.
**T2 byte exactness (property test).** [AFTER THE CORE] For a corpus (ASCII; multi-line; CRLF; lone CR; tabs and trailing spaces; astral emoji; combining marks; RTL; zero-width joiner; U+2028/2029; NUL; a JSON-hostile string with quotes and backslashes; leading/trailing newlines; 1 MiB and `max_prompt_bytes`): `sha256(prompt.encode("utf-8")) == result.prompt_sha256 == sha256(fake.kwargs["messages"][0]["content"].encode("utf-8"))`, and `prompt_utf16_units` equals the JavaScript length of the string. Invalid input (lone surrogate, over-size) returns HTTP 422 with zero calls.
**T3 pre-call sha check (`prompt_sha256` is REQUIRED).** [M1a] A Briefing whose `prompt_sha256` does not match its `prompt`, and a Briefing with the field missing or malformed, each return HTTP 422 (`prompt_sha_mismatch` / `invalid_briefing`) with Kernel's computed sha, byte count and UTF-16 length, and zero model calls. The same three cases for `request_sha256` (mismatch → `request_sha_mismatch`, missing or malformed → `invalid_briefing`), including a Briefing whose only difference from a valid one is one changed parameter (a temperature, a tool description, a `timeout_s` of `60` versus `60.0`), and a Briefing whose prompt sha is right and request sha wrong (and the reverse); each has zero model calls.
**T4 no sequencing, no retry.** [M1a] Drive the fake to (a) return a tool call, (b) return unparseable text under `json_strict` and `json_lenient`, (c) return `finish_reason="length"`, (d) raise each litellm exception class, (e) raise a timeout. In every case assert the fake was called exactly once and the result is a normal `ExecutionResult` (HTTP 200) with the right `status`, `error` and `parse_error`.
**T5 no file reads, no network.** [AFTER THE CORE] Register a `sys.addaudithook` before the request and assert that no `open`, `os.listdir`, `os.scandir` or `socket.connect` event occurs between request start and end (the fake litellm replaces every legitimate I/O). This directly fails the three protocol-file reads that exist today (`specialist.py:35-38,80-83`, `hound.py:8-11`).
**T6 no composition.** [M1a] (a) Import-graph check: the executor package's transitive imports must not include `core.composition`, `core.prompt_builder`, `core.reconcile`, `core.triggers`, `core.orchestrator`, `pods.*`, or the legacy schema module. (b) Source scan: the executor's source contains none of `PromptBuilder`, `assemble`, `### BLOCK`, `registry/`, `protocol`. (c) Behavior: two different Briefings that differ only in `prompt` produce fake kwargs that differ only in `messages`.
**T7 stateless.** [AFTER THE CORE] Run 50 Briefings (some concurrent, each with a unique marker in the prompt); assert each result contains only its own marker, no module-level state changed (snapshot `vars()` of the executor modules before and after), and the same Briefing sent twice makes two model calls (no cache, no de-duplication on `attempt_id`).
**T8 strict validation.** [M1a] Unknown top-level field, missing field, wrong type, model not on the allowlist, tool shape not on the allowlist, `timeout_s` out of range, empty `tools` array, `prompt` over `max_prompt_bytes`: each returns HTTP 422 with zero calls.
**T9 parse modes.** [M1a] A table of cases for `text`, `json_strict`, `json_lenient` including a fenced block, a list, an empty list, a scalar, invalid JSON, empty text, and text plus tool call; `json_lenient` output must equal `parse_json_lenient` from `core/kernel_utils.py:34` on the same inputs (a differential test against the current function, which is deleted only after this test exists).
**T10 result echo.** [M1a (see note)] `segments` returned deep-equal to the request's, including unknown extra keys; `kernel.revision`/`git_sha` come from the environment; `usage` (including `reasoning_tokens`), `finish_reason`, `effective_model` and multiple `tool_calls` (including a malformed one, kept with `parse_error`) map exactly.
**T11 error mapping.** [M1a (see note)] Each litellm exception class produces the `type` and `retryable` in 4.4; the `message` equals the fixed generic string in the 4.4 table; fake exceptions whose text contains, in turn, the prompt, the Kernel auth token, a `Bearer` token, an `AIza` key, a `ya29.` token, a JWT-like string and a PEM block each yield the FIXED GENERIC message for that category; the response body contains no provider text: for every case, no substring of the fake exception's text, no `projects/` path, no token or key shape and no prompt marker appears anywhere in the body; and two different raw texts for the same category give byte-identical bodies. The log line for the same request contains the category, the provider status and the raw provider text with prompt substrings (20 characters or longer) and credential shapes scrubbed.
**T12 logs.** [M1a (see note)] Capture all log output for a request; assert it contains `attempt_id`, `call_label`, sha, duration and error type, and contains no prompt text, no output text and no credential.
**T13 golden bridge.** [AFTER THE CORE] Convert each of the 230 golden requests into a Briefing using only section-2 fields (`prompt` = `messages[0].content`); execute; compute each request's `prompt_sha256` and `request_sha256` from the golden kwargs by the 5.2 rule and send them; assert the fake receives kwargs byte-identical to the golden and no `prompt_sha_mismatch` or `request_sha_mismatch` occurs. This proves the contract can express everything Kernel sends today.
**T14 headings and scaffold are just text.** [M1a] Execute a Briefing whose prompt is a six-layer prompt written entirely by the test (layer headings `## L1 — MANDATE` … `## L6 — MEMORY`, blank lines, a closing line, CRLF and LF variants, emoji, a stale `### BLOCK n: THE MANDATE` heading and an `[EXECUTION_START: ...]` line). Assert: the fake receives exactly one message with `role == "user"` and `content == prompt` byte for byte; no message, key or text is added; the response `segments` equal the request's; and the result's `prompt_sha256` equals the sha256 of the test's own copy of the string.
**T15 sha vectors.** [M1a] Execute Briefings built from V1–V4 (section 5.2) with Backend-independent expected values hard-coded in the test; assert Kernel's `prompt_sha256` and `request_sha256` equal them, send V1–V4 as Briefings with their vectors' shas in the request fields and assert HTTP 200, send each with one wrong sha and assert 422 with the matching code, and assert that a one-character change to `prompt` or to any parameter changes the respective sha.

## 7. Parameters the plan's list did not name, and additions I am flagging

| # | Item | Why | Status |
|---|---|---|---|
| F1 | `finish_reason` in the result | Truncation returns success with `finish_reason="length"` (verified 2026-09-21); today it is discarded (`LiteLLMResponse`, `agent_factory.py:22-64`) so a cut-off reply looks like a normal one | required |
| F2 | `max_output_tokens` in the request | Nothing bounds output today; needed to control cost and to test truncation | kept as an optional field; Backend authors it in `call_settings` (decided, R3) |
| F3 | `prompt_sha256` in the request | Pre-call verification of "saved equals sent" without spending a model call | **decided: REQUIRED** (PM decision 2026-09-21) |
| F4 | `request_sha256` in the result | Proves tools and schema, not only the prompt | **decided: adopted**, rule and vectors in 5.2 (PM decision 2026-09-21) |
| F5 | `effective_model` in the result | The provider reports the model actually used | proposed |
| F6 | `usage.reasoning_tokens` | Pro thinking tokens are inside `completion_tokens`; cost analysis needs them separate (80 of 81 in the measured call) | proposed |
| F7 | `tool_calls[].arguments_raw` and per-call `parse_error` | Malformed tool calls are silently dropped today | proposed |
| F8 | `timing` in the result | Test Lab and the Failure Handler need duration | required |
| F9 | Kernel-side guardrails: model allowlist, tool allowlist, `max_prompt_bytes`, `max_timeout_s` | Once Kernel executes any Briefing it is otherwise a general model proxy (K1 §4) | **decided** (PM decision 2026-09-21): model allowlist; tool allowlist = function tools + `googleSearch`; `max_prompt_bytes` 4 MiB; max timeout. Kernel config, not Briefing fields, not raisable by Backend |
| F10 | `vertex_location` | Hard-coded `us-central1` (`agent_factory.py:13`); a future model may only be served from another region | **decided: fixed by Kernel config, not a Briefing field** (PM decision 2026-09-21) |
| F11 | `top_p`, `top_k`, `seed`, `stop`, safety settings, candidate count, a separate system message, streaming | Not used at any call site today | excluded from v1; a field is added only when a Recipe needs it |
| F12 | Idempotency / de-duplication | Kernel is stateless; `attempt_id` is echoed only | Backend's job |
| F13 | Provider search metadata for grounded calls | Only `url_citation` title and url survive litellm (`agent_factory.py:51-57`) | UNVERIFIED whether more is obtainable |

## 8. Measurements taken for this document (real model, 2026-09-21)

| Probe | Result |
|---|---|
| baseline Flash call | success, `finish_reason="stop"`, `effective_model="gemini-2.5-flash"`, usage (6, 1) |
| `timeout=0.4` | `litellm.Timeout`, status 408, after 0.59 s |
| unknown model id | `litellm.NotFoundError`, status 404; message contains the project path |
| invalid response schema | `litellm.BadRequestError`, status 400 |
| `max_tokens=3` on a long request | success, `finish_reason="length"`, usage (11, 3) |
| Pro with `reasoning_effort="minimal"` | success, usage (6, 81), `reasoning_tokens=80` |
| litellm defaults | `request_timeout` 6000 s; no `num_retries` (Kernel makes no retries today); `timeout` param default None |

UNVERIFIED: whether litellm's `timeout` enforces total wall-clock time for long generations (the 0.4 s case was a connection-level timeout); whether a safety block appears as an exception or as an empty response with a `finish_reason`.

## 9. Decisions and remaining open details

### 9.1 Revision 1's questions, all decided (PM decision 2026-09-21)

| Was | Decision | Where it landed |
|---|---|---|
| Q1 authoring home of per-call settings | `call_settings` per Function and per Agent, platform defaults in registry doc `call_defaults`; Backend sends explicit values | section 2 (paragraph after the schema) |
| Q2 `prompt_sha256` required? | REQUIRED; Kernel refuses mismatch or missing with zero model calls | section 2, 5.1, T3 |
| Q3 `request_sha256` | adopted; canonicalization is normative with four test vectors | 5.2, T15 |
| Q4 segment validation | none; Kernel only echoes, Backend tests its own offsets | section 2 |
| Q5 `length` / `content_filter` | `status:"ok"` with `finish_reason` set; Backend's Runner treats them as failures unless the call allows truncation | section 4, F1 |
| Q6 region | fixed by Kernel config | section 2, F10 |
| Q7 provider error text | REVISED in revision 3: `type`, provider status and a FIXED GENERIC message per category; raw provider text only in Kernel's logs | 4.4, T11 |
| Q8 tool allowlist | function tools and `googleSearch` only | section 2, F9, T8 |
| Q9 prompt size cap | 4 MiB, Kernel config, not raisable by Backend | section 2, F9, T8 |

### 9.2 Small details, ALL ANSWERED by the PM on 2026-09-21 (kept for the record)

- **R1 (superseded by revision 3) Scrubbing scope for `projects/<id>`.** The PM first said to redact `projects/<id>/`; revision 3 goes further: no provider text is returned at all (4.4), so there is nothing to redact on the return path. Scrubbing of prompt substrings, credential shapes and the project path stays for Kernel's own logs.
- **R2 (accepted: Backend hashes the exact JSON it sends) Number typing in `request_sha256`.** `60` and `60.0` hash differently (5.2). Backend and Kernel must send and hash the same JSON number kind. Default: Backend hashes the exact JSON text it sends; T15 includes an integer-versus-float case. Backend 2 to confirm its serializer keeps `timeout_s` as written.
- **R3 (closed) `max_output_tokens` and `allow_truncation` in `call_settings`.** The PM's list of `call_settings` is model, temperature, reasoning effort, parse mode, timeout. `max_output_tokens` is an existing optional Briefing field; the truncation switch is Backend's Runner concern (Kernel returns `ok` either way). **Closed (PM decision 2026-09-21): both are added to the `call_settings` list (the PM tells Backend for C2).** Kernel needs no change.
- **R4 (corrected in revision 3) Value of `max_timeout_s`.** Kernel's maximum MODEL timeout is 280 s (below Cloud Run's 300 s request limit, so Kernel can still return a structured timeout result). Backend's HTTP timeout to Kernel is the call's own `timeout_s` + 15 (so at most 295 s, still below 300 s), which means Kernel's timeout always fires first and returns a structured result before Backend's client gives up. Today's values (`origin/main` of the Backend repo as fetched on this machine, 2026-09-21 12:20, so possibly not the newest): the turn call passes 150 s at `src/api/master_routes.py:876` (`kernel_post(KERNEL_URL, sovereign_request, 150, app_id)`; this replaces my earlier citation of `:510`, which was the older local checkout) and the strike launch passes 280 s at `src/services/gate_sequencer.py:168`; every other Kernel call passes 60 s. Backend's X0 raises the outer limits.
