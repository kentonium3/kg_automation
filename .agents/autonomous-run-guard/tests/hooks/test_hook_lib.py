r"""Tests for ``scripts/hooks/_hook_lib.py`` and ``scripts/hooks/mission_lifecycle_gate.py``.

WHY THIS MODULE IS SHAPED THE WAY IT IS
---------------------------------------
The library under test is **fail-closed**: every failure path denies. That makes a
naive fail-closed suite worthless, because *everything* denies against an empty
implementation — a module whose entire body is ``deny("no")`` would pass a suite made
only of deny assertions (``contracts/denial-payload.md`` §5).

So every deny group here is **paired with a positive that must still allow**, and the
pairs are shown to move independently under mutation. The paired positives are marked
``PAIRED POSITIVE`` in their docstrings; removing one does not weaken a deny test, it
removes the only evidence that the deny tests distinguish anything.

TWO INVOCATION STYLES, BOTH DELIBERATE
--------------------------------------
* **Subprocess** for anything whose deliverable is the *wire contract* — single-line
  JSON on stdout, exit 0, nothing else on stdout. Only a subprocess measures stdout and
  the exit code the way the hook harness does, and every response builder calls
  ``sys.exit()``. This follows the discipline WP02 established in
  ``test_upstream_filing_guard.py``.
* **Direct calls** for the pure functions (``split_segments``, ``argv_matches``,
  ``missing_markers``, ``parse_payload``), where a subprocess would only obscure which
  assertion failed.

  ⚠ Both styles appear for F1 and F2 on purpose. A direct call proves what
  ``split_segments`` returns; only the subprocess proves what the *gate* decides about a
  command shaped the way a Claude Code Bash call really is. F1 and F2 were both invisible
  to 52 mutations of the separator set because the implementation and its tests shared one
  false premise — that ``shlex`` hands back a newline token. Driving the real wire is what
  tests the premise instead of the set.

ISOLATION
---------
The hooks root is resolved through an explicit env seam, ``SPEC_KITTY_HOOKS_ROOT``, not
a monkeypatched private. ``test_the_ledger_lands_under_the_env_override`` proves the
seam takes effect **before** any other result in this module is believed: without it an
allow here could be an allow inherited from a ledger in the real
``<git-common-dir>/spec-kitty-hooks/``. Every test uses a unique ``session_id`` as a
second line of defence, and nothing here touches the network, invokes ``spec-kitty``, or
writes outside ``tmp_path``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import pytest

from hooks import _hook_lib as lib

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
GATE = SCRIPTS_DIR / "hooks" / "mission_lifecycle_gate.py"
HOOKS_DIR = SCRIPTS_DIR / "hooks"

# --- literals asserted against the RENDERED output, never imported from the module ----
# A test that finds the module's own constant in the module's own output has checked
# nothing. These are typed out again on purpose.
ANTI_PATTERN_LINE = "never by adding a token command"
CLOSING_LIMIT_LINE = "it cannot prove the judgment was sound"
RUNNABLE_LINE_RE = re.compile(r"^\s*(gh|spec-kitty|python|\.venv/bin)\b", re.MULTILINE)

# Credential-shaped literals. Deliberately fake, and deliberately *shaped* like the real
# thing: NFR-004 is about the field an assertion forgot, so the probe has to look like
# something a redactor would be tempted to let through.
FAKE_TOKEN = "ghp_notarealtokennotarealtokennotareal"
FAKE_PASSWORD = "password=hunter2"

FOOTER = "**Authored by**: Kent Gale & Claude, 2026-08-25"

ALL_MARKERS = ("sweep.authored", "sweep.recent_closed", "sweep.register_refs", "register.read")


# =============================================================================
# Harness
# =============================================================================


def _env(hooks_root: Path, **extra: str) -> dict[str, str]:
    env = {**os.environ, "SPEC_KITTY_HOOKS_ROOT": str(hooks_root)}
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SCRIPTS_DIR), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
    )
    env.update(extra)
    return env


def run_gate(
    payload: Any,
    *,
    hooks_root: Path,
    argv: tuple[str, ...] = (),
    raw_stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the dispatcher exactly as the hook harness does: JSON on stdin."""
    stdin = raw_stdin if raw_stdin is not None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(GATE), *argv],
        input=stdin,
        capture_output=True,
        text=True,
        env=_env(hooks_root),
    )


def run_lib(code: str, *, hooks_root: Path) -> subprocess.CompletedProcess[str]:
    """Drive a library entry point in a real process, so stdout and the exit code are real.

    Used where the behaviour under test is a library response builder rather than a
    dispatcher route: the checkpoint modules that would reach these paths in production
    are WP04/WP05/WP06's files, which do not exist yet, and inventing a stand-in script
    here would test the stand-in.
    """
    return subprocess.run(
        [sys.executable, "-c", "from hooks import _hook_lib as lib\n" + code],
        capture_output=True,
        text=True,
        env=_env(hooks_root),
    )


def pre_payload(session_id: str, command: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "session_id": session_id,
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(REPO_ROOT),
        "tool_use_id": "toolu_test",
    }
    payload.update(extra)
    return payload


def post_payload(session_id: str, command: str, **extra: Any) -> dict[str, Any]:
    payload = pre_payload(session_id, command, **extra)
    payload["hook_event_name"] = "PostToolUse"
    payload["tool_response"] = {"stdout": "", "stderr": "", "interrupted": False}
    return payload


def post_read_payload(session_id: str, file_path: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "hook_event_name": "PostToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": file_path},
        "cwd": str(REPO_ROOT),
    }


def failure_payload(session_id: str, command: str, **extra: Any) -> dict[str, Any]:
    payload = pre_payload(session_id, command, **extra)
    payload["hook_event_name"] = "PostToolUseFailure"
    payload["error"] = "Exit code 1\nsomething broke"
    payload["error_type"] = "NonZeroExit"
    return payload


def assert_allow(result: subprocess.CompletedProcess[str]) -> None:
    """Allow is *silence*: exit 0 with nothing on stdout.

    Asserting emptiness and not merely the exit code matters — every path exits 0, so an
    exit-code-only assertion cannot tell an allow from a deny.
    """
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", f"expected an allow (empty stdout), got: {result.stdout!r}"


