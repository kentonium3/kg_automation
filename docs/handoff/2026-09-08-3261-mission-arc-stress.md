---
title: 'Handoff: stress the 3.2.6.1 hotfix with a real mission arc'
doc_type: note
audience: agents_and_humans
status: active
last_updated: '2026-09-08'
---

# Handoff — stress the 3.2.6.1 hotfix with a real mission arc

**From:** work-hat session in `~/repos/spec-kitty-qa` (`kent@spec-kitty.ai`), 2026-09-08
**To:** personal-hat Claude in `~/repos/kg-automation` (`kent@intentional.biz`)
**Why you:** this repo has **124 `kitty-specs/` entries** against spec-kitty-qa's 21. Mission-state variety is the thing being tested, and you have far more of it.

---

## 1. Read this first: you are already running the build under test

There is one machine and one `uv tool` install, so **your CLI is already `3.2.6.1`** — I installed it this afternoon. You did not opt into this and nothing warned you.

`3.2.6.1` is an **unmerged, untagged hotfix** — `spec-kitty/spec-kitty#4051`, branch `hotfix/3.2.6.1`, cut from the `v3.2.6` tag (not `main`). Robert needs it released tomorrow morning for a two-day training in Darmstadt.

**Confirm the build from provenance, never from `--version`:**

```bash
cat ~/.local/share/uv/tools/spec-kitty-cli/uv-receipt.toml
cat ~/.local/share/uv/tools/spec-kitty-cli/lib/python3.13/site-packages/spec_kitty_cli-*.dist-info/direct_url.json
```

Expect the receipt to name `git = "https://github.com/spec-kitty/spec-kitty?rev=cb5ab3a6a9df…"` and `direct_url.json` to carry `vcs_info.commit_id = cb5ab3a6a9df593c073ab2d04c440e879882eb0e`. If it says anything else, **stop and tell Kent** — the install moved under one of us.

**Rollback, if the build turns out to be bad:**
```bash
UV_TOOL_BIN_DIR=/home/kgale/.local/bin uv tool install --force spec-kitty-cli==3.2.6
```

## 2. What the hotfix repaired

Four things, of which the first two matter to you:

- **`#4033`** — `specify` / `agent mission create` had no idempotency guard, created non-atomic orphan missions, and exited 0 on failure.
- **`#4035`** — `specify` left an orphaned mission scaffold when the protected-branch commit failed, and a retry then created a **second** mission folder.
- `#3988` — the Getting Started tutorial did not work as written.
- A `Priivacy-ai → spec-kitty` URL bump.

So the repair lives in **mission-creation atomicity and the commit path**. That is the surface to stress.

## 3. What I already covered — do not repeat it

On Linux, at `cb5ab3a6a`, in throwaway repos:

- Create in a repo with **no commits** → clean refusal, exit 1, zero debris across three attempts.
- Create on a **protected branch** (`main`) → refuses *before* attempting the commit, exit 1, zero debris; retry gives the identical refusal with **no orphan and no duplicate folder**.
- Create on a feature branch → succeeds (the refusal is not over-broad).
- Arc advanced `not_started → discovery → specify → plan`. **The state machine is sound.**
- Downstream: no four-component-version (`3.2.6.1`) parsing problem anywhere — packaging, migration planner, `charter context`, `doctor provenance|channel|skills`, `profiles list`. A 2,701-test suite is green under it.

**Known and already reported, so don't re-file it:** every `spec-kitty-composed-*` prompt from `spec-kitty next` is a 4-line stub (`#3909`). Within one mission, `discovery` produced a real 143-line prompt while `specify` and `plan` produced stubs. The discriminator is the generation path, not the step. The **slash-command** path (`/spec-kitty.specify`, 864 lines, stamped `3.2.6.1`) is intact — that is why this is not a training blocker. Full report: `spec-kitty/spec-kitty#4070`.

## 4. What I want you to stress — four gaps, in priority order

### G-1 — Idempotency after a *successful* create (highest value)

`#4033`'s own title says "no idempotency guard". I only tested a retry **after a refusal**, where there was nothing to collide with. **Untested: create the same mission slug when the first create succeeded.** Does it refuse, reuse, or make a second folder? This is the named symptom, on the path the repair touched, and nobody has exercised it.

### G-2 — The teardown half: close, discard, and the coordination worktree

My arc never *closed* a mission. The repair is about scaffold atomicity at create; teardown is its mirror and is known-fragile:

- `spec-kitty-qa`'s known-issues register records that `mission close --discard` **strands the slug** (the flatten deletes `topology` from `meta.json`, and the resume probe then rejects the scaffold as `malformed`, so no new mission can use that base slug) and leaves `meta.json` **modified-uncommitted**.
- `spec-kitty/spec-kitty#4041` — an archived terminal mission **keeps its coordination worktree** and no command reclaims it. I have this reproducing in spec-kitty-qa right now.
- Slack named a "coord-triple teardown bug (strands the worktree, eats the mission #, prints success)" as a headline P0.

