---
title: Filing guard — repoint at the new org's upstream repos
doc_type: design
status: superseded
created: 2026-08-26
last_updated: '2026-08-26'
owners: [kgale]
vehicle: none — superseded by mission `filing-guard-survives-org-rename-01M0ZYJ5`
superseded_by:
  - spec-kitty/spec-kitty-qa#287 — the wiring and `_hook_lib.py:1023` fixes that actually shipped
  - mission `filing-guard-survives-org-rename-01M0ZYJ5` — the prefix widening, the
    liveness assertion on the target set, and the documentation surfaces
  - spec-kitty/spec-kitty-qa#291 — what that mission deliberately CUT, and why
---

# Filing guard — repoint at the new org's upstream repos

> ## ⛔ SUPERSEDED — this note is a record, not a plan
>
> **Nothing below is work to do.** Everything it proposed has either shipped, been
> re-scoped, or been deliberately cut:
>
> | This note proposed | What happened |
> |---|---|
> | Widen `UPSTREAM` to a tuple of prefixes | **Not what shipped.** Prefix widening was abandoned: any org-prefix rule breaks again at the next rename, and `spec-kitty/` alone also matches our own tracker. What shipped instead is the inversion — `OURS` enumerates the repositories we own and everything else is upstream, so no prefix list exists to go stale. There is no `UPSTREAM_PREFIXES` in the tree; `_hook_lib.py` matches by full-string equality against `OURS` and states outright that it is *"Never a substring test"* |
> | Three touch points in `upstream_filing_guard.py` | Wrong — see the correction box below. The fourth, in `_hook_lib.py:1023`, shipped under spec-kitty/spec-kitty-qa#287 |
> | The failing-first test below | **Dropped.** Measured as a blind oracle; see the correction box |
> | "Derive the target set from configuration" as the follow-up | **Replaced.** The mission built a liveness assertion on the target set instead — configuration went stale identically and just as silently |
> | Rebinding-detection machinery for register references | **Cut (spec-kitty/spec-kitty-qa#291).** Once a reference names its own repository it cannot silently rebind, so there is nothing left to detect |
>
> The correction box that follows is kept **verbatim**. What this note got wrong is the
> useful part of the record, and deleting it would destroy the evidence.
>
> ---
>
> ## ⚠ The original correction box (2026-08-26) — kept as written
>
> Two post-plan reviews (paula-patterns, debugger-debbie) found this note **wrong on scope,
> ordering, and its test plan**. It is kept because what it got wrong is the useful part of the
> record, not because it is a plan to execute. See **qa#287** for what was actually fixed.
>
> - **Scope** — "Three touch points, all in `upstream_filing_guard.py`" is wrong. There was a
>   fourth in `_hook_lib.py:1023`, failing the **opposite** way (closed, not open), which blocked
>   `spec-kitty specify` outright. That one is now fixed; the rest of this note is not.
> - **Ordering** — the prefix widening described here is the **last** item, not the first.
>   Correct order: wiring → `_hook_lib.py:1023` → repo-scoped dedup evidence → prefix widening.
> - **Test plan** — the failing-first test proposed below is a **blind oracle**. Measured by
>   mutation: it misses `return True`, misses the over-broad `spec-kitty/` typo, and its only
>   unique kill is a letter-case variant. It should be **dropped**, not added. Build new cases
>   through the existing e2e harness instead (`run_bash` / `filing_command(repo=…)` /
>   `assert_deny` / `assert_allow`), and always as deny/allow **pairs**.
> - **The stated follow-up is wrong too** — "derive the target set from configuration" would not
>   have prevented this. `env/*.json` *is* configuration, owns `upstream.repo`, and went stale
>   identically and just as silently. The mechanism that catches it is a **liveness assertion**
>   on the target set.
> - **Not mentioned below, and org-independent:** `scripts/lib/gh_comment.py:76` shells
>   `gh issue comment` through `subprocess`, which a `PreToolUse` hook cannot see; and
>   `gh api repos/.../issues -X POST` is missed because `\bissue\b` does not match `issues`.

## The defect

`scripts/hooks/upstream_filing_guard.py:84` defines the gate's entire notion of "upstream":

```python
UPSTREAM = "Priivacy-ai/"
```

The Team Kitty migration (2026-08-26) moved all upstream filing targets to the `spec-kitty`
org. Per the QA playbook §5, QA now files into exactly three repos:

- `spec-kitty/EXPERIMENTAL-spec-kitty-saas` — Team Kitty pages, invitations, email, dossier
- `spec-kitty/EXPERIMENTAL-spec-kitty` — the CLI
- `spec-kitty/EXPERIMENTAL-spec-kitty-planning` — docs, runbooks, questions

None of these contain the substring `Priivacy-ai/`. So `targets_upstream()` returns False for
every filing the playbook asks us to make, and the guard is **silently inert**: no dedup check,
no attribution footer, no template enforcement.

## Why this is urgent rather than tidy

The failure mode is not "the gate blocks the wrong thing" — it is "the gate is not there."
That is the configuration that produced 27 junk issues on the vendor's public repo (qa#283).
The guard's own docstring names silent omission as the failure it exists to catch. It is
currently unable to catch it on the only repos we now file into.

## The change

Replace the single prefix with a tuple of prefixes.

```python
UPSTREAM_PREFIXES = ("Priivacy-ai/", "spec-kitty/EXPERIMENTAL-")
```

Three touch points, all in `upstream_filing_guard.py`:

| Line | Today | Change |
|---|---|---|
| 84 | `UPSTREAM = "Priivacy-ai/"` | tuple of prefixes |
| 369 | `"whether it targets " + UPSTREAM + "."` | a display string derived from the tuple |
| 476 | `any(UPSTREAM in token for token in argv)` | any prefix, any token |

### The discriminator, and why it is not `"spec-kitty/"`

`"spec-kitty/"` would also match `spec-kitty/spec-kitty-qa` — **this repo**. Internal filings
are deliberately outside the gate; the copy gate applies upstream, not to our own tracker.
Gating our own repo would force dedup evidence and an attribution footer onto routine internal
issues and would be a behaviour change nobody asked for.

All three upstream targets share the `EXPERIMENTAL-` prefix. `spec-kitty/EXPERIMENTAL-` is
therefore a clean discriminator that includes every upstream target and excludes ours.

**Known limit, stated rather than hidden:** this is a name-shaped discriminator. If the new org
renames the repos when the migration settles — dropping `EXPERIMENTAL-`, which is the obvious
eventual step — the gate goes inert again in exactly the same way, and just as silently. This
change buys correctness now; it does not buy durability. A follow-up that derives the target set
from configuration rather than a hardcoded prefix is the real fix, and is out of scope here.

## Fail direction — do not touch

`_hook_lib.deny()` **raises** off `PreToolUse`: this guard is fail-CLOSED. A mistake here does
not fail quietly, it blocks every `gh issue` command. The change must not touch the fail
direction, the denial-raising path, or the argv-position parsing. Widening a prefix tuple is the
whole change.

Note the deliberate asymmetry already in the file: an unresolvable `--repo` **denies**
(`build_unresolvable_repo_denial`), because a repo the gate cannot see is one it cannot clear.
That behaviour is correct and unchanged.

## Tests — red before green

The guard carries 80 dedicated tests (`test_upstream_filing_guard.py` 19,
`test_upstream_filing_guard_fixes.py` 61) plus 44 wiring tests. Both suites parameterise the
target repo through constants (`filing_command(repo=...)`, `UPSTREAM_REPO`), so new-org coverage
is added as parallel cases, not by rewriting existing ones.

The failing-first test:

```python
def test_new_org_filing_is_gated():
    argv = ["gh", "issue", "create", "--repo",
            "spec-kitty/EXPERIMENTAL-spec-kitty-saas", "--title", "T", "--body", "b"]
    assert targets_upstream(argv) is True     # False today
```

Required coverage:

1. Each of the three upstream repos is gated (dedup + footer enforced).
2. `Priivacy-ai/` filings remain gated — no regression on the retiring org.
3. **`spec-kitty/spec-kitty-qa` is NOT gated** — the discriminator's whole point.
4. Read-only verbs (`issue list`, `issue view`, `search issues`, `pr list`, `repo view`) stay
   allowed against the new org, mirroring the existing Priivacy-ai cases.
5. Mention-is-not-invocation still holds: `echo "gh issue create --repo spec-kitty/EXPERIMENTAL-…"`
   is not a filing.

## Explicitly out of scope

- The **96 files** across this repo that reference `Priivacy-ai`. That is the register-invalidation
  pass, it is bulk-edit-shaped, and it carries its own occurrence-classification guardrail.
  Folding it in here would turn a three-line change into a migration.
- `docs/spec-kitty-issues.md` accuracy.
- Deriving the target set from configuration (see "Known limit" above).