def assert_deny(result: subprocess.CompletedProcess[str]) -> str:
    """Assert the full wire contract of a denial and return the reason for content checks."""
    assert result.returncode == 0, f"exit {result.returncode}; stderr={result.stderr}"
    assert result.stdout, "expected a denial payload on stdout, got nothing"
    assert result.stdout.endswith("\n"), "the payload must be newline-terminated"
    newlines = result.stdout.count("\n")
    assert newlines == 1, (
        f"the payload must be ONE physical line; got {newlines} newlines: {result.stdout!r}"
    )
    payload = json.loads(result.stdout)  # consumes the WHOLE of stdout, by construction
    specific = payload["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "deny"
    reason = specific["permissionDecisionReason"]
    assert isinstance(reason, str) and reason
    return reason


def assert_context(result: subprocess.CompletedProcess[str], *, event: str) -> str:
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") == 1, result.stdout
    payload = json.loads(result.stdout)
    specific = payload["hookSpecificOutput"]
    assert specific["hookEventName"] == event
    assert "permissionDecision" not in specific, (
        "permissionDecision must never appear on a non-PreToolUse event: a checkpoint "
        "that appears to deny where it structurally cannot is C-004's overstatement"
    )
    return specific["additionalContext"]


def run_gate_with_absent_checkpoint(
    payload: dict[str, Any], *, hooks_root: Path
) -> subprocess.CompletedProcess[str]:
    """Drive the dispatcher with a checkpoint name that can never resolve.

    The fail-closed default must be asserted WITHOUT depending on WP04/WP05/WP06 not
    having landed yet. Relying on the real modules being absent would make these tests
    break the day those work packages add them — forcing another WP to edit a file it does
    not own, which is the ownership collision this mission is documenting.
    """
    code = (
        "import sys\n"
        "from hooks import mission_lifecycle_gate as gate\n"
        "gate.PRE_TOOL_CHECKPOINTS = ('definitely_absent_checkpoint',)\n"
        f"sys.stdin = __import__('io').StringIO({json.dumps(json.dumps(payload))})\n"
        "gate.main([])\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=_env(hooks_root)
    )


def write_ledger(hooks_root: Path, session_id: str, body: Any) -> Path:
    path = hooks_root / "sessions" / f"{session_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return path


def full_ledger(session_id: str, markers: tuple[str, ...] = ALL_MARKERS) -> dict[str, Any]:
    return {
        "schema": "spec-kitty-qa/session-ledger@1",
        "session_id": session_id,
        "created_at": "2026-08-25T06:11:04Z",
        "updated_at": "2026-08-25T06:19:22Z",
        "markers": {
            name: {"first_seen_at": "2026-08-25T06:11:04Z", "count": 1, "source_tool": "Bash"}
            for name in markers
        },
    }


EVAL_LEDGER = "import sys\nlib.evaluate_session_ledger(sys.argv[1] if len(sys.argv) > 1 else {sid!r})\n"


def eval_ledger(session_id: str, *, hooks_root: Path) -> subprocess.CompletedProcess[str]:
    """Run the shared ledger evaluator — the seam WP04's CP-BEFORE calls — for real."""
    return run_lib(f"lib.evaluate_session_ledger({session_id!r})\n", hooks_root=hooks_root)


# =============================================================================
# Harness verification — prove the isolation before believing any other result.
# =============================================================================


def test_the_ledger_lands_under_the_env_override(tmp_path: Path) -> None:
    """The isolation seam takes effect, so no result in this module is inherited.

    This is the single most likely source of a false green here: if the override did not
    take effect, the gate would read the developer's real
    ``<git-common-dir>/spec-kitty-hooks/`` ledger and an allow could be someone else's
    evidence.
    """
    session_id = "iso-probe-1"
    lib.mark(session_id, "register.read", "Read", root=tmp_path)

    landed = tmp_path / "sessions" / f"{session_id}.json"
    assert landed.exists(), f"no ledger under tmp_path; found: {list(tmp_path.rglob('*'))}"

    real_root = lib.hooks_root()
    assert real_root.resolve() != tmp_path.resolve(), "tmp_path IS the real root; no isolation"
    assert not (real_root / "sessions" / f"{session_id}.json").exists()


def test_the_env_override_reaches_a_subprocess(tmp_path: Path) -> None:
    """The subprocess harness honours the same seam the direct calls do."""
    session_id = "iso-probe-2"
    result = run_lib(
        f"lib.mark({session_id!r}, 'register.read', 'Read')\n", hooks_root=tmp_path
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "sessions" / f"{session_id}.json").exists()


def test_two_sessions_do_not_share_evidence(tmp_path: Path) -> None:
    """Markers under session A must not satisfy a gate under session B (FR-002).

    A fresh session starting empty is the design, not a bug: a sweep performed in another
    session tells this one nothing about what closed upstream since.
    """
    for marker in ALL_MARKERS:
        lib.mark("session-A", marker, "Bash", root=tmp_path)

    assert_allow(eval_ledger("session-A", hooks_root=tmp_path))
    reason = assert_deny(eval_ledger("session-B", hooks_root=tmp_path))
    assert "sweep.authored" in reason


# =============================================================================
# T011 — payload parsing DENIES on malformed input (qa #277's class, at the source)
# =============================================================================


def test_a_wellformed_payload_parses(tmp_path: Path) -> None:
    """PAIRED POSITIVE for the whole payload group: a real payload is not rejected."""
    parsed = lib.parse_payload_mapping(pre_payload("s", "spec-kitty status"))
    assert parsed.session_id == "s"
    assert parsed.hook_event_name == "PreToolUse"
    assert parsed.tool_name == "Bash"
    assert parsed.tool_input["command"] == "spec-kitty status"
    assert parsed.cwd == str(REPO_ROOT)
    assert parsed.tool_use_id == "toolu_test"
    # Absent on PreToolUse, and requiring them would deny every legitimate call.
    assert parsed.error is None and parsed.error_type is None
    assert parsed.is_interrupt is False and parsed.is_timeout is False


def test_a_failure_payload_parses_its_error_fields(tmp_path: Path) -> None:
    """PAIRED POSITIVE: PostToolUseFailure carries a different field set, and both parse."""
    parsed = lib.parse_payload_mapping(failure_payload("s", "spec-kitty merge"))
    assert parsed.hook_event_name == "PostToolUseFailure"
    assert parsed.error is not None and parsed.error.startswith("Exit code 1")
    assert parsed.error_type == "NonZeroExit"


def test_malformed_payload_denies(tmp_path: Path) -> None:
    """Unparseable JSON must DENY — the deliberate divergence from the proven pattern.

    ``upstream_filing_guard.py`` does ``except Exception: allow()`` here (qa #277). A
    guard that fails open manufactures a green nobody earned, so this inverts it.
    """
    reason = assert_deny(run_gate(None, hooks_root=tmp_path, raw_stdin="{not json"))
    assert "JSON" in reason


def test_empty_stdin_denies(tmp_path: Path) -> None:
    assert_deny(run_gate(None, hooks_root=tmp_path, raw_stdin=""))


@pytest.mark.parametrize("body", ["42", '"a string"', "[]", "null", "true"])
def test_non_object_payload_denies(tmp_path: Path, body: str) -> None:
    reason = assert_deny(run_gate(None, hooks_root=tmp_path, raw_stdin=body))
    assert "object" in reason


def test_missing_session_id_denies(tmp_path: Path) -> None:
    """An unidentifiable session has no evidence, and ``unknown.json`` is a shared bucket."""
    payload = pre_payload("s", "spec-kitty status")
    del payload["session_id"]
    reason = assert_deny(run_gate(payload, hooks_root=tmp_path))
    assert "session_id" in reason


@pytest.mark.parametrize("value", ["", "   ", None, 7, [], {}])
def test_empty_or_non_string_session_id_denies(tmp_path: Path, value: Any) -> None:
    payload = pre_payload("s", "spec-kitty status")
    payload["session_id"] = value
    assert_deny(run_gate(payload, hooks_root=tmp_path))


def test_missing_tool_input_denies(tmp_path: Path) -> None:
    payload = pre_payload("s", "spec-kitty status")
    del payload["tool_input"]
    reason = assert_deny(run_gate(payload, hooks_root=tmp_path))
    assert "tool_input" in reason


@pytest.mark.parametrize("value", ["a string", 7, [], None])
def test_non_object_tool_input_denies(tmp_path: Path, value: Any) -> None:
    payload = pre_payload("s", "spec-kitty status")
    payload["tool_input"] = value
    reason = assert_deny(run_gate(payload, hooks_root=tmp_path))
    assert "tool_input" in reason


def test_absent_and_non_object_tool_input_denials_differ(tmp_path: Path) -> None:
    """Two branches, two messages — otherwise one of the two guards is never demonstrated.

    Found while designing the mutation pass: the ``"tool_input" not in raw`` branch is
    redundant for the *decision* (the type check denies the absent case too), so without
    this test it could be deleted with the suite staying green. What it actually buys is a
    truer message, and that is what is pinned here.
    """
    absent = pre_payload("ti-1", "spec-kitty status")
    del absent["tool_input"]
    wrong_type = pre_payload("ti-2", "spec-kitty status") | {"tool_input": "a string"}

    absent_reason = assert_deny(run_gate(absent, hooks_root=tmp_path))
    type_reason = assert_deny(run_gate(wrong_type, hooks_root=tmp_path))
    assert absent_reason != type_reason
    assert "carries no tool_input" in absent_reason
    assert "not a JSON object" in type_reason


def test_missing_hook_event_name_denies(tmp_path: Path) -> None:
    """The response shape depends on the event, so an unnamed event cannot be answered."""
    payload = pre_payload("s", "spec-kitty status")
    del payload["hook_event_name"]
    reason = assert_deny(run_gate(payload, hooks_root=tmp_path))
    assert "hook_event_name" in reason


def test_parse_payload_reads_a_stream(tmp_path: Path) -> None:
    """PAIRED POSITIVE for the public stream entry point WP07's guard will call."""
    import io

    parsed = lib.parse_payload(io.StringIO(json.dumps(pre_payload("stream-1", "ls"))))
    assert parsed.session_id == "stream-1"


@pytest.mark.parametrize("value", [None, "", "   ", 7])
def test_parse_payload_mapping_requires_a_hook_event_name(value: Any) -> None:
    """The library's own check, not the dispatcher's.

    Found by the mutation pass: removing this check left every wire test green, because
    the dispatcher checks the event name before it parses. The check still matters —
    ``upstream_filing_guard.py`` calls ``parse_payload`` directly in WP07 and has no such
    pre-check — so it is now demonstrated here rather than only implied.
    """
    payload = pre_payload("s", "ls")
    if value is None:
        del payload["hook_event_name"]
    else:
        payload["hook_event_name"] = value
    with pytest.raises(lib.PayloadError, match="hook_event_name"):
        lib.parse_payload_mapping(payload)


def test_unhandled_exception_denies(tmp_path: Path) -> None:
    """An exception nobody predicted must still deny, naming the CLASS and not the message.

    A message can quote payload content, and payload content can carry a credential
    (NFR-004). So the class is named and the message is dropped.
    """
    injected = f"RuntimeError with {FAKE_TOKEN} inside it"
    code = (
        "import json, sys\n"
        "from hooks import mission_lifecycle_gate as gate\n"
        f"def boom(*a, **k): raise RuntimeError({injected!r})\n"
        "gate.lib.split_segments = boom\n"
        f"sys.stdin = __import__('io').StringIO({json.dumps(json.dumps(pre_payload('s', 'spec-kitty merge')))})\n"
        "gate.main([])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
    )
    reason = assert_deny(result)
    assert "RuntimeError" in reason, "the denial must name the exception class"
    assert FAKE_TOKEN not in result.stdout, "the exception MESSAGE must not reach the denial"
    assert injected not in reason


@pytest.mark.parametrize("event", ["PostToolUse", "PostToolUseFailure"])
def test_an_unhandled_exception_on_a_post_event_emits_no_permission_decision(
    tmp_path: Path, event: str
) -> None:
    """F3 (C-004). The fail-closed handler must not claim authority the event lacks.

    ``deny()`` hard-codes ``hookEventName: "PreToolUse"``, so routing every unpredicted
    exception through it emitted a **PreToolUse denial for a PostToolUse payload**. That
    defeats ``deny()``'s own ``ValueError`` guard on exactly the path the guard was built
    for: a checkpoint calling ``deny(event="PostToolUseFailure")`` raises, the blanket
    handler catches it, and re-emits the overstatement the guard exists to prevent.

    A post event has no deny authority, so the honest answer is silence. The consequence
    is a missing marker or an unrecorded fault, both of which point toward a denial at a
    later checkpoint — the safe direction, and the one the routes already take for a
    malformed post payload.
    """
    payload = (post_payload if event == "PostToolUse" else failure_payload)("f3", "cd /tmp")
    code = (
        "import sys\n"
        "from hooks import mission_lifecycle_gate as gate\n"
        f"def boom(*a, **k): raise RuntimeError({FAKE_TOKEN!r})\n"
        "gate.lib.split_segments = boom\n"
        f"sys.stdin = __import__('io').StringIO({json.dumps(json.dumps(payload))})\n"
        "gate.main([])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=_env(tmp_path)
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", (
        "a post event carries no deny authority; an exception there must be silent, not a "
        f"PreToolUse denial: {result.stdout!r}"
    )


def test_a_payload_error_on_a_post_event_emits_no_permission_decision(tmp_path: Path) -> None:
    """The other half of F3: ``except lib.PayloadError`` denied on post events too."""
    code = (
        "import sys\n"
        "from hooks import mission_lifecycle_gate as gate\n"
        "def boom(*a, **k): raise gate.lib.PayloadError('unreadable')\n"
        "gate._dispatch = boom\n"
        f"sys.stdin = __import__('io').StringIO({json.dumps(json.dumps({'hook_event_name': 'PostToolUse'}))})\n"
        "gate.main([])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=_env(tmp_path)
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", result.stdout


def test_an_unreadable_payload_with_no_event_still_denies(tmp_path: Path) -> None:
    """PAIRED POSITIVE for F3: silence is conditional on KNOWING the event is not PreToolUse.

    When stdin will not parse at all there is no resolved event to thread, so nothing has
    been established about the call and the answer stays fail-closed (NFR-001). Without
    this, "exit 0 on anything that is not PreToolUse" would silently become "exit 0 on
    anything we could not read", which is qa #277 all over again.
    """
    assert_deny(run_gate(None, hooks_root=tmp_path, raw_stdin="{nope"))


# =============================================================================
# T012 — session ledger: read status, atomic write, closed vocabulary
# =============================================================================


def test_an_ok_ledger_with_all_four_markers_allows(tmp_path: Path) -> None:
    """PAIRED POSITIVE for the whole ledger group."""
    write_ledger(tmp_path, "led-ok", full_ledger("led-ok"))
    assert_allow(eval_ledger("led-ok", hooks_root=tmp_path))


def test_absent_ledger_denies(tmp_path: Path) -> None:
    """FRESH: deny for want of evidence, with the 'run the sweep' message."""
    reason = assert_deny(eval_ledger("led-fresh", hooks_root=tmp_path))
    for marker in ALL_MARKERS:
        assert marker in reason
    assert "corrupt" not in reason.lower()


def test_a_partial_ledger_names_only_the_missing_markers(tmp_path: Path) -> None:
    """FR-009: name the step. Listing what is already satisfied stops needless re-runs."""
    write_ledger(tmp_path, "led-part", full_ledger("led-part", ("sweep.authored", "register.read")))
    reason = assert_deny(eval_ledger("led-part", hooks_root=tmp_path))
    assert "sweep.recent_closed" in reason
    assert "sweep.register_refs" in reason
    assert "Already satisfied" in reason
    # the satisfied ones are reported as satisfied, not as missing
    missing_block = reason.split("Already satisfied")[0]
    assert "✗ sweep.authored" not in missing_block
    assert "✗ register.read" not in missing_block


def test_unreadable_ledger_denies_on_injected_oserror(tmp_path: Path) -> None:
    """UNREADABLE: an OSError is injected rather than provoked with ``chmod``.

    A chmod-based test can be platform-constant — root, or a filesystem that ignores the
    mode — and would then prove nothing while looking green. Injecting the error the
    branch claims to handle tests the branch.
    """
    write_ledger(tmp_path, "led-oserr", full_ledger("led-oserr"))
    code = (
        "import pathlib\n"
        "def boom(self, *a, **k): raise OSError(5, 'Input/output error')\n"
        "pathlib.Path.read_text = boom\n"
        "lib.evaluate_session_ledger('led-oserr')\n"
    )
    reason = assert_deny(run_lib(code, hooks_root=tmp_path))
    assert "OSError" in reason, "the denial must name the error class"
    assert "led-oserr.json" in reason, "the denial must name the path"
    assert "not a missing step" in reason


def test_unreadable_ledger_denies_when_the_path_is_a_directory(tmp_path: Path) -> None:
    """UNREADABLE, provoked without injection: a directory where the file should be.

    ``IsADirectoryError`` is a real ``OSError`` on every supported platform, so this is
    the non-injected companion to the test above.
    """
    (tmp_path / "sessions" / "led-isdir.json").mkdir(parents=True)
    reason = assert_deny(eval_ledger("led-isdir", hooks_root=tmp_path))
    assert "led-isdir.json" in reason
    assert "Error" in reason


def test_corrupt_json_denies(tmp_path: Path) -> None:
    write_ledger(tmp_path, "led-corrupt", "{ this is not json")
    reason = assert_deny(eval_ledger("led-corrupt", hooks_root=tmp_path))
    assert "corrupt" in reason.lower()
    assert "delete" in reason.lower(), "the remediation is to delete the file and re-run"


@pytest.mark.parametrize("body", ["[]", '"a string"', "42", "null"])
def test_non_object_ledger_denies(tmp_path: Path, body: str) -> None:
    write_ledger(tmp_path, "led-scalar", body)
    reason = assert_deny(eval_ledger("led-scalar", hooks_root=tmp_path))
    assert "corrupt" in reason.lower()


def test_unknown_schema_denies(tmp_path: Path) -> None:
    led = full_ledger("led-schema")
    led["schema"] = "spec-kitty-qa/session-ledger@99"
    write_ledger(tmp_path, "led-schema", led)
    reason = assert_deny(eval_ledger("led-schema", hooks_root=tmp_path))
    assert "corrupt" in reason.lower()


def test_absent_schema_denies(tmp_path: Path) -> None:
    led = full_ledger("led-noschema")
    del led["schema"]
    write_ledger(tmp_path, "led-noschema", led)
    assert_deny(eval_ledger("led-noschema", hooks_root=tmp_path))


@pytest.mark.parametrize("value", ["[]", '"x"', "7", "null"])
def test_markers_not_object_denies(tmp_path: Path, value: str) -> None:
    led = full_ledger("led-markers")
    led["markers"] = json.loads(value)
    write_ledger(tmp_path, "led-markers", led)
    reason = assert_deny(eval_ledger("led-markers", hooks_root=tmp_path))
    assert "corrupt" in reason.lower()


def test_fresh_and_corrupt_messages_differ(tmp_path: Path) -> None:
    """Two denials, two different remediations — collapsing them wastes a sweep.

    'You have not run the sweep' sends the agent to do the right thing. 'Your ledger is
    corrupt' sends it to delete a file. Emitting the first for the second wastes the
    sweep AND leaves the corrupt file in place to deny again.
    """
    fresh = assert_deny(eval_ledger("led-diff-fresh", hooks_root=tmp_path))
    write_ledger(tmp_path, "led-diff-corrupt", "{{{")
    corrupt = assert_deny(eval_ledger("led-diff-corrupt", hooks_root=tmp_path))
    assert fresh != corrupt
    assert "delete" in corrupt.lower() and "delete" not in fresh.lower()


def test_unreadable_and_corrupt_messages_differ(tmp_path: Path) -> None:
    write_ledger(tmp_path, "led-diff2", "{{{")
    corrupt = assert_deny(eval_ledger("led-diff2", hooks_root=tmp_path))
    (tmp_path / "sessions" / "led-diff3.json").mkdir(parents=True, exist_ok=True)
    unreadable = assert_deny(eval_ledger("led-diff3", hooks_root=tmp_path))
    assert corrupt != unreadable


@pytest.mark.parametrize(
    "marker",
    [
        {"count": 1, "source_tool": "Bash"},
        {"first_seen_at": "x", "source_tool": "Bash"},
        {"first_seen_at": "x", "count": 0, "source_tool": "Bash"},
        {"first_seen_at": "x", "count": "many", "source_tool": "Bash"},
        {"first_seen_at": "x", "count": 1},
        "not an object",
        None,
    ],
)
def test_malformed_marker_is_absent_not_fatal(tmp_path: Path, marker: Any) -> None:
    """A malformed marker can never satisfy a gate, and does not invalidate the ledger."""
    led = full_ledger("led-mm")
    led["markers"]["sweep.authored"] = marker
    write_ledger(tmp_path, "led-mm", led)
    reason = assert_deny(eval_ledger("led-mm", hooks_root=tmp_path))
    assert "sweep.authored" in reason
    assert "corrupt" not in reason.lower(), "one bad marker must not condemn the ledger"


def test_corrupt_ledger_is_not_overwritten(tmp_path: Path) -> None:
    """Overwriting a corrupt ledger erases the evidence and hands the next call a pass."""
    path = write_ledger(tmp_path, "led-nowrite", "{ corrupt")
    before = path.read_bytes()
    lib.mark("led-nowrite", "register.read", "Read", root=tmp_path)
    assert path.read_bytes() == before
    assert_deny(eval_ledger("led-nowrite", hooks_root=tmp_path))


def test_unreadable_ledger_is_not_overwritten(tmp_path: Path) -> None:
    directory = tmp_path / "sessions" / "led-nowrite2.json"
    directory.mkdir(parents=True)
    lib.mark("led-nowrite2", "register.read", "Read", root=tmp_path)
    assert directory.is_dir(), "the write path clobbered an unreadable ledger"


def test_read_creates_no_directory(tmp_path: Path) -> None:
    """A read must never create state — otherwise the gate manufactures its own evidence."""
    root = tmp_path / "nothing-here"
    state, status = lib.read_session_ledger("led-nodir", root=root)
    assert state == {}
    assert status is lib.LedgerStatus.FRESH
    assert not root.exists()


def test_session_id_traversal_stays_under_sessions(tmp_path: Path) -> None:
    """``session_id`` arrives from outside the process; sanitisation is a traversal guard."""
    path = lib.session_ledger_path("../../etc/passwd", root=tmp_path)
    sessions = (tmp_path / "sessions").resolve()
    assert path.parent.resolve() == sessions
    assert ".." not in path.parts
    assert path.name == "______etc_passwd.json"


def test_an_empty_session_id_never_reaches_the_ledger(tmp_path: Path) -> None:
    """The shared ``unknown.json`` bucket must never be created, let alone satisfy a gate."""
    payload = pre_payload("", "spec-kitty status")
    assert_deny(run_gate(payload, hooks_root=tmp_path))
    assert not (tmp_path / "sessions").exists()


def test_unknown_marker_id_is_ignored(tmp_path: Path) -> None:
    """The vocabulary is CLOSED, so a later writer cannot invent a key that unlocks a gate."""
    lib.mark("led-vocab", "sweep.authored", "Bash", root=tmp_path)
    lib.mark("led-vocab", "totally.made.up", "Bash", root=tmp_path)
    state, status = lib.read_session_ledger("led-vocab", root=tmp_path)
    assert status is lib.LedgerStatus.OK
    assert set(state["markers"]) == {"sweep.authored"}


def test_marking_twice_increments_and_keeps_first_seen(tmp_path: Path) -> None:
    """PAIRED POSITIVE: the write path really does write, and preserves first_seen_at."""
    lib.mark("led-twice", "register.read", "Read", root=tmp_path)
    first = lib.read_session_ledger("led-twice", root=tmp_path)[0]["markers"]["register.read"]
    lib.mark("led-twice", "register.read", "Bash", root=tmp_path)
    second = lib.read_session_ledger("led-twice", root=tmp_path)[0]["markers"]["register.read"]
    assert second["count"] == 2
    assert second["first_seen_at"] == first["first_seen_at"]


def test_the_write_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    lib.mark("led-atomic", "register.read", "Read", root=tmp_path)
    leftovers = list((tmp_path / "sessions").glob("*.tmp"))
    assert leftovers == [], f"a temp file survived the replace: {leftovers}"


def test_concurrent_writers_never_fabricate_a_marker(tmp_path: Path) -> None:
    """N=20 concurrent writers: loss is permitted by the contract, fabrication is not.

    Marker *loss* points toward deny (the step must be re-run). A lock file would add a
    stale-lock mode pointing toward hang-or-allow, which is why there is no lock.
    """
    import threading

    written = ["register.read", "sweep.authored", "sweep.recent_closed", "sweep.register_refs"]
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            lib.mark("led-conc", written[index % len(written)], "Bash", root=tmp_path)
            state, status = lib.read_session_ledger("led-conc", root=tmp_path)
            assert status in (lib.LedgerStatus.OK, lib.LedgerStatus.FRESH), status
            assert set(state.get("markers", {})) <= set(written)
        except BaseException as exc:  # noqa: BLE001 - re-raised in the main thread
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    state, status = lib.read_session_ledger("led-conc", root=tmp_path)
    assert status is lib.LedgerStatus.OK, "the file must parse after every write"
    assert set(state["markers"]) <= set(written), "a marker was fabricated"


def test_ledger_bytes_contain_no_credential(tmp_path: Path) -> None:
    """NFR-004 asserted on the BYTES: a secret hides in the field the assertion forgot.

    ⚠ The repository is named with ``--repo``, and it has to be. This case used to pass
    the reference as a bare positional, which the old *substring over every token*
    matcher accepted — ``gh issue list`` has no positional repository argument, so that
    was a false positive the classifier happened to survive on. Under the target-value
    extractor an unflagged token names no target, no marker is recorded, and the
    ``ledger.exists()`` guard below fires. That guard is doing its job: without a repo
    flag this test would assert NFR-004 against a file that was never written.
    """
    session_id = f"led-secret-{FAKE_TOKEN[:8]}"
    command = (
        f"GH_TOKEN={FAKE_TOKEN} gh issue list --author kent --state all "
        "--repo Priivacy-ai/spec-kitty"
    )
    assert_allow(run_gate(post_payload(session_id, command), hooks_root=tmp_path))

    ledger = tmp_path / "sessions" / f"{session_id}.json"
    assert ledger.exists(), "the marker was not recorded, so this test proved nothing"
    raw = ledger.read_bytes()
    assert FAKE_TOKEN.encode() not in raw
    assert b"GH_TOKEN" not in raw
    assert b"gh issue list" not in raw


def test_old_session_files_are_pruned_and_recent_ones_are_not(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True)
    stale = sessions / "ancient.json"
    fresh = sessions / "recent.json"
    stale.write_text("{}", encoding="utf-8")
    fresh.write_text("{}", encoding="utf-8")
    old = time.time() - 20 * 86400
    os.utime(stale, (old, old))

    faults = tmp_path / "faults"
    faults.mkdir()
    fault_file = faults / "mission.jsonl"
    fault_file.write_text("{}", encoding="utf-8")
    os.utime(fault_file, (old, old))

    lib.mark("led-prune", "register.read", "Read", root=tmp_path)

    assert not stale.exists(), "a file outside the retention window survived"
    assert fresh.exists(), "a file INSIDE the retention window was pruned"
    assert fault_file.exists(), "pruning must never touch faults/"


def test_hooks_root_resolves_under_the_git_common_dir() -> None:
    """The root is the git common dir, NOT $TMPDIR — that is what makes a lane's evidence
    visible from the primary checkout."""
    root = lib.hooks_root()
    assert root.name == "spec-kitty-hooks"
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    expected = (REPO_ROOT / common).resolve() if not Path(common).is_absolute() else Path(common).resolve()
    assert root.parent.resolve() == expected
    assert "spec-kitty-filing-guard" not in str(root), "the two guards must not share a ledger"


def test_an_unresolvable_hooks_root_denies(tmp_path: Path) -> None:
    """A gate that cannot locate its own ledger has established nothing."""
    code = (
        "def boom(*a, **k): raise lib.HooksRootError('git rev-parse --git-common-dir failed')\n"
        "lib.hooks_root = boom\n"
        "lib.evaluate_session_ledger('led-noroot')\n"
    )
    env = _env(tmp_path)
    env.pop("SPEC_KITTY_HOOKS_ROOT")
    result = subprocess.run(
        [sys.executable, "-c", "from hooks import _hook_lib as lib\n" + code],
        capture_output=True,
        text=True,
        env=env,
    )
    reason = assert_deny(result)
    assert "ledger" in reason.lower()


# =============================================================================
# T013 — argv parsing via shlex (FR-010a): a MENTION is not an INVOCATION
# =============================================================================


def segments(command: str) -> list[list[str]]:
    return lib.split_segments(command)


MERGE = ("spec-kitty", "merge")
AGENT_MERGE = ("spec-kitty", "agent", "mission", "merge")
AGENT_CREATE = ("spec-kitty", "agent", "mission", "create")
MISSION_CREATE = ("spec-kitty", "mission", "create")


def matches_any(command: str, verb: tuple[str, ...]) -> bool:
    return any(lib.argv_matches(argv, verb) for argv in segments(command))


@pytest.mark.parametrize(
    ("command", "verb", "expected", "why"),
    [
        ("spec-kitty merge --mission x", MERGE, True, "the plain form"),
        ("spec-kitty merge", MERGE, True, "no flags at all"),
        (
            "spec-kitty merge-driver-meta a b c",
            MERGE,
            False,
            r"\b matches before a hyphen, so a naive regex false-positives on all six "
            r"merge-driver-* subcommands",
        ),
        ("spec-kitty agent mission merge", AGENT_MERGE, True, "a naive regex misses this entirely"),
        ("spec-kitty agent mission merge", MERGE, False, "and it is not the top-level verb"),
        ("spec-kitty agent mission create", AGENT_CREATE, True, "FR-001's target"),
        (
            "spec-kitty mission create",
            AGENT_CREATE,
            False,
            "a DIFFERENT command (tracker fetch); token matching disambiguates, regex does not",
        ),
        ("spec-kitty mission create", MISSION_CREATE, True, "and it matches its own verb"),
        ("foo && spec-kitty merge --mission x", MERGE, True, "segment 2 is still gated"),
        ("foo&&spec-kitty merge", MERGE, True, "unspaced operators segment too"),
        ("foo; spec-kitty merge", MERGE, True, "semicolon"),
        ("foo | spec-kitty merge", MERGE, True, "pipe"),
        ("foo || spec-kitty merge", MERGE, True, "or-else"),
        ("(spec-kitty merge)", MERGE, True, "subshell parentheses"),
        ("spec-kitty  merge   --mission x", MERGE, True, "flexible whitespace"),
        ("spec-kitty --json merge --mission x", MERGE, True, "flag order independence"),
        ("/usr/local/bin/spec-kitty merge", MERGE, True, "argv[0] is compared by basename"),
        ("FOO=1 spec-kitty merge", MERGE, True, "leading env-style assignments are skipped"),
        ("env FOO=1 spec-kitty merge", MERGE, True, "and so is a leading `env`"),
        ("sh -c 'spec-kitty merge --mission x'", MERGE, True, "reached through sh -c"),
        # --- F1: the newline. `shlex` never emits one as a token, so a `\n` in the
        # separator pattern was dead code that looked alive, and a line break was a
        # complete escape. Multi-line is the DEFAULT shape of a Claude Code Bash call.
        (
            "cd /tmp\nspec-kitty agent mission create",
            AGENT_CREATE,
            True,
            "F1: a line break is a segment boundary — data-model.md §4.1 names newline",
        ),
        (
            "cd /tmp && \\\nspec-kitty merge",
            MERGE,
            True,
            "F1: a line continuation joins the lines; it used to yield a '\\nspec-kitty' token",
        ),
        (
            'git commit -m "fix the gate\n\nspec-kitty merge is only mentioned"',
            MERGE,
            False,
            "F1 PAIRED NEGATIVE: a quoted mention that SPANS lines is still one token",
        ),
        # --- F2: keywords and glued punctuation runs. `punctuation_chars` emits `);` and
        # `&&(` as single tokens, so enforcement turned on whether a space was typed.
        ("{ spec-kitty merge; }", MERGE, True, "F2: a brace group"),
        ("if true; then spec-kitty merge; fi", MERGE, True, "F2: after a `then` keyword"),
        ("(cd /tmp); spec-kitty merge", MERGE, True, "F2: `);` is ONE token"),
        ("(cd /tmp) ; spec-kitty merge", MERGE, True, "F2: and the spaced form must agree"),
        ("true&&(spec-kitty merge)", MERGE, True, "F2: `&&(` is ONE token"),
        ("nohup spec-kitty merge", MERGE, True, "F2: a leading wrapper program"),
        ("time spec-kitty merge", MERGE, True, "F2: and a leading keyword-shaped one"),
        ("command spec-kitty merge", MERGE, True, "F2: `command` defeats an alias, not the gate"),
        ("! spec-kitty merge", MERGE, True, "F2: negation is a prefix, not a program"),
        ("while spec-kitty merge; do :; done", MERGE, True, "F2: `while` — see _KEYWORD_PREFIXES"),
        ("until spec-kitty merge; do :; done", MERGE, True, "F2: and `until`"),
        ("if spec-kitty merge; then :; fi", MERGE, True, "F2: and the `if` condition itself"),
        (
            'echo "{ spec-kitty merge; }"',
            MERGE,
            False,
            "F2 PAIRED NEGATIVE: quoting the whole brace group is STILL a mention",
        ),
        (
            "nohup git merge main",
            MERGE,
            False,
            "F2 PAIRED NEGATIVE: skipping a prefix must not stop argv[0] being compared",
        ),
    ],
)
def test_argv_matching_discriminators(command: str, verb: tuple[str, ...], expected: bool, why: str) -> None:
    assert matches_any(command, verb) is expected, why


@pytest.mark.parametrize(
    "command",
    [
        'echo "do not run spec-kitty merge --mission x yet"',
        "echo 'reminder: spec-kitty agent mission create'",
        'printf "%s" "spec-kitty merge"',
        'python -c "print(\'spec-kitty merge\')"',
        ':  # spec-kitty merge',
        'true "spec-kitty merge"',
    ],
)
def test_a_quoted_mention_is_not_an_invocation(command: str) -> None:
    """FR-010a. The whole phrase is ONE argument, so ``argv[0]`` is never ``spec-kitty``.

    The allowlist is on ``argv[0]``: a denylist of ``echo`` would be defeated by
    ``printf``, ``:`` and ``true`` equally well, which is why none of those are enumerated
    in the implementation.
    """
    assert not matches_any(command, MERGE)
    assert not matches_any(command, AGENT_CREATE)


@pytest.mark.parametrize(
    "command",
    ["git merge main", "hg merge", "foo merge --mission x", "npm create vite"],
)
def test_a_different_program_with_the_same_subcommand_does_not_match(command: str) -> None:
    """``argv[0]`` is compared, not just the tokens after it.

    Found by the mutation pass: deleting the ``argv[0]`` comparison left 26 argv tests
    green, because every existing case differed in a LATER token too. ``git merge main``
    is the case that needs it — without the comparison it matches
    ``("spec-kitty", "merge")`` and every ``git merge`` in the repo starts being gated.
    """
    assert not matches_any(command, MERGE)


def test_an_unparseable_sh_c_payload_denies(tmp_path: Path) -> None:
    """A gated verb hidden inside an untokenisable ``sh -c`` string must not escape.

    Found on review, not by a test: the inner-command tokenisation error used to be
    swallowed, leaving only the outer ``sh`` argv — which is not a gated program, so the
    call ALLOWED. Propagating the error denies instead.
    """
    with pytest.raises(lib.CommandParseError):
        lib.split_segments('sh -c \'spec-kitty merge --mission "unterminated\'')
    assert_deny(
        run_gate(
            pre_payload("shc-1", 'sh -c \'spec-kitty merge --mission "unterminated\''),
            hooks_root=tmp_path,
        )
    )


def test_a_quoted_sweep_query_is_not_a_sweep_query(tmp_path: Path) -> None:
    """The live filing guard is satisfied by exactly this, which is the defect FR-010a closes."""
    command = 'echo "gh issue list --author kent --state all Priivacy-ai/spec-kitty"'
    assert_allow(run_gate(post_payload("sweep-echo", command), hooks_root=tmp_path))
    state, status = lib.read_session_ledger("sweep-echo", root=tmp_path)
    assert status is lib.LedgerStatus.FRESH
    assert state.get("markers", {}) == {}


def test_a_real_sweep_query_does_mark(tmp_path: Path) -> None:
    """PAIRED POSITIVE: without this, a detector that marks NOTHING would look correct."""
    command = "gh issue list --author kent --state all --repo Priivacy-ai/spec-kitty"
    assert_allow(run_gate(post_payload("sweep-real", command), hooks_root=tmp_path))
    state, _ = lib.read_session_ledger("sweep-real", root=tmp_path)
    assert "sweep.authored" in state["markers"]


def test_the_upstream_repo_alone_does_not_mark_the_authored_sweep(tmp_path: Path) -> None:
    """``sweep.authored`` needs BOTH the upstream repo and ``--author``, not either.

    Found while designing the mutation pass: dropping the ``--author`` requirement left
    every deny test green, because no near-miss case carried the repo *without* the flag.
    """
    command = "gh issue list --state all --repo Priivacy-ai/spec-kitty"
    assert_allow(run_gate(post_payload("auth-miss", command), hooks_root=tmp_path))
    state, _ = lib.read_session_ledger("auth-miss", root=tmp_path)
    assert "sweep.authored" not in state.get("markers", {})


# =============================================================================
# The ownership seam — `target_repo`, `is_ours`, `names_upstream`
#
# Direct calls, because a subprocess would only obscure which of the three answered
# wrongly. The wire-level pairs live in `test_cp_before.py`.
# =============================================================================


@pytest.mark.parametrize(
    "form",
    ["--repo {repo}", "--repo={repo}", "-R {repo}", "-R{repo}", "-R={repo}"],
    ids=["long-separated", "long-equals", "short", "short-attached", "short-equals"],
)
def test_every_target_form_extracts_the_same_value(form: str) -> None:
    """Every spelling `gh` accepts, extracting identically.

    ⚠ `--repo=X` is ONE token with the value inside it. Only the separated long form had
    coverage before, so an extractor that missed the `=` form would read no target, and
    "no target" is not "ours" — the two failure directions are different and both silent.

    ⚠ The last two are the ATTACHED short forms and they were the cycle-2 blocker: `gh`
    treats `-Rowner/name`, `-R=owner/name` and `-R owner/name` as ONE flag, MEASURED::

        $ gh issue list -Rcli/cli  --limit 1 --json url  -> cli/cli
        $ gh issue list -R=cli/cli --limit 1 --json url  -> cli/cli

    An extractor handling only the separated short form reads NO target from
    `-RPriivacy-ai/spec-kitty` — so an honest operator sweeping upstream in a spelling
    the tool fully supports earned nothing, and `-Rspec-kitty/spec-kitty-qa` appended
    after an upstream `--repo` earned a marker while `gh` queried our own tracker.
    """
    argv = ["gh", "issue", "list", *form.format(repo="octocat/hello").split(), "--state", "all"]
    assert lib.target_repo(argv) == "octocat/hello"


def test_a_command_with_no_target_flag_names_nothing() -> None:
    """`None`, not a guess. Resolving a git remote here was considered and cut
    (qa#291 item 4); a bare filing keeps today's behaviour."""
    assert lib.target_repo(["gh", "issue", "list", "--state", "all"]) is None
    assert lib.target_repo([]) is None
    assert lib.target_repo(["gh", "issue", "list", "--repo"]) is None


def test_a_bare_positional_reference_is_not_a_target() -> None:
    """PAIRED with the extraction tests: a token that merely LOOKS like a repository is
    not one. `gh issue list` has no positional repository argument, and the old
    scan-every-token matcher treating one as a target is the class of false positive the
    extractor removes."""
    assert lib.target_repo(["gh", "issue", "list", "Priivacy-ai/spec-kitty"]) is None


def test_the_last_target_flag_wins_and_a_repo_inside_a_value_is_not_a_target() -> None:
    """TWO rules, both live in the same argv, because both were once broken here.

    1. A body or a `--search` VALUE naming another repository must not move the verdict.
       Under the inversion, token-scanning would classify an internal filing as upstream
       whenever its description cited anything.
    2. When the target flag is REPEATED, the LAST occurrence decides — because that is
       what `gh` does (measured, see `target_repo`'s docstring). This test's predecessor
       was named for first-wins and carried only ONE `--repo`, so it never exercised
       first-vs-last at all and the extractor disagreed with `gh` under a green suite.

    The fixture therefore carries two REAL target flags naming opposite sides plus a
    third mention inside a value. Under first-wins the verdict flips to upstream.
    """
    argv = ["gh", "issue", "create", "--repo", "Priivacy-ai/spec-kitty",
            "--body", "see Priivacy-ai/spec-kitty#3728",
            "--repo", "spec-kitty/spec-kitty-qa"]
    assert lib.target_repo(argv) == "spec-kitty/spec-kitty-qa"
    assert lib.is_ours(lib.target_repo(argv))
    assert not lib.names_upstream(argv)


#: EVERY spelling `gh` accepts, as `(token…)` builders. Every ORDERED PAIR of these is
#: exercised below, so a mixed-spelling duplicate cannot slip between two per-form tests
#: that each only ever see their own spelling — which is exactly how the attached short
#: form survived a green suite: three forms were pinned individually and pairwise, and
#: the two `gh` also accepts were in neither list.
_TARGET_FORMS = (
    "--repo {repo}",
    "--repo={repo}",
    "-R {repo}",
    "-R{repo}",
    "-R={repo}",
)

_FORM_IDS = ("sep", "eq", "short", "short-attached", "short-eq")


@pytest.mark.parametrize(
    "second_form", _TARGET_FORMS, ids=[f"2nd-{name}" for name in _FORM_IDS]
)
@pytest.mark.parametrize(
    "first_form", _TARGET_FORMS, ids=[f"1st-{name}" for name in _FORM_IDS]
)
@pytest.mark.parametrize(
    "first_repo,second_repo,expected_upstream",
    [
        pytest.param(
            "Priivacy-ai/spec-kitty",
            "spec-kitty/spec-kitty-qa",
            False,
            id="upstream-then-ours",
        ),
        pytest.param(
            "spec-kitty/spec-kitty-qa",
            "Priivacy-ai/spec-kitty",
            True,
            id="ours-then-upstream",
        ),
    ],
)
def test_a_repeated_target_flag_resolves_the_way_gh_resolves_it(
    first_form: str,
    second_form: str,
    first_repo: str,
    second_repo: str,
    expected_upstream: bool,
) -> None:
    """MEASURED against gh 2.98.0, not inferred — both directions, every mix of forms::

        $ gh issue list --repo cli/cli --repo octocat/Hello-World --limit 1 --json url
        [{"url":"https://github.com/octocat/Hello-World/issues/11019"}]
        $ gh issue list --repo octocat/Hello-World --repo cli/cli --limit 1 --json url
        [{"url":"https://github.com/cli/cli/issues/14257"}]
        $ gh issue list --repo cli/cli -R octocat/Hello-World  -> octocat/Hello-World
        $ gh issue list -R cli/cli --repo octocat/Hello-World  -> octocat/Hello-World
        $ gh issue list --repo=cli/cli --repo octocat/Hello-World -> octocat/Hello-World
        $ gh issue list --repo cli/cli --repo=octocat/Hello-World -> octocat/Hello-World

    BOTH parametrized directions matter and neither alone is sufficient:

    * `ours-then-upstream` is the DENY half — first-wins reads our own tracker, so
      `names_upstream` answers False while `gh` files upstream. That is a guard that
      goes inert on a real upstream filing.
    * `upstream-then-ours` is the ALLOW half — first-wins reads upstream, so a sweep
      earns its marker while `gh` queries our own issues. That is T004's gaming path,
      reopened by one extra token.
    """
    argv = [
        "gh", "issue", "list",
        *first_form.format(repo=first_repo).split(),
        *second_form.format(repo=second_repo).split(),
        "--state", "all",
    ]
    assert lib.target_repo(argv) == second_repo, (
        f"`{first_form.format(repo=first_repo)} {second_form.format(repo=second_repo)}` "
        f"resolved to something other than {second_repo}; `gh` binds the target with a "
        "cobra string flag, so the LAST occurrence wins"
    )
    assert lib.names_upstream(argv) is expected_upstream


# -----------------------------------------------------------------------------
# The VALUE axis. `gh` prints its own target as `-R, --repo [HOST/]OWNER/REPO`, and it
# accepts clone URLs too, so two values that LOOK different reach the same tracker.
# Everything below was measured against gh 2.98.0 (2026-08-27) by reading back the
# repository `gh` actually queried out of the issue URL it returned.
# -----------------------------------------------------------------------------

#: Every value spelling MEASURED to reach `cli/cli`, as `{repo}` templates. The `{repo}`
#: placeholder is substituted so the same list can be pointed at OUR tracker below —
#: which is what makes this an exploit list and not a formatting list.
_VALUE_FORMS_GH_ACCEPTS = (
    "{repo}",
    "github.com/{repo}",
    "GitHub.com/{repo}",
    "http://github.com/{repo}",
    "https://github.com/{repo}",
    "https://GITHUB.COM/{repo}",
    "https://github.com/{repo}.git",
    "https://user@github.com/{repo}",
    "git://github.com/{repo}",
    "ssh://git@github.com/{repo}.git",
    "git+ssh://git@github.com/{repo}.git",
    "git@github.com:{repo}",
    "git@github.com:{repo}.git",
)


@pytest.mark.parametrize("value_form", _VALUE_FORMS_GH_ACCEPTS)
def test_every_value_form_gh_accepts_reaches_the_same_repository(value_form: str) -> None:
    """ALLOW half. Each of these made `gh` query `cli/cli`; each must extract `cli/cli`.

    MEASURED, e.g.::

        $ gh issue list --repo github.com/cli/cli --limit 1 --json url
        [{"url":"https://github.com/cli/cli/issues/14257"}]
        $ gh issue list --repo git@github.com:cli/cli.git --limit 1 --json url
        [{"url":"https://github.com/cli/cli/issues/14257"}]
    """
    argv = ["gh", "issue", "list", "--repo", value_form.format(repo="cli/cli")]
    assert lib.target_repo(argv) == "cli/cli"


@pytest.mark.parametrize("value_form", _VALUE_FORMS_GH_ACCEPTS)
def test_a_host_qualified_spelling_of_our_own_tracker_is_still_ours(value_form: str) -> None:
    """DENY half, and the reason the value axis is not cosmetic.

    This is the cycle-2 blocker in the value axis instead of the flag axis. MEASURED::

        $ gh issue list --repo github.com/spec-kitty/spec-kitty-qa --limit 1 --json url
        [{"url":"https://github.com/spec-kitty/spec-kitty-qa/issues/291"}]

    `gh` queries OUR OWN tracker. An extractor comparing the value verbatim finds
    `github.com/spec-kitty/spec-kitty-qa` is not in `OURS`, answers "upstream", and
    awards a sweep marker for a sweep of our own issues — T004's gaming path, reopened
    by a prefix the tool documents in its own `--help`.
    """
    argv = ["gh", "issue", "list", "--repo", value_form.format(repo="spec-kitty/spec-kitty-qa")]
    assert lib.is_ours(lib.target_repo(argv)), (
        f"`--repo {value_form.format(repo='spec-kitty/spec-kitty-qa')}` reaches our own "
        "tracker in `gh` but did not classify as ours"
    )
    assert not lib.names_upstream(argv)


@pytest.mark.parametrize(
    "value",
    [
        "cli/cli.git",  # `.git` is stripped off a URL, never off a bare name
        "github.com/cli/cli/extra",
        "https://github.com/cli/cli/issues/1",
        "//github.com/cli/cli",
        "/cli/cli",
        "cli/cli/",
        "HTTPS://GitHub.com/cli/cli",  # the scheme test is case-SENSITIVE in `gh`
        "ftp://github.com/cli/cli",
        "foo@github.com:cli/cli",  # the scp form requires a literal `git@`
    ],
)
def test_a_value_gh_refuses_is_not_repaired(value: str) -> None:
    """PAIRED with the two above: normalisation must not accept MORE than the tool does.

    Every value here was measured to make `gh` fail — *expected the "[HOST/]OWNER/REPO"
    format*, *invalid path*, or a 404 on the literal name. Repairing them would be a
    divergence in the opposite direction from the one this seam just closed: this
    extractor would resolve a target `gh` never resolves at all.

    Returning the value untouched is also the safe answer — it is not in `OURS`, so it
    falls to the enforcing side.
    """
    argv = ["gh", "issue", "list", "--repo", value]
    assert lib.target_repo(argv) == value
    assert not lib.is_ours(lib.target_repo(argv))


@pytest.mark.parametrize(
    "value",
    [
        "evil.example/spec-kitty/spec-kitty-qa",
        "https://evil.example/spec-kitty/spec-kitty-qa",
        "git@evil.example:spec-kitty/spec-kitty-qa",
    ],
)
def test_the_same_name_on_another_host_is_not_ours(value: str) -> None:
    """DENY half of the host handling. The host is stripped ONLY when it is GitHub's.

    MEASURED: `--repo evil.example/cli/cli` makes `gh` connect to `evil.example`, so a
    repository of the same `owner/name` on another host is a DIFFERENT repository. If
    the host were stripped unconditionally, this would classify as ours and a filing
    guard routed through this seam would skip its evidence requirement on it.
    """
    argv = ["gh", "issue", "create", "--repo", value, "--title", "x"]
    assert not lib.is_ours(lib.target_repo(argv))
    assert lib.names_upstream(argv)


# -----------------------------------------------------------------------------
# The EMPTY value — a pinned decision, not an accident
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tokens",
    [
        pytest.param(["--repo", ""], id="long-separated"),
        pytest.param(["--repo="], id="long-equals"),
        pytest.param(["-R", ""], id="short-separated"),
    ],
)
def test_an_empty_target_value_names_nothing(tokens: list[str]) -> None:
    """All three spellings of an empty value agree, because `gh` treats them alike.

    They did NOT agree before: the `=` branch ended `or None` and the separated branch
    did not, so `--repo=` returned `None` while `--repo ""` returned `''` — and `''` is
    not in `OURS`, so it answered "upstream" and earned a sweep marker for a query `gh`
    resolved from the git remote, which is our own tracker. MEASURED::

        $ gh issue list --repo "" --limit 1 --json url
        [{"url":"https://github.com/spec-kitty/spec-kitty-qa/issues/291"}]
        $ gh issue list --repo=  --limit 1 --json url
        [{"url":"https://github.com/spec-kitty/spec-kitty-qa/issues/291"}]
        $ gh issue list -R ""    --limit 1 --json url
        [{"url":"https://github.com/spec-kitty/spec-kitty-qa/issues/291"}]

    `None` — "no target named" — is the chosen answer of the two honest options, and
    the choice is justified in `target_repo`'s docstring. It is NOT git-remote
    resolution, which stays cut (qa#291 item 4).
    """
    assert lib.target_repo(["gh", "issue", "list", *tokens, "--state", "all"]) is None


@pytest.mark.parametrize(
    "tokens",
    [
        pytest.param(["--repo", ""], id="empty-long-separated"),
        pytest.param(["--repo="], id="empty-long-equals"),
        pytest.param(["-R", ""], id="empty-short-separated"),
    ],
)
def test_an_empty_target_value_defeats_an_earlier_real_target(tokens: list[str]) -> None:
    """An empty value cannot be SKIPPED, because in `gh` it wins like any other. MEASURED::

        $ gh issue list --repo cli/cli --repo "" --limit 1 --json url
        [{"url":"https://github.com/spec-kitty/spec-kitty-qa/issues/291"}]

    An extractor that ignored an empty occurrence would keep `Priivacy-ai/spec-kitty`
    from the earlier flag and award `sweep.authored` while `gh` swept our own issues —
    the same one-token gaming path as a repeated flag, spelled with nothing at all.
    """
    argv = ["gh", "issue", "list", "--repo", "Priivacy-ai/spec-kitty", *tokens]
    assert lib.target_repo(argv) is None
    assert not lib.names_upstream(argv)


def test_an_empty_target_value_does_not_defeat_a_LATER_real_target() -> None:
    """PAIRED CONTROL. Resetting on empty must not become "empty poisons the command".

    MEASURED: `gh issue list --repo "" --repo cli/cli` queried `cli/cli`. Without this
    pair, a `target_repo` that returned `None` whenever any empty value appeared would
    pass the test above and silently stop awarding markers to real upstream sweeps.
    """
    argv = ["gh", "issue", "list", "--repo", "", "--repo", "Priivacy-ai/spec-kitty"]
    assert lib.target_repo(argv) == "Priivacy-ai/spec-kitty"
    assert lib.names_upstream(argv)


# -----------------------------------------------------------------------------
# The boundary this extractor deliberately does NOT cross
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("-aRcli/cli", id="assignee-swallows-the-R"),
        pytest.param("-lRcli/cli", id="label-swallows-the-R"),
    ],
)
def test_an_R_inside_a_shorthand_cluster_is_not_a_target(token: str) -> None:
    """The boundary, pinned with the measurement that ARGUES for it.

    `gh` clusters single-character shorthands, and a value-taking one SWALLOWS what
    follows. MEASURED::

        $ gh issue list -aRcli/cli --limit 1 --json url
        GraphQL: Could not find an assignee with the login 'Rcli/cli'.

    `gh` read an ASSIGNEE, not a repository, and resolved the target from the git
    remote — ours. A cluster-aware extractor would read `cli/cli` as the target and
    award a marker for a sweep of our own tracker: a NEW hole, opened by trying to
    close a smaller one. Reading nothing here is the correct answer, and knowing which
    cluster is which needs `gh`'s per-subcommand flag-arity table, not a guess at it.
    """
    assert lib.target_repo(["gh", "issue", "list", token, "--state", "all"]) is None


