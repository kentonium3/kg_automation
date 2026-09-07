#!/usr/bin/env python3
"""FR-008 — which hook scripts exist, and what, if anything, references them?

This repository shipped versioned hook scripts for months while the wiring that invoked
them lived in one operator home directory. Every other machine therefore had the scripts,
had no gate, and said so nowhere. That silence is what this module removes: it makes
non-enforcement *visible*, so the state is reported rather than assumed.

It answers exactly one question, and refuses a bigger one.

WHAT IT CANNOT TELL YOU
-----------------------
This reads settings files. There is no documented runtime way to list the hooks a live
session has active, so it cannot tell you a wired hook fired -- only that something
references the script. Project hooks additionally require each person cloning this
repository to accept the workspace-trust dialog before they run at all, so a fresh clone
is wired but not yet enforcing. The only end-to-end proof is a live session, and that is
an operator step rather than a check.

That paragraph is repeated in the report footer on purpose. A reader who takes "all
required wiring present" for "the gate is running" has been misled by a report that
checked something narrower, which is the defect class this mission exists to remove
(NFR-002, C-004).

SCOPE, AND WHY IT EXITS ZERO SO OFTEN
-------------------------------------
An always-red detector gets ignored, and an ignored detector is the same as no detector.
So the exit status is reserved for the things this repository has decided must hold:

* every pair in ``REQUIRED_WIRING`` is present in an in-repo settings file;
* every in-repo settings file that exists parses;
* every script referenced by an in-repo settings file exists on disk;
* the wiring file is tracked by git;
* no in-repo hook command carries the fail-open idiom or a machine-local absolute path.

Everything else is informational, including ``upstream_filing_guard.py`` being wired only
in operator-local settings. That is a known, named gap -- WP08 wired the mission-lifecycle
gate and deliberately did not expand scope -- and naming it beats failing on it.

C-002: this only ever READS. ``--include-user`` reads the operator's home settings and
must never write there, or anywhere else.

USAGE
-----
    python3 scripts/hooks/check_wiring.py
    python3 scripts/hooks/check_wiring.py --include-user
    python3 scripts/hooks/check_wiring.py --settings /path/to/settings.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: The ``(script, event)`` pairs that must be wired IN THIS REPOSITORY. A missing pair is
#: the one thing here that is unambiguously broken rather than merely worth knowing.
#:
#: ⚠ ``PostToolUse`` was ADDED after the post-merge review, and its absence was a livelock.
#: Markers are recorded on ``PostToolUse`` only, because intent is not execution (FR-010b).
#: With it unwired, an agent could run the sweep correctly, earn NOTHING, and be refused
#: forever by a denial telling it to run the step it had just run.
#:
#: This detector reported GREEN over that, because its required set carried the same gap as
#: the wiring it was checking. A detector that shares a blind spot with its subject is worth
#: less than no detector, because it converts an absence into a reassurance.
REQUIRED_WIRING: tuple[tuple[str, str], ...] = (
    ("mission_lifecycle_gate.py", "PreToolUse"),
    ("mission_lifecycle_gate.py", "PostToolUse"),
    ("mission_lifecycle_gate.py", "PostToolUseFailure"),
)

#: The repository-relative settings files read when ``--settings`` is not given.
DEFAULT_SETTINGS: tuple[str, ...] = (".claude/settings.json", ".claude/settings.local.json")

#: The one whose tracked-ness is asserted. ``.claude/`` sits inside a spec-kitty
#: auto-managed ignore block that re-adds itself, and a ``!`` negation is inert because git
#: cannot re-include a file under an excluded directory -- so this file is only ever in the
#: index because somebody ran ``git add -f``, and only stays there while nobody undoes it.
WIRING_FILE = ".claude/settings.json"

#: The user-level settings file, resolved the way Claude Code resolves it: ``CLAUDE_CONFIG_DIR``
#: when that is set, otherwise ``~/.claude``. Measured on this machine — a work-account session
#: runs with ``CLAUDE_CONFIG_DIR=~/.claude-work``, so a detector hardcoding ``~/.claude`` reads a
#: file the running session does not, and reports ``upstream_filing_guard.py`` as referenced by
#: nothing while it is in fact wired. Reporting the wrong file is worse than reporting none.
USER_SETTINGS_DEFAULT = "~/.claude/settings.json"


def _user_settings_path() -> tuple[Path, str]:
    """``(path, label)`` for the user-level settings file. Reads env only; writes nothing."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        path = Path(config_dir).expanduser() / "settings.json"
        return path, f"$CLAUDE_CONFIG_DIR/settings.json ({path})"
    path = Path(USER_SETTINGS_DEFAULT).expanduser()
    return path, USER_SETTINGS_DEFAULT

