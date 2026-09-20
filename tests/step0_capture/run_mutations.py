"""
Mutation evidence for Step 0: each mutation is a deliberate defect applied in a
fresh process; the named suite must FAIL. A control run (no mutation) must PASS.

  python3 tests/step0_capture/run_mutations.py          run all, write MUTATIONS.txt
  python3 tests/step0_capture/run_mutations.py --child NAME   (internal)
"""
import io
import json
import os
import runpy
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

# name -> (suite, description)
MUTATIONS = {
    "control_goldens": ("goldens", "no mutation (must PASS)"),
    "control_capture": ("capture", "no mutation (must PASS)"),
    "g1_prompt_heading": ("goldens", "PromptBuilder heading 'THE MANDATE' -> 'THE MANDATE.' (+1 char in every PromptBuilder prompt)"),
    "g2_tool_description": ("goldens", "REPLY_TOOL description +2 chars"),
    "g3_reasoning_effort_dropped": ("goldens", "build_request omits reasoning_effort"),
    "g4_pm_temperature": ("goldens", "PM temperature 0.4 -> 0.5"),
    "g5_reconcile_mandate_word": ("goldens", "one word changed inside the hardcoded reconcile mandate"),
    "g6_dispatch_tool_law": ("goldens", "DISPATCH_TOOL_LAW +2 chars"),
    "g7_vertex_location": ("goldens", "vertex_location us-central1 -> us-east5"),
    "g8_schema_property_order": ("goldens", "COVERAGE_SCHEMA properties re-ordered (same keys, different order)"),
    "g9_l1_trailing_space": ("goldens", "compose_l1_lines output gains a trailing space (PM prompts only)"),
    "c1_second_copy": ("capture", "generate_content sends a modified COPY of build_request's dict (temperature 0.123)"),
    "c2_segment_offset": ("capture", "every segment start is off by one"),
    "c3_thread_context": ("capture", "collector stored thread-locally instead of in a ContextVar"),
    "c4_no_precall_copy": ("capture", "capture keeps the request by reference (no deepcopy at begin)"),
    "c5_collector_not_reset": ("capture", "capture_calls never resets the ContextVar (leaks into later requests)"),
    "c6_calls_always_present": ("capture", "attach_capture adds calls/kernel_version even when not requested"),
    "c7_segment_bytes_wrong": ("capture", "segment bytes = character count instead of UTF-8 bytes"),
    "c8_stub_drops_segments": ("capture", "oversize stub drops its segments"),
    "control_token": ("token", "no mutation (must PASS)"),
    "t1_gate_always_authorizes": ("token", "token check always returns True (any/no token honoured)"),
    "t2_empty_matches_empty": ("token", "empty-env guard removed (empty header == empty env authorizes)"),
    "t3_gate_ignored": ("token", "everything authorized regardless of header (flag honoured with no token)"),
    "t4_token_echoed_in_response": ("token", "attach_capture echoes the env token into a declared response field (kernel_version.revision)"),
    "t5_plain_equality": ("token", "token compared with == so hmac.compare_digest is no longer what runs (an invocation-spy check, not a timing test)"),
    "t6_token_printed": ("token", "token check prints the presented token to stdout (a log leak)"),
    "t7_unset_env_authorizes": ("token", "fail-open: an unset env var authorizes any request"),
    "t8_env_not_stripped": ("token", "env value is not stripped (a Secret Manager trailing newline breaks the match)"),
    "t9_no_min_length": ("token", "minimum token length removed (a 15-character token is accepted)"),
    "t10_presented_not_stripped": ("token", "presented header value is not stripped"),
    "t11_authorization_never_reset": ("token", "capture_gate never removes the authorization when the request ends"),
    "t12_non_ascii_token_accepted": ("token", "the visible-ASCII requirement on the configured token is removed entirely"),
    "t14_interior_space_allowed": ("token", "looser rule: isascii() and isprintable() (allows an interior space) instead of visible ASCII 0x21-0x7e"),
    "t13_reset_without_fallback": ("token", "reset_capture_authorized has no deny-fallback for a token from another context"),
}


