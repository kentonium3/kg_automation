r"""Tests for ``scripts/hooks/checkpoints/before.py`` — the §0 sweep-evidence gate.

WHY THIS MODULE IS SHAPED THE WAY IT IS
---------------------------------------
Two of its tests are the reason the work package exists, and the rest support them.

**T022 — a MENTION must not mark.** The defect this checkpoint is built to avoid is a
marker set by a command that never did the work. ``echo "gh issue list …"`` did the sweep
in no sense whatsoever; if it marks, the gate manufactures a green nobody earned, inside
the mechanism built to stop exactly that.

**T023 — a mission that skipped the sweep is SHOWN refused.** The mission's headline
success criterion is a demonstration, not "the tests pass".

THE FAIL-CLOSED TRAP, AND HOW IT IS ANSWERED HERE
-------------------------------------------------
Every failure path of this gate denies, so a suite made only of deny assertions is
worthless: a checkpoint whose whole body was ``lib.deny("no")`` would pass all of them.
Every deny group below is therefore **paired with a positive that must still allow**, and
the pairs were shown to move independently under mutation. Docstrings marked ``PAIRED
POSITIVE`` are not decoration — removing one does not weaken a deny test, it removes the
only evidence that the deny tests distinguish anything.

DRIVING THE REAL WIRE
---------------------
WP03 was rejected once for a reason this module has to answer: *mutation testing cannot
detect a false premise shared by the implementation and its tests.* Fifty-two mutations of
a separator set all survived because both sides believed ``shlex`` emits a newline token,
and it does not. More in-process variations of the same assumption would have found
nothing.

So the load-bearing assertions here run a **subprocess** reading a real JSON payload on
stdin and writing a real decision to stdout, and the commands they carry are **multi-line**
— the shape a Claude Code Bash call actually has. Direct calls are used only where a
subprocess would obscure which assertion failed.

Two subprocess harnesses, for one ownership reason:

* :func:`run_gate` invokes ``mission_lifecycle_gate.py`` itself. Used for every
  ``PostToolUse`` route, which consults no checkpoint at all.
* :func:`run_before` drives the same dispatcher with ``PRE_TOOL_CHECKPOINTS`` narrowed to
  ``('before',)``. The dispatcher consults ``after`` first, and ``after`` is **WP06's**
  file: asserting through it would make this module's results depend on a file this work
  package neither owns nor can see. Narrowing is the same device WP03 used in the opposite
  direction, and for the same reason.

ISOLATION
---------
The ledger root is redirected with ``SPEC_KITTY_HOOKS_ROOT``, an explicit seam rather than
a monkeypatched private. ``test_the_ledger_lands_under_the_env_override`` proves the
redirect takes effect **before** any other result here is believed: without it, an allow
in this module could be an allow inherited from the real
``<git-common-dir>/spec-kitty-hooks/``. Every test also uses a session id of its own.
Nothing here touches the network, invokes ``spec-kitty`` or ``gh``, or writes outside
``tmp_path``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from hooks import _hook_lib as lib

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
GATE = SCRIPTS_DIR / "hooks" / "mission_lifecycle_gate.py"

# --- literals asserted against RENDERED output, never imported from the module ---------
# A test that finds a module's own constant in that module's own output has checked
# nothing. These are typed out again on purpose.
ANTI_PATTERN_LINE = "never by adding a token command"
RUNNABLE_LINE_RE = re.compile(r"^\s*(gh|spec-kitty|python|\.venv/bin)\b", re.MULTILINE)

#: FR-011 spelled out, in the order a denial reports them. Typed out rather than imported
#: from ``lib.MARKER_ORDER`` for the same reason: a gate that shrank would otherwise shrink
#: this expectation with it.
REQUIRED_MARKERS = (
    "sweep.authored",
    "sweep.recent_closed",
    "sweep.register_refs",
    "register.read",
)

#: The REAL command for each marker — what an agent that actually ran §0 would have run.
#: Fed as a successful ``PostToolUse``, each of these must set its own marker and no other.
REAL_SWEEP_COMMANDS: dict[str, str] = {
    "sweep.authored": (
        "gh issue list --repo Priivacy-ai/spec-kitty --author kentonium3 --state all "
        "--limit 100 --json number,state,title,closedAt"
    ),
    "sweep.recent_closed": (
        "gh issue list --repo Priivacy-ai/spec-kitty --state closed --limit 100 "
        '--search "closed:>=2026-08-01" --json number,title,closedAt'
    ),
    "sweep.register_refs": (
        "gh issue view 3728 --repo Priivacy-ai/spec-kitty --json state,title "
        "# cross-checking the refs docs/spec-kitty-issues.md cites"
    ),
    "register.read": "cat docs/spec-kitty-issues.md",
}

GATED_CREATE = "spec-kitty agent mission create --mission mission-lifecycle-gate-01M0VRDZ"


# =============================================================================
# Harness
# =============================================================================


def _env(hooks_root: Path) -> dict[str, str]:
    env = {**os.environ, "SPEC_KITTY_HOOKS_ROOT": str(hooks_root)}
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SCRIPTS_DIR), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
    )
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


def run_before(
    payload: Any, *, hooks_root: Path, setup: str = "", raw_stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Drive the real dispatcher with CP-BEFORE as the only checkpoint consulted.

    Real stdin, real stdout, real exit code, real tokeniser, real ledger IO — everything
    except WP06's ``after`` module, which this work package does not own and cannot assume
    the shape of.

    ``setup`` is executed in the child before the payload is dispatched. It exists for the
    two conditions that cannot be produced from outside the process — an unpredicted
    exception, and proving that no socket is opened — and for nothing else.
    """
    stdin = raw_stdin if raw_stdin is not None else json.dumps(payload)
    code = (
        "import io, sys\n"
        "from hooks import mission_lifecycle_gate as gate\n"
        "from hooks import _hook_lib as lib\n"
        "from hooks.checkpoints import before\n"
        "gate.PRE_TOOL_CHECKPOINTS = ('before',)\n"
        + setup
        + f"sys.stdin = io.StringIO({json.dumps(stdin)})\n"
        "gate.main([])\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=_env(hooks_root)
    )


def pre_payload(session_id: str, command: str, **extra: Any) -> dict[str, Any]:
    """A ``PreToolUse`` payload in the shape MEASURED on Claude Code 2.1.231.

    Keys captured live from a probe hook, not copied out of documentation: ``cwd``,
    ``effort``, ``hook_event_name``, ``permission_mode``, ``prompt_id``, ``session_id``,
    ``tool_input``, ``tool_name``, ``tool_use_id``, ``transcript_path``. The command is at
    ``tool_input.command``; there is no ``inputs`` key and no ``response`` key.
    """
    payload = {
        "session_id": session_id,
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command, "description": "a tool call"},
        "cwd": str(REPO_ROOT),
        "tool_use_id": "toolu_test",
        "permission_mode": "bypassPermissions",
        "transcript_path": "/dev/null",
    }
    payload.update(extra)
    return payload


def post_payload(session_id: str, command: str, **extra: Any) -> dict[str, Any]:
    """A successful ``PostToolUse``. MEASURED: it adds ``duration_ms`` and ``tool_response``
    to the ``PreToolUse`` shape and changes nothing else."""
    payload = pre_payload(session_id, command, **extra)
    payload["hook_event_name"] = "PostToolUse"
    payload["duration_ms"] = 12
    payload["tool_response"] = {
        "interrupted": False,
        "isImage": False,
        "noOutputExpected": False,
        "stdout": "",
        "stderr": "",
    }
    return payload


def post_read_payload(session_id: str, file_path: str) -> dict[str, Any]:
    """MEASURED: a ``Read`` ``PostToolUse`` carries ``tool_input.file_path`` and a
    ``tool_response`` of ``{"file": …, "type": …}``."""
    return {
        "session_id": session_id,
        "hook_event_name": "PostToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": file_path},
        "tool_response": {"type": "text", "file": {}},
        "duration_ms": 3,
        "cwd": str(REPO_ROOT),
        "tool_use_id": "toolu_test",
    }


def assert_allow(result: subprocess.CompletedProcess[str]) -> None:
    """Allow is *silence*: exit 0 and nothing on stdout.

    Every path exits 0, so an exit-code-only assertion cannot tell an allow from a denial.
    """
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", f"expected an allow (empty stdout), got: {result.stdout!r}"


