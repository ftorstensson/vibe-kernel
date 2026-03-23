
**Entry 028: The 404 Model Registry Ghost**
*   **Symptom:** Backend threw 404 when calling `gemini-3.0-pro`.
*   **Lesson:** Never assume upcoming model IDs. **Always verify against the Vertex AI registry.** Reverted to `gemini-2.5-pro` (stable) and `gemini-2.0-flash-001`.

**Entry 029: The Silent Uvicorn Buffer**
*   **Symptom:** `print()` logs were invisible in the terminal.
*   **Fix:** Use `logging.getLogger("uvicorn.error")`. It forces logs to terminal immediately.

**Entry 030: The Schema Leak (Self-Talk)**
*   **Symptom:** LLM put its internal reasoning ("I have analyzed the request...") into the user chat bubble.
*   **Fix:** Strictly separate `user_message` (social) from `thought_process` (internal) in Pydantic schemas. Use "Negative Constraints" in prompts: "NO META-TALK."

**Entry 031: The 422 Handshake Error**
*   **Symptom:** Frontend fetch fails with "Unprocessable Entity."
*   **Fix:** Ensure FastAPI parameters (Form vs Body) match exactly between Frontend `FormData` and Backend endpoint signatures.

**Entry 032: The Truncation Trap (Merging Logic)**
*   **Symptom:** Refactoring major UI components led to 200+ lines of specialized visual logic being deleted, breaking all layers except the one being worked on.
*   **Fix:** Never "lean out" the page logic during a refactor. Always merge new architectural changes into the existing production code to preserve resizable frames and custom node types. Use explicit typing (e.g. `DeptSlot`) to satisfy the TS compiler during ledger-to-node mapping.



**Entry 033: The Truncation Trap**
*   **Symptom:** Refactoring major UI components led to 200+ lines of visual logic being deleted.
*   **Fix:** Never "lean out" production files during a refactor. Always merge new logic into the existing production code.

**Entry 034: The Middleware Gate**
*   **Symptom:** Production Handshake failed with "Access-Control-Allow-Origin" errors.
*   **Fix:** CORSMiddleware must be added **before** routes are mounted. Use `allow_origins=["*"]` for Cloud Run MVPs to handle shifting service URLs.

**Entry 035: Baked Config (Docker Build Args)**
*   **Symptom:** Local frontend talking to Cloud backend or vice-versa.
*   **Fix:** Next.js environment variables must be passed as `--build-arg` during the Docker build process, as they are baked at build-time.

**Entry 036: The Firestore Index Block**
*   **Symptom:** Listing projects failed with a 500 error when trying to sort by `is_pinned` and `updated_at`.
*   **Fix:** Firestore requires a manual composite index for multi-field sorting. Always check logs for the auto-generated index link.

**Entry 037: The Closure Staleness Trap**
*   **Symptom:** Cards disappearing during long AI requests.
*   **Fix:** In Zustand/Async functions, never rely on variables captured at the start of the function. Always use the functional update pattern: `set((state) => ({ ...state.data + newPatch }))` to ensure you merge with the absolute latest state.

**Entry 038: Manifest Type Sync**
*   **Symptom:** TS errors when saving state.
*   **Fix:** Ensure the `VibeManifest` interface (what we save) and `VibeStore` interface (what we use) are perfectly synchronized. Every property in the store must be explicitly accounted for in the Manifest contract.



**Entry 040: The Appendix Mandate**
*   **Fix:** Harden the Pydantic schema to make the Appendix object mandatory. This forces the model to perform the research before validating the response.

**Entry 041: Async State ID Race**
*   **Symptom:** `Failed to Fetch: Store has no Project ID` error when sending messages immediately after project creation.
*   **Fix:** In `vibe-store.ts`, set the `project.id` synchronously at the very start of the hydration/creation logic. Never allow the ID to be null during an active session.

**Entry 042: Pure Setters (RPC Error)**
*   **Symptom:** "Failed to fetch" errors when putting `fetch()` calls inside a Zustand `set()` block.
*   **Fix:** Zustand setters must be pure. Move all autosave network calls outside of the `set()` function to prevent race conditions.


**Entry 043: The Side-Effect RPC Error**
*   **Symptom:** "Failed to fetch" errors when putting `fetch()` calls inside a Zustand `set()` block.
*   **Fix:** Zustand setters must be pure. Move all autosave network calls outside of the `set()` function to prevent race conditions.

