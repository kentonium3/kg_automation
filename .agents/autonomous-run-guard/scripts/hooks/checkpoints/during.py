#!/usr/bin/env python3
"""CP-DURING — record the fault, inject the D-3 capture SOP. **This is not a gate.**

``PostToolUseFailure`` fires *after* the failing command has already run, and it carries no
deny authority: ``permissionDecision`` / ``permissionDecisionReason`` / ``updatedInput`` are
``PreToolUse``-only fields. So this checkpoint cannot refuse, delay, or undo anything. Three
checkpoints exist in this gate; only two of them can say no, and this is not one of them.
The enforcement of the D-3 obligation is **CP-AFTER** (WP06), which refuses a merge whose
fault ledger is unreconciled.

WHAT IT PROVES
    * a ``spec-kitty`` command was observed failing, and
    * the capture SOP was **emitted** into a channel measured to reach the model's context.

WHAT IT CANNOT PROVE
    * that the agent **read** the SOP, let alone acted on it. Visibility was measured;
      compliance was not, and cannot be by this method (WP01 spike §1). FR-003 may claim
      emission and nothing further — do not reword this to "the SOP was delivered".
    * that a fault the harness never surfaced was recorded. An empty ledger and a recording
      path that never fired are indistinguishable from outside.
    * that the diagnosis the SOP asks for is correct.

THE EVENT DOES THE CLASSIFICATION — never re-derive it
------------------------------------------------------
⚠ Do not "improve" this into an exit-status check. WP01 measured both directions of that
error in one session: ``grep -q`` finding nothing exits 1 and is delivered as a *successful*
``PostToolUse`` carrying ``returnCodeInterpretation``, and a Bash-tool timeout is likewise
delivered as a *successful* ``PostToolUse`` with ``tool_response.timedOutAfterMs``. Keying
on the **event** disposes of the whole false-positive class for free — and means a
``spec-kitty`` command that times out will **not** reach this checkpoint at all.

⚠ ``error_type`` and ``is_timeout`` **DO NOT EXIST** on this payload. The shipped hook
reference documents both; the implementation constructs neither. ``is_interrupt`` is the
filter's only input, and a filter written against the other two would read ``None`` forever.

ONE CHANNEL, AND WHY THE SECOND WAS REMOVED
-------------------------------------------
The SOP goes out on stdout as ``additionalContext`` only, at exit 0. Nothing is written to
stderr and the exit status is never non-zero.

WP01's spike measured a second channel — a stderr copy with ``exit 2`` — also reaching the
model's context, and this module shipped both for redundancy. **The operator removed it**, for
three reasons in order of weight: ``exit 2`` produces a ``hook_blocking_error`` attachment that
prefixes this hook's own absolute command line onto the model-visible text **twice**; a
blocking-shaped signal on an event with no deny authority invites exactly the misreading C-004
exists to prevent; and it turned ``test_the_during_route_is_not_a_gate`` (WP03's file) red on
its exit-code assertion, buying a cross-package edit for redundancy on a channel already
measured working.

⚠ **Do not restore it believing it was forgotten.**
``test_the_sop_is_emitted_on_the_single_measured_channel`` pins the removal deliberately.

⚠ **And do not repeat the claim this section used to make.** It said the two channels "fail
independently: a harness change that silently drops ``additionalContext`` leaves ``exit 2``
standing." With one channel that is simply false — if the harness drops ``additionalContext``,
the SOP is lost entirely. It is recorded here because a stale docstring twenty lines above the
code was arguing for the restoration the test forbids, which is the more dangerous half of an
incomplete edit: the code was right and the prose recruited the next reader against it.

SCOPE, DELIBERATELY NOT BUILT (operator scope reduction, 2026-08-25)
--------------------------------------------------------------------
No ``tool_use_id`` fault identity, no cross-worktree keying, no liveness record, no
reconciliation state machine, no new command parsing. The append-only line **is** the
record; nothing deduplicates, so nothing can collide.
"""

from __future__ import annotations

import json
import sys
from typing import NoReturn, Sequence

from hooks import _hook_lib as lib
from hooks import fault_ledger

EVENT = "PostToolUseFailure"

#: ⚠ There is NO reconcile command. WP06 — the merge checkpoint that would have consumed the
#: fault ledger — was CUT from this mission, so the CLI subcommand this used to name always
#: answers "not available". Naming it anyway would send the agent to a surface that cannot
#: work, which is the livelock shape this mission hit three times before shipping a fourth.
RECONCILE = (
    "there is no reconcile command in this build \u2014 the merge checkpoint was cut, "
    "so tracking the fault is your obligation and nothing enforces it"
)

