#!/usr/bin/env python3
"""PreToolUse guard for the spec-kitty bug-reporting runbook.

Enforces the two steps of docs/runbooks/spec-kitty-bug-reporting.md that leave an
observable trace: **dedup ran** (step 2) and **the attribution footer is present**
(step 4). Both are gated at `gh issue create|comment` against any repository that is
not ours — see `_hook_lib.OURS`, the single place that answers "is this ours?".

WHAT THIS PROVES, AND WHAT IT DOES NOT
--------------------------------------
It proves a step's *artifact* exists in this session — a command ran, a file was
read. It cannot prove the *judgment* was sound: that the dedup hits were actually
read, that a near-match was correctly rejected, that the intent check's verdict was
honest. Nothing observable from a tool payload can prove that.

That limit is worth stating because pretending otherwise would make this the very
thing we keep filing bugs about — a green that means less than it looks like.

It is still worth having, because the failure it catches is the one that actually
happens: **silent omission**. On 2026-08-23 two issues went out (#3698,
spec-kitty-saas#1112) with no dedup and no footer, not because the steps were
judged unnecessary but because the runbook was never opened. Runbook v2.1 records
nine earlier filings that missed the footer the same way. A gate cannot stop bad
judgment; it can stop a step being skipped without anyone noticing.

Consequently a filing that trips this gate should be fixed by *running the step*,
never by adding a token command to satisfy the marker.

SESSION LEDGER
--------------
Markers are recorded per `session_id` under a temp dir. A fresh session starts with
an empty ledger, which is correct: dedup is per-finding, and a session that files
without having searched in that session has not searched.

MENTION IS NOT INVOCATION — AND THE THREE LIMITS THAT REMAIN
------------------------------------------------------------
Filing detection and marker recording both read **argv token positions**, via the
shared `shlex` helpers in `_hook_lib.py`. The two guards in this repository parse
commands the same way on purpose; a second copy of the parsing here would drift.

Substring matching, which this replaced, was wrong in both directions at once, and
both directions were observed in the field:

* a Bash command whose quoted *text* mentioned a filing was DENIED — it blocked an
  agent that was only writing a file, twice in one session;
* `echo "gh issue list …"` SET the `queue` marker. Measured live, a session ledger
  read `{"queue": true, "register": true, "intent": true}` with none of the three
  steps run — every marker set by an authoring command that quoted the query.

Three limits follow, stated here rather than left for the next reader to discover:

1. **`PreToolUse` sees an INTENDED command, never a result.** A real queue search
   still marks even if it returns nothing, because this event fires *before* the
   tool runs and cannot know whether it will succeed. What argv parsing removed is
   *mention-shaped* evidence, not deliberate circumvention. Marking from
   `PostToolUse` — which fires only on success — belongs to the lifecycle gate,
   not to this guard.
2. **A body read from a file is read TWICE**: once here, and again by `gh` when the
   command runs. This is a TOCTOU window. The gate therefore proves the file
   *contained* a footer when it was checked, and not what was posted.
3. **A command that will not tokenise is denied**, filing or not, because a command
   the gate cannot parse is one it cannot clear. That is wider than the filings this
   guard exists for, and it is the same stance the sibling lifecycle gate takes for
   the same reason.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

# Resolve `hooks.*` whether this file is run as a script (sys.path[0] is scripts/hooks/)
# or imported directly by the test suite. Same shim as mission_lifecycle_gate.py.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from hooks import _hook_lib as lib  # noqa: E402

FOOTER_MARKER = "Authored by"

# ⚠ THIS MODULE HAS NO PRIVATE NOTION OF "UPSTREAM". It once carried
# `UPSTREAM = "Priivacy-ai/"` here, an organisation prefix entirely separate from the
# shared library's. Two definitions of one concept is how one of them went stale without
# the other noticing — the defect this mission removes. The ownership seam now arrives
# through `lib` and is reached as `lib.OURS`, `lib.is_ours`, `lib.target_repo` and
# `lib.UPSTREAM_TARGETS`.
#
# ⚠ Reached through `lib.` at every use, NEVER copied into a module-level alias here.
# An alias is a second name for the canonical value, and a second name is the shape the
# split-brain took the first time. It also keeps the remedy text genuinely DERIVED: swap
# `lib.UPSTREAM_TARGETS` and the printed remedy changes with it (T010).

#: A raw-text SCOPE test used ONLY on the unparseable path — never for a gating decision.
#: Deliberately loose: over-matching costs a denial inside this guard's own remit, which is
#: safe. Under-matching would let an unparseable filing through, so it asks only whether the
#: words `gh` and `issue` both appear at all.
_FILING_SHAPE_RE = re.compile(r"\bgh\b[\s\S]*\bissue\b|\bissue\b[\s\S]*\bgh\b")
RUNBOOK = "docs/runbooks/spec-kitty-bug-reporting.md"
TEMPLATE = "docs/templates/spec-kitty-bug-report-external-template.md"
REGISTER = "spec-kitty-issues.md"

#: `gh issue <verb>` values this guard gates. Compared by token POSITION.
FILING_VERBS = ("create", "comment")

#: 1 MiB is far past any issue body. The read is bounded by reading `cap + 1` bytes and
#: refusing when the extra byte arrives — NEVER by `st_size`, which is 0 for a FIFO and
#: would make the bound infinite in exactly the case it exists for.
BODY_SIZE_CAP = 1024 * 1024

# --- step detection -------------------------------------------------------
#
# ALLOWLISTS, not denylists. A denylist of `echo` is defeated by `printf`, `:`, `true`,
# a comment and a heredoc equally well; naming the one program that bit is how a guard
# acquires a hole the size of every other program. An `argv[0]` outside these sets does
# not mark, which is the fail-closed direction: unproven evidence means the gate denies
# and the agent runs the step for real.

#: Queue-search invocations, by verb prefix.
QUEUE_VERBS = (("gh", "issue", "list"), ("gh", "search", "issues"), ("gh", "issue", "view"))

#: Programs that actually READ a file. `ls`, `touch` and `stat` are absent on purpose:
#: they NAME the path without reading it.
REGISTER_READERS = frozenset(
    {"cat", "bat", "head", "tail", "less", "more", "nl", "sed", "awk", "grep", "rg", "view", "git"}
)

DEDUP_SCRIPT = "upstream_dedup.py"
_PYTHON_RE = re.compile(r"^python(?:\d+(?:\.\d+)*)?$")
_TEST_PATH_RE = re.compile(r"\btests?/")

LEDGER_DIR = os.path.join(tempfile.gettempdir(), "spec-kitty-filing-guard")


def ledger_path(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "unknown")
    return os.path.join(LEDGER_DIR, f"{safe}.json")


# ⚠ DO NOT "FIX" THE SWALLOW BELOW. It is the SAME idiom as the qa #277 fail-open in
# `main()`, and it is SAFE HERE because the consequence runs the other way. Trace it:
#
#   unreadable or corrupt ledger -> {} -> no markers -> missing_register/missing_queue
#   are true -> the gate DENIES;
#   `mark()` also calls it, so a corrupt read makes `mark()` write a fresh dict, LOSING
#   markers -> again toward DENY.
#
# Both directions land on deny, which is the safe direction, and
# `test_corrupt_ledger_denies_and_read_ledger_is_unchanged` measures it rather than
# asserting it. Contrast the lifecycle gate, whose reader returns a STATUS because there
# FRESH and CORRUPT must produce different messages. This guard has one message path, and
# the swallow is not reachable as a fail-open.
def read_ledger(session_id: str) -> dict:
    try:
        with open(ledger_path(session_id)) as fh:
            return json.load(fh)
    except Exception:
        return {}


def mark(session_id: str, key: str) -> None:
    try:
        os.makedirs(LEDGER_DIR, exist_ok=True)
        led = read_ledger(session_id)
        led[key] = True
        with open(ledger_path(session_id), "w") as fh:
            json.dump(led, fh)
    except Exception:
        pass  # never let bookkeeping break a tool call


def allow() -> None:
    sys.exit(0)


def deny(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    # Hardcoded, because a payload the gate could not read carries no
                    # `hook_event_name` to echo. This holds only while the wiring stays
                    # PreToolUse-only on both matchers; scripts/hooks/check_wiring.py is
                    # the surface that would notice if it changed.
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def context(text: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": text,
                }
            }
        )
    )
    sys.exit(0)


DRAFT_CONTEXT = f"""You are writing to docs/drafts/, which stages copy destined to leave this repo.
{RUNBOOK} governs it. Required BEFORE drafting, not after:

  2a. Read docs/{REGISTER} FIRST. If the symptom is already there, apply the workaround
      and stop — and check whether an existing row attributes it to a cause that no
      longer holds.
  2b. Search the upstream queue, open AND closed:
      gh issue list --repo <repo> --search "<symptom>" --state all
  2d. INTENT CHECK, required for any "they forgot / missed / failed to X" finding.
      Search the PRODUCT'S OWN TESTS for the mechanism you are about to call missing.
      A behaviour pinned by a green test is a DECISION, not an oversight.
      Resolve the product tree at the INSTALLED BUILD's SHA (git show <sha>:<path>) —
      a working checkout can be weeks stale, which makes the check search the wrong code.

