"""Tri-state classifier tests for the QA-pipeline teardown verify.sh (WP01/T005).

The property that matters (Engineering Principle 14, NFR-001): a PROBE ERROR —
missing tool, non-zero probe exit, permission denial — must classify as
UNCHECKABLE, never as ABSENT. A verifier that reports "verified removed" when
it could not check converts an unknown into a false assurance, which is
exactly the failure class this mission's acceptance instrument exists to
prevent. Probes are stubbed via PATH shadowing; filesystem surfaces via the
script's QA_VERIFY_* env overrides.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY = REPO_ROOT / "scripts" / "decommission" / "office2" / "verify.sh"


def _write_stub(bin_dir: Path, name: str, body: str) -> None:
    p = bin_dir / name
    p.write_text(f"#!/bin/sh\n{body}\n")
    p.chmod(0o755)


def _run(env_overrides: dict[str, str], stub_bin: Path, args: list[str] | None = None):
    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"
    env.update(env_overrides)
    proc = subprocess.run(
        ["bash", str(VERIFY)] + (args or []),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    verdicts = {}
    for line in proc.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0].startswith("V-"):
            verdicts[parts[0]] = parts[1]
    return proc, verdicts


@pytest.fixture
def surfaces(tmp_path):
    """Filesystem surfaces in a traversable tmp tree (so path checks are
    conclusive) with every removal target absent."""
    claude_home = tmp_path / "home-claude"
    claude_home.mkdir()
    (tmp_path / "etc").mkdir()  # traversable parent -> V-11 is conclusive
    return {
        "QA_VERIFY_BUNDLE": str(tmp_path / "bundle"),
        "QA_VERIFY_SERVICE_DIR": str(tmp_path / "qa-register"),
        "QA_VERIFY_CLAUDE_HOME": str(claude_home),
        "QA_VERIFY_ROOT_ENV": str(tmp_path / "etc" / "qa-webhook.env"),
        "QA_VERIFY_CANARY_STATE": str(tmp_path / "canary-last-tick.json"),
    }


@pytest.fixture
def broken_probes(tmp_path):
    """Every command probe errors out (exit >= 1 in each tool's error band)."""
    bin_dir = tmp_path / "stub-bin-broken"
    bin_dir.mkdir()
    _write_stub(bin_dir, "pgrep", "exit 3")          # >= 2 = pgrep probe failure
    _write_stub(bin_dir, "ss", "exit 255")
    _write_stub(bin_dir, "tailscale", "exit 1")
    _write_stub(bin_dir, "docker", "exit 1")
    _write_stub(bin_dir, "sg", "exit 1")             # sg fallback also broken
    _write_stub(bin_dir, "crontab", "echo 'permission denied' >&2; exit 2")
    _write_stub(bin_dir, "systemctl", "exit 1")
    return bin_dir


@pytest.fixture
def clean_probes(tmp_path):
    """Every probe succeeds and reports the surface conclusively gone."""
    bin_dir = tmp_path / "stub-bin-clean"
    bin_dir.mkdir()
    _write_stub(bin_dir, "pgrep", "exit 1")          # 1 = no process matched
    _write_stub(
        bin_dir, "ss",
        'echo "State  Recv-Q Send-Q Local Address:Port Peer Address:Port"\n'
        'echo "LISTEN 0 128 127.0.0.1:22 0.0.0.0:*"',
    )
    _write_stub(bin_dir, "tailscale", 'echo "No serve config"; exit 0')
    _write_stub(bin_dir, "docker", "exit 0")         # empty listing, rc 0
    _write_stub(bin_dir, "crontab", 'echo "no crontab for claude" >&2; exit 1')
    _write_stub(bin_dir, "systemctl", 'echo "felix-canary.timer enabled"; exit 0')
    return bin_dir


class TestProbeErrorNeverAbsent:
    """THE Principle-14 property: probe error -> UNCHECKABLE, never ABSENT."""

    def test_all_probe_backed_checks_uncheckable(self, surfaces, broken_probes):
        proc, verdicts = _run(surfaces, broken_probes)
        probe_backed = ["V-01", "V-02", "V-03", "V-04", "V-05", "V-06", "V-07", "V-15"]
        for check in probe_backed:
            assert verdicts.get(check) == "UNCHECKABLE", (
                f"{check} classified {verdicts.get(check)!r} on a probe error — "
                f"a broken probe must never read as verified-absent.\n{proc.stdout}"
            )

    def test_no_removal_check_reads_absent_on_error(self, surfaces, broken_probes):
        _, verdicts = _run(surfaces, broken_probes)
        for check in ["V-01", "V-02", "V-03", "V-04", "V-05", "V-06", "V-07", "V-15"]:
            assert verdicts.get(check) != "ABSENT"

    def test_exit_nonzero_with_uncheckables(self, surfaces, broken_probes):
        proc, _ = _run(surfaces, broken_probes)
        assert proc.returncode != 0, "UNCHECKABLE results must never pass the gate"


class TestConclusiveClassification:
    def test_clean_teardown_classifies_absent(self, surfaces, clean_probes):
        proc, verdicts = _run(surfaces, clean_probes)
        for check in ["V-01", "V-02", "V-03", "V-04", "V-05", "V-06", "V-07",
                      "V-08", "V-09", "V-10", "V-11", "V-15"]:
            assert verdicts.get(check) == "ABSENT", (
                f"{check}={verdicts.get(check)!r}\n{proc.stdout}"
            )

    def test_surviving_surfaces_classify_present(self, surfaces, tmp_path):
        bin_dir = tmp_path / "stub-bin-present"
        bin_dir.mkdir()
        _write_stub(bin_dir, "pgrep", "exit 0")      # process still matches
        _write_stub(
            bin_dir, "ss",
            'echo "LISTEN 0 4096 127.0.0.1:3457 0.0.0.0:*"\n'
            'echo "LISTEN 0 4096 *:8443 *:*"\n'
            'echo "LISTEN 0 4096 100.92.197.90:8788 0.0.0.0:*"',
        )
        _write_stub(bin_dir, "tailscale",
                    'echo "https://office2.example.ts.net:8443 (Funnel on)"; exit 0')
        _write_stub(bin_dir, "docker", 'echo "qa-register:fb679e6"; echo "qa-register"')
        _write_stub(bin_dir, "crontab", 'echo "no crontab for claude" >&2; exit 1')
        _write_stub(bin_dir, "systemctl", "exit 0")
        proc, verdicts = _run(surfaces, bin_dir)
        for check in ["V-01", "V-02", "V-03", "V-04", "V-05", "V-06", "V-07"]:
            assert verdicts.get(check) == "PRESENT", (
                f"{check}={verdicts.get(check)!r}\n{proc.stdout}"
            )
        assert proc.returncode != 0

    def test_missing_dir_with_unreadable_parent_is_uncheckable(
        self, surfaces, clean_probes, tmp_path
    ):
        # A path that does not exist under an untraversable parent is NOT
        # verified-absent — the classifier must say so.
        surfaces = dict(surfaces)
        surfaces["QA_VERIFY_SERVICE_DIR"] = str(tmp_path / "no-such-parent" / "qa-register")
        _, verdicts = _run(surfaces, clean_probes)
        assert verdicts.get("V-08") == "UNCHECKABLE"


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_bundle(surfaces: dict[str, str], *, attestation: bool = True,
                 env_mode: str = "unreadable") -> Path:
    """Build a bundle whose CLAUDE-MANIFEST verifies, with a root-produced
    qa-webhook.env entry in ROOT-MANIFEST per *env_mode*:
      unreadable — chmod 000 (the production shape: 0600 root)
      mismatch   — readable but ROOT-MANIFEST carries a wrong hash
    """
    bundle = Path(surfaces["QA_VERIFY_BUNDLE"])
    bundle.mkdir(parents=True, exist_ok=True)
    db = bundle / "register.db"
    db.write_text("dbdata\n")
    (bundle / "CLAUDE-MANIFEST.txt").write_text(f"{_sha256(db)}  register.db\n")
    env = bundle / "qa-webhook.env"
    env.write_text("TEST_PLACEHOLDER=not-a-real-credential\n")
    if env_mode == "mismatch":
        root_hash = "0" * 64
    else:
        root_hash = _sha256(env)
    (bundle / "ROOT-MANIFEST.txt").write_text(f"{root_hash}  qa-webhook.env\n")
    if env_mode == "unreadable":
        env.chmod(0o000)
    marker = "root-manifest-verified: yes\n" if attestation else "root-manifest-verified: no\n"
    (bundle / "operator-complete.txt").write_text(
        "mission: qa-pipeline-decommission-01M219TT\n" + marker
    )
    return bundle


def _write_canary(surfaces: dict[str, str], status: str, age_seconds: int) -> None:
    import json
    from datetime import datetime, timedelta, timezone

    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    Path(surfaces["QA_VERIFY_CANARY_STATE"]).write_text(
        json.dumps({"status": status, "completed_at_utc": ts.isoformat()})
    )


class TestArchiveIntegrityClassifier:
    """V-12: root-produced entries the claude user cannot read (finding 3)."""

    def test_unreadable_entry_with_attestation_is_ok(self, surfaces, clean_probes):
        _make_bundle(surfaces, attestation=True, env_mode="unreadable")
        proc, verdicts = _run(surfaces, clean_probes)
        assert verdicts.get("V-12") == "OK", proc.stdout

    def test_unreadable_entry_without_attestation_is_uncheckable(
        self, surfaces, clean_probes
    ):
        # Cannot hash it, root never attested — that is NOT a pass.
        _make_bundle(surfaces, attestation=False, env_mode="unreadable")
        proc, verdicts = _run(surfaces, clean_probes)
        assert verdicts.get("V-12") == "UNCHECKABLE", proc.stdout
        assert proc.returncode != 0

    def test_hash_mismatch_is_fail(self, surfaces, clean_probes):
        _make_bundle(surfaces, attestation=True, env_mode="mismatch")
        proc, verdicts = _run(surfaces, clean_probes)
        assert verdicts.get("V-12") == "FAIL", proc.stdout
        assert proc.returncode != 0


def _since_past(seconds: int = 86400) -> list[str]:
    """A --since reference *seconds* in the past (epoch form)."""
    import time

    return ["--since", str(int(time.time()) - seconds)]


class TestCanaryClassifier:
    """V-13: stale is could-not-check; an explicit bad tick is FAIL (finding 3);
    only a tick POSTdating the --since teardown reference can vouch (Codex 3)."""

    def test_stale_green_tick_is_uncheckable(self, surfaces, clean_probes):
        _write_canary(surfaces, "success", age_seconds=4000)  # > 2100s bound
        proc, verdicts = _run(surfaces, clean_probes, _since_past())
        assert verdicts.get("V-13") == "UNCHECKABLE", proc.stdout

    def test_failed_tick_is_fail(self, surfaces, clean_probes):
        _write_canary(surfaces, "failure", age_seconds=10)
        proc, verdicts = _run(surfaces, clean_probes, _since_past())
        assert verdicts.get("V-13") == "FAIL", proc.stdout

    def test_fresh_green_tick_is_ok(self, surfaces, clean_probes):
        _write_canary(surfaces, "success", age_seconds=10)
        proc, verdicts = _run(surfaces, clean_probes, _since_past())
        assert verdicts.get("V-13") == "OK", proc.stdout

    def test_fresh_green_tick_predating_since_is_uncheckable(
        self, surfaces, clean_probes
    ):
        # A fresh green tick that PREdates the teardown reference proves
        # nothing about post-teardown collateral health.
        import time

        _write_canary(surfaces, "success", age_seconds=600)  # fresh (< 2100s)
        future_ref = ["--since", str(int(time.time()) - 10)]  # tick older than ref
        proc, verdicts = _run(surfaces, clean_probes, future_ref)
        assert verdicts.get("V-13") == "UNCHECKABLE", proc.stdout
        assert "predates" in proc.stdout

    def test_missing_since_is_uncheckable(self, surfaces, clean_probes):
        _write_canary(surfaces, "success", age_seconds=10)
        proc, verdicts = _run(surfaces, clean_probes)  # no --since at all
        assert verdicts.get("V-13") == "UNCHECKABLE", proc.stdout

    def test_unparseable_since_is_uncheckable(self, surfaces, clean_probes):
        _write_canary(surfaces, "success", age_seconds=10)
        proc, verdicts = _run(surfaces, clean_probes, ["--since", "not-a-time"])
        assert verdicts.get("V-13") == "UNCHECKABLE", proc.stdout

    def test_iso_since_accepted(self, surfaces, clean_probes):
        from datetime import datetime, timedelta, timezone

        _write_canary(surfaces, "success", age_seconds=10)
        iso_ref = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        proc, verdicts = _run(surfaces, clean_probes, ["--since", iso_ref])
        assert verdicts.get("V-13") == "OK", proc.stdout


class TestPersistencePositiveOutranksProbeFailure:
    """V-15 (finding 4): a QA hit already found must survive a later probe error."""

    def test_crontab_hit_with_broken_systemctl_is_present(self, surfaces, tmp_path):
        bin_dir = tmp_path / "stub-bin-v15"
        bin_dir.mkdir()
        _write_stub(bin_dir, "pgrep", "exit 1")
        _write_stub(bin_dir, "ss", 'echo "State"; exit 0')
        _write_stub(bin_dir, "tailscale", 'echo "No serve config"; exit 0')
        _write_stub(bin_dir, "docker", "exit 0")
        _write_stub(bin_dir, "crontab", 'echo "0 * * * * /home/claude/start-webhook.sh # qa-webhook"')
        _write_stub(bin_dir, "systemctl", "exit 1")  # later probe breaks
        proc, verdicts = _run(surfaces, bin_dir)
        assert verdicts.get("V-15") == "PRESENT", proc.stdout


class TestExternalProbe:
    """V-14: the curl classification (run with --external)."""

    def _curl_case(self, surfaces, tmp_path, rc: int):
        bin_dir = tmp_path / f"stub-curl-{rc}"
        bin_dir.mkdir()
        _write_stub(bin_dir, "curl", f"exit {rc}")
        return _run(surfaces, bin_dir, ["--external"])

    def test_http_answer_is_present(self, surfaces, tmp_path):
        _, verdicts = self._curl_case(surfaces, tmp_path, 0)
        assert verdicts.get("V-14") == "PRESENT"

    def test_connection_refused_is_absent(self, surfaces, tmp_path):
        _, verdicts = self._curl_case(surfaces, tmp_path, 7)
        assert verdicts.get("V-14") == "ABSENT"

    @pytest.mark.parametrize("rc", [6, 28, 52])
    def test_transport_ambiguity_is_uncheckable_never_absent(
        self, surfaces, tmp_path, rc
    ):
        # DNS failure / timeout / empty reply cannot distinguish "service
        # removed" from "probe never reached the host" (Principle 14).
        proc, verdicts = self._curl_case(surfaces, tmp_path, rc)
        assert verdicts.get("V-14") == "UNCHECKABLE"
        assert proc.returncode != 0
