# Research: QA Pipeline decommission

All findings measured live on 2026-09-08 (read-only probes as `office2-claude`),
not derived from documentation.

## D-1 Webhook persistence mechanism

- **Decision**: treat the webhook as a manually-launched process; teardown =
  SIGTERM + remove launcher; no unit/cron disable step exists or is needed.
- **Rationale**: `crontab -l` has no webhook/qa entry; `systemctl --user
  list-unit-files` has no qa unit; nothing in `~/.config` references
  `start-webhook`. 12-day uptime is consistent with manual launch.
- **Alternatives considered**: systemd disable / cron removal — inapplicable,
  measured absent.

## D-2 Funnel teardown authority

- **Decision**: Funnel off is an operator (root) step in the Kent-run script.
- **Rationale**: agent accounts have no sudo (verified 2026-08-29, CLAUDE.md);
  `tailscale funnel status` reads fine unprivileged but serve/funnel mutations
  need root or operator privilege, and granting operator is itself a Tier 0
  change. Exact off-syntax to be captured from `tailscale funnel --help` on
  office2 during WP01 (verify-CLI-flag-shape discipline).
- **Alternatives considered**: `tailscale set --operator=claude` to let the
  agent do it — rejected: Tier 0 change to enable a one-shot action.

## D-3 Archive destination

- **Decision**: `/data/services/host-state/decommission/qa-pipeline-2026-09-08/`.
- **Rationale**: Restic source set is `/data/services`, `/data/transcripts`,
  `/home/claude`, `/home/kgale` (service-inventory #888 note). Writing inside
  an existing source path avoids the snapshot path-group split that adding a
  new top-level source would cause (restic forget groups by host,paths — #895
  note). `host-state/` is the established home for recoverable state capture.
- **Alternatives considered**: new `/data/archives` root — rejected (path-group
  split); `/data/services/backup/` — rejected, that tree belongs to the backup
  service itself.

## D-4 `/etc/qa-webhook.env` handling

- **Decision**: the operator script archives it (root can read it; claude
  cannot) into the same archive directory with `0600` root-owned permissions
  preserved, then removes it.
- **Rationale**: C-003 archive-first applies to it; only root can produce the
  copy. Its contents are work-account credentials — the archive stays on the
  Restic-covered host, is not committed anywhere, and is never printed.
- **Alternatives considered**: skip archiving (it is presumably rotated/dead) —
  rejected: attestation covers service ownership, not credential lifecycle.

## D-5 Container/image removal authority

- **Decision**: claude performs `docker stop/rm` + `rmi qa-register:fb679e6`
  via the manifest (claude is in the `docker` group — CLAUDE.md, measured by
  the running `docker ps` succeeding under `sg docker`).
- **Rationale**: keeps the entire non-root teardown on the manifest path.

## D-6 Baseline drift signal

- **Decision**: declare `expected_baselines: [listening-ports.txt,
  docker-images.txt]` in the manifest.
- **Rationale**: port/funnel/container drift has no repo-file signal, which is
  exactly the case `expected_baselines` exists for (deployment runbook; #685
  caveat). Without it the 03:00 audit alerts on our own change — the #886
  class this mission is supposed to end, not repeat.

## D-7 The `:443 → :3456` tailnet serve entry

- **Decision**: untouched, explicitly out of scope.
- **Rationale**: it is tailnet-only (not public) and serves a different
  component; the funnel teardown targets only the `:8443` entry.

## D-8 Mac cleanup safety

- **Decision**: cleanup script inventories each path first, refuses to delete
  any path containing a git repository with unpushed commits or a dirty tree
  (surfaces it instead), snapshots `~/repos/spec-kitty-qa` git state
  before/after (must be identical), and never runs with HOME unset
  (Engineering Principle 15).
- **Rationale**: the teamspace-qa-scratch dirs are of unknown provenance;
  the spec's edge case demands stop-and-surface over silent deletion.
