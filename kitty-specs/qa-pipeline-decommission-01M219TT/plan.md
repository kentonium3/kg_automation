# Implementation Plan: QA Pipeline decommission

**Mission**: `qa-pipeline-decommission-01M219TT` · **Branch**: `feat/970-qa-decommission`
**Spec**: [spec.md](spec.md) · **Issue**: kentonium3/kg-automation#970

## Technical Context

**Language/Version**: Bash (POSIX sh–compatible; office2 = Ubuntu 24.04,
Mac = zsh-hosted /bin/sh) for manifest actions, operator script, and
verification; Python 3 only if a check needs structured parsing.
**Primary Dependencies**: none new — existing deploy library
(`scripts/deploy/lib/`), Docker CLI (claude in `docker` group), Tailscale CLI
(root for mutations), Restic (existing schedule, no config change).
**Storage**: archive bundle under `/data/services/host-state/` (inside the
Restic source set); no new stores.
**Testing**: tri-state verification contract (this mission's acceptance
instrument) + repo CI validators for architecture data.
**Target Platform**: office2 (Ubuntu 24.04, via felix-deployer manifest) and
the Mac (local script).
**Project Type**: infrastructure decommission (removal-only; no service code).

**What exists (measured 2026-09-08, read-only):**

- `qa-dispatch-webhook`: `python3 -u scripts/qa_dispatch_webhook.py --serve
  --config env/linear-qa.json`, cwd `/home/claude/spec-kitty-qa`, PID 5068
  (12-day uptime), launched manually by `~claude/start-webhook.sh` (sources
  root-owned `/etc/qa-webhook.env`). **No reboot persistence** — no crontab
  entry, no systemd unit. Pid file `~claude/qa-webhook.pid`, log
  `~claude/qa-webhook.log`.
- Tailscale Funnel: ON — `https://office2.tail0f5f56.ts.net:8443` (Funnel) →
  `127.0.0.1:3457`. The `:443` tailnet-only serve → `:3456` is a DIFFERENT
  service and is out of scope. Funnel/serve reconfiguration requires root
  (agent accounts have no sudo) → operator script.
- `qa-register`: Docker container `qa-register:fb679e6`, bound
  `100.92.197.90:8788->8788`. State `/data/services/qa-register/`:
  `register.db` (+`-shm`,`-wal`), one pre-005 backup trio, `service.env`.
  The `claude` user is in the `docker` group → container/image removal is
  claude-executable.
