# Work Packages: QA Pipeline decommission

**Mission**: `qa-pipeline-decommission-01M219TT` · **Branch**: `feat/970-qa-decommission`
**Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md) · **Contract**: [contracts/teardown-verification.md](contracts/teardown-verification.md)
**Generated**: 2026-09-08

## Shape of the work

Three work packages, eleven subtasks. WP01 builds every office2 artifact (the
teardown/verify scripts, the operator root script, the gated deploy manifest).
WP02 updates the architecture record to match what WP01 does and therefore
depends on it. WP03 (Mac cleanup) is independent and can run in parallel with
both. Execution on office2 happens post-merge via felix-deployer; the mission's
in-repo deliverables are the scripts, manifest, and record.

## Subtask Index

| ID | Description | WP | Parallel |
|---|---|---|---|
| T001 | Office2 teardown script: stop container → archive (claude bundle + CLAUDE-MANIFEST.txt) → stop webhook → remove surfaces | WP01 | |
| T002 | Operator root script: archive /etc/qa-webhook.env + ROOT-MANIFEST.txt, remove it, funnel off :8443, write operator-complete marker | WP01 | [P] |
| T003 | Tri-state verify script implementing contract V-01..V-15 (office2 side) | WP01 | [P] |
| T004 | Deploy manifest with expected_baselines + operator-marker completion gate | WP01 | |
| T005 | Dry-run/self-test validation for T001–T004 (shell syntax, dry-run paths, tri-state semantics) | WP01 | |
| T006 | service-inventory.json: retire qa-register + qa-dispatch-webhook entries (status, health_check none, retirement note + archive path) | WP02 | |
| T007 | listening-ports, credentials, data-flows data + markdown counterparts updated for the removal | WP02 | [P] |
| T008 | signal-to-doc-map sweep: update every doc_target for service-removed change class (INDEX, DEVELOPER_PORTAL, security-posture as applicable) | WP02 | |
| T009 | Operator runbook note: how to run the root script, verify, and what the rebaseline gate expects | WP02 | [P] |
| T010 | Mac cleanup script: inventory-first, unpushed-git guard, spec-kitty-qa pre/post snapshot, Documents/spec-kitty classification inventory | WP03 | |
| T011 | Execute Mac cleanup + record inventory file + M-01..M-08 verification evidence | WP03 | |

## WP01 — Office2 teardown artifacts

**Depends on**: none

Build the teardown script (archive-first per the plan's 8-step ordering), the
operator root script, the tri-state verify script, and the gated deploy
manifest. All scripts live under `scripts/decommission/office2/`; the manifest
under `deploys/queued/`. Covers FR-001..FR-006, FR-008, FR-010, C-001, C-003,
C-004, NFR-001, NFR-002.

## WP02 — Architecture record and runbook

**Depends on**: WP01

Update the machine-readable record and its markdown counterparts so the record
matches post-teardown reality, and write the operator note. Covers FR-007,
FR-008 (documentation side), SC-004, NFR-004.

## WP03 — Mac cleanup

**Depends on**: none

Build and execute the local cleanup with its guards and evidence. Scripts under
`scripts/decommission/mac/`; the inventory/evidence file under the mission's
`research/` directory. Covers FR-009, SC-005, C-002, M-01..M-08.
