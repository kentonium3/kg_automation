---
title: QA Pipeline Decommission
doc_type: runbook
audience: agents_and_humans
status: approved
created: 2026-09-08
last_validated: 2026-09-08
last_updated: '2026-09-08'
version: v1.0
owners: [kgale]
---

# QA Pipeline Decommission (operator note)

Mission `qa-pipeline-decommission-01M219TT` · kentonium3/kg-automation#970.
Removes the two spec-kitty-qa QA Pipeline interim tenants from office2 —
`qa-register` (Docker SQLite register, `:8788`) and `qa-dispatch-webhook`
(native process, `:3457`, publicly exposed via Tailscale Funnel `:8443`, the
host's only public-internet ingress) — archive-first, with a root-only half
that Kent runs by hand.

This runbook is the operator's map of a **one-shot decommission**. After the
gate below passes it is a historical record plus the restore procedure.

## What felix-deployer applies (manifest 0030)

`deploys/queued/0030-qa-pipeline-decommission.yaml` (Tier 2 — recent Restic
snapshot enforced before apply). Its entrypoint
`scripts/deploy/deploy-qa-pipeline-decommission.sh --apply`:

1. Copies `teardown.sh`, `operator-root-steps.sh`, `verify.sh` into the archive
   bundle **once** — frozen copies at a path that survives repo evolution. On
   retry ticks an already-bundled script is never silently overwritten: if the
   repo copy has diverged from the bundled copy, the entrypoint fails loudly
   and the divergence must be reconciled deliberately. The verification gate
   and the operator run the **bundle** copies, not the moving checkout.
2. Runs `scripts/decommission/office2/teardown.sh --apply` (idempotent), which
   does everything the `claude` user can do, archive-before-removal (C-003):
   - **stop** the qa-register container (quiesces SQLite for a cold copy);
   - **archive** to the bundle: `register.db*` (all six files, incl. the
     pre-005 backup trio), `service.env`, `start-webhook.sh`,
     `qa-webhook.log`, a tarball of `/home/claude/spec-kitty-qa/`, a
     `docker save` export of the qa-register image, `docker inspect` run
     metadata — then write `CLAUDE-MANIFEST.txt` (sha256 of every
     claude-produced file) and verify it **before any removal**;
   - **stop** the webhook process (SIGTERM via `qa-webhook.pid`);
   - **remove**: the container, every local image whose repository is
     `qa-register` (any tag), `/data/services/qa-register/`,
     `/home/claude/spec-kitty-qa/`, and the `~claude` launcher trio
     (`start-webhook.sh`, `qa-webhook.pid`, `qa-webhook.log`).

What the manifest **cannot** do is the root-only half — that is deliberately
Kent's step (Tier-0 hard lock: agents never execute root actions on office2).

## Kent's step: the operator script (root)

After the deployer has applied the manifest (it will start alerting — see the
gate below — that is your cue, not a fault):

```bash
ssh office2-kgale
```

```bash
sudo bash /data/services/host-state/decommission/qa-pipeline-2026-09-08/operator-root-steps.sh
```

Idempotent — safe to re-run. It:

1. archives `/etc/qa-webhook.env` into the bundle (0600 root:root), records
   its sha256 in `ROOT-MANIFEST.txt`, verifies the copy, **then** removes
   `/etc/qa-webhook.env`;
2. captures the current Funnel config into the bundle;
3. turns Tailscale Funnel **off for `:8443` only** — the `:443` tailnet-only
   Serve → `:3456` (Vikunja) is a different service and is untouched;
4. writes `operator-complete.txt` — the marker the gate waits for.

It never prints the contents of `qa-webhook.env` (it holds credentials).

## The rebaseline gate (deliberate per-tick failure)

The manifest's `verification.post` requires **both** `operator-complete.txt`
and a clean run of the **bundle's frozen** `verify.sh`, anchored on the
teardown completion stamp: `--since "$(head -n1 <bundle>/teardown-complete.txt)"`
(written once by `teardown.sh` at first completion), so V-13 only accepts a
felix-canary tick that **postdates** the teardown. Until then, **the final action fails on every
felix-deployer tick (~5 min) and each failing tick sends an ntfy alert.** This
is the designed gate, not an incident — the known, accepted cost of holding
the deploy open until the root half is done (plan step 7). `teardown.sh` is
idempotent, so the per-tick re-run is a no-op.

Only when the gate passes is the deploy recorded under `deploys/applied/` and
the deferred-confirm rebaseline stamped for the two declared baselines
(`expected_baselines: [listening-ports.txt, docker-images.txt]` — the port
closures and image removal have no repo-file signal, the #685 caveat). After
that, B-01/B-02 hold: the applied record carries a `rebaseline:` success stamp
and the next daily 03:00 audit reports zero QA-related drift. Any **later**
drift naming qa-register / qa-dispatch-webhook / ports 8443, 3457, 8788 is
unexpected — investigate (see
[`security-baseline-ops.md`](<./security-baseline-ops.md>)).

## Reading `verify.sh` (tri-state)

```bash
ssh office2-claude 'B=/data/services/host-state/decommission/qa-pipeline-2026-09-08; bash "$B/verify.sh" --since "$(head -n1 "$B/teardown-complete.txt")"'
```

Without `--since` (or with an unparseable value) V-13 reports `UNCHECKABLE` by
design — a canary tick that predates the teardown cannot vouch for
post-teardown collateral health.

One line per check — `V-01`..`V-13`, `V-15` (contract:
`kitty-specs/qa-pipeline-decommission-01M219TT/contracts/teardown-verification.md`):

| Verdict | Meaning |
|---|---|
| `ABSENT` (or `OK` for V-12 archive-integrity / V-13 collateral-health) | verified removed / verified intact |
| `PRESENT` (or `FAIL`) | removal did not happen — the surface is still there |
| `UNCHECKABLE` | **the probe itself failed** (permission, missing tool, unparseable output). Never a pass — Engineering Principle 14: verified-absent ≠ could-not-check |

Exit 0 **only** when every removal check is `ABSENT`, every integrity/health
check is `OK`, and there are **zero** `UNCHECKABLE`. A nonzero exit with
`UNCHECKABLE` lines means *fix the probe or the permissions and re-run* — it
does not tell you whether teardown succeeded.

From the Mac, the external Funnel probe (V-14) runs separately:

```bash
bash scripts/decommission/office2/verify.sh --external
```

## Archive location + restore sketch (NFR-002)

Bundle: `/data/services/host-state/decommission/qa-pipeline-2026-09-08/`
— inside the Restic source set (`/data/services`), so it enters the nightly
snapshots without any source-set change. Integrity: every claude-produced file
is sha256-listed in `CLAUDE-MANIFEST.txt`, the root-produced `qa-webhook.env`
in `ROOT-MANIFEST.txt`. Never commit or print bundle contents — the env files
hold credentials.

The bundle suffices to restore either component with no other source:

- **qa-register**: `docker load < qa-register-image.tar`; restore
  `/data/services/qa-register/` from `register.db*` + `service.env`; re-run
  with the settings in `qa-register-inspect.json` (ports, binds, env).
- **qa-dispatch-webhook**: unpack `spec-kitty-qa-copy.tar.gz` to
  `/home/claude/spec-kitty-qa/`; reinstall `/etc/qa-webhook.env` (root, 0600)
  from the bundle; relaunch via the archived `start-webhook.sh`; re-enable
  Funnel `:8443 → 127.0.0.1:3457` (root) if public ingress is intended —
  that re-opens the host's only public ingress, so treat it as a new
  security-posture decision, not a mechanical restore.

## Retention check (B-03)

After the next scheduled backup (04:00 daily), confirm the bundle has entered
a snapshot: the restic pointer's snapshot timestamp must **postdate the
bundle's mtime** (claude-readable pointer check — no sudo needed):

```bash
ssh office2-claude 'cat /data/services/backup/state/last-backup.json'
```

Compare its snapshot timestamp against the bundle's mtime. Retention then
follows the existing GFS policy; the bundle is deliberately *not* pruned
separately. Keep the on-disk bundle at operator discretion once B-03 has
confirmed snapshot coverage.

## Related records

Signal-to-doc-map targets reviewed and left unchanged (verified QA-free):
`service-dependencies.view.md`, `felix-capability-roadmap.md`, `identity-model.md`,
`data-flows.view.md`, `hardware-inventory.json`, `docs/design/README.md`,
ADR-0004, `phone-termius-setup.md`.


- Deploy manifest: `deploys/queued/0030-qa-pipeline-decommission.yaml`
  (moves to `deploys/applied/` when the gate passes)
- Scripts (repo copies): `scripts/decommission/office2/`
- Architecture record: retired entries in
  [`service-inventory.json`](<../design/architecture/data/service-inventory.json>),
  ports dropped from
  [`network-topology.json`](<../design/architecture/data/network-topology.json>),
  credential retired in
  [`credential-manifest.json`](<../design/architecture/data/credential-manifest.json>),
  flow retired in
  [`data-flows.json`](<../design/architecture/data/data-flows.json>);
  narrative in [`security-posture.md`](<../design/architecture/security-posture.md>)
  (office2 back to **zero public ingress**, with the permanent DNS/CT-log residue noted)
- Mac-side scratch cleanup: WP03 of the same mission (separate local script;
  `~/repos/spec-kitty-qa` is protected and untouched)