- `/home/claude/spec-kitty-qa/`: stale non-git code copy.
- Restic source set: `/data/services`, `/data/transcripts`, `/home/claude`,
  `/home/kgale` (service-inventory, #888 note). Archive destination:
  `/data/services/host-state/decommission/qa-pipeline-2026-09-08/` — inside an
  existing source path (no snapshot path-group split; #895 precedent).
- Baselines drifted by removal: `listening-ports.txt` (`:8443` v4+v6, `:3457`,
  `:8788`), `docker-images.txt` (qa-register image). Port/funnel drift has **no
  repo-file signal** → the manifest MUST declare `expected_baselines`.
- Mac scratch paths: `~/repos/teamspace-qa-scratch{,2}`, `~/teamspace-qa-harness`,
  `~/teamkitty-qa`, `~/teamkitty-qa-harness`, QA material in
  `~/Documents/spec-kitty/`. Protected: `~/repos/spec-kitty-qa` (untouched;
  pre/post git-state snapshot proves it).

**Charter Check**: Directives engaged: 001 (architecture record updated in the
same merge), 003 (decision 01M219WG37WXRZPHXGNY3ZHHAR recorded), 030/034 (tests
for any helper logic; verification checks are the mission's "tests"), 037
(living documentation sync — signal-to-doc-map consulted). Engineering
Principle 14 governs every verification check (verified-absent ≠ could-not-check);
Principle 15 (no $HOME scripts with HOME unset) governs the Mac cleanup script.

**Constraints carried from spec**: C-001 Tier-0 hard lock (operator script for
root steps), C-002 work-hat boundary, C-003 archive-first, C-004 tier
discipline, C-005 teardown at deploy step.

## Approach

One deploy manifest carries every office2 action the `claude` user can perform,
ordered archive-first. Root-only actions (Funnel off, `/etc/qa-webhook.env`
removal) ship as a single reviewed operator script the manifest does NOT run;
Kent executes it via `ssh office2-kgale` after the deployer applies the manifest.
Verification is a single idempotent script asserting every removed surface with
tri-state results (absent / present / could-not-check) so NFR-001/SC-006 are
mechanically checkable. The architecture record and the manifest ride the same
merge. Mac cleanup is a local script with inventory-first and an unpushed-git
guard.

**Ordering within the deploy step** (C-003):

1. Archive: `register.db*`, `service.env`, `start-webhook.sh`, and a
   root-readable copy request for `/etc/qa-webhook.env` (operator script
   archives it before deleting, since claude cannot read it) →
   `/data/services/host-state/decommission/qa-pipeline-2026-09-08/`
2. Stop webhook (SIGTERM the pid from `qa-webhook.pid`; verify exit), remove
   `start-webhook.sh`, `qa-webhook.pid`, `qa-webhook.log` (log is archived
   first — it is the only record of recent traffic)
3. Stop + remove qa-register container, remove image `qa-register:fb679e6`,
   remove `/data/services/qa-register/`
4. Remove `/home/claude/spec-kitty-qa/`
5. Operator script (Kent): archive+remove `/etc/qa-webhook.env`, turn Funnel
   off for `:8443`
6. Verify script: tri-state assertions over process, ports, container, image,
   directories, funnel state
7. Rebaseline: manifest `expected_baselines` declares `listening-ports.txt` +
   `docker-images.txt`; felix-deployer's deferred-confirm flow stamps outcomes

## Implementation Concern Map

| Concern | Where it lands | Spec refs |
|---|---|---|
| Deploy manifest + teardown scripts (office2, claude-executable) | WP01 | FR-001, FR-003, FR-004, FR-005, FR-010, C-003, C-004 |
| Operator (root) script + its runbook note | WP01 | FR-002, FR-006, C-001 |
| Tri-state verification script | WP01 | NFR-001, SC-001, SC-002, SC-006 |
| Architecture record updates (inventory retire, ports, credentials, data-flows, signal-to-doc-map targets) | WP02 | FR-007, SC-004 |
| Rebaseline declaration + audit-clean verification | WP01 (manifest) + WP02 (docs) | FR-008, NFR-004, SC-003 |
| Mac cleanup script (inventory-first, unpushed-git guard, spec-kitty-qa snapshot) | WP03 | FR-009, SC-005, C-002 |

WP02 depends on WP01 (records what the manifest does). WP03 is independent.

## Phase 0 — Research

See [research.md](research.md). All clarifications resolved by live measurement;
no NEEDS CLARIFICATION markers remain.

## Phase 1 — Design & Contracts

- [data-model.md](data-model.md) — archive layout, inventory retirement shape,
  expected_baselines declaration.
- [contracts/teardown-verification.md](contracts/teardown-verification.md) —
  the tri-state verification contract (the mission's acceptance instrument).

## Risks

- **Deployer tick timing**: manifest applies within ~5 min of merge to main;
  the 90-minute session budget means merge must not slip past ~T+60.
  Mitigation: WPs are small; WP03 runs in parallel.
- **Funnel command shape**: exact `tailscale funnel` off-syntax verified
  against `tailscale funnel --help` on office2 before the operator script is
  finalized (feedback: verify CLI flag shape).
- **Webhook restarts mid-teardown**: none possible — no persistence mechanism
  exists; the only launcher is the script the manifest removes.
- **register.db parity**: explicitly out of scope (Kent's attestation); the
  archive is the recovery path.
