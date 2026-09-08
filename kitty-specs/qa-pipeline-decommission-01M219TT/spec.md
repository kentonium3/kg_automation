# Mission Specification: QA Pipeline decommission

**Mission Branch**: `feat/970-qa-decommission`
**Created**: 2026-09-08
**Status**: Draft
**Input**: kentonium3/kg-automation#970 — decommission the QA Pipeline's interim
tenancy on office2 and remove Mac traces, now that EXE.dev owns the pipeline
end-to-end (Kent's attestation, 2026-09-08: Linear no longer needs the office2
webhook; the office2 code copy is stale; the live register is not on office2).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Close the public ingress (Priority: P1)

Kent (system owner) wants office2's only public-internet ingress — the QA
dispatch webhook exposed via Tailscale Funnel on `:8443` — shut down and
removed, because nothing legitimate uses it anymore. After the mission, an
outside request to the Funnel URL gets no service, the webhook process is gone,
and nothing on the host can silently restart it.

**Why this priority**: it is standing public attack surface on the personal
Felix host, serving a pipeline that has moved away. Every other outcome of the
mission is hygiene; this one is security.

**Independent Test**: from any external network, the former Funnel URL refuses
or fails to connect; on office2, no webhook process runs, ports `:8443` and
`:3457` are not listening, and a reboot does not resurrect either.

**Acceptance Scenarios**:

1. **Given** the webhook is running and Funnel is on, **When** the teardown
   deploy step executes (including the operator-run root steps), **Then** the
   webhook process is stopped, its launch script and pid/log files are removed,
   and Funnel no longer forwards `:8443`.
2. **Given** teardown is complete, **When** the host is inspected, **Then**
   `:8443` and `:3457` appear in no listening-socket list and no QA process
   exists for any user.
3. **Given** teardown is complete, **When** the daily security audit next runs
   after rebaseline, **Then** it reports no drift attributable to this change.

---

### User Story 2 - Remove the register component with archive-first discipline (Priority: P2)

Kent wants the `qa-register` container, its image, and its data directory off
office2 — but with the database archived to Restic-covered storage first, so a
surprise dependency can be recovered without re-standing the service.

**Why this priority**: it is a running service and stored state; removal
completes the decommission, and archive-first caps the worst case at
"restore from archive".

**Independent Test**: the container and image are absent, the service
directory is gone, and a dated archive containing the database files and
service configuration exists in Restic-covered storage.

**Acceptance Scenarios**:

1. **Given** qa-register is running, **When** the deploy step executes,
   **Then** an archive of `register.db*` and `service.env` exists under
   Restic-covered storage before the container is stopped.
2. **Given** the archive exists, **When** removal completes, **Then** no
   qa-register container or image remains, `:8788` is not listening, and
   `/data/services/qa-register/` is gone.

---

### User Story 3 - The record tells the truth (Priority: P2)

Kent (and every future agent session) reads the architecture record and the
security baselines and finds no claim that the QA Pipeline still runs on
office2. Inventory entries are marked retired with a pointer to this mission;
listening-ports and docker-image baselines are rebaselined so the daily audit
is clean.

**Why this priority**: the machine-readable record is authoritative in this
system; a decommission that leaves the record lying re-creates the #886 class
of recurring false alerts.

**Independent Test**: architecture-data validators pass; inventory shows both
QA components as retired; the next scheduled security audit after rebaseline
raises no QA-related drift.

**Acceptance Scenarios**:

1. **Given** the services are removed, **When** the mission merges, **Then**
   `service-inventory.json`, listening-ports data, credentials, and data-flow
   records reflect the removal and CI validators pass.
2. **Given** rebaseline completes, **When** the next daily audit runs, **Then**
   no drift alert references QA components.

---

### User Story 4 - Mac scratch traces removed (Priority: P3)

