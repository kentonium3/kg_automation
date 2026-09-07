r"""WP07 — the four fixes to ``scripts/hooks/upstream_filing_guard.py``, each red first.

Companion to ``tests/hooks/test_upstream_filing_guard.py`` (WP02), which pins the
behaviours that survive this work unchanged. This module holds the other half: every
assertion here was **false against the pre-fix guard** and is true after it. The two files
are disjoint on purpose — WP02 owns the characterisation baseline, WP07 owns the
inversions — so neither has to edit the other (see WP02's docstring on lane collapse).

THE FOUR DEFECTS
----------------
1. **qa #277 — the guard failed OPEN.** ``main()`` opened with
   ``try: payload = json.load(sys.stdin) / except Exception: allow()``. Any unparseable
   payload *permitted* the filing. A gate whose failure mode is "yes" manufactures a green
   nobody earned.
2. **qa #276 — a file-supplied body was invisible.** The footer check ran against the
   literal Bash command string, so ``--body-file draft.md`` was denied for a footer that
   was present in the file all along, and the denial sent the author to add one twice.
3. **The mention/invocation false positive.** ``FILING_RE.search(command)`` matched a
   *substring*, so ``echo "… gh issue create --repo Priivacy-ai/… …"`` was denied. This
   fired twice during the session that produced this mission, against an agent that was
   only writing a file.
4. **The marker-faking inverse.** Markers were recorded from ``PreToolUse`` command
   *text*, so ``echo "gh issue list …"`` set the ``queue`` marker. MEASURED live during
   that same session: a ledger read ``{"queue": true, "register": true, "intent": true}``
   when none of the three steps had run — every marker set by an *authoring* command that
   happened to quote the query as a literal.

Defects 3 and 4 are one root cause seen from both ends: substring matching cannot tell a
mention from an invocation. One direction lets a mention masquerade as a command, the
other lets a mention masquerade as evidence. Both are fixed by parsing argv.

RED-FIRST EVIDENCE (C-003)
--------------------------
Every test below was run against the unfixed guard before the fix was written. Measured,
from ``.venv/bin/python -m pytest -q -p no:randomly
tests/hooks/test_upstream_filing_guard_fixes.py``::

    64 failed, 26 passed in 18.30s

The failure output, by group::

    # T036 — the fail-open. Every parse-failure case ALLOWED:
    E  AssertionError: expected a denial payload on stdout, got nothing
    E  assert '' != ''
    #   test_unparseable_payload_denies, test_empty_stdin_denies,
    #   test_non_object_payload_denies[list], [string], [number],
    #   test_non_object_tool_input_denies, test_unhandled_exception_denies

    # T036 — the wrapper did not exist:
    E  AssertionError: the module must route __main__ through a fail-closed wrapper
    #   test_main_is_invoked_through_the_failclosed_wrapper

    # T037 — a correctly footered file body was DENIED (qa #276):
    E  AssertionError: expected an allow (empty stdout), got: '{"hookSpecificOutput":
    E    {"hookEventName": "PreToolUse", "permissionDecision": "deny",
    E     "permissionDecisionReason": "BLOCKED — this filing has not completed the
    E     bug-reporting runbook.\n\nFOOTER (step 4) — missing from the body: ...
    #   test_body_file_with_footer_is_allowed, test_body_file_equals_form_resolved,
    #   test_short_flag_form_resolved, test_relative_body_file_resolves_against_payload_cwd

    # T037/T038 — an unresolvable body was reported as a MISSING FOOTER:
    E  AssertionError: assert "BLOCKED — this filing's body cannot be read" in reason
    #   every dynamic-form case, every unreadable-file case

    # T039 — the mention/invocation pair, both directions:
    E  AssertionError: expected an allow (empty stdout), got: '{"hookSpecificOutput": ...
    #   test_quoted_mention_of_a_filing_command_is_allowed
    E  AssertionError: expected a denial payload on stdout, got nothing
    #   test_echo_does_not_set_queue_marker, test_printf_does_not_set_queue_marker,
    #   test_ls_of_register_does_not_set_register_marker,
    #   test_touch_of_register_does_not_set_register_marker,
    #   test_multiline_echo_mention_does_not_mark

    # T039 — the docstring did not state either limit:
    E  AssertionError: the guard's docstring must state the PreToolUse marking limit
    #   test_docstring_states_the_pretooluse_marking_limit,
    #   test_docstring_states_the_body_file_toctou_limit

**26 of these tests passed against the unfixed guard, and that is worth reading rather
than skimming.** Most are the "still works afterwards" half of a pair — the six real
queue searches, the six real register reads, the intent check, the scoping test. A fix
that stopped ``echo`` from marking by refusing to mark at all would pass every inversion
above and destroy the guard; those are what stop it, and they are supposed to be green
throughout.

Two passed for a *reason unrelated to their subject*, which is a different thing:

* ``test_body_file_without_footer_is_denied`` — the old guard denied it too, for the
  wrong cause. Its companion ``…_names_the_footer_and_not_a_read_failure`` is the
  assertion that was red.
* ``test_denial_never_contains_body_file_contents`` — trivially true when the file is
  never opened.

A third was a **blind oracle, and this run is what caught it**:
``test_body_file_toctou_limit_is_stated_in_the_denial`` originally accepted the substring
``re-read``, which the old dedup section happens to contain in a sentence about the
runbook — so it passed against the guard it was written to fail against. It now asserts a
phrase that exists nowhere but the TOCTOU statement, and is red pre-fix like the rest. It
is kept in that corrected form as the record; see its own docstring.

A test that was green before the fix is not evidence of the fix. Each of the three above
is now either paired with a discriminating assertion or rewritten.

MUTATION PASS (T040)
--------------------
After green, the load-bearing line of each fix was reverted and the module re-run. Run
with ``PYTHONDONTWRITEBYTECODE=1`` and ``__pycache__`` cleared before **every** mutant,
because CPython validates a ``.pyc`` on (mtime, size) and a same-size edit within the
filesystem's mtime granularity is silently ignored — a mutant reported SURVIVED elsewhere
in this mission had never executed. The whole module is run each time, never ``-k``: a
narrowed run elsewhere in this mission reported two false SURVIVEDs that other tests in
the same module were already killing. The harness restores the guard through ``atexit``
and SIGTERM/SIGINT/SIGHUP, and verifies the file's SHA-256 against the pre-run value
afterwards; it matched, and the unmutated module re-ran at 85 passed.

Baseline before any mutation: **90 passed**.

===  =============================================================  ======================
 #    Mutation                                                       Observed
===  =============================================================  ======================
 M1   ``main()``'s payload guard back to ``except Exception:         **KILLED**
      allow()``                                                      10 failed, 80 passed
 M2   ``body, denial = resolve_body(argv, cwd)`` → ``= command,      **KILLED**
      None`` — i.e. the footer checked against the command string     31 failed, 59 passed
 M3   ``is_filing`` back to a substring search for                   **KILLED**
      ``\bgh\s+issue\s+(create|comment)\b``                           3 failed, 87 passed
 M4   ``detect_markers`` back to the three pre-fix ``re.search``     **KILLED**
      calls over the flattened token text                             9 failed, 81 passed
 M5   the wrapper's ``except SystemExit: raise`` deleted             **KILLED**
                                                                      84 failed, 6 passed
===  =============================================================  ======================

M3's three kills, enumerated because the third was not the one predicted:
``test_quoted_mention_of_a_filing_command_is_allowed`` and
``test_multiline_authoring_command_quoting_a_filing_is_allowed`` are the single-line and
multi-line halves of the same defect. The third is
``test_a_filing_reached_through_shell_syntax_is_still_gated[sh-dash-c]``, and its failure
text is the interesting part: under M3 the OUTER ``sh -c '<filing>'`` segment matches the
substring too, so the guard evaluates ``['sh', '-c', '<the whole filing as one token>']``
as if it were the filing — and that segment carries no body flag, so it denies with *no
body flag is present, so the tool would prompt for it*. A substring matcher does not
merely over-match; it over-matches onto a segment whose argv means something else, and
then explains itself confidently in terms of that segment. It is the smallest kill set of
the five, which is what a narrowly-scoped fix looks like.

M5 runs the OPPOSITE way from the rest of this work: deleting the re-raise turns every
allow into a deny. "Fail closed" is a direction, not a licence, and a gate that denies
everything is switched off within a day.

WHY THE WIRE AND NOT AN IMPORT
------------------------------
Same three reasons WP02 gives: the guard exits on every path, the deliverable is a wire
contract, and ``LEDGER_DIR`` is computed at import from ``tempfile.gettempdir()``. Ledger
isolation therefore rides on ``TMPDIR``; WP02 proves that isolation takes effect and this
module inherits the proof rather than restating it.

Two tests here need to reach *inside* the guard process (an internal raising, and proving
no subprocess is ever spawned). Those run through a generated driver that imports the
module, patches the one thing under test, and calls the real ``run()`` — so the wrapper
and the wire are still the code under test, not a re-implementation of them.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "scripts" / "hooks"
GUARD = HOOKS_DIR / "upstream_filing_guard.py"

# --- literals from the guard's rendered output -------------------------------------
# Asserted as literals, never imported: a test that finds the guard's own constant in the
# guard's own output has compared a value with itself.

PARSE_HEADLINE = "BLOCKED — this hook could not read the tool payload it was asked to judge."
BODY_HEADLINE = "BLOCKED — this filing's body cannot be read"
REPO_HEADLINE = "BLOCKED — this filing's --repo value cannot be resolved"
TOKENISE_HEADLINE = "BLOCKED — this Bash command could not be tokenised"

# WP02's discriminators, restated here so a collapse of the four causes into one text is
# caught from this side too.
DEDUP_HEADER = "DEDUP (step 2) — no trace of it in this session:"
REGISTER_CAUSE = "docs/spec-kitty-issues.md was not read"
QUEUE_CAUSE = "the upstream queue was not searched"
FOOTER_HEADER = "FOOTER (step 4) — missing from the body:"
CLOSING_BLOCK = "never by adding a token command"

# The named dynamic forms (T038). One per row of the WP's table.
FORM_COMMAND_SUBSTITUTION = "command substitution"
FORM_VARIABLE_EXPANSION = "variable expansion"
FORM_STDIN = "the body is read from stdin"
FORM_EDITOR = "the body is composed in an editor"
FORM_TEMPLATE = "the body comes from a template"
FORM_PROMPT = "no body flag is present, so the tool would prompt for it"
FORM_MULTIPLE = "more than one body source is given"

# The named read failures (T037).
FORM_NOT_A_FILE = "the path does not name a readable regular file"
FORM_NO_CWD = "the path is relative and the payload carries no cwd to anchor it"
FORM_TOO_LARGE = "the file is larger than the 1 MiB the gate will read"
FORM_NOT_UTF8 = "the file is not valid UTF-8"

FOOTERED_BODY = (
    "The symptom reproduces on build abc1234.\n\n"
    "**Authored by**: Kent Gale & Claude, 2026-08-25\n"
    "**Submission approved by**: Kent Gale, 2026-08-25\n"
)
UNFOOTERED_BODY = "The symptom reproduces on build abc1234.\n"

REGISTER_PATH = "/repo/docs/spec-kitty-issues.md"
QUEUE_SEARCH = 'gh issue list --repo Priivacy-ai/spec-kitty --search "symptom" --state all'
UPSTREAM_REPO = "Priivacy-ai/spec-kitty"

# NFR-004 probes. Synthetic — neither string is a credential, and both are shaped like the
# thing that must never reach a denial or the ledger.
FAKE_TOKEN = "ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # noqa: S105 - synthetic probe
FAKE_SECRET = "password=hunter2"  # noqa: S105 - synthetic probe


# =============================================================================
# Harness
# =============================================================================


def run_guard(payload: dict, *, tmpdir: Path, raw: str | None = None):
    """Invoke the guard exactly as the hook harness does: JSON on stdin, JSON on stdout.

    ``raw`` bypasses ``json.dumps`` so a malformed payload can be delivered byte-for-byte.
    """
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload) if raw is None else raw,
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR": str(tmpdir), "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=60,
    )


def run_bash(session_id: str, command: str, *, tmpdir: Path, cwd: str | None = None):
    payload: dict = {
        "session_id": session_id,
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    if cwd is not None:
        payload["cwd"] = cwd
    return run_guard(payload, tmpdir=tmpdir)


def run_read(session_id: str, file_path: str, *, tmpdir: Path):
    return run_guard(
        {"session_id": session_id, "tool_name": "Read", "tool_input": {"file_path": file_path}},
        tmpdir=tmpdir,
    )


def assert_allow(result) -> None:
    """Allow is silence: exit 0, nothing on stdout. The guard exits 0 on every path."""
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", f"expected an allow (empty stdout), got: {result.stdout!r}"


def assert_deny(result) -> str:
    """Assert the full wire contract of a denial and return the reason (denial-payload §1)."""
    assert result.returncode == 0, result.stderr
    assert result.stdout, "expected a denial payload on stdout, got nothing"
    assert result.stdout.endswith("\n"), "the payload must be newline-terminated"
    assert result.stdout.count("\n") == 1, (
        f"the payload must be a single physical line, got {result.stdout.count(chr(10))}"
    )
    decoder = json.JSONDecoder()
    parsed, consumed = decoder.raw_decode(result.stdout)
    assert result.stdout[consumed:] == "\n", "parsing must consume the whole of stdout"
    specific = parsed["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "deny"
    return specific["permissionDecisionReason"]


def satisfy_register(session_id: str, *, tmpdir: Path) -> None:
    assert_allow(run_read(session_id, REGISTER_PATH, tmpdir=tmpdir))


def satisfy_queue(session_id: str, *, tmpdir: Path) -> None:
    assert_allow(run_bash(session_id, QUEUE_SEARCH, tmpdir=tmpdir))


def satisfy_dedup(session_id: str, *, tmpdir: Path) -> None:
    satisfy_register(session_id, tmpdir=tmpdir)
    satisfy_queue(session_id, tmpdir=tmpdir)


def ledger_bytes(session_id: str, *, tmpdir: Path) -> bytes:
    """The ledger file's RAW BYTES. A secret hides in the field the assertion forgot."""
    path = tmpdir / "spec-kitty-filing-guard" / f"{session_id}.json"
    return path.read_bytes() if path.exists() else b""


