r"""WP08 — tests for the WIRING, not for the Python behind it.

Everything WP03-WP05 built fires only where something is wired to fire it. Until this
work package, that wiring lived in one operator home directory, so a fresh clone of this
repository had no gate and said so nowhere. These tests hold the two halves of the
remedy: the tracked settings artifact, and the shell shim that stands between the hook
harness and the dispatcher.

WHY EVERY ASSERTION HERE IS ABOUT A STRING OR A SUBPROCESS
-----------------------------------------------------------
The property under test is *"a missing script denies"*. If the script is missing there is
no Python to import, so no unit test of ``mission_lifecycle_gate.py`` can reach it. The
mode lives entirely in the shell one-liner recorded in ``.claude/settings.json``. So the
shim tests **extract that one-liner from the settings file and run it**; none of them
re-types it. A retyped copy tests a copy, and the real string then rots untested — which
is precisely how the operator-local wiring came to carry ``|| exit 0`` (a missing script
becomes an ALLOW) with nothing noticing for months.

THE PAIRING RULE, AND WHY IT IS NOT OPTIONAL
--------------------------------------------
A fail-closed suite made only of deny assertions passes against a shim whose entire body
is ``printf '<deny>'`` — everything denies when nothing works. So each denial test below
is paired with ``test_allow_passes_through_as_silence`` and
``test_deny_passes_through_verbatim``, which fail the moment the shim stops
distinguishing outcomes. Deleting either positive does not weaken a denial assertion; it
removes the only evidence the denial assertions distinguish anything at all.

WHAT SC-003 IS CLAIMED AS, EXACTLY
-----------------------------------
**The tracked artifact.** Not a denial observed in a fresh clone. Project hooks require
each person cloning this repository to accept the workspace-trust dialog before any hook
runs, and a ``-p`` session does not count as acceptance — the shipped binary logs
``Skipping <event> hook execution - workspace trust not accepted``. So a fresh clone is
*wired but not yet enforcing*, and no non-interactive test can demonstrate otherwise.
Asserting a behavioural denial here would be a success reported over a gap, which is the
defect class this whole mission exists to remove.

The committed-object assertions read ``git show HEAD:<path>`` rather than cloning. A
naive ``git clone .`` breaks under a detached HEAD, which is what ``actions/checkout``
produces by default: the clone has no usable HEAD and checks out nothing, so the test
would pass or fail for a reason unrelated to its subject.

NFR-003 — measured warm latency of one gated tool call
-------------------------------------------------------
Measured by ``test_the_allow_path_stays_under_the_warm_budget``, through the **whole
shim** (``sh -c`` plus ``python3`` plus the dispatcher), because that is what a Bash tool
call actually pays. Not through ``.venv/bin/python``: a fresh clone has no ``.venv`` and
the committed wiring names ``python3``.

Measured 2026-08-25 on this work package's lane worktree. Three consecutive 20-run
batches are quoted so the spread is visible rather than implied by a single sample.

==========================  ==========================================================
n                           20 timed runs per batch, plus 1 warm-up run DISCARDED
what is timed               the whole shim: ``sh -c`` + ``python3`` + the dispatcher
interpreter                 ``python3`` -> /usr/local/opt/python@3.13/libexec/bin/python3
                            (CPython 3.13.15), i.e. the interpreter a shell finds with
                            this project's ``.venv`` off PATH
machine                     macOS (Darwin 25.5.0), x86_64
min                         101.3 / 101.6 / 101.6 ms
median                      **105.6 / 104.2 / 103.5 ms**
max                         118.1 / 116.1 / 109.7 ms
discarded warm-up           121.9 ms  (the cold run, and why it is discarded)
interpreter floor           ``python3 -c pass`` alone: median 44.8 ms -- roughly 43% of
                            the budget is spent before a line of gate code runs
budget                      median < 250 ms  (NFR-003 / SC-005)
outlier bound               max < 750 ms
==========================  ==========================================================

The discarded warm-up is a **stated** limit, not a hidden one: NFR-003's budget is
explicitly *warm*, and the first invocation pays the cold-interpreter cost (measured
separately at roughly 157 ms against a warm 62 ms for the existing guard). Reporting a
median without the maximum would hide the case that gets a gate switched off, so both are
asserted. The maximum bound is deliberately looser than three times the median: one
cold-cache outlier on a laptop under load should not turn the suite red, while a
pathological regression still does. That looseness is a choice, and this sentence is
where it is written down.

⚠ **The 250 ms budget supersedes the 100 ms still written in
``contracts/denial-payload.md`` §6 and ``quickstart.md`` §8.** Those two files are not
owned by this work package and were deliberately left alone; the divergence is reported
to the orchestrator instead. NFR-003 and SC-005 are authoritative.
"""

from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
SETTINGS_REL = ".claude/settings.json"
CHECK_WIRING = REPO_ROOT / "scripts" / "hooks" / "check_wiring.py"
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "autonomous-run-protocol.md"
GATE_REL = "scripts/hooks/mission_lifecycle_gate.py"