Kent wants the QA scratch and harness directories deleted from the Mac —
`~/repos/teamspace-qa-scratch`, `~/repos/teamspace-qa-scratch2`,
`~/teamspace-qa-harness`, `~/teamkitty-qa`, `~/teamkitty-qa-harness`, and any
QA-pipeline material inside `~/Documents/spec-kitty/` — while the
`~/repos/spec-kitty-qa` clone is left strictly untouched.

**Why this priority**: local hygiene with no security dimension; lowest risk,
lowest urgency.

**Independent Test**: the named scratch paths no longer exist; the
`~/repos/spec-kitty-qa` clone is bit-for-bit untouched (same HEAD, same
uncommitted state).

**Acceptance Scenarios**:

1. **Given** each scratch path, **When** its contents have been inventoried
   (checked for unpushed/unique material) and removal executes, **Then** the
   path is gone and the inventory note records what was there.
2. **Given** `~/Documents/spec-kitty/` holds mixed content, **When** removal
   executes, **Then** only QA-pipeline material is removed and everything else
   remains.
3. **Given** the mission is complete, **When** `~/repos/spec-kitty-qa` is
   inspected, **Then** its git state is identical to before the mission.

### Edge Cases

- The webhook receives a live request mid-teardown → acceptable: Kent attests
  no legitimate traffic remains; teardown does not wait for quiet.
- `register.db` turns out to hold rows the EXE.dev register lacks → the
  archive is the recovery path; the mission does not verify content parity.
- A scratch directory on the Mac contains an unpushed git repository → stop
  removal of that path and surface it to Kent rather than deleting.
- Root-requiring steps (Funnel/serve config, `/etc/qa-webhook.env`) cannot be
  performed by the agent → generated as scripts for Kent; the mission is not
  complete until Kent has run them and verification passes.
- A reboot occurs between teardown and verification → fine: the webhook has no
  reboot persistence, and the container is removed rather than stopped.

## Requirements *(mandatory)*

### Functional Requirements

| ID | Title | User Story | Priority | Status |
|----|-------|------------|----------|--------|
| FR-001 | Stop and remove the QA dispatch webhook | As the system owner, I want the webhook process stopped and its launch script, pid file, and log removed so that no QA ingress mechanism remains on office2. | High | Open |
| FR-002 | Close the Funnel ingress | As the system owner, I want the Tailscale Funnel forwarding on `:8443` turned off (operator-run where root is required) so that office2 has zero public-internet ingress. | High | Open |
| FR-003 | Archive register data before removal | As the system owner, I want `register.db*` and `service.env` archived to Restic-covered storage before the service is touched so that recovery never requires the service. | High | Open |
| FR-004 | Remove the qa-register component | As the system owner, I want the qa-register container, image, and `/data/services/qa-register/` removed so that no QA service or state remains. | High | Open |
| FR-005 | Remove the office2 code copy | As the system owner, I want `/home/claude/spec-kitty-qa/` removed so that no stale pipeline code remains on the host. | Medium | Open |
| FR-006 | Generate operator scripts for root-owned artifacts | As the system owner, I want a reviewed script that removes `/etc/qa-webhook.env` and applies the Funnel change so that I can execute the root steps myself. | High | Open |
| FR-007 | Update the architecture record | As a future reader of the record, I want inventory, listening-ports, credentials, and data-flow records updated (components retired, ingress removed) so that the machine-readable record matches reality. | High | Open |
| FR-008 | Rebaseline security monitoring | As the system owner, I want the affected baselines reset through the sanctioned mechanism so that the daily audit is clean after the change. | High | Open |
| FR-009 | Remove Mac scratch traces | As the machine owner, I want the five named scratch/harness paths and QA material in `~/Documents/spec-kitty/` removed after a contents inventory so that no QA pipeline traces remain on the Mac. | Medium | Open |
| FR-010 | Ride the deploy manifest | As the system operator, I want every office2 action expressible by the pipeline delivered via `deploys/queued/` manifest (with expected baseline declarations for runtime-only drift) so that the change is governed and auditable. | High | Open |

### Non-Functional Requirements