Then draft from {TEMPLATE}, including the mandatory attribution footer."""

#: Verbatim and mandatory in every denial this guard emits (denial-payload §3.1). Two
#: claims: the anti-pattern, and the honest limit.
CLOSING_BLOCK = [
    "⚠ Fix this by RUNNING the step, never by adding a token command to satisfy the",
    "  marker. This gate proves a step ran; it cannot prove the judgment was sound.",
    f"  Full lifecycle: {RUNBOOK}",
]

#: The resolvable alternative, shown as a runnable line wherever the gate refuses because
#: it could not read something (denial-payload §3.2).
BODY_FILE_REMEDY = [
    "  gh issue create --repo <owner>/<repo> --title \"<title>\" \\",
    "    --body-file docs/drafts/<your-draft>.md",
]

GATE_SELF_CHECK = "  .venv/bin/python -m pytest tests/hooks -q"

#: A target is echoed back to the reader ONLY when it looks like one. Every other denial
#: in this module renders fixed strings, and that is an NFR-004 posture, not an accident:
#: argv can carry a credential and a denial message is not a safe place to put one. The
#: reader needs to see WHICH repository was judged, so the value is rendered — through
#: this shape test, at the sink, which is the only place that knows what is being printed.
_PRINTABLE_TARGET_RE = re.compile(r"[A-Za-z0-9._/-]{1,100}\Z")
_UNPRINTABLE_TARGET = "<a value the gate will not echo>"


def render_target(target: str | None) -> str:
    if target is None:
        return "<none named>"
    return target if _PRINTABLE_TARGET_RE.match(target) else _UNPRINTABLE_TARGET


def ownership_rule_lines(target: str | None) -> list[str]:
    """Why this filing is gated, stated as the rule actually in force (FR-013).

    ⚠ THE HONEST SENTENCE CHANGED WITH THE RULE. This block used to assert that the
    target was "upstream Priivacy-ai" — a confident claim about an organisation prefix
    that stopped being the criterion, and stopped existing, on the day of the rename.
    Classification is now ownership-inverted: the gate knows only that the target is not
    in the set we own. Saying more than that would be the gate making a false statement
    about its own rule, which is worse than saying less.

    Everything printed here DERIVES from the canonical sets, so a rename edits one place
    and every message follows.
    """
    ours = ", ".join(sorted(lib.OURS)) or "<empty>"
    return [
        f"  Target: {render_target(target)} — this repository is not in the set we own,",
        f"  so the upstream bug-reporting runbook applies. We own: {ours}.",
        "  Anything outside that set is treated as upstream, including a repository we do",
        "  not recognise at all: the unknown falls to the enforcing side on purpose.",
        "",
    ]


def build_denial(missing_register: bool, missing_queue: bool, missing_footer: bool,
                 intent_checked: bool, *, footer_from_file: bool = False,
                 target: str | None = None) -> str:
    lines = ["BLOCKED — this filing has not completed the bug-reporting runbook.", ""]
    lines += ownership_rule_lines(target)
    if missing_register or missing_queue:
        lines.append("DEDUP (step 2) — no trace of it in this session:")
        if missing_register:
            lines.append(f"  ✗ docs/{REGISTER} was not read. Read it FIRST: it answers a")
            lines.append("    question the queue cannot — whether the symptom is expected, and")
            lines.append("    whether an existing row blames a cause that no longer holds.")
        if missing_queue:
            lines.append("  ✗ the upstream queue was not searched. Open AND closed:")
            lines.append('      gh issue list --repo <repo> --search "<symptom>" --state all')
        lines.append("")
        lines.append("  Dedup is step 2 and not step 5 because skipping it wastes the DRAFT,")
        lines.append("  not just the filing. Run it, then re-read what you drafted — it")
        lines.append("  routinely changes the finding.")
        lines.append("")
    if missing_footer:
        lines += [
            "FOOTER (step 4) — missing from the body:",
            "",
            "    **Authored by**: Kent Gale & <agent, model>, <date>",
            "    **Submission approved by**: Kent Gale, <date>",
            "",
            "  It discloses that an agent drafted the copy and names who approved it.",
            f"  Copy composed ad hoc rather than from {TEMPLATE}",
            "  still needs it — that is exactly how it gets missed.",
            "",
            "  Add it, then re-file:",
            "",
        ]
        lines += BODY_FILE_REMEDY
        lines.append("")
        if footer_from_file:
            lines += [
                "  The body was read from the file you named, so this is a report about what",
                "  that file contained WHEN CHECKED — not what was posted. The filing command",
                "  reads it again; the gate cannot see that second read.",
                "",
            ]
    if not intent_checked:
        lines += [
            "INTENT CHECK (step 2d) — no trace in this session. NOT blocking, because it",
            "  is only required for a \"they forgot / missed X\" finding. If this filing",
            "  makes such a claim, search the product's OWN TESTS for the mechanism first:",
            "  a behaviour pinned by a green test is a DECISION, not an oversight.",
            "  Resolve the product tree at the installed build's SHA — a stale checkout",
            "  searches the wrong code.",
            "",
        ]
    lines += CLOSING_BLOCK
    return "\n".join(lines)


def build_parse_failure_denial(exc_name: str) -> str:
    """qa #277: a payload the gate could not read is a DENIAL, never a pass.

    Deliberately NOT `build_denial`'s text. A broken payload is not a missing dedup step,
    and sending the agent to re-run the sweep for it wastes the sweep and hides the real
    fault — the same reasoning that keeps FRESH and CORRUPT apart in the lifecycle gate.

    Only the exception CLASS is rendered. `str(exc)` would quote payload content back into
    the message, and a tool payload can carry a token (NFR-004).
    """
    return "\n".join(
        [
            "BLOCKED — this hook could not read the tool payload it was asked to judge.",
            "",
            f"  ✗ reading the payload raised {exc_name}.",
            "",
            "This is a DENIAL and not a pass. Until 2026-08-25 this path allowed, so any",
            "malformed payload waved a filing through with the runbook unchecked and nothing",
            "recorded that the check had not run. A guard whose failure mode is \"yes\"",
            "manufactures a green nobody earned, which is worse than no guard: it is a green",
            "someone will cite.",
            "",
            "The exception class is shown and the payload is not, because a tool payload can",
            "carry a credential and a denial message is not a safe place to put one.",
            "",
            "If this is reproducible, start with the gate's own tests:",
            "",
            GATE_SELF_CHECK,
            "",
        ]
        + CLOSING_BLOCK
    )


def build_unreadable_body_denial(flag: str, form: str, *why: str) -> str:
    """FR-009: name the step, not the failure.

    Reporting "missing footer" for a body the gate never read is the pre-fix behaviour and
    it is misleading — it sends the author to add a footer that is already there. That is
    qa #276's second cost, after the denial itself.
    """
    lines = [
        "BLOCKED — this filing's body cannot be read, so the attribution footer cannot be",
        "checked. This is NOT a report that the footer is missing.",
        "",
        f"  ✗ {flag} — {form}",
        "",
    ]
    lines += list(why)
    if why:
        lines.append("")
    lines += [
        "Write the body to a file and pass it by path, which the gate can read:",
        "",
    ]
    lines += BODY_FILE_REMEDY
    lines += [
        "",
        "Resolving the form above would mean executing or guessing part of a command the",
        "gate is deciding whether to permit. A gate that runs its own input is not a gate,",
        "so naming what it cannot read is the honest refusal.",
        "",
        "A body the gate CAN read is checked when it is read, and read again by the filing",
        "command — so a pass proves what the file contained when checked, not what was",
        "posted.",
        "",
    ]
    return "\n".join(lines + CLOSING_BLOCK)


def build_unresolvable_repo_denial(form: str) -> str:
    """The deliberate widening (research R-4's open risk), given its own message.

    A `--repo` value the gate cannot resolve cannot be shown to be non-upstream, so the
    filing denies. Naming the footer here would send the author to fix a thing that is not
    wrong; it is the REPOSITORY that is unreadable.
    """
    ours = ", ".join(sorted(lib.OURS)) or "<empty>"
    example = lib.UPSTREAM_TARGETS[0] if lib.UPSTREAM_TARGETS else "<owner>/<repo>"
    return "\n".join(
        [
            "BLOCKED — this filing's --repo value cannot be resolved, so the gate cannot tell",
            "whether it targets a repository we own. It is the REPOSITORY that is unreadable",
            "here, not the footer and not the dedup evidence.",
            "",
            f"  ✗ --repo — {form}",
            "",
            f"  The set we own: {ours}. Anything outside it is treated as upstream and must",
            "  carry the runbook's evidence — so a target the gate cannot read is one it",
            "  cannot place on either side.",
            "",
            "This denies where the old substring check allowed, and that is intended: a",
            "repository the gate cannot see is one it cannot clear. Pass it literally:",
            "",
            f"  gh issue create --repo {example} --title \"<title>\" \\",
            "    --body-file docs/drafts/<your-draft>.md",
            "",
        ]
        + CLOSING_BLOCK
    )


def build_untokenisable_denial() -> str:
    return "\n".join(
        [
            "BLOCKED — this Bash command could not be tokenised, so the gate cannot tell",
            "whether it files an upstream issue.",
            "",
            "  ✗ unbalanced quoting in the command",
            "",
            "A command the gate cannot parse is one it cannot clear. Close the quote and",
            "re-run; if the command is correct as written, split it so each invocation is",
            "its own line.",
            "",
            "The gate's own tests are the place to start if this looks wrong:",
            "",
            GATE_SELF_CHECK,
            "",
        ]
        + CLOSING_BLOCK
    )


# =============================================================================
# argv inspection — token POSITION, never substring
# =============================================================================

FORM_COMMAND_SUBSTITUTION = "command substitution"
FORM_VARIABLE_EXPANSION = "variable expansion"
FORM_STDIN = "the body is read from stdin"
FORM_EDITOR = "the body is composed in an editor"
FORM_TEMPLATE = "the body comes from a template"
FORM_PROMPT = "no body flag is present, so the tool would prompt for it"
FORM_MULTIPLE = "more than one body source is given"
FORM_NO_VALUE = "the body flag was given without a value"
FORM_NOT_A_FILE = "the path does not name a readable regular file"
FORM_NO_CWD = "the path is relative and the payload carries no cwd to anchor it"
FORM_TOO_LARGE = f"the file is larger than the {BODY_SIZE_CAP // 1024 // 1024} MiB the gate will read"
FORM_NOT_UTF8 = "the file is not valid UTF-8"

_VARIABLE_RE = re.compile(r"\$\{?[A-Za-z_]")


def dynamic_form(token: str) -> str | None:
    """Which dynamic form `token` is, or None if it is a literal.

    `shlex` expands nothing, so a dynamic value survives as a recognisable token and an
    honest refusal is possible. MEASURED shapes, because the tokeniser splits some of them:
    `"$(cat f)"` survives whole, bare `$(cat f)` leaves `$` behind when the segment breaks
    at `(`, and `` `cat f` `` splits into two tokens the first of which keeps the backtick.
    """
    if "`" in token:
        return FORM_COMMAND_SUBSTITUTION
    if "$(" in token or token == "$":
        return FORM_COMMAND_SUBSTITUTION
    if _VARIABLE_RE.search(token):
        return FORM_VARIABLE_EXPANSION
    if "$" in token:
        return FORM_COMMAND_SUBSTITUTION
    return None


def flag_value(argv: list[str], *flags: str) -> tuple[str | None, str | None, bool]:
    """`(flag_as_written, value, present)` for the first of `flags` that appears.

    Handles the separated form and, for long flags, the `=` form. `present` distinguishes
    "flag absent" from "flag present with no value", which are different refusals.
    """
    for index, token in enumerate(argv):
        for flag in flags:
            if token == flag:
                value = argv[index + 1] if index + 1 < len(argv) else None
                return flag, value, True
            if flag.startswith("--") and token.startswith(f"{flag}="):
                return flag, token[len(flag) + 1 :], True
    return None, None, False


def is_filing(argv: list[str]) -> bool:
    """`gh issue create|comment`, by token position. Nothing else is a filing.

    Under `shlex` a quoted mention is a single ARGUMENT to whatever program the segment
    invokes, so `echo "… gh issue create …"` has `argv[0] == "echo"` and is not a filing.
    """
    return any(lib.argv_matches(argv, ("gh", "issue", verb)) for verb in FILING_VERBS)


def targets_upstream(argv: list[str]) -> bool:
    """True when this filing targets a repository that is **not ours**.

    THE QUESTION IS ABOUT THE TARGET, AND ONLY THE TARGET. This used to be
    `any(UPSTREAM in token for token in argv)` — a substring scan of EVERY token in the
    segment — and the target `--repo` value, parsed a few lines above the call site, was
    thrown away unused. Two things followed, and the second is worse than the first.

    MEASURED FALSE REFUSAL. `gh issue create --repo spec-kitty/spec-kitty-qa --title T
    --body "tracks <upstream>#12"` was DENIED: an internal filing blocked because its
    BODY quoted an upstream reference. Whether the gate fired then depended on whether
    the body arrived via `--body` or `--body-file`, which is incoherent for a question
    about where a filing is going.

    AND IT GETS STRICTLY WORSE UNDER THE INVERSION. Classification is now "not ours
    implies upstream" (FR-002), so a token scan would have to ask whether every token is
    ours — and almost no token is. Body prose, titles, labels and paths would all read as
    upstream. The token scan is not merely imprecise here; it is unimplementable.

    The four cases, all decided from `lib.target_repo`'s single extraction:

    * target IS ours  -> not upstream, allow. Body content is IRRELEVANT.
    * target is NOT ours -> upstream, demand the runbook's evidence. Unknown falls to the
      enforcing side, which is FR-002's whole point: `octocat/hello` is gated.
    * target present but UNRESOLVABLE (a substitution, a variable) -> never reaches here.
      `evaluate_bash` denies first, naming the form, which is today's behaviour.
    * NO target named -> ``False``, abstain. This is today's behaviour preserved and it
      is a KNOWN, DELIBERATELY UNGUARDED GAP: `gh` would resolve the git remote, and
      resolving one here was considered and CUT (qa#291 item 4). No subprocess.

    ⚠ ABSTENTION IS NOT A FAILURE DIRECTION. Returning ``False`` for an unnamed target is
    a judgement that the command is outside this guard's remit, not an error posture. The
    guard's fail-CLOSED posture lives in :func:`run`, and the two must not be conflated.

    One notion of "upstream" in this tree, not two: this delegates rather than
    reimplements, so `_hook_lib` stays the sole authority.
    """
    return lib.names_upstream(argv)


def resolve_body(argv: list[str], cwd: str) -> tuple[str | None, str | None]:
    """`(body_text, denial)` — exactly one of them is not None.

    Resolution is attempted ONLY against the single segment that is the filing invocation.
    Scanning every segment produced a false-positive class where a `-e` belonging to a
    different program was reported as this filing's editor flag.
    """
    if flag_value(argv, "--editor", "-e")[2]:
        return None, build_unreadable_body_denial("--editor", FORM_EDITOR)
    if flag_value(argv, "--template", "-T")[2]:
        return None, build_unreadable_body_denial("--template", FORM_TEMPLATE)

    file_flag, file_value, file_present = flag_value(argv, "--body-file", "-F")
    text_flag, text_value, text_present = flag_value(argv, "--body", "-b")

    if file_present and text_present:
        return None, build_unreadable_body_denial(
            f"{text_flag} and {file_flag}", FORM_MULTIPLE,
            "  The gate will not guess which one the tool would use.",
        )
    if not file_present and not text_present:
        return None, build_unreadable_body_denial(
            "gh issue", FORM_PROMPT,
            "  A body the gate never sees is a body it cannot check.",
        )

    flag = file_flag if file_present else text_flag
    value = file_value if file_present else text_value
    if value is None:
        return None, build_unreadable_body_denial(str(flag), FORM_NO_VALUE)

    form = dynamic_form(value)
    if form is not None:
        return None, build_unreadable_body_denial(str(flag), form)

    if not file_present:
        return value, None

    if value == "-":
        return None, build_unreadable_body_denial(str(flag), FORM_STDIN)
    return read_body_file(str(flag), value, cwd)


def read_body_file(flag: str, raw_path: str, cwd: str) -> tuple[str | None, str | None]:
    """Read a file-supplied body, bounded, and never echo what it contained (NFR-004).

    ⚠ `is_file()` before `open()` is load-bearing and not a tidiness check. A FIFO reports
    `st_size == 0`, so a bound derived from the stat is no bound at all — and `open()` on a
    FIFO with no writer blocks forever, wedging the tool call this hook was asked to judge.
    `is_file()` is `S_ISREG`, so a FIFO, a directory and a device all fail it before
    anything is opened.
    """
    path = Path(raw_path)
    if not path.is_absolute():
        if not cwd:
            return None, build_unreadable_body_denial(
                f"{flag} {raw_path}", FORM_NO_CWD,
                "  Pass an absolute path, or re-run so the payload carries a cwd.",
            )
        path = Path(cwd) / path

    try:
        if not path.is_file():
            return None, build_unreadable_body_denial(
                f"{flag} {raw_path}", FORM_NOT_A_FILE,
                f"  Resolved to: {path}",
            )
        with open(path, encoding="utf-8") as fh:
            # cap + 1: the extra byte is how the cap is DETECTED. Bounding by st_size
            # would trust a number the file controls.
            body = fh.read(BODY_SIZE_CAP + 1)
    except UnicodeDecodeError:
        return None, build_unreadable_body_denial(
            f"{flag} {raw_path}", FORM_NOT_UTF8,
            "  The bytes are not rendered here; a draft body is exactly the kind of text",
            "  that carries a pasted credential.",
        )
    except OSError as exc:
        return None, build_unreadable_body_denial(
            f"{flag} {raw_path}", f"the file could not be read ({type(exc).__name__})",
            f"  Resolved to: {path}",
        )

    if len(body) > BODY_SIZE_CAP:
        return None, build_unreadable_body_denial(f"{flag} {raw_path}", FORM_TOO_LARGE)
    return body, None


# =============================================================================
# Marker recording — an ALLOWLIST of programs that could have performed the step
# =============================================================================


def _is_python(program: str) -> bool:
    return bool(_PYTHON_RE.match(program))


def detect_markers(segments: list[list[str]]) -> set[str]:
    """Which markers these segments are evidence for.

    Keyed on the segment's own `argv[0]`. A program outside the allowlist earns nothing —
    the fail-closed direction, because unknown means unproven, which means the gate denies
    and the agent runs the step for real.
    """
    found: set[str] = set()
    for raw_argv in segments:
        argv = lib.effective_argv(raw_argv)
        if not argv:
            continue
        program = lib.program_of(argv)
        names_register = any(REGISTER in token for token in argv[1:])

        if names_register and (program in REGISTER_READERS or _is_python(program)):
            found.add("register")

        # ⚠ BOTH branches are conditioned on ownership, and conditioning only the first
        # would be worse than conditioning neither. `queue` is what unlocks a filing into
        # somebody else's tracker, so evidence for it must be about somebody else's
        # tracker. WP01 established exactly this for the mission-start gate's markers —
        # "a sweep of our own issues would satisfy a gate whose entire purpose is to make
        # us look at the product under test" — and this module, which adopted that gate's
        # ownership seam for classification, never adopted it here.
        #
        # If only the `gh` branch were conditioned the free marker would simply move one
        # line down, onto the branch `docs/runbooks/spec-kitty-bug-reporting.md` actually
        # prescribes — so it would be the exercised path, not an obscure one.
        #
        # `intent` is deliberately left unconditioned: it is advisory and never blocks
        # (see the ledger read below, where only `register` and `queue` gate the filing).
        swept_upstream = lib.names_upstream(argv)

        if (
            program == "gh"
            and swept_upstream
            and any(lib.argv_matches(argv, verb) for verb in QUEUE_VERBS)
        ):
            found.add("queue")

        # The dedup script is credited on a WEAKER condition than the `gh` branch, and the
        # asymmetry is forced by its sanctioned form. `docs/runbooks/spec-kitty-bug-reporting.md`
        # invokes it as `upstream_dedup.py --query "<keywords>"`, naming no repository at all — the
        # script resolves that itself. Requiring `names_upstream` here would refuse the
        # prescribed command, which is the livelock shape, so the condition is the narrower
        # "the target is not OURS": a named target that is ours is refused, and an unnamed
        # one is credited because nothing here can tell what it resolves to. That gap is the
        # same one qa#291 item 4 tracks.
        #
        # ⚠ The script must be argv[1] — POSITION, not an option blacklist.
        #
        # This used to be a substring test over every token, so merely MENTIONING the
        # filename earned the marker while executing nothing. The first attempt at this
        # excluded `-c`, and a pre-merge review immediately found three more:
        # `python3 --version scripts/upstream_dedup.py`, `-V`, and `-m json.tool …` all
        # name the script, all earn the marker, and none of them runs it — the interpreter
        # consumes the command and exits first. That is an enumerated deny over another
        # program's option grammar, too narrow by exactly the margin such a list is always
        # too narrow by.
        #
        # Python runs a SCRIPT only when the script path is the first argument. Requiring
        # that is positive-form and total OVER INTERPRETER OPTION GRAMMAR: every present
        # and future interpreter option fails closed without being named. The sanctioned
        # invocations — `python scripts/upstream_dedup.py --query "<keywords>"` and the
        # `.venv/bin/python` spelling — both satisfy it.
        #
        # ⚠ "Total" is scoped to that grammar and no further, because an earlier wording
        # here said "total" flat. `DEDUP_SCRIPT in argv[1]` is a SUBSTRING test over a
        # path, and this guard marks from PreToolUse TEXT, so the file need not exist or
        # run. MEASURED: `python3 /tmp/not_really_upstream_dedup.py` earns `queue`.
        # Tightening to a basename match would narrow it; the marking-from-intent half is
        # architectural and belongs with qa#292, not here.
        runs_dedup_script = len(argv) > 1 and DEDUP_SCRIPT in argv[1]
        if _is_python(program) and runs_dedup_script:
            if not lib.is_ours(lib.target_repo(argv)):
                found.add("queue")
            if "--mechanism" in argv:
                found.add("intent")

        if program == "git" and any(
            lib.argv_matches(argv, verb) for verb in (("git", "grep"), ("git", "show"))
        ):
            if any(_TEST_PATH_RE.search(token) for token in argv[1:]):
                found.add("intent")
    return found


# =============================================================================
# Entry
# =============================================================================


def evaluate_bash(session_id: str, command: str, cwd: str) -> None:
    try:
        segments = lib.split_segments(command)
    except lib.CommandParseError:
        # We cannot tell whether an untokenisable command files — but this guard's scope is
        # upstream filings, and a command showing no sign of being one is not ours to refuse.
        #
        # ⚠ MEASURED: denying every untokenisable command refuses ordinary bash. An apostrophe
        # inside a heredoc body makes the whole command unparseable, and prose bodies with
        # apostrophes are most of the commit messages and issue bodies written in this repo.
        # A gate that refuses ordinary work is a gate somebody turns off.
        #
        # This is a SCOPE test, not a parse: if the raw text shows a filing verb we still deny,
        # because inside our scope we fail closed. Outside it we abstain, which is what a guard
        # with a stated remit should do. An earlier attempt stripped heredoc bodies instead and
        # was reverted — a delimiter matcher over raw text desynchronises on `<<<`, on `<<`
        # inside quotes, and on arithmetic, and silently ALLOWED real filings.
        if _FILING_SHAPE_RE.search(command):
            deny(build_untokenisable_denial())
        allow()

    # Record dedup evidence BEFORE evaluating the gate.
    for key in sorted(detect_markers(segments)):
        mark(session_id, key)

    for raw_argv in segments:
        argv = lib.effective_argv(raw_argv)
        if not is_filing(argv):
            continue

        # ONE EXTRACTION, READ BY EVERY BRANCH BELOW. `lib.target_repo` is the sole
        # authority on what this filing targets: the unresolvable-form check, the
        # classification verdict, and the denial's own text all read THIS value.
        #
        # ⚠ THIS LINE IS THE FIX FOR A MEASURED BYPASS, and the bypass was introduced by
        # the very change that made classification target-based. For one review cycle the
        # unresolvable branch below read `flag_value(argv, "--repo", "-R")` while the
        # verdict read `lib.target_repo(argv)` — two parsers in one module, disagreeing
        # about what a target is, which is the split-brain this mission exists to remove.
        # `flag_value` reads only the separated and long-`=` spellings, so the three
        # ATTACHED short forms slipped past it. MEASURED end to end, both ledger states:
        #
        #     gh issue create -R$VAR    --title T --body "…"          -> DENY  (no evidence)
        #     gh issue create -R$VAR    --title T --body "<footer>"   -> ALLOW  ← the bypass
        #     gh issue create -R=$VAR   --title T --body "<footer>"   -> ALLOW
        #     gh issue create -R`cat r` --title T --body "<footer>"   -> ALLOW
        #
        # The cycle-1 claim that the divergence "fails in the enforcing direction" was
        # measured over the no-evidence case ONLY. A safety property established over a
        # subset of its inputs is not a safety property — and the subset that was skipped
        # is the one an author actually reaches, because an author who is filing has
        # normally done the runbook. Assert both states or assert nothing.
        target = lib.target_repo(argv)

        # UNRESOLVABLE FIRST — and "first" is load-bearing, not stylistic. This branch
        # short-circuits BEFORE the ledger is read, so a dynamic target denies regardless
        # of how much evidence the session has banked. It does not ask WHICH repository is
        # targeted; it asks whether the extracted value is a literal at all, so that a
        # substitution can be refused BY NAME rather than guessed at.
        #
        # `target is None` — no target flag, an empty value, or the flag as the last token
        # — falls through to the abstain path below, exactly as `--repo ""` and `--repo=`
        # already did. That is the same "no target named" case documented in
        # `lib.target_repo`, and it is deliberately unguarded (qa#291 item 4). MEASURED
        # (gh 2.98.0): `gh issue list --repo` with the flag last exits 1 with "flag needs
        # an argument: --repo" — the command never runs, so nothing is filed by the form
        # this branch no longer names. It denied here before as FORM_NO_VALUE; keeping a
        # second target parser alive to preserve that message is the trade this fix
        # refuses to make.
        if target is not None:
            form = dynamic_form(target)
            if form is not None:
                deny(build_unresolvable_repo_denial(form))

        # THE DECISION INPUT IS THE TARGET, not the tokens. The scoping comment this
        # replaced said only tokens of the filing's own segment counted; that is still
        # true and now narrower still — one value in that segment decides, and it is the
        # value `gh` itself would resolve.
        #
        # `targets_upstream` re-enters `lib.target_repo` rather than being handed `target`
        # above. That costs one call and cannot diverge — it is the SAME extractor — and
        # it keeps the delegation: passing the value in would make the guard carry its own
        # two-line notion of "not ours", which is the second definition this mission
        # exists to delete.
        if not targets_upstream(argv):
            continue

        body, denial = resolve_body(argv, cwd)
        if denial is not None:
            deny(denial)

        led = read_ledger(session_id)
        missing_register = not led.get("register")
        missing_queue = not led.get("queue")
        missing_footer = FOOTER_MARKER not in (body or "")
        if missing_register or missing_queue or missing_footer:
            deny(
                build_denial(
                    missing_register, missing_queue, missing_footer,
                    bool(led.get("intent")),
                    footer_from_file=flag_value(argv, "--body-file", "-F")[2],
                    target=target,
                )
            )
    allow()


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise TypeError("the tool payload is not a JSON object")
        tool_input = payload.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            raise TypeError("tool_input is not a JSON object")
    except Exception as exc:  # noqa: BLE001 — a payload we cannot read DENIES (qa #277)
        deny(build_parse_failure_denial(type(exc).__name__))

    session_id = str(payload.get("session_id") or "")
    tool = payload.get("tool_name") or ""
    cwd = str(payload.get("cwd") or "")

    if tool == "Bash":
        evaluate_bash(session_id, str(tool_input.get("command") or ""), cwd)

    path = str(tool_input.get("file_path") or "")
    if tool in {"Read", "Grep", "Glob"} and REGISTER in path:
        mark(session_id, "register")
        allow()
    if REGISTER in path:
        mark(session_id, "register")
    if "docs/drafts/" in path and not path.endswith("README.md"):
        context(DRAFT_CONTEXT)
    allow()


def run() -> None:
    """NFR-001: an unhandled exception ANYWHERE denies.

    ⚠ Re-raising `SystemExit` is load-bearing and runs the OPPOSITE way from the rest of
    this wrapper. `allow()`, `deny()` and `context()` all end in `sys.exit(0)`, which
    raises `SystemExit` — a `BaseException`. Catch it without re-raising and every allow
    becomes a deny: not "fail-closed" but a broken gate that gets switched off within a
    day. MEASURED as mutant M5: deleting the re-raise took the fixes' own test module from
    85 passed to 79 failed, 6 passed.
    """
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 — deliberate: nothing escapes to an allow
        deny(build_parse_failure_denial(type(exc).__name__))


if __name__ == "__main__":
    run()
