# Mac cleanup evidence — WP03 (T011)

Mission: qa-pipeline-decommission-01M219TT · FR-009 · run 2026-09-08T20:23:37Z (UTC)
Script: `scripts/decommission/mac/cleanup.sh` (dry-run reviewed first, then executed;
identical decisions in both modes). Exit code of the real run: **2** (completed with
refusals surfaced — by design, not an error).

## Outcome summary

| Check | Target | Result |
|---|---|---|
| M-01 | `~/repos/teamspace-qa-scratch` | **PRESENT — removal REFUSED** (dirty tree; no git remote → all commits unpushed) |
| M-02 | `~/repos/teamspace-qa-scratch2` | **PRESENT — removal REFUSED** (dirty tree; no git remote → all commits unpushed) |
| M-03 | `~/teamspace-qa-harness` | **ABSENT** (already absent before the run) |
| M-04 | `~/teamkitty-qa` | **ABSENT** (already absent before the run) |
| M-05 | `~/teamkitty-qa-harness` | **ABSENT** (deleted this run; guard clean — no git repo inside) |
| M-06 | `~/Documents/spec-kitty/` QA material | **OK** — inventory written before removal; 0 entries QA-classified, all 4 entries NON-QA and preserved |
| M-07 | `~/repos/spec-kitty-qa` protection | **clone_intact OK** — before/after snapshots identical (proof below) |
| M-08 | unpushed-git guard | **OK** — guard held; 2 targets refused and surfaced, nothing with unpushed/dirty git state was deleted |

## What was deleted

- `~/teamkitty-qa-harness` — not a git repository; contained only
  `docs/design/automated-qa-pipeline-design.md` and a `.DS_Store`. Clearly
  QA-pipeline material (the pipeline design doc); no unique git history at risk.

## What was REFUSED (surfaced for Kent — action needed)

Both refusals are the M-08 guard doing its job; the paths are untouched.

1. **`~/repos/teamspace-qa-scratch`**
   - Guard trigger: dirty tree (`?? .DS_Store`, `?? dist/`).
   - Additionally: the repo has **zero git remotes**, so all 6 commits on `main`
     (latest `98e3e35 chore: apply spec-kitty upgrade changes (3.2.6rc3 -> 3.2.6rc3)`)
     exist nowhere else — even with a clean tree the unpushed-commit guard would fire.
   - Contents: a kittified scratch project (`.kittify/` with missions/memory/event log,
     `.claude/`, `dist/spec-kitty-plugins`, `qa-marker.txt`).
2. **`~/repos/teamspace-qa-scratch2`**
   - Guard trigger: dirty tree (`?? .DS_Store`, `?? .kittify/.DS_Store`).
   - Additionally zero git remotes; 3 commits on `main` (latest
     `4ba4d5c chore: apply spec-kitty upgrade changes (3.2.6rc3 -> 3.2.6rc3)`) exist
     nowhere else.
   - Contents: a kittified scratch project (`.kittify/`, `.claude/`).

To finish the removal Kent can either delete them manually (attesting the git
history is disposable) or clean/push them and re-run
`scripts/decommission/mac/cleanup.sh`.

## `~/Documents/spec-kitty/` classification (M-06)

Inventory was written to disk **before** any removal. Criterion: an entry is QA
only when its name carries a QA-pipeline indicator (qa / teamspace / teamkitty /
register / webhook / harness, case-insensitive); anything else — including
anything ambiguous — is NON-QA and preserved.

| Entry | Classification | Criterion / rationale | Post-run |
|---|---|---|---|
| `.DS_Store` | NON-QA | Finder metadata, no QA indicator | preserved |
| `analyzer-what-it-is-brief.md` | NON-QA | spec-kitty-analyzer explainer, not QA pipeline | preserved |
| `zeitgeist-first-experience-feedback-DRAFT.md` | NON-QA | zeitgeist project material | preserved |
| `zeitgeist-scoping-example` | NON-QA | zeitgeist project material | preserved |