@pytest.mark.parametrize("form", _TARGET_FORMS, ids=list(_FORM_IDS))
def test_a_filing_is_classified_by_the_winning_flag_in_every_spelling(form: str) -> None:
    """The FILING direction, which is WP02's bypass rather than a missing marker.

    A filing that names our tracker first and upstream last goes UPSTREAM in `gh`. If
    `names_upstream` answers False here, a guard routed through this seam classifies a
    real upstream filing as internal and skips its evidence requirement — the guard
    silently inert on exactly the act it exists to govern, which is the defect this
    mission was written to remove. Measured directly::

        target_repo(shlex.split(
            'gh issue create --repo spec-kitty/spec-kitty-qa '
            '-RPriivacy-ai/spec-kitty --title x'))
          -> 'spec-kitty/spec-kitty-qa'   under the cycle-2 extractor  (WRONG)
    """
    argv = [
        "gh", "issue", "create",
        "--repo", "spec-kitty/spec-kitty-qa",
        *form.format(repo="Priivacy-ai/spec-kitty").split(),
        "--title", "x",
    ]
    assert lib.target_repo(argv) == "Priivacy-ai/spec-kitty"
    assert lib.names_upstream(argv)

    #: PAIRED: reversed, the same two flags must classify as OURS. Without this half an
    #: extractor answering "upstream" unconditionally would pass.
    reversed_argv = [
        "gh", "issue", "create",
        *form.format(repo="Priivacy-ai/spec-kitty").split(),
        "--repo", "spec-kitty/spec-kitty-qa",
        "--title", "x",
    ]
    assert lib.is_ours(lib.target_repo(reversed_argv))
    assert not lib.names_upstream(reversed_argv)