FAIL_OPEN_IDIOM = "|| exit 0"
MACHINE_PATH_PREFIXES = ("/Users/", "/home/")

#: Path-shaped tokens ending in ``.py``. Deliberately loose: a token this misses is a
#: reference this cannot check, and the report says which tokens it could not resolve
#: rather than implying it resolved them all.
PY_TOKEN_RE = re.compile(r"[^\s\"'|;&()<>]*\.py\b")

PROJECT_DIR_TOKENS = ("${CLAUDE_PROJECT_DIR}", "$CLAUDE_PROJECT_DIR")

DISCLAIMER = (
    "This report reads settings files. There is no documented runtime way to list the\n"
    "  hooks a live session has active, so it cannot tell you a wired hook fired -- only\n"
    "  that something references the script. Project hooks also require each person\n"
    "  cloning this repository to accept the workspace-trust dialog before they run at\n"
    "  all, so a fresh clone is wired but not yet enforcing."
)

KNOWN_GAPS = (
    "upstream_filing_guard.py is wired only in operator-local settings"
    " (~/.claude-work/settings.json), so it is not clone-portable. WP08 wired the"
    " mission-lifecycle gate and left this one alone on purpose; run with --include-user"
    " to see the operator-local references from this machine.",
)


@dataclass(frozen=True)
class Entry:
    """One leaf hook command, with enough provenance to report it."""

    event: str
    matcher: str | None
    command: str
    source: str
    in_repo: bool


@dataclass(frozen=True)
class SettingsFile:
    path: Path
    label: str
    status: str  # "ok" | "absent" | "unparseable"
    detail: str
    entries: tuple[Entry, ...]
    in_repo: bool


def _resolve_repo_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _read_settings(path: Path, *, label: str, in_repo: bool) -> SettingsFile:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return SettingsFile(path, label, "absent", "no such file", (), in_repo)
    except OSError as exc:
        return SettingsFile(path, label, "unparseable", type(exc).__name__, (), in_repo)
    try:
        doc = json.loads(text)
    except ValueError as exc:
        return SettingsFile(path, label, "unparseable", type(exc).__name__, (), in_repo)
    if not isinstance(doc, dict):
        return SettingsFile(path, label, "unparseable", "top level is not an object", (), in_repo)

    entries: list[Entry] = []
    hooks = doc.get("hooks")
    if isinstance(hooks, dict):
        for event, blocks in hooks.items():
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                matcher = block.get("matcher")
                for entry in block.get("hooks") or []:
                    if not isinstance(entry, dict):
                        continue
                    command = entry.get("command")
                    if isinstance(command, str):
                        entries.append(
                            Entry(
                                event=str(event),
                                matcher=matcher if isinstance(matcher, str) else None,
                                command=command,
                                source=label,
                                in_repo=in_repo,
                            )
                        )
    return SettingsFile(path, label, "ok", f"{len(entries)} hook command(s)", tuple(entries), in_repo)


def _hook_scripts(repo_root: Path) -> list[str]:
    """Top-level ``scripts/hooks/*.py``, excluding private modules and this file."""
    directory = repo_root / "scripts" / "hooks"
    if not directory.is_dir():
        return []
    return sorted(
        p.name
        for p in directory.glob("*.py")
        if not p.name.startswith("_") and p.name != Path(__file__).name
    )


def _resolve_token(token: str, repo_root: Path) -> Path | None:
    """Resolve a path-shaped command token, or ``None`` when it still carries a variable
    this cannot expand. Unresolved is reported as unresolved, never as present."""
    resolved = token
    for marker in PROJECT_DIR_TOKENS:
        resolved = resolved.replace(marker, str(repo_root))
    if "$" in resolved:
        return None
    candidate = Path(resolved).expanduser()
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    return candidate


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args], capture_output=True, text=True
    )


