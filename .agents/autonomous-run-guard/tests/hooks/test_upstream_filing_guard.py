r"""Characterisation tests for ``scripts/hooks/upstream_filing_guard.py``.

The guard shipped in August 2026 with **zero** test coverage — measured:
``grep -rl 'scripts/hooks\|filing_guard' tests/`` returned no files. The pattern the
mission-lifecycle-gate mission calls "the proven pattern" was proven by field use, not
by tests. This module is the missing baseline: it pins the behaviour WP07 is about to
change, so that a fix is distinguishable from a weakening of the check.

SCOPE — WHAT IS HERE AND WHAT DELIBERATELY IS NOT
-------------------------------------------------
Only the guard's **correct** behaviours are pinned here (subtasks T005-T008): the allow
path, and the three denial causes. Every assertion in this module is one that stays
TRUE after WP07's fixes land.

The guard's two known **defects** are NOT pinned here, on purpose:

  * **qa #277** — a malformed hook payload fails *open* (``upstream_filing_guard.py``,
    the ``except Exception: allow()`` in ``main()``), violating NFR-001.
  * **qa #276** — the attribution footer is matched against the raw Bash command string,
    so a ``--body-file`` filing is denied for a footer the guard cannot see.

Those live in **WP07** as red-first tests asserting the *correct* behaviour. Writing
them here as "pins the current, defective behaviour" would mean WP07 had to invert tests
in a file it does not own, which collapses WP02 and WP07 into one lane that WP03 already
depends on — a self-dependency, i.e. register row #3431's lane-cycle defect reproducing
on this build. So the split is structural, not stylistic. **Do not add defect-pinning
tests to this file.**

Two further current behaviours are known to be defective and are therefore also absent,
recorded here so a reader does not mistake the omission for an oversight:

  * a single Bash call that both sets the ``queue`` marker and *is* the filing currently
    satisfies the gate against evidence it produced in the same event (markers come from
    ``PreToolUse`` command text, i.e. from intent rather than execution — the defect
    FR-010 removes);
  * ``echo "gh issue list …"`` currently sets the ``queue`` marker, and ``echo "… gh
    issue create …"`` is currently denied — both artefacts of substring matching that
    WP07 replaces with ``shlex`` argv parsing.

INVOCATION IS A SUBPROCESS, NOT AN IMPORT — three reasons, none stylistic:
  * the guard calls ``sys.exit()`` on every path;
  * the deliverable is a **wire contract** (single-line JSON on stdout, exit 0), and only
    a subprocess measures stdout and the exit code the way the hook harness does;
  * ``LEDGER_DIR`` is computed at *module import time* from ``tempfile.gettempdir()``, so
    an imported module would pin one ledger path for the whole session and let tests
    contaminate one another.

Ledger isolation therefore rides on ``TMPDIR``, which ``tempfile.gettempdir()`` honours.
``test_ledger_is_isolated_to_tmp_path`` proves the isolation actually takes effect before
any other result in this module is believed — without it, an "allow" here could be an
allow inherited from the developer's own ``/tmp`` ledger.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "hooks" / "upstream_filing_guard.py"

# --- fragments of the rendered denial, chosen to DISCRIMINATE causes ---------
# Asserted as literals against the rendered string, never imported from the guard: a test
# that finds the guard's own constant in the guard's own output has checked nothing.
DEDUP_HEADER = "DEDUP (step 2) — no trace of it in this session:"
REGISTER_CAUSE = "docs/spec-kitty-issues.md was not read"
QUEUE_CAUSE = "the upstream queue was not searched"
FOOTER_HEADER = "FOOTER (step 4) — missing from the body:"
FOOTER_TEMPLATE_AUTHOR = "**Authored by**: Kent Gale & <agent, model>, <date>"
FOOTER_TEMPLATE_APPROVER = "**Submission approved by**: Kent Gale, <date>"
INTENT_PARAGRAPH = "INTENT CHECK (step 2d) — no trace in this session. NOT blocking"
CLOSING_BLOCK = "never by adding a token command"

# A body carrying the attribution footer, as an agent would actually write it.
FOOTERED_BODY = "**Authored by**: Kent Gale & Claude, 2026-08-25"
UNFOOTERED_BODY = "the symptom reproduces on build abc1234"

REGISTER_PATH = "/repo/docs/spec-kitty-issues.md"
QUEUE_SEARCH = 'gh issue list --repo Priivacy-ai/spec-kitty --search "symptom" --state all'


def run_guard(payload: dict, *, tmpdir: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the guard exactly as the hook harness does: JSON on stdin, JSON on stdout."""
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR": str(tmpdir)},
    )


def run_bash(session_id: str, command: str, *, tmpdir: Path) -> subprocess.CompletedProcess[str]:
    return run_guard(
        {"session_id": session_id, "tool_name": "Bash", "tool_input": {"command": command}},
        tmpdir=tmpdir,
    )


def run_read(session_id: str, file_path: str, *, tmpdir: Path) -> subprocess.CompletedProcess[str]:
    return run_guard(
        {"session_id": session_id, "tool_name": "Read", "tool_input": {"file_path": file_path}},
        tmpdir=tmpdir,
    )


def filing_command(body: str, *, verb: str = "create", repo: str = "Priivacy-ai/spec-kitty") -> str:
    if verb == "comment":
        return f'gh issue comment 42 --repo {repo} --body "{body}"'
    return f'gh issue create --repo {repo} --title "T" --body "{body}"'


def assert_allow(result: subprocess.CompletedProcess[str]) -> None:
    """Allow is *silence*: exit 0 with nothing on stdout.

    Asserting emptiness and not merely the exit code matters — the guard exits 0 on every
    path, including denial, so an exit-code-only assertion cannot tell allow from deny.
    """
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", f"expected an allow (empty stdout), got: {result.stdout!r}"