Nothing in `~/Documents/spec-kitty/` was removed; all four entries verified
still present after the run.

## M-07 protection snapshot equality (before/after)

Snapshot = `git rev-parse HEAD` + sha256 of `git status --porcelain` output.

| | HEAD | status sha256 |
|---|---|---|
| before | `abb5cf2844fb90956a72b63b5db35af92caa7917` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| after | `abb5cf2844fb90956a72b63b5db35af92caa7917` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

Identical (the status hash is the sha256 of empty output — the clone was and
remains clean). `~/repos/spec-kitty-qa` was never opened for writing by the
script; only `git rev-parse` / `git status` reads. **clone_intact OK.**

## Full real-run output (verbatim)

```
PROTECT-SNAPSHOT before: HEAD=abb5cf2844fb90956a72b63b5db35af92caa7917 status_sha256=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
TARGET M-01 /Users/kentgale/repos/teamspace-qa-scratch: REFUSED — dirty tree in /Users/kentgale/repos/teamspace-qa-scratch (2 entr(y/ies), e.g. ?? .DS_Store)
TARGET M-02 /Users/kentgale/repos/teamspace-qa-scratch2: REFUSED — dirty tree in /Users/kentgale/repos/teamspace-qa-scratch2 (2 entr(y/ies), e.g. ?? .DS_Store)
TARGET M-03 /Users/kentgale/teamspace-qa-harness: already absent — nothing to do
TARGET M-04 /Users/kentgale/teamkitty-qa: already absent — nothing to do
TARGET M-05 /Users/kentgale/teamkitty-qa-harness: guard clean — approved for deletion
DELETED: /Users/kentgale/teamkitty-qa-harness
DOCS entry: .DS_Store -> NON-QA (no QA-pipeline indicator in name; preserved by default)
DOCS entry: analyzer-what-it-is-brief.md -> NON-QA (no QA-pipeline indicator in name; preserved by default)
DOCS entry: zeitgeist-first-experience-feedback-DRAFT.md -> NON-QA (no QA-pipeline indicator in name; preserved by default)
DOCS entry: zeitgeist-scoping-example -> NON-QA (no QA-pipeline indicator in name; preserved by default)
INVENTORY written: <scratchpad>/inventory-real.md (before Documents removal)

=== Verification (tri-state) ===
M-01 PRESENT /Users/kentgale/repos/teamspace-qa-scratch still exists — removal REFUSED: dirty tree in /Users/kentgale/repos/teamspace-qa-scratch (2 entr(y/ies), e.g. ?? .DS_Store)
M-02 PRESENT /Users/kentgale/repos/teamspace-qa-scratch2 still exists — removal REFUSED: dirty tree in /Users/kentgale/repos/teamspace-qa-scratch2 (2 entr(y/ies), e.g. ?? .DS_Store)
M-03 ABSENT /Users/kentgale/teamspace-qa-harness does not exist
M-04 ABSENT /Users/kentgale/teamkitty-qa does not exist
M-05 ABSENT /Users/kentgale/teamkitty-qa-harness does not exist
M-06 OK inventory=<scratchpad>/inventory-real.md qa_removed=0 nonqa_preserved=4
M-07 clone_intact OK HEAD=abb5cf2844fb90956a72b63b5db35af92caa7917 status_sha256=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 (identical to before)
M-08 OK guard held: 2 target(s) REFUSED and surfaced (listed below), none deleted
  REFUSED: /Users/kentgale/repos/teamspace-qa-scratch :: dirty tree in /Users/kentgale/repos/teamspace-qa-scratch (2 entr(y/ies), e.g. ?? .DS_Store)
  REFUSED: /Users/kentgale/repos/teamspace-qa-scratch2 :: dirty tree in /Users/kentgale/repos/teamspace-qa-scratch2 (2 entr(y/ies), e.g. ?? .DS_Store)

SUMMARY deleted=1 refused=2 already_absent=2 dry_run=0
INVENTORY: <scratchpad>/inventory-real.md
```