@pytest.mark.parametrize(
    "reference",
    [
        "spec-kitty/spec-kitty-qa",
        "spec-kitty/SPEC-KITTY-QA",
        "Spec-Kitty/Spec-Kitty-QA",
    ],
)
def test_ours_is_matched_case_insensitively(reference: str) -> None:
    """Matches the semantics of the other owner/name comparator in the tree
    (`scripts/scope_resolve.py`), which lower-cases both sides."""
    assert lib.is_ours(reference)


@pytest.mark.parametrize(
    "reference,why",
    [
        pytest.param(
            "spec-kitty/spec-kitty",
            "the prefix-adjacent pair: `'spec-kitty/spec-kitty' in "
            "'spec-kitty/spec-kitty-qa'` is True, so a substring comparison inverts this",
            id="prefix-adjacent",
        ),
        pytest.param(
            "spec-kitty/spec-kitty-qa-fork",
            "our name is a PREFIX of this one; equality, not startswith",
            id="our-name-is-a-prefix",
        ),
        pytest.param("spec-kitty/", "a bare org is not a repository", id="bare-org"),
        pytest.param("spec-kitty", "an org alone is not a reference", id="org-only"),
        pytest.param(
            "spec-kitty/spec-kitty-analyzer",
            "contested and resolved UPSTREAM: operator-maintained, but it receives defect "
            "reports about a product we test",
            id="analyzer-is-upstream",
        ),
        pytest.param("octocat/hello", "unknown falls to the enforcing side", id="unknown"),
        pytest.param(None, "no target named is not a claim of ownership", id="none"),
    ],
)
def test_what_is_not_ours(reference: str | None, why: str) -> None:
    """The deny half of `is_ours`, PAIRED with `test_ours_is_matched_case_insensitively`.

    Alone, either side is satisfiable by a constant function."""
    assert not lib.is_ours(reference), why


