---
id: hook-fail-directions
doc_type: design
title: Hook fail directions — why PreToolUse and Stop must fail opposite ways
status: active
last_validated: 2026-09-04
version: 1.0.0
---

# Hook fail directions — why `PreToolUse` and `Stop` must fail opposite ways

> **What this is.** Doctrine about this repository's hook layer, derived from the abandoned
> turn-yield Stop-gate mission (qa#278). It is reasoning, not measurement — for measured facts about
> the `Stop` event itself, see [`stop-hook-contract-measured.md`](stop-hook-contract-measured.md),
> which is a live-probe record and should stay that way.
>
> Carried forward when `docs/design/turn-yield-stop-gate-archive/` was removed (qa#368). The mission
> was abandoned; the reasoning below survived it because it is about the hooks we still run.

## 1. The fail-safe direction inverts, and that is the whole problem

A `PreToolUse` gate that cannot decide should **deny**. A `Stop` hook that errors into blocking
**traps the session with no way out**, so its safe failure is to **permit**.

This repository therefore has hooks with *opposite* safe directions, and "making them consistent"
would be a catastrophic edit that looks like tidying. Two concrete traps came from exactly that
confusion:

- the existing `PreToolUse` shell wrapper emits a **deny** on script failure;
- `check_wiring.py` flags `|| exit 0` as a hazard on every entry — correct for `PreToolUse`, exactly
  backwards for `Stop`.

**Before changing any hook's error path, establish which event it serves.** The answer determines
which direction is safe, and the two answers are opposites.

## 2. `_hook_lib` is a fail-CLOSED library

`scripts/hooks/_hook_lib.py` is built for `PreToolUse`. `deny()` raises `ValueError` on any event but
`PreToolUse`; `hooks_root()` raises rather than guessing, and its docstring says *"Callers deny."*

**Any fail-open component consuming it must re-read every error contract under the inversion.** The
abandoned mission's own constraint table said "response builders come from `_hook_lib`" — which,
followed literally, would have produced a `Stop` gate whose only refusal path raises, gets swallowed
by the fail-open handler, and permits forever. A gate that looks complete and holds nothing open.

The library's module docstring already records the same tension:

> DIVERGENCE 1 — C-001 says extend the proven pattern. The proven pattern FAILS OPEN.
> NFR-001 wins, and this is where it wins.

## 3. Recording must never gate permitting, but it must gate refusing

Permit when you cannot record. **Refuse only when you can.**

A refusal whose evidence was never durably stored is a refusal the release path can never escape:
nothing downstream can see why it happened or clear it. The asymmetry is deliberate — an
unrecordable permit costs an audit line, an unrecordable refusal costs a wedged session.

## Provenance

Extracted from `docs/design/turn-yield-stop-gate-archive/README.md` §"The four things worth carrying
forward regardless of approach", items 1–3. Item 4 of that list — that a self-administered quality
checklist cannot see two rows disagreeing — is methodology rather than hook doctrine and now lives in
[`measure-dont-derive.md`](measure-dont-derive.md).

Two facts about the mission that produced this, worth not re-learning:

- **It was abandoned because the approach was chosen without first asking the spec-kitty team how
  they run multiple parallel overnight runs.** Ask the team first. That is the reason it was
  abandoned; do not skip it a second time.
- **qa#278 remains open.** The defect it describes — an unattended run dying because the agent ends
  its turn to report — is real and unfixed. Nothing here fixes it.

The mission's own artifacts recorded one further lesson worth keeping: an earlier draft claimed a
mechanism was *"confirmed with the operator during discovery"* and cited a decision moment that did
not say that. Fabricated provenance survives until someone opens the cited source.
