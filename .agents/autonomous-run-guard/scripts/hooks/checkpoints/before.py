"""CP-BEFORE — refuse to begin a mission without §0 upstream-sweep evidence (FR-001).

The obligation already existed. ``docs/runbooks/autonomous-run-protocol.md`` §0 has told
every agent to sweep the upstream queue before starting a mission for as long as it has
existed. What it lacked was a trigger, and the cost of that is measured rather than
argued: on 2026-08-24, **27 of the 54** upstream refs cited in ``docs/spec-kitty-issues.md``
were already closed upstream. Verifying those 27 the next day found **6 genuinely
retirable** and **5 whose upstream is closed while the defect is not** — both directions of
error were live, in the same register, at the same time.

This checkpoint is the trigger. On a ``PreToolUse`` call that begins a mission it consults
this session's evidence ledger and refuses unless all four §0 steps are recorded.

WHAT THIS PROVES
----------------
That a command *with the shape of* a §0 sweep query ran to a **successful exit** in this
session, and that the register was **opened**.

WHAT IT CANNOT PROVE — and must never be read as proving
--------------------------------------------------------
* that the sweep's **output was read**, rather than the query merely having run;
* that a closed upstream issue was **checked against the build we run** — closed upstream
  is not the same fact as fixed in our build, and 5 of the 27 were exactly that gap;
* that the register was **corrected** afterwards.

Nothing observable from a hook payload can prove judgment. What this removes is **silent
omission** — the step nobody decided to skip, that simply never happened because the
runbook was never opened. Overstating it would make this checkpoint the very defect class
the mission exists to prevent (C-004).

THE RESIDUAL EVASION GAP (NFR-002)
----------------------------------
Matching is by token position, so a command that merely *mentions* a gated verb is not
gated. What that cannot close, and what is therefore **not** claimed:

* a command assembled through a **shell variable** — ``CMD="spec-kitty specify"; $CMD``;
* an **alias** or shell function standing in for the program name;
* ``eval "$(printf 'spec-kitty specify')"``;
* a wrapper that exits 0 without doing the work, on the marker side.

``sh -c '…'`` is unwrapped by the shared library and *is* matched, one wrapper class that
happens to be closable. The rest are deliberate circumvention, which is the same class as
deleting the hook and is outside what any of this claims to stop.

⚠ **That list is not exhaustive, and reading it as exhaustive is the mistake it invites.**
MEASURED at the wire, these ordinary, non-adversarial prefixes also reach the verb ungated::

    bash -lc 'spec-kitty agent mission create …'   # ``-lc``, not a literal ``-c`` token
    uv run spec-kitty specify
    timeout 60 spec-kitty specify
    echo specify | xargs spec-kitty

They are recorded and deliberately **not** closed: none is a measured problem, and closing
them is new capability this pared-down mission did not buy. What is corrected is the
overstatement — a reader of the list above would conclude ``uv run spec-kitty specify`` is
gated, and it is not. A false **positive**
denies, which is the safe direction, and its remedy is the one every denial names: run the
step.

FR-010b SUPERSEDES ``contracts/session-ledger.md`` §3's ORDERING
----------------------------------------------------------------
That contract paragraph says recording precedes evaluation *in the same call*, and it is
an accurate description of ``upstream_filing_guard.py``, which records from ``PreToolUse``
command **text**. Text records **intent**: a command that was denied, crashed, or never ran
leaves text behind all the same.

Under FR-010b a marker is written only from ``PostToolUse``, which fires after a tool
**completes successfully**. The marker for a step therefore lands on a **later event** than
the call that reads it, and the contract's same-call ordering is not merely unimplemented
here — it is impossible. Do not "restore" it; restoring it re-opens the hole.

The benign consequence, checked rather than assumed: a single command cannot both *be* a
sweep query and *be* ``mission create``, so nothing legitimate is judged against evidence
it produced in the same call. The one shape that is refused —
``<sweep query> && spec-kitty agent mission create`` — is refused correctly: at the moment
the gate evaluates, the sweep has not yet succeeded.

⚠ Recording is **not this module's job** and is deliberately not duplicated here. The
dispatcher routes ``PostToolUse`` straight to ``_hook_lib.record_markers``. A second
detector in this file would be the drift the shared library exists to prevent.

THE ``create`` AMBIGUITY — a recorded DECISION, not an oversight
-----------------------------------------------------------------
The CLI ships **two** different subcommands whose last word is ``create``, and its own
completion manifest describes them differently:

* ``spec-kitty agent mission create`` — "Create new mission directory structure";
* ``spec-kitty mission create`` — "Fetch a tracker ticket and prepare it as a mission brief".

**Both are gated.** They are different commands, but both *begin a mission*, and the value
of having swept the upstream queue first is identical either way. FR-001 names only the
first; gating the second is a deliberate widening, written down here so the next reader
finds a decision rather than an apparent accident.

``spec-kitty specify`` is gated for the same reason. ``spec-kitty agent mission merge`` is
**not** — that is CP-AFTER's surface, and a merge gate that also demanded sweep evidence
would report the wrong missing step. Neither are the six ``merge-driver-*`` subcommands,
which a regex anchored on ``\\bmerge\\b`` would have caught.

WHAT LIVES ELSEWHERE, ON PURPOSE
--------------------------------
The four-marker conjunction (FR-011), the four distinct denial texts (FR-009), argv
tokenisation and every ledger read live in ``scripts/hooks/_hook_lib.py``, implemented
once. Divergences from the contracts are recorded in that module's docstring — read it
before "correcting" anything here. The one most likely to be corrected back: a multi-line
command is split by LINE before ``shlex`` sees it, because ``shlex`` never emits a newline
token.

Reference: ``kitty-specs/mission-lifecycle-gate-01M0VRDZ/`` — ``spec.md`` (FR-001, FR-009,
FR-010b, FR-011, FR-012, NFR-001..004), ``contracts/session-ledger.md``,
``contracts/denial-payload.md``.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from hooks import _hook_lib as lib

#: Every verb that BEGINS a mission, matched by token POSITION so that a mention is not an
#: invocation. See the ``create`` ambiguity note in the module docstring: both spellings
#: are here on purpose.
GATED_VERBS: tuple[tuple[str, ...], ...] = (
    ("spec-kitty", "agent", "mission", "create"),
    ("spec-kitty", "mission", "create"),
    ("spec-kitty", "specify"),
)

#: FR-012's store. A directory of its own, under the same git-common-dir root as the
#: session ledger, so a record written inside a work-package worktree is visible to the
#: merge check running in the primary checkout.
#:
#: ⚠⚠ NEVER the fault JSONL. CP-AFTER's fold denies on any record whose ``kind`` it cannot
#: interpret, so one liveness line in ``faults/<mission>.jsonl`` would refuse every merge
#: in this repository, permanently.
LIVENESS_DIR_NAME = "liveness"
LIVENESS_SCHEMA = "spec-kitty-qa/gate-liveness@1"
CHECKPOINT_NAME = "before"


def gates_a_mission_start(argv: Sequence[str]) -> bool:
    """Does this shell segment begin a mission?

    Token positions, never substrings: ``echo "spec-kitty specify"`` has ``argv[0] ==
    "echo"`` and the whole phrase as one argument.
    """
    return any(lib.argv_matches(argv, verb) for verb in GATED_VERBS)


def liveness_path(session_id: str, *, cwd: str | None = None) -> Path:
    """``<git-common-dir>/spec-kitty-hooks/liveness/<safe_session_id>.json``.

    Keyed by ``session_id`` because that is the question FR-012 asks: *was enforcement
    active in the session that is asserting no faults?* Sanitised, so a ``../`` in a
    payload cannot escape the directory.
    """
    return (
        lib.hooks_root(cwd) / LIVENESS_DIR_NAME / f"{lib.safe_component(session_id)}.json"
    )


def record_liveness(session_id: str, *, cwd: str | None = None) -> None:
    """Record that the gate FIRED in this session (FR-012).

    **"Enforcement was not active" is a different answer from "no faults occurred."** An
    absent fault ledger is indistinguishable from a gate that never ran, so CP-AFTER
    refuses ``assert-none`` unless a liveness record exists.

    ⚠ This call site is the reason the FR is satisfiable at all. Liveness was originally
    CP-DURING's, and CP-DURING fires only on ``PostToolUseFailure`` — so a mission with
    **zero failing commands** would have recorded no liveness, ``assert-none`` would have
    been refused, and the merge would have been unsatisfiable: a correct check that can
    never pass. CP-BEFORE is the only checkpoint that runs in a fault-free mission.

    Written on **every** consultation, gated or not. The fact being recorded is that the
    hook ran, not that a refusal was considered — and a session that only ever runs
    ``spec-kitty status`` still had enforcement active.

    Nothing payload-derived reaches disk except a sanitised ``session_id`` (NFR-004).
    Failure is swallowed, as bookkeeping must be: the consequence of an unwritten record
    is a REFUSED ``assert-none``, which is the safe direction.
    """
    try:
        path = liveness_path(session_id, cwd=cwd)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": LIVENESS_SCHEMA,
            "session_id": lib.safe_component(session_id),
            "checkpoint": CHECKPOINT_NAME,
            # The most recent time the gate was observed live in this session. Not a
            # start time: claiming one would need a read, and nothing asks for it.
            "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        handle, tmp_name = tempfile.mkstemp(
            prefix=f"{path.stem}.", suffix=".tmp", dir=str(path.parent)
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(record, stream)
            os.replace(tmp, path)  # atomic; never an in-place truncate
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 - bookkeeping must never break a tool call
        return


def evaluate(payload: lib.Payload, segments: list[list[str]]) -> None:
    """The checkpoint seam. Abstain by returning; gate by never returning.

    ``lib.evaluate_session_ledger`` returns only on the allow path — on every other branch
    it writes a denial and exits — so the ``return None`` below is reached only when this
    session has earned all four markers.

    Order matters twice:

    1. **Liveness first.** A call that is about to be refused still proves the gate was
       live, and that is the fact FR-012 records.
    2. **The gated check before any ledger read** (NFR-003). A ``spec-kitty status`` in a
       session with no evidence must cost nothing and must not be refused.
    """
    if payload.hook_event_name != "PreToolUse":
        # Only PreToolUse carries permissionDecision. A checkpoint that appeared to refuse
        # where it structurally cannot would be an inert payload claiming an authority the
        # event does not have (C-004).
        return None

    record_liveness(payload.session_id, cwd=payload.cwd)

    if not any(gates_a_mission_start(argv) for argv in segments):
        return None

    lib.evaluate_session_ledger(payload.session_id, cwd=payload.cwd)
    return None