@pytest.mark.parametrize(
    "repo",
    [
        pytest.param("spec-kitty/spec-kitty", id="post-rename-cli"),
        pytest.param("spec-kitty/spec-kitty-saas", id="post-rename-saas"),
        pytest.param("spec-kitty/EXPERIMENTAL-spec-kitty", id="current-cli"),
        pytest.param("Priivacy-ai/spec-kitty", id="retiring-org"),
        pytest.param("octocat/hello", id="never-seen"),
    ],
)
def test_names_upstream_is_true_for_everything_that_is_not_ours(repo: str) -> None:
    """The inversion, at the seam. NONE of the post-rename names appears in any constant
    in the module — that they classify as upstream with no list edit IS the mission."""
    assert lib.names_upstream(["gh", "issue", "list", "--repo", repo])


def test_names_upstream_is_false_for_our_own_tracker_and_for_no_target() -> None:
    """PAIRED POSITIVE-SIDE: without this, `def names_upstream(...): return True` passes
    every assertion above."""
    assert not lib.names_upstream(["gh", "issue", "list", "--repo", "spec-kitty/spec-kitty-qa"])
    assert not lib.names_upstream(["gh", "issue", "list", "--state", "all"])


# =============================================================================
# The remedies derive from the target set (T005)
# =============================================================================