## Pre-removal inventory (verbatim copy of the on-disk inventory file)

```
# Mac QA cleanup inventory — 20260908T202337Z

Mode: EXECUTE
Protection snapshot (before): HEAD=abb5cf2844fb90956a72b63b5db35af92caa7917 status_sha256=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855

## Named scratch targets

### M-01 /Users/kentgale/repos/teamspace-qa-scratch
- state: present
- contents (top 2 levels):
    ~/repos/teamspace-qa-scratch
    ~/repos/teamspace-qa-scratch/.DS_Store
    ~/repos/teamspace-qa-scratch/dist
    ~/repos/teamspace-qa-scratch/dist/spec-kitty-plugins
    ~/repos/teamspace-qa-scratch/.claude
    ~/repos/teamspace-qa-scratch/.claude/settings.json
    ~/repos/teamspace-qa-scratch/.claude/agents
    ~/repos/teamspace-qa-scratch/.claude/skills
    ~/repos/teamspace-qa-scratch/.claude/CLAUDE.md
    ~/repos/teamspace-qa-scratch/.claudeignore
    ~/repos/teamspace-qa-scratch/.gitignore
    ~/repos/teamspace-qa-scratch/.gitattributes
    ~/repos/teamspace-qa-scratch/.git
    ~/repos/teamspace-qa-scratch/.git/config
    ~/repos/teamspace-qa-scratch/.git/objects
    ~/repos/teamspace-qa-scratch/.git/HEAD
    ~/repos/teamspace-qa-scratch/.git/info
    ~/repos/teamspace-qa-scratch/.git/logs
    ~/repos/teamspace-qa-scratch/.git/description
    ~/repos/teamspace-qa-scratch/.git/hooks
    ~/repos/teamspace-qa-scratch/.git/refs
    ~/repos/teamspace-qa-scratch/.git/index
    ~/repos/teamspace-qa-scratch/.git/COMMIT_EDITMSG
    ~/repos/teamspace-qa-scratch/.git/FETCH_HEAD
    ~/repos/teamspace-qa-scratch/.kittify
    ~/repos/teamspace-qa-scratch/.kittify/.kitty.env
    ~/repos/teamspace-qa-scratch/.kittify/memory
    ~/repos/teamspace-qa-scratch/.kittify/missions
    ~/repos/teamspace-qa-scratch/.kittify/skills-manifest.json
    ~/repos/teamspace-qa-scratch/.kittify/metadata.yaml
    ~/repos/teamspace-qa-scratch/.kittify/config.yaml
    ~/repos/teamspace-qa-scratch/.kittify/.migration-backup
    ~/repos/teamspace-qa-scratch/.kittify/agent_profiles_manifest.json
    ~/repos/teamspace-qa-scratch/.kittify/canonical-events.jsonl
    ~/repos/teamspace-qa-scratch/.kittify/AGENTS.md
    ~/repos/teamspace-qa-scratch/qa-marker.txt
- git guard: FIRED — dirty tree in /Users/kentgale/repos/teamspace-qa-scratch (2 entr(y/ies), e.g. ?? .DS_Store)
- decision: REFUSE (path left untouched; surfaced per M-08)

### M-02 /Users/kentgale/repos/teamspace-qa-scratch2
- state: present
- contents (top 2 levels):
    ~/repos/teamspace-qa-scratch2
    ~/repos/teamspace-qa-scratch2/.DS_Store
    ~/repos/teamspace-qa-scratch2/.claude
    ~/repos/teamspace-qa-scratch2/.claude/settings.json
    ~/repos/teamspace-qa-scratch2/.claude/agents
    ~/repos/teamspace-qa-scratch2/.claude/skills
    ~/repos/teamspace-qa-scratch2/.claude/CLAUDE.md
    ~/repos/teamspace-qa-scratch2/.claudeignore
    ~/repos/teamspace-qa-scratch2/.gitignore
    ~/repos/teamspace-qa-scratch2/.gitattributes
    ~/repos/teamspace-qa-scratch2/.git
    ~/repos/teamspace-qa-scratch2/.git/.DS_Store
    ~/repos/teamspace-qa-scratch2/.git/ORIG_HEAD
    ~/repos/teamspace-qa-scratch2/.git/config
    ~/repos/teamspace-qa-scratch2/.git/objects
    ~/repos/teamspace-qa-scratch2/.git/HEAD
    ~/repos/teamspace-qa-scratch2/.git/info
    ~/repos/teamspace-qa-scratch2/.git/logs
    ~/repos/teamspace-qa-scratch2/.git/description
    ~/repos/teamspace-qa-scratch2/.git/hooks
    ~/repos/teamspace-qa-scratch2/.git/refs
    ~/repos/teamspace-qa-scratch2/.git/index
    ~/repos/teamspace-qa-scratch2/.git/COMMIT_EDITMSG
    ~/repos/teamspace-qa-scratch2/.git/FETCH_HEAD
    ~/repos/teamspace-qa-scratch2/.kittify
    ~/repos/teamspace-qa-scratch2/.kittify/.kitty.env
    ~/repos/teamspace-qa-scratch2/.kittify/.DS_Store
    ~/repos/teamspace-qa-scratch2/.kittify/memory
    ~/repos/teamspace-qa-scratch2/.kittify/missions
    ~/repos/teamspace-qa-scratch2/.kittify/skills-manifest.json
    ~/repos/teamspace-qa-scratch2/.kittify/metadata.yaml
    ~/repos/teamspace-qa-scratch2/.kittify/config.yaml
    ~/repos/teamspace-qa-scratch2/.kittify/agent_profiles_manifest.json
    ~/repos/teamspace-qa-scratch2/.kittify/canonical-events.jsonl
    ~/repos/teamspace-qa-scratch2/.kittify/AGENTS.md
- git guard: FIRED — dirty tree in /Users/kentgale/repos/teamspace-qa-scratch2 (2 entr(y/ies), e.g. ?? .DS_Store)
- decision: REFUSE (path left untouched; surfaced per M-08)

### M-03 /Users/kentgale/teamspace-qa-harness
- state: already ABSENT before this run

### M-04 /Users/kentgale/teamkitty-qa
- state: already ABSENT before this run

### M-05 /Users/kentgale/teamkitty-qa-harness
- state: present
- contents (top 2 levels):
    ~/teamkitty-qa-harness
    ~/teamkitty-qa-harness/docs
    ~/teamkitty-qa-harness/docs/design
    ~/teamkitty-qa-harness/docs/.DS_Store
- git guard: clean (no repo, or repo fully pushed with clean tree)
- decision: DELETE

## ~/Documents/spec-kitty classification (M-06)

- `.DS_Store` — **NON-QA** — criterion: no QA-pipeline indicator in name; preserved by default
- `analyzer-what-it-is-brief.md` — **NON-QA** — criterion: no QA-pipeline indicator in name; preserved by default
- `zeitgeist-first-experience-feedback-DRAFT.md` — **NON-QA** — criterion: no QA-pipeline indicator in name; preserved by default
- `zeitgeist-scoping-example` — **NON-QA** — criterion: no QA-pipeline indicator in name; preserved by default
```

## Notes

- The dry-run (reviewed before execution) produced decisions identical to the
  real run; no decision changed between modes.
- The interim staging dir `autonomous-run-guard` referenced in planning was
  already gone before this run (consistent with M-03/M-04 being pre-absent).
- Definition of done status: M-01/M-02 are explicitly REFUSED-and-surfaced (the
  sanctioned alternative to pass per the WP), M-03..M-08 pass,
  `~/repos/spec-kitty-qa` provably untouched.