#: The two entries T041 adds. Named here rather than imported from the settings file: a
#: test that reads its expectation out of the artifact it is checking has checked nothing.
#: ⚠ PostToolUse was MISSING here and in the wiring itself until the post-merge review.
#: Markers are recorded on PostToolUse only, so without it CP-BEFORE could deny and could
#: never be satisfied — run the sweep correctly, earn nothing, be refused forever. This
#: constant is part of why the detector reported green over it: the test and the thing it
#: tested shared the same incomplete idea of what "wired" means.
GATE_EVENTS = ("PreToolUse", "PostToolUse", "PostToolUseFailure")

#: The operator-local anti-pattern this repository must never commit. The wiring in
#: ``~/.claude-work/settings.json`` reads
#: ``test -f <script> && python3 <script> || exit 0`` — so a script that has been renamed,
#: moved or deleted silently becomes an ALLOW. NFR-001 requires the opposite.
FAIL_OPEN_IDIOM = "|| exit 0"

#: Substrings that make a command string machine-local. The operator wiring hardcodes
#: ``/Users/kentgale/repos/...``, which is exactly why it does not travel.
MACHINE_PATH_PREFIXES = ("/Users/", "/home/")

WARM_RUNS = 20
MEDIAN_BUDGET_MS = 250.0
MAX_BUDGET_MS = 750.0


# =============================================================================
# Harness
# =============================================================================


def _settings_section(report: str) -> str:
    """Just the report's SETTINGS FILES block. Asserted on rather than the whole report,
    because the KNOWN GAPS footer also carries the phrase `operator-local` and a whole-text
    search would answer a different question."""
    return report.split("SETTINGS FILES", 1)[1].split("\n\n", 1)[0]


def _settings_rows(report: str) -> int:
    """How many rows the report's SETTINGS FILES section carries."""
    body = _settings_section(report)
    return len([line for line in body.splitlines() if line.strip().startswith("[")])


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _entries(doc: dict[str, Any], event: str) -> list[dict[str, Any]]:
    """Every leaf hook entry registered for ``event``."""
    out: list[dict[str, Any]] = []
    for matcher_block in doc.get("hooks", {}).get(event, []) or []:
        for entry in matcher_block.get("hooks", []) or []:
            out.append({**entry, "_matcher": matcher_block.get("matcher")})
    return out


def _all_commands(doc: dict[str, Any]) -> list[tuple[str, str]]:
    """``(event, command)`` for every command-type entry in the document."""
    out: list[tuple[str, str]] = []
    for event in doc.get("hooks", {}):
        for entry in _entries(doc, event):
            command = entry.get("command")
            if isinstance(command, str):
                out.append((event, command))
    return out


def _gate_command(doc: dict[str, Any], event: str) -> str:
    """The one command string registered for ``event`` that names the dispatcher."""
    matches = [
        entry["command"]
        for entry in _entries(doc, event)
        if isinstance(entry.get("command"), str)
        and "mission_lifecycle_gate.py" in entry["command"]
    ]
    assert len(matches) == 1, (
        f"expected exactly one {event} entry naming the dispatcher in {SETTINGS_REL}; "
        f"found {len(matches)}"
    )
    return matches[0]


def _assert_registers_the_gate_hooks(text: str, *, origin: str) -> None:
    """The SC-003 artifact assertion, factored so the working tree, the committed object
    and a synthetic repository can all be held to the identical standard."""
    doc = json.loads(text)
    for event in GATE_EVENTS:
        entries = [
            entry
            for entry in _entries(doc, event)
            if isinstance(entry.get("command"), str)
            and "mission_lifecycle_gate.py" in entry["command"]
        ]
        assert entries, f"{origin} registers no {event} hook naming the dispatcher"
        for entry in entries:
            assert entry["_matcher"] == "Bash", (
                f"{origin}: the {event} entry must match Bash only; "
                f"got {entry['_matcher']!r}"
            )
            assert isinstance(entry.get("timeout"), int) and entry["timeout"] > 0, (
                f"{origin}: the {event} entry needs a positive timeout — a hook that "
                "hangs is a hook that gets removed"
            )


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True
    )


def _path_without_the_project_virtualenv(path: str) -> str:
    """Drop any ``.venv/bin`` entry from PATH.

    NFR-003 is a claim about what the COMMITTED wiring costs, and the committed wiring
    names ``python3``. On a fresh clone there is no ``.venv``, so measuring through this
    repository's virtualenv would report the latency of an interpreter the wiring never
    invokes. pytest is normally started from ``.venv/bin/python``, which puts that
    directory first on PATH, so it has to be removed deliberately rather than assumed
    absent.
    """
    kept = [part for part in path.split(os.pathsep) if part and ".venv" not in part]
    return os.pathsep.join(kept)