| ID | Title | Requirement | Category | Priority | Status |
|----|-------|-------------|----------|----------|--------|
| NFR-001 | Verifiable closure | Post-change verification distinguishes "verified absent" from "could not check" for every removed surface (process, three ports, container, image, directories); zero surfaces left in "could not check". | Reliability | High | Open |
| NFR-002 | Recovery window | Every archived artifact is restorable for at least the standing Restic retention period; the rollback procedure restores webhook or register service within 30 minutes using only the archives. | Reliability | High | Open |
| NFR-003 | Collateral safety | Zero non-QA services degraded: felix-canary green and all inventory health checks passing within one canary cycle after each deploy step. | Reliability | High | Open |
| NFR-004 | Alert hygiene | At most one expected-drift window: the first daily audit after rebaseline is clean; no recurring QA-related drift alerts thereafter. | Security | Medium | Open |

### Constraints

| ID | Title | Constraint | Category | Priority | Status |
|----|-------|------------|----------|----------|--------|
| C-001 | Tier 0 hard lock | Root-requiring host changes (Funnel/serve reconfiguration if root-gated, `/etc/qa-webhook.env` removal) are generated as scripts and executed only by Kent via `ssh office2-kgale`. | Technical | High | Open |
| C-002 | Work-hat boundary | `~/repos/spec-kitty-qa` on the Mac is untouched; nothing is filed in the `spec-kitty` org; no EXE.dev, Notion, or employee-credential surface is modified. | Business | High | Open |
| C-003 | Archive-first | No stateful artifact (`register.db*`, `service.env`, `/etc/qa-webhook.env`, `start-webhook.sh`) is deleted before a copy exists in Restic-covered storage. | Technical | High | Open |
| C-004 | Tier discipline | Tier 1 steps carry pre-flight and post-change connectivity verification; Tier 2 steps require a Restic backup within 24 hours; agent accounts hold no sudo. | Technical | High | Open |
| C-005 | Timing | Teardown executes as the mission's ordered deploy step, not as an immediate pre-mission action (Decision 01M219WG37WXRZPHXGNY3ZHHAR). | Business | Medium | Open |

### Key Entities

- **qa-dispatch-webhook**: manually-launched process (no reboot persistence),
  public via Tailscale Funnel `:8443 → 127.0.0.1:3457`; config in root-owned
  `/etc/qa-webhook.env`; launch script `start-webhook.sh`, pid + log files in
  the claude home.
- **qa-register**: Docker component `qa-register:fb679e6` bound on `:8788`,
  state in `/data/services/qa-register/` (`register.db` + WAL/SHM siblings,
  one pre-migration backup pair, `service.env`).
- **Architecture record**: `docs/design/architecture/data/` JSON (service
  inventory, listening ports, credentials, data flows) — authoritative; must
  match post-change reality.
- **Security baselines**: security-monitor fingerprints (`listening-ports.txt`,
  `docker-images.txt`) drifted by this change; reset via the sanctioned
  rebaseline mechanism.
- **Mac scratch paths**: the five named directories plus QA material inside
  `~/Documents/spec-kitty/`; explicitly distinct from the protected
  `~/repos/spec-kitty-qa` clone.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: office2 has zero public-internet ingress: external connection
  attempts to the former Funnel URL fail, and no listening socket exists on
  `:8443`, `:3457`, or `:8788`.
- **SC-002**: zero QA Pipeline processes, containers, images, service
  directories, or code copies remain on office2; one dated archive of the
  register data and webhook configuration exists in Restic-covered storage.
- **SC-003**: the first scheduled security audit after rebaseline completes
  with zero QA-related drift findings, and stays clean for the following
  seven days.
- **SC-004**: architecture-data CI validators pass with both QA components
  recorded as retired; no document in the active record claims the pipeline
  runs on office2.
- **SC-005**: the five Mac scratch paths are absent; `~/repos/spec-kitty-qa`
  HEAD and working-tree state are unchanged from the pre-mission snapshot.
- **SC-006**: every removal in SC-001/SC-002/SC-005 is verified by a check
  that can tell "verified absent" from "could not check", and zero checks
  report "could not check".