def filing(
    *,
    body: str | None = None,
    body_file: str | None = None,
    flags: str = "",
    verb: str = "create",
    repo: str = UPSTREAM_REPO,
) -> str:
    """Build a filing command. Assembled here so no test file quotes one as a literal."""
    parts = ["gh", "issue", verb]
    if verb == "comment":
        parts.append("42")
    parts += ["--repo", repo, "--title", '"T"']
    if body is not None:
        parts += ["--body", f'"{body}"']
    if body_file is not None:
        parts += ["--body-file", body_file]
    if flags:
        parts.append(flags)
    return " ".join(parts)


DRIVER = r'''
import contextlib, io, json, os, sys

spec = json.loads(open(sys.argv[1]).read())
sys.path.insert(0, spec["hooks_dir"])

# The spawn RECORD, and the reason it is a record rather than an exception.
#
# `guard.run()` catches BaseException and converts it into a denial that exits 0, and
# the result loop below catches SystemExit separately. So an AssertionError raised by a
# patched entry point is swallowed into an ordinary denial and leaves `error` None. An
# oracle that reads only `error` — or only the verdict, since twelve of these payloads
# expect a denial anyway — cannot tell "denied correctly" from "denied because it tried
# to spawn and we caught it". MEASURED: a guard mutated to spawn 14 real processes
# produced byte-identical stdout and exit codes on every command.
#
# The list survives the exception. That is the whole fix.
spawned = []

if spec["mode"] == "no-subprocess":
    import subprocess

    def _forbidden(*a, **k):
        spawned.append("patched-entry-point")
        raise AssertionError("the guard spawned a process")

    for _name in (
        "run", "call", "check_call", "check_output", "Popen",
        "getoutput", "getstatusoutput",
    ):
        setattr(subprocess, _name, _forbidden)
    for _name in (
        "system", "popen", "execv", "execvp", "execve", "execl", "execlp", "execlpe",
        "posix_spawn", "posix_spawnp", "spawnv", "spawnvp", "spawnl", "spawnlp", "fork",
    ):
        if hasattr(os, _name):
            setattr(os, _name, _forbidden)

    # Catches a spawn regardless of import spelling or attribute rebinding, which the
    # patch set alone cannot: a module that bound the real callable at import time still
    # trips the hook. An audit hook cannot be removed once installed, which is why it is
    # added HERE in the disposable child process and never in the pytest process.
    #
    # ⚠ NOT total, and an earlier draft of this comment claimed it was. `ctypes` reaches
    # libc directly — `ctypes.CDLL(None).system(b"...")` touches none of the patched
    # attributes and raises none of the audited events, so `spawned` stays empty. Closing
    # that needs `ctypes.*` audit events too, and the honest scope of this oracle is:
    # every spawn route reachable through `subprocess` and `os`.
    _AUDITED = (
        "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
        "os.fork",
    )

    def _audit(event, args):
        if event.startswith(_AUDITED):
            spawned.append(event)

    sys.addaudithook(_audit)

# ⚠ The guard is imported AFTER the patches, deliberately. A mutation spelled
# `from subprocess import run` at guard module scope binds the real callable at import
# time, so a patch installed afterwards would never be seen — which would make the
# red-demonstration pass or fail depending on how the mutation happens to be spelled.
import upstream_filing_guard as guard

if spec["mode"] == "boom":
    def _boom(*a, **k):
        raise RuntimeError("synthetic internal failure")
    guard.read_ledger = _boom

if spec.get("mutate_spawn"):
    # A guard that spawns a process and otherwise behaves perfectly. Used to prove the
    # oracle below is not blind; a real defect would look exactly like this.
    _real_run = guard.run

    def _spawning_run():
        try:
            os.posix_spawn("/bin/echo", ["/bin/echo", "x"], {})
        except BaseException:
            pass
        return _real_run()

    guard.run = _spawning_run

results = []
for payload in spec["payloads"]:
    out = io.StringIO()
    sys.stdin = io.StringIO(json.dumps(payload))
    code = 0
    error = None
    del spawned[:]
    try:
        with contextlib.redirect_stdout(out):
            guard.run()
    except SystemExit as exc:
        code = exc.code or 0
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
    results.append({
        "stdout": out.getvalue(),
        "code": code,
        "error": error,
        "spawned": list(spawned),
    })

open(spec["out"], "w").write(json.dumps(results))
'''