#: The remedies that answer "what is in that queue?" — they must name the queues, so
#: they derive from `UPSTREAM_TARGETS`. `sweep.register_refs` answers a DIFFERENT
#: question, "where does THIS reference live?", and is covered by its own pair below.
QUEUE_SCOPED_MARKERS = tuple(sorted(lib.MARKERS - {"sweep.register_refs"}))


def _all_printed_remedies(ledger: Path) -> str:
    return (
        "\n".join(line for lines in lib.MARKER_COMMANDS.values() for line in lines)
        + "\n"
        + lib.corrupt_ledger_denial(ledger, "JSONDecodeError")
    )


def test_every_literal_repository_printed_is_a_canonical_target(tmp_path: Path) -> None:
    """No upstream literal survives in remedy-producing code.

    Five sites used to carry hand-copied literals. After the rename they name a
    repository that does not exist, `gh` fails on every one, no marker can be earned and
    mission start is refused PERMANENTLY behind a remedy that cannot satisfy it.

    Shell expansions (`"${ref%#*}"`) are excluded on purpose: they are not literals, and
    reading a repository off the reference is exactly what `sweep.register_refs` must do.
    """
    printed = _all_printed_remedies(tmp_path / "ledger.json")
    referenced = {
        ref for ref in re.findall(r"--repo[= ](\S+)", printed) if "$" not in ref
    }
    assert referenced, "no remedy names a repository at all"
    assert referenced <= set(lib.UPSTREAM_TARGETS), (
        f"{sorted(referenced - set(lib.UPSTREAM_TARGETS))} is printed but is not in "
        "UPSTREAM_TARGETS — a hand-copied literal survives a rename"
    )


@pytest.mark.parametrize("marker", QUEUE_SCOPED_MARKERS)
def test_each_queue_scoped_remedy_covers_every_target(marker: str) -> None:
    """PAIRED with the test above, which only forbids strays. This forbids omissions:
    a remedy that names one of three queues cannot tell a human to sweep the others."""
    printed = "\n".join(lib.MARKER_COMMANDS[marker])
    for target in lib.UPSTREAM_TARGETS:
        assert target in printed, f"the {marker} remedy does not name {target}"


def test_the_register_refs_remedy_reads_the_repo_off_each_reference() -> None:
    """The one remedy that must NOT name a constant repository — the DENY half.

    ⚠ MEASURED by WP03, not reasoned: the register's 53 references live in THREE
    repositories (47 `Priivacy-ai/spec-kitty`, 4 `spec-kitty/spec-kitty-qa`, 1
    `Priivacy-ai/spec-kitty-saas`). Any single repository is wrong, and deriving from
    `UPSTREAM_TARGETS` would only swap one wrong repository for another. It is not a
    quiet failure either: querying #205/#214 against the CLI repo returned CLOSED for
    two entirely unrelated issues — a confident wrong answer.
    """
    printed = "\n".join(lib.MARKER_COMMANDS["sweep.register_refs"])
    named = [target for target in lib.UPSTREAM_TARGETS if target in printed]
    assert not named, (
        f"the register cross-check remedy pins {named}, but the register's references "
        "live in several repositories — a single repo answers CONFIDENTLY and WRONGLY"
    )
    assert re.search(r"--repo\s+\"?\$\{?ref", printed), (
        "the remedy must read each reference's repository off the reference itself"
    )


def _runbook_register_refs_command() -> str:
    """Read §0 query 3 from the operator-facing runbook, not from hook constants."""
    runbook = (REPO_ROOT / "docs/runbooks/autonomous-run-protocol.md").read_text(encoding="utf-8")
    marker = "# 3. Cross-check every upstream ref the register cites, each against its OWN repository"
    assert runbook.count(marker) == 1, "runbook query 3 heading is absent or ambiguous"
    lines = runbook.split(marker, 1)[1].lstrip("\n").splitlines()
    try:
        end = lines.index("done")
    except ValueError:
        pytest.fail("runbook query 3 has no closing `done`")
    return "\n".join(lines[: end + 1])


def test_runbook_register_refs_query_is_the_gate_remedy_verbatim() -> None:
    """#285: the documented command and enforced remedy must move together or not at all."""
    documented = _runbook_register_refs_command()
    enforced = "\n".join(lib.MARKER_COMMANDS["sweep.register_refs"])

    assert documented == enforced, (
        "§0 query 3 drifted from MARKER_COMMANDS[sweep.register_refs]; following the runbook "
        "would no longer prove what the mission-start gate demands"
    )


def test_runbook_register_refs_query_actually_earns_its_marker() -> None:
    """Exact text equality is insufficient if both copies drift to the same inert command."""
    command = _runbook_register_refs_command()
    payload = lib.Payload(
        session_id="runbook-drift-probe",
        hook_event_name="PostToolUse",
        tool_name="Bash",
        tool_input={"command": command},
        cwd=str(REPO_ROOT),
        tool_use_id=None,
        error=None,
        error_type=None,
        is_interrupt=False,
        is_timeout=False,
        raw={},
    )

    markers = lib.detect_markers(payload, lib.split_segments(command))
    assert "sweep.register_refs" in markers, (
        "the runbook and gate agree on a command that cannot earn sweep.register_refs"
    )


def test_the_register_refs_remedy_is_still_a_runnable_register_cross_check() -> None:
    """The ALLOW half. Without it, deleting the remedy entirely passes the test above.

    Pins the three things that make the printed command earn the marker it demands:
    it reads the register, it matches QUALIFIED `owner/name#123` references, and it
    tokenises as `gh issue view` — which is the conjunction `detect_markers` requires.
    A remedy that cannot earn its own marker is a livelock, and this gate has shipped
    one before.
    """
    printed = "\n".join(lib.MARKER_COMMANDS["sweep.register_refs"])
    assert lib.REGISTER in printed, "the remedy does not read the register"
    assert "/" in printed and "#" in printed, "the remedy does not match qualified refs"
    assert "gh issue view" in printed, "the remedy cannot earn sweep.register_refs"

    segments = lib.split_segments("\n".join(lib.MARKER_COMMANDS["sweep.register_refs"]))
    views = [
        seg for seg in segments
        if lib._positional_tokens(lib.effective_argv(seg))[1:3] == ["issue", "view"]
    ]
    assert views, (
        "no segment of the printed remedy tokenises as `gh issue view`, so running the "
        "gate's own advice verbatim would earn nothing — the livelock, re-armed"
    )
    assert lib.names_upstream(lib.effective_argv(views[0])), (
        "the printed cross-check does not classify as upstream, so it earns nothing"
    )


def test_the_corrupt_ledger_remedy_covers_every_target(tmp_path: Path) -> None:
    """The FIFTH remedy site, which the other two assertions could not see.

    ⚠ Found by mutation, not by reading. Restoring the hand-copied literal here left
    both remedy tests green: the literal happened to be a MEMBER of `UPSTREAM_TARGETS`,
    so "no strays" was satisfied, and `MARKER_COMMANDS` — the only thing the coverage
    test iterated — was untouched. This site is a separate function and needs its own
    assertion, which is the whole reason a hand-copied duplicate survived here in the
    first place.
    """
    printed = lib.corrupt_ledger_denial(tmp_path / "ledger.json", "JSONDecodeError")
    for target in lib.UPSTREAM_TARGETS:
        assert target in printed, (
            f"the corrupt-ledger remedy does not name {target} — this site was a "
            "hand-copied duplicate once and must never become one again"
        )


def test_a_previously_allowed_command_now_correctly_denies(tmp_path: Path) -> None:
    """The blast radius widens in BOTH directions, by design — so make it visible.

    Tokenising starts gating commands the old regex missed. ``foo && spec-kitty merge``
    is the measured example: the old substring/regex matcher anchored on the start of the
    command text and let the chained invocation through.
    """
    assert matches_any("foo && spec-kitty merge --mission x", MERGE)
    assert not re.match(r"^\s*spec-kitty\s+merge\b", "foo && spec-kitty merge --mission x")


def test_malformed_quoting_denies() -> None:
    with pytest.raises(lib.CommandParseError):
        lib.split_segments('spec-kitty merge --mission "unterminated')


def test_malformed_quoting_denies_through_the_wire(tmp_path: Path) -> None:
    reason = assert_deny(
        run_gate(pre_payload("argv-bad", 'spec-kitty merge --mission "unterminated'), hooks_root=tmp_path)
    )
    assert "quoting" in reason.lower()


def test_segments_split_at_every_documented_operator() -> None:
    """EVERY boundary ``data-model.md`` §4.1 names — ``;`` ``&&`` ``||`` ``|`` ``&`` newline ``(``.

    The name used to promise a completeness the body did not have: it exercised the four
    operators the implementation already believed in. That is precisely why a 52-mutation
    pass could not see F1 or F2 — the mutations moved the separator *set*, never the
    assumption that ``shlex`` hands back a newline token (it does not) or that a glued
    ``);`` arrives as ``)`` and ``;`` (it does not). Both are asserted here now.
    """
    assert lib.split_segments("a && b || c ; d | e & f") == [
        ["a"],
        ["b"],
        ["c"],
        ["d"],
        ["e"],
        ["f"],
    ]
    assert lib.split_segments("a\nb") == [["a"], ["b"]], "F1: newline"
    assert lib.split_segments("(a); b") == [["a"], ["b"]], "F2: the glued `);` run"
    assert lib.split_segments("a&&(b)") == [["a"], ["b"]], "F2: the glued `&&(` run"
    # A brace is NOT a separator: `{ a; }` is one segment `{ a` and one `}`. The brace is
    # dropped when argv[0] is read (see effective_argv), which is where F2's other half is.
    assert lib.split_segments("{ a; }") == [["{", "a"], ["}"]]
    assert lib.program_of(["{", "a"]) == "a", "F2: the brace is not the program"


def test_a_quoted_newline_token_is_a_separator() -> None:
    """The one live path to the ``\\n`` branch of the separator pattern, asserted.

    Physical newlines are handled by :func:`lib.split_segments`'s line splitting and never
    reach the token loop, so ``\\n`` in the pattern would be dead code that looks alive —
    the exact defect F1 was. It is reachable through a QUOTED newline, which ``shlex``
    strips the quotes from and hands back as a token indistinguishable from an operator.
    Over-splitting is the safe direction; this pins which direction it takes.
    """
    assert lib.split_segments('foo "\n" bar') == [["foo"], ["bar"]]


def test_an_empty_command_yields_no_segments() -> None:
    assert lib.split_segments("") == []
    assert lib.split_segments("   ") == []