**Take one throwaway mission all the way to close/discard and report what state survives.**

### ~~G-3 — Two missions at once~~ — WITHDRAWN, and the real gap it hid is now closed

**Withdrawn: I misread `#4035`.** "Double-mission" does not mean two concurrent missions. The issue is explicit: *"two `kitty-specs/<slug>-<ULID>` folders for **one intended mission** — one orphaned (untracked, invisible to all branch state), one real."* One mission, two folders, from a failed create followed by the recovery the error message advises.

*(For the record, since Kent asked: concurrent missions **are** supported. `branch_naming.py:22` — "two concurrent missions with identical human slugs produce distinct branch names" — and `workflow_executor.py:508` scope by `mission_slug` "so that concurrent missions…". There is no single-active-mission guard. It is simply not what `#4035` is about, so it is not worth your time here.)*

**What that misreading hid, and what I then found:** `#4035`'s repro step 1 is **`spec-kitty specify <slug>`**, a distinct top-level command — and I had only tested `agent mission create`. So the headline fix's own reported entry point was untested. **I have now run it verbatim and it passes:**

- Step 1, `spec-kitty specify task-list` on protected `main` → exit 1, clean refusal, **`kitty-specs/` absent**, `git status` clean, only `main` exists (no phantom coordination branch).
- Step 2, recovery via `agent mission create task-list --start-branch feat/task-list` → exit 0, success.
- **Exactly one `kitty-specs` entry** afterwards, and its `meta.json` coordination branch **exists** — which is `#4035`'s specific tell, since the orphan used to name a branch that was never created.

So do not spend time here. G-1, G-2 and G-4 are the open ones.

### G-4 — Worktree creation at `implement`

My arc stopped at `plan`, so lane worktrees were never created. If you can get a small mission as far as `implement`, that exercises worktree creation, which is where G-2's failures originate.

## 5. Hard limits — please respect these

- ⛔ **Do not run `spec-kitty doctor mission-state --fix`.** With 124 missions here you will likely see `SNAPSHOT_DRIFT` blockers and `upgrade --project` will *recommend* that command. `#3541`/`#3565` closed 2026-08-19 (before the `v3.2.6` tag), so it is *probably* safe on this build — but "probably" is not good enough against real mission history. `--audit` is read-only and fine. Always pass `< /dev/null`: non-TTY stdin makes the repair auto-decline.
- ⛔ **Do not change the CLI install.** Both hats share it. If you need to roll back, tell Kent first.
- ⛔ **Do not file anything in the `spec-kitty` org.** That is work-hat territory and this is your personal hat; a customer-voice report should not be rewritten into an employee-voice one, and vice versa. Report to me instead — §6.
- Prefer **throwaway repos** for destructive probes. Only use `kg-automation`'s real mission history for **read-only** audits, and say so when you do.
- `kg-automation` is in the named repo set for the **spec-kitty workflow-fault detour protocol**, so run the detour autonomously rather than stopping to ask — but capture the evidence, which is what the protocol is actually for.

## 6. How to report back

Write findings to:

```
~/repos/kg-automation/docs/handoff/2026-09-08-3261-findings.md
```

I will read that file and relay anything real into `spec-kitty/spec-kitty#4070` under the work hat, with Kent's copy approval. **You should not post it yourself.**

For each finding, give me:

1. **The exact command and its full output**, including the **exit code measured without a pipe** — `$?` after a pipeline is the last command's code, not the CLI's. I got this wrong today and nearly reported a phantom "silent exit-0".
2. **Build identity as a tuple** — line, SHA, how it got there. Not a version string. `3.2.6.1` alone identifies nothing.
3. **The debris state after any failure** — `kitty-specs/`, `git status --porcelain`, `git worktree list`, `git branch -a`. "It refused" and "it refused cleanly" are different findings.
4. **Whether it reproduces on a second attempt**, since idempotency is the thing under test.
5. **Whether you think it is caused by the hotfix or pre-existing.** If pre-existing, say what makes you think so. A hotfix blamed for an old bug costs more than silence.

**Please also report clean results.** "G-1 behaves correctly, here is the transcript" is directly useful — it is the difference between untested and tested, and tonight that distinction is what Robert is deciding on.

## 7. Timing

Robert wants the release out **tomorrow morning**. Anything you find in the next few hours can still change the tag. Anything later still matters — the report is explicitly a rolling one — but the release decision will have been made.

If you find something that looks release-blocking, say so at the top of your findings file in those words, so I do not have to infer urgency from the middle of a transcript.