def assert_deny(result: subprocess.CompletedProcess[str]) -> str:
    """Assert the wire contract of a denial and return the reason for content assertions."""
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "expected a denial payload on stdout, got nothing"
    assert len(result.stdout.strip().splitlines()) == 1, "the payload must be single-line JSON"
    payload = json.loads(result.stdout)
    specific = payload["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "deny"
    return specific["permissionDecisionReason"]


def satisfy_register(session_id: str, *, tmpdir: Path) -> None:
    assert_allow(run_read(session_id, REGISTER_PATH, tmpdir=tmpdir))


def satisfy_queue(session_id: str, *, tmpdir: Path) -> None:
    assert_allow(run_bash(session_id, QUEUE_SEARCH, tmpdir=tmpdir))


# =============================================================================
# Harness verification — prove the isolation before believing any other result.
# =============================================================================


def test_ledger_is_isolated_to_tmp_path(tmp_path: Path) -> None:
    """A marker written during a test lands under ``tmp_path``, never in a shared tempdir.

    This is the single most likely source of a false green in this module: if ``TMPDIR``
    did not take effect, a stale ledger in the ambient ``spec-kitty-filing-guard/``
    directory would make every allow-path test pass for the wrong reason — and keep
    passing after WP07 breaks the behaviour they claim to pin.
    """
    session_id = "isolation-probe-session"
    satisfy_register(session_id, tmpdir=tmp_path)

    ledger = tmp_path / "spec-kitty-filing-guard" / f"{session_id}.json"
    assert ledger.exists(), f"no ledger under tmp_path; found: {list(tmp_path.iterdir())}"
    assert json.loads(ledger.read_text()) == {"register": True}

    ambient = Path(tempfile.gettempdir()) / "spec-kitty-filing-guard" / f"{session_id}.json"
    assert ambient.resolve() != ledger.resolve(), "tmp_path IS the ambient tempdir; no isolation"
    assert not ambient.exists(), f"the guard wrote outside tmp_path: {ambient}"


def test_two_tmpdirs_do_not_share_a_ledger(tmp_path: Path) -> None:
    """The same ``session_id`` under a second TMPDIR starts with an empty ledger.

    The direct proof that no test can inherit another's markers: mark ``register`` in one
    tmpdir, then file from the *same session id* in another and watch it be denied for the
    register cause. If the ledger leaked, this would allow.
    """
    session_id = "isolation-probe-session"
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    satisfy_register(session_id, tmpdir=first)
    satisfy_queue(session_id, tmpdir=first)
    assert_allow(run_bash(session_id, filing_command(FOOTERED_BODY), tmpdir=first))

    satisfy_queue(session_id, tmpdir=second)
    reason = assert_deny(run_bash(session_id, filing_command(FOOTERED_BODY), tmpdir=second))

    assert REGISTER_CAUSE in reason


# =============================================================================
# T005 — the positive control: dedup evidence + footer present -> ALLOW.
#
# Without this group a module in which *everything denies* would look correct, and a
# fail-closed suite that passes against an empty implementation proves nothing
# (contracts/denial-payload.md §5).
# =============================================================================


def test_allows_when_register_read_queue_searched_and_footer_present(tmp_path: Path) -> None:
    """The happy path: all three observable runbook artefacts exist in the session."""
    session_id = "t005-happy-path"
    satisfy_register(session_id, tmpdir=tmp_path)
    satisfy_queue(session_id, tmpdir=tmp_path)

    result = run_bash(session_id, filing_command(FOOTERED_BODY), tmpdir=tmp_path)

    assert_allow(result)


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("gh pr create --repo Priivacy-ai/spec-kitty --title T --body b", id="pr-create"),
        pytest.param("ls docs/", id="unrelated-command"),
    ],
)
def test_gate_is_scoped_to_issue_filings(command: str, tmp_path: Path) -> None:
    """Everything outside ``gh issue create|comment`` is allowed, whatever it names.

    A fresh session with no markers and no footer anywhere. If these denied, the module's
    denial tests would prove only that the guard denies indiscriminately.

    ⚠ A third case, ``gh issue create --repo octocat/hello``, sat here asserting ALLOW and
    has MOVED — not been deleted — to
    :func:`test_a_repository_that_is_not_ours_is_gated_even_when_unrecognised` below,
    where it is pinned as a DENY. These two are about the guard's REMIT and did not move.
    """
    assert_allow(run_bash("t005-out-of-scope", command, tmpdir=tmp_path))


def test_a_repository_that_is_not_ours_is_gated_even_when_unrecognised(tmp_path: Path) -> None:
    """FR-002: classification is INVERTED, so ``octocat/hello`` is upstream and denied.

    This assertion used to read the other way, and the flip is deliberate. It is justified
    by a requirement, never by the new code: the edge case the mission exists for is a
    repository under our OWN organisation that is neither ours nor a known upstream, and
    it must fall to the enforcing side rather than through the gap. "Unrecognised" is one
    class — there is no way to close it for ``spec-kitty/spec-kitty-saas`` and leave it
    open for ``octocat/hello``.

    Re-pinned FROM THE OTHER SIDE rather than dropped, and the denial's TEXT is asserted
    as well as the denial: a gate that refuses for an unstated reason, or for a rule that
    no longer exists, is the thing FR-013 forbids.

    ⚠ RESIDUE: a filing into an unrelated third-party repository now demands this
    project's register and template, which is not what its author would expect to be asked
    for. Accepted for its failure direction — enforcing rather than silent — and recorded
    in ``research.md`` A-17.
    """
    command = "gh issue create --repo octocat/hello --title T --body b"

    reason = assert_deny(run_bash("t005-unrecognised", command, tmpdir=tmp_path))

    assert "octocat/hello" in reason, "the denial must name the target it judged"
    assert "not in the set we own" in reason
    assert "upstream spec-kitty" not in reason, "the gate must not claim what it cannot know"
    assert "Priivacy-ai" not in reason, "the retired organisation prefix must not reappear"
    assert CLOSING_BLOCK in reason


# =============================================================================
# T006 — the register was never read -> DENY, naming the register cause only.
#
# FR-009's whole point is that four causes produce four different texts. A test that
# only asserts "denied" cannot tell them apart, and would stay green if a future change
# collapsed every cause into one message.
# =============================================================================


