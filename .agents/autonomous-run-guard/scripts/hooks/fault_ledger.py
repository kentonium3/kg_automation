#!/usr/bin/env python3
"""The fault ledger: one append-only JSONL line per observed spec-kitty fault.

⚠ **This module records. It does not enforce anything.** CP-DURING, its only writer, fires
on ``PostToolUseFailure``, which cannot block — the tool has already run. Enforcement of
the D-3 obligation is CP-AFTER (WP06), which reads this file and refuses a merge whose
faults carry no reconciliation line.

WHAT A RECORD PROVES, AND WHAT IT DOES NOT
------------------------------------------
A line proves that a ``spec-kitty`` command was **observed failing** by a live hook. It
does not prove that every fault was recorded: a fault the harness never surfaced leaves no
line, and an empty ledger is indistinguishable from a recording path that never fired.
"No faults occurred" must therefore be asserted, never inferred from an empty file.

⚠ **The loss asymmetry, and it runs the opposite way to the session ledger.** A lost
*marker* denies, which is safe. A lost *fault record* allows, which is not. That is why
this file is append-only JSONL written one ``os.write`` at a time, while the session ledger
is a rewritten object — and why a write failure here is reported to the agent (see
:func:`record_fault`'s return value) rather than swallowed.

STORAGE
-------
``<hooks-root>/faults/<safe_session_id>.jsonl``, where the hooks root is
``_hook_lib.hooks_root()`` — ``<git-common-dir>/spec-kitty-hooks``, overridable through
``SPEC_KITTY_HOOKS_ROOT``. Living inside ``.git/`` means it is never tracked, needs no
``.gitignore`` entry, and survives temp reaping.

**Keyed on ``session_id``**, exactly as the existing session ledger is. Cross-worktree
fault visibility is a *deliberately unbuilt* capability (operator scope reduction,
2026-08-25): a fault recorded in a WP worktree under one session is not visible to a merge
check running under a different session. That limit is real; it is written here rather than
designed around, because the machinery to close it was the complexity that sank WP03.

APPEND PROTOCOL
---------------
Exactly one ``os.write`` per record, mode ``0o600``, every record under 4096 bytes. That is
what makes concurrent ``O_APPEND`` writes interleave without splitting on a local
filesystem. The file is never rewritten and never deleted.

REDACTION (NFR-004)
-------------------
Nothing from ``tool_input`` is written verbatim. :func:`redact_argv` keeps shape-safe bare
tokens and bare ``--flag`` names and replaces every flag *value* with ``<redacted>`` except
a small allowlist. ``cwd``, ``transcript_path`` and the raw ``error`` body — all of which
carry absolute filesystem paths — are not recorded at all.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from hooks import _hook_lib as lib

#: Flags whose VALUE is safe to keep: they name a mission, not a credential
#: (``contracts/fault-ledger.md`` §4). Every other flag value becomes ``<redacted>``.
VALUE_ALLOWLIST = frozenset({"--mission", "--handle", "--topology"})
#: ⚠ ``--json`` was here and was REMOVED. It takes no value, so its only effect was to make
#: the following POSITIONAL be treated as an allowlisted flag value — `spec-kitty merge
#: --json s3cr3t` kept `s3cr3t`. Not a live leak beyond the documented bare-positional
#: pass-through, but a value-allowlist entry for a valueless flag misleads the next reader
#: about which tokens survive.

#: A token is kept only if it matches this. An ALLOWLIST, because a denylist of "token",
#: "secret" and "password" is defeated by the next credential that is named none of them.
#: The length cap is load-bearing: ``ghp_`` + 36 characters exceeds it, and so does every
#: other credential shape long enough to be worth stealing.
SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,23}")

#: The one program whose failures are this ledger's business. Matched on the tokenised
#: argv's basename via ``lib.program_of`` — never as a substring, so ``echo "spec-kitty
#: merge"`` names the verb and invokes nothing.
PROGRAM = "spec-kitty"

REDACTED = "<redacted>"
MAX_COMMAND_CHARS = 200
_EXIT_CODE = re.compile(r"^Exit code (\d+)")


def _value_of(flag: str, value: str) -> str:
    """A flag's value survives only if the flag is allowlisted AND the value is shape-safe.

    Both conditions, because either alone leaks: ``--api-key s3cr3t`` is indistinguishable
    from a mission handle by shape, and an allowlisted flag is no guarantee about what was
    passed to it.
    """
    return value if flag in VALUE_ALLOWLIST and SAFE_TOKEN.fullmatch(value) else REDACTED


def redact_argv(argv: Sequence[str]) -> str:
    """Render ``argv`` as a command *shape*. Never a copy of what the user typed.

    ⚠ A token following a bare flag is treated as that flag's **value**, so a positional
    after a boolean flag (``spec-kitty merge --force demo``) is redacted too. Over-redaction
    costs ledger detail; the other direction costs a credential. Only the safe error is
    available here, because nothing in this process knows which flags take values.
    """
    out: list[str] = []
    pending: str | None = None
    for token in argv:
        if token.startswith("-"):
            name, sep, value = token.partition("=")
            safe_name = name if SAFE_TOKEN.fullmatch(name.lstrip("-")) else "--flag"
            if sep:
                out.append(f"{safe_name}={_value_of(safe_name, value)}")
                pending = None
            else:
                out.append(safe_name)
                pending = safe_name
            continue
        if pending is not None:
            out.append(_value_of(pending, token))
            pending = None
            continue
        out.append(token if SAFE_TOKEN.fullmatch(token) else REDACTED)
    return " ".join(out)[:MAX_COMMAND_CHARS]


def exit_code_of(error: str | None) -> int | None:
    """The exit code from ``error``'s first line, or ``None``.

    ⚠ ``Exit code N`` is an undocumented **presentation string, not an API** (WP01 spike
    §4). Recording is never conditional on parsing it: if the prefix is reworded upstream
    the ledger loses detail and the trigger — which keys on the *event* — keeps working.
    """
    match = _EXIT_CODE.match(error or "")
    return int(match.group(1)) if match else None


def fault_path(session_id: str, *, root: str | os.PathLike[str] | None = None,
               cwd: str | None = None) -> Path:
    """The ledger path for one session. ``session_id`` is sanitised: it arrives from
    outside the process, so a ``../`` in one would otherwise escape the directory."""
    base = Path(root) if root is not None else lib.hooks_root(cwd)
    return base / lib.FAULTS_DIR_NAME / f"{lib.safe_component(session_id)}.jsonl"


def append_record(path: Path, record: Mapping[str, Any]) -> bool:
    """Append one record. Returns whether it landed — the caller must not claim it did."""
    line = (json.dumps(record, separators=(",", ":")) + "\n").encode()
    for attempt in range(2):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line)  # exactly one write; no buffered writer, no partial flush
            finally:
                os.close(fd)
            return True
        except OSError:
            if attempt:
                return False
    return False


def record_fault(payload: lib.Payload, segments: Sequence[Sequence[str]], *,
                 root: str | os.PathLike[str] | None = None) -> bool:
    """Record one observed fault. Returns ``False`` when the write did not land."""
    argv = next((a for a in segments if lib.program_of(a) == PROGRAM), ())
    record = {
        "kind": "fault",
        "at": datetime.now(timezone.utc).isoformat(),
        # ⚠ SANITISED and BOUNDED, not raw. The filename was already safe, but the RECORD
        # wrote payload.session_id verbatim — and parse_payload only checks it is a
        # non-empty string. A hostile or malformed payload could therefore put a secret,
        # or an arbitrarily long blob, straight into the ledger through the one field the
        # redaction pass did not touch. It also broke the contract's under-4096-bytes
        # guarantee, which assumed every field except the command was fixed-size.
        "session_id": lib.safe_component(payload.session_id)[:128],
        "command": redact_argv(argv),
        "exit_code": exit_code_of(payload.error),
        "interrupted": bool(payload.is_interrupt),
    }
    # ⚠ `fault_path` resolves the hooks root, which raises `HooksRootError` — a `HookError`,
    # NOT an `OSError`. Called as a bare argument it escaped `append_record`'s `except OSError`
    # entirely, escaped this function, and was absorbed by the dispatcher's blanket handler
    # into a silent allow: no ledger line, no SOP, no NOT-recorded warning. Reachable from any
    # failing `spec-kitty` call whose cwd is outside a worktree (a scratchpad, $HOME), or when
    # `git rev-parse` is missing or times out.
    #
    # It survived 18 mutants because EVERY test supplied `SPEC_KITTY_HOOKS_ROOT`, so the
    # production root-resolution path had no coverage at all — the test seam hid the one
    # failure mode this module says it cannot tolerate.
    try:
        path = fault_path(payload.session_id, root=root, cwd=payload.cwd)
    except lib.HookError:
        return False
    return append_record(path, record)


def read_records(session_id: str, *, root: str | os.PathLike[str] | None = None,
                 cwd: str | None = None) -> list[dict[str, Any]]:
    """Every record for a session, in append order. WP06's merge check reads through here
    so the path and sanitisation logic exist in exactly one place.

    ⚠ An unparseable line is **kept** as ``{"kind": "unreadable"}`` rather than skipped. A
    record this version cannot interpret may be the one that matters, and silently dropping
    it would turn a corrupt ledger into a clean one.
    """
    path = fault_path(session_id, root=root, cwd=cwd)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            parsed = None
        records.append(parsed if isinstance(parsed, dict) else {"kind": "unreadable"})
    return records