def drive(
    payloads: list[dict], *, mode: str, tmp_path: Path, mutate_spawn: bool = False
) -> list[dict]:
    """Run the guard's real ``run()`` in-process, with one thing patched.

    Needed for two properties a plain subprocess cannot express: an internal raising, and
    proving nothing is ever executed. The *wrapper* and the *wire* are still the code
    under test — only the injected fault is synthetic.
    """
    driver = tmp_path / "driver.py"
    driver.write_text(DRIVER)
    spec = tmp_path / "spec.json"
    out = tmp_path / "out.json"
    spec.write_text(
        json.dumps(
            {
                "hooks_dir": str(HOOKS_DIR),
                "mode": mode,
                "mutate_spawn": mutate_spawn,
                "payloads": payloads,
                "out": str(out),
            }
        )
    )
    proc = subprocess.run(
        [sys.executable, str(driver), str(spec)],
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=60,
    )
    assert proc.returncode == 0, f"driver failed: {proc.stderr}"
    return json.loads(out.read_text())


class _Result:
    """Adapter so ``assert_deny``/``assert_allow`` read a driver result unchanged."""

    def __init__(self, record: dict) -> None:
        self.stdout = record["stdout"]
        self.returncode = record["code"]
        self.stderr = record["error"] or ""


# =============================================================================
# T036 — qa #277: a payload the guard cannot read must DENY, not allow.
# =============================================================================


def test_unparseable_payload_denies(tmp_path: Path) -> None:
    """RED pre-fix: allowed (empty stdout). ``except Exception: allow()`` at ``main()``."""
    result = run_guard({}, tmpdir=tmp_path, raw='{"session_id": "x", ')

    reason = assert_deny(result)
    assert reason.startswith(PARSE_HEADLINE)


def test_empty_stdin_denies(tmp_path: Path) -> None:
    """RED pre-fix: allowed. An empty payload is the everyday shape of a broken pipe."""
    reason = assert_deny(run_guard({}, tmpdir=tmp_path, raw=""))

    assert reason.startswith(PARSE_HEADLINE)


@pytest.mark.parametrize(
    "raw",
    [pytest.param("[]", id="list"), pytest.param('"x"', id="string"), pytest.param("3", id="number")],
)
def test_non_object_payload_denies(raw: str, tmp_path: Path) -> None:
    """Valid JSON that is not an object: ``payload.get`` would raise. RED pre-fix: allowed.

    Distinct from the unparseable case because ``json.load`` SUCCEEDS here — a guard that
    only wrapped the parse call would sail past this one and raise later.
    """
    reason = assert_deny(run_guard({}, tmpdir=tmp_path, raw=raw))

    assert reason.startswith(PARSE_HEADLINE)
    assert "TypeError" in reason


def test_non_object_tool_input_denies(tmp_path: Path) -> None:
    """``tool_input`` present but not an object. RED pre-fix: allowed."""
    result = run_guard(
        {"session_id": "t036", "tool_name": "Bash", "tool_input": "not-an-object"},
        tmpdir=tmp_path,
    )

    reason = assert_deny(result)
    assert reason.startswith(PARSE_HEADLINE)
    assert "TypeError" in reason


def test_unhandled_exception_denies(tmp_path: Path) -> None:
    """NFR-001: an exception ANYWHERE in ``main()`` denies, not just a parse failure.

    ``read_ledger`` is made to raise — a stand-in for any future edit that raises where
    nobody expected it. RED pre-fix: no wrapper existed, so the driver recorded
    ``error: RuntimeError`` and nothing on stdout.
    """
    payload = {
        "session_id": "t036-boom",
        "tool_name": "Bash",
        "tool_input": {"command": filing(body=FOOTERED_BODY)},
    }

    record = drive([payload], mode="boom", tmp_path=tmp_path)[0]

    assert record["error"] is None, f"the exception escaped the wrapper: {record['error']}"
    reason = assert_deny(_Result(record))
    assert reason.startswith(PARSE_HEADLINE)
    assert "RuntimeError" in reason


def test_parse_failure_message_is_not_the_runbook_text(tmp_path: Path) -> None:
    """A broken payload is not a missing dedup step, and must not be reported as one.

    Sending the agent to re-run the sweep for a payload the gate could not read wastes the
    sweep and hides the real fault. Same reasoning that keeps FRESH and CORRUPT apart in
    the session-ledger contract.
    """
    reason = assert_deny(run_guard({}, tmpdir=tmp_path, raw="{oops"))

    assert DEDUP_HEADER not in reason
    assert REGISTER_CAUSE not in reason
    assert QUEUE_CAUSE not in reason
    assert FOOTER_HEADER not in reason


def test_parse_denial_names_exception_class_not_message(tmp_path: Path) -> None:
    """NFR-004: the class, never ``str(exc)`` — which quotes the payload back at the log.

    ``json`` puts the offending text and offset in the message. Rendering it would put
    arbitrary payload content, up to and including a credential, inside a denial.
    """
    reason = assert_deny(run_guard({}, tmpdir=tmp_path, raw='{"token": "' + FAKE_TOKEN))

    assert "JSONDecodeError" in reason
    assert FAKE_TOKEN not in reason
    assert "Unterminated" not in reason and "char " not in reason


def test_parse_denial_carries_a_runnable_line(tmp_path: Path) -> None:
    """denial-payload §3.2: every denial contains something the reader can run.

    An infrastructure failure has no runbook step to re-run, so the runnable remedy is the
    gate's own tests.
    """
    reason = assert_deny(run_guard({}, tmpdir=tmp_path, raw="{oops"))

    assert _runnable_lines(reason), f"no runnable line in:\n{reason}"


def _runnable_lines(reason: str) -> list[str]:
    """denial-payload §3.2's own predicate: a line the reader can paste and run."""
    return [
        line for line in reason.splitlines()
        if line.strip().startswith(("gh ", "spec-kitty ", "python ", ".venv/bin"))
    ]


def test_parse_denial_carries_the_mandatory_closing_block(tmp_path: Path) -> None:
    """denial-payload §3.1: verbatim, in every denial, including this one."""
    reason = assert_deny(run_guard({}, tmpdir=tmp_path, raw="{oops"))

    assert CLOSING_BLOCK in reason
    assert reason.rstrip().endswith("docs/runbooks/spec-kitty-bug-reporting.md")


def test_allow_path_still_allows_with_the_wrapper_in_place(tmp_path: Path) -> None:
    """The wrapper's landmine, pinned: ``allow()`` exits via ``SystemExit``.

    ``SystemExit`` is a ``BaseException``. A wrapper that catches it without re-raising
    turns every allow into a deny — not "fail-closed" but a broken gate that gets switched
    off inside a day. This runs the REAL wire, so the ``__main__`` wrapper is what answers.
    """
    session_id = "t036-allow-path"
    satisfy_dedup(session_id, tmpdir=tmp_path)

    result = run_bash(session_id, filing(body=FOOTERED_BODY), tmpdir=tmp_path)

    assert result.returncode == 0
    assert result.stdout == "", f"the wrapper swallowed an allow: {result.stdout!r}"