**Entry 044: Atomic Name Sync**
*   **Symptom:** UI Header remained "Untitled" even after the AI named the project.
*   **Fix:** Ensure the Frontend Store and the Backend Dispatcher perform a "Handshake" where `suggested_project_name` updates the local state and Firestore record in the same turn.

**Entry 045: Literal Role Enforcement**
*   **Symptom:** TS error: "Type 'string' is not assignable to type 'user' | 'assistant'".
*   **Fix:** Use `as const` when assigning role strings in TypeScript to satisfy strict literal type checks in the ChatMessage interface.


# SCAR_TISSUE_LEDGER

**Entry 046: The Graph Entrypoint Crash**
*   **Symptom:** Backend failed to start with `ValueError: Graph must have an entrypoint`.
*   **Fix:** LangGraph `StateGraph` cannot be compiled as an empty object. It requires at least one node, an edge from START, and an edge to END before `compile()` is called.

**Entry 047: The Alphabetical Layout Bug**
*   **Symptom:** Departments and Agents appearing in random order in the Lab UI.
*   **Fix:** Move away from `Object.keys()` mapping. Implement explicit `dept_index` and `role_index` fields in the database and use a hardcoded `DEPT_ORDER` array in the UI.

**Entry 048: Side-Effect RPC Errors**
*   **Symptom:** `Failed to fetch` error during project creation.
*   **Fix:** Autosave fetches must be triggered outside of the Zustand `set()` function. Functional updates `set((state) => ...)` must remain pure to avoid race conditions.

**Entry 049: The Key Name Collision**
*   **Symptom:** Department Lenses disappeared from the Lab UI after a database update.
*   **Fix:** The seeder script changed the field name from `lens_profile` to `lens`. The "Dumb Code" in the UI was hardcoded to look for `lens_profile`. **Lesson:** Never change a database key name without updating the entire chain (Store + Backend + Seeder). Always use the full key name provided in the Types.

**Entry 050: The Google Search Tool Pivot**
*   **Symptom:** Backend 400 error: `google_search_retrieval is not supported`.
*   **Fix:** As of Jan 2026, Google has consolidated the tool name to `google_search`. The configuration must be a dictionary: `{"google_search": {}}` instead of a string.

**Entry 051: The Vertex AI Content Mandate**
*   **Symptom:** 400 error: `at least one contents field is required`.
*   **Fix:** Gemini on Vertex AI forbids sending a request containing only a `SystemMessage`. Every specialist call must include a `HumanMessage` (even if generic) to satisfy the API structure.

**Entry 052: The "Placeholder" Trap**
*   **Symptom:** AI returned text saying "Logic for authoring loop continues here..."
*   **Fix:** Avoid providing "lean" or "simplified" code snippets in the dispatcher. Always implement the full iteration loop over the specialist roster to prevent the AI from generating its own placeholder text.

**Entry 053: The Firestore Client Case-Sensitivity**
- **Symptom:** `AttributeError: module 'google.cloud.firestore' has no attribute 'client'`.
- **Fix:** Use `firestore.Client()` (Capitalized) for the constructor.

**Entry 054: The Schema Import Ghost**
- **Symptom:** `ImportError: cannot import name 'StrategySpatialOutput'`.
- **Fix:** Ensure the Pydantic schema file includes the top-level wrapper classes (`StrategySpatialOutput` and `StrategyPatch`) required by the dispatcher, even if the primary content schema changes.

**Entry 055: The Accessibility Linter Wall**
- **Symptom:** Build fails on "Element has no title attribute" for textareas.
- **Fix:** Every `textarea` and icon-only `button` in the Agency Lab must have a `title` and `aria-label`.

**Entry 056: The AI Aesthetic Trap (Swiss-Mono Bias)**
- **Symptom:** AI defaulted to all-caps/mono-spacing for "minimalism," destroying UX readability.
- **Lesson:** AI pattern-matches to a "look" rather than "utility." Designer-in-the-loop is required to enforce high-fidelity hierarchy (e.g., Sans-Inter, proper vertical rhythm).

**Entry 057: Hydration Desync (New Layer Crash)**
- **Symptom:** `Cannot read properties of undefined (reading 'nodes')` when clicking new layers in old projects.
- **Fix:** Implemented an `EMPTY_LAYERS` constant and a `mergedLayers` hydration guard in the store to ensure all layers exist, even if missing from the cloud DB.

