---
id: mission-brief-template
doc_type: template
title: Mission Brief
status: active
level: reference
owners: [kgale]
last_validated: 2026-08-24
version: 1.0.0
---

# Mission Brief — template

**What this is.** The handoff package for an agent that will own a mission end to end. Filled in by
the coordinator *before* dispatch, handed to a fresh agent, and sufficient on its own — the executing
agent should never have to reconstruct the plan.

**Why it exists.** A runbook is inert; it only helps an agent who decides to read it. A brief is a
**payload that travels with the work**: the obligations arrive *with* the assignment. Sections
2, 3 and 6 are not context — they are the procedures that would otherwise be missed.

> **Fill in every section. An unanswered section is an operator decision** — and per
> `runbooks/autonomous-run-protocol.md` §1b that means the mission **does not start**; it gets
> surfaced and the next item is taken instead.

---

## 1. Identity and ownership

| | |
|---|---|
| **Mission** | `<slug>` |
| **Issue(s)** | `#NNN` — and what "done" means for each |
| **Branch / worktree** | `<branch>` · `<worktree path>` |
| **Vehicle** | full mission / kitty-light — **and why** (D-2: full mission where scope justifies it) |
| **Coordinator** | who holds the map and can be reached |

**You own this mission and are expected to drive it to completion.** Do not wait for approval on
obvious next steps. Where you need a judgment call, see §5.

## 2. Upstream sweep — done at `<date>` (runbook §0)

*Filled in by the coordinator. Do not re-run; act on it.*

- **Build under test**: `spec-kitty-cli <version>` SHA `<sha>`
- **Register rows retired this sweep**: `<#refs, or "none">`
- **⚠ Fault forecast — open upstream issues touching this mission's surfaces:**

  | Upstream | Symptom you may hit | Documented workaround |
  |---|---|---|
  | `#NNNN` | … | … (or **none — this is a `[STOP-B]`**) |

- **Recently fixed upstream, so do NOT work around**: `<#refs>` — if you find yourself reaching for
  a workaround listed here, stop: the workaround is stale and applying it can mask real behaviour.

## 3. On a workflow fault (runbook §D-3) — this is part of DONE, not a detour

**Capture, then continue. Do not halt.** And do not treat this as a distraction from finishing:
**robustly capturing a fault is part of completing the mission.**

⚑ **The evidence is perishable — applying the workaround destroys it.** Before you work around
anything, capture:

1. Exact command + full error output.
2. Build SHA, and the surrounding state (git/worktree/event-log/status as relevant).
3. Root cause — **inspected, not guessed**.
4. The workaround, applied and **observed to work**.

Write all four into a tracking issue **as the need arises**, before continuing.

- **Pre-known workaround** (documented in `docs/spec-kitty-issues.md`, an upstream issue, or memory)
  → apply it, record it, continue. If it is not yet a register row, add one **with a retirement
  condition**.
- **No documented workaround** → `[STOP-B]`. Do **not** improvise one — an improvised workaround is
  a silent workaround.
- **Mid-mission you may assert a hypothesis, not a root-cause claim.** Dedupe, the intent check
  against the tooling's own tests, and formatting happen in the post-mission batch — those read
  surfaces that still exist afterwards. *(Two issues were filed this way with root causes that
  measurement later disproved.)*

## 4. Scope — and what is explicitly OUT

**In scope:** …

**Out of scope, decided in advance** (so it is not re-litigated mid-mission):

- …
- **Product bugs are findings, never fixes.** Never edit the product-under-test's code.

## 5. Decisions — how to choose without stopping

- **At an ordinary implementation fork** → decide per **D-1**: prefer the **more durable, universal,
  maintainable** option. "Reversible" means *back up a data store or mutable runner file before
  changing it if it is not already git-tracked* — it does **not** mean pick the smaller change.
  **Log the decision + rationale.**
- **At a genuine operator decision** (a product requirement, a priority call) → **do not ask, and do
  not decide it.** Surface it in the running report and **move to the next item**. If it blocks this
  mission mid-flight, back out to the last clean `main`, drop the mission, leave no dirty tree.
- **Never present options and wait.** That is the single most common way an unattended run dies.

## 6. Definition of done — including what is owed at terminus

- [ ] Acceptance criteria met and **measured**, not asserted.
- [ ] Suite green at or above the floor (`<count> passed, <count> skipped`).
- [ ] Both review point-cuts ran (post-plan, pre-merge), Opus fallback if Codex is exhausted.
- [ ] **Every workflow fault captured** with all four items from §3, in a tracking issue.
- [ ] **Register updated** — new workarounds added with retirement conditions.
- [ ] Clean tree. Scoped `git add`. Never merged red.
- [ ] **Handoff note** listing: decisions + rationale, faults captured, anything deferred, and
      anything you could **not prove** — a partial pass reported as complete is a defect.

## 7. Non-negotiables

Never post outward without the operator's copy sign-off (draft it and keep going) · never force-push
· never leave a dirty tree or half-merged mission · no secrets in files, logs or output · Tier-0 host
changes off-limits · `.kittify/` and `kitty-specs/` flow through workflow commands · **never write
`kitty-specs/` from a lane worktree** (the commit guard warns and allows while `move-task` refuses,
stranding the WP — evidence goes to scratch, the coordinator records it on the planning branch).

## 8. Reaching the coordinator

Reach back for: a genuine operator decision, a `[STOP-B]`, or a discovery that invalidates the
mission's premise. **Not** for routine forks — those are §5.

State what you tried, what you measured, and what you recommend. A question with a measurement
attached is answerable; one without is a halt.
