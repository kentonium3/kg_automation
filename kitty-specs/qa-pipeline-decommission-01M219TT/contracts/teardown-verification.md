# Contract: teardown verification (tri-state)

The verification script (`verify` action of the deploy, re-runnable any time)
evaluates every surface below and prints one line per check:
`<check-id> ABSENT|PRESENT|UNCHECKABLE <evidence>`. Exit 0 only when every
check is `ABSENT`. A probe error (ssh failure, permission denial, missing tool)
yields `UNCHECKABLE`, never `ABSENT` (Engineering Principle 14).

## office2 checks (run as claude on office2)

| ID | Surface | ABSENT means | Probe sketch |
|---|---|---|---|
| V-01 | webhook process | no process matches `qa_dispatch_webhook.py --serve` | `pgrep -f` distinguishing exit 1 (no match) from exit ≥2 (error) |
| V-02 | port 3457 | no listening socket | `ss -tlnp` parse; ss failure → UNCHECKABLE |
| V-03 | port 8443 | no listening socket (v4+v6) | same |
| V-04 | port 8788 | no listening socket | same |
| V-05 | funnel entry | `tailscale funnel status` output contains no `:8443` proxy | command failure → UNCHECKABLE |
| V-06 | container | no container (any state) named/imaged qa-register | `docker ps -a` filter |
| V-07 | image | `qa-register:fb679e6` absent from `docker images` | |
| V-08 | service dir | `/data/services/qa-register` does not exist | `test -e` semantics; parent unreadable → UNCHECKABLE |
| V-09 | code copy | `/home/claude/spec-kitty-qa` does not exist | |
| V-10 | launcher trio | `start-webhook.sh`, `qa-webhook.pid`, `qa-webhook.log` all absent from `~claude` | |
| V-11 | root env file | `/etc/qa-webhook.env` absent | claude can `test -e` /etc entries; stat failure → UNCHECKABLE |
| V-12 | archive bundle | bundle dir exists AND `MANIFEST.txt` sha256 lines all verify | inverse polarity: PRESENT-and-valid required; reported as `ABSENT` check-family for uniform exit semantics via `archive_ok` |

## Mac checks (run locally)

| ID | Surface | ABSENT means |
|---|---|---|
| M-01..M-05 | the five scratch paths | path does not exist |
| M-06 | QA material in `~/Documents/spec-kitty/` | inventoried QA entries removed; non-QA entries untouched (listed in evidence) |
| M-07 | `~/repos/spec-kitty-qa` protection | git HEAD + `status --porcelain` hash identical to pre-mission snapshot (this is a PRESENT-and-unchanged check, reported via `clone_intact`) |

## Baseline checks (post-rebaseline)

| ID | Surface | Pass means |
|---|---|---|
| B-01 | applied-manifest record | `deploys/applied/*qa*.yaml` carries a `rebaseline:` stamp with outcome success |
| B-02 | next daily audit | no drift finding referencing qa-register / qa-dispatch-webhook / ports 8443, 3457, 8788 |
