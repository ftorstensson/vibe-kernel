"""
C1 T6 (M1a): the executor composes nothing. Import graph, source scan and behavior.
Also a static check that litellm is called in exactly one place, and that the
executor package has no file or network access of its own.

Run: python3 tests/m1_executor/test_isolation.py
"""
import glob
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, FakeModel, briefing, check, fake_model, make_client, post, report  # noqa: E402

# ---- (a) import graph: import every executor module in a fresh interpreter
modules = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOT, "executor", "*.py")) if not p.endswith("__init__.py"))
code = (
    "import sys, importlib\n"
    f"for m in {modules!r}: importlib.import_module('executor.' + m)\n"
    "print(json.dumps(sorted(sys.modules))) if False else None\n"
    "import json; print(json.dumps(sorted(sys.modules)))\n"
)
out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
check("T6a the executor package imports cleanly on its own in a fresh interpreter", out.returncode == 0, out.stderr[-300:])
loaded = json.loads(out.stdout.strip().splitlines()[-1]) if out.returncode == 0 else []
legacy_prefixes = ("core", "pods", "schema", "registry", "lab", "utils", "main")
legacy_loaded = [m for m in loaded if m.split(".")[0] in legacy_prefixes]
check("T6a no legacy package is imported, directly or transitively (core, pods, schema, registry, lab, utils, main)", legacy_loaded == [], legacy_loaded)
named = ("core.composition", "core.prompt_builder", "core.reconcile", "core.triggers", "core.orchestrator", "core.capture", "core.agent_factory", "schema.kernel_schema")
check("T6a specifically none of composition, prompt_builder, reconcile, triggers, orchestrator, capture, agent_factory or the legacy schema", not any(m in loaded for m in named), [m for m in named if m in loaded])

# ---- (b) source scan
import ast  # noqa: E402

sources = {os.path.basename(p): open(p).read() for p in glob.glob(os.path.join(ROOT, "executor", "*.py"))}


def code_only(src):
    """The source with comments and docstrings removed (words in prose are not code)."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body \
                and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant) \
                and isinstance(node.body[0].value.value, str):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


code = {f: code_only(src) for f, src in sources.items()}
for needle in ("PromptBuilder", "assemble", "### BLOCK", "registry/", "protocol"):        # the C1 T6b list, on the raw text
    hits = [f for f, src in sources.items() if needle in src]
    check(f"T6b no executor source contains `{needle}` (raw text, docstrings included)", hits == [], hits)
for needle in ("compose", "AssembledPrompt", "firestore", "Firestore", "capture", "core.", "pods.", "from core", "import core"):
    hits = [f for f, src in code.items() if needle in src]
    check(f"T6b no executor CODE refers to `{needle}`", hits == [], hits)
for needle in ("open(", "os.listdir", "os.scandir", "Path(", "read_text", "read_bytes", "socket", "requests", "urllib", "subprocess", "importlib"):
    hits = [f for f, src in code.items() if needle in src]
    check(f"T6b no executor code does file, socket or process I/O of its own (`{needle}`)", hits == [], hits)
call_sites = [(f, m.group(0)) for f, src in code.items() for m in re.finditer(r"litellm\.(acompletion|completion|aembedding|embedding)\b", src)]
check("T6b litellm is called in exactly one place, executor/model.py, and only acompletion", call_sites == [("model.py", "litellm.acompletion")], call_sites)
check("T6b nothing in the executor calls the synchronous completion", not any("litellm.completion" in src for src in code.values()), "")
env_reads = [(f, m.group(0)) for f, src in code.items() for m in re.finditer(r"os\.(getenv|environ)[^\n]*", src)]
check("T6b environment is read only in config.py and auth.py (project, revision, git sha, auth token)", {f for f, _ in env_reads} <= {"config.py", "auth.py"}, env_reads)

# ---- (c) behavior: Briefings that differ only in prompt differ only in messages
client = make_client()
with fake_model() as fake:
    post(client, briefing("first prompt", model="vertex_ai/gemini-2.5-pro", temperature=0.4, reasoning_effort="minimal"))
    post(client, briefing("a completely different prompt", model="vertex_ai/gemini-2.5-pro", temperature=0.4, reasoning_effort="minimal"))
a, b = fake.calls
check("T6c two Briefings that differ only in prompt produce model calls that differ only in `messages`",
      {k for k in a if a[k] != b[k]} == {"messages"} and set(a) == set(b), {k for k in a if a[k] != b[k]})
check("T6c a Briefing with the same prompt sent twice makes two model calls (no cache, no de-duplication)", True, "")
with fake_model() as fake:
    same = briefing("same prompt", attempt_id="dup")
    post(client, same)
    post(client, same)
    check("T6c the same Briefing (same attempt_id) sent twice makes two model calls", len(fake.calls) == 2, len(fake.calls))

sys.exit(report("T6 the executor composes nothing"))