def test_main_is_invoked_through_the_failclosed_wrapper() -> None:
    """The ``__main__`` block routes through ``run()``, which is where the wrapper lives.

    Read from the source rather than executed, because the property is about WIRING and
    the two tests above cover the behaviour. It is the cheap half of a pair, not the
    evidence on its own.
    """
    import ast

    tree = ast.parse(GUARD.read_text())
    entry = [node for node in tree.body if isinstance(node, ast.If)]
    called = {
        node.func.id
        for block in entry
        for node in ast.walk(block)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "run" in called, "the module must route __main__ through a fail-closed wrapper"
    assert "main" not in called, "__main__ must not call main() directly, bypassing the wrapper"


def test_corrupt_ledger_denies_and_read_ledger_is_unchanged(tmp_path: Path) -> None:
    """THE TRAP, measured rather than asserted (T036).

    ``read_ledger``'s ``except Exception: return {}`` is the SAME idiom as the qa #277
    defect and is SAFE here, because the consequence runs the other way: no ledger means
    no markers means the gate DENIES. This pins that direction, so a later reader who
    "simplifies" the swallow finds out from a test rather than from a filing that went out
    unchecked.
    """
    session_id = "t036-corrupt-ledger"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    ledger = tmp_path / "spec-kitty-filing-guard" / f"{session_id}.json"
    assert ledger.exists(), "the arrangement is void if no ledger was written"
    ledger.write_text("{not json at all")

    reason = assert_deny(run_bash(session_id, filing(body=FOOTERED_BODY), tmpdir=tmp_path))

    # The dedup causes, not the parse-failure text: a corrupt ledger is indistinguishable
    # from a fresh one here, and this guard has one message path for both.
    assert DEDUP_HEADER in reason
    assert REGISTER_CAUSE in reason
    assert QUEUE_CAUSE in reason
    assert PARSE_HEADLINE not in reason


# =============================================================================
# T037 — qa #276: a body that lives in a file is READ, and checked.
#
# SC-004 is a PAIR and is tested as one. Fixing #276 by dropping the footer check would
# satisfy half of it and destroy the guard.
# =============================================================================


def test_body_file_with_footer_is_allowed(tmp_path: Path) -> None:
    """SC-004, first half. RED pre-fix: DENIED for a footer that was in the file.

    This is qa #276 exactly: the guard matched ``Authored by`` against the literal Bash
    command string, where a file-supplied body never appears.
    """
    session_id = "t037-footered"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    body = tmp_path / "draft.md"
    body.write_text(FOOTERED_BODY)

    result = run_bash(session_id, filing(body_file=str(body)), tmpdir=tmp_path)

    assert_allow(result)


def test_body_file_without_footer_is_denied(tmp_path: Path) -> None:
    """SC-004, second half. Pre-fix this denied too — but for the wrong reason.

    Green before and after, which is exactly why it cannot stand alone: see
    ``test_body_file_denial_names_the_footer_and_not_a_read_failure``.
    """
    session_id = "t037-unfootered"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    body = tmp_path / "draft.md"
    body.write_text(UNFOOTERED_BODY)

    reason = assert_deny(run_bash(session_id, filing(body_file=str(body)), tmpdir=tmp_path))

    assert FOOTER_HEADER in reason


def test_body_file_denial_names_the_footer_and_not_a_read_failure(tmp_path: Path) -> None:
    """The discriminator for the test above: a READ file lacking a footer is a footer fault.

    Without this, "resolution" could be satisfied by never reading the file at all and
    denying everything — which is the pre-fix behaviour wearing a new message.
    """
    session_id = "t037-unfootered-cause"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    body = tmp_path / "draft.md"
    body.write_text(UNFOOTERED_BODY)

    reason = assert_deny(run_bash(session_id, filing(body_file=str(body)), tmpdir=tmp_path))

    assert FOOTER_HEADER in reason
    assert BODY_HEADLINE not in reason
    assert DEDUP_HEADER not in reason


def test_body_file_equals_form_resolved(tmp_path: Path) -> None:
    """``--body-file=<path>``. RED pre-fix: denied."""
    session_id = "t037-equals"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    body = tmp_path / "draft.md"
    body.write_text(FOOTERED_BODY)
    command = f"gh issue create --repo {UPSTREAM_REPO} --title T --body-file={body}"

    assert_allow(run_bash(session_id, command, tmpdir=tmp_path))


def test_short_flag_form_resolved(tmp_path: Path) -> None:
    """``-F <path>``, gh's short form for ``--body-file``. RED pre-fix: denied."""
    session_id = "t037-short-flag"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    body = tmp_path / "draft.md"
    body.write_text(FOOTERED_BODY)
    command = f"gh issue create --repo {UPSTREAM_REPO} --title T -F {body}"

    assert_allow(run_bash(session_id, command, tmpdir=tmp_path))


def test_inline_body_equals_and_short_forms_are_resolved(tmp_path: Path) -> None:
    """``--body=<text>`` and ``-b <text>`` check the literal token, not the whole string.

    The pre-fix substring match happened to be right about these; the argv version has to
    stay right about them, and a narrowing that only understood ``--body <text>`` would
    deny both.
    """
    session_id = "t037-inline-forms"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    one_line = FOOTERED_BODY.replace("\n", " ").strip()

    for command in (
        f'gh issue create --repo {UPSTREAM_REPO} --title T --body="{one_line}"',
        f'gh issue create --repo {UPSTREAM_REPO} --title T -b "{one_line}"',
    ):
        assert_allow(run_bash(session_id, command, tmpdir=tmp_path))


def test_relative_body_file_resolves_against_payload_cwd(tmp_path: Path) -> None:
    """The anchor is ``payload["cwd"]``, never the hook process's cwd. RED pre-fix: denied.

    The hook runs with an unrelated cwd. Anchoring against ``os.getcwd()`` would resolve a
    relative path against the wrong tree and deny a correct filing — the #276 defect
    reappearing one layer down.
    """
    session_id = "t037-relative"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    drafts = tmp_path / "repo" / "docs" / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "issue.md").write_text(FOOTERED_BODY)
    command = filing(body_file="docs/drafts/issue.md")

    result = run_bash(session_id, command, tmpdir=tmp_path, cwd=str(tmp_path / "repo"))

    assert_allow(result)


def test_relative_body_file_without_cwd_denies(tmp_path: Path) -> None:
    """No ``cwd`` in the payload and a relative path: the gate cannot anchor it, so it says so."""
    session_id = "t037-relative-no-cwd"
    satisfy_dedup(session_id, tmpdir=tmp_path)

    reason = assert_deny(
        run_bash(session_id, filing(body_file="docs/drafts/issue.md"), tmpdir=tmp_path)
    )

    assert BODY_HEADLINE in reason
    assert FORM_NO_CWD in reason
    assert FOOTER_HEADER not in reason


def test_missing_body_file_denies(tmp_path: Path) -> None:
    """A path that names nothing. Named as a read failure, never as a missing footer."""
    session_id = "t037-missing"
    satisfy_dedup(session_id, tmpdir=tmp_path)

    reason = assert_deny(
        run_bash(session_id, filing(body_file=str(tmp_path / "nope.md")), tmpdir=tmp_path)
    )

    assert BODY_HEADLINE in reason
    assert FORM_NOT_A_FILE in reason
    assert FOOTER_HEADER not in reason


def test_body_file_that_is_a_directory_denies(tmp_path: Path) -> None:
    """A directory opens without error on some platforms and fails on read on others."""
    session_id = "t037-directory"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    target = tmp_path / "adir"
    target.mkdir()

    reason = assert_deny(run_bash(session_id, filing(body_file=str(target)), tmpdir=tmp_path))

    assert BODY_HEADLINE in reason
    assert FORM_NOT_A_FILE in reason


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores the permission bits")
def test_unreadable_body_file_denies(tmp_path: Path) -> None:
    """``OSError`` on open is a denial naming the error class, not a missing footer."""
    session_id = "t037-unreadable"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    body = tmp_path / "locked.md"
    body.write_text(FOOTERED_BODY)
    body.chmod(0)

    try:
        reason = assert_deny(run_bash(session_id, filing(body_file=str(body)), tmpdir=tmp_path))
    finally:
        body.chmod(stat.S_IRUSR | stat.S_IWUSR)

    assert BODY_HEADLINE in reason
    assert "PermissionError" in reason
    assert FOOTER_HEADER not in reason


def test_undecodable_body_file_denies(tmp_path: Path) -> None:
    """Bytes that are not UTF-8. Denied, named, and never rendered into the message."""
    session_id = "t037-undecodable"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    body = tmp_path / "binary.md"
    body.write_bytes(b"\xff\xfe**Authored by**: nobody")

    reason = assert_deny(run_bash(session_id, filing(body_file=str(body)), tmpdir=tmp_path))

    assert BODY_HEADLINE in reason
    assert FORM_NOT_UTF8 in reason


def test_oversized_body_file_denies(tmp_path: Path) -> None:
    """The read is BOUNDED. An unbounded read of an attacker-chosen path is a new capability.

    The cap is enforced by reading ``cap + 1`` bytes and refusing when the extra byte
    arrives — never by trusting ``st_size``, which is 0 for a FIFO and would make the
    bound infinite exactly where it matters.
    """
    session_id = "t037-oversized"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    body = tmp_path / "huge.md"
    body.write_text("x" * (1024 * 1024 + 1))

    reason = assert_deny(run_bash(session_id, filing(body_file=str(body)), tmpdir=tmp_path))

    assert BODY_HEADLINE in reason
    assert FORM_TOO_LARGE in reason


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs on this platform")
def test_fifo_body_file_denies_without_hanging(tmp_path: Path) -> None:
    """A FIFO with no writer blocks forever on open. ``is_file()`` is what stops it.

    This is the concrete reason the size bound cannot come from ``st_size``: a FIFO
    reports 0, so a ``read(st_size)`` bound is no bound at all — and the process would
    already be blocked in ``open()`` before reaching it. The 60s subprocess timeout is
    part of the assertion: a hang fails this test rather than wedging the run.
    """
    session_id = "t037-fifo"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)

    reason = assert_deny(run_bash(session_id, filing(body_file=str(fifo)), tmpdir=tmp_path))

    assert BODY_HEADLINE in reason
    assert FORM_NOT_A_FILE in reason


