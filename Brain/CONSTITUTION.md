# 📑 THE VIBE KERNEL CONSTITUTION (v1.0)
**The Industrial Operating Manual for the Standalone Agent Engine.**

## I. THE REFINED HIERARCHY (The Functional Blocks)
To prevent "Context Decay" and "Instruction Saturation," every agent turn is constructed from three distinct blocks of data, triggered by a Work Order.

1.  **THE LAW (The Machine Architecture):**
    *   **Nature:** Unbreakable physical constraints.
    *   **Scope:** Native Vertex AI SDK usage, the De-loading Law, Physics Gates (RED/GREEN), and JSON Hammer enforcement.
    *   **Rule:** The Law never changes based on the project. It is the "Gravity" of the Kernel.

2.  **THE LENS (The Expertise/Exo-Brain):**
    *   **Nature:** Strategic perspective and "The Way of Thinking."
    *   **Scope:** ELI Protocol, Research Rules (v1.2), Design Lab Taxonomy, and Optimization Targets (e.g., "The Wank Factor").
    *   **Rule:** The Lens tells the AI *how* to process information. It is the "Software" slotted into the brain.

3.  **THE TRUTH (The Established State):**
    *   **Nature:** Validated Knowledge vs. Volatile Context.
    *   **Scope:** 
        *   *Established Truth:* User-approved milestones and Stabilized Bricks.
        *   *Volatile Truth:* Chat history and the "Spark" (User Intent).
    *   **Rule:** The Truth is "Knowledge in the making." It is the only data the AI is permitted to analyze.

4.  **THE WORK ORDER (The Foreman’s Command):**
    *   **Nature:** The specific trigger for the turn.
    *   **Scope:** "Synthesize these reports," or "Probing for the Money Logic."
    *   **Rule:** The Work Order points the **LENS** at the **TRUTH** while obeying the **LAW**.

---

## II. THE ATOMIC POD ROSTER (Cognitive Isolation)
The Kernel is divided into isolated pods. Agents in one pod are physically "blind" to the raw data of another.

1.  **SOCIAL POD (Turn A):**
    *   **The Clerk (IQ 0.0):** Extraction and fact-checking.
    *   **The Partner/PM (EQ 0.4):** Social facilitation and momentum.
    *   **The Kaiser (Clinical Logic):** The Auditor that enforces the Physics Gate (RED/GREEN).

2.  **STRIKE TEAM POD (Turn B):**
    *   **The Hounds (Tool):** Native Google Search. Harvesting direct URIs.
    *   **The Specialists (ELI):** Strategic analysts. Producing grounded, raw research reports.

3.  **SYNTHESIS POD (Turn C):**
    *   **The Editor/Goldsmith:** High-IQ synthesizer. Welds raw specialist data into stabilized "Truth Bricks."

---

## III. THE LAWS OF PHYSICS (Banned Patterns)
1.  **The De-loading Law:** Social agents (PM/Clerk) are forbidden from seeing "Raw Research" (Turn B data). They only receive "Stabilized Bricks" (Turn C data).
2.  **The Native Grounding Law:** All research must use the raw Vertex SDK `grounding_metadata`. LangChain tool-bindings are banned.
3.  **The Anti-Mirror Law:** The PM is forbidden from recapping the user. It must either progress the "Spark" or probe a "Gap."
4.  **The First-Token Priority:** The [MISSION STATUS] and [KAISER MANDATE] must be the first tokens in any social prompt.

---

## IV. THE ASSEMBLY LINE FLOW
1.  **INPUT:** User Message + Current Truth (Firestore).
2.  **TURN A (Social):** Clerk audits Truth -> Kaiser sets Gate -> PM responds to User.
3.  **TURN B (Strike):** If Gate is GREEN -> Hounds hunt -> Specialists write ELI reports.
4.  **TURN C (Synthesis):** Editor welds reports into new "Established Truth" Bricks.
5.  **OUTPUT:** Update Firestore + Signal Frontend.