@pytest.mark.parametrize(
    ("command", "marker"),
    [
        ("echo sweep", "sweep.authored"),
        ("ls docs/spec-kitty-issues.md", "register.read"),
        ("touch docs/spec-kitty-issues.md", "register.read"),
        ("gh issue list", "sweep.authored"),
        ("gh issue list --author kent", "sweep.authored"),
        ("gh issue list --state closed --repo Priivacy-ai/spec-kitty", "sweep.recent_closed"),
    ],
)
def test_token_commands_do_not_satisfy_markers(tmp_path: Path, command: str, marker: str) -> None:
    """4b: a marker's pattern must match something only the REAL step produces."""
    session = f"near-miss-{abs(hash(command)) % 10_000}"
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    state, _ = lib.read_session_ledger(session, root=tmp_path)
    assert marker not in state.get("markers", {})
    assert_deny(eval_ledger(session, hooks_root=tmp_path))


# =============================================================================
# F1/F2 — THE REAL WIRE, driven with the shapes a Claude Code Bash call actually has
# =============================================================================
# Nothing above this line would have caught F1 or F2, and neither would more mutations of
# the separator set: the implementation and its tests shared the false premise that
# `shlex` hands back a newline token. These tests drive `mission_lifecycle_gate.py` end to
# end — stdin payload in, wire JSON out — with multi-line and keyword-wrapped commands,
# so the premise is measured instead of assumed. Both directions are covered: the gate
# must DENY the escape, and the marker side must EARN credit for the same shape, because a
# fix to only one of them leaves CP-BEFORE denying forever while telling the agent to run
# the step it just ran.


MULTILINE_GATED = "cd /tmp\nspec-kitty agent mission create --mission x"
MULTILINE_SWEEP = (
    "cd /tmp\ngh issue list --author kent --state all --repo Priivacy-ai/spec-kitty"
)


def test_a_gated_verb_on_a_later_line_reaches_the_checkpoints(tmp_path: Path) -> None:
    """F1 at the wire: ``cd /tmp⏎spec-kitty agent mission create`` used to ALLOW.

    Asserted through the absent-checkpoint seam because reaching the checkpoints IS the
    observable: the dispatcher only consults them once a segment invokes a gated program.
    A denial naming the checkpoint therefore proves the second line was seen as an
    invocation; an allow would prove it was not.
    """
    reason = assert_deny(
        run_gate_with_absent_checkpoint(
            pre_payload("f1-wire", MULTILINE_GATED), hooks_root=tmp_path
        )
    )
    assert "checkpoint" in reason


def test_one_line_and_two_lines_decide_alike(tmp_path: Path) -> None:
    """The single-line twin of the case above. A gate whose answer turns on a line break
    is not a gate, so the two shapes are asserted to reach the same decision."""
    one_line = "cd /tmp && spec-kitty agent mission create --mission x"
    for index, command in enumerate((one_line, MULTILINE_GATED)):
        reason = assert_deny(
            run_gate_with_absent_checkpoint(
                pre_payload(f"f1-symmetry-{index}", command), hooks_root=tmp_path / str(index)
            )
        )
        assert "checkpoint" in reason


@pytest.mark.parametrize(
    "command",
    [
        "{ spec-kitty merge --mission x; }",
        "if true; then spec-kitty merge --mission x; fi",
        "(cd /tmp); spec-kitty merge --mission x",
        "true&&(spec-kitty merge --mission x)",
        "nohup spec-kitty merge --mission x",
    ],
)
def test_keyword_and_glued_punctuation_forms_reach_the_checkpoints(
    tmp_path: Path, command: str
) -> None:
    """F2 at the wire. Every one of these ALLOWED before, and the first four are the
    review's own reproductions."""
    root = tmp_path / str(abs(hash(command)) % 10_000)
    root.mkdir()
    reason = assert_deny(
        run_gate_with_absent_checkpoint(pre_payload("f2-wire", command), hooks_root=root)
    )
    assert "checkpoint" in reason


def test_a_multiline_command_that_invokes_nothing_gated_allows(tmp_path: Path) -> None:
    """PAIRED POSITIVE for F1: splitting on lines must not make every script a denial.

    Without this, an implementation that denied *any* multi-line command would pass every
    F1 test above.
    """
    assert_allow(run_gate(pre_payload("f1-pos", "cd /tmp\ngit status\nls -la"), hooks_root=tmp_path))


def test_a_multiline_quoted_mention_is_not_an_invocation_at_the_wire(tmp_path: Path) -> None:
    """The false positive a naive ``splitlines()`` creates, pinned at the wire.

    Tokenising each physical line in isolation makes ``git commit -m "line one`` an
    unterminated quote, and an untokenisable command DENIES — so the naive fix turns every
    multi-line commit message in this repo into a refusal, and a body that happens to
    mention a gated verb into a refusal that names the wrong reason. A line that will not
    tokenise absorbs the next one instead.
    """
    command = 'git commit -m "fix the gate\n\nspec-kitty merge is only mentioned here"'
    assert_allow(run_gate(pre_payload("f1-quoted", command), hooks_root=tmp_path))


def test_an_unterminated_quote_across_every_line_still_denies(tmp_path: Path) -> None:
    """PAIRED NEGATIVE for the re-join: absorbing lines must not absorb the denial.

    If the rejoining loop swallowed the final tokenisation failure, a mis-quoted command
    would ALLOW — the fail-open direction NFR-001 forbids.
    """
    with pytest.raises(lib.CommandParseError):
        lib.split_segments('echo "a\nspec-kitty merge')
    reason = assert_deny(
        run_gate(pre_payload("f1-unterminated", 'echo "a\nspec-kitty merge'), hooks_root=tmp_path)
    )
    assert "quoting" in reason.lower()


def test_a_pathological_command_cannot_stall_the_tool_call() -> None:
    """The absorb loop is quadratic, so it needs a bound — and this is that bound.

    Found by measuring the fix rather than reading it. A chunk that will not tokenise
    absorbs the next line and re-tokenises from the start, so an unterminated quote near
    the top of a long heredoc costs O(n²): MEASURED at 0.06s for 100 lines, 1.8s for 500
    and **71s for 2000**. A hook that takes 71 seconds is the F5 failure mode wearing a
    different hat — it stalls the tool call it was asked to judge, and this fix would have
    reintroduced it while closing F1.

    Bounded, the answer is a denial, which is where an unterminated quote ends up anyway;
    the cap only decides how soon. Writing a document through a heredoc whose prose
    contains an apostrophe already denied before this change, for the same reason.
    """
    lines = ['echo "unterminated', *[f"some heredoc prose line {i}" for i in range(2_000)]]
    started = time.perf_counter()
    with pytest.raises(lib.CommandParseError):
        lib.split_segments("\n".join(lines))
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0, f"the gate took {elapsed:.1f}s to answer; unbounded it takes ~71s"


def test_a_multiline_quoted_string_within_the_bound_still_resolves() -> None:
    """PAIRED POSITIVE for the cap: absorbing must still work for real multi-line quotes."""
    body = "\n".join(f"line {i}" for i in range(20))
    assert lib.split_segments(f'git commit -m "{body}"\nspec-kitty merge') == [
        ["git", "commit", "-m", body],
        ["spec-kitty", "merge"],
    ]


def test_a_sweep_on_a_later_line_still_marks(tmp_path: Path) -> None:
    """F1's MARKER TWIN — the half that makes the fix survivable.

    F1 broke both sides symmetrically. If only the deny side were fixed, running the sweep
    as a multi-line script would earn nothing, and CP-BEFORE would deny forever while
    telling the agent to run the step it had just run.
    """
    assert_allow(run_gate(post_payload("f1-marker", MULTILINE_SWEEP), hooks_root=tmp_path))
    state, status = lib.read_session_ledger("f1-marker", root=tmp_path)
    assert status is lib.LedgerStatus.OK, "a ledger with a marker in it is OK, not FRESH"
    assert "sweep.authored" in state["markers"], (
        "the sweep ran on line two; before F1 argv[0] was `cd` and the marker was never written"
    )


def test_a_register_read_after_a_line_break_still_marks(tmp_path: Path) -> None:
    """The same twin for the reader allowlist, which reads ``argv[0]`` of each segment."""
    command = "cd /tmp\ncat docs/spec-kitty-issues.md"
    assert_allow(run_gate(post_payload("f1-register", command), hooks_root=tmp_path))
    state, _ = lib.read_session_ledger("f1-register", root=tmp_path)
    assert "register.read" in state["markers"]


def test_a_marker_still_needs_its_own_evidence_across_lines(tmp_path: Path) -> None:
    """PAIRED NEGATIVE for both twins: the line split must not become a free marker.

    ``ls`` names the register without reading it, and a near-miss ``gh issue list`` is
    still a near miss on line two.
    """
    command = "cd /tmp\nls docs/spec-kitty-issues.md\ngh issue list --state all"
    assert_allow(run_gate(post_payload("f1-nearmiss", command), hooks_root=tmp_path))
    state, _ = lib.read_session_ledger("f1-nearmiss", root=tmp_path)
    assert state.get("markers", {}) == {}


# =============================================================================
# T015 — response builders: one wire shape, and only ever "no"
# =============================================================================


def test_allow_writes_nothing(tmp_path: Path) -> None:
    result = run_lib("lib.allow()\n", hooks_root=tmp_path)
    assert_allow(result)


def test_deny_payload_is_single_line_json(tmp_path: Path) -> None:
    result = run_lib("lib.deny('BLOCKED — line one\\nline two\\nline three')\n", hooks_root=tmp_path)
    assert result.stdout.count("\n") == 1
    reason = assert_deny(result)
    assert "\n" in reason, "newlines belong INSIDE the JSON string"


def test_deny_payload_exit_code_is_zero(tmp_path: Path) -> None:
    result = run_lib("lib.deny('BLOCKED — x')\n", hooks_root=tmp_path)
    assert result.returncode == 0, "the JSON carries the decision, not the exit code"


def test_deny_payload_has_no_extra_stdout(tmp_path: Path) -> None:
    """A stray debug print makes the JSON unparseable and THE DENY IS LOST."""
    result = run_lib("lib.deny('BLOCKED — x')\n", hooks_root=tmp_path)
    json.loads(result.stdout)  # consumes the whole of stdout or raises


def test_deny_refuses_to_claim_authority_on_a_non_pretooluse_event(tmp_path: Path) -> None:
    """``permissionDecision`` is PreToolUse-only; ``deny`` must not be talked into faking it."""
    result = run_lib(
        "try:\n"
        "    lib.deny('BLOCKED — x', event='PostToolUseFailure')\n"
        "except ValueError as exc:\n"
        "    print('REFUSED', file=__import__('sys').stderr)\n",
        hooks_root=tmp_path,
    )
    assert result.stdout == "", result.stdout
    assert "REFUSED" in result.stderr


def test_during_checkpoint_never_emits_permission_decision(tmp_path: Path) -> None:
    result = run_lib(
        "lib.additional_context('capture the evidence', event='PostToolUseFailure')\n",
        hooks_root=tmp_path,
    )
    text = assert_context(result, event="PostToolUseFailure")
    assert text == "capture the evidence"
    assert "permissionDecision" not in result.stdout


def test_never_emits_permission_decision_allow() -> None:
    """Silence is the allow. An explicit allow can OVERRIDE another layer's decision.

    Asserted against the source of both new modules, because the failure mode is a future
    edit adding the string, not a current path emitting it.
    """
    emission = re.compile(r"""["']permissionDecision["']\s*:\s*["']allow["']""")
    for module in (HOOKS_DIR / "_hook_lib.py", HOOKS_DIR / "mission_lifecycle_gate.py"):
        assert not emission.search(module.read_text(encoding="utf-8")), module


def test_no_response_this_suite_produces_contains_an_explicit_allow(tmp_path: Path) -> None:
    """The runtime companion to the source scan: every emitted payload, checked."""
    for name, scenario in sorted(DENIAL_SCENARIOS.items()):
        root = tmp_path / name
        root.mkdir()
        assert '"allow"' not in scenario(root).stdout, name