def _sh(
    command: str,
    *,
    project_dir: Path,
    stdin: str = "{}",
    path: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the committed hook command exactly as the harness does: ``sh -c``, payload on
    stdin, ``CLAUDE_PROJECT_DIR`` supplied by Claude Code.

    Claude Code spawns a shell-form hook command through the user shell with
    ``CLAUDE_PROJECT_DIR`` set in the child environment (read out of the 2.1.231 binary's
    hook-spawn path: ``{...vD(), ...Jqt(o), CLAUDE_PROJECT_DIR: A(T)}`` where ``T`` is the
    project root). ``sh -c`` is the conservative stand-in — a shim that works under ``sh``
    works under bash and zsh too.
    """
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    env.pop("VIRTUAL_ENV", None)
    env["PATH"] = _path_without_the_project_virtualenv(env.get("PATH", ""))
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        ["/bin/sh", "-c", command],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
    )


def _stub_gate(project_dir: Path, body: str) -> Path:
    """Plant a stand-in dispatcher at the path the committed wiring resolves to."""
    target = project_dir / GATE_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(body), encoding="utf-8")
    return target


def _only_json_object(stdout: str) -> dict[str, Any]:
    """Parse stdout as EXACTLY one JSON object, single line, nothing else.

    The wire contract's whole point: a stray second line makes the payload unparseable and
    the decision is lost. ``json.loads`` on the whole buffer is what proves nothing else
    rode along.
    """
    assert stdout.endswith("\n"), f"payload is not newline-terminated: {stdout!r}"
    assert stdout.count("\n") == 1, (
        f"expected exactly one line on stdout, got {stdout.count(chr(10))}: {stdout!r}"
    )
    return json.loads(stdout)


@pytest.fixture(scope="module")
def settings_doc() -> dict[str, Any]:
    assert SETTINGS.exists(), (
        f"{SETTINGS_REL} is missing. It is the authoritative surface of WP08 — without it "
        "this repository ships hook scripts that nothing invokes."
    )
    return _load(SETTINGS)


@pytest.fixture(scope="module")
def pre_command(settings_doc: dict[str, Any]) -> str:
    return _gate_command(settings_doc, "PreToolUse")


@pytest.fixture(scope="module")
def failure_command(settings_doc: dict[str, Any]) -> str:
    return _gate_command(settings_doc, "PostToolUseFailure")


# =============================================================================
# T044 — the wiring artifact (SC-003)
# =============================================================================


def test_settings_is_tracked() -> None:
    """`.claude/` is gitignored by a spec-kitty auto-managed block that re-adds itself, and
    a `!` negation is inert because git cannot re-include a file under an excluded
    directory. `git add -f` is the only mechanism, and it is already this repository's
    precedent — the `.claude/agents/*.md` files are tracked past the identical rule."""
    result = _git("ls-files", "--error-unmatch", SETTINGS_REL)
    assert result.returncode == 0, (
        f"{SETTINGS_REL} is not tracked. Force-add it: git add -f {SETTINGS_REL}\n"
        f"{result.stderr}"
    )


def test_the_tracked_settings_file_is_no_longer_reported_as_ignored() -> None:
    """Tracked-and-ignored is the F-3 hazard: it works on the machine that force-added it
    and vanishes for the next person. Once tracked, `git check-ignore` reports no match."""
    result = _git("check-ignore", "-v", SETTINGS_REL)
    assert result.returncode != 0, (
        f"{SETTINGS_REL} is still matched by an ignore rule: {result.stdout.strip()}"
    )


def test_settings_registers_the_gate_hooks(settings_doc: dict[str, Any]) -> None:
    _assert_registers_the_gate_hooks(
        SETTINGS.read_text(encoding="utf-8"), origin="the working-tree settings file"
    )


def test_the_stored_settings_object_registers_the_gate_hooks() -> None:
    """The same assertions against the object git will ship — not the working tree.

    `git show <rev>:` rather than `git clone .`: a repository whose HEAD is detached — what
    `actions/checkout` produces by default — clones an unusable HEAD and checks out
    nothing, so the clone form would go green or red for a reason unrelated to wiring.

    ⚠ It reads `HEAD:` when the path is in HEAD and the **index** otherwise, and it never
    skips. A skip is the one outcome that asserts nothing, and this work package hands off
    **uncommitted** by instruction — so a skip-if-absent form would be skipping in the
    normal case rather than the exceptional one, and would have been the only evidence for
    SC-003 quietly not existing. The index blob is a real git object, produced by the
    `git add -f` that `test_settings_is_tracked` requires, and it is byte-for-byte what the
    next commit stores.
    """
    shown = _git("show", f"HEAD:{SETTINGS_REL}")
    source = f"HEAD:{SETTINGS_REL}"
    if shown.returncode != 0:
        shown = _git("show", f":{SETTINGS_REL}")
        source = f"the index entry for {SETTINGS_REL}"
    assert shown.returncode == 0, (
        f"{SETTINGS_REL} is in neither HEAD nor the index, so there is no stored object to "
        f"check. Force-add it: git add -f {SETTINGS_REL}\n{shown.stderr}"
    )
    _assert_registers_the_gate_hooks(shown.stdout, origin=source)


def test_the_committed_object_assertion_is_not_vacuous(tmp_path: Path) -> None:
    """The `git show HEAD:` path exercised end to end against a synthetic repository that
    HAS the file committed — including the negative case, so the assertion is shown able to
    fail. The test above reads HEAD only once a commit exists; this one proves that branch
    of it works before any commit does."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True
    )
    target = tmp_path / SETTINGS_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SETTINGS, target)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", SETTINGS_REL], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "w"], check=True)

    shown = subprocess.run(
        ["git", "-C", str(tmp_path), "show", f"HEAD:{SETTINGS_REL}"],
        capture_output=True,
        text=True,
        check=True,
    )
    _assert_registers_the_gate_hooks(shown.stdout, origin="a synthetic committed object")

    with pytest.raises(AssertionError):
        _assert_registers_the_gate_hooks(
            json.dumps({"hooks": {"Stop": []}}), origin="an empty document"
        )