# SCAR TISSUE LEDGER (v4.4)
*The Black Box Recorder of the Design Truth Engine*

**Entry 058: The Meta-Talk Trap**
- **Symptom:** Specialists writing about "Design Taxonomy" or "AI Agencies" instead of the actual project (e.g. StormQuest).
- **Fix:** Implemented the "Intent Firewall." Specialists are physically shielded from the Agency Handbook. They only receive the Project Memory and the Director's Vision.

**Entry 059: The Mirroring Trap**
- **Symptom:** PM repeating the Director's input back to them ("You said you want a travel app...") instead of suggesting new value.
- **Fix:** Implemented the "Anti-Mirror Law." The PM is explicitly punished for echoing the user and rewarded for adding "Strategic Bricks" to the wall.

**Entry 060: The Race Condition (Pacing)**
- **Symptom:** The PM says "I'm starting the team" and the paper arrives in the same turn, leaving the user confused for 60 seconds.
- **Fix:** Implemented the "Two-Stage Gate." The PM must ask for permission to start the loop, and the backend blocks execution until the Director says "Yes."

**Entry 061: The Dual-Repo Path Gap**
- **Symptom:** Backend "Eye" couldn't see Frontend files.
- **Fix:** Absolute pathing via `FRONTEND_PATH` environment variable. Never use relative paths for cross-repository bridging.

**Entry 062: The Swiss-Mono Aesthetic Bias**
- **Symptom:** AI defaulted to all-caps/mono-spacing for "minimalism," destroying readability.
- **Fix:** Designer-in-the-loop enforced high-fidelity hierarchy (Sans-Inter, bold headers, vertical explainer stacks).

# SCAR TISSUE LEDGER (v4.7 - The Intelligence Update)
*Last Updated: 2026-02-26*

**Entry 063: The Gemini Grounding Paradox (Turn Stealing)**
*   **Problem:** Gemini 2.5 Pro uses internal grounding and "steals the turn," bypassing manual ReAct loops and hiding URLs.
*   **Fix:** **The Native Bypass.** Use `Tool.from_dict({"google_search": {}})` and programmatically harvest `grounding_metadata` from the response. It is 2x faster and 100% reliable.

**Entry 064: The Cognitive Split (Partner vs. Scribe)**
*   **Problem:** Asking the PM to be social AND a JSON clerk causes "Instruction Saturation" and robotic tone.
*   **Fix:** **The Sidecar Pattern.** Turn 1 is the Social PM (Fast Lane). Turn 2 is the Invisible Scribe (Slow Lane) extracting data. They are separate models/turns.

**Entry 065: The "Yes" Poisoning (Context Isolation)**
*   **Symptom:** Specialists research the word "Yes" or "Go" instead of the project vision.
*   **Fix:** **The Iron Curtain.** Specialists are physically blocked from reading the chat history. They receive ONLY the structured Mission Manifesto.

**Entry 066: The Return Pipe Void**
*   **Symptom:** `NoneType` error in frontend when PM finishes Turn 1.
*   **Fix:** Every logic branch in `architect.py` must explicitly `return pm_decision` to keep the frontend store hydrated.

**Entry 067: The character-perfect search block**
*   **Lesson:** Markdown and Python patches fail on single characters or quote escapes (`\u0027`).
*   **Fix:** **The Overwrite Protocol.** Use a Python script or `cat` to physically rewrite files when surgical patches fail 3 times.

**Entry 068: The Mega-Schema Branching Wall**
*   **Symptom:** 400 BadRequest: "The specified schema produces a constraint that has too much branching."
*   **Diagnosis:** Trying to fit all 5 papers into one Pydantic class (`StrategyPaperContent`) overwhelmed Gemini 2.5's serving constraints.
*   **Fix:** **Schema Fragmentation.** Break the giant brief schema into 5 paper-specific schemas (BigIdeaContent, OpportunityContent, etc.).

**Entry 069: The Scribe-Starvation Trap (Amnesia)**
*   **Symptom:** Vision (Manifesto) disappearing after 3 turns.
*   **Fix:** Scribe must read the FULL , not just , to maintain vision continuity.

