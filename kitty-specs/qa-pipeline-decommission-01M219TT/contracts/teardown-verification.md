# Contract: teardown verification (tri-state)

The verification script (`verify` action of the deploy, re-runnable any time)
evaluates every surface below and prints one line per check:
`<check-id> ABSENT|PRESENT|UNCHECKABLE <evidence>`. Exit 0 only when every
removal check is `ABSENT` and every integrity/health check is `OK`. A probe
error (ssh failure, permission denial, missing tool, unparseable output)
yields `UNCHECKABLE`, never a pass (Engineering Principle 14).

## office2 checks (run as claude on office2)

| ID | Surface | Pass means | Probe sketch |
|---|---|---|---|
| V-01 | webhook process | no process matches `qa_dispatch_webhook.py --serve` | `pgrep -f`: exit 1 = ABSENT, exit 0 = PRESENT, exit ≥2 = UNCHECKABLE |
| V-02 | port 3457 | no listening socket | `ss -tlnp` parse; ss failure → UNCHECKABLE |
| V-03 | port 8443 | no listening socket (v4+v6) | same |
| V-04 | port 8788 | no listening socket | same |
| V-05 | funnel entry (local view) | `tailscale funnel status` output contains no `:8443` proxy | command failure → UNCHECKABLE |
| V-06 | container | no container (any state) whose image repository is `qa-register` | `docker ps -a` |
| V-07 | images | zero local images whose repository is `qa-register` (any tag or ID) — not just `fb679e6` | `docker images` by repo |
| V-08 | service dir | `/data/services/qa-register` does not exist | `test -e`; parent unreadable → UNCHECKABLE |
| V-09 | code copy | `/home/claude/spec-kitty-qa` does not exist | |
| V-10 | launcher trio | `start-webhook.sh`, `qa-webhook.pid`, `qa-webhook.log` all absent from `~claude` | |
| V-11 | root env file | `/etc/qa-webhook.env` absent | `test -e`; stat failure → UNCHECKABLE |
| V-12 | archive integrity | bundle exists; every line of `CLAUDE-MANIFEST.txt` **and** `ROOT-MANIFEST.txt` sha256-verifies; `operator-complete.txt` present | reported as `archive_ok` OK/FAIL/UNCHECKABLE |
| V-13 | collateral health | felix-canary latest tick green AND no inventory health check newly failing vs. pre-mission snapshot | canary state file + health run; missing/stale tick → UNCHECKABLE |
| V-15 | persistence re-scan | fresh post-teardown scan of claude crontab, systemd user units, and `~claude` launch scripts finds no QA launcher | scan failure → UNCHECKABLE |

## External check (run from the Mac)

| ID | Surface | Pass means |
|---|---|---|
| V-14 | public funnel URL | HTTPS request to `https://office2.tail0f5f56.ts.net:8443/` fails to connect/refuses (no HTTP response from the former service). Any 2xx/4xx/5xx HTTP answer = PRESENT; DNS/transport ambiguity that cannot distinguish refused from untested = UNCHECKABLE. Caveat recorded: the Mac is a tailnet member; the probe still traverses the public Funnel hostname. |

## Mac checks (run locally)

| ID | Surface | Pass means |
|---|---|---|
| M-01..M-05 | the five scratch paths | path does not exist |
| M-06 | QA material in `~/Documents/spec-kitty/` | a written inventory file (path, classification QA/non-QA, decision, rationale) exists **before** removal; QA-classified entries removed; every non-QA entry still present |
| M-07 | `~/repos/spec-kitty-qa` protection | git HEAD + `status --porcelain` output identical to the pre-mission snapshot (PRESENT-and-unchanged, reported via `clone_intact`) |
| M-08 | unpushed-git guard | for every scratch path removed: either it contained no git repo, or its repo had no unpushed commits and no dirty tree; any other state → removal refused and surfaced (recorded in the inventory file) |

## Baseline checks (post-rebaseline)

| ID | Surface | Pass means |
|---|---|---|
| B-01 | applied-manifest record | `deploys/applied/*qa*.yaml` carries a `rebaseline:` stamp with outcome success, timestamped after `operator-complete.txt` |
| B-02 | next daily audit | a **successful** audit run with run timestamp after the rebaseline stamp exists, its status parsed as completed, and it contains zero drift findings referencing qa-register / qa-dispatch-webhook / ports 8443, 3457, 8788. Missing, stale, or failed audit → UNCHECKABLE, not pass |
| B-03 | retention coverage | the restic backup pointer's snapshot timestamp postdates the archive bundle's creation time (the bundle has entered a snapshot) |