def test_settings_preserves_spec_kitty_entries(settings_doc: dict[str, Any]) -> None:
    """Co-tenancy is a requirement, not a courtesy. This file was spec-kitty's before it
    was the gate's, and an edit that dropped `session-start` would silently detach every
    mission from its session record."""
    expected = {"SessionStart": "spec-kitty session-start", "Stop": "spec-kitty session-stop"}
    for event, command in expected.items():
        commands = [entry.get("command") for entry in _entries(settings_doc, event)]
        assert command in commands, (
            f"{SETTINGS_REL} no longer registers {command!r} on {event}; found {commands}"
        )


def test_no_absolute_machine_paths_in_hook_commands(settings_doc: dict[str, Any]) -> None:
    """Portability, stated as an assertion. The operator wiring hardcodes
    `/Users/kentgale/repos/spec-kitty-qa/...`, which is the concrete reason it never
    travelled to a second machine."""
    for event, command in _all_commands(settings_doc):
        for prefix in MACHINE_PATH_PREFIXES:
            assert prefix not in command, (
                f"the {event} command carries the machine-local path prefix {prefix!r}: "
                f"{command}"
            )


def test_no_fail_open_idiom_in_hook_commands(settings_doc: dict[str, Any]) -> None:
    """The operator wiring reads `test -f <script> && python3 <script> || exit 0`. That
    trailing clause converts a missing, renamed or crashed guard into an ALLOW — the exact
    inversion of NFR-001. Nothing committed here may carry it."""
    for event, command in _all_commands(settings_doc):
        assert FAIL_OPEN_IDIOM not in command, (
            f"the {event} command carries the fail-open idiom {FAIL_OPEN_IDIOM!r}: {command}"
        )


def test_every_hook_command_sets_a_timeout(settings_doc: dict[str, Any]) -> None:
    """PAIRED POSITIVE for the two tests above: they only forbid things, so on an empty
    hooks block they both pass. This one requires something to be there."""
    for event in GATE_EVENTS:
        entries = _entries(settings_doc, event)
        assert entries, f"{SETTINGS_REL} registers nothing at all on {event}"
        for entry in entries:
            assert isinstance(entry.get("timeout"), int)


def test_the_settings_file_is_valid_json() -> None:
    """A malformed file is not merely broken — spec-kitty's registrar copies it aside as
    `settings.json.invalid.<hex>` and builds a fresh structure, so the gate disappears and
    nothing announces it."""
    json.loads(SETTINGS.read_text(encoding="utf-8"))


# =============================================================================
# T042/T044 — the shim (NFR-001), the mode Python cannot close
# =============================================================================


def test_missing_script_denies(pre_command: str, tmp_path: Path) -> None:
    """No script at the resolved path: nothing runs, so there is no Python that could
    answer. The shim answers."""
    result = _sh(pre_command, project_dir=tmp_path)
    assert result.returncode == 0
    payload = _only_json_object(result.stdout)["hookSpecificOutput"]
    assert payload["hookEventName"] == "PreToolUse"
    assert payload["permissionDecision"] == "deny"
    assert "could not run" in payload["permissionDecisionReason"]


def test_missing_interpreter_denies(pre_command: str, tmp_path: Path) -> None:
    """A fresh clone with no `python3` on PATH is a real state, and it must not be an
    open door."""
    _stub_gate(tmp_path, "print('should never run')\n")
    result = _sh(pre_command, project_dir=tmp_path, path=str(tmp_path / "empty-bin"))
    assert result.returncode == 0
    payload = _only_json_object(result.stdout)["hookSpecificOutput"]
    assert payload["permissionDecision"] == "deny"


def test_crashing_script_denies(pre_command: str, tmp_path: Path) -> None:
    _stub_gate(tmp_path, "import sys\nsys.exit(3)\n")
    result = _sh(pre_command, project_dir=tmp_path)
    assert result.returncode == 0
    payload = _only_json_object(result.stdout)["hookSpecificOutput"]
    assert payload["permissionDecision"] == "deny"