def apply(name):
    import core.agent_factory as af
    import core.prompt_builder as pb
    import core.capture as cap

    if name.startswith("control"):
        return
    if name == "g1_prompt_heading":
        orig = pb.PromptBuilder.assemble
        pb.PromptBuilder.assemble = staticmethod(lambda **k: orig(**k).replace("THE MANDATE", "THE MANDATE.", 1))
    elif name == "g2_tool_description":
        from core import orchestrator_answer as oa
        oa.REPLY_TOOL["function"]["description"] += " x"
    elif name == "g3_reasoning_effort_dropped":
        orig = af.LiteLLMModel.build_request
        def build(self, *a, **k):
            out = orig(self, *a, **k)
            out.pop("reasoning_effort", None)
            return out
        af.LiteLLMModel.build_request = build
    elif name == "g4_pm_temperature":
        orig = af.AgentFactory.get_partner_pm
        def pm():
            model, config = orig()
            config.temperature = 0.5
            return model, config
        af.AgentFactory.get_partner_pm = staticmethod(pm)
    elif name == "g5_reconcile_mandate_word":
        orig = pb.PromptBuilder.assemble
        def assemble(mandate="", **k):
            if mandate and "fact-reconciliation function" in mandate:
                mandate = mandate.replace("REVISION", "REVISIONS", 1)
            return orig(mandate=mandate, **k)
        pb.PromptBuilder.assemble = staticmethod(assemble)
    elif name == "g6_dispatch_tool_law":
        import pods.social.engine as eng
        eng.DISPATCH_TOOL_LAW += " x"
    elif name == "g7_vertex_location":
        af.LOCATION = "us-east5"
    elif name == "g8_schema_property_order":
        from core.coverage import COVERAGE_SCHEMA
        COVERAGE_SCHEMA["properties"] = dict(reversed(list(COVERAGE_SCHEMA["properties"].items())))
    elif name == "g9_l1_trailing_space":
        import pods.social.engine as eng
        orig = eng.compose_l1_lines
        eng.compose_l1_lines = lambda persona: [line + " " for line in orig(persona)] if orig(persona) else orig(persona)
    elif name == "c1_second_copy":
        def mutated(self, prompt, generation_config=None, response_schema=None, tools=None, tool_choice=None, label=None, meta=None):
            request = self.build_request(prompt, generation_config, response_schema, tools, tool_choice)
            capture = cap.current_capture()
            call = capture.begin(label, meta, request, af._assembled_prompt(prompt)) if capture is not None else None
            response = af.LiteLLMResponse(af.litellm.completion(**dict(request, temperature=0.123)))
            if call is not None:
                capture.finish(call, response)
            return response
        af.LiteLLMModel.generate_content = mutated
    elif name == "c2_segment_offset":
        orig = pb.AssembledPrompt.segments.fget
        pb.AssembledPrompt.segments = property(lambda self: [dict(s, start=s["start"] + 1) for s in orig(self)])
    elif name == "c3_thread_context":
        import threading
        tl = threading.local()
        cap._CAPTURE = type("V", (), {"get": lambda self: getattr(tl, "c", None), "set": lambda self, c: setattr(tl, "c", c) or "t", "reset": lambda self, t: setattr(tl, "c", None)})()
    elif name == "c4_no_precall_copy":
        cap.copy = type("C", (), {"deepcopy": staticmethod(lambda x: x)})
    elif name == "c5_collector_not_reset":
        from contextlib import contextmanager
        @contextmanager
        def leaky(enabled, max_bytes=None):
            if not enabled:
                yield None
                return
            c = cap.CallCapture(max_bytes)
            cap._CAPTURE.set(c)
            yield c
        cap.capture_calls = leaky
        import main
        main.capture_calls = leaky
    elif name == "c6_calls_always_present":
        def always(response, capture):
            response = dict(response)
            response["calls"] = capture.to_list() if capture else []
            response["kernel_version"] = cap.kernel_version()
            return response
        cap.attach_capture = always
        import main
        main.attach_capture = always
    elif name == "c7_segment_bytes_wrong":
        orig = pb.AssembledPrompt.segments.fget
        pb.AssembledPrompt.segments = property(lambda self: [dict(s, bytes=s["end"] - s["start"]) for s in orig(self)])
    elif name == "c8_stub_drops_segments":
        orig = cap.CallCapture._entry
        def entry(self, call):
            e = orig(self, call)
            if e["oversize"]:
                e["segments"] = []
            return e
        cap.CallCapture._entry = entry
    elif name in ("t1_gate_always_authorizes", "t2_empty_matches_empty", "t5_plain_equality", "t6_token_printed", "t7_unset_env_authorizes", "t8_env_not_stripped", "t9_no_min_length", "t10_presented_not_stripped", "t12_non_ascii_token_accepted", "t14_interior_space_allowed"):
        import hmac as _hmac, os as _os
        import main
        def make(kind):
            def valid(presented):
                raw_env = _os.environ.get("KERNEL_CAPTURE_TOKEN") or ""
                expected = raw_env if kind == "t8_env_not_stripped" else raw_env.strip()
                pres = str(presented) if (presented and kind == "t10_presented_not_stripped") else (str(presented).strip() if presented else "")
                min_len = 1 if kind == "t9_no_min_length" else 16
                if kind == "t1_gate_always_authorizes":
                    return True
                if kind == "t2_empty_matches_empty":
                    if expected != "" and len(expected) < 16:
                        return False
                    return _hmac.compare_digest(pres.encode(), expected.encode())
                if kind == "t6_token_printed":
                    print(f"presented={presented}")
                if kind == "t7_unset_env_authorizes" and "KERNEL_CAPTURE_TOKEN" not in _os.environ:
                    return True
                if len(expected) < min_len or not pres:
                    return False
                if kind == "t14_interior_space_allowed":
                    if not expected.isascii() or not expected.isprintable():
                        return False
                elif kind != "t12_non_ascii_token_accepted" and not all(0x21 <= ord(ch) <= 0x7E for ch in expected):
                    return False
                if kind == "t5_plain_equality":
                    return pres == expected
                return _hmac.compare_digest(pres.encode(), expected.encode())
            return valid
        cap.capture_token_valid = make(name)
        main.capture_token_valid = cap.capture_token_valid
        if name == "t5_plain_equality":
            cap.hmac = type("H", (), {"compare_digest": staticmethod(lambda a, b: a == b)})
    elif name == "t11_authorization_never_reset":
        import main
        cap.reset_capture_authorized = lambda token: None
        main.reset_capture_authorized = cap.reset_capture_authorized
    elif name == "t13_reset_without_fallback":
        import main
        def strict_reset(token):
            cap._AUTHORIZED.reset(token)
        cap.reset_capture_authorized = strict_reset
        main.reset_capture_authorized = strict_reset
    elif name == "t3_gate_ignored":
        import main
        cap._AUTHORIZED = contextvars_default_true()
        cap.set_capture_authorized = lambda a: None
        main.set_capture_authorized = cap.set_capture_authorized
    elif name == "t4_token_echoed_in_response":
        import os as _os, main
        orig = cap.attach_capture
        def echo(response, capture):
            out = orig(response, capture)
            if capture is not None:
                out = dict(out)
                out["kernel_version"] = dict(out["kernel_version"], revision=_os.environ.get("KERNEL_CAPTURE_TOKEN"))
            return out
        cap.attach_capture = echo
        main.attach_capture = echo
    else:
        raise SystemExit(f"unknown mutation {name}")