def _tracking_status(repo_root: Path) -> tuple[str, str]:
    """``(status, detail)`` for the wiring file. ``UNKNOWN`` when git cannot answer -- an
    exported tarball is a legitimate state and must not be reported as a defect."""
    if _git(repo_root, "rev-parse", "--git-dir").returncode != 0:
        return "UNKNOWN", "not a git working tree, so tracking cannot be determined"
    if _git(repo_root, "ls-files", "--error-unmatch", WIRING_FILE).returncode != 0:
        return (
            "UNTRACKED",
            f"{WIRING_FILE} is not in the index. It is covered by the .claude/ ignore rule,"
            " so it only travels when force-added: git add -f " + WIRING_FILE,
        )
    # ⚠ `--no-index` is load-bearing. Without it `git check-ignore` NEVER reports a tracked
    # file, so the first branch below was unreachable and this function could only ever print
    # "no ignore rule matches it" — which is false here. A rule DOES match: `.gitignore`'s
    # spec-kitty auto-managed block, which re-adds itself, and which is exactly why this file
    # is only in the index because somebody ran `git add -f`.
    #
    # An operator who reads "no ignore rule matches it" and concludes the ignore hazard is gone
    # is one `git rm --cached` away from losing the wiring silently. Reporting the rule that
    # matches is the interesting fact, not a footnote.
    ignored = _git(repo_root, "check-ignore", "-v", "--no-index", WIRING_FILE)
    if ignored.returncode == 0:
        return "TRACKED", (
            f"tracked by `git add -f`, and STILL matched by {ignored.stdout.strip()} — "
            "untrack it and it disappears from every clone"
        )
    return "TRACKED", "tracked, and no ignore rule matches it"


