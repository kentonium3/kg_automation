# Data Model: QA Pipeline decommission

No new runtime data. Three data shapes matter:

## Archive bundle

`/data/services/host-state/decommission/qa-pipeline-2026-09-08/`

| File | Source | Producer |
|---|---|---|
| `register.db`, `register.db-shm`, `register.db-wal` | `/data/services/qa-register/` (container stopped first — cold copy) | manifest (claude) |
| `register.pre-005-*.db{,-shm,-wal}` | same | manifest (claude) |
| `service.env` | same | manifest (claude) |
| `start-webhook.sh` | `/home/claude/` | manifest (claude) |
| `qa-webhook.log` | `/home/claude/` | manifest (claude) |
| `spec-kitty-qa-copy.tar.gz` — the office2 code copy | `/home/claude/spec-kitty-qa/` | manifest (claude) |
| `qa-register-image.tar` — `docker save` of the image | docker | manifest (claude) |
| `qa-register-inspect.json` — container run metadata | `docker inspect` | manifest (claude) |
| `CLAUDE-MANIFEST.txt` — sha256 of every claude-produced file above | generated | manifest (claude) |
| `qa-webhook.env` (0600 root) | `/etc/` | operator script (root) |
| `ROOT-MANIFEST.txt` — sha256 of the root-produced file | generated | operator script (root) |
| `operator-complete.txt` — marker gating manifest completion + rebaseline | generated | operator script (root) |

Invariants: the claude-produced bundle exists and `CLAUDE-MANIFEST.txt`
verifies **before** any removal step runs (C-003; stopping a component is not
removal and precedes its archive to quiesce SQLite); the root-produced entries
verify against `ROOT-MANIFEST.txt` before verification passes; the bundle
suffices to restore either component without any other source (NFR-002:
image export + code tarball + run metadata + env files); bundle lives inside
the Restic source set; nothing in the bundle is ever committed to git or
printed to logs (the env files hold credentials).

## Inventory retirement shape

Both `qa-register` and `qa-dispatch-webhook` entries in
`service-inventory.json`: `status` → `retired`, `health_check` → none (canary
status-gate suppression, #712 precedent), retirement note naming this mission +
issue #970 + the archive path. Listening-ports data drops `:8443`, `:3457`,
`:8788`; credentials data retires the webhook env entry (archived, then
removed); data-flow records drop the Linear→office2 ingress flow.

## expected_baselines declaration

Manifest field: `expected_baselines: ["listening-ports.txt", "docker-images.txt"]`
— the runtime-only drift (ports closed, image removed) that has no repo-file
signal (#685 caveat in CLAUDE.md).

## Verification result (tri-state, Principle 14)

Each check in the verification contract yields exactly one of:
`ABSENT` (verified removed), `PRESENT` (removal failed), `UNCHECKABLE`
(probe itself failed — never reported as success). Mission passes only with
all-`ABSENT` and zero `UNCHECKABLE`.