def assert_deny(result: subprocess.CompletedProcess[str]) -> str:
    """Assert the whole wire contract of a denial, and return the reason."""
    assert result.returncode == 0, f"exit {result.returncode}; stderr={result.stderr}"
    assert result.stdout, "expected a denial payload on stdout, got nothing"
    assert result.stdout.endswith("\n")
    newlines = result.stdout.count("\n")
    assert newlines == 1, (
        f"the payload must be ONE physical line; got {newlines} newlines: {result.stdout!r}"
    )
    payload = json.loads(result.stdout)
    specific = payload["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "deny"
    reason = specific["permissionDecisionReason"]
    assert isinstance(reason, str) and reason
    return reason


def markers_on_disk(session_id: str, hooks_root: Path) -> dict[str, Any]:
    """Read the ledger FILE. Never a return value — a recorder that reports what it did
    not write is exactly the shape under test."""
    path = hooks_root / "sessions" / f"{lib.safe_component(session_id)}.json"
    if not path.exists():
        return {}
    state = json.loads(path.read_text(encoding="utf-8"))
    markers = state.get("markers")
    return markers if isinstance(markers, dict) else {}


def satisfy(session_id: str, hooks_root: Path, *markers: str) -> None:
    """Earn ``markers`` the only way they can be earned: run the real command and succeed.

    Deliberately NOT a hand-written ledger file. A test that fabricates the evidence it
    then checks for has tested its own fixture.
    """
    for marker in markers:
        assert_allow(run_gate(post_payload(session_id, REAL_SWEEP_COMMANDS[marker]),
                              hooks_root=hooks_root))
    written = markers_on_disk(session_id, hooks_root)
    for marker in markers:
        assert marker in written, f"{marker} was not earned by its own real command"


# =============================================================================
# The isolation seam — proven before any other result here is believed
# =============================================================================


def test_the_ledger_lands_under_the_env_override(tmp_path: Path) -> None:
    """Without this, an allow in this module could be inherited from the real ledger."""
    assert_allow(run_gate(post_payload("iso-1", REAL_SWEEP_COMMANDS["register.read"]),
                          hooks_root=tmp_path))
    assert (tmp_path / "sessions" / "iso-1.json").is_file(), (
        "SPEC_KITTY_HOOKS_ROOT did not take effect; every isolation claim below is void"
    )


# =============================================================================
# T022 — a MENTION is not an INVOCATION. This is the work package's reason to exist.
# =============================================================================

#: Each row: a command that a substring matcher would mark on, the marker it must NOT set,
#: and why it is not evidence.
NEAR_MISSES: tuple[tuple[str, str, str], ...] = (
    (
        'echo "gh issue list --author kentonium3 --state all --repo Priivacy-ai/spec-kitty"',
        "sweep.authored",
        "argv[0] is echo; the whole gated phrase is ONE argument",
    ),
    (
        "echo 'gh issue list --state closed --search \"closed:>=2026-08-01\"'",
        "sweep.recent_closed",
        "single-quoted, still one argument to echo",
    ),
    (
        "printf '%s\\n' \"gh issue view 3728 --repo Priivacy-ai/spec-kitty --json state\"",
        "sweep.register_refs",
        "printf fakes echo equally well, which is why the reader list is an allowlist",
    ),
    (
        "ls docs/spec-kitty-issues.md",
        "register.read",
        "ls names the path without reading a byte of it",
    ),
    (
        "touch docs/spec-kitty-issues.md",
        "register.read",
        "touch writes the mtime and reads nothing",
    ),
    (
        "gh-fake issue list --author kentonium3 --state all --repo Priivacy-ai/spec-kitty",
        "sweep.authored",
        "a different program wearing the sweep's exact shape queried nothing upstream",
    ),
)


@pytest.mark.parametrize("command,marker,why", NEAR_MISSES, ids=[r[1] + "-" + r[0][:12] for r in NEAR_MISSES])
def test_a_near_miss_command_sets_no_marker(
    tmp_path: Path, command: str, marker: str, why: str
) -> None:
    """T022. Asserted TWO ways, because they fail differently.

    The ledger on disk must not contain the marker, **and** a subsequent ``mission create``
    must still be refused naming it. The first catches a recorder that marked; the second
    catches a gate that would have been satisfied anyway.
    """
    session = f"near-{marker}-{abs(hash(command)) % 10_000}"
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))

    assert marker not in markers_on_disk(session, tmp_path), (
        f"{command!r} set {marker} on disk — {why}"
    )

    reason = assert_deny(run_before(pre_payload(session, GATED_CREATE), hooks_root=tmp_path))
    assert marker in reason, f"the denial must still name {marker} as missing"


@pytest.mark.parametrize("marker", REQUIRED_MARKERS)
def test_the_real_command_does_set_its_marker(tmp_path: Path, marker: str) -> None:
    """PAIRED POSITIVE for the whole near-miss table.

    Without this, a recorder that marks NOTHING AT ALL passes every row above — and would
    then deny every mission forever while telling the agent to run a step it had run.
    """
    session = f"real-{marker}"
    assert_allow(run_gate(post_payload(session, REAL_SWEEP_COMMANDS[marker]), hooks_root=tmp_path))
    assert marker in markers_on_disk(session, tmp_path), (
        f"the real §0 command for {marker} earned nothing"
    )


def test_a_gh_call_missing_its_own_distinguishing_flags_marks_nothing(tmp_path: Path) -> None:
    """A real ``gh issue list`` that is not either sweep query is not either sweep query."""
    command = "gh issue list --repo Priivacy-ai/spec-kitty"
    assert_allow(run_gate(post_payload("bare-gh", command), hooks_root=tmp_path))
    assert markers_on_disk("bare-gh", tmp_path) == {}


def test_a_commented_out_sweep_marks_nothing(tmp_path: Path) -> None:
    """``: # gh issue list …`` runs the null command and succeeds. It swept nothing."""
    command = ": # gh issue list --author kentonium3 --state all --repo Priivacy-ai/spec-kitty"
    assert_allow(run_gate(post_payload("noop-gh", command), hooks_root=tmp_path))
    assert markers_on_disk("noop-gh", tmp_path) == {}


def test_the_real_sweep_as_PreToolUse_marks_nothing(tmp_path: Path) -> None:
    """T022's SECOND AXIS (FR-010b), and argv parsing does not cover it.

    ⚠ **This test does NOT reach CP-BEFORE, and on its own it proves less than its name
    suggests.** The dispatcher discards any command with no ``spec-kitty`` segment before a
    checkpoint is consulted, so what is pinned here is the pre-filter. It survived the mutant
    that recorded markers from intent. The assertion that actually covers FR-010b's second
    axis is ``test_a_pretooluse_payload_cannot_self_satisfy_the_ledger`` at the end of this
    module — keep this as the paired dispatcher-level check, not as the FR-010b evidence.

    Token matching would mark from ``PreToolUse`` text just as happily as from
    ``PostToolUse`` text — the two mechanisms are independent, so they need independent
    tests. ``PreToolUse`` records INTENT: the command may be denied, may crash, may never
    run. Only ``PostToolUse`` fires after a tool completes successfully.
    """
    for marker in REQUIRED_MARKERS:
        assert_allow(run_before(pre_payload("intent", REAL_SWEEP_COMMANDS[marker]),
                                hooks_root=tmp_path))
    assert markers_on_disk("intent", tmp_path) == {}, (
        "PreToolUse wrote evidence from intent; a command that never ran earned a marker"
    )

    reason = assert_deny(run_before(pre_payload("intent", GATED_CREATE), hooks_root=tmp_path))
    for marker in REQUIRED_MARKERS:
        assert marker in reason


def test_a_multiline_mention_at_the_wire_marks_nothing(tmp_path: Path) -> None:
    """The premise-testing form: a MULTI-LINE command, through the real wire.

    A line break is the default shape of a Claude Code Bash call, and it was a complete
    escape until WP03's F1 fix. Both directions matter here: the mention on line three must
    not mark, and the paired positive below shows the real command on line three does.
    """
    command = (
        "cd /tmp\n"
        "echo 'about to check the queue'\n"
        'echo "gh issue list --repo Priivacy-ai/spec-kitty --author kentonium3 --state all"\n'
        "ls docs/spec-kitty-issues.md"
    )
    assert_allow(run_gate(post_payload("multi-miss", command), hooks_root=tmp_path))
    assert markers_on_disk("multi-miss", tmp_path) == {}


def test_a_multiline_real_sweep_at_the_wire_marks_every_step(tmp_path: Path) -> None:
    """PAIRED POSITIVE at the wire, multi-line: all four earned in ONE Bash call."""
    command = "cd /repo\n" + "\n".join(REAL_SWEEP_COMMANDS[m] for m in REQUIRED_MARKERS)
    assert_allow(run_gate(post_payload("multi-real", command), hooks_root=tmp_path))
    assert sorted(markers_on_disk("multi-real", tmp_path)) == sorted(REQUIRED_MARKERS)


# =============================================================================
# T023 — SC-001: a mission that skipped the sweep is SHOWN refused
# =============================================================================


def test_a_mission_create_with_no_sweep_evidence_is_refused(tmp_path: Path) -> None:
    """T023, the mission's headline success criterion, as a demonstration.

    Fresh session, no evidence, ``spec-kitty agent mission create`` → a well-formed denial
    naming all four missing steps, each with something runnable. Then the same payload,
    after the four steps have actually been run, → silence.
    """
    session = "sc-001"
    assert not (tmp_path / "sessions" / f"{session}.json").exists()

    result = run_before(pre_payload(session, GATED_CREATE), hooks_root=tmp_path)
    reason = assert_deny(result)

    for marker in REQUIRED_MARKERS:
        assert marker in reason, f"the denial does not name {marker}"
    assert RUNNABLE_LINE_RE.search(reason), "the denial carries nothing the reader can run"
    assert ANTI_PATTERN_LINE in reason
    assert "Already satisfied" not in reason, "nothing was satisfied; do not claim otherwise"

    # A read must never create state: the gate would be manufacturing its own evidence
    # store on the way to deciding it has none.
    assert not (tmp_path / "sessions" / f"{session}.json").exists()

    satisfy(session, tmp_path, *REQUIRED_MARKERS)
    assert_allow(run_before(pre_payload(session, GATED_CREATE), hooks_root=tmp_path))


@pytest.mark.parametrize("omitted", REQUIRED_MARKERS)
def test_three_of_four_markers_is_still_a_refusal(tmp_path: Path, omitted: str) -> None:
    """FR-011 executed four ways: no single query stands in for the sweep.

    This is the conjunction. If the gate were an ``any()``, every row here would allow.
    The denial must name the one that is missing AND list the three already satisfied —
    that difference is what the message is for.
    """
    session = f"partial-{omitted}"
    present = [m for m in REQUIRED_MARKERS if m != omitted]
    satisfy(session, tmp_path, *present)

    reason = assert_deny(run_before(pre_payload(session, GATED_CREATE), hooks_root=tmp_path))
    assert omitted in reason.split("Already satisfied")[0], (
        f"the denial must name {omitted} as MISSING, not merely mention it"
    )
    satisfied_line = reason.split("Already satisfied this session: ")[1].splitlines()[0]
    for marker in present:
        assert marker in satisfied_line, f"{marker} was earned but is not reported as satisfied"
    assert omitted not in satisfied_line