**Entry 070: The "Waiter" Mirroring Loop**
*   **Symptom:** PM repeating user input and speaking in the third person.
*   **Fix:** **The Prose Firewall.** Physically redact JSON keys from the PM prompt. Force natural-language vision paragraphs via  helper.

**Entry 071: The Reversed Handshake**
*   **Symptom:** PM talking based on old context; amnesia during research turns.
*   **Fix:** Scribe runs Turn 1 (IQ/Logic), PM runs Turn 2 (EQ/Vibe). Vision is locked in Firestore before the PM ever speaks.

**Entry 072: The Lion’s Mouth (Dynamic Registry)**
*   **Symptom:** Key Drift (camelCase vs snake_case) creating logic dead-ends.
*   **Fix:**  is a boot-loader. It physically pings Firestore for canonical keys on startup. No more hardcoded strings.
# SCAR TISSUE LEDGER (v15.0 - The Assembly Line Update)

**Entry 073: The Cognitive Multi-tasking Decay (Brief Starvation)**
*   **Symptom:** Scribe produced a 10-character brief ("lets go") instead of strategy.
*   **Lesson:** LLMs cannot extract complex JSON and author high-fidelity prose in the same turn. The JSON constraint "starves" the creative attention.
*   **Fix:** **The Cognitive Split.** Turn 1: Clerk (JSON Extraction). Turn 2: Author (Prose Synthesis).

**Entry 074: The Polite Liar (Persona Override)**
*   **Symptom:** PM said "The team is unleashed" even when the Business Model was missing and the gate was RED.
*   **Lesson:** Persona-driven models prioritize "being a good partner" over technical instructions.
*   **Fix:** **The Red-Light Mandate.** Prepend [MISSION STATUS: RED] to the absolute first token of the PM prompt to trigger "First-Token Priority" logic.

**Entry 075: The Native Grounding Bypass (URL Leak)**
*   **Symptom:** Specialists reported "URLs not provided" even when searches were successful.
*   **Lesson:** LangChain's `ChatVertexAI` wrapper often swallows the `grounding_metadata`.
*   **Fix:** **The Native SDK Bypass.** Use the raw `vertexai.generative_models` SDK for search turns to physically harvest `grounding_chunks` (URLs) and inject them manually into specialists.

**Entry 076: The "ELI" Meta-Research Hallucination**
*   **Symptom:** Researchers analyzed the "ELI Framework" instead of the actual project.
*   **Lesson:** Researchers given a thin brief (< 500 chars) default to their internal training (ELI) to fill space.
*   **Fix:** **The Density Deadbolt.** Physically block specialists from starting if the `problem_statement` is under 500 characters.

**Entry 077: The Naming Vomit (Model Loquacity)**
*   **Symptom:** Small sidecar calls (like the Naming Node) returned 500-word tutorial guides instead of a single-word name.
*   **Lesson:** High-IQ models like Gemini 2.0 Flash default to "helpful verbosity" and will ignore brief prompts unless physically constrained.
*   **Fix:** **The Token Choke.** Force a hard physical limit of `max_output_tokens=10` and use a "Force-Dumb" prompt: "Return ONLY the name. No quotes. No lists."

**Entry 078: The Pydantic Lobotomy (Depth Loss)**
*   **Symptom:** Specialists produced shallow, repetitive "Dumb Boxes" instead of the 4+ paragraphs of deep strategic analysis mandated in their Exo-Brains.
*   **Cause:** Using `with_structured_output` (Pydantic) forces the model to prioritize JSON syntax over strategic reasoning, consuming the model's "logic budget" on formatting.
*   **Fix:** **Prose-First Restoration.** Allow Specialists to run as "Ordinary AIs" (Prose mode) to restore depth. Use Pydantic/JSON schemas only at the final Editor turn to map that prose into the Strategy Bricks.

**Entry 079: The SaaS Ghost (Attractor Bias)**
*   **Symptom:** Specialists defaulted to "B2B SaaS" or "Enterprise Training" research even when the vision was a "Beer App for Tradies" or a "Calorie Tracker."
*   **Fix:** **The Fidelity Anchor.** Implement a **Dual-Brief** (Positive Anchor + Negative Constraints). The Author must explicitly list what the project is NOT (e.g., "This is NOT a B2B SaaS tool") to repel the model's training-data attractors.