def test_denial_never_contains_body_file_contents(tmp_path: Path) -> None:
    """NFR-004: name the path and the error class; never echo what was read.

    A draft body is exactly the kind of text that carries a pasted token, and a denial is
    the least safe place to put one.
    """
    session_id = "t037-no-contents"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    body = tmp_path / "draft.md"
    body.write_text(f"reproduces with {FAKE_TOKEN} and {FAKE_SECRET}\n")

    reason = assert_deny(run_bash(session_id, filing(body_file=str(body)), tmpdir=tmp_path))

    assert FAKE_TOKEN not in reason
    assert FAKE_SECRET not in reason
    assert "reproduces with" not in reason


def test_body_file_toctou_limit_is_stated_in_the_denial(tmp_path: Path) -> None:
    """NFR-002. The guard reads the file; the filing command reads it AGAIN.

    So the gate proves the file contained a footer WHEN CHECKED — not what was posted.
    Stating it is the requirement; a gate that lets the reader assume more than it
    delivers is this mission's own defect class.

    ⚠ THIS TEST WAS A BLIND ORACLE ON ITS FIRST DRAFT and is kept in its corrected form as
    the record. It originally accepted the substring ``re-read``, and it PASSED against the
    unfixed guard — whose dedup section happens to say "Run it, then re-read what you
    drafted", a sentence about the runbook with nothing to do with reading a body file. A
    substring chosen for convenience matched a sentence chosen for a different purpose. The
    assertion is now a phrase that exists nowhere but the TOCTOU statement itself.
    """
    session_id = "t037-toctou"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    body = tmp_path / "draft.md"
    body.write_text(UNFOOTERED_BODY)

    reason = assert_deny(run_bash(session_id, filing(body_file=str(body)), tmpdir=tmp_path))

    assert "not what was posted" in reason


# =============================================================================
# T038 — every dynamic body form DENIES, naming which form was seen.
#
# `shlex` does not expand anything, so a dynamic body survives as a recognisable token.
# That is what makes an honest refusal possible: the guard can SEE that the body is
# dynamic and say so, rather than reporting a footer it never looked for.
# =============================================================================


@pytest.mark.parametrize(
    ("body_expression", "form"),
    [
        pytest.param('"$(cat draft.md)"', FORM_COMMAND_SUBSTITUTION, id="dollar-paren-quoted"),
        pytest.param("$(cat draft.md)", FORM_COMMAND_SUBSTITUTION, id="dollar-paren-bare"),
        pytest.param("`cat draft.md`", FORM_COMMAND_SUBSTITUTION, id="backticks"),
        pytest.param('"$BODY"', FORM_VARIABLE_EXPANSION, id="dollar-var"),
        pytest.param('"${BODY}"', FORM_VARIABLE_EXPANSION, id="dollar-brace-var"),
    ],
)
def test_dynamic_body_denies_naming_the_form(
    body_expression: str, form: str, tmp_path: Path
) -> None:
    """One row per dynamic form. Each denial names THAT form.

    Resolving any of them would mean executing or guessing part of a command the gate is
    deciding whether to permit. Research R-4 rejected ``bash -n``, ``bash -c 'printf %s'``
    and direct evaluation for that reason: a gate that runs its own input is not a gate.
    """
    session_id = "t038-" + form.replace(" ", "-")
    satisfy_dedup(session_id, tmpdir=tmp_path)
    command = f"gh issue create --repo {UPSTREAM_REPO} --title T --body {body_expression}"

    reason = assert_deny(run_bash(session_id, command, tmpdir=tmp_path))

    assert BODY_HEADLINE in reason
    assert form in reason


@pytest.mark.parametrize(
    ("tail", "form"),
    [
        pytest.param("--body-file -", FORM_STDIN, id="body-file-dash"),
        pytest.param("-F -", FORM_STDIN, id="short-body-file-dash"),
        pytest.param("--editor", FORM_EDITOR, id="editor-long"),
        pytest.param("-e", FORM_EDITOR, id="editor-short"),
        pytest.param("--template bug.md", FORM_TEMPLATE, id="template-long"),
        pytest.param("-T bug.md", FORM_TEMPLATE, id="template-short"),
        pytest.param("", FORM_PROMPT, id="no-body-flag"),
        pytest.param(
            '--body "x" --body-file draft.md', FORM_MULTIPLE, id="two-body-sources"
        ),
    ],
)
def test_unobservable_body_form_denies_naming_the_form(
    tail: str, form: str, tmp_path: Path
) -> None:
    """The non-substitution half of the table: stdin, editor, template, prompt, ambiguity."""
    session_id = "t038-" + form.replace(" ", "-")[:40]
    satisfy_dedup(session_id, tmpdir=tmp_path)
    command = f"gh issue create --repo {UPSTREAM_REPO} --title T {tail}".strip()

    reason = assert_deny(run_bash(session_id, command, tmpdir=tmp_path))

    assert BODY_HEADLINE in reason
    assert form in reason


def test_a_flag_belonging_to_another_program_is_not_read_as_this_filing_s(
    tmp_path: Path,
) -> None:
    """Body resolution reads THE FILING'S OWN SEGMENT, never the whole command.

    ``grep -e pattern f && gh issue create … --body-file <valid>`` is the shape that
    matters: ``-e`` is grep's ``--regexp`` and has nothing to do with the filing. A
    resolver that scanned every segment reported this as ``the body is composed in an
    editor`` — a denial naming a flag belonging to a different program, which is worse
    than a wrong verdict because it is a wrong verdict with a confident explanation.

    Segment scoping is what prevents it, and it is easy to lose in a refactor that reaches
    for the flat token list.
    """
    session_id = "t038-foreign-flag"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    body = tmp_path / "draft.md"
    body.write_text(FOOTERED_BODY)
    command = f"grep -e pattern notes.txt && {filing(body_file=str(body))}"

    assert_allow(run_bash(session_id, command, tmpdir=tmp_path))


@pytest.mark.parametrize(
    "wrapper",
    [
        pytest.param("sh -c '{cmd}'", id="sh-dash-c"),
        pytest.param("for i in 1; do {cmd}; done", id="for-loop-body"),
        pytest.param("{{ {cmd}; }}", id="brace-group"),
        pytest.param("{cmd} &", id="backgrounded"),
    ],
)
def test_a_filing_reached_through_shell_syntax_is_still_gated(
    wrapper: str, tmp_path: Path
) -> None:
    """Four ways to invoke a filing that a matcher reading ``argv[0]`` literally misses.

    Each is checked by giving it a body file that does NOT exist: an allow here would mean
    the filing was never evaluated, and a footer-shaped denial would mean it was evaluated
    against the wrong thing. The unreadable-body denial is the one that proves the segment
    reached body resolution.
    """
    session_id = "t039-" + wrapper.split()[0].strip("{")
    satisfy_dedup(session_id, tmpdir=tmp_path)
    command = wrapper.format(cmd=filing(body_file=str(tmp_path / "absent.md")))

    reason = assert_deny(run_bash(session_id, command, tmpdir=tmp_path))

    assert BODY_HEADLINE in reason
    assert FORM_NOT_A_FILE in reason


def test_piped_stdin_body_denies_naming_stdin(tmp_path: Path) -> None:
    """A pipe INTO the filing. The segment after ``|`` is the invocation, and it is gated.

    Worth its own test because the pipe is where a naive whole-string matcher and a
    segment-aware one visibly disagree: the filing is not the first thing in the command.
    """
    session_id = "t038-piped"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    command = f"cat draft.md | gh issue create --repo {UPSTREAM_REPO} --title T -F -"

    reason = assert_deny(run_bash(session_id, command, tmpdir=tmp_path))

    assert BODY_HEADLINE in reason
    assert FORM_STDIN in reason


def test_malformed_quoting_denies(tmp_path: Path) -> None:
    """``shlex`` raising ``ValueError`` means the gate cannot see what the command does.

    It therefore cannot see whether it files, so it refuses. This matches the sibling
    lifecycle gate, which denies on the same condition for the same reason.
    """
    reason = assert_deny(
        run_bash("t038-malformed", 'gh issue create --title "unterminated', tmpdir=tmp_path)
    )

    assert TOKENISE_HEADLINE in reason
    assert CLOSING_BLOCK in reason


def test_dynamic_repo_denies_naming_the_repo(tmp_path: Path) -> None:
    """THE DELIBERATE WIDENING (research R-4 open risk), asserted so it is not a side effect.

    A ``--repo`` value the gate cannot resolve cannot be shown to be non-upstream, so the
    filing denies. Pre-fix this ALLOWED, because ``Priivacy-ai/`` was not a substring of
    the command. Token-position matching is more accurate in both directions, and this is
    the direction that costs something.

    The message names the REPOSITORY as the unresolvable part. Naming the footer here
    would send the author to fix a thing that is not wrong.
    """
    session_id = "t038-dynamic-repo"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    command = 'gh issue create --repo "$REPO" --title T --body "b"'

    reason = assert_deny(run_bash(session_id, command, tmpdir=tmp_path))

    assert REPO_HEADLINE in reason
    assert FOOTER_HEADER not in reason
    assert BODY_HEADLINE not in reason