def test_syntax_error_in_the_script_denies(pre_command: str, tmp_path: Path) -> None:
    """The mode a bad merge produces. The interpreter exits non-zero before any of the
    dispatcher's own fail-closed handling is reachable."""
    _stub_gate(tmp_path, "def broken(:\n")
    result = _sh(pre_command, project_dir=tmp_path)
    assert result.returncode == 0
    assert _only_json_object(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_partial_stdout_then_crash_yields_only_the_canned_deny(
    pre_command: str, tmp_path: Path
) -> None:
    """The reason the shim captures before it emits.

    `python3 script.py || printf '<canned>'` streams the script's stdout as it is produced,
    so a script that prints half a payload and then dies leaves garbage PLUS the canned
    deny on stdout: two fragments, unparseable, decision lost. Capture first, emit once.
    """
    _stub_gate(
        tmp_path,
        """
        import sys
        sys.stdout.write('{"hookSpecificOutput":{"hookEventNa')
        sys.stdout.flush()
        sys.exit(1)
        """,
    )
    result = _sh(pre_command, project_dir=tmp_path)
    assert result.returncode == 0
    payload = _only_json_object(result.stdout)["hookSpecificOutput"]
    assert payload["permissionDecision"] == "deny"
    assert "hookEventNa\"" not in result.stdout


def test_allow_passes_through_as_silence(pre_command: str, tmp_path: Path) -> None:
    """PAIRED POSITIVE. Every denial test above passes against a shim that denies
    unconditionally; this one does not. Silence IS the allow — not a bare newline, which
    some harnesses read as an empty payload."""
    _stub_gate(tmp_path, "import sys\nsys.exit(0)\n")
    result = _sh(pre_command, project_dir=tmp_path)
    assert result.returncode == 0
    assert result.stdout == "", f"expected silence, got {result.stdout!r}"


def test_deny_passes_through_verbatim(pre_command: str, tmp_path: Path) -> None:
    """PAIRED POSITIVE. A real denial from the dispatcher must arrive unmodified: the shim
    is a conduit on the success path, not a re-renderer."""
    real = (
        '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny",'
        '"permissionDecisionReason":"BLOCKED - a real checkpoint said so."}}'
    )
    _stub_gate(
        tmp_path,
        f"""
        import sys
        sys.stdout.write({real!r} + "\\n")
        """,
    )
    result = _sh(pre_command, project_dir=tmp_path)
    assert result.returncode == 0
    assert result.stdout == real + "\n"


def test_context_injection_passes_through_verbatim(
    failure_command: str, tmp_path: Path
) -> None:
    """PAIRED POSITIVE for the failure-event shim: CP-DURING's normal output is an
    `additionalContext` payload, and it must survive the shim unchanged."""
    real = (
        '{"hookSpecificOutput":{"hookEventName":"PostToolUseFailure",'
        '"additionalContext":"D-3: capture the evidence now."}}'
    )
    _stub_gate(
        tmp_path,
        f"""
        import sys
        sys.stdout.write({real!r} + "\\n")
        """,
    )
    result = _sh(failure_command, project_dir=tmp_path)
    assert result.stdout == real + "\n"


def test_failure_event_shim_denies_nothing_when_the_script_is_missing(
    failure_command: str, tmp_path: Path
) -> None:
    """`PostToolUseFailure` structurally cannot refuse anything — the tool has already run.
    A canned payload claiming otherwise would be an inert overstatement (C-004), so the
    failure shim reports the outage as context instead."""
    result = _sh(failure_command, project_dir=tmp_path)
    assert result.returncode == 0
    payload = _only_json_object(result.stdout)["hookSpecificOutput"]
    assert payload["hookEventName"] == "PostToolUseFailure"
    assert "permissionDecision" not in payload
    assert payload["additionalContext"].strip()


def test_failure_event_shim_never_emits_permission_decision(failure_command: str) -> None:
    """Asserted against the committed string itself, so the property holds for every
    outcome the shim can produce and not only for the one a test happened to trigger."""
    assert "permissionDecision" not in failure_command


def test_the_pre_tool_canned_payload_names_the_event_that_fired(pre_command: str) -> None:
    """The mirror of the test above. `permissionDecision` is a PreToolUse-only field; a
    canned payload naming the wrong event is discarded and the denial is lost."""
    assert '\\"hookEventName\\":\\"PreToolUse\\"' in pre_command or (
        '"hookEventName":"PreToolUse"' in pre_command
    )


def test_the_canned_payloads_carry_no_apostrophe(
    pre_command: str, failure_command: str
) -> None:
    """The canned JSON lives inside shell single quotes inside a JSON string. One
    apostrophe ends the shell quoting mid-payload and the deny becomes a syntax error at
    the moment it is most needed."""
    for command in (pre_command, failure_command):
        _, _, tail = command.partition("printf")
        assert "'" in tail, "the canned payload should be single-quoted for the shell"
        body = tail.split("'")[1]
        assert "’" not in body


def test_the_wiring_invokes_python3_not_the_virtualenv(
    pre_command: str, failure_command: str
) -> None:
    """A fresh clone has no `.venv`. The guards are stdlib-only, so `python3` is
    sufficient — and it is also the interpreter NFR-003 is measured against."""
    for command in (pre_command, failure_command):
        assert "python3" in command
        assert ".venv" not in command


def test_the_wiring_resolves_the_script_through_the_project_dir_variable(
    pre_command: str, failure_command: str
) -> None:
    """`CLAUDE_PROJECT_DIR` is set in the hook child environment by Claude Code 2.1.231
    (hook-spawn path: `{...vD(), ...Jqt(o), CLAUDE_PROJECT_DIR: A(T)}`, `T` = project
    root), so a shell-form command expands it like any other variable. If it were ever
    unset the path becomes `/scripts/hooks/...`, which does not exist — and a nonexistent
    script is a denial, so the failure direction is the safe one."""
    for command in (pre_command, failure_command):
        assert "CLAUDE_PROJECT_DIR" in command
        assert GATE_REL in command


# =============================================================================
# T043/T044 — the detector
# =============================================================================


def _wiring_fixture(
    root: Path,
    *,
    settings: dict[str, Any] | str,
    with_script: bool = True,
) -> Path:
    (root / "scripts" / "hooks").mkdir(parents=True, exist_ok=True)
    if with_script:
        (root / GATE_REL).write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    path = root / SETTINGS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        settings if isinstance(settings, str) else json.dumps(settings, indent=2),
        encoding="utf-8",
    )
    return path


