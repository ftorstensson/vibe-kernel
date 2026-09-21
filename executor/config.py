"""
Milestone 1 executor configuration (docs/m0/K1 section 4, C1 section 2).

Everything here is Kernel configuration: none of it is a Briefing field and
Backend cannot change any of it per request. Read at call time (not import
time) wherever it comes from the environment, so a deploy that changes an env
var needs no code change and a test can patch it.
"""
import os

CONTRACT_VERSION = 1

# Regional physics: same defaults as the legacy factory (core/agent_factory.py),
# deliberately not imported from it (the executor must not depend on legacy code).
DEFAULT_PROJECT = "vibe-agent-final"
LOCATION = "us-central1"

# Guardrails (PM decision 2026-09-21). A new model is a Kernel config change.
ALLOWED_MODELS = ("vertex_ai/gemini-2.5-pro", "vertex_ai/gemini-2.5-flash")
ALLOWED_TOOL_SHAPES = ("function", "googleSearch")
MAX_PROMPT_BYTES = 4 * 1024 * 1024
MAX_TIMEOUT_S = 280
MAX_SEGMENTS = 2000
MAX_SEGMENTS_BYTES = 256 * 1024
# Cloud Run's own request-body limit is 32 MiB; a prompt is at most 4 MiB of
# UTF-8, but JSON escaping can inflate it, so the body cap is the platform's.
MAX_BODY_BYTES = 32 * 1024 * 1024

# Interim shared-secret gate (PM decision 2026-09-21). NOT Authorization: the
# identity token Backend sends at K3 will need that header.
AUTH_HEADER = "X-Kernel-Auth-Token"
AUTH_ENV = "KERNEL_AUTH_TOKEN"
MIN_TOKEN_LENGTH = 16

# Cap on raw provider text written to Kernel's own log line.
LOG_PROVIDER_TEXT_CAP = 2000


def project_id():
    return os.getenv("GOOGLE_CLOUD_PROJECT", DEFAULT_PROJECT)


def kernel_version():
    return {"revision": os.getenv("K_REVISION"), "git_sha": os.getenv("KERNEL_GIT_SHA")}