# =============================================================================
# T020 — which verbs this checkpoint gates, by token POSITION
# =============================================================================

#: Commands that BEGIN a mission. Every one of these must be refused by a session with no
#: evidence. The last two are the shapes a naive matcher loses: a chained invocation, and
#: a line break — which is the default shape of a Claude Code Bash call.
GATED_COMMANDS: tuple[str, ...] = (
    "spec-kitty agent mission create --mission demo",
    "spec-kitty mission create --ticket SPE-123",
    "spec-kitty specify",
    "cd /repo && spec-kitty agent mission create --mission demo",
    "cd /repo\nspec-kitty specify --from-brief brief.md",
)

#: Commands that do NOT begin a mission, and are the paired positives for the table above.
#: ``agent mission merge`` belongs to CP-AFTER; a merge refused for missing sweep evidence
#: would name the wrong step. The ``merge-driver-*`` family is what a regex anchored on
#: ``\bmerge\b`` false-positives on. ``echo`` is the whole point of token matching.
UNGATED_COMMANDS: tuple[str, ...] = (
    "spec-kitty status",
    "spec-kitty agent mission merge --mission demo",
    "spec-kitty merge-driver-meta a b c",
    'echo "spec-kitty agent mission create"',
    "spec-kitty next --mission demo",
    # The rows that only a TOKEN matcher survives. A mention alone never reaches this
    # checkpoint — the dispatcher filters it out before consulting anyone — so the mention
    # has to travel alongside a real `spec-kitty` segment to be observable at all.
    'spec-kitty status && echo "spec-kitty specify"',
    "spec-kitty status\necho 'spec-kitty agent mission create'",
)


@pytest.mark.parametrize("command", GATED_COMMANDS)
def test_a_mission_start_without_evidence_is_refused(tmp_path: Path, command: str) -> None:
    session = f"gated-{abs(hash(command)) % 10_000}"
    reason = assert_deny(run_before(pre_payload(session, command), hooks_root=tmp_path))
    assert "upstream-sweep evidence" in reason


@pytest.mark.parametrize("command", UNGATED_COMMANDS)
def test_a_command_that_begins_no_mission_allows(tmp_path: Path, command: str) -> None:
    """PAIRED POSITIVE for the gated table.

    Without this, a checkpoint that refused EVERY ``spec-kitty`` call would pass every row
    above — and would make the CLI unusable while looking like a working gate.
    """
    session = f"ungated-{abs(hash(command)) % 10_000}"
    assert_allow(run_before(pre_payload(session, command), hooks_root=tmp_path))


def test_the_same_gated_command_allows_once_the_evidence_exists(tmp_path: Path) -> None:
    """The second paired positive: gating is about the EVIDENCE, not about the verb."""
    session = "gated-then-allowed"
    assert_deny(run_before(pre_payload(session, GATED_CREATE), hooks_root=tmp_path))
    satisfy(session, tmp_path, *REQUIRED_MARKERS)
    for command in GATED_COMMANDS:
        assert_allow(run_before(pre_payload(session, command), hooks_root=tmp_path))


def test_gating_is_by_token_position_not_by_substring() -> None:
    """Direct calls, where a subprocess would obscure which row failed."""
    from hooks.checkpoints import before

    assert before.gates_a_mission_start(["spec-kitty", "agent", "mission", "create"])
    assert before.gates_a_mission_start(["/usr/local/bin/spec-kitty", "specify"])
    assert before.gates_a_mission_start(["spec-kitty", "--json", "specify"])
    assert not before.gates_a_mission_start(["echo", "spec-kitty agent mission create"])
    assert not before.gates_a_mission_start(["spec-kitty", "merge-driver-meta", "a"])
    assert not before.gates_a_mission_start(["spec-kitty", "agent", "mission", "merge"])
    assert not before.gates_a_mission_start([])


# =============================================================================
# T021 — the denial names the step and how to run it (FR-009), and the four causes
# are four DIFFERENT texts
# =============================================================================


def write_ledger(session_id: str, hooks_root: Path, state: Any) -> Path:
    """Fabricate a ledger. Used ONLY for the failure modes, where the broken file IS the
    condition under test — never to manufacture evidence a test then checks for."""
    path = hooks_root / "sessions" / f"{lib.safe_component(session_id)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state if isinstance(state, str) else json.dumps(state), encoding="utf-8")
    return path


def valid_marker() -> dict[str, Any]:
    return {"first_seen_at": "2026-08-25T00:00:00Z", "count": 1, "source_tool": "Bash"}


def fresh_reason(tmp_path: Path) -> str:
    return assert_deny(run_before(pre_payload("cause-fresh", GATED_CREATE), hooks_root=tmp_path))


def corrupt_reason(tmp_path: Path) -> str:
    write_ledger("cause-corrupt", tmp_path, "{not json at all")
    return assert_deny(run_before(pre_payload("cause-corrupt", GATED_CREATE), hooks_root=tmp_path))


def unreadable_reason(tmp_path: Path) -> str:
    path = write_ledger("cause-unreadable", tmp_path, {"schema": "x", "markers": {}})
    path.chmod(0o000)
    try:
        return assert_deny(
            run_before(pre_payload("cause-unreadable", GATED_CREATE), hooks_root=tmp_path)
        )
    finally:
        path.chmod(0o600)


def no_session_reason(tmp_path: Path) -> str:
    payload = pre_payload("ignored", GATED_CREATE)
    del payload["session_id"]
    return assert_deny(run_before(payload, hooks_root=tmp_path))


def test_the_four_causes_produce_four_distinct_texts(tmp_path: Path) -> None:
    """FRESH and CORRUPT both refuse, and collapsing them is tempting and wrong.

    *"You have not run the sweep"* sends the reader to do the right thing. *"Your ledger is
    corrupt"* sends it to delete a file. Emitting the first for the second wastes a sweep
    and leaves the corrupt file in place to refuse again.
    """
    reasons = {
        "FRESH": fresh_reason(tmp_path),
        "CORRUPT": corrupt_reason(tmp_path),
        "UNREADABLE": unreadable_reason(tmp_path),
        "NO_SESSION": no_session_reason(tmp_path),
    }
    headlines = {name: text.splitlines()[0] for name, text in reasons.items()}
    assert len(set(headlines.values())) == 4, f"causes share a headline: {headlines}"

    assert "upstream-sweep evidence" in reasons["FRESH"]
    assert "corrupt" in reasons["CORRUPT"] and "rm " in reasons["CORRUPT"]
    assert "could not be read" in reasons["UNREADABLE"]
    assert "not a missing step" in reasons["UNREADABLE"], (
        "an unreadable ledger must not read as a step the agent skipped"
    )
    assert "session_id" in reasons["NO_SESSION"]


@pytest.mark.parametrize("cause", ["FRESH", "CORRUPT", "UNREADABLE", "NO_SESSION"])
def test_every_denial_carries_something_runnable_and_the_verbatim_closing_block(
    tmp_path: Path, cause: str
) -> None:
    """FR-009. A denial the reader cannot act on has named a step and nothing else."""
    reason = {
        "FRESH": fresh_reason,
        "CORRUPT": corrupt_reason,
        "UNREADABLE": unreadable_reason,
        "NO_SESSION": no_session_reason,
    }[cause](tmp_path)
    assert RUNNABLE_LINE_RE.search(reason), f"{cause} carries no runnable line:\n{reason}"
    assert ANTI_PATTERN_LINE in reason
    assert "docs/runbooks/autonomous-run-protocol.md" in reason


def test_the_fresh_denial_names_the_query_that_produces_each_missing_step(
    tmp_path: Path,
) -> None:
    """FR-009's substance: *which* step, and the query that earns it — never a generic
    refusal that sends the agent to guess."""
    reason = assert_deny(run_before(pre_payload("fr009", GATED_CREATE), hooks_root=tmp_path))
    assert "gh issue list" in reason
    assert "--author" in reason
    assert "--state closed" in reason
    assert "gh issue view" in reason
    assert "docs/spec-kitty-issues.md" in reason


def test_no_denial_ever_carries_an_explicit_allow(tmp_path: Path) -> None:
    """``contracts/denial-payload.md`` §2: silence is the allow.

    An explicit affirmative decision from a hook can OVERRIDE a decision another layer
    would have made. This gate is only ever entitled to say no.
    """
    result = run_before(pre_payload("never-allow", GATED_CREATE), hooks_root=tmp_path)
    assert '"allow"' not in result.stdout
    assert_allow(run_before(pre_payload("never-allow-2", "spec-kitty status"), hooks_root=tmp_path))


# --- NFR-004 ---------------------------------------------------------------------------

FAKE_TOKEN = "ghp_notarealtokennotarealtokennotareal"
FAKE_PASSWORD = "password=hunter2"


def test_no_payload_content_reaches_the_rendered_reason(tmp_path: Path) -> None:
    """NFR-004, asserted on the RENDERED string rather than on the template.

    The probes are deliberately *shaped* like the real thing: this failure mode is about
    the field an assertion forgot, so a probe that looks nothing like a credential proves
    nothing.
    """
    command = (
        f"GH_TOKEN={FAKE_TOKEN} spec-kitty agent mission create --mission demo "
        f'--body "{FAKE_PASSWORD}"'
    )
    reason = assert_deny(run_before(pre_payload("secret-1", command), hooks_root=tmp_path))
    assert FAKE_TOKEN not in reason
    assert "hunter2" not in reason
    assert "GH_TOKEN" not in reason
    assert "--body" not in reason
    # PAIRED POSITIVE: a redactor that emptied the message would pass the four asserts
    # above and tell the reader nothing.
    for marker in REQUIRED_MARKERS:
        assert marker in reason