def _build_report(repo_root: Path, files: list[SettingsFile]) -> tuple[str, list[str]]:
    problems: list[str] = []
    lines: list[str] = []
    add = lines.append

    add("mission-lifecycle gate -- hook wiring report")
    add(f"repository: {repo_root}")
    add("")

    # -- 3. settings files: present / absent / unparseable ---------------------------------
    add("SETTINGS FILES")
    for f in files:
        scope = "in-repo" if f.in_repo else "operator-local, informational"
        add(f"  [{f.status.upper():<12}] {f.label}  ({scope}; {f.detail})")
        if f.status == "unparseable" and f.in_repo:
            problems.append(
                f"{f.label} does not parse ({f.detail}). spec-kitty's registrar renames an"
                " invalid settings file aside as settings.json.invalid.<hex> and builds a"
                " fresh one, so the gate disappears without anything announcing it."
            )
    add("")

    entries = [e for f in files for e in f.entries]

    # -- 1 & 2. every hook script, and what references it ----------------------------------
    add("HOOK SCRIPTS AND THEIR REFERENCES")
    scripts = _hook_scripts(repo_root)
    if not scripts:
        add(f"  (no top-level scripts/hooks/*.py under {repo_root})")
    for name in scripts:
        refs = [e for e in entries if name in e.command]
        if not refs:
            add(f"  {name}: UNWIRED -- nothing in the settings files read references it")
            continue
        for ref in refs:
            where = "in-repo" if ref.in_repo else "operator-local"
            matcher = ref.matcher or "(no matcher)"
            add(f"  {name}: {ref.event} [{matcher}] <- {ref.source} ({where})")
    add("")

    # -- required wiring -------------------------------------------------------------------
    add("REQUIRED WIRING (this repository)")
    for script, event in REQUIRED_WIRING:
        matched = [
            e for e in entries if e.in_repo and e.event == event and script in e.command
        ]
        if matched:
            add(f"  [OK      ] {script} @ {event} <- {matched[0].source}")
        else:
            add(f"  [UNWIRED ] {script} @ {event}")
            problems.append(
                f"required wiring is UNWIRED: {script} @ {event}. Nothing in this"
                " repository invokes that checkpoint, so it does not run for anyone who"
                " clones it."
            )
    add("")

    # -- 4. referenced script paths exist --------------------------------------------------
    add("REFERENCED SCRIPT PATHS")
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        for token in PY_TOKEN_RE.findall(entry.command):
            key = (entry.source, token)
            if key in seen:
                continue
            seen.add(key)
            target = _resolve_token(token, repo_root)
            if target is None:
                add(f"  [UNRESOLVED] {token}  ({entry.source}) -- carries a variable this cannot expand")
                continue
            if target.exists():
                add(f"  [PRESENT   ] {token}  ({entry.source})")
                continue
            add(f"  [MISSING   ] {token}  ({entry.source}) -- resolved to {target}")
            if entry.in_repo:
                problems.append(
                    f"{entry.source} references {token} on {entry.event}, and it is not"
                    f" there ({target}). That is a live fail-closed condition, not a pass:"
                    " every gated call gets the canned denial until the file is restored."
                )
    if not seen:
        add("  (no .py references found in any command string)")
    add("")

    # -- 5. the wiring file is tracked -----------------------------------------------------
    add("WIRING FILE TRACKING")
    status, detail = _tracking_status(repo_root)
    add(f"  [{status}] {WIRING_FILE} -- {detail}")
    if status == "UNTRACKED":
        problems.append(f"{WIRING_FILE} is UNTRACKED. {detail}")
    add("")

    # -- 6. command-string hazards ---------------------------------------------------------
    add("COMMAND-STRING HAZARDS")
    flagged = False
    for entry in entries:
        hazards: list[str] = []
        if FAIL_OPEN_IDIOM in entry.command:
            hazards.append(
                f"carries {FAIL_OPEN_IDIOM!r}, which turns a missing or crashed script into"
                " an ALLOW"
            )
        for prefix in MACHINE_PATH_PREFIXES:
            if prefix in entry.command:
                hazards.append(f"carries the machine-local path prefix {prefix!r}")
        for hazard in hazards:
            flagged = True
            scope = "in-repo" if entry.in_repo else "operator-local, informational"
            add(f"  [FLAG] {entry.source} {entry.event}: {hazard}  ({scope})")
            if entry.in_repo:
                problems.append(f"{entry.source} {entry.event} {hazard}.")
    if not flagged:
        add("  none")
    add("")

    add("KNOWN GAPS")
    for gap in KNOWN_GAPS:
        add(f"  - {gap}")
    add("")

    add("WHAT THIS REPORT CANNOT TELL YOU")
    add("  " + DISCLAIMER)
    add("")

    if problems:
        add(f"RESULT: {len(problems)} problem(s)")
        for problem in problems:
            add(f"  x {problem}")
    else:
        add("RESULT: every required pair is wired and every check above passed.")
    return "\n".join(lines) + "\n", problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_wiring.py",
        description="Report which hook scripts exist and what references them (FR-008).",
    )
    parser.add_argument(
        "--settings",
        action="append",
        default=None,
        metavar="PATH",
        help="Read this settings file instead of the repository defaults. Repeatable.",
    )
    parser.add_argument(
        "--include-user",
        action="store_true",
        help="Additionally READ the user-level settings file — $CLAUDE_CONFIG_DIR/settings.json"
        f" when that variable is set, otherwise {USER_SETTINGS_DEFAULT}. Off by default so the"
        " report does not depend on one developer's home directory. Read-only, always (C-002).",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        metavar="PATH",
        help="Treat PATH as the repository root for script enumeration, git checks and"
        " $CLAUDE_PROJECT_DIR expansion. Defaults to the repository containing this file.",
    )
    args = parser.parse_args(argv)

    repo_root = _resolve_repo_root(args.repo_root)

    files: list[SettingsFile] = []
    if args.settings:
        for raw in args.settings:
            path = Path(raw).expanduser().resolve()
            try:
                label = str(path.relative_to(repo_root))
            except ValueError:
                label = str(path)
            files.append(_read_settings(path, label=label, in_repo=True))
    else:
        for rel in DEFAULT_SETTINGS:
            files.append(_read_settings(repo_root / rel, label=rel, in_repo=True))

    if args.include_user:
        user_path, user_label = _user_settings_path()
        files.append(_read_settings(user_path, label=user_label, in_repo=False))

    report, problems = _build_report(repo_root, files)
    sys.stdout.write(report)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