#: D-3, compressed to what is readable at the moment of a fault. The whole argument is
#: perishability: applying the workaround mutates the very state that proves what happened.
SOP = f"""⚠ A spec-kitty command just FAILED. Diagnose it COMPLETELY now, before you work around it.

Applying the workaround mutates the evidence — git state, the worktree, the event log, the
exact failing output. A diagnosis deferred to "later" may be a diagnosis of something that no
longer exists. Capture-and-continue is the STRICTER stance, not the lazier one: stopping needs
no diagnosis, while continuing needs both a root cause AND a working workaround — and the
workaround proves itself, because one that let the mission continue has been exercised.

DO NOW, at the fault (perishable):
  1. the exact command, its exact error, the build SHA, and the surrounding state
  2. the root cause — measured, not inferred. Filing fast is what produces false root causes:
     #257 and #258 were both filed with root causes that later measurement disproved.
  3. proof the workaround works
  4. capture 1-3 into a tracking issue

DEFER (not perishable): dedupe against docs/spec-kitty-issues.md and the upstream queue, the
intent check, and formatting to the template. Batch those afterwards.

THEN TRACK IT. The fault is recorded in the fault ledger for this session.

⚠ Nothing gates on that record. The merge checkpoint that would have enforced it was CUT
from this mission, so reconciliation is YOUR obligation and no mechanism will remind you.
Saying otherwise would be this gate claiming an enforcement it does not have.

Full lifecycle: {lib.RUNBOOK}"""

#: Told to the agent instead of silently swallowed. A dropped fault record is a missed
#: obligation — the one loss direction this model cannot tolerate — so the SOP must never
#: claim a record that did not land.
NOT_RECORDED = (
    "⚠ This fault was NOT recorded: the fault ledger could not be written. The merge gate "
    "will not know about it. Reconcile it by hand."
)


def _emit(text: str) -> NoReturn:
    """One channel: ``additionalContext`` on stdout, exit 0.

    ⚠ Never ``permissionDecision``. This event has no deny authority, and a checkpoint that
    *appears* to deny where it structurally cannot is the overstatement C-004 forbids.
    Compact separators and one explicit newline: the JSON must be ONE physical line.

    ⚠ **The stderr + ``exit 2`` second channel was REMOVED by operator decision.** WP01
    measured it reaching context, and it was shipped here first for redundancy. Three reasons
    it went, in order of weight:

    * ``exit 2`` produces a ``hook_blocking_error`` attachment that prefixes the hook's own
      absolute command line onto the model-visible text — **twice**, inside ``blockingError``
      and again in a sibling ``command`` field. Paying a path leak for redundancy on a channel
      already measured working is the wrong trade.
    * A ``blocking``-shaped signal on an event with no deny authority invites exactly the
      misreading C-004 exists to prevent, even though it cannot actually block.
    * It turned ``test_the_during_route_is_not_a_gate`` red on its exit-code assertion — a
      WP03-owned test — so redundancy here was buying a cross-package edit.

    The mission was pared to known problems. One measured channel is the known-sufficient
    thing; a second is defence-in-depth against a harness change nobody has observed.
    """
    body = {"hookEventName": EVENT, "additionalContext": text}
    sys.stdout.write(json.dumps({"hookSpecificOutput": body}, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    sys.exit(0)


def evaluate(payload: lib.Payload, segments: Sequence[Sequence[str]]) -> None:
    """Abstain by returning ``None``; otherwise record and emit. It never denies."""
    if payload.is_interrupt:
        # An operator pressing Ctrl-C is not a spec-kitty defect, and the SOP is noise at
        # that moment. Recorded as a fault it would block merges over a non-event.
        # ⚠ The dispatcher filters this too. Both layers own the rule on purpose: a filter
        # that lives only upstream is one refactor away from being gone.
        return None
    if not any(lib.program_of(argv) == fault_ledger.PROGRAM for argv in segments):
        # `matcher: "Bash"` fires on every failing Bash call, so the checkpoint decides for
        # itself. Tokenised argv, never a substring.
        return None
    recorded = fault_ledger.record_fault(payload, segments)
    _emit(SOP if recorded else f"{NOT_RECORDED}\n\n{SOP}")