def test_a_credential_in_a_command_never_reaches_the_ledger(tmp_path: Path) -> None:
    """The other sink. A marker holds ``first_seen_at``, ``count`` and ``source_tool`` —
    no command text, no argument values, no paths."""
    command = (
        f"GH_TOKEN={FAKE_TOKEN} gh issue list --repo Priivacy-ai/spec-kitty "
        "--author kentonium3 --state all"
    )
    assert_allow(run_gate(post_payload("secret-2", command), hooks_root=tmp_path))
    on_disk = (tmp_path / "sessions" / "secret-2.json").read_text(encoding="utf-8")
    assert "sweep.authored" in on_disk
    assert FAKE_TOKEN not in on_disk
    assert "Priivacy-ai" not in on_disk


# =============================================================================
# NFR-001 — every failure resolves toward DENY, each shown, each paired
# =============================================================================


def test_an_unparseable_payload_denies(tmp_path: Path) -> None:
    assert_deny(run_before(None, hooks_root=tmp_path, raw_stdin="{not json"))


def test_a_payload_with_no_tool_input_denies(tmp_path: Path) -> None:
    payload = pre_payload("nfr-tool-input", GATED_CREATE)
    del payload["tool_input"]
    reason = assert_deny(run_before(payload, hooks_root=tmp_path))
    assert "tool_input" in reason


def test_a_ledger_whose_schema_is_unrecognised_denies_as_corrupt(tmp_path: Path) -> None:
    """A schema this build cannot interpret is not an empty ledger. Reading it as one would
    hand the next call a clean pass over a file nobody can vouch for."""
    write_ledger(
        "nfr-schema",
        tmp_path,
        {"schema": "spec-kitty-qa/session-ledger@99", "markers": {m: valid_marker() for m in REQUIRED_MARKERS}},
    )
    reason = assert_deny(run_before(pre_payload("nfr-schema", GATED_CREATE), hooks_root=tmp_path))
    assert "corrupt" in reason


def test_a_ledger_whose_markers_are_not_an_object_denies(tmp_path: Path) -> None:
    write_ledger(
        "nfr-markers",
        tmp_path,
        {"schema": "spec-kitty-qa/session-ledger@1", "markers": ["sweep.authored"]},
    )
    reason = assert_deny(run_before(pre_payload("nfr-markers", GATED_CREATE), hooks_root=tmp_path))
    assert "corrupt" in reason


def test_a_single_malformed_marker_counts_as_ABSENT_and_the_rest_stay_valid(
    tmp_path: Path,
) -> None:
    """The row that distinguishes "one bad value" from "the whole file is unusable".

    A malformed marker can never satisfy a gate, but it must not condemn the ledger: the
    refusal is the FRESH-class *you have not run this step* text naming that one marker,
    and the other three must still be reported as satisfied.
    """
    markers = {m: valid_marker() for m in REQUIRED_MARKERS}
    markers["sweep.register_refs"] = {"first_seen_at": 17, "count": "many"}
    write_ledger(
        "nfr-one-bad",
        tmp_path,
        {"schema": "spec-kitty-qa/session-ledger@1", "markers": markers},
    )
    reason = assert_deny(run_before(pre_payload("nfr-one-bad", GATED_CREATE), hooks_root=tmp_path))
    assert "corrupt" not in reason, "one bad marker is not a corrupt ledger"
    assert "upstream-sweep evidence" in reason
    head, satisfied = reason.split("Already satisfied this session: ")
    assert "sweep.register_refs" in head
    assert "sweep.register_refs" not in satisfied.splitlines()[0]
    for marker in ("sweep.authored", "sweep.recent_closed", "register.read"):
        assert marker in satisfied.splitlines()[0]


def test_an_unhandled_exception_denies_naming_only_the_exception_CLASS(tmp_path: Path) -> None:
    """The message of an exception can quote payload content, and payload content can carry
    a credential. Only the class name may be reported."""
    setup = (
        "def _boom(*a, **k):\n"
        f"    raise RuntimeError('leaked {FAKE_TOKEN}')\n"
        "lib.evaluate_session_ledger = _boom\n"
    )
    reason = assert_deny(
        run_before(pre_payload("nfr-boom", GATED_CREATE), hooks_root=tmp_path, setup=setup)
    )
    assert "RuntimeError" in reason
    assert FAKE_TOKEN not in reason


def test_a_command_that_will_not_tokenise_denies(tmp_path: Path) -> None:
    reason = assert_deny(
        run_before(
            pre_payload("nfr-quote", 'spec-kitty agent mission create --mission "unterminated'),
            hooks_root=tmp_path,
        )
    )
    assert "quoting" in reason.lower()


def test_a_well_formed_payload_with_full_evidence_still_allows(tmp_path: Path) -> None:
    """PAIRED POSITIVE for the entire NFR-001 group.

    Every test above passes trivially against a checkpoint whose whole body is a refusal.
    This is the only thing in the group that does not.
    """
    session = "nfr-positive"
    satisfy(session, tmp_path, *REQUIRED_MARKERS)
    assert_allow(run_before(pre_payload(session, GATED_CREATE), hooks_root=tmp_path))


def test_no_socket_is_opened_on_a_gated_path(tmp_path: Path) -> None:
    """NFR-003's absolute: never a network call on a gated path.

    A gate that reached the network would stall the tool call it was asked to judge the
    first time GitHub was slow, and would turn an outage into a refusal.
    """
    setup = (
        "import socket\n"
        "def _no_socket(*a, **k):\n"
        "    raise AssertionError('the gate opened a socket')\n"
        "socket.socket = _no_socket\n"
        "socket.create_connection = _no_socket\n"
    )
    session = "no-socket"
    assert_deny(run_before(pre_payload(session, GATED_CREATE), hooks_root=tmp_path, setup=setup))
    satisfy(session, tmp_path, *REQUIRED_MARKERS)
    assert_allow(run_before(pre_payload(session, GATED_CREATE), hooks_root=tmp_path, setup=setup))


def test_a_session_id_that_traverses_stays_inside_the_hooks_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``session_id`` arrives from outside the process, so a ``../`` in one would otherwise
    escape both directories."""
    from hooks.checkpoints import before

    hostile = "../../etc/passwd"
    monkeypatch.setenv("SPEC_KITTY_HOOKS_ROOT", str(tmp_path))
    ledger = lib.session_ledger_path(hostile, root=tmp_path)
    liveness = before.liveness_path(hostile)
    assert ledger.parent == tmp_path / "sessions"
    assert liveness.parent == tmp_path / "liveness"
    assert ".." not in str(ledger) and ".." not in str(liveness)


# =============================================================================
# T047 / T048 — gate liveness (FR-012)
# =============================================================================


def liveness_on_disk(session_id: str, hooks_root: Path) -> dict[str, Any]:
    path = hooks_root / "liveness" / f"{lib.safe_component(session_id)}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def test_liveness_is_recorded_by_a_mission_with_zero_faults(tmp_path: Path) -> None:
    """T048, and the deadlock it exists to break.

    FR-012 refuses ``assert-none`` unless a liveness record exists for the session. That
    obligation was originally CP-DURING's, and CP-DURING fires only on
    ``PostToolUseFailure`` — so a mission in which **nothing failed** would have recorded
    no liveness, ``assert-none`` would have been refused, and the merge would have been
    unsatisfiable. A correct check that can never pass.

    This drives a whole clean mission — sweep, mission create, several ordinary
    ``spec-kitty`` calls — with **not one failing command**, and shows the record present.
    """
    session = "clean-mission"
    satisfy(session, tmp_path, *REQUIRED_MARKERS)
    assert_allow(run_before(pre_payload(session, GATED_CREATE), hooks_root=tmp_path))
    for command in ("spec-kitty status", "spec-kitty next --mission demo"):
        assert_allow(run_before(pre_payload(session, command), hooks_root=tmp_path))

    record = liveness_on_disk(session, tmp_path)
    assert record, "a fault-free mission left no liveness record; assert-none is unsatisfiable"
    assert record["session_id"] == session
    assert record["checkpoint"] == "before"
    assert record["schema"].startswith("spec-kitty-qa/gate-liveness@")


def test_a_hostile_session_id_is_sanitised_in_the_record_as_well_as_the_path(
    tmp_path: Path,
) -> None:
    """NFR-004: the sanitised ``session_id`` is the ONLY payload-derived value on disk.

    The filename and the field are two separate writes of the same untrusted string, and
    sanitising only the first leaves raw payload content in a file — with the traversal
    itself preserved verbatim for whatever reads it next.
    """
    hostile = "../../etc/pa ssw;d"
    assert_allow(run_before(pre_payload(hostile, "spec-kitty status"), hooks_root=tmp_path))

    written = list((tmp_path / "liveness").glob("*.json"))
    assert len(written) == 1
    assert written[0].parent == tmp_path / "liveness"
    body = written[0].read_text(encoding="utf-8")
    assert ".." not in body and "/" not in json.loads(body)["session_id"]
    assert json.loads(body)["session_id"] == "______etc_pa_ssw_d"


def test_liveness_is_recorded_even_when_the_call_is_refused(tmp_path: Path) -> None:
    """The fact recorded is *the gate fired*, not *the gate allowed*."""
    assert_deny(run_before(pre_payload("live-denied", GATED_CREATE), hooks_root=tmp_path))
    assert liveness_on_disk("live-denied", tmp_path)


def test_liveness_is_recorded_for_an_ungated_spec_kitty_call(tmp_path: Path) -> None:
    """A session that never starts a mission still had enforcement active — and the merge
    that asserts no faults may be exactly such a session."""
    assert_allow(run_before(pre_payload("live-ungated", "spec-kitty status"), hooks_root=tmp_path))
    assert liveness_on_disk("live-ungated", tmp_path)


def test_no_liveness_record_ever_enters_the_fault_ledger(tmp_path: Path) -> None:
    """⚠⚠ The trap this must not fall into.

    CP-AFTER's fold refuses on any record whose ``kind`` it cannot interpret. One liveness
    line written into ``faults/<mission>.jsonl`` would refuse every merge in this
    repository, permanently. Liveness lives in a file of its own.
    """
    session = "live-separate"
    assert_allow(run_before(pre_payload(session, "spec-kitty status"), hooks_root=tmp_path))

    assert (tmp_path / "liveness" / f"{session}.json").is_file()
    faults = tmp_path / "faults"
    if faults.exists():
        for path in faults.rglob("*"):
            if path.is_file():
                assert "liveness" not in path.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("**/*.jsonl")), (
        "liveness must never be appended to a JSONL ledger"
    )


def test_a_non_pretooluse_event_records_no_liveness_and_decides_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PAIRED NEGATIVE for the liveness group: the record must mean *this checkpoint ran*,
    not *some event happened*. CP-BEFORE is consulted only on ``PreToolUse``; calling it
    directly with another event must be a no-op in both directions."""
    from hooks.checkpoints import before

    monkeypatch.setenv("SPEC_KITTY_HOOKS_ROOT", str(tmp_path))
    payload = lib.parse_payload_mapping(post_payload("live-post", GATED_CREATE))
    assert before.evaluate(payload, lib.split_segments(GATED_CREATE)) is None
    assert not liveness_on_disk("live-post", tmp_path)


