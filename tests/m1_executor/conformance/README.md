# Executor conformance harness (K1e)

A self-contained check that a Kernel executor behaves the way Backend's client must expect: the
four literal sha vectors, authentication, every 422 code, a generic provider error for each of the
nine categories, result shape, parse modes, byte-exactness, health and capabilities. Backend can run
it against a local server without help from the Kernel session.

`run_conformance.py` is also a **reference client**. It uses only the Python standard library, and the
functions at the top of the file (`canonical_json`, `request_params`, `request_sha256`, `make_briefing`)
are a compact, independent implementation of the request rules in C1 sections 2 and 5. If your client
disagrees with the vectors in check `C-V2a`..`C-V4a`, your canonicalization is wrong, not Kernel.

## Run it (no network, no Google credentials, no cost)

From the Kernel repository root, with Kernel's dependencies installed (`pip install -r requirements.txt`):

    python3 tests/m1_executor/conformance/run_conformance.py

That starts the REAL executor (`main.app`, the code that is deployed) on a free localhost port with a
throwaway random token that is never printed, and with **one** thing replaced: `litellm.acompletion` is
a deterministic fake (`serve_fake.py`). Expected last line: `100 checks, 0 failed, 0 skipped -> CONFORMANT`
and exit code 0. A failure prints the check id, the C1/K1 section it comes from and what was received.

Options: `--json report.json` writes the results.

## Point it at another server

    # your own launch of the fake server
    KERNEL_AUTH_TOKEN=<throwaway> python3 tests/m1_executor/conformance/serve_fake.py --port 8899
    KERNEL_AUTH_TOKEN=<same token> python3 tests/m1_executor/conformance/run_conformance.py --url http://127.0.0.1:8899 --fake

    # a REAL Kernel (deployed or local): only the checks that need no model call run,
    # unless you accept real (cheap) model calls
    KERNEL_AUTH_TOKEN=<its token> python3 tests/m1_executor/conformance/run_conformance.py --url https://<kernel> [--allow-model-calls]

The token is read from the environment and never printed. Against a real Kernel the provider-error, parse
and echo checks are skipped (they need the fake, which chooses its behavior from `call_label`).

## What the fake does (`serve_fake.py`)

It chooses from the Briefing's `call_label` (Backend never uses these labels in production):
`conf.echo` returns the prompt text it received byte for byte; `conf.tool_calls`, `conf.length`,
`conf.grounded`, `conf.reasoning`, `conf.json.plain|fenced|list|invalid`, `conf.slow` (5 s, use `timeout_s: 1`),
and `conf.error.<category>` for the nine error categories (the raw exception text contains
`SECRET-PROVIDER-TEXT` and a `projects/<id>` path, so a leak into a response body is caught).

## What is checked

| Group | Checks | Source |
|---|---|---|
| A health and capabilities | health is open and minimal; capabilities needs the token and has exactly five keys | K1 1 |
| B authentication | 401 with no header, a wrong token, the token in `Authorization`, an empty header; all bodies byte-identical; garbage body gets 401 not 422 | K1 2, K-T7 |
| C the four vectors | your `prompt_sha256` and `request_sha256` equal the literals V1-V4; wrong shas give 422 `prompt_sha_mismatch` / `request_sha_mismatch` with Kernel's computed value; the accepted Briefing returns the literals | C1 5.1, 5.2 |
| D every 422 code | `unknown_field`, `missing_field`, `invalid_type`, `invalid_value`, `invalid_format`, `out_of_range`, `not_allowed`, `too_large`, `invalid_json`, `not_an_object`, `invalid_prompt`, `invalid_text`, `prompt_sha_mismatch`, `request_sha_mismatch`, each with the right `field` | C1 2, 5.4 |
| E result shape | all sixteen keys; echoes; timing; `reasoning_tokens`; tool calls kept in order (malformed one too); grounding sources; `finish_reason: length` is still `status: ok` | C1 4 |
| F provider errors | for each category: HTTP 200, `status: error`, the fixed generic message, retryable flag, provider status, no provider text, shas still returned; Kernel's own timeout has `provider_status: null` | C1 4.4 |
| G parse modes | strict, fenced, lenient, list, invalid, text | C1 4.3 |
| H byte exactness | a six-layer prompt with CRLF, emoji, NUL, U+2028/2029 reaches the model unchanged; sizes and shas match; `60` vs `60.0` hash differently; a 4 MiB prompt is accepted | C1 2.2, 5 |

## Things a client should know (each is checked or documented here)

- **The error code is `error.code`, not `error.type`.** A 422 body is `{"error": {"type": "invalid_briefing", "code": "...", "field": "..."}}`.
- **Provider failures are HTTP 200** with `status: "error"`; branch on `status` and `error.type` / `error.retryable`, never on `error.message`.
- **Hash the same JSON number you send.** `60` and `60.0` produce different `request_sha256`. Non-ASCII text is hashed as itself (`ensure_ascii=False`), keys sorted at every level, no whitespace.
- **`max_output_tokens` is hashed under the litellm name `max_tokens`, and `timeout_s` as `timeout`.** Null fields are omitted from the hashed object. `messages` and `vertex_*` are never hashed.
- **A wrong token with a very large body may surface as a connection reset** rather than a readable 401: Kernel refuses before reading the body, so the socket can close while the client is still sending. Handle transport errors on a 401-class failure.
- **Send the header `X-Kernel-Auth-Token`**, not `Authorization` (which the later identity lock will need).
