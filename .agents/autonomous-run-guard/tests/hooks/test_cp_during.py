r"""Tests for CP-DURING — ``scripts/hooks/checkpoints/during.py`` and ``fault_ledger.py``.

⚠ **CP-DURING IS NOT A GATE.** Nothing in this module asserts a denial, because
``PostToolUseFailure`` has no deny authority: the tool has already run. What is asserted
is that a fault was *recorded* and the SOP was *emitted*. Neither claim reaches as far as
"the agent complied", and no assertion here should be written as though it did (C-004).

WHY THE WIRE TESTS EXIST
------------------------
WP03 was rejected because 52 mutations could not see two blocking defects: the
implementation and its tests shared one false premise about how a Claude Code Bash
command is shaped. **Mutation testing cannot detect a false premise shared by the
implementation and its tests.** So the load-bearing behaviours here are driven through
``mission_lifecycle_gate.py`` in a real subprocess, with a **multi-line** command — the
everyday shape of a Bash tool call, and the exact shape that hid those defects.

Direct calls into ``during.evaluate`` appear *alongside* the wire tests, never instead of
them, for the one filter the dispatcher also applies (``is_interrupt``): a wire-only test
of that filter would pass even if ``during.py`` had no filter at all, because the
dispatcher short-circuits first. Both layers own the rule; both are pinned.

ISOLATION
---------
Almost every test routes the ledger through the explicit ``SPEC_KITTY_HOOKS_ROOT`` env seam
into ``tmp_path`` and uses a unique ``session_id``.

⚠ **One deliberately does not, and that this was once universal is exactly what hid F1.** With
every test supplying the env seam, the production root-resolution path had no coverage at all,
so a silently-dropped fault survived eighteen mutants. See
``test_an_unresolvable_hooks_root_does_not_silently_drop_the_fault``, and do not "restore
consistency" by giving it the seam — that would make it unable to fail. Nothing here writes outside ``tmp_path``,
invokes ``spec-kitty``, or touches the network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
GATE = SCRIPTS_DIR / "hooks" / "mission_lifecycle_gate.py"

# Credential-shaped probes. Deliberately fake and deliberately *shaped* like the real
# thing — NFR-004 is about the field an assertion forgot, so the probe has to look like
# something a redactor would be tempted to let through.
FAKE_TOKEN = "ghp_notarealtokennotarealtokennotareal"
FAKE_PASSWORD = "password=hunter2"
#: ⚠ Short and shape-safe on purpose. The long/odd-shaped probes above are caught by the
#: token shape rule alone, so they cannot tell whether the flag-value allowlist does
#: anything. This one is indistinguishable from a mission handle by shape — only the
#: allowlist can redact it — and it is what makes ``--api-key abc123`` a tested case.
SHORT_SECRET = "s3cr3t"

# Asserted against the RENDERED output, never imported from the module under test. A test
# that finds a module's own constant in that module's own output has checked nothing.
SOP_PERISHABLE_LINE = "Diagnose it COMPLETELY now"
SOP_CAPTURE_LINE = "root cause"


# =============================================================================
# Harness
# =============================================================================


def _env(hooks_root: Path) -> dict[str, str]:
    env = {**os.environ, "SPEC_KITTY_HOOKS_ROOT": str(hooks_root)}
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SCRIPTS_DIR), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_gate(payload: Any, *, hooks_root: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the dispatcher exactly as the hook harness does: JSON on stdin."""
    return subprocess.run(
        [sys.executable, str(GATE)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=_env(hooks_root),
    )


def failure_payload(session_id: str, command: str, **extra: Any) -> dict[str, Any]:
    """A ``PostToolUseFailure`` payload carrying exactly the fields WP01 measured.

    ⚠ ``error_type`` and ``is_timeout`` are **absent on purpose**. The shipped hook
    reference documents both; the implementation constructs neither, and neither appeared
    in any captured payload (WP01 spike §4, Claude Code 2.1.231). Adding them to a fixture
    here would let an implementation that reads them pass a test the harness can never
    reproduce.
    """
    payload: dict[str, Any] = {
        "session_id": session_id,
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(REPO_ROOT),
        "tool_use_id": f"toolu_{uuid.uuid4().hex[:12]}",
        "error": "Exit code 1\nError: Mission not found: 'nope'",
        "is_interrupt": False,
        "duration_ms": 2333,
    }
    payload.update(extra)
    return payload


#: The everyday shape of a Claude Code Bash call, and the shape WP03's premise got wrong.
#: The gated verb is on its **own line**: the line break IS the segment separator.
MULTILINE_COMMAND = 'echo "about to merge"\nspec-kitty merge --mission demo-mission\n'


def ledger_lines(hooks_root: Path, session_id: str) -> list[dict[str, Any]]:
    from hooks import fault_ledger

    path = fault_ledger.fault_path(session_id, root=hooks_root)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture()
def session_id() -> str:
    return f"cpduring-{uuid.uuid4().hex[:12]}"


# =============================================================================
# (a) A fault is recorded — driven through the real wire, multi-line command
# =============================================================================


def test_a_failing_spec_kitty_command_is_recorded_through_the_real_wire(
    tmp_path: Path, session_id: str
) -> None:
    """The load-bearing demonstration: the gated verb is on line two of the command."""
    result = run_gate(
        failure_payload(session_id, MULTILINE_COMMAND), hooks_root=tmp_path
    )

    lines = ledger_lines(tmp_path, session_id)
    assert len(lines) == 1, (lines, result.stdout, result.stderr)
    record = lines[0]
    assert record["kind"] == "fault"
    assert record["session_id"] == session_id
    assert record["interrupted"] is False
    assert record["exit_code"] == 1
    assert "spec-kitty merge" in record["command"]
    assert record["at"].endswith("Z") or "+00:00" in record["at"]


def test_a_record_still_lands_when_the_exit_prefix_cannot_be_parsed(
    tmp_path: Path, session_id: str
) -> None:
    """``Exit code N`` is a presentation string, not an API.

    Recording is never conditional on parsing it: if the prefix is reworded upstream the
    ledger must lose *detail*, never the record.
    """
    payload = failure_payload(
        session_id, MULTILINE_COMMAND, error="the tool blew up in some new way"
    )
    run_gate(payload, hooks_root=tmp_path)

    lines = ledger_lines(tmp_path, session_id)
    assert len(lines) == 1, lines
    assert lines[0]["exit_code"] is None


def test_two_faults_append_two_lines(tmp_path: Path, session_id: str) -> None:
    """Append-only, and nothing deduplicates: a retried command is two pieces of evidence."""
    for _ in range(2):
        run_gate(failure_payload(session_id, MULTILINE_COMMAND), hooks_root=tmp_path)

    assert len(ledger_lines(tmp_path, session_id)) == 2


def test_the_ledger_file_is_owner_only(tmp_path: Path, session_id: str) -> None:
    from hooks import fault_ledger

    run_gate(failure_payload(session_id, MULTILINE_COMMAND), hooks_root=tmp_path)
    path = fault_ledger.fault_path(session_id, root=tmp_path)
    assert path.stat().st_mode & 0o777 == 0o600


# =============================================================================
# (b) A cancellation is NOT recorded — paired with the positive, both layers
# =============================================================================


def test_an_operator_cancellation_is_not_recorded_and_the_pair_that_is(
    tmp_path: Path, session_id: str
) -> None:
    """PAIRED. Without the positive half, an implementation that records *nothing* passes.

    An operator pressing Ctrl-C is not a spec-kitty defect, and injecting the D-3 SOP at
    that moment is noise. ``is_interrupt`` is the filter's only input — ``is_timeout`` does
    not exist on this event, and a Bash-tool timeout never reaches this event at all.
    """
    cancelled = run_gate(
        failure_payload(session_id, MULTILINE_COMMAND, is_interrupt=True),
        hooks_root=tmp_path,
    )
    assert ledger_lines(tmp_path, session_id) == []
    assert cancelled.stdout.strip() == ""

    recorded = run_gate(failure_payload(session_id, MULTILINE_COMMAND), hooks_root=tmp_path)
    assert len(ledger_lines(tmp_path, session_id)) == 1
    assert "additionalContext" in recorded.stdout


def test_the_checkpoint_filters_the_interrupt_itself_not_only_the_dispatcher(
    tmp_path: Path, session_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dispatcher short-circuits interrupts, so a wire-only test proves nothing here.

    Both layers own the rule. This one drives ``during.evaluate`` directly, which is the
    only way the checkpoint's own filter can be shown to move under mutation.
    """
    monkeypatch.setenv("SPEC_KITTY_HOOKS_ROOT", str(tmp_path))
    from hooks import _hook_lib as lib
    from hooks.checkpoints import during

    segments = lib.split_segments(MULTILINE_COMMAND)

    cancelled = lib.parse_payload_mapping(
        failure_payload(session_id, MULTILINE_COMMAND, is_interrupt=True)
    )
    assert during.evaluate(cancelled, segments) is None
    assert ledger_lines(tmp_path, session_id) == []

    # PAIRED POSITIVE: the identical payload with the flag false does record and does emit.
    live = lib.parse_payload_mapping(failure_payload(session_id, MULTILINE_COMMAND))
    with pytest.raises(SystemExit):
        during.evaluate(live, segments)
    assert len(ledger_lines(tmp_path, session_id)) == 1


def test_a_failing_non_spec_kitty_command_is_not_recorded_and_the_pair_that_is(
    tmp_path: Path, session_id: str
) -> None:
    """PAIRED. Matched by tokenised argv, never by substring.

    ``matcher: "Bash"`` fires on every failing Bash call, so the checkpoint must decide for
    itself whether a ``spec-kitty`` command was invoked. ``echo "spec-kitty merge"`` names
    the verb inside a quoted argument and invokes nothing.
    """
    quoted = run_gate(
        failure_payload(session_id, 'echo "spec-kitty merge"'), hooks_root=tmp_path
    )
    assert ledger_lines(tmp_path, session_id) == []
    assert quoted.stdout.strip() == ""

    run_gate(failure_payload(session_id, MULTILINE_COMMAND), hooks_root=tmp_path)
    assert len(ledger_lines(tmp_path, session_id)) == 1


# =============================================================================
# (c) C-004 — the checkpoint must never claim an authority the event does not have
# =============================================================================


def test_during_checkpoint_never_emits_permission_decision(
    tmp_path: Path, session_id: str
) -> None:
    """``permissionDecision`` is ``PreToolUse``-only.

    A checkpoint that *appears* to deny where it structurally cannot is the overstatement
    C-004 forbids: an inert payload that reads to a later maintainer as enforcement.
    """
    result = run_gate(failure_payload(session_id, MULTILINE_COMMAND), hooks_root=tmp_path)

    assert "permissionDecision" not in result.stdout
    assert "permissionDecision" not in result.stderr
    body = json.loads(result.stdout.strip())["hookSpecificOutput"]
    assert set(body) == {"hookEventName", "additionalContext"}
    assert body["hookEventName"] == "PostToolUseFailure"


def test_the_sop_is_emitted_on_the_single_measured_channel(
    tmp_path: Path, session_id: str
) -> None:
    """One channel: ``additionalContext`` on stdout, exit 0. Nothing on stderr.

    WP01 measured both this and a stderr copy with ``exit 2`` reaching the model's context.
    The second channel was **removed by operator decision** — it prefixes the hook's own
    absolute command line onto the model-visible text twice, and a ``blocking``-shaped signal
    on an event with no deny authority invites the misreading C-004 exists to prevent. One
    measured channel is the known-sufficient thing; a second is defence-in-depth against a
    harness change nobody has observed.

    This test pins the removal, so a later reader cannot restore the second channel believing
    it was merely forgotten.
    """
    result = run_gate(failure_payload(session_id, MULTILINE_COMMAND), hooks_root=tmp_path)

    assert result.returncode == 0, "this event cannot block; a non-zero exit misrepresents that"
    stdout_text = json.loads(result.stdout.strip())["hookSpecificOutput"]["additionalContext"]
    assert SOP_PERISHABLE_LINE in stdout_text
    assert SOP_CAPTURE_LINE in stdout_text
    assert result.stderr == "", f"the stderr channel was removed; got: {result.stderr!r}"
    # ONE physical line of JSON: a stray line makes the payload unparseable.
    assert len(result.stdout.strip().splitlines()) == 1


def test_the_sop_says_the_fault_was_not_recorded_when_the_write_failed(
    tmp_path: Path, session_id: str
) -> None:
    """Bookkeeping must not break the tool call — and must not lie about having recorded.

    A dropped fault record is a missed obligation, the one loss direction this model cannot
    tolerate. So a write failure is told to the agent rather than swallowed.
    """
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")

    result = run_gate(failure_payload(session_id, MULTILINE_COMMAND), hooks_root=blocked)

    text = json.loads(result.stdout.strip())["hookSpecificOutput"]["additionalContext"]
    assert "NOT recorded" in text


# =============================================================================
# (d) NFR-004 — redaction, scanned as BYTES
# =============================================================================


def test_no_credential_shaped_literal_reaches_the_ledger_or_the_sop(
    tmp_path: Path, session_id: str
) -> None:
    """Scan the raw bytes, not the parsed object. A secret hides in the field the
    assertion forgot to check."""
    command = (
        f'GH_TOKEN={FAKE_TOKEN} spec-kitty merge --mission demo \\\n'
        f'  --body "{FAKE_PASSWORD}" --token {FAKE_TOKEN} --api-key {SHORT_SECRET}\n'
    )
    result = run_gate(failure_payload(session_id, command), hooks_root=tmp_path)

    from hooks import fault_ledger

    raw = fault_ledger.fault_path(session_id, root=tmp_path).read_bytes()
    assert len(ledger_lines(tmp_path, session_id)) == 1, raw
    for probe in (FAKE_TOKEN, FAKE_PASSWORD, "hunter2", "GH_TOKEN", SHORT_SECRET):
        assert probe.encode() not in raw, probe
        assert probe not in result.stdout, probe
        assert probe not in result.stderr, probe

    # PAIRED POSITIVE: the allowlist must still let a mission handle through, or "redacted
    # everything" would pass every assertion above while making the ledger useless.
    assert "--mission demo" in ledger_lines(tmp_path, session_id)[0]["command"]


def test_the_record_carries_no_absolute_path_from_the_payload(
    tmp_path: Path, session_id: str
) -> None:
    """``cwd`` and ``transcript_path`` are absolute filesystem paths on every payload."""
    payload = failure_payload(session_id, MULTILINE_COMMAND)
    payload["transcript_path"] = "/Users/someone/.claude/projects/x/session.jsonl"
    run_gate(payload, hooks_root=tmp_path)

    from hooks import fault_ledger

    raw = fault_ledger.fault_path(session_id, root=tmp_path).read_bytes()
    assert b"/Users/someone" not in raw
    assert str(REPO_ROOT).encode() not in raw


def test_every_record_fits_in_one_atomic_append(tmp_path: Path, session_id: str) -> None:
    """≤ 4096 bytes is what makes concurrent ``O_APPEND`` writes interleave without splitting.

    ⚠ The input has to be *far* past the cap, not merely long. At 400 repetitions the
    untruncated record is ~3.8 KB — under 4096 by luck — so the test passed with truncation
    removed. A boundary test whose input lands inside the boundary tests nothing.
    """
    command = "spec-kitty merge " + "--flag x " * 4000
    assert len(command) > 4096 * 8
    run_gate(failure_payload(session_id, command), hooks_root=tmp_path)

    from hooks import fault_ledger

    raw = fault_ledger.fault_path(session_id, root=tmp_path).read_bytes()
    assert 0 < len(raw) <= 4096, len(raw)


# =============================================================================
# The seam WP06 reads
# =============================================================================


def test_read_records_returns_what_record_fault_appended(
    tmp_path: Path, session_id: str
) -> None:
    """WP06's merge check reads this ledger; the reader ships beside the writer so the
    path logic exists in exactly one place."""
    from hooks import fault_ledger

    assert fault_ledger.read_records(session_id, root=tmp_path) == []
    run_gate(failure_payload(session_id, MULTILINE_COMMAND), hooks_root=tmp_path)
    records = fault_ledger.read_records(session_id, root=tmp_path)
    assert [r["kind"] for r in records] == ["fault"]


def test_a_session_id_cannot_escape_the_ledger_directory(tmp_path: Path) -> None:
    """A traversal guard, not cosmetics: ``session_id`` arrives from outside the process."""
    from hooks import fault_ledger

    path = fault_ledger.fault_path("../../etc/passwd", root=tmp_path)
    assert path.parent == tmp_path / "faults"
    assert ".." not in path.name


def test_an_unparseable_ledger_line_is_kept_not_skipped(tmp_path: Path, session_id: str) -> None:
    """A record this version cannot interpret may be the one that matters.

    Silently skipping it would turn a corrupt ledger into a clean one, and WP06 would then
    allow a merge on the strength of a file it could not read.
    """
    from hooks import fault_ledger

    run_gate(failure_payload(session_id, MULTILINE_COMMAND), hooks_root=tmp_path)
    path = fault_ledger.fault_path(session_id, root=tmp_path)
    with path.open("a") as handle:
        handle.write("{ this is not json\n")

    kinds = [r["kind"] for r in fault_ledger.read_records(session_id, root=tmp_path)]
    assert kinds == ["fault", "unreadable"]


# =============================================================================
# Review cycle 1, findings 1 and 3. Both closed here.
#
# Finding 1 is the one that matters: EVERY test in this module until now supplied
# SPEC_KITTY_HOOKS_ROOT, so the production root-resolution path had no coverage
# at all. A `HooksRootError` is a `HookError`, not an `OSError`, so it escaped
# `append_record`'s handler, escaped `record_fault`, and was absorbed by the
# dispatcher into a silent allow — no ledger line, no SOP, no warning.
#
# The test seam hid the single failure mode this module says it cannot tolerate.
# =============================================================================


def test_an_unresolvable_hooks_root_does_not_silently_drop_the_fault(
    tmp_path: Path, session_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no env seam and a cwd outside any worktree, the agent must still be told.

    Reachable in ordinary use: a failing `spec-kitty` call whose cwd is a scratchpad or
    `$HOME`, or a machine where `git rev-parse` is missing or slow enough to time out.
    """
    outside = tmp_path / "not-a-git-repo"
    outside.mkdir()

    payload = failure_payload(session_id, "spec-kitty merge --mission x")
    payload["cwd"] = str(outside)

    # ⚠ CORRECTED after review measured it. An earlier version of this comment claimed the
    # inherited subprocess cwd was a second escape hatch that also had to be shut. It is not:
    # `hooks_root` runs `git rev-parse` with `cwd=payload.cwd`, so the PAYLOAD's cwd alone
    # decides. Measured three ways — drop `cwd=` with the fix intact and this passes; drop it
    # with the fix reverted and it still reddens.
    #
    # The load-bearing hatch is the ENV SEAM. `run_gate` sets `SPEC_KITTY_HOOKS_ROOT`, which
    # is why the first attempt failed with the fix already correct. Opening it makes this test
    # unable to fail — a correct check that can never pass.
    #
    # `cwd=` is kept because it would matter for a payload carrying no `cwd` at all. The
    # original comment was a confident explanation that measurement disproved, and it would
    # have taught the next reader to harden the wrong seam.
    env = {k: v for k, v in os.environ.items() if k != "SPEC_KITTY_HOOKS_ROOT"}
    env["PYTHONPATH"] = str(SCRIPTS_DIR)
    result = subprocess.run(
        [sys.executable, str(GATE)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(outside),
    )

    assert result.returncode == 0, "this event cannot block, whatever else goes wrong"
    assert result.stdout.strip(), (
        "a fault that could not be recorded must still reach the agent — silence here is "
        "the dropped obligation the module docstring says it cannot tolerate"
    )
    text = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "NOT recorded" in text, f"the agent must be told the record did not land: {text!r}"


def test_a_shape_unsafe_value_of_an_allowlisted_flag_is_still_redacted(
    tmp_path: Path, session_id: str
) -> None:
    """The credential guard is a conjunction, and only one half was pinned.

    `_value_of` keeps a token when the flag is allowlisted AND the value matches the safe
    shape. Its docstring says "both conditions, because either alone leaks" — but dropping
    the shape half passed the entire suite, because every probe used a flag that was not on
    the allowlist. A credential passed as `--mission` reached the ledger.

    This is the sibling of the leak the author found. That one was the allowlist half being
    inert; this is the shape half being untested. Same conjunction, other side.
    """
    fake_token = "ghp_notarealtokennotarealtokennotare"
    payload = failure_payload(session_id, f"spec-kitty merge --mission {fake_token}")

    run_gate(payload, hooks_root=tmp_path)

    recorded = (tmp_path / "faults" / f"{session_id}.jsonl").read_text()
    assert fake_token not in recorded, (
        f"an allowlisted flag does not license an unsafe value; ledger held: {recorded!r}"
    )
    assert "<redacted>" in recorded


# =============================================================================
# Review cycle 2, finding 4. F4, F5 and F6 all shipped unpinned — reverting any
# of them left the suite green. Cycle 1 rejected F3 for exactly that shape, so
# leaving these unpinned would be the same defect with a different number.
# =============================================================================


def test_a_valueless_flag_does_not_license_the_next_positional(
    tmp_path: Path, session_id: str
) -> None:
    """F6. ``--json`` takes no value, so allowlisting it kept whatever followed.

    Narrow, but real: `spec-kitty merge --json s3cr3t` recorded `s3cr3t`. A
    value-allowlist entry for a valueless flag also misleads the next reader about
    which tokens survive.
    """
    payload = failure_payload(session_id, "spec-kitty merge --json s3cr3t")

    run_gate(payload, hooks_root=tmp_path)

    recorded = (tmp_path / "faults" / f"{session_id}.jsonl").read_text()
    assert "s3cr3t" not in recorded, (
        f"a valueless flag must not license the following positional; ledger held {recorded!r}"
    )


def test_the_sop_does_not_name_a_reconcile_command_that_does_not_exist(
    tmp_path: Path, session_id: str
) -> None:
    """The SOP must not send the agent to a surface that cannot work.

    This test previously asserted the OPPOSITE — that the SOP named `--fault` and
    `--issue` — because the reconcile subcommand was WP06's and WP06 was expected to
    land. WP06 was cut. The subcommand it would have routed to now always answers
    "not available", so naming it would send an agent to a dead surface: the exact
    livelock shape this mission hit three times before shipping a fourth in its own
    wiring.

    Inverted rather than deleted, so the reason survives with the assertion.
    """
    result = run_gate(failure_payload(session_id, "spec-kitty merge --mission x"),
                      hooks_root=tmp_path)
    text = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    assert "fault reconcile" not in text, (
        f"the SOP names a reconcile command that does not exist in this build: {text!r}"
    )
    assert "Nothing gates on that record" in text, (
        "the SOP must say plainly that nothing enforces the obligation, rather than "
        f"quietly omitting it: {text!r}"
    )
    assert "merge is gated" not in text, (
        f"the merge checkpoint was cut; claiming it gates is an enforcement that does not exist: {text!r}"
    )


def test_the_sop_never_claims_a_record_that_did_not_land(
    tmp_path: Path, session_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F4. The prefix said NOT recorded while the body said the fault was recorded.

    Both strings reached the agent in one message, ten lines apart. The body must be
    true on both branches, and must name the FAULT ledger — `session ledger` is a
    different, defined artifact in this codebase, and a cycle-2 fix briefly said that.
    """
    outside = tmp_path / "not-a-git-repo"
    outside.mkdir()
    payload = failure_payload(session_id, "spec-kitty merge --mission x")
    payload["cwd"] = str(outside)

    env = {k: v for k, v in os.environ.items() if k != "SPEC_KITTY_HOOKS_ROOT"}
    env["PYTHONPATH"] = str(SCRIPTS_DIR)
    result = subprocess.run(
        [sys.executable, str(GATE)], input=json.dumps(payload),
        capture_output=True, text=True, env=env, cwd=str(outside),
    )
    text = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    assert "NOT recorded" in text
    assert "session ledger" not in text, (
        "the SOP must name the FAULT ledger; `session ledger` is a different artifact "
        f"and saying so contradicts the NOT-recorded prefix in the same message: {text!r}"
    )