DENIAL_SCENARIOS: dict[str, Callable[[Path], subprocess.CompletedProcess[str]]] = {
    "malformed-payload": lambda root: run_gate(None, hooks_root=root, raw_stdin="{nope"),
    "non-object-payload": lambda root: run_gate(None, hooks_root=root, raw_stdin="[]"),
    "missing-session-id": lambda root: run_gate(
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "x"}},
        hooks_root=root,
    ),
    "missing-tool-input": lambda root: run_gate(
        {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Bash"}, hooks_root=root
    ),
    "unknown-event": lambda root: run_gate(
        pre_payload("s", "spec-kitty status") | {"hook_event_name": "PreToolUseVNext"},
        hooks_root=root,
    ),
    "missing-checkpoint-module": lambda root: run_gate_with_absent_checkpoint(
        pre_payload("s", "spec-kitty merge --mission x"), hooks_root=root
    ),
    "malformed-quoting": lambda root: run_gate(
        pre_payload("s", 'spec-kitty merge --mission "unterminated'), hooks_root=root
    ),
    "fresh-ledger": lambda root: eval_ledger("scenario-fresh", hooks_root=root),
    "corrupt-ledger": lambda root: (
        write_ledger(root, "scenario-corrupt", "{{{"),
        eval_ledger("scenario-corrupt", hooks_root=root),
    )[1],
    "unreadable-ledger": lambda root: (
        (root / "sessions" / "scenario-unreadable.json").mkdir(parents=True, exist_ok=True),
        eval_ledger("scenario-unreadable", hooks_root=root),
    )[1],
}


@pytest.mark.parametrize("name", sorted(DENIAL_SCENARIOS))
def test_every_denial_contains_the_anti_pattern_line(tmp_path: Path, name: str) -> None:
    """4a: the closing block is the only place the reader is told which fix is the real one."""
    reason = assert_deny(DENIAL_SCENARIOS[name](tmp_path))
    assert ANTI_PATTERN_LINE in reason
    assert CLOSING_LIMIT_LINE in reason
    assert "docs/runbooks/autonomous-run-protocol.md" in reason


@pytest.mark.parametrize("name", sorted(DENIAL_SCENARIOS))
def test_every_denial_contains_a_runnable_command(tmp_path: Path, name: str) -> None:
    """FR-009: a denial with no command in it tells the reader nothing they can act on."""
    reason = assert_deny(DENIAL_SCENARIOS[name](tmp_path))
    assert RUNNABLE_LINE_RE.search(reason), f"no runnable line in:\n{reason}"


@pytest.mark.parametrize("name", sorted(DENIAL_SCENARIOS))
def test_every_denial_starts_with_blocked(tmp_path: Path, name: str) -> None:
    reason = assert_deny(DENIAL_SCENARIOS[name](tmp_path))
    assert reason.startswith("BLOCKED — "), reason[:80]


def test_no_denial_quotes_a_credential(tmp_path: Path) -> None:
    """NFR-004 on the RENDERED string, with the secret in the two places it really appears."""
    command = (
        f'GH_TOKEN={FAKE_TOKEN} spec-kitty merge --mission x --body "{FAKE_PASSWORD}"'
    )
    reason = assert_deny(
        run_gate_with_absent_checkpoint(pre_payload("secret-1", command), hooks_root=tmp_path)
    )
    assert FAKE_TOKEN not in reason
    assert FAKE_PASSWORD not in reason
    assert "GH_TOKEN" not in reason


# =============================================================================
# T016 — the dispatcher: two route tables and a fail-closed default
# =============================================================================


def test_an_ungated_command_allows(tmp_path: Path) -> None:
    """PAIRED POSITIVE for the whole dispatcher group.

    Without this, a dispatcher that denied EVERY PreToolUse call would pass every other
    test in this section.
    """
    assert_allow(run_gate(pre_payload("disp-1", "ls -la"), hooks_root=tmp_path))
    assert_allow(run_gate(pre_payload("disp-2", "git status --short"), hooks_root=tmp_path))
    assert_allow(run_gate(pre_payload("disp-3", "pytest tests/hooks"), hooks_root=tmp_path))


def test_a_non_bash_tool_call_allows(tmp_path: Path) -> None:
    payload = {
        "session_id": "disp-4",
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "/repo/README.md"},
        "cwd": str(REPO_ROOT),
    }
    assert_allow(run_gate(payload, hooks_root=tmp_path))


def test_unknown_event_denies(tmp_path: Path) -> None:
    """Fail closed on an event whose authority we cannot know."""
    payload = pre_payload("disp-5", "ls") | {"hook_event_name": "SomeFutureEvent"}
    reason = assert_deny(run_gate(payload, hooks_root=tmp_path))
    assert "event" in reason.lower()


@pytest.mark.parametrize(
    "event", ["SessionStart", "Stop", "SubagentStop", "Notification", "PreCompact", "UserPromptSubmit"]
)
def test_a_known_non_gating_event_emits_nothing(tmp_path: Path, event: str) -> None:
    """PAIRED POSITIVE for the unknown-event deny: the known ones must stay silent."""
    payload = pre_payload("disp-6", "ls") | {"hook_event_name": event}
    assert_allow(run_gate(payload, hooks_root=tmp_path))


def test_missing_checkpoint_module_denies(tmp_path: Path) -> None:
    """A gated command with no checkpoint to consult must DENY, not sail through.

    Safe to land now precisely because wiring is WP08 and lands last: nothing invokes
    this script in anger until WP04/WP05/WP06 supply the checkpoint modules.
    """
    reason = assert_deny(
        run_gate_with_absent_checkpoint(
            pre_payload("disp-7", "spec-kitty merge --mission x"), hooks_root=tmp_path
        )
    )
    assert "checkpoint" in reason.lower()


def test_a_checkpoint_that_abstains_lets_the_call_through(tmp_path: Path) -> None:
    """PAIRED POSITIVE: the seam must be able to say 'not mine', or it is just a deny-all.

    Proven by resolving the seam to a stand-in that abstains, which is exactly the
    contract WP04/WP05/WP06 implement.
    """
    code = (
        "import sys, types\n"
        "from hooks import mission_lifecycle_gate as gate\n"
        "mod = types.ModuleType('stub')\n"
        "mod.evaluate = lambda payload, segments: None\n"
        "gate._load_checkpoint = lambda name: mod\n"
        f"sys.stdin = __import__('io').StringIO({json.dumps(json.dumps(pre_payload('disp-8', 'spec-kitty merge --mission x')))})\n"
        "gate.main([])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=_env(tmp_path)
    )
    assert_allow(result)


def test_a_checkpoint_that_denies_is_relayed_verbatim(tmp_path: Path) -> None:
    code = (
        "import sys, types\n"
        "from hooks import mission_lifecycle_gate as gate\n"
        "mod = types.ModuleType('stub')\n"
        "mod.evaluate = lambda payload, segments: gate.lib.deny('BLOCKED — the stub said no.\\n"
        "  gh issue list --state all\\n' + gate.lib.CLOSING_BLOCK)\n"
        "gate._load_checkpoint = lambda name: mod\n"
        f"sys.stdin = __import__('io').StringIO({json.dumps(json.dumps(pre_payload('disp-9', 'spec-kitty merge --mission x')))})\n"
        "gate.main([])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=_env(tmp_path)
    )
    reason = assert_deny(result)
    assert "the stub said no" in reason


def test_marker_recording_happens_on_ungated_calls(tmp_path: Path) -> None:
    """Recording is NOT gated: a sweep run before any gated command must leave a trace."""
    command = "gh issue list --author kent --state all --repo Priivacy-ai/spec-kitty"
    assert_allow(run_gate(post_payload("rec-1", command), hooks_root=tmp_path))
    state, status = lib.read_session_ledger("rec-1", root=tmp_path)
    assert status is lib.LedgerStatus.OK
    assert "sweep.authored" in state["markers"]
    assert state["markers"]["sweep.authored"]["source_tool"] == "Bash"


def test_reading_the_register_marks_it(tmp_path: Path) -> None:
    assert_allow(
        run_gate(post_read_payload("rec-2", "/repo/docs/spec-kitty-issues.md"), hooks_root=tmp_path)
    )
    state, _ = lib.read_session_ledger("rec-2", root=tmp_path)
    assert "register.read" in state["markers"]
    assert state["markers"]["register.read"]["source_tool"] == "Read"


def test_a_marker_earned_in_the_same_call_does_not_satisfy_that_call(tmp_path: Path) -> None:
    """Review finding F4 — and it is CORRECT, not a bug.

    Markers are written from ``PostToolUse`` (success only), never from ``PreToolUse``
    command text, because text records *intent* rather than *execution* — the defect
    FR-010 removes. So the marker for a step lands on a LATER event than the call that
    performed it, and a single call that both performs a step and trips the gate is
    denied. At the moment the gate evaluates, the step has not yet succeeded.
    """
    session = "f4-same-call"
    command = (
        "gh issue list --author kent --state all --repo Priivacy-ai/spec-kitty "
        "&& spec-kitty agent mission create --handle x"
    )
    # The PreToolUse call records NOTHING...
    assert_deny(run_gate(pre_payload(session, command), hooks_root=tmp_path))
    state, status = lib.read_session_ledger(session, root=tmp_path)
    assert status is lib.LedgerStatus.FRESH, "PreToolUse must not write evidence from intent"

    # ...and the marker appears only once the command has actually SUCCEEDED.
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    state, _ = lib.read_session_ledger(session, root=tmp_path)
    assert "sweep.authored" in state["markers"]


def test_a_failed_command_records_no_marker(tmp_path: Path) -> None:
    """``PostToolUseFailure`` is failure, and a failed sweep is not a sweep."""
    command = "gh issue list --author kent --state all --repo Priivacy-ai/spec-kitty"
    run_gate(failure_payload("rec-3", command), hooks_root=tmp_path)
    state, status = lib.read_session_ledger("rec-3", root=tmp_path)
    assert status is lib.LedgerStatus.FRESH
    assert state.get("markers", {}) == {}


def test_the_during_route_is_not_a_gate(tmp_path: Path) -> None:
    """CP-DURING cannot block. With no checkpoint module it stays SILENT, never denies.

    The fail-closed default is scoped to routes that HAVE deny authority. Denying on a
    ``PostToolUseFailure`` would be C-004's overstatement: the tool has already run.
    """
    result = run_gate(failure_payload("dur-1", "spec-kitty merge --mission x"), hooks_root=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "permissionDecision" not in result.stdout


def test_the_cli_seam_dispatches_when_argv_is_present(tmp_path: Path) -> None:
    """The operator surface is a CLI, not a hook: no hook JSON on stdout, non-zero on error."""
    result = run_gate(None, hooks_root=tmp_path, argv=("fault", "reconcile"), raw_stdin="")
    assert "hookSpecificOutput" not in result.stdout
    assert "permissionDecision" not in result.stdout
    # Today WP06's handler is absent, so the routing ends in usage on stderr. Once it
    # lands this assertion is the durable half: a CLI invocation is never answered with a
    # hook decision.
    if result.returncode != 0:
        assert "usage" in result.stderr.lower()


def test_cli_unknown_subcommand_exits_nonzero_without_hook_json(tmp_path: Path) -> None:
    result = run_gate(None, hooks_root=tmp_path, argv=("definitely-not-a-subcommand",), raw_stdin="")
    assert result.returncode != 0
    assert "hookSpecificOutput" not in result.stdout
    assert "usage" in result.stderr.lower()


def test_the_cli_seam_never_reads_stdin(tmp_path: Path) -> None:
    """A CLI invocation must not be answerable with a hook payload."""
    result = run_gate(
        pre_payload("cli-1", "spec-kitty merge"), hooks_root=tmp_path, argv=("fault", "assert-none")
    )
    assert "permissionDecision" not in result.stdout


# =============================================================================
# NFR-002 — the module docstrings must record what a reader will otherwise "correct" back
# =============================================================================


@pytest.mark.parametrize(
    "needle",
    [
        "upstream_filing_guard",  # what is being extended
        "NFR-001",  # and what is being diverged from
        "git-common-dir",  # the ledger-root divergence
        "session-ledger.md",  # named, so the orchestrator can reconcile
        "heredoc",  # the explicit tie-break
        "false negative",  # the residual command-matching gap
        "newline",  # DIVERGENCE 3: the boundary shlex never emits a token for
    ],
)
def test_the_library_docstring_records_its_divergences(needle: str) -> None:
    """An undocumented divergence from a 'proven pattern' is what the next reader reverts."""
    doc = lib.__doc__ or ""
    assert needle in doc, f"the module docstring does not mention {needle!r}"


@pytest.mark.parametrize(
    "needle",
    ["a step ran", "cannot prove", "CP-DURING is not a gate", "WP08"],
)
def test_the_dispatcher_docstring_states_what_it_cannot_prove(needle: str) -> None:
    from hooks import mission_lifecycle_gate as gate

    doc = gate.__doc__ or ""
    assert needle in doc, f"the dispatcher docstring does not mention {needle!r}"


def test_nothing_claims_the_during_checkpoint_enforces() -> None:
    """C-004. ``PostToolUseFailure`` cannot block, so no surface may imply that it does."""
    from hooks import mission_lifecycle_gate as gate

    for doc in (lib.__doc__ or "", gate.__doc__ or ""):
        lowered = doc.lower()
        for claim in ("cp-during enforces", "cp-during blocks", "during checkpoint blocks"):
            assert claim not in lowered
