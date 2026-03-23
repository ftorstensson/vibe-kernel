# VIBE KERNEL (v21.1)
The Sovereign Standalone Agent Engine.

The Vibe Kernel is a Dumb Fortress that processes human intent through an isolated assembly line. It is Sovereign, meaning it fetches its own configurations and project state directly from Firestore based on an App Registry Map (ARM).

---

## THE ARCHITECTURAL PILLARS
1. THE LAW (Machine): Immutable physical constraints (Native Vertex SDK, 32k token cutoff).
2. THE LENS (Expertise): Dynamic DNA and SOPs fetched internally from the agency_registry.
3. THE TRUTH (State): User-approved Knowledge Bricks and Manifesto facts fetched via project ID.
4. THE MAP (Cartography): A master index at _kernel_registry/{app_id} that tells the Kernel how to navigate the database.

---

## THE ASSEMBLY LINE (Execution Flow)
- Bootstrap 0: Kernel fetches the ARM to get its Eyes.
- Bootstrap 1: Kernel fetches Milestone SOPs and Agent DNA in parallel.
- Bootstrap 2: Kernel fetches Project Ledger and enforces the De-loading Law.
- Turn A (Social): Cynical Clerk audits chat against the dynamic Map-driven checklist.
- Turn B (Strike): Parallel Hounds (Google Search) + Specialist ELI Reports.
- Turn C (Synthesis): Editor welds reports into Truth Bricks (TEXT or VISUAL_SPEC).
- The Weld: Python regex physically injects Markdown links into prose.

---

## DIRECTORY STRUCTURE
- core/: Bootloader, Orchestrator, Clock, PromptBuilder
- pods/: Social, Strike Team, Synthesis, Maintenance
- registry/: (Deprecated) Milestones now live in Firestore
- lab/: Vault Scanners, Map Seeders, API Stress Tests
- Brain/: The Constitution and Scar Tissue Ledger

---

## GETTING STARTED

1. Environment Setup:
pip install -r requirements.txt
gcloud auth application-default login

2. Seeding the Map:
python3 lab/seed_map.py

3. Running the Engine:
python3 main.py

---
Safety Valve: If no Map is found for an app_id, the Kernel throws a 502 Map Error (Kernel is Blind).