def test_denies_when_the_register_was_never_read(tmp_path: Path) -> None:
    """Queue searched, footer present, register unread — the filing is blocked."""
    session_id = "t006-no-register"
    satisfy_queue(session_id, tmpdir=tmp_path)

    reason = assert_deny(run_bash(session_id, filing_command(FOOTERED_BODY), tmpdir=tmp_path))

    assert reason.startswith("BLOCKED — this filing has not completed the bug-reporting runbook.")


def test_register_denial_names_the_register_and_not_the_other_causes(tmp_path: Path) -> None:
    """The reason carries the register bullet and neither the queue nor the footer cause."""
    session_id = "t006-cause-discrimination"
    satisfy_queue(session_id, tmpdir=tmp_path)

    reason = assert_deny(run_bash(session_id, filing_command(FOOTERED_BODY), tmpdir=tmp_path))

    assert DEDUP_HEADER in reason
    assert REGISTER_CAUSE in reason
    assert QUEUE_CAUSE not in reason
    assert FOOTER_HEADER not in reason


def test_register_denial_carries_the_mandatory_closing_block(tmp_path: Path) -> None:
    """Every denial must tell the reader to RUN the step, not to fake the marker.

    ``never by adding a token command`` is the literal from denial-payload §4a. It is the
    one sentence that stops the gate from training agents to satisfy it cheaply, so it is
    asserted on every denial cause in this module.
    """
    session_id = "t006-closing-block"
    satisfy_queue(session_id, tmpdir=tmp_path)

    reason = assert_deny(run_bash(session_id, filing_command(FOOTERED_BODY), tmpdir=tmp_path))

    assert CLOSING_BLOCK in reason


# =============================================================================
# T007 — the upstream queue was never searched -> DENY, naming the queue cause only.
# =============================================================================


def test_denies_when_the_upstream_queue_was_never_searched(tmp_path: Path) -> None:
    """Register read, footer present, queue unsearched — the filing is blocked."""
    session_id = "t007-no-queue"
    satisfy_register(session_id, tmpdir=tmp_path)

    reason = assert_deny(run_bash(session_id, filing_command(FOOTERED_BODY), tmpdir=tmp_path))

    assert reason.startswith("BLOCKED — this filing has not completed the bug-reporting runbook.")


def test_queue_denial_names_the_queue_and_not_the_other_causes(tmp_path: Path) -> None:
    """The reason carries the queue bullet and neither the register nor the footer cause."""
    session_id = "t007-cause-discrimination"
    satisfy_register(session_id, tmpdir=tmp_path)

    reason = assert_deny(run_bash(session_id, filing_command(FOOTERED_BODY), tmpdir=tmp_path))

    assert DEDUP_HEADER in reason
    assert QUEUE_CAUSE in reason
    assert REGISTER_CAUSE not in reason
    assert FOOTER_HEADER not in reason