def test_a_liveness_write_that_fails_never_breaks_the_tool_call(tmp_path: Path) -> None:
    """Bookkeeping must not break the call it was asked to judge.

    The consequence of an unwritten record is a REFUSED ``assert-none`` later, which is the
    safe direction — so the swallow here is not the fail-open idiom NFR-001 forbids.
    """
    setup = (
        "def _boom(*a, **k):\n"
        "    raise OSError('read-only file system')\n"
        "before.liveness_path = _boom\n"
    )
    session = "live-broken"
    satisfy(session, tmp_path, *REQUIRED_MARKERS)
    assert_allow(run_before(pre_payload(session, GATED_CREATE), hooks_root=tmp_path, setup=setup))
    assert not liveness_on_disk(session, tmp_path)


# =============================================================================
# Review cycle 1, findings F1 and F3.
#
# F1 was a BLIND ORACLE, and the most instructive defect in this work package.
# `test_the_real_sweep_as_PreToolUse_marks_nothing` claims to pin FR-010b's second
# mechanism — that intent is not execution — and it never reaches CP-BEFORE at all.
# The dispatcher discards any command with no `spec-kitty` segment BEFORE consulting
# a checkpoint, so the test proves the dispatcher's pre-filter and nothing about the
# checkpoint's own behaviour.
#
# The cost was measured, not theoretical: a mutant adding one line to `evaluate()` —
# `lib.record_markers(payload, segments)` before the gate check — SURVIVED all 311
# tests, while at the wire a single PreToolUse payload self-satisfied the entire
# ledger and was allowed through.
#
# The fix is to assert on a shape that REACHES the checkpoint: the sweep commands
# chained with a gated verb, so the dispatcher admits the payload and the checkpoint
# is the thing under test.
# =============================================================================


def test_a_pretooluse_payload_cannot_self_satisfy_the_ledger(tmp_path: Path) -> None:
    """The four real sweep queries, chained with the gated verb, in ONE PreToolUse call.

    This is the shape the dispatcher admits, so CP-BEFORE genuinely runs. Intent must
    still not be execution: the call is denied and the ledger is never created.

    ⚠ Do not "simplify" this back to a payload without the gated verb. That is precisely
    the blind oracle it replaces — the dispatcher drops such a payload before any
    checkpoint sees it, and the assertion then passes for the wrong reason.
    """
    session = "self-satisfy"
    chained = " && ".join(list(REAL_SWEEP_COMMANDS.values()) + [GATED_CREATE])

    reason = assert_deny(run_before(pre_payload(session, chained), hooks_root=tmp_path))

    for marker in REAL_SWEEP_COMMANDS:
        assert marker in reason, f"the denial must still name {marker} as missing"

    ledger = tmp_path / "sessions" / f"{session}.json"
    assert not ledger.exists(), (
        "a PreToolUse payload recorded markers — intent was treated as execution, which is "
        f"the FR-010b defect this test exists to catch. Ledger: {ledger.read_text()!r}"
        if ledger.exists() else "unreachable"
    )


@pytest.mark.parametrize("marker", sorted(lib.MARKER_COMMANDS))
def test_each_printed_remedy_earns_the_marker_it_was_printed_for(
    marker: str, tmp_path: Path
) -> None:
    """F3. A gate that prints a command which cannot satisfy it is a livelock.

    It happened: `sweep.register_refs`' remedy named the register only inside a comment,
    while the detector required it in the `gh issue view` segment — so an agent running
    exactly what the gate told it to run was refused again, with the identical message.
    That is a correct check that can never pass, inside the mechanism built to prevent
    exactly that, and it is the third instance this mission has caught.

    It was fixed by hand in `_hook_lib` with no regression test anywhere. This is that test.
    """
    remedy = lib.MARKER_COMMANDS[marker]
    command = "\n".join(remedy) if isinstance(remedy, tuple) else remedy
    command = command.replace("<number>", "3728").replace("<date-of-last-sweep>", "2026-08-01")

    # ⚠ dot-free: the ledger sanitises `.` out of a session id, so a literal
    # f"remedy-{marker}" filename does not exist on disk.
    session = f"remedy-{marker.replace('.', '-')}"
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))

    ledger = json.loads((tmp_path / "sessions" / f"{session}.json").read_text())
    assert marker in (ledger.get("markers") or {}), (
        f"the gate prints this to satisfy {marker}, and running it earned "
        f"{sorted((ledger.get('markers') or {}))} instead — a livelock"
    )


def test_a_bare_issue_view_does_not_earn_the_register_cross_check(tmp_path: Path) -> None:
    """Negative control for the test above, so widening the detector cannot pass vacuously."""
    assert_allow(run_gate(
        post_payload("bare-view", "gh issue view 3728 --repo Priivacy-ai/spec-kitty --json state"),
        hooks_root=tmp_path,
    ))
    ledger = tmp_path / "sessions" / "bare-view.json"
    earned = sorted((json.loads(ledger.read_text()).get("markers") or {})) if ledger.exists() else []
    assert "sweep.register_refs" not in earned, (
        f"a view with no register reference must not earn the cross-check; earned {earned}"
    )


def test_an_allowed_pretooluse_payload_also_records_nothing(tmp_path: Path) -> None:
    """Finding 1: the sibling of the self-satisfaction hole, on the ALLOWED path.

    ``test_a_pretooluse_payload_cannot_self_satisfy_the_ledger`` exercises the DENIED path,
    where ``lib.deny`` exits before any post-checkpoint recording could run. A mutant that
    records markers *after* the checkpoint loop therefore survived it — and at the wire that
    reproduces F1's own sentence: one ``PreToolUse`` payload earns all four markers, and the
    mission create that follows is allowed.

    So this drives a payload that is ALLOWED (a non-gating ``spec-kitty`` verb chained with
    the four sweep queries) and asserts the ledger is still never created. Intent is not
    execution on either path.
    """
    session = "allowed-no-record"
    chained = " && ".join(["spec-kitty status"] + list(REAL_SWEEP_COMMANDS.values()))

    assert_allow(run_before(pre_payload(session, chained), hooks_root=tmp_path))

    ledger = tmp_path / "sessions" / f"{session}.json"
    assert not ledger.exists(), (
        "an ALLOWED PreToolUse payload recorded markers — the same self-satisfaction hole as "
        f"the denied path, one checkpoint later. Ledger: {ledger.read_text()!r}"
        if ledger.exists() else "unreachable"
    )


# =============================================================================
# Team Kitty migration — the sweep must be earnable against the org we now file into
#
# The `sweep.authored` earning site was the only org-dependent one: `sweep.recent_closed`
# keys on `--state closed` + `closed:>=`, and `sweep.register_refs` on `gh issue view` plus
# a register mention, both org-agnostic. So a correct sweep of the new org earned three of
# four markers and mission start was refused — while the denial's printed remedy named the
# RETIRING org, making the only satisfiable sweep a meaningless one. That is the
# "token command to satisfy the marker" the gate's own CLOSING_BLOCK forbids.
# =============================================================================

#: Every repo the QA playbook §5 routes filings to. All are `spec-kitty/EXPERIMENTAL-*`;
#: `spec-kitty/spec-kitty-qa` is deliberately absent — it is ours, not upstream.
NEW_ORG_REPOS = (
    "spec-kitty/EXPERIMENTAL-spec-kitty",
    "spec-kitty/EXPERIMENTAL-spec-kitty-saas",
    "spec-kitty/EXPERIMENTAL-spec-kitty-planning",
)