**Entry 080: The Redirect 404 (Link Smear)**
*   **Symptom:** "View Source" buttons on the canvas led to internal Google Search redirect URLs that failed to load or threw 404s.
*   **Fix:** **The Link Washer.** Use the Native SDK to physically harvest the `web.uri` field from `grounding_metadata` (the direct destination). In the UI, implement a regex `washLink` utility to extract the raw URI from any accidental Markdown wrappers.

**Entry 081: The Context Avalanche (Connection Reset)**
*   **Symptom:** Backend threw `ConnectionResetError` (54) and crashed when moving to Paper 2 of a project.
*   **Cause:** "Backpack Bloat." The system was carrying the physical weight of all previous papers' "Deep Research" (appendix data) into every social turn, exceeding the payload limit.
*   **Fix:** **The De-loading Law.** Physically strip raw logic, specialist reports, and treasure links before sending project data to the PM or Clerk. Treat completed papers as **Institutional Memory** (Summary Bricks only).

**Entry 082: The Foundation Collision (Armor)**
*   **Symptom:** Generic move commands (e.g., "Moving to Paper 2") caused the Clerk to overwrite the "Core Idea" spark with the string "Paper 2," triggering a logic crash.
*   **Fix:** **Spark Armor.** Implement a physical code-gate in the orchestrator: only allow the `core_idea` bucket to be updated if the new incoming text is significantly more detailed (longer) than the existing foundation.
**Entry 083: The People-Pleaser Pivot (Clerk)**
*   **Symptom:** The Clerk approved a vague "beer app" idea immediately despite the "Lightning Strike" requirement.
*   **Lesson:** Clinical models (IQ) default to "helpfulness" (The SaaS Ghost). They will hallucinate approval to keep the process moving.
*   **Fix:** The "Cynical Auditor" Mandate. Hard-coded the "Proprietary Logic Rule": The Clerk stays RED if the user provides info a Hound can find on Google.

**Entry 084: The Narrator/Visionary Conflict**
*   **Symptom:** During Turn 3, the PM ignored the research and hallucinated a new mission ("Project Alchemist").
*   **Lesson:** Persona-driven models with "Momentum" optimization will leap to the *next* milestone if not strictly anchored.
*   **Fix:** The "Post-Op" Anchor. The Orchestrator now mutes the PM during research and anchors the "Reporting" turn strictly to the "Established Truth" bricks.

**Entry 085: The "Spec-Brick" Dependency**
*   **Problem:** Directly generating images/audio inside the Kernel creates a hard dependency on specific APIs (Midjourney/Flux), breaking the "Headless" rule.
*   **Fix:** Generative Intent Specs. Specialists output a "Technical Spec" (Markdown/JSON). The Kernel remains text-only; a separate "Renderer" service handles the binary creation.

**Entry 086: The Infinite Project (Context Drift)**
*   **Problem:** Long-running projects cause "Instruction Drift" as the Knowledge Bricks ledger exceeds the model's attention window.
*   **Fix:** "The Clock." Automatic compression of historical bricks into a "FOUNDATIONAL_CONTEXT" block while keeping the 3 most recent bricks verbatim.

**Entry 087: The Fragile Bridge (Courier Failure)**
*   **Symptom:** Constant 422 Schema Errors and maintenance desync between the Main App and the Kernel.
*   **Lesson:** Passing full SOP/DNA payloads via API creates a "leaky" boundary where a database change in the App breaks the Kernel.
*   **Fix:** **Sovereign Kernel Architecture (v21.0)**. The Kernel receives only IDs and fetches its own Milestone SOPs, Agent DNA, and Project State directly from Firestore.

**Entry 088: The Naming Ghost (Cartography)**
*   **Symptom:** Kernel 404s or 500s when a different app uses different collection names or field keys.
*   **Lesson:** Hardcoded database paths are the enemy of scaling. A "Headless" engine must be told how to see.
*   **Fix:** **App Registry Map (ARM)**. Implemented "Bootstrap 0": The Kernel pings `_kernel_registry/{app_id}` to fetch a Map that defines the paths and schema keys for that specific application.

**Entry 089: Case-Sensitivity 404**
*   **Symptom:** Sovereign fetch failed for `THE_BIG_IDEA` because Firestore keys were lowercase (`the_big_idea`).
*   **Lesson:** Human input and UI constants are volatile. Database lookups must be deterministic.
*   **Fix:** Lowercase normalization. The `SovereignBootloader` now forces all IDs to lowercase before pining the Vault.