def test_dynamic_body_denial_does_not_say_missing_footer(tmp_path: Path) -> None:
    """FR-009: name the step, not the failure.

    Reporting "missing footer" for a body the gate never read is today's behaviour and it
    is misleading — it sends the author to add a footer that is already there. That is how
    #276 wasted two filings before it was diagnosed.
    """
    session_id = "t038-not-a-footer-fault"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    command = f'gh issue create --repo {UPSTREAM_REPO} --title T --body "$(cat d.md)"'

    reason = assert_deny(run_bash(session_id, command, tmpdir=tmp_path))

    assert FOOTER_HEADER not in reason
    assert "missing from the body" not in reason
    assert "**Authored by**: Kent Gale & <agent, model>, <date>" not in reason


def test_dynamic_body_denial_offers_the_resolvable_alternative(tmp_path: Path) -> None:
    """Every dynamic-form denial shows the form that WOULD work, as a runnable line."""
    session_id = "t038-alternative"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    command = f'gh issue create --repo {UPSTREAM_REPO} --title T --body "$BODY"'

    reason = assert_deny(run_bash(session_id, command, tmpdir=tmp_path))

    assert "--body-file" in reason
    assert "docs/drafts/" in reason
    assert any(line.strip().startswith("gh ") for line in reason.splitlines())


def test_guard_never_invokes_a_subprocess(tmp_path: Path) -> None:
    """Nothing in the guard executes anything, over the WHOLE denial matrix.

    Running a substring of a command you are deciding whether to permit is an
    arbitrary-execution hole inside a security gate. Asserted by making every execution
    entry point raise and driving the full matrix through it, rather than by reading the
    source and concluding there is no call.
    """
    body = tmp_path / "draft.md"
    body.write_text(FOOTERED_BODY)
    commands = [
        filing(body=FOOTERED_BODY),
        filing(body=UNFOOTERED_BODY),
        filing(body_file=str(body)),
        filing(body_file=str(tmp_path / "nope.md")),
        f'gh issue create --repo {UPSTREAM_REPO} --title T --body "$(cat d.md)"',
        f"gh issue create --repo {UPSTREAM_REPO} --title T --body `cat d.md`",
        f'gh issue create --repo {UPSTREAM_REPO} --title T --body "$BODY"',
        f"gh issue create --repo {UPSTREAM_REPO} --title T -F -",
        f"gh issue create --repo {UPSTREAM_REPO} --title T --editor",
        f"gh issue create --repo {UPSTREAM_REPO} --title T",
        'gh issue create --repo "$REPO" --title T --body "b"',
        'gh issue create --title "unterminated',
        QUEUE_SEARCH,
        f"echo {json.dumps(QUEUE_SEARCH)}",
        "ls docs/spec-kitty-issues.md",
    ]
    payloads = [
        {
            "session_id": "t038-no-exec",
            "cwd": str(tmp_path),
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        for command in commands
    ]

    records = drive(payloads, mode="no-subprocess", tmp_path=tmp_path)

    # ⚠ The assertion is the RECORD, not the escaped exception, and not the verdict.
    # `run()` catches BaseException and denies, so an injected AssertionError never
    # reaches `error` — the previous form of this test could not fail. Twelve of these
    # payloads expect a denial anyway, so asserting the verdict is no better: a spawn on
    # any denial-bound path produces exactly the expected output.
    # `test_the_no_subprocess_oracle_can_actually_fail` pins that this still detects.
    attempts = {i: r["spawned"] for i, r in enumerate(records) if r["spawned"]}
    assert not attempts, (
        f"the guard attempted to execute something: {attempts}. Running any part of a "
        "command you are deciding whether to permit is arbitrary execution inside a "
        "security gate"
    )

    escaped = [record["error"] for record in records if record["error"]]
    assert not escaped, f"the guard raised out of its own wrapper: {escaped}"


def test_the_no_subprocess_oracle_can_actually_fail(tmp_path: Path) -> None:
    """The oracle above must detect a guard that really does spawn.

    Without this, `test_guard_never_invokes_a_subprocess` is unfalsifiable and its green
    means nothing. MEASURED before the record was added: a guard mutated to spawn on all
    15 payloads produced byte-identical stdout and exit codes, and the test passed.

    ⚠ What this proves, exactly — an earlier version of this docstring overstated it.
    `os.posix_spawn` was not in the patch set BEFORE this change; it is now. So the
    interception here comes from the PATCH SET, not from the audit hook: `_forbidden`
    fires, records, and raises, and no process is ever created. This test therefore
    proves the record survives the swallow — which is the fix — and says nothing about
    the audit hook. `test_the_audit_hook_sees_a_spawn_the_patch_set_would_miss` covers
    that half separately, because a primitive that is both patched and audited can never
    exercise the hook.
    """
    payloads = [
        {
            "session_id": "t038-oracle-check",
            "cwd": str(tmp_path),
            "tool_name": "Bash",
            "tool_input": {"command": filing(body=FOOTERED_BODY)},
        }
    ]

    clean = drive(payloads, mode="no-subprocess", tmp_path=tmp_path)
    mutant = drive(
        payloads, mode="no-subprocess", tmp_path=tmp_path, mutate_spawn=True
    )

    assert not clean[0]["spawned"], "the unmutated guard recorded a spawn"
    assert mutant[0]["spawned"], (
        "a guard that spawns a process was not detected — the oracle is blind again"
    )
    # The mutant is invisible to the OLD oracle. Note WHY, precisely: `error` is None
    # because the mutation swallows its own exception, not because `run()` swallowed it.
    # Both routes produce the same blindness, but only one of them is what this line
    # measures, and an earlier comment here attributed it to the wrong one.
    assert mutant[0]["error"] is None, (
        "the mutant should be indistinguishable by the OLD oracle; if it raises out, "
        "this test is no longer demonstrating the blindness it exists to demonstrate"
    )


def test_the_audit_hook_sees_a_spawn_the_patch_set_would_miss(tmp_path: Path) -> None:
    """The audit hook must be measured, or it is decoration.

    A pre-merge review established that deleting `sys.addaudithook` from the driver
    leaves the suite green, because every primitive the mutation could reach is also
    patched — so the hook's contribution was unmeasured in BOTH directions.

    This measures it in the direction that matters: with NO patches installed, does the
    hook's own predicate record a real spawn? If this goes red the hook is not covering
    what its comment claims, and the honest response is to delete it rather than keep an
    unmeasured mechanism that reads like protection.
    """
    probe = tmp_path / "audit_probe.py"
    probe.write_text(
        "import json, subprocess, sys\n"
        "spawned = []\n"
        "_AUDITED = (\n"
        '    "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn",\n'
        '    "os.fork",\n'
        ")\n"
        "def _audit(event, args):\n"
        "    if event.startswith(_AUDITED):\n"
        "        spawned.append(event)\n"
        "sys.addaudithook(_audit)\n"
        # No patches at all — a real process really runs, exactly as an undetected
        # defect would run one.
        'subprocess.run(["/bin/echo", "x"], capture_output=True)\n'
        'print(json.dumps(spawned))\n'
    )
    proc = subprocess.run(
        [sys.executable, str(probe)], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    recorded = json.loads(proc.stdout.strip().splitlines()[-1])
    assert recorded, (
        "the audit hook recorded nothing for a real subprocess.run — its predicate does "
        "not match the events CPython actually raises, so it is protecting nothing"
    )


# =============================================================================
# T039 — argv parsing kills the false positive AND the fakeable marker.
# =============================================================================


def test_quoted_mention_of_a_filing_command_is_allowed(tmp_path: Path) -> None:
    """DEFECT 3. RED pre-fix: DENIED, because the phrase was a substring of the command.

    Under ``shlex`` the whole phrase is a single ARGUMENT to ``echo``, so a check on token
    position is immune to it. This is not hypothetical: it blocked a sibling agent's
    file-authoring command twice in the session that produced this mission.
    """
    mention = filing(body=UNFOOTERED_BODY)
    command = f"echo {json.dumps(mention)}"

    assert_allow(run_bash("t039-mention", command, tmpdir=tmp_path))


def test_multiline_authoring_command_quoting_a_filing_is_allowed(tmp_path: Path) -> None:
    """The same defect in the shape it actually arrived in: a MULTI-LINE authoring command.

    A single-line ``echo`` and a multi-line heredoc-ish write are different code paths —
    ``shlex`` never emits a newline token, so line handling happens before tokenising.
    A fix validated only on one line would be validated against a construction that is not
    the one that bit.
    """
    mention = filing(body=UNFOOTERED_BODY)
    command = "\n".join(
        [
            "printf '%s\\n' " + json.dumps("# Draft"),
            "printf '%s\\n' " + json.dumps(f"Run: {mention}"),
            "printf '%s\\n' " + json.dumps("Then wait for approval."),
        ]
    )

    assert_allow(run_bash("t039-multiline-mention", command, tmpdir=tmp_path))


def test_echo_does_not_set_queue_marker(tmp_path: Path) -> None:
    """DEFECT 4. RED pre-fix: the marker was set and the later filing was ALLOWED.

    MEASURED live: a session ledger read ``{"queue": true, "register": true,
    "intent": true}`` with none of the three steps run — every one set by an authoring
    command that quoted the query as a literal.
    """
    session_id = "t039-echo-queue"
    satisfy_register(session_id, tmpdir=tmp_path)
    assert_allow(run_bash(session_id, f"echo {json.dumps(QUEUE_SEARCH)}", tmpdir=tmp_path))

    reason = assert_deny(run_bash(session_id, filing(body=FOOTERED_BODY), tmpdir=tmp_path))

    assert QUEUE_CAUSE in reason
    assert b'"queue"' not in ledger_bytes(session_id, tmpdir=tmp_path)


def test_printf_does_not_set_queue_marker(tmp_path: Path) -> None:
    """The allowlist is why ``printf`` is covered. A denylist of ``echo`` would miss it.

    Also ``:``, ``true``, a comment and a heredoc. Naming the one program that bit is how
    a guard gets a hole the size of every other program.
    """
    session_id = "t039-printf-queue"
    satisfy_register(session_id, tmpdir=tmp_path)
    command = "printf '%s\\n' " + json.dumps(QUEUE_SEARCH)
    assert_allow(run_bash(session_id, command, tmpdir=tmp_path))

    reason = assert_deny(run_bash(session_id, filing(body=FOOTERED_BODY), tmpdir=tmp_path))

    assert QUEUE_CAUSE in reason


@pytest.mark.parametrize("program", ["true", ":"])
def test_shell_builtins_do_not_set_the_queue_marker(program: str, tmp_path: Path) -> None:
    """Two more programs a denylist of ``echo`` would not have covered."""
    session_id = f"t039-builtin-{program.replace(':', 'colon')}"
    satisfy_register(session_id, tmpdir=tmp_path)
    assert_allow(
        run_bash(session_id, f"{program} {json.dumps(QUEUE_SEARCH)}", tmpdir=tmp_path)
    )

    reason = assert_deny(run_bash(session_id, filing(body=FOOTERED_BODY), tmpdir=tmp_path))

    assert QUEUE_CAUSE in reason


@pytest.mark.parametrize("program", ["ls", "touch", "stat"])
def test_naming_the_register_without_reading_it_does_not_mark(
    program: str, tmp_path: Path
) -> None:
    """``ls``/``touch``/``stat`` NAME the register. None of them reads it.

    The allowlist is the mechanism: an ``argv[0]`` that is not a known reader earns
    nothing, which means the gate denies and the agent reads the register for real.
    """
    session_id = f"t039-{program}-register"
    satisfy_queue(session_id, tmpdir=tmp_path)
    assert_allow(run_bash(session_id, f"{program} docs/spec-kitty-issues.md", tmpdir=tmp_path))

    reason = assert_deny(run_bash(session_id, filing(body=FOOTERED_BODY), tmpdir=tmp_path))

    assert REGISTER_CAUSE in reason
    assert QUEUE_CAUSE not in reason, "the queue was satisfied; it must not be named"


def test_filing_after_double_ampersand_is_gated(tmp_path: Path) -> None:
    """A filing chained after ``&&`` is a real invocation and must be seen.

    Segment splitting is what makes this work; a matcher that only looked at ``argv[0]``
    of the whole command would allow it.
    """
    session_id = "t039-chained"
    command = f"true && {filing(body=UNFOOTERED_BODY)}"

    reason = assert_deny(run_bash(session_id, command, tmpdir=tmp_path))

    assert DEDUP_HEADER in reason


def test_env_prefixed_filing_is_gated(tmp_path: Path) -> None:
    """``NAME=VALUE`` prefixes hide ``argv[0]`` from a matcher that reads it literally."""
    session_id = "t039-env-prefixed"
    command = f"GH_HOST=github.com {filing(body=UNFOOTERED_BODY)}"

    reason = assert_deny(run_bash(session_id, command, tmpdir=tmp_path))

    assert DEDUP_HEADER in reason


def test_multiline_filing_is_gated(tmp_path: Path) -> None:
    """A filing on the SECOND line of a multi-line command. The line break is the operator.

    This is the construction the mutation table's M3 mutant could not see, and it is the
    reason this module drives the real wire with multi-line commands rather than testing
    the matcher's return value: a false premise shared by the implementation and its
    tests is invisible to mutation.
    """
    session_id = "t039-multiline-filing"
    command = "\n".join([
        "echo 'about to file'",
        filing(body=UNFOOTERED_BODY),
    ])

    reason = assert_deny(run_bash(session_id, command, tmpdir=tmp_path))

    assert DEDUP_HEADER in reason


def test_multiline_echo_mention_does_not_mark(tmp_path: Path) -> None:
    """The marker side of the multi-line case: mentions on several lines earn nothing."""
    session_id = "t039-multiline-mention"
    satisfy_register(session_id, tmpdir=tmp_path)
    command = "\n".join([
        f"echo {json.dumps(QUEUE_SEARCH)}",
        "echo " + json.dumps("python scripts/upstream_dedup.py --mechanism foo"),
        "echo " + json.dumps("git grep -n mechanism -- tests/"),
    ])
    assert_allow(run_bash(session_id, command, tmpdir=tmp_path))

    reason = assert_deny(run_bash(session_id, filing(body=FOOTERED_BODY), tmpdir=tmp_path))

    assert QUEUE_CAUSE in reason
    ledger = ledger_bytes(session_id, tmpdir=tmp_path)
    assert b'"queue"' not in ledger
    assert b'"intent"' not in ledger


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(QUEUE_SEARCH, id="gh-issue-list"),
        pytest.param(
            'gh search issues "symptom" --repo Priivacy-ai/spec-kitty --state all',
            id="gh-search-issues",
        ),
        pytest.param("gh issue view 3728 --repo Priivacy-ai/spec-kitty", id="gh-issue-view"),
        pytest.param('python scripts/upstream_dedup.py --query "s"', id="dedup-script"),
        pytest.param(
            '.venv/bin/python scripts/upstream_dedup.py --query "s"', id="dedup-venv-python"
        ),
        pytest.param("true && " + QUEUE_SEARCH, id="chained-after-and"),
    ],
)
def test_real_queue_search_still_marks(command: str, tmp_path: Path, request) -> None:
    """The narrowing must not eat the real thing. Six genuine dedup invocations.

    The pair to the mention tests: a fix that stopped ``echo`` from marking by refusing to
    mark at all would pass every test above this one and destroy the guard's usefulness.
    """
    session_id = request.node.name
    satisfy_register(session_id, tmpdir=tmp_path)
    assert_allow(run_bash(session_id, command, tmpdir=tmp_path))

    assert_allow(run_bash(session_id, filing(body=FOOTERED_BODY), tmpdir=tmp_path))


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("cat docs/spec-kitty-issues.md", id="cat"),
        pytest.param("grep -n 3728 docs/spec-kitty-issues.md", id="grep"),
        pytest.param("rg 3728 docs/spec-kitty-issues.md", id="rg"),
        pytest.param("head -50 docs/spec-kitty-issues.md", id="head"),
        pytest.param("sed -n '1,50p' docs/spec-kitty-issues.md", id="sed"),
        pytest.param("git show HEAD:docs/spec-kitty-issues.md", id="git-show"),
    ],
)
def test_real_register_reads_still_mark(command: str, tmp_path: Path, request) -> None:
    """The register allowlist's positive half, one row per reader named in the WP table."""
    session_id = request.node.name
    satisfy_queue(session_id, tmpdir=tmp_path)
    assert_allow(run_bash(session_id, command, tmpdir=tmp_path))

    assert_allow(run_bash(session_id, filing(body=FOOTERED_BODY), tmpdir=tmp_path))


