# Handoff — autonomous-run guard intake

**Written 2026-09-06 by a work-hat session in `spec-kitty-qa`. Everything below is for a
PERSONAL-hat session in `kg-automation`.** The work-hat session deliberately stopped short of
committing here, because committing to a personal repo from the work account crosses the boundary
`~/.claude/CLAUDE.md` draws.

---

## Prompt — paste this to start

> The autonomous-run guard was removed from `spec-kitty-qa` (PR #417, merged 2026-09-06) and its
> files are sitting uncommitted in this repo on branch `chore/receive-autonomous-run-guard`, under
> `.agents/autonomous-run-guard/`. Read `docs/handoff/2026-09-06-autonomous-run-guard-intake.md`
> first, then help me land it — and expect the answer to be "keep less than arrived."

---

## State you will find

- **Branch:** `chore/receive-autonomous-run-guard`, cut from `main`.
- **Path:** `.agents/autonomous-run-guard/` — 36 files, **uncommitted**.
- **Contents:** 7 script modules, 7 test modules (869 collected tests), 6 documents, and
  `check-wiring-before.txt` (the wiring detector's output captured while the guard was still live —
  the tool that produces it is in this directory, so this is the only record of that state).
- **Provenance:** all 20 code and doc files verified byte-identical to `spec-kitty-qa@main` by
  sha256 before that repo deleted them. There is **no other copy** — the interim staging directory
  at `~/Documents/spec-kitty/autonomous-run-guard` was removed, and `spec-kitty-qa` squash-merged
  the deletion.

⚠ **The pre-commit secret scanner will refuse the commit.** It flags four **synthetic** test
fixtures — `ghp_notarealtokennotarealtokennotareal`, 36 literal `A`s, and `password=hunter2` — in
the test suite for the guard whose job is redacting secrets. Verified: no real credential is
present. `--no-verify` is justified here, or allowlist the paths.

---

## Read this before rebuilding any of it

**The filing guard did not prevent the incident it exists for.** Measured, recorded at
`spec-kitty-qa:docs/spec-kitty-issues.md:158`: in the 27-junk-issue incident the guard was asked
and **denied every one of the identical commands**. The filing happened anyway from a
`subprocess.run` inside a Python heredoc — and a `PreToolUse` hook only ever sees Bash tool calls,
never subprocesses those calls spawn. No transcript recorded any of it.

So this is roughly 129 KB of mechanism and 539 tests guarding a path it structurally cannot
observe. Your own assessment on 2026-09-06: over-optimised for a real but rare occurrence.

**The replacement you named is cheaper and strictly stronger:**

1. **An instruction** — never file upstream autonomously; findings accumulate for review.
2. **A capability control** — autonomous runs carry no upstream credential. With no credential, no
   `subprocess.run`, no heredoc and no hook-invisible path can file. **This closes the case the
   guard missed, not merely the case it caught.**

Rebuild only what those two leave uncovered. On the evidence that may be nothing, and the honest
outcome of this intake may be an archive commit plus a short instruction, with the mechanism never
wired again.

---

## Of the four goals that started this, only two were ever mechanised

You asked for a repeating pre-mission routine. Measured against what was built:

| Goal | What exists |
| :--- | :--- |
| Check upstream for a new build; check known issues | `checkpoints/before.py` — a real `PreToolUse` deny, but it gates that the sweep was **marked**, not that it happened |
| New fault → **stop**, capture, diagnose, workaround | `checkpoints/during.py` + `fault_ledger.py` — **cannot stop anything**; `PostToolUseFailure` fires after the tool ran |
| Gather findings for review at end of run | **never built** — the merge checkpoint was descoped |
| Report issues, update local tracking | **never built** — same |
| Codex adversarial review post-plan and post-merge | **never a hook** — it is `CLAUDE.md` prose, and it works |
| Don't stop between turns during autonomous runs | **abandoned** (qa#278, still open) |

Two of six, and one of those two cannot do what you asked. The three that most need automation —
end-of-run gathering, reporting, and not-stopping — are the ones that were never built or were
abandoned. `_hook_lib.py` is 85 KB of the 154 KB and carries 358 of the tests: **the shared library
is bigger than everything it holds up.**

---

## If you keep the "don't stop between turns" goal

It is the one goal nothing here addresses, and it is why the whole thing started. Two facts:

- The only measured foundation is `docs/design/stop-hook-contract-measured.md` in this directory,
  and it was measured on **Claude Code 2.1.231 / macOS**.
- You want autonomous runs on **office4**, which is **Linux Mint**. Those measurements do not
  transfer, and the file's own claim is "the durable home so that probe is never repeated."

So the real blocker under "software factory equivalent on office4" is that nobody has measured the
`Stop` contract on Linux. Small, separable, and worth doing before building anything on it.

---

## Suggested first moves

1. Commit the intake as an archive (`--no-verify`, noting why), so it stops being uncommitted work
   in a clean repo. That alone makes it durable — this repo has a remote; nothing else holding
   these files did.
2. Decide **whether to rebuild at all**, using the two-item replacement above as the baseline.
3. If you rebuild, start from the goals table rather than the code — the code optimises the two
   cheapest goals.
4. If you do not, keep `check-wiring-before.txt` and the six documents as the record and drop the
   mechanism.

## Related

- `spec-kitty/spec-kitty-qa#417` — the removal PR
- `spec-kitty/spec-kitty-qa#416` — the full specification, since the mission was discarded
- `spec-kitty/spec-kitty-qa#370` — the parent issue; its doctrine half remains open
- `spec-kitty/spec-kitty-qa#278` — the abandoned turn-yield gate, still open