#: EVERY way `gh` accepts a repo, MEASURED against gh 2.98.0 by reading back the
#: repository it actually queried — never inferred::
#:
#:     $ gh issue list --repo cli/cli  --limit 1 --json url   ->  cli/cli
#:     $ gh issue list --repo=cli/cli  --limit 1 --json url   ->  cli/cli
#:     $ gh issue list -R cli/cli      --limit 1 --json url   ->  cli/cli
#:     $ gh issue list -Rcli/cli       --limit 1 --json url   ->  cli/cli
#:     $ gh issue list -R=cli/cli      --limit 1 --json url   ->  cli/cli
#:
#: Only the separated long form had any coverage originally, so a `startswith`-based
#: prefix check would have gone inert on `--repo=` with the suite green. The last two —
#: the ATTACHED short forms — were absent from this list through a whole review cycle,
#: and their absence reopened that hole one character narrower: `gh` fully supports
#: `-Rowner/name`, so an honest upstream sweep spelled that way earned NOTHING, and a
#: `-Rspec-kitty/spec-kitty-qa` appended after an upstream `--repo` earned a marker
#: while `gh` queried our own tracker.
REPO_FLAG_FORMS = (
    "--repo {repo}",
    "--repo={repo}",
    "-R {repo}",
    "-R{repo}",
    "-R={repo}",
)


@pytest.mark.parametrize("repo", NEW_ORG_REPOS)
@pytest.mark.parametrize("form", REPO_FLAG_FORMS)
def test_a_new_org_authored_sweep_earns_its_marker(
    tmp_path: Path, repo: str, form: str
) -> None:
    """The fix's reason for existing, across every repo and every flag spelling."""
    session = f"neworg-{abs(hash((repo, form)))}"
    command = (
        f"gh issue list {form.format(repo=repo)} --author kentonium3 --state all "
        "--limit 100 --json number,state,title,closedAt"
    )
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    assert "sweep.authored" in markers_on_disk(session, tmp_path), (
        f"a correct authored sweep of {repo} via `{form.format(repo=repo)}` earned nothing"
    )


@pytest.mark.parametrize("form", REPO_FLAG_FORMS)
def test_the_retiring_org_still_earns_its_marker(tmp_path: Path, form: str) -> None:
    """PAIRED NEGATIVE-SIDE REGRESSION: widening must not drop the old org.

    Both orgs are live during the migration; a sweep of either is real evidence.
    """
    session = f"oldorg-{abs(hash(form))}"
    command = (
        f"gh issue list {form.format(repo='Priivacy-ai/spec-kitty')} --author kentonium3 "
        "--state all --limit 100 --json number,state,title,closedAt"
    )
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    assert "sweep.authored" in markers_on_disk(session, tmp_path)


#: The post-rename names, which no list in the guard mentions. These must classify as
#: upstream with NO edit to any constant — that property IS the mission. Written out here
#: rather than derived from `lib.UPSTREAM_TARGETS`, deliberately: derived, they would
#: track whatever the module happens to say and could never detect the module being wrong.
POST_RENAME_REPOS = (
    "spec-kitty/spec-kitty",
    "spec-kitty/spec-kitty-saas",
    "spec-kitty/spec-kitty-planning",
    "spec-kitty/spec-kitty-analyzer",  # the contested case, resolved UPSTREAM
    "octocat/hello-world",  # unknown falls to the enforcing side (FR-002)
)

#: Every sweep marker and a real command that earns it against `{repo}`. All three are
#: conditioned on upstream now; before this mission only the first one was, so a sweep of
#: our own tracker earned two of the four required markers.
SWEEP_COMMANDS_BY_REPO: dict[str, str] = {
    "sweep.authored": (
        "gh issue list --repo {repo} --author kentonium3 --state all "
        "--limit 100 --json number,state,title,closedAt"
    ),
    "sweep.recent_closed": (
        "gh issue list --repo {repo} --state closed --limit 100 "
        '--search "closed:>=2026-08-01" --json number,title,closedAt'
    ),
    # ⚠ KNOWN WEAK: the register is named here in a COMMENT, and that is enough to earn
    # the marker — `_register_named_anywhere` is a mere-mention test over every token, so
    # `echo docs/spec-kitty-issues.md; gh issue view 1 --repo <upstream>` earns it with no
    # register read at all. That is the same "token command satisfying the gate" shape
    # CLOSING_BLOCK forbids, surviving on the one marker whose target cannot be checked.
    #
    # Requiring the register to be named in a segment whose program is a READER was tried
    # and reverted: it is correct, and it turns 10 tests red across helpers that satisfy
    # markers by mention rather than by reading. Not the cheap change it looks like.
    # Tracked with the rest of the evidence-scoping work in qa#291.
    "sweep.register_refs": (
        "gh issue view 3728 --repo {repo} --json state,title "
        "# cross-checking the refs docs/spec-kitty-issues.md cites"
    ),
}


@pytest.mark.parametrize("marker", sorted(SWEEP_COMMANDS_BY_REPO))
@pytest.mark.parametrize("repo", POST_RENAME_REPOS)
def test_a_post_rename_name_is_upstream_with_no_list_edit(
    tmp_path: Path, repo: str, marker: str
) -> None:
    """THE MISSION, stated as an assertion.

    None of these names appears in any constant in the guard. Under "not ours implies
    upstream" they are upstream anyway, so the day upstream is renamed the gate keeps
    working. Under the org-prefix definition this mission removed, every one of them
    classified as OURS and every sweep marker went silently unearnable.
    """
    session = f"postrename-{marker}-{abs(hash(repo)) % 10_000}"
    command = SWEEP_COMMANDS_BY_REPO[marker].format(repo=repo)
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    assert marker in markers_on_disk(session, tmp_path), (
        f"a real {marker} sweep of {repo} earned nothing — the classifier does not "
        "survive the rename, which is the entire point of this mission"
    )


@pytest.mark.parametrize("marker", sorted(SWEEP_COMMANDS_BY_REPO))
def test_our_own_repo_earns_no_sweep_marker(tmp_path: Path, marker: str) -> None:
    """The deny half, extended from `sweep.authored` to ALL THREE.

    A sweep of `spec-kitty/spec-kitty-qa` — our own tracker — is not evidence about the
    product under test, and accepting it satisfies a gate whose whole purpose is to make
    us look upstream. Two of these three markers were earnable this way until T004: they
    keyed on `--state closed`/`closed:>=` and on `gh issue view` + a register mention,
    neither of which mentions a repository at all.

    ⚠ Paired with `test_a_post_rename_name_is_upstream_with_no_list_edit` above. Alone,
    this assertion is satisfied by a detector that earns NOTHING, ever.
    """
    session = f"ourrepo-{marker}"
    command = SWEEP_COMMANDS_BY_REPO[marker].format(repo="spec-kitty/spec-kitty-qa")
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    assert marker not in markers_on_disk(session, tmp_path), (
        f"a sweep of OUR OWN tracker earned {marker} — our own issues were accepted as "
        "evidence about the product under test"
    )


@pytest.mark.parametrize("marker", sorted(SWEEP_COMMANDS_BY_REPO))
@pytest.mark.parametrize("form", REPO_FLAG_FORMS)
def test_our_own_repo_earns_nothing_in_any_flag_form(
    tmp_path: Path, marker: str, form: str
) -> None:
    """The refusal must not depend on the flag SPELLING.

    `--repo=X` hides the value inside a longer token. An extractor that handles only the
    separated form reads no target at all from `--repo=spec-kitty/spec-kitty-qa`, and
    "no target" is not "ours" — which would let the `=` form earn markers the separated
    form is refused.
    """
    session = f"ourrepo-form-{marker}-{abs(hash(form)) % 10_000}"
    template = SWEEP_COMMANDS_BY_REPO[marker].replace(
        "--repo {repo}", form.format(repo="{repo}")
    )
    command = template.format(repo="spec-kitty/spec-kitty-qa")
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    assert marker not in markers_on_disk(session, tmp_path), (
        f"`{form}` let our own tracker earn {marker} while `--repo X` did not"
    )


# -----------------------------------------------------------------------------
# The EMPTY target value, through the REAL gate
#
# MEASURED (gh 2.98.0), run from this checkout, whose origin is our own tracker:
#
#   $ gh issue list --repo "" --limit 1 --json url
#   [{"url":"https://github.com/spec-kitty/spec-kitty-qa/issues/291"}]
#   $ gh issue list --repo=   --limit 1 --json url          -> the same
#   $ gh issue list -R ""     --limit 1 --json url          -> the same
#   $ gh issue list --repo Priivacy-ai/spec-kitty --repo "" --limit 1 --json url
#   [{"url":"https://github.com/spec-kitty/spec-kitty-qa/issues/291"}]
#
# `gh` resolves an empty value from the git remote, and an EMPTY LAST OCCURRENCE beats
# an earlier real one. Two spellings of it used to disagree inside the extractor —
# `--repo=` returned None and `--repo ""` returned `''` — so one of them earned a
# marker for a sweep of our own issues while the other, which `gh` treats identically,
# did not.
# -----------------------------------------------------------------------------

#: `(tokens replacing `--repo {repo}`, id)`. Each makes `gh` fall back to the git remote.
EMPTY_TARGET_SPELLINGS = [
    pytest.param('--repo ""', id="empty-long-separated"),
    pytest.param("--repo=", id="empty-long-equals"),
    pytest.param('-R ""', id="empty-short-separated"),
    pytest.param('--repo Priivacy-ai/spec-kitty --repo ""', id="upstream-then-empty"),
    pytest.param("--repo Priivacy-ai/spec-kitty --repo=", id="upstream-then-empty-equals"),
]


