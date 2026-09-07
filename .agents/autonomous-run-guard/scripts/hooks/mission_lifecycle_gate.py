#!/usr/bin/env python3
"""The mission-lifecycle enforcement gate: one entry point, three checkpoints.

The obligations in ``docs/runbooks/autonomous-run-protocol.md`` already existed. What
they lacked was a trigger. This script is that trigger: a Claude Code hook that fires
without anyone deciding to invoke it.

WHAT THIS GATE PROVES
---------------------
It proves a step ran. Nothing more: a command was tokenised and matched a gated verb, a
marker was written after a tool call *succeeded*, a fault was recorded when a command
failed.

WHAT IT CANNOT PROVE — and must never be read as proving
--------------------------------------------------------
It **cannot prove** the judgment was sound. Specifically it cannot prove:

* that a sweep's *output was read*, rather than the query merely having run;
* that a closed upstream issue was actually checked against the build we run;
* that a fault nobody noticed occurred — an empty fault ledger and a recording path that
  never fired are indistinguishable from the outside, which is exactly why "no faults" is
  asserted explicitly and never inferred from silence.

Overstating any of that would make this the very defect class the gate exists to prevent
(C-004): a green nobody earned, inside the mechanism built to stop them.

⚠ CP-DURING is not a gate
-------------------------
``PostToolUseFailure`` cannot block — the tool has already run by the time it fires. The
during-checkpoint is **record plus notify**: it writes the fault and returns
``additionalContext`` carrying the D-3 capture SOP, so the SOP arrives while the evidence
is still alive. Calling it enforcement would overstate it. The enforcement of the D-3
obligation is CP-AFTER, which refuses a merge whose fault ledger is unreconciled.

ROUTING (FR-010b)
-----------------
Routes on ``hook_event_name``, never by guessing from which fields happen to be present:

===========================  ==========================================================
``PreToolUse``               consult the checkpoints for a gated invocation; otherwise
                             allow. **Writes nothing.**
``PostToolUse``              marker recording only — markers come from SUCCESS, never
                             from ``PreToolUse`` command text, which records *intent*.
``PostToolUseFailure``       CP-DURING: record the fault and inject the SOP. Cannot deny.
known non-tool events        silence, exit 0.
anything unrecognised        deny. An event whose authority we cannot know is answered
                             fail-closed.
===========================  ==========================================================

⚠ **A step performed and gated in the SAME call is denied, and that is correct.**
(Post-plan review finding F4.) The existing filing guard gets away with "record, then
evaluate" because it records from ``PreToolUse`` command *text* — which is the defect
FR-010 removes, since text records intent rather than execution. Once markers are written
from ``PostToolUse`` only, the marker for a step necessarily lands on a **later event**
than the call that performed it. So ``<sweep query> && spec-kitty agent mission create``
is refused: at the moment the gate evaluates, the sweep has not yet succeeded. The denial
message says so, otherwise it reads as a bug to the agent that just ran the query.

TWO SEAMS, so later work packages ADD FILES rather than editing this one
-----------------------------------------------------------------------
**1. Checkpoint seam.** ``scripts/hooks/checkpoints/{before,during,after}.py`` are
resolved by lookup and lazy import. Each module supplies:

    def evaluate(payload: lib.Payload, segments: list[list[str]]) -> None
        # abstain by returning None; gate by calling lib.deny(...)

and the during-module additionally may call ``lib.additional_context(...)``. A missing or
unimportable checkpoint module **denies** on a ``PreToolUse`` route. That default is safe
to land now precisely because the wiring is **WP08** and lands last: nothing invokes this
script in anger until the checkpoints exist, so the fail-closed default is a placeholder
being honest, not a bug for whoever lands next.

**2. CLI seam.** With a non-empty ``sys.argv[1:]`` this is an operator CLI
(``… fault reconcile``, ``… fault assert-none``), not a hook: it does not read stdin and
never prints hook JSON. The handler is resolved from the checkpoints package and supplied
by WP06; an unknown or unavailable subcommand exits non-zero with usage on **stderr**.

Divergences from the contracts, and the honest limits of command matching, are recorded in
``_hook_lib.py``'s module docstring — read that before "correcting" anything here. The one
most likely to be "corrected" back: a multi-line command is split by LINE before ``shlex``
sees it, because ``shlex`` never emits a newline token.
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

# Resolve `hooks.*` whether this file is run as a script (sys.path[0] is scripts/hooks/)
# or imported as `hooks.mission_lifecycle_gate` by the test suite.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from hooks import _hook_lib as lib  # noqa: E402

CHECKPOINT_PACKAGE = "hooks.checkpoints"

#: Programs whose invocation makes a checkpoint's opinion necessary. The dispatcher owns
#: *when a checkpoint is consulted*; each checkpoint owns *which verbs it gates*, so the
#: verb sets stay in WP04's and WP06's files. Coarse on purpose: a command that does not
#: invoke `spec-kitty` at all cannot be a lifecycle event, and asking is what costs.
GATED_PROGRAMS = frozenset({"spec-kitty"})

#: Consulted in order on a PreToolUse route.
#:
#: ⚠ CP-AFTER (``checkpoints/after.py``, WP06) was CANCELLED, so ``"after"`` is not listed.
#: It was listed until WP08 wired this dispatcher, and with the module absent the
#: fail-closed path below denied EVERY gated invocation with an infrastructure denial —
#: correct behaviour for a checkpoint that should exist, and a wall for one that never
#: will. Re-adding the name without landing the module reinstates that wall.
#: (Out-of-fence edit made by WP08 and authorised by the orchestrator; the CP-AFTER
#: references elsewhere in this file and in ``_hook_lib.py`` are now stale and are
#: reported to mission level rather than rewritten here.)
PRE_TOOL_CHECKPOINTS = ("before",)

#: Events that exist, carry no deny authority, and are not this gate's business. Listed
#: so that an *unrecognised* event can be told apart from a known-irrelevant one and
#: answered fail-closed.
NON_GATING_EVENTS = frozenset(
    {
        "SessionStart",
        "SessionEnd",
        "Stop",
        "SubagentStop",
        "SubagentStart",
        "Notification",
        "PreCompact",
        "PostCompact",
        "UserPromptSubmit",
    }
)


def _load_checkpoint(name: str):
    """Import a checkpoint module. Raises on absence; the caller decides what that means."""
    return importlib.import_module(f"{CHECKPOINT_PACKAGE}.{name}")


def _missing_checkpoint_denial(name: str, detail: str) -> str:
    return lib.infrastructure_denial(
        f"the {name!r} checkpoint could not be loaded, so this lifecycle command cannot be "
        "checked.",
        f"  ✗ {CHECKPOINT_PACKAGE}.{name} — {detail}",
        "",
        "Confirm the checkpoint modules are present, then retry:",
        "",
        "  .venv/bin/python -m pytest tests/hooks -q",
    )


#: Raw-text SCOPE test for the unparseable path only. Loose on purpose: over-matching costs a
#: denial inside this gate's own remit; under-matching would let an unparseable gated
#: invocation through.
_GATED_SHAPE_RE = re.compile(r"\bspec-kitty\b")


def _segments_or_deny(payload: lib.Payload) -> list[list[str]]:
    if payload.tool_name != "Bash":
        return []
    try:
        return lib.split_segments(payload.command)
    except lib.CommandParseError:
        # We cannot tell whether an untokenisable command is gated — but this gate's scope is
        # `spec-kitty` invocations, and a command showing no sign of being one is not ours.
        #
        # ⚠ MEASURED: denying EVERY untokenisable command refuses ordinary bash. An apostrophe
        # inside a heredoc body makes the whole command unparseable, and prose bodies carrying
        # an apostrophe are most of the commit messages written in this repo. A gate that
        # refuses ordinary work is a gate somebody turns off, and a disabled one stops nothing.
        #
        # A SCOPE test, not a parse: raw text naming `spec-kitty` still denies, because inside
        # our remit we fail closed. Outside it we abstain, which is what a guard with a stated
        # scope should do.
        #
        # ⚠ An earlier attempt stripped heredoc BODIES instead, and was reverted. A delimiter
        # matcher over raw text desynchronises on `<<<` here-strings, on `<<` inside a quoted
        # string, and on `<<` in arithmetic — silently converting denials into ALLOWS in both
        # guards. Fixing a false positive by introducing a fail-open is a bad trade, and the
        # direction it broke in was the one no test covered.
        if _GATED_SHAPE_RE.search(payload.command):
            lib.deny(lib.malformed_command_denial())
        lib.allow()


def _route_pre_tool_use(payload: lib.Payload) -> None:
    """Consult the checkpoints for a gated invocation. Writes nothing; see F4 above."""
    segments = _segments_or_deny(payload)
    if not any(lib.program_of(argv) in GATED_PROGRAMS for argv in segments):
        lib.allow()

    for name in PRE_TOOL_CHECKPOINTS:
        try:
            module = _load_checkpoint(name)
        except Exception as exc:  # noqa: BLE001 - fail closed: a checkpoint we cannot ask denies
            lib.deny(_missing_checkpoint_denial(name, type(exc).__name__))
        module.evaluate(payload, segments)  # abstains by returning; gates by denying
    lib.allow()


def _route_post_tool_use(payload: lib.Payload) -> None:
    """Marker recording only. Success is the whole point: this event fires on success."""
    try:
        segments = lib.split_segments(payload.command) if payload.tool_name == "Bash" else []
    except lib.CommandParseError:
        # A command that ran and succeeded but will not re-tokenise records nothing. The
        # consequence is a missing marker, which denies later — the safe direction. This
        # event has no authority to deny, so it must not pretend to.
        return
    lib.record_markers(payload, segments)


def _route_post_tool_use_failure(payload: lib.Payload) -> None:
    """CP-DURING. Record the fault and inject the SOP. It cannot refuse anything."""
    if payload.is_interrupt or payload.is_timeout:
        # An operator cancellation is not a defect (FR-003).
        return
    try:
        segments = lib.split_segments(payload.command) if payload.tool_name == "Bash" else []
    except lib.CommandParseError:
        return
    try:
        module = _load_checkpoint("during")
    except Exception:  # noqa: BLE001
        # ⚠ Deliberately NOT a denial. This event has no deny authority, so a denial here
        # would be an inert payload claiming a power the event does not have (C-004). The
        # unreconciled-fault check at CP-AFTER is what makes a missed fault visible.
        return
    module.evaluate(payload, segments)


def _run_cli(argv: list[str]) -> int:
    """The operator surface. A CLI, not a hook: stdin is not read and no hook JSON is
    printed. WP06 supplies the handler; this ships only the routing."""
    try:
        module = _load_checkpoint("cli")
        handler = module.main
    except Exception:
        print(
            "usage: mission_lifecycle_gate.py [fault reconcile --fault <id> --issue <ref>]\n"
            "       mission_lifecycle_gate.py [fault assert-none --by <who> --note <what>]\n"
            "\n"
            "The operator subcommands are not available in this build.\n"
            "With no arguments this script is a Claude Code hook and reads a payload on stdin.",
            file=sys.stderr,
        )
        return 2
    return int(handler(argv) or 0)


def _event_of(payload_raw) -> str | None:
    """The payload's ``hook_event_name``, or ``None`` when it does not carry a usable one.

    Resolved in ONE place and threaded to both the router and the fail-closed handler, so
    the handler cannot answer with a shape the event has no authority for (F3/C-004).
    """
    if not isinstance(payload_raw, dict):
        return None
    event = payload_raw.get("hook_event_name")
    return event if isinstance(event, str) and event.strip() else None


def _fail_closed(event: str | None, headline: str, *why: str) -> None:
    """The last-resort answer. DENY on ``PreToolUse``; on any other event, silence.

    ⚠ ``lib.deny`` hard-codes ``hookEventName: "PreToolUse"`` — correctly, since that is
    the only event carrying ``permissionDecision``. Routing *every* unpredicted exception
    through it therefore emitted a PreToolUse denial for a ``PostToolUse`` payload, which
    defeated ``lib.deny``'s own ``ValueError`` guard on exactly the path the guard exists
    for: a checkpoint calling ``deny(event="PostToolUseFailure")`` raises, this handler
    catches it, and re-emits the overstatement (C-004).

    A post event cannot block, so the honest answer there is to write nothing. That is not
    a fail-OPEN: the consequence is a marker not written or a fault not recorded, and both
    of those resolve toward a DENIAL at a later checkpoint — the same direction the post
    routes already take for a payload they cannot parse.

    When no event could be resolved at all, nothing is known about the call and the answer
    stays a denial (NFR-001).
    """
    if event is not None and event != "PreToolUse":
        lib.allow()
    lib.deny(lib.infrastructure_denial(headline, *why))


def _dispatch(payload_raw) -> None:
    event = _event_of(payload_raw)
    if event is None:
        lib.deny(
            lib.infrastructure_denial(
                "this hook payload carries no hook_event_name, so no response shape is "
                "correct for it.",
                "  ✗ hook_event_name is absent or empty",
            )
        )

    if event in NON_GATING_EVENTS:
        lib.allow()

    if event == "PreToolUse":
        # Only this event has deny authority, so only here is a validation failure
        # answerable with a denial.
        try:
            payload = lib.parse_payload_mapping(payload_raw)
        except lib.PayloadError as exc:
            lib.deny(
                lib.infrastructure_denial(
                    "this hook payload could not be trusted, so the command it describes "
                    "cannot be checked.",
                    f"  ✗ {exc}",
                )
            )
        _route_pre_tool_use(payload)
        lib.allow()

    if event in {"PostToolUse", "PostToolUseFailure"}:
        try:
            payload = lib.parse_payload_mapping(payload_raw)
        except lib.PayloadError:
            # No deny authority here, and a malformed payload records nothing. The
            # consequence is a missing marker or an unrecorded fault, both of which point
            # toward a denial at a later checkpoint.
            lib.allow()
        if event == "PostToolUse":
            _route_post_tool_use(payload)
        else:
            _route_post_tool_use_failure(payload)
        lib.allow()

    lib.deny(
        lib.infrastructure_denial(
            f"this gate does not recognise the hook event {event!r}, so it cannot know "
            "whether the call needs checking.",
            f"  ✗ unrecognised hook event: {event!r}",
            "",
            "An event whose authority is unknown is answered fail-closed. If this event is",
            "legitimate, it belongs in this script's NON_GATING_EVENTS or a route of its own.",
        )
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point. Every failure path resolves toward DENY (NFR-001)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        return _run_cli(args)

    # Resolved BEFORE dispatch and outside the try, so the handlers below know which
    # response shape the event actually authorises. `None` means the payload never got far
    # enough to say — see _fail_closed.
    event: str | None = None
    try:
        payload_raw = lib.parse_json_object(sys.stdin)
        event = _event_of(payload_raw)
        _dispatch(payload_raw)
    except SystemExit:
        # allow()/deny()/additional_context() all exit; let their decision stand.
        raise
    except lib.PayloadError as exc:
        _fail_closed(
            event,
            "this hook payload could not be read, so nothing about the call it "
            "describes has been established.",
            f"  ✗ {exc}",
        )
    except BaseException as exc:  # noqa: BLE001
        # The exception CLASS only. Its message can quote payload content, and payload
        # content can carry a credential (NFR-004).
        _fail_closed(
            event,
            "this gate raised an unexpected exception, so it has established nothing "
            "about this call.",
            f"  ✗ {type(exc).__name__} while evaluating the payload",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