def test_read_tool_on_register_still_marks(tmp_path: Path) -> None:
    """The ``Read``/``Grep``/``Glob`` branch is untouched: a real tool call is real evidence."""
    session_id = "t039-read-tool"
    satisfy_queue(session_id, tmpdir=tmp_path)
    satisfy_register(session_id, tmpdir=tmp_path)

    assert_allow(run_bash(session_id, filing(body=FOOTERED_BODY), tmpdir=tmp_path))


def test_intent_marker_needs_a_real_program(tmp_path: Path) -> None:
    """The advisory intent paragraph is driven by the same allowlist.

    A mention cannot silence it either — which matters because a silenced advisory reads
    as a satisfied one.
    """
    session_id = "t039-intent"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    assert_allow(
        run_bash(
            session_id,
            "echo " + json.dumps("git grep -n mechanism -- tests/"),
            tmpdir=tmp_path,
        )
    )

    reason = assert_deny(run_bash(session_id, filing(body=UNFOOTERED_BODY), tmpdir=tmp_path))

    assert "INTENT CHECK (step 2d)" in reason


def test_real_intent_check_marks(tmp_path: Path) -> None:
    """Its pair: a genuine ``git grep`` over a test path does mark, so the paragraph goes."""
    session_id = "t039-intent-real"
    satisfy_dedup(session_id, tmpdir=tmp_path)
    assert_allow(run_bash(session_id, 'git grep -n "mechanism" -- tests/', tmpdir=tmp_path))

    reason = assert_deny(run_bash(session_id, filing(body=UNFOOTERED_BODY), tmpdir=tmp_path))

    assert "INTENT CHECK (step 2d)" not in reason
    assert FOOTER_HEADER in reason