@pytest.mark.parametrize("marker", sorted(SWEEP_COMMANDS_BY_REPO))
@pytest.mark.parametrize("spelling", EMPTY_TARGET_SPELLINGS)
def test_an_empty_target_value_earns_no_sweep_marker(
    tmp_path: Path, marker: str, spelling: str
) -> None:
    """DENY half. `gh` reads OUR OWN tracker here, so no sweep marker may be earned.

    The last two spellings are the sharp ones: a real upstream repository is named and
    then defeated by an empty occurrence. An extractor that skipped empty values would
    keep the upstream name, award the marker, and be wrong about which tracker `gh`
    actually swept.
    """
    session = f"emptytarget-{marker}-{abs(hash(spelling)) % 10_000}"
    command = SWEEP_COMMANDS_BY_REPO[marker].replace("--repo {repo}", spelling, 1).format(
        repo="unused"
    )
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    assert marker not in markers_on_disk(session, tmp_path), (
        f"`{spelling}` earned {marker}, but `gh` resolves an empty target from the git "
        "remote — this checkout's own tracker"
    )


@pytest.mark.parametrize("marker", sorted(SWEEP_COMMANDS_BY_REPO))
def test_an_empty_target_does_not_defeat_a_LATER_real_target(
    tmp_path: Path, marker: str
) -> None:
    """PAIRED ALLOW half. Resetting on empty must not become "empty poisons the command".

    MEASURED: `gh issue list --repo "" --repo cli/cli` queried `cli/cli`. Without this
    pair, an extractor returning `None` whenever ANY empty value appears would satisfy
    the deny half above while silently withholding markers from real upstream sweeps —
    the livelock direction, and the harder one to notice.
    """
    session = f"emptythenreal-{marker}"
    command = SWEEP_COMMANDS_BY_REPO[marker].replace(
        "--repo {repo}", '--repo "" --repo {repo}', 1
    ).format(repo="Priivacy-ai/spec-kitty")
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    assert marker in markers_on_disk(session, tmp_path), (
        f"an empty target BEFORE a real upstream one withheld {marker}, but `gh` "
        "queries the last occurrence"
    )


# -----------------------------------------------------------------------------
# The VALUE axis, through the REAL gate
#
# `gh` prints its own target as `-R, --repo [HOST/]OWNER/REPO` and accepts clone URLs,
# so a host-qualified spelling of our own tracker reaches our own tracker. MEASURED:
#
#   $ gh issue list --repo github.com/spec-kitty/spec-kitty-qa --limit 1 --json url
#   [{"url":"https://github.com/spec-kitty/spec-kitty-qa/issues/291"}]
#   $ gh issue list -Rgithub.com/spec-kitty/spec-kitty-qa --limit 1 --json url
#   [{"url":"https://github.com/spec-kitty/spec-kitty-qa/issues/291"}]
# -----------------------------------------------------------------------------

#: Value spellings MEASURED to reach the repository named by `{repo}`.
HOST_QUALIFIED_VALUE_FORMS = (
    "github.com/{repo}",
    "https://github.com/{repo}",
    "git@github.com:{repo}.git",
)


@pytest.mark.parametrize("marker", sorted(SWEEP_COMMANDS_BY_REPO))
@pytest.mark.parametrize("value_form", HOST_QUALIFIED_VALUE_FORMS)
def test_a_host_qualified_sweep_of_our_own_tracker_earns_nothing(
    tmp_path: Path, marker: str, value_form: str
) -> None:
    """DENY half, and the same hole as the attached short form on the VALUE axis.

    Compared verbatim, `github.com/spec-kitty/spec-kitty-qa` is not in `OURS`, so the
    gate calls it upstream and awards a marker for a sweep of our own issues — while
    `gh` is querying our own issues.
    """
    session = f"hostqual-ours-{marker}-{abs(hash(value_form)) % 10_000}"
    command = SWEEP_COMMANDS_BY_REPO[marker].format(
        repo=value_form.format(repo="spec-kitty/spec-kitty-qa")
    )
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    assert marker not in markers_on_disk(session, tmp_path), (
        f"`{value_form}` let our own tracker earn {marker}; `gh` resolves it to "
        "spec-kitty/spec-kitty-qa"
    )


@pytest.mark.parametrize("marker", sorted(SWEEP_COMMANDS_BY_REPO))
@pytest.mark.parametrize("value_form", HOST_QUALIFIED_VALUE_FORMS)
def test_a_host_qualified_sweep_of_upstream_still_earns_its_marker(
    tmp_path: Path, marker: str, value_form: str
) -> None:
    """PAIRED ALLOW half. The deny half alone is satisfied by refusing every qualified
    value outright, which would withhold markers from a real upstream sweep spelled in
    a form `gh` documents in its own `--help`."""
    session = f"hostqual-up-{marker}-{abs(hash(value_form)) % 10_000}"
    command = SWEEP_COMMANDS_BY_REPO[marker].format(
        repo=value_form.format(repo="Priivacy-ai/spec-kitty")
    )
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    assert marker in markers_on_disk(session, tmp_path), (
        f"a real upstream sweep spelled `{value_form}` earned nothing"
    )


# -----------------------------------------------------------------------------
# A REPEATED target flag — the gaming path that is one token wide
#
# `gh` binds the target with a cobra string flag, so the LAST occurrence wins. That is
# measured against the tool, not inferred (gh 2.98.0):
#
#   $ gh issue list --repo cli/cli --repo octocat/Hello-World --limit 1 --json url
#   [{"url":"https://github.com/octocat/Hello-World/issues/11019"}]
#   $ gh issue list --repo octocat/Hello-World --repo cli/cli --limit 1 --json url
#   [{"url":"https://github.com/cli/cli/issues/14257"}]
#
# An extractor that took the FIRST occurrence let `--repo <upstream> --repo <ours>` earn
# a sweep marker while `gh` queried our own tracker — exactly the "token command to
# satisfy the marker" the gate's own CLOSING_BLOCK forbids, and exactly what T004 exists
# to prevent. These run through the REAL gate, not against the extractor, because the
# claim being pinned is about what the gate awards.
# -----------------------------------------------------------------------------

#: `(first repo, last repo, does the LAST one earn the marker?)`. Both halves are
#: required: the deny half alone is satisfied by a gate that awards nothing.
DUPLICATE_TARGET_DIRECTIONS = [
    pytest.param(
        "spec-kitty/EXPERIMENTAL-spec-kitty",
        "spec-kitty/spec-kitty-qa",
        False,
        id="upstream-then-ours-earns-nothing",
    ),
    pytest.param(
        "spec-kitty/spec-kitty-qa",
        "spec-kitty/EXPERIMENTAL-spec-kitty",
        True,
        id="ours-then-upstream-earns-it",
    ),
]


@pytest.mark.parametrize("first,last,earns", DUPLICATE_TARGET_DIRECTIONS)
@pytest.mark.parametrize("marker", sorted(SWEEP_COMMANDS_BY_REPO))
def test_a_repeated_target_flag_is_judged_on_the_repo_gh_would_query(
    tmp_path: Path, marker: str, first: str, last: str, earns: bool
) -> None:
    """The verdict must follow the repository `gh` ACTUALLY queries, not the first one
    the command mentions. Under first-wins both halves invert: our own tracker earns
    every sweep marker while upstream is swept for nothing."""
    session = f"dupflag-{marker}-{abs(hash((first, last))) % 10_000}"
    command = SWEEP_COMMANDS_BY_REPO[marker].format(repo=last).replace(
        f"--repo {last}", f"--repo {first} --repo {last}", 1
    )
    assert f"--repo {first} --repo {last}" in command, "the fixture lost its duplicate"
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    earned = marker in markers_on_disk(session, tmp_path)
    assert earned is earns, (
        f"`--repo {first} --repo {last}` "
        f"{'earned' if earned else 'did not earn'} {marker}, but `gh` queries {last}"
    )


@pytest.mark.parametrize("first,last,earns", DUPLICATE_TARGET_DIRECTIONS)
@pytest.mark.parametrize("last_form", REPO_FLAG_FORMS)
@pytest.mark.parametrize("first_form", REPO_FLAG_FORMS)
def test_a_repeated_target_flag_resolves_the_same_in_any_mix_of_spellings(
    tmp_path: Path, first_form: str, last_form: str, first: str, last: str, earns: bool
) -> None:
    """MIXED spellings, because `gh` does not care which spelling came first — measured::

        $ gh issue list --repo cli/cli -R octocat/Hello-World     -> octocat/Hello-World
        $ gh issue list -R cli/cli --repo octocat/Hello-World     -> octocat/Hello-World
        $ gh issue list --repo=cli/cli --repo octocat/Hello-World -> octocat/Hello-World
        $ gh issue list --repo cli/cli --repo=octocat/Hello-World -> octocat/Hello-World

    Per-form tests each see only their OWN spelling, so a mixed duplicate slips between
    them. This is the one shape that catches an extractor that special-cases one form.
    """
    session = f"dupmix-{abs(hash((first_form, last_form, first))) % 100_000}"
    flags = f"{first_form.format(repo=first)} {last_form.format(repo=last)}"
    command = SWEEP_COMMANDS_BY_REPO["sweep.authored"].format(repo=last).replace(
        f"--repo {last}", flags, 1
    )
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    earned = "sweep.authored" in markers_on_disk(session, tmp_path)
    assert earned is earns, (
        f"`{flags}` {'earned' if earned else 'did not earn'} sweep.authored, but `gh` "
        f"queries {last}"
    )