def test_queue_denial_carries_the_mandatory_closing_block(tmp_path: Path) -> None:
    """See ``test_register_denial_carries_the_mandatory_closing_block``."""
    session_id = "t007-closing-block"
    satisfy_register(session_id, tmpdir=tmp_path)

    reason = assert_deny(run_bash(session_id, filing_command(FOOTERED_BODY), tmpdir=tmp_path))

    assert CLOSING_BLOCK in reason


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(
            'gh issue list --repo Priivacy-ai/spec-kitty --search "symptom" --state all',
            id="gh-issue-list",
        ),
        pytest.param(
            'gh search issues "symptom" --repo Priivacy-ai/spec-kitty --state all',
            id="gh-search-issues",
        ),
        pytest.param(
            'python scripts/upstream_dedup.py --query "symptom"',
            id="upstream-dedup-script",
        ),
        pytest.param("gh issue view 3728 --repo Priivacy-ai/spec-kitty", id="gh-issue-view"),
    ],
)
def test_these_commands_satisfy_the_queue_marker(
    command: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """Four genuine dedup invocations, each of which must clear the queue requirement.

    Measured against the shipped guard rather than derived from ``QUEUE_SEARCH_RE``:
    reading the pattern and asserting what it *ought* to match is how a blind oracle gets
    written. WP07 narrows queue detection to ``shlex`` argv parsing; these four are real
    argv-parseable invocations and must survive that narrowing.
    """
    session_id = request.node.name
    satisfy_register(session_id, tmpdir=tmp_path)
    assert_allow(run_bash(session_id, command, tmpdir=tmp_path))

    assert_allow(run_bash(session_id, filing_command(FOOTERED_BODY), tmpdir=tmp_path))


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("gh pr list --repo Priivacy-ai/spec-kitty --state all", id="gh-pr-list"),
        pytest.param("gh repo view Priivacy-ai/spec-kitty", id="gh-repo-view"),
        pytest.param("git log --oneline -5", id="git-log"),
    ],
)
def test_these_commands_do_not_satisfy_the_queue_marker(
    command: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """Commands adjacent to a dedup search that must NOT be mistaken for one.

    ``gh pr list`` is the near miss worth pinning: same tool, same repo, plural-listing
    shape, and it searches the wrong queue entirely.
    """
    session_id = request.node.name
    satisfy_register(session_id, tmpdir=tmp_path)
    assert_allow(run_bash(session_id, command, tmpdir=tmp_path))

    reason = assert_deny(run_bash(session_id, filing_command(FOOTERED_BODY), tmpdir=tmp_path))

    assert QUEUE_CAUSE in reason


# =============================================================================
# T008 — the attribution footer is missing -> DENY, naming the footer cause only.
# =============================================================================


@pytest.mark.parametrize("verb", ["create", "comment"])
def test_denies_when_the_attribution_footer_is_missing(verb: str, tmp_path: Path) -> None:
    """Both dedup steps done, footer absent — blocked, for ``create`` and ``comment`` alike."""
    session_id = f"t008-no-footer-{verb}"
    satisfy_register(session_id, tmpdir=tmp_path)
    satisfy_queue(session_id, tmpdir=tmp_path)

    reason = assert_deny(
        run_bash(session_id, filing_command(UNFOOTERED_BODY, verb=verb), tmpdir=tmp_path)
    )

    assert FOOTER_HEADER in reason
    assert CLOSING_BLOCK in reason


def test_footer_denial_names_the_footer_and_not_the_dedup_causes(tmp_path: Path) -> None:
    """The reason carries the footer block and neither dedup bullet nor the dedup header."""
    session_id = "t008-cause-discrimination"
    satisfy_register(session_id, tmpdir=tmp_path)
    satisfy_queue(session_id, tmpdir=tmp_path)

    reason = assert_deny(run_bash(session_id, filing_command(UNFOOTERED_BODY), tmpdir=tmp_path))

    assert FOOTER_HEADER in reason
    assert DEDUP_HEADER not in reason
    assert REGISTER_CAUSE not in reason
    assert QUEUE_CAUSE not in reason


def test_footer_denial_quotes_the_exact_template_the_agent_must_copy(tmp_path: Path) -> None:
    """Both template lines appear verbatim — that text is the remedy, not a description of it.

    A denial that names a missing footer without showing it makes the reader go looking,
    which is how the footer got missed nine times before this gate existed.
    """
    session_id = "t008-template-lines"
    satisfy_register(session_id, tmpdir=tmp_path)
    satisfy_queue(session_id, tmpdir=tmp_path)

    reason = assert_deny(run_bash(session_id, filing_command(UNFOOTERED_BODY), tmpdir=tmp_path))

    assert FOOTER_TEMPLATE_AUTHOR in reason
    assert FOOTER_TEMPLATE_APPROVER in reason


def test_unmarked_intent_check_is_reported_in_the_denial(tmp_path: Path) -> None:
    """Half one of "advisory": with ``intent`` unmarked the paragraph is shown."""
    session_id = "t008-intent-shown"
    satisfy_register(session_id, tmpdir=tmp_path)
    satisfy_queue(session_id, tmpdir=tmp_path)

    reason = assert_deny(run_bash(session_id, filing_command(UNFOOTERED_BODY), tmpdir=tmp_path))

    assert INTENT_PARAGRAPH in reason


def test_unmarked_intent_check_does_not_by_itself_deny(tmp_path: Path) -> None:
    """Half two of "advisory", asserted explicitly so it cannot silently become gating.

    Same arrangement as the T005 happy path — register, queue, footer, and no intent-check
    command anywhere — stated here as a property of the intent check rather than as a
    property of the allow path. The intent check is only required for a "they forgot X"
    claim, so it informs; it must never block.
    """
    session_id = "t008-intent-not-gating"
    satisfy_register(session_id, tmpdir=tmp_path)
    satisfy_queue(session_id, tmpdir=tmp_path)

    result = run_bash(session_id, filing_command(FOOTERED_BODY), tmpdir=tmp_path)

    assert_allow(result)
    ledger = json.loads((tmp_path / "spec-kitty-filing-guard" / f"{session_id}.json").read_text())
    assert "intent" not in ledger, "the arrangement is void if something marked intent"


# =============================================================================
# Bash-side register marking (WP02 review finding F2).
#
# Added after review. The reviewer deleted
#
#     if REGISTER in command:
#         mark(session_id, "register")
#
# from the guard's Bash branch and ALL 25 tests stayed green — every register
# marker in the module reached the ledger through the ``Read`` branch instead.
#
# That matters because WP07/T039 rewrites exactly this path into an argv
# allowlist (``grep|rg|cat|sed|awk|head|tail|less|git|python`` mark; ``ls`` and
# ``touch`` must not). Without a baseline here, nothing distinguishes "narrowed
# correctly" from "narrowed too far" — WP07 would be changing behaviour no test
# describes.
#
# This asserts only what SURVIVES that fix: reading the register with a real
# reader marks it. ``cat`` is on T039's allowlist, so this is characterisation,
# not a wish.
# =============================================================================


def test_reading_the_register_via_bash_marks_it(tmp_path: Path) -> None:
    """A genuine Bash read of the register satisfies the register requirement.

    The ``Read``-tool path is covered elsewhere; this covers the Bash path, which
    is a separate marking site in the guard and is the one WP07 narrows.
    """
    session_id = "bash-register-marking"

    satisfy_queue(session_id, tmpdir=tmp_path)
    assert_allow(run_bash(session_id, f"cat {REGISTER_PATH}", tmpdir=tmp_path))

    # Register + queue + footer all satisfied -> the filing is allowed. If the
    # Bash-side marking is removed, the register cause reappears and this denies.
    assert_allow(
        run_bash(session_id, filing_command(FOOTERED_BODY), tmpdir=tmp_path)
    )


def test_the_denial_names_the_register_when_only_the_bash_read_is_missing(
    tmp_path: Path,
) -> None:
    """Discriminator for the test above: without the Bash read, the register cause is named.

    Paired deliberately. The positive test alone could pass while asserting
    nothing about *why* — this pins that the register requirement is what the
    Bash read discharges, and not some other cause incidentally satisfied.
    """
    session_id = "bash-register-marking-absent"

    satisfy_queue(session_id, tmpdir=tmp_path)
    reason = assert_deny(
        run_bash(session_id, filing_command(FOOTERED_BODY), tmpdir=tmp_path)
    )
    assert REGISTER_CAUSE in reason
    assert QUEUE_CAUSE not in reason, "the queue was satisfied; it must not be named"


# =============================================================================
# T013 — the ownership inversion, pinned in BOTH directions through the harness.
#
# WHY THESE CASES DID NOT ALREADY EXIST. Before this work **no test in this tree
# named our own repository as a filing target** — every filing in both modules
# went to an upstream one. So the guard's old predicate could have said almost
# anything about "ours" and stayed green, and one thing it did say was wrong: a
# bare organisation prefix, which after the Team Kitty rename matches upstream
# and us alike. An assertion set that never exercises the "ours" side cannot
# catch that, and did not.
#
# EVERY CASE RUNS THROUGH THE REAL HARNESS — ``run_bash`` into the guard as a
# subprocess, ``assert_allow``/``assert_deny`` on the wire contract. A direct
# ``assert targets_upstream(argv) is True`` is deliberately absent: it was measured
# DURING PLANNING (not here) to be a blind oracle, surviving both ``return True``
# and the over-broad organisation prefix, with a letter-case variant as its only
# unique kill. What IS measured here is that the harness-built cases kill both of
# those mutants — see the battery recorded in this work package's review notes.
#
# ``assert_allow`` requires exit 0 AND strictly empty stdout. That strictness is
# what stops an allow-assertion passing vacuously, and it is not relaxed here.
# =============================================================================

#: Ours. Full ``owner/name``, matching ``_hook_lib.OURS``.
OUR_REPO = "spec-kitty/spec-kitty-qa"

#: ⚠ POST-RENAME, and deliberately not yet in ``UPSTREAM_TARGETS``. The property the
#: mission delivers is that a repository the guard has never been told about is gated
#: anyway, so exercising only today's names would demonstrate nothing. No edit to
#: ``OURS`` accompanies these cases — that is the point of them.
POST_RENAME_SAAS = "spec-kitty/spec-kitty-saas"

#: ⚠ A PREFIX OF ``OUR_REPO``, and that is the whole reason it is here:
#: ``"spec-kitty/spec-kitty" in "spec-kitty/spec-kitty-qa"`` is True. Under a substring
#: comparison our own tracker would satisfy a filing into a DIFFERENT repository. This
#: is upstream and must be gated.
ADJACENT_TO_OURS = "spec-kitty/spec-kitty"

#: A body that cites the other side of the ownership line. Quoted into ``--body`` by
#: ``filing_command``, so it carries no double quote of its own.
BODY_CITING_UPSTREAM = "tracks Priivacy-ai/spec-kitty#12 and spec-kitty/spec-kitty#3"
BODY_CITING_OURS = f"tracks {OUR_REPO}#291, our own row"

OWNERSHIP_CAUSE = "not in the set we own"


def test_filing_into_our_own_repository_is_allowed_with_no_evidence_at_all(
    tmp_path: Path,
) -> None:
    """The allow half of the ownership pair: an internal filing is not this gate's business.

    A fresh session — register unread, queue unsearched, body unfootered. Every one of
    the three requirements is unmet, and the filing is still allowed, because none of
    them applies to a repository we own. If ownership were decided by a bare
    organisation prefix, or if classification defaulted to "upstream", this denies.
    """
    command = filing_command(UNFOOTERED_BODY, repo=OUR_REPO)

    assert_allow(run_bash("t013-ours-allow", command, tmpdir=tmp_path))


def test_filing_into_a_repository_that_merely_shares_our_prefix_is_denied(
    tmp_path: Path,
) -> None:
    """The deny half, and the one that pins FULL-STRING comparison rather than substring.

    ``spec-kitty/spec-kitty`` is a proper prefix of ``spec-kitty/spec-kitty-qa``, so a
    membership test written with ``in`` — in either direction — classifies it as ours and
    allows it. It is not ours, and with no evidence in the session it must deny.

    Paired with the test above: together they say the comparison is equality, since one
    of them fails under substring matching and the other fails under nothing-is-ours.
    """
    command = filing_command(UNFOOTERED_BODY, repo=ADJACENT_TO_OURS)

    reason = assert_deny(run_bash("t013-adjacent-deny", command, tmpdir=tmp_path))

    assert OWNERSHIP_CAUSE in reason
    assert ADJACENT_TO_OURS in reason, "the denial must name the target it judged"
    assert DEDUP_HEADER in reason


def test_an_internal_filing_whose_body_cites_upstream_is_allowed(tmp_path: Path) -> None:
    """THE MEASURED FALSE REFUSAL, fixed and pinned.

    ``gh issue create --repo spec-kitty/spec-kitty-qa --title T --body "tracks
    <upstream>#12"`` was DENIED — an internal filing blocked because its BODY quoted an
    upstream reference. The old predicate substring-scanned every token in the segment,
    so the gating decision depended on whether the body arrived via ``--body`` or
    ``--body-file``, which is incoherent for a question about where a filing is going.

    Cross-referencing an upstream issue from an internal one is ordinary work — this is
    a gate that refused ordinary work, which is how gates get switched off.
    """
    command = filing_command(BODY_CITING_UPSTREAM, repo=OUR_REPO)

    assert_allow(run_bash("t013-body-mentions-upstream", command, tmpdir=tmp_path))


def test_an_upstream_filing_whose_body_cites_our_repository_is_still_denied(
    tmp_path: Path,
) -> None:
    """The mirror, and the half that stops the fix over-shooting into a hole.

    Body content is IRRELEVANT to classification now — which has to mean irrelevant in
    both directions. A predicate that asked "does any token name something we own?" would
    fix the false refusal above and simultaneously let any upstream filing through by
    quoting our own tracker in its body. This asserts it does not.
    """
    command = filing_command(BODY_CITING_OURS, repo=ADJACENT_TO_OURS)

    reason = assert_deny(run_bash("t013-body-mentions-ours", command, tmpdir=tmp_path))

    assert OWNERSHIP_CAUSE in reason
    assert DEDUP_HEADER in reason


def test_a_post_rename_repository_is_gated_without_any_edit_to_the_ownership_set(
    tmp_path: Path,
) -> None:
    """THE PROPERTY THE MISSION EXISTS TO DELIVER, stated over a name nothing enumerates.

    ``spec-kitty/spec-kitty-saas`` is what the product tracker is called after the
    rename. It appears in no list the guard consults — not in ``OURS``, not in
    ``UPSTREAM_TARGETS`` — and it is gated anyway, because classification asks whether
    the target is ours rather than whether it is a recognised upstream.

    The predecessor of this rule enumerated upstream organisation prefixes. The rename
    changed the prefix and the guard went silently inert: running, reporting nothing,
    checking nothing, while four issues were filed through it. A test over today's names
    only would not have caught that then and would not catch its recurrence now.
    """
    command = filing_command(UNFOOTERED_BODY, repo=POST_RENAME_SAAS)

    reason = assert_deny(run_bash("t013-post-rename-deny", command, tmpdir=tmp_path))

    assert OWNERSHIP_CAUSE in reason
    assert POST_RENAME_SAAS in reason


def test_a_post_rename_repository_allows_once_the_runbook_evidence_exists(
    tmp_path: Path,
) -> None:
    """The allow half of the post-rename pair — the gate is satisfiable, not merely loud.

    Without this the case above would be indistinguishable from a guard that denies every
    filing into that repository unconditionally, which is a different (and useless)
    behaviour that would pass the deny half on its own.
    """
    session_id = "t013-post-rename-allow"
    satisfy_register(session_id, tmpdir=tmp_path)
    satisfy_queue(session_id, tmpdir=tmp_path)

    command = filing_command(FOOTERED_BODY, repo=POST_RENAME_SAAS)

    assert_allow(run_bash(session_id, command, tmpdir=tmp_path))


# The five spellings `gh` accepts for its target flag, measured against gh 2.98.0 in
# WP01. They are listed here as WHOLE COMMANDS rather than built by ``filing_command``,
# because ``filing_command`` can only emit the separated long form and the point of this
# pair is that the OTHER four reach the same verdict. A guard that read only
# ``--repo VALUE`` would gate the separated form and wave ``-Rowner/name`` straight past.
_TARGET_SPELLINGS = [
    pytest.param("--repo {repo}", id="separated-long"),
    pytest.param("--repo={repo}", id="attached-long"),
    pytest.param("-R {repo}", id="separated-short"),
    pytest.param("-R{repo}", id="attached-short"),
    pytest.param("-R={repo}", id="attached-short-equals"),
]


@pytest.mark.parametrize("spelling", _TARGET_SPELLINGS)
def test_every_target_spelling_gates_an_upstream_filing(spelling: str, tmp_path: Path) -> None:
    """Deny half: whichever way the target is written, upstream demands the evidence."""
    target = spelling.format(repo=POST_RENAME_SAAS)
    command = f'gh issue create {target} --title "T" --body "{UNFOOTERED_BODY}"'

    reason = assert_deny(run_bash("t013-spelling-deny", command, tmpdir=tmp_path))

    assert OWNERSHIP_CAUSE in reason
    assert POST_RENAME_SAAS in reason


@pytest.mark.parametrize("spelling", _TARGET_SPELLINGS)
def test_every_target_spelling_recognises_our_own_repository(
    spelling: str, tmp_path: Path
) -> None:
    """Allow half: the same five spellings, on the ours side, in a session with no evidence.

    Without this half, a guard that failed to READ a spelling at all would pass the deny
    half for the wrong reason — an unread target is no target, and one plausible reading
    of "no target" is also a denial. Asserting both sides is what tells the two apart.
    """
    target = spelling.format(repo=OUR_REPO)
    command = f'gh issue create {target} --title "T" --body "{UNFOOTERED_BODY}"'

    assert_allow(run_bash("t013-spelling-allow", command, tmpdir=tmp_path))


# =============================================================================
# The unresolvable-target battery — added in review cycle 2, and the reason it
# exists is more useful than the cases themselves.
#
# Cycle 1 left the unresolvable-form check reading the target through
# ``flag_value(argv, "--repo", "-R")`` while the VERDICT read
# ``lib.target_repo(argv)``. Two parsers, one module, disagreeing about what a
# target is — the split-brain this mission exists to remove, reintroduced by the
# change that removed it elsewhere. ``flag_value`` never reads the three ATTACHED
# short spellings, so they reached the classification path unchecked.
#
# ⚠ THE DIVERGENCE WAS SEEN AND MISREAD, and that is the lesson to keep. It was
# reported as failing "in the enforcing direction" on the strength of this:
#
#     gh issue create -R$VAR --title T --body "…"          -> DENY
#
# True — and measured over an EMPTY LEDGER only. With the ledger satisfied the
# same command ALLOWED, because the generic runbook denial that made the empty
# case look safe was the only thing standing there, and evidence dissolves it.
# A safety property established over a subset of its inputs is not a safety
# property; and the subset skipped here was the one an author actually reaches,
# since an author who is filing has normally already done the runbook.
#
# So EVERY case below is asserted in BOTH ledger states, and the satisfied state
# carries its own control: a LITERAL upstream target, same spelling, same
# session, must ALLOW first. Without that control a deny under a "satisfied"
# ledger proves nothing — it is equally consistent with a ledger that was never
# satisfied at all.
# =============================================================================

#: Literals, not imports. A test that finds the guard's own constant in the guard's
#: own output has compared a value with itself.
UNRESOLVABLE_HEADLINE = "BLOCKED — this filing's --repo value cannot be resolved"
FORM_VARIABLE_EXPANSION = "variable expansion"
FORM_COMMAND_SUBSTITUTION = "command substitution"

#: The three shapes ``dynamic_form`` names, each written the way a shell author
#: would write it. Quoted, so ``shlex`` keeps the value in one token whichever
#: spelling wraps it — the unquoted attached form is pinned separately below,
#: because that one is the review's verbatim reproducer.
_DYNAMIC_TARGET_VALUES = [
    pytest.param('"$UPSTREAM_REPO"', FORM_VARIABLE_EXPANSION, id="variable-expansion"),
    pytest.param('"$(cat repo.txt)"', FORM_COMMAND_SUBSTITUTION, id="command-substitution"),
    pytest.param('"`cat repo.txt`"', FORM_COMMAND_SUBSTITUTION, id="backticks"),
]

_LEDGER_STATES = [
    pytest.param(False, id="empty-ledger"),
    pytest.param(True, id="satisfied-ledger"),
]


@pytest.mark.parametrize("ledger_satisfied", _LEDGER_STATES)
@pytest.mark.parametrize(("value", "form"), _DYNAMIC_TARGET_VALUES)
@pytest.mark.parametrize("spelling", _TARGET_SPELLINGS)
def test_an_unresolvable_target_denies_in_every_spelling_and_both_ledger_states(
    spelling: str, value: str, form: str, ledger_satisfied: bool, tmp_path: Path
) -> None:
    """A target the gate cannot resolve denies BEFORE the ledger is consulted.

    Thirty cases: five spellings × three dynamic shapes × both ledger states. The
    satisfied-ledger half is the one cycle 1 did not measure and is where three of
    the five spellings allowed.

    Two negative assertions carry as much as the positive one. ``FOOTER_HEADER``
    absent says the refusal does not send the author to fix a footer that is
    already there — it is the REPOSITORY that is unreadable. ``DEDUP_HEADER``
    absent says the denial came from the unresolvable branch and not from the
    generic runbook denial, which is precisely the confusion that made the
    empty-ledger measurement read as safe.
    """
    session_id = f"t013-dynamic-target-{ledger_satisfied}"
    body = UNFOOTERED_BODY

    if ledger_satisfied:
        satisfy_register(session_id, tmpdir=tmp_path)
        satisfy_queue(session_id, tmpdir=tmp_path)
        body = FOOTERED_BODY
        # CONTROL — prove the ledger really is satisfied for THIS spelling before
        # believing anything about the deny below. A literal upstream target with
        # every requirement met is allowed; if this control ever denies, the
        # assertion that follows it is measuring an unsatisfied ledger.
        control = spelling.format(repo=POST_RENAME_SAAS)
        assert_allow(
            run_bash(
                session_id,
                f'gh issue create {control} --title "T" --body "{FOOTERED_BODY}"',
                tmpdir=tmp_path,
            )
        )

    target = spelling.format(repo=value)
    command = f'gh issue create {target} --title "T" --body "{body}"'

    reason = assert_deny(run_bash(session_id, command, tmpdir=tmp_path))

    assert UNRESOLVABLE_HEADLINE in reason
    assert form in reason, "the denial must name the form it could not resolve"
    assert FOOTER_HEADER not in reason, "the footer is not the unreadable part"
    assert DEDUP_HEADER not in reason, (
        "this must be the unresolvable-target denial, not the generic runbook one — "
        "the generic denial is what dissolves the moment evidence exists"
    )


def test_the_attached_short_target_bypass_denies_with_a_satisfied_ledger(
    tmp_path: Path,
) -> None:
    """THE REVIEW'S VERBATIM REPRODUCER, unquoted, in the state where it allowed.

    ``gh issue create -R$VAR --title T --body "**Authored by**: …"`` — the exact
    shape Codex measured. Written without quotes on purpose: the parametrised
    battery above quotes its values so one token survives every spelling, and a
    reproducer that differs from the report is a reproducer of something else.
    """
    session_id = "t013-attached-short-bypass"
    satisfy_register(session_id, tmpdir=tmp_path)
    satisfy_queue(session_id, tmpdir=tmp_path)

    command = f'gh issue create -R$UPSTREAM_REPO --title "T" --body "{FOOTERED_BODY}"'

    reason = assert_deny(run_bash(session_id, command, tmpdir=tmp_path))

    assert UNRESOLVABLE_HEADLINE in reason
    assert FORM_VARIABLE_EXPANSION in reason


def test_the_attached_short_target_denies_for_the_repository_on_an_empty_ledger_too(
    tmp_path: Path,
) -> None:
    """The same command with no evidence — and the assertion is about WHY it denies.

    This case already denied before the fix, which is what made the divergence look
    harmless. It denied for the WRONG REASON: the generic runbook denial, which any
    completed runbook removes. Asserting the deny alone reproduces cycle 1's error;
    asserting the CAUSE is what distinguishes a short-circuit from a coincidence.
    """
    command = f'gh issue create -R$UPSTREAM_REPO --title "T" --body "{UNFOOTERED_BODY}"'

    reason = assert_deny(run_bash("t013-attached-short-empty", command, tmpdir=tmp_path))

    assert UNRESOLVABLE_HEADLINE in reason
    assert DEDUP_HEADER not in reason, "denying for the runbook here is the pre-fix behaviour"


def test_a_filing_that_names_no_repository_is_allowed_a_known_unguarded_gap(
    tmp_path: Path,
) -> None:
    """⚠ A DELIBERATE HOLE, pinned so it is visible rather than discovered.

    With no target flag, ``gh`` resolves the repository from the checkout's git remote.
    The guard does not: resolving a remote here means running a subprocess to decide
    whether to permit a command, and it was considered and CUT (qa#291 item 4). So the
    filing is ALLOWED, exactly as it was before this work.

    This is ABSTENTION — a judgement that the command is outside the guard's remit — and
    not a failure direction. The fail-closed posture lives in the ``run()`` wrapper and is
    untouched.

    It is pinned because an unguarded gap that no test names is indistinguishable from an
    oversight, and because the day someone closes it, this test is where they will read
    why it was open.
    """
    command = f'gh issue create --title "T" --body "{UNFOOTERED_BODY}"'

    assert_allow(run_bash("t013-no-target", command, tmpdir=tmp_path))


def test_the_denial_text_derives_from_the_canonical_sets(tmp_path: Path) -> None:
    """FR-013: the printed rule is DERIVED, so a rename edits one place and text follows.

    Asserted through the rendered denial rather than by reading the source. Hand-copied
    literals are what left an earlier gate printing commands that named a repository which
    no longer existed — ``gh`` fails on every one, no marker can ever be earned, and the
    remedy cannot satisfy the refusal it accompanies. That is a livelock, not a refusal.

    ``OURS`` is imported here for the EXPECTED value only. That is the one import that
    does not make this circular: the guard's own copy of the set is precisely what has
    been deleted, so finding the shared set's contents in the guard's output is evidence
    that the deletion took, not a tautology.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from hooks._hook_lib import OURS

    command = filing_command(UNFOOTERED_BODY, repo=POST_RENAME_SAAS)

    reason = assert_deny(run_bash("t013-derived-text", command, tmpdir=tmp_path))

    for owned in OURS:
        assert owned in reason, f"the denial must state the set in force; {owned} is absent"
    assert "Priivacy-ai" not in reason, "the retired organisation prefix must not reappear"


def test_the_rule_and_the_remedy_follow_a_change_to_the_canonical_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T010: swap the canonical sets and the printed text changes with them.

    ⚠ AN IMPORT, against this module's own standing rule that the guard is invoked as a
    subprocess. The rule exists because the guard exits on every decision path and because
    ``LEDGER_DIR`` is bound at import; neither applies to the two text builders called
    here, which are pure functions that return a string. And a subprocess is the one thing
    that CANNOT answer this question — the sets would have to be edited on disk to swap
    them, which is a different test with a much worse failure mode.

    The assertion that matters is the negative one. ``spec-kitty/spec-kitty-qa`` and
    ``spec-kitty/EXPERIMENTAL-spec-kitty`` must be ABSENT once the sets are swapped: a
    hand-copied literal would still be sitting in the output, and a hand-copied literal is
    exactly what left an earlier gate printing a remedy naming a repository that no longer
    existed — ``gh`` fails on every such command, no marker can ever be earned, and the
    refusal cannot be satisfied. Asserting only that the NEW names appear would pass with
    the old ones still there beside them.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from hooks import _hook_lib as lib
    from hooks import upstream_filing_guard as guard

    monkeypatch.setattr(lib, "OURS", frozenset({"acme/renamed-tracker"}))
    monkeypatch.setattr(lib, "UPSTREAM_TARGETS", ("acme/renamed-upstream",))

    rule = "\n".join(guard.ownership_rule_lines("octocat/hello"))
    remedy = guard.build_unresolvable_repo_denial("variable expansion")

    assert "acme/renamed-tracker" in rule, "the rule text does not derive from OURS"
    assert "acme/renamed-tracker" in remedy, "the remedy does not derive from OURS"
    assert "acme/renamed-upstream" in remedy, "the example does not derive from UPSTREAM_TARGETS"
    assert "spec-kitty/spec-kitty-qa" not in rule, "a hand-copied literal survived the swap"
    assert "spec-kitty/spec-kitty-qa" not in remedy, "a hand-copied literal survived the swap"
    assert "EXPERIMENTAL" not in remedy, "a hand-copied literal survived the swap"


# =============================================================================
# The dedup marker must be earned against a tracker that is not ours.
#
# Post-merge mission review, finding H-1. WP01 conditioned the mission-start gate's
# sweep markers on ownership, with a note that they must never be earnable against
# our own tracker. The filing guard's own `queue` marker never got that condition,
# so a sweep of our own issues unlocked a filing into somebody else's.
#
# Both award branches are conditioned here. Fixing only the `gh` branch moves the
# free marker onto the dedup-script branch — which is the one the bug-reporting
# runbook actually tells people to use, so it would be exercised by default.
# =============================================================================

OUR_TRACKER = "spec-kitty/spec-kitty-qa"
OURS_QUEUE_SEARCH = f'gh issue list --repo {OUR_TRACKER} --search "symptom" --state all'
DEDUP_OURS = f"python3 scripts/upstream_dedup.py --repo {OUR_TRACKER} --query symptom"
DEDUP_UPSTREAM = (
    "python3 scripts/upstream_dedup.py --repo Priivacy-ai/spec-kitty --query symptom"
)
#: Names the dedup script in a comment and runs nothing. `names_dedup_script` is a
#: substring test over any token, so merely mentioning the filename used to earn the
#: marker — a token command satisfying the gate, which the gate's own closing block
#: (`never by adding a token command`) explicitly forbids.
DEDUP_TOKEN_COMMAND = "python3 -c 'pass  # scripts/upstream_dedup.py' --mechanism"

#: Invocations that NAME the dedup script and never execute it, because an interpreter
#: option consumes the command first. Every one of these earned the marker while doing
#: nothing at all. `-c` was the only one originally excluded, which was too narrow by
#: exactly the margin an enumerated deny is always too narrow by — hence the rule is now
#: positional (the script must be argv[1]) rather than a list of options to refuse.
DEDUP_NON_EXECUTING = (
    ("python3 --version scripts/upstream_dedup.py", "--version, prints and exits"),
    ("python3 -V scripts/upstream_dedup.py", "-V, prints and exits"),
    ("python3 -m json.tool scripts/upstream_dedup.py", "-m, runs a different module"),
)


@pytest.mark.parametrize(
    "sweep,label",
    [
        (OURS_QUEUE_SEARCH, "gh search of our own tracker"),
        (DEDUP_OURS, "dedup script pointed at our own tracker"),
        (DEDUP_TOKEN_COMMAND, "a token command that only names the dedup script"),
        *DEDUP_NON_EXECUTING,
    ],
)
def test_a_sweep_that_is_not_upstream_does_not_unlock_an_upstream_filing(
    tmp_path: Path, sweep: str, label: str
) -> None:
    """The deny half. Evidence about our own tracker is not evidence about theirs."""
    session = f"h1-deny-{abs(hash(sweep)) % 10_000}"
    assert_allow(run_bash(session, sweep, tmpdir=tmp_path))
    satisfy_register(session, tmpdir=tmp_path)

    reason = assert_deny(
        run_bash(session, filing_command(FOOTERED_BODY), tmpdir=tmp_path)
    )
    assert QUEUE_CAUSE in reason, (
        f"{label} satisfied the dedup requirement for a filing into somebody else's "
        "tracker — the guard accepted evidence about the wrong repository"
    )


@pytest.mark.parametrize(
    "sweep,label",
    [
        (QUEUE_SEARCH, "gh search of an upstream tracker"),
        (DEDUP_UPSTREAM, "dedup script pointed at an upstream tracker"),
    ],
)
def test_a_real_upstream_sweep_still_unlocks_the_filing(
    tmp_path: Path, sweep: str, label: str
) -> None:
    """The allow half, and it is the half that matters.

    A condition that refuses everything would pass the deny cases above while making
    the guard unusable. This proves the sanctioned path still works — including the
    dedup script, which the bug-reporting runbook prescribes.
    """
    session = f"h1-allow-{abs(hash(sweep)) % 10_000}"
    assert_allow(run_bash(session, sweep, tmpdir=tmp_path))
    satisfy_register(session, tmpdir=tmp_path)

    assert_allow(run_bash(session, filing_command(FOOTERED_BODY), tmpdir=tmp_path))