def contextvars_default_true():
    import contextvars
    return contextvars.ContextVar("kernel_capture_authorized", default=True)


def run_suite(suite):
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        if suite == "goldens":
            import run_goldens
            sys.argv = ["run_goldens.py"]
            rc = run_goldens.main()
        else:
            try:
                runpy.run_path(os.path.join(HERE, "test_capture_token.py" if suite == "token" else "test_capture.py"), run_name="__main__")
                rc = 0
            except SystemExit as exc:
                rc = exc.code or 0
            except Exception as exc:  # a mutation can also crash the suite: that is a detection too
                print(f"[FAIL] suite crashed: {type(exc).__name__}: {exc}")
                rc = 1
    lines = buf.getvalue().splitlines()
    fails = [ln for ln in lines if ln.startswith("[FAIL]")]
    total = next((ln for ln in reversed(lines) if "checks," in ln), "")
    return rc, fails, total


def child(name):
    suite = MUTATIONS[name][0]
    apply(name)
    rc, fails, total = run_suite(suite)
    print(json.dumps({"rc": rc, "fails": fails, "total": total}))


def parent():
    rows, ok_all = [], True
    for name, (suite, desc) in MUTATIONS.items():
        proc = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", name], capture_output=True, text=True, cwd=ROOT)
        try:
            result = json.loads(proc.stdout.strip().splitlines()[-1])
        except Exception:
            result = {"rc": 99, "fails": [f"[FAIL] child produced no result: {proc.stderr[-300:]}"], "total": ""}
        is_control = name.startswith("control")
        detected = result["rc"] != 0
        ok = (not detected) if is_control else detected
        ok_all &= ok
        rows.append((name, suite, desc, ok, is_control, result))
    out = ["Step 0 mutation evidence: every mutation must be DETECTED (suite fails); controls must PASS.", ""]
    for name, suite, desc, ok, is_control, r in rows:
        verdict = ("PASS (no failures)" if ok else "UNEXPECTED FAILURE") if is_control else ("DETECTED" if ok else "MISSED")
        out.append(f"{verdict:20} {name}  [{suite}]  {desc}")
        if not is_control:
            scenarios = sorted({ln[7:].split(":")[0] for ln in r["fails"]})
            out.append(f"{'':20}   failing checks: {len(r['fails'])}; distinct scenarios/areas: {len(scenarios)}")
            for ln in r["fails"][:3]:
                out.append(f"{'':20}   e.g. {ln[:170]}")
        else:
            out.append(f"{'':20}   {r['total'].strip()}")
    out.append("")
    out.append(f"RESULT: {'ALL MUTATIONS DETECTED, CONTROLS CLEAN' if ok_all else 'SOME MUTATIONS MISSED OR A CONTROL FAILED'}")
    text = "\n".join(out)
    print(text)
    with open(os.path.join(HERE, "MUTATIONS.txt"), "w") as f:
        f.write(text + "\n")
    return 0 if ok_all else 1


if __name__ == "__main__":
    if "--child" in sys.argv:
        child(sys.argv[sys.argv.index("--child") + 1])
    else:
        sys.exit(parent())
