# Autonomous-run guard — received from spec-kitty-qa

**Received 2026-09-06** from `spec-kitty-qa` @ `chore/retire-autonomous-run-guard`, where it was
removed. This is its home now; there is no copy in that repository. Tracking issue: `spec-kitty/spec-kitty-qa#370`.

⚠ **Staging is not a commitment to rebuild.** See "The open question" below.

## What is here

| Path | Contents |
| :--- | :--- |
| `scripts/hooks/` | 7 modules — the mission-lifecycle gate, its two checkpoints, the fault ledger, the wiring diagnostic, the shared library, and the upstream filing guard |
| `tests/hooks/` | 7 modules, 869 collected tests |
| `docs/` | 6 documents: the autonomous-run protocol, hook fail directions, the measured `Stop` contract, the mission-brief template, and the two design docs written about the guard itself |
| `check-wiring-before.txt` | `check_wiring.py --include-user` output captured while the guard was still live and wired — the only record of the pre-removal wiring state, since the tool that produces it is in this directory rather than in the repo |

All 14 code and test files, plus all 6 documents, verified byte-identical to `spec-kitty-qa@main`
by sha256 on arrival.

## Why it left spec-kitty-qa

It is one operator's local discipline and no contributor runs it: the filing guard is wired in
`~/.claude-work/settings.json` by absolute path, and the gate in that repo's own
`.claude/settings.json`. It has no coupling to the QA pipeline — verified adversarially: no
dynamic import, no entry point, no CI reference, no `.kittify/` reference — yet it cost that
repository **869 of 3,496 collected tests** on every run.

More decisively: **it is superseded.** Further QA Pipeline development happens in the software
factory, which brings its own run protocol and its own turn-end handling. The `Stop` work and the
autonomous-run protocol have no successor to serve.

## The open question — read before rebuilding any of this

**The filing guard did not prevent the incident it exists for.** Measured, recorded at
`docs/spec-kitty-issues.md:158` in the origin repo: in the 27-junk-issue incident the guard was
asked and **denied every one of the identical commands**. The filing then happened from a
`subprocess.run` inside a Python heredoc — and a `PreToolUse` hook only ever sees Bash tool calls,
never subprocesses those calls spawn. No transcript recorded any of it.

So this is ~129 KB of mechanism and 539 tests for a guard whose canonical failure case it
structurally could not observe. The operator's assessment (2026-09-06) is that it was
over-optimised for a real but rare occurrence.

**The likely replacement is not a guard at all**, and it is cheaper and stronger:

1. **An instruction** — never file upstream autonomously; findings accumulate for review.
2. **A capability control** — autonomous runs carry no upstream credential. With no credential, no
   `subprocess.run`, no heredoc, and no hook-invisible path can file. This closes the case the
   guard missed, not merely the case it caught.

Rebuild only what those two leave uncovered. On the evidence, that may be nothing.

## Durability

This is the durable copy. An interim staging directory at `~/Documents/spec-kitty/autonomous-run-guard`
was used to carry the material across and has been removed — it had no remote and served no purpose
once this landed.