def _wired(command: str = 'python3 "$CLAUDE_PROJECT_DIR/scripts/hooks/mission_lifecycle_gate.py"') -> dict[str, Any]:
    return {
        "hooks": {
            event: [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": command, "timeout": 10}],
                }
            ]
            for event in GATE_EVENTS
        }
    }


def _check(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK_WIRING), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def test_the_detector_passes_on_a_fully_wired_tree(tmp_path: Path) -> None:
    """PAIRED POSITIVE for every detector failure test below. An always-red detector is
    ignored, and an ignored detector is indistinguishable from no detector."""
    path = _wiring_fixture(tmp_path, settings=_wired())
    result = _check("--repo-root", str(tmp_path), "--settings", str(path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PreToolUse" in result.stdout


def test_the_detector_names_a_missing_required_entry(tmp_path: Path) -> None:
    doc = _wired()
    doc["hooks"].pop("PostToolUseFailure")
    path = _wiring_fixture(tmp_path, settings=doc)
    result = _check("--repo-root", str(tmp_path), "--settings", str(path))
    assert result.returncode != 0
    assert "PostToolUseFailure" in result.stdout
    assert "UNWIRED" in result.stdout


def test_the_detector_names_an_unparseable_settings_file(tmp_path: Path) -> None:
    """`present` is not enough: spec-kitty's registrar renames an invalid file aside and
    rebuilds an empty one, so the gate can be gone while the path still exists.

    ⚠ The required wiring is supplied by a SECOND, valid file, so the only thing wrong with
    this fixture is the broken one. The first version of this test put the broken JSON in
    the only settings file — which also made the required pairs unfindable, so it went red
    through the required-wiring check and stayed green with the unparseable check deleted
    entirely (mutant MC6 SURVIVED). It was a correct-looking assertion measuring something
    else.
    """
    good = _wiring_fixture(tmp_path, settings=_wired())
    broken = tmp_path / ".claude" / "settings.local.json"
    broken.write_text("{ this is not json", encoding="utf-8")
    result = _check(
        "--repo-root", str(tmp_path), "--settings", str(good), "--settings", str(broken)
    )
    assert result.returncode != 0, result.stdout
    assert "UNPARSEABLE" in result.stdout
    assert "settings.local.json does not parse" in result.stdout


def test_the_detector_names_a_wired_but_missing_script(tmp_path: Path) -> None:
    path = _wiring_fixture(tmp_path, settings=_wired(), with_script=False)
    result = _check("--repo-root", str(tmp_path), "--settings", str(path))
    assert result.returncode != 0
    assert "MISSING" in result.stdout
    assert GATE_REL in result.stdout


def test_the_detector_names_the_fail_open_idiom(tmp_path: Path) -> None:
    command = (
        'test -f "$CLAUDE_PROJECT_DIR/scripts/hooks/mission_lifecycle_gate.py" && '
        'python3 "$CLAUDE_PROJECT_DIR/scripts/hooks/mission_lifecycle_gate.py" || exit 0'
    )
    path = _wiring_fixture(tmp_path, settings=_wired(command))
    result = _check("--repo-root", str(tmp_path), "--settings", str(path))
    assert result.returncode != 0
    assert FAIL_OPEN_IDIOM in result.stdout


def test_the_detector_names_an_absolute_machine_path(tmp_path: Path) -> None:
    """⚠ Asserted on the hazard line specifically, not merely on a non-zero exit.

    A hardcoded `/Users/...` path also fails the wired-but-missing check, because the path
    does not exist on the machine running the tests. So the loose version of this test went
    red with the machine-path check deleted (mutant MC4 SURVIVED) — a blind oracle reading
    a different check's verdict and reporting it as its own.
    """
    command = "python3 /Users/someone/repos/spec-kitty-qa/scripts/hooks/mission_lifecycle_gate.py"
    path = _wiring_fixture(tmp_path, settings=_wired(command))
    result = _check("--repo-root", str(tmp_path), "--settings", str(path))
    assert result.returncode != 0
    assert "[FLAG]" in result.stdout
    assert "machine-local path prefix '/Users/'" in result.stdout


def test_the_detector_reports_an_unwired_script_without_failing(tmp_path: Path) -> None:
    """`upstream_filing_guard.py` is deliberately still operator-local: WP08 wires the
    mission-lifecycle gate and nothing else. Making that a failure would leave the detector
    permanently red for a state somebody chose."""
    path = _wiring_fixture(tmp_path, settings=_wired())
    (tmp_path / "scripts" / "hooks" / "upstream_filing_guard.py").write_text("", encoding="utf-8")
    result = _check("--repo-root", str(tmp_path), "--settings", str(path))
    assert result.returncode == 0
    assert "upstream_filing_guard.py" in result.stdout
    assert "UNWIRED" in result.stdout


def test_the_detector_fails_on_an_untracked_wiring_file(tmp_path: Path) -> None:
    """The F-3 hazard, exercised against a real repository rather than asserted about one.
    Tracked-and-ignored works on the machine that force-added it; untracked-and-ignored is
    the state this whole work package exists to make visible."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = _wiring_fixture(tmp_path, settings=_wired())
    untracked = _check("--repo-root", str(tmp_path), "--settings", str(path))
    assert untracked.returncode != 0
    assert "UNTRACKED" in untracked.stdout

    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", SETTINGS_REL], check=True)
    tracked = _check("--repo-root", str(tmp_path), "--settings", str(path))
    assert tracked.returncode == 0, tracked.stdout


def test_the_detector_reads_the_real_repository_without_failing() -> None:
    """The detector run against this repository, with no fixtures. This is the assertion
    that WP08 actually landed: the required pairs are wired, the file is tracked, and no
    committed command carries a machine path or the fail-open idiom."""
    result = _check()
    assert result.returncode == 0, result.stdout + result.stderr


def test_report_does_not_claim_hooks_fired() -> None:
    """NFR-002. There is no documented runtime way to list active hooks, so the detector
    reads settings files and must say so where the reader sees it — a report that implies
    more than it checked is the defect this mission is about."""
    result = _check()
    assert "cannot" in result.stdout.lower()
    assert "workspace-trust" in result.stdout or "workspace trust" in result.stdout
    assert "fired" in result.stdout


def test_the_detector_never_writes_outside_the_repository(tmp_path: Path) -> None:
    """C-002, checked rather than promised: `--include-user` reads the operator's home
    settings, and a detector that wrote there would be modifying a file outside this
    repository."""
    source = CHECK_WIRING.read_text(encoding="utf-8")
    for forbidden in ("write_text(", "open(", "mkdir(", "unlink(", "touch("):
        assert forbidden not in source.replace("read_text(", ""), (
            f"check_wiring.py contains {forbidden!r}; it must only read"
        )


def test_include_user_is_off_by_default(tmp_path: Path) -> None:
    """A detector whose output depends on the developer's home directory cannot be
    asserted against, so the home settings are opt-in and reported informationally.

    PAIRED: the `--include-user` half is asserted too. Without it the absence assertion
    passes on any run that produced no output at all, which it did while `check_wiring.py`
    did not yet exist.
    """
    path = _wiring_fixture(tmp_path, settings=_wired())
    default = _check("--repo-root", str(tmp_path), "--settings", str(path))
    assert default.returncode == 0, default.stdout + default.stderr
    assert "SETTINGS FILES" in default.stdout
    assert "operator-local" not in _settings_section(default.stdout)

    opted_in = _check(
        "--repo-root", str(tmp_path), "--settings", str(path), "--include-user"
    )
    assert "operator-local, informational" in _settings_section(opted_in.stdout)
    assert _settings_rows(opted_in.stdout) == _settings_rows(default.stdout) + 1


def test_include_user_follows_claude_config_dir(tmp_path: Path) -> None:
    """The user-level file is whichever one the harness would read.

    Measured on this machine: a work-account session runs with
    `CLAUDE_CONFIG_DIR=~/.claude-work`, so a detector hardcoding `~/.claude/settings.json`
    reads a file the live session does not — and then reports `upstream_filing_guard.py`
    as referenced by nothing while it is in fact wired. A report that names the wrong file
    is worse than one that names none.
    """
    path = _wiring_fixture(tmp_path, settings=_wired())
    home = tmp_path / "fake-config"
    home.mkdir()
    (home / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 /Users/someone/upstream_filing_guard.py || exit 0",
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(CHECK_WIRING),
            "--repo-root",
            str(tmp_path),
            "--settings",
            str(path),
            "--include-user",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_CONFIG_DIR": str(home), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert str(home) in result.stdout
    assert "$CLAUDE_CONFIG_DIR/settings.json" in result.stdout
    # The operator-local hazards are REPORTED and do not turn the detector red: they
    # describe a file this repository does not own and cannot fix.
    assert "[FLAG]" in result.stdout
    assert result.returncode == 0, result.stdout


# =============================================================================
# T046 — NFR-003
# =============================================================================


def test_the_allow_path_stays_under_the_warm_budget(pre_command: str) -> None:
    """20 warm runs of the ALLOW path through the whole committed shim.

    The allow path is the one every Bash tool call pays, so it is the one the budget is
    about. One warm-up run is executed and DISCARDED: NFR-003's budget is explicitly warm,
    and the first invocation pays cold-interpreter cost. Measured numbers live in this
    module's docstring.
    """
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "nfr003-latency",
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
        }
    )
    warm_up = _sh(pre_command, project_dir=REPO_ROOT, stdin=payload)
    assert warm_up.returncode == 0 and warm_up.stdout == "", (
        "the latency probe must exercise the ALLOW path; it did not. "
        f"stdout={warm_up.stdout!r}"
    )

    samples: list[float] = []
    for _ in range(WARM_RUNS):
        started = time.perf_counter()
        result = _sh(pre_command, project_dir=REPO_ROOT, stdin=payload)
        samples.append((time.perf_counter() - started) * 1000.0)
        assert result.stdout == ""

    median = statistics.median(samples)
    worst = max(samples)
    report = (
        f"n={len(samples)} min={min(samples):.1f}ms median={median:.1f}ms "
        f"max={worst:.1f}ms interpreter={shutil.which('python3')}"
    )
    assert median < MEDIAN_BUDGET_MS, f"median over budget: {report}"
    assert worst < MAX_BUDGET_MS, f"outlier over the looser bound: {report}"


# =============================================================================
# T045 — the runbook correction, held in place
# =============================================================================
#
# The correction T045 makes is one word in one table cell, and one word is exactly what a
# future editor restores without noticing. `PostToolUse` fires only after a tool SUCCEEDS,
# so a runbook that names it for the during-mission checkpoint describes a checkpoint that
# can never fire on the fault it exists for. That defect survived in this file until this
# mission; nothing was watching it. These tests watch it.


def _trigger_row(label: str) -> list[str]:
    """The cells of one row of §9's trigger table."""
    text = RUNBOOK.read_text(encoding="utf-8")
    matches = [
        line for line in text.splitlines() if line.startswith(f"| **{label}**")
    ]
    assert len(matches) == 1, (
        f"expected exactly one §9 trigger row for {label!r}; found {len(matches)}"
    )
    return [cell.strip() for cell in matches[0].strip().strip("|").split("|")]


def test_the_runbook_during_row_names_the_failure_event() -> None:
    """IC-07. The hook column must name `PostToolUseFailure` FIRST — the row also mentions
    `PostToolUse` in the clause explaining why it is wrong, so a substring search either
    way would answer the wrong question."""
    hook_cell = _trigger_row("During")[2]
    assert hook_cell.startswith("`PostToolUseFailure`"), (
        "§9's during-mission row must name PostToolUseFailure as its trigger. "
        f"It reads: {hook_cell[:90]}"
    )
    assert "succeeds" in hook_cell, (
        "the row must carry the REASON in one clause, or the correction is one edit away "
        "from being undone again"
    )


def test_the_runbook_after_row_promises_no_checkpoint_that_does_not_exist() -> None:
    """CP-AFTER was cut from the mission. A runbook row describing a merge gate that was
    never built is a reader trusting enforcement that is not there."""
    hook_cell = _trigger_row("After")[2]
    assert "Not built" in hook_cell
    assert "`PreToolUse`:" not in hook_cell


def test_the_runbook_says_the_during_checkpoint_cannot_refuse_anything() -> None:
    """Three rows are not three gates. `PostToolUseFailure` fires after the tool has run."""
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "not a gate" in text
    assert "record-plus-notify" in text


def test_the_runbook_layer_table_lists_the_failure_event() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "| **Hook** (`PreToolUse` / `PostToolUse` / `PostToolUseFailure`)" in text


def test_the_runbook_names_workspace_trust_as_a_first_run_step() -> None:
    """The replacement for the stale machine-local caveat. Deleting the caveat instead of
    replacing it would have read as a solved problem, and it is not solved — it moved."""
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "workspace-trust dialog" in text or "workspace trust" in text
    assert "First-run step" in text
    assert "upstream_filing_guard.py" in text


def test_the_detector_command_the_runbook_prints_actually_exists() -> None:
    """A runbook that tells the reader to run something absent is worse than silence."""
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "python3 scripts/hooks/check_wiring.py" in text
    assert CHECK_WIRING.exists()