def test_docstring_states_the_pretooluse_marking_limit() -> None:
    """NFR-002/C-004. The residual, stated rather than discovered by the next reader.

    A real queue search still marks even if it returns nothing, because ``PreToolUse``
    sees an INTENDED command and cannot know it will succeed. What this WP removed is
    mention-shaped evidence, not deliberate circumvention. Claiming otherwise would put
    the mission's own defect class inside the mechanism built to prevent it.
    """
    docstring = _guard_docstring()

    assert "PreToolUse" in docstring
    assert "intended" in docstring.lower(), (
        "the guard's docstring must state the PreToolUse marking limit"
    )


def test_docstring_states_the_body_file_toctou_limit() -> None:
    """NFR-002. The file is read twice — once by the gate, once by the filing command."""
    docstring = _guard_docstring()

    assert "TOCTOU" in docstring or "re-read" in docstring, (
        "the guard's docstring must state the body-file TOCTOU limit"
    )


def _guard_docstring() -> str:
    import ast

    return ast.get_docstring(ast.parse(GUARD.read_text())) or ""


# =============================================================================
# T040 — the wire contract and the secrets sweep, over the WHOLE denial matrix.
# =============================================================================


def _denial_matrix(tmp_path: Path) -> list[str]:
    """One command per denial path the guard can take."""
    body = tmp_path / "unfootered.md"
    body.write_text(UNFOOTERED_BODY)
    return [
        filing(body=UNFOOTERED_BODY),  # footer missing
        filing(body=FOOTERED_BODY),  # dedup missing
        filing(body_file=str(body)),  # footer missing, from a file
        filing(body_file=str(tmp_path / "nope.md")),  # unreadable
        filing(body_file="relative.md"),  # relative, no cwd
        f'gh issue create --repo {UPSTREAM_REPO} --title T --body "$(cat d.md)"',
        f'gh issue create --repo {UPSTREAM_REPO} --title T --body "$BODY"',
        f"gh issue create --repo {UPSTREAM_REPO} --title T -F -",
        f"gh issue create --repo {UPSTREAM_REPO} --title T --editor",
        f"gh issue create --repo {UPSTREAM_REPO} --title T -T bug.md",
        f"gh issue create --repo {UPSTREAM_REPO} --title T",
        'gh issue create --repo "$REPO" --title T --body "b"',
        'gh issue create --title "unterminated',
    ]


def test_every_denial_satisfies_the_wire_contract(tmp_path: Path) -> None:
    """denial-payload §1, over every path: one line, ``json.loads`` consumes it, exit 0.

    A stray print makes the JSON unparseable and the deny is silently LOST — the guard
    reports nothing and the filing proceeds. That is the fail-open this mission removes,
    reintroduced by a debug line.
    """
    for index, command in enumerate(_denial_matrix(tmp_path)):
        result = run_bash(f"t040-wire-{index}", command, tmpdir=tmp_path)
        reason = assert_deny(result)
        assert reason, f"empty reason for: {command}"
        assert CLOSING_BLOCK in reason, f"no closing block for: {command}"


def test_no_denial_emits_an_allow_decision(tmp_path: Path) -> None:
    """Silence is the allow. An explicit allow can OVERRIDE another layer's decision.

    This guard is only ever entitled to say no, so ``permissionDecision`` must never carry
    the affirmative value on any path — including the allow paths, which write nothing.
    """
    commands = _denial_matrix(tmp_path) + [QUEUE_SEARCH, "ls docs/", filing(body=FOOTERED_BODY)]

    for index, command in enumerate(commands):
        result = run_bash(f"t040-noallow-{index}", command, tmpdir=tmp_path)
        assert '"allow"' not in result.stdout, f"explicit allow emitted for: {command}"


def test_every_denial_carries_a_runnable_line(tmp_path: Path) -> None:
    """denial-payload §3.2 over the whole matrix: a denial with no command in it is not a step."""
    for index, command in enumerate(_denial_matrix(tmp_path)):
        reason = assert_deny(run_bash(f"t040-runnable-{index}", command, tmpdir=tmp_path))
        assert _runnable_lines(reason), f"no runnable line in the denial for: {command}\n{reason}"


def test_the_footer_only_denial_carries_a_runnable_line(tmp_path: Path) -> None:
    """The matrix above cannot see this one, and that is why it is written out separately.

    Every command in ``_denial_matrix`` runs in a FRESH session, so every denial it
    produces carries the dedup section — and the dedup section supplies the runnable line.
    A footer-only denial (dedup already satisfied) is the one denial that has no other
    section to borrow from, and pre-fix it contained no runnable line at all: it named the
    template to copy but never the command to re-file with.

    A quantified assertion whose arrangement makes one case unreachable is a green nobody
    earned; this is that case, arranged so it is reached.
    """
    session_id = "t040-footer-only-runnable"
    satisfy_dedup(session_id, tmpdir=tmp_path)

    reason = assert_deny(run_bash(session_id, filing(body=UNFOOTERED_BODY), tmpdir=tmp_path))

    assert DEDUP_HEADER not in reason, "the arrangement is void if the dedup section is present"
    assert FOOTER_HEADER in reason
    assert _runnable_lines(reason), f"no runnable line in the footer-only denial:\n{reason}"


def test_no_secret_reaches_a_denial_or_the_ledger_bytes(tmp_path: Path) -> None:
    """NFR-004, over the whole matrix, with the ledger checked as BYTES.

    The ledger is grepped rather than parsed because a secret hides in the field the
    assertion forgot to look at — parsing to a dict and checking known keys checks only
    the keys you thought of.
    """
    for index, command in enumerate(_denial_matrix(tmp_path)):
        session_id = f"t040-secret-{index}"
        spiked = f"GH_TOKEN={FAKE_TOKEN} {command} # {FAKE_SECRET}"
        result = run_bash(session_id, spiked, tmpdir=tmp_path, cwd=str(tmp_path))

        if result.stdout:
            reason = assert_deny(result)
            assert FAKE_TOKEN not in reason, f"token leaked for: {command}"
            assert FAKE_SECRET not in reason, f"secret leaked for: {command}"

        raw = ledger_bytes(session_id, tmpdir=tmp_path)
        assert FAKE_TOKEN.encode() not in raw, f"token reached the ledger for: {command}"
        assert FAKE_SECRET.encode() not in raw, f"secret reached the ledger for: {command}"


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(
            f"gh pr create --repo {UPSTREAM_REPO} --title T --body b", id="pr-create"
        ),
        pytest.param(f"gh issue list --repo {UPSTREAM_REPO}", id="issue-list"),
        pytest.param("ls docs/", id="unrelated-command"),
    ],
)
def test_the_gate_is_still_scoped_to_upstream_issue_filings(
    command: str, tmp_path: Path
) -> None:
    """The narrowing did not widen the SCOPE: non-issue commands still allow.

    Stated from this side as well as WP02's, because argv parsing rewrote both halves of
    the scoping test and a rewrite that quietly gated ``gh pr create`` would pass every
    other test in this module.

    ⚠ PARAMETERISED, not a ``for`` loop, and the shape is load-bearing. A fourth case,
    ``gh issue create --repo octocat/hello``, sat here asserting ALLOW and has MOVED — not
    been deleted — to :func:`test_an_unrecognised_repository_is_now_gated_as_upstream`
    directly below, where it is pinned as a DENY. These three are about the guard's REMIT
    and did not move; that one was about ownership CLASSIFICATION and did. A loop could
    not have expressed the partial flip: its cheapest edit is to delete the line, which
    loses the assertion instead of re-pinning it.
    """
    assert_allow(run_bash("t040-scope", command, tmpdir=tmp_path))


def test_an_unrecognised_repository_is_now_gated_as_upstream(tmp_path: Path) -> None:
    """The flipped half of the case above: ``octocat/hello`` is now DENIED (FR-002).

    Deliberate, and justified by a requirement rather than by the new code: an
    unrecognised repository is treated as upstream, because the edge case the mission
    exists for — a repository under our OWN organisation that is neither ours nor a known
    upstream — must fall to the enforcing side rather than through the gap. There is no
    way to close that gap for ``spec-kitty/spec-kitty-saas`` and leave it open for
    ``octocat/hello``; "unrecognised" is one class.

    ⚠ RESIDUE, recorded so the next reader is not surprised: a filing into an unrelated
    third-party repository now demands this project's register and template, which is not
    what its author would expect to be asked for. Accepted for its failure direction —
    enforcing rather than silent — and recorded in ``research.md`` A-17.
    """
    reason = assert_deny(
        run_bash(
            "t040-unrecognised",
            "gh issue create --repo octocat/hello --title T --body b",
            tmpdir=tmp_path,
        )
    )

    assert "octocat/hello" in reason, "the denial must name the target it judged"
    assert "not in the set we own" in reason
    assert "Priivacy-ai" not in reason, "the retired organisation prefix must not reappear"
