"""teardown.sh step-4 probe-failure abort (WP01 review finding 1).

The defect class: ``die`` inside a command substitution only exits the
subshell, so ``[ -n "$(webhook_pids)" ]`` would read a pgrep probe failure
(rc >= 2) as "no pids remain" and let removal proceed against a webhook whose
state is unknown. The fix assigns the substitution first, so the failure
propagates under ``set -e`` and the script aborts BEFORE any removal step.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEARDOWN = REPO_ROOT / "scripts" / "decommission" / "office2" / "teardown.sh"


def _stub(bin_dir: Path, name: str, body: str) -> None:
    p = bin_dir / name
    p.write_text(f"#!/bin/sh\n{body}\n")
    p.chmod(0o755)


def test_pgrep_failure_mid_wait_aborts_before_removal(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # docker: reachable, but no qa-register containers/images anywhere.
    _stub(bin_dir, "docker", "exit 0")
    # pgrep: first call reports a live webhook pid (a pid that does not
    # exist, so the script's `kill || true` is a no-op); every later call
    # fails with rc=3 — the probe broke mid-wait.
    counter = tmp_path / "pgrep-calls"
    _stub(
        bin_dir,
        "pgrep",
        f'c=$(cat "{counter}" 2>/dev/null || echo 0)\n'
        f'c=$((c+1)); echo "$c" > "{counter}"\n'
        'if [ "$c" -le 1 ]; then echo 99999; exit 0; else exit 3; fi',
    )
    # sleep: instant, so the 30-iteration wait loop does not slow the test.
    _stub(bin_dir, "sleep", "exit 0")

    svc = tmp_path / "qa-register"
    svc.mkdir()
    (svc / "register.db").write_text("dbdata\n")
    home = tmp_path / "home-claude"
    home.mkdir()
    (home / "start-webhook.sh").write_text("launcher\n")
    (home / "qa-webhook.pid").write_text("99999\n")
    (home / "qa-webhook.log").write_text("log\n")
    bundle = tmp_path / "bundle"

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["QA_TEARDOWN_BUNDLE"] = str(bundle)
    env["QA_TEARDOWN_SERVICE_DIR"] = str(svc)
    env["QA_TEARDOWN_CLAUDE_HOME"] = str(home)

    proc = subprocess.run(
        ["bash", str(TEARDOWN), "--apply"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )

    assert proc.returncode != 0, (
        "a pgrep probe failure mid-wait must abort the teardown, not read as "
        f"'webhook exited'\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    # Removal was NOT reached: every removal target is still in place.
    assert svc.exists(), "service dir was removed despite an unverifiable webhook state"
    assert (home / "start-webhook.sh").exists()
    assert (home / "qa-webhook.pid").exists()
    assert (home / "qa-webhook.log").exists()
    # The archive half (which precedes step 4) did run — the abort is step 4's.
    assert (bundle / "CLAUDE-MANIFEST.txt").exists()
    assert "step5" not in proc.stdout and "step6" not in proc.stdout


def test_healthy_wait_still_completes(tmp_path):
    """Control: pid gone on the re-probe (rc=1) lets teardown finish."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "docker", "exit 0")
    counter = tmp_path / "pgrep-calls"
    _stub(
        bin_dir,
        "pgrep",
        f'c=$(cat "{counter}" 2>/dev/null || echo 0)\n'
        f'c=$((c+1)); echo "$c" > "{counter}"\n'
        'if [ "$c" -le 1 ]; then echo 99999; exit 0; else exit 1; fi',
    )
    _stub(bin_dir, "sleep", "exit 0")

    svc = tmp_path / "qa-register"
    svc.mkdir()
    (svc / "register.db").write_text("dbdata\n")
    home = tmp_path / "home-claude"
    home.mkdir()
    (home / "start-webhook.sh").write_text("launcher\n")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["QA_TEARDOWN_BUNDLE"] = str(tmp_path / "bundle")
    env["QA_TEARDOWN_SERVICE_DIR"] = str(svc)
    env["QA_TEARDOWN_CLAUDE_HOME"] = str(home)

    proc = subprocess.run(
        ["bash", str(TEARDOWN), "--apply"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert not svc.exists()
    assert not (home / "start-webhook.sh").exists()
