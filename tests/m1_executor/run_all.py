"""
Runs every offline suite: the Milestone 1 executor suites and the legacy suites that
must stay green until their sites are deleted (M4). No network, no real model.
(tests/phase_2a and phase_2b call the real Vertex model and are NOT run here.)

Run: python3 tests/m1_executor/run_all.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SUITES = [
    "tests/m1_executor/test_contract.py",
    "tests/m1_executor/test_endpoint.py",
    "tests/m1_executor/test_isolation.py",
    "tests/m1_executor/conformance/run_conformance.py",
    "tests/step0_capture/run_goldens.py",
    "tests/step0_capture/test_capture.py",
    "tests/step0_capture/test_capture_token.py",
    "tests/phase_1_5/test_trigger_sequencing_regression.py",
    "tests/phase_4/test_chat_manager_graceful_failure.py",
    "tests/phase_7_prep/test_ancestor_chat_summary.py",
]

failed = []
for suite in SUITES:
    proc = subprocess.run([sys.executable, suite], cwd=ROOT, capture_output=True, text=True)
    lines = [l for l in proc.stdout.splitlines() if "checks" in l and ("PASS" in l or "FAIL" in l)]
    print(f"{'ok  ' if proc.returncode == 0 else 'FAIL'} {suite}: {lines[-1].strip() if lines else proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ''}")
    if proc.returncode != 0:
        failed.append(suite)
print("\nALL GREEN" if not failed else f"\nFAILED: {failed}")
sys.exit(1 if failed else 0)