def test_our_repo_is_not_confused_with_the_prefix_adjacent_upstream_repo(
    tmp_path: Path,
) -> None:
    """The substring/equality conflation, pinned as a PAIR.

    `"spec-kitty/spec-kitty" in "spec-kitty/spec-kitty-qa"` is True. Under a substring
    comparison our own tracker satisfies a requirement about the upstream CLI repo. The
    two commands here differ by four characters and must land on opposite sides.
    """
    upstream = SWEEP_COMMANDS_BY_REPO["sweep.authored"].format(repo="spec-kitty/spec-kitty")
    ours = SWEEP_COMMANDS_BY_REPO["sweep.authored"].format(repo="spec-kitty/spec-kitty-qa")

    assert_allow(run_gate(post_payload("adjacent-up", upstream), hooks_root=tmp_path))
    assert "sweep.authored" in markers_on_disk("adjacent-up", tmp_path), (
        "the upstream half of the adjacent pair earned nothing"
    )

    assert_allow(run_gate(post_payload("adjacent-ours", ours), hooks_root=tmp_path))
    assert "sweep.authored" not in markers_on_disk("adjacent-ours", tmp_path), (
        "our own tracker satisfied a requirement about spec-kitty/spec-kitty — the "
        "comparison is a substring test, not full-string equality"
    )


def test_the_denial_remedy_names_every_repo_we_still_file_into(tmp_path: Path) -> None:
    """A remedy pointing at a retired repo is worse than no remedy: it is satisfiable,
    so it trains the agent to earn the marker by sweeping a dead queue.

    ⚠ THIS ASSERTION WAS A STALENESS CARRIER. It pinned the literal
    `spec-kitty/EXPERIMENTAL-spec-kitty`, so after the rename it stayed green while the
    printed remedy named a repository that no longer exists — pinning today's value
    instead of detecting drift. It now asserts against `lib.UPSTREAM_TARGETS`, the one
    place the remedies are built from, so the remedy and the target set can never
    disagree. What keeps `UPSTREAM_TARGETS` itself honest is the §0 sweep against the
    live queues; no offline assertion can see upstream's rename.
    """
    reason = assert_deny(
        run_before(pre_payload("remedy-org", GATED_CREATE), hooks_root=tmp_path)
    )
    assert lib.UPSTREAM_TARGETS, "UPSTREAM_TARGETS is empty, so this asserts nothing"
    for target in lib.UPSTREAM_TARGETS:
        assert target in reason, (
            f"the printed remedy does not name {target}, a repo we file into — a remedy "
            "that omits a queue cannot tell a human to sweep it"
        )


def test_no_remedy_names_a_repository_outside_the_canonical_target_set(
    tmp_path: Path,
) -> None:
    """The other direction, and the one a hand-copied literal fails.

    Every repository LITERAL printed in the denial must be a member of
    `UPSTREAM_TARGETS`. A literal left behind in one remedy site survives a change to
    the target set, which is exactly how the gate came to print a dead repository while
    four other sites were correct.

    Shell expansions are excluded deliberately: the register cross-check reads each
    reference's repository off the reference, because the register's refs span three
    repositories and any constant answers confidently and wrongly.
    """
    reason = assert_deny(
        run_before(pre_payload("remedy-only-canonical", GATED_CREATE), hooks_root=tmp_path)
    )
    referenced = {ref for ref in re.findall(r"--repo[= ](\S+)", reason) if "$" not in ref}
    assert referenced, "the denial printed no --repo reference at all"
    stray = {ref for ref in referenced if ref not in lib.UPSTREAM_TARGETS}
    assert not stray, (
        f"the denial names {sorted(stray)}, which is not in UPSTREAM_TARGETS — a "
        "hand-copied literal survives a rename that moves every other remedy"
    )


# =============================================================================
# The marker gate must require a target that IS a repository name.
#
# Post-merge mission review, finding C-1. `names_upstream` answers "should this be
# enforced against?", and `_canonical_target` returns anything it cannot parse
# VERBATIM so that an unparseable value falls to the enforcing side. On the filing
# path that is safe. On the AWARD path it inverts: unparseable -> not in OURS ->
# upstream -> marker granted. Measured before the fix: `--repo $X` earned the marker
# while the honest `--repo <ours>` earned nothing.
#
# The condition added is that the target must LOOK LIKE a repository — enumerated
# ALLOW over slug syntax, so every shape nobody has thought of fails closed. It is
# deliberately NOT membership of `UPSTREAM_TARGETS`: that would stop a post-rename
# name earning without a list edit, which is the fragility this mission removed.
# =============================================================================

#: Targets that are not repository names, and the shell feature that produces each.
#: Every one of these reaches `gh` as something other than the token written here.
NON_REPOSITORY_TARGETS = (
    ("$X", "variable expansion"),
    ("${REPO}", "braced variable expansion"),
    ("$(cat r)", "command substitution"),
    ("spec-kitty/spec-kitty-qa*", "glob star — bash expands it to our own tracker"),
    ("spec-kitty/spec-kitty-q[a]", "glob character class"),
    ("spec-kitty/spec-kitty-q?a", "glob single-character wildcard"),
    ("{spec-kitty/spec-kitty-qa,--json}", "brace expansion"),
    ("~/spec-kitty/spec-kitty-qa", "tilde expansion"),
)

#: The two markers whose sanctioned query names one literal repository. `register.read`
#: has no target at all, and `sweep.register_refs` cannot have one — see its own test.
TARGETED_SWEEP_MARKERS = ("sweep.authored", "sweep.recent_closed")


@pytest.mark.parametrize("marker", TARGETED_SWEEP_MARKERS)
@pytest.mark.parametrize("target,feature", NON_REPOSITORY_TARGETS)
def test_a_target_that_is_not_a_repository_name_earns_nothing(
    tmp_path: Path, marker: str, target: str, feature: str
) -> None:
    """The C-1 deny half, across every shape review found.

    The glob rows are not hypothetical. With a matching directory present bash expands
    `spec-kitty/spec-kitty-qa*` to our own tracker, so the sweep really does hit our own
    issues while the token on the wire reads as something else.
    """
    session = f"c1-deny-{marker}-{abs(hash(target)) % 10_000}"
    command = SWEEP_COMMANDS_BY_REPO[marker].format(repo=target)
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    assert marker not in markers_on_disk(session, tmp_path), (
        f"{feature} earned {marker}. An unparseable target is not evidence of a sweep — "
        "it is evidence that we cannot tell what was swept"
    )


@pytest.mark.parametrize("marker", TARGETED_SWEEP_MARKERS)
@pytest.mark.parametrize("repo", POST_RENAME_REPOS)
def test_a_real_repository_still_earns_after_the_slug_condition(
    tmp_path: Path, marker: str, repo: str
) -> None:
    """The allow half, and the reason the fix is not an `UPSTREAM_TARGETS` allowlist.

    These names are not in any constant. A membership test would refuse them and the
    gate would demand a sweep of a repository that no longer exists — the rename
    fragility this mission was written to delete. A slug-shape test keeps them earning.
    """
    session = f"c1-allow-{marker}-{abs(hash(repo)) % 10_000}"
    command = SWEEP_COMMANDS_BY_REPO[marker].format(repo=repo)
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    assert marker in markers_on_disk(session, tmp_path), (
        f"a real sweep of {repo} earned nothing — the slug condition is too tight and "
        "has reintroduced the post-rename outage"
    )


def test_the_register_cross_check_still_earns_with_its_variable_target(
    tmp_path: Path,
) -> None:
    """`sweep.register_refs` must keep NO slug condition. Revision 2 of the fix note.

    The register's refs span three repositories, so query 3 reads each reference's
    repository off the reference itself. Its target is necessarily `${ref%#*}`. Requiring
    a slug here would make the marker unearnable by any correct query — and the gate
    PRINTS this loop as the way to earn it, so the operator would run exactly what they
    were told and be refused again. That is the livelock this mission repaired.
    """
    session = "c1-register-refs-variable"
    command = (
        'for ref in $(grep -oE "[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#[0-9]+" '
        "docs/spec-kitty-issues.md | sort -u); do "
        'gh issue view "${ref#*#}" --repo "${ref%#*}" --json number,state,title; done'
    )
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    assert "sweep.register_refs" in markers_on_disk(session, tmp_path), (
        "the register cross-check stopped earning its marker — the operator now lands on "
        "three of four markers and is refused, running the gate's own printed remedy"
    )


def test_a_bare_issue_view_still_earns_no_register_marker(tmp_path: Path) -> None:
    """The paired deny half for the marker that has no slug condition.

    Dropping `names_upstream` from `sweep.register_refs` must not make it free. The
    conjunction that remains is: the register named somewhere in the command, AND a
    target named at all. A bare view naming the register in a comment satisfies the
    first and not the second.
    """
    session = "c1-register-refs-no-target"
    command = "gh issue view 291 --json state,title  # docs/spec-kitty-issues.md"
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    assert "sweep.register_refs" not in markers_on_disk(session, tmp_path), (
        "a view that names no repository earned the cross-check marker"
    )


@pytest.mark.parametrize("marker", sorted(lib.MARKER_COMMANDS))
def test_the_gate_accepts_the_command_it_prints(tmp_path: Path, marker: str) -> None:
    """A gate may never print an instruction it will then refuse.

    This is the doctrine failure that killed revision 1 of the fix, turned into
    something the suite catches. The gate's remedy text and the predicate that accepts
    it are two encodings of one rule; nothing but this test keeps them in step.
    """
    printed = lib.MARKER_COMMANDS[marker]
    command = "\n".join(printed) if isinstance(printed, (list, tuple)) else str(printed)
    session = f"remedy-earns-{marker}"
    assert_allow(run_gate(post_payload(session, command), hooks_root=tmp_path))
    assert marker in markers_on_disk(session, tmp_path), (
        f"the gate prints this as the way to earn {marker}, and running it verbatim does "
        "not earn it. An operator who follows the instruction is refused again with the "
        "identical text — a correct check that can never pass"
    )
