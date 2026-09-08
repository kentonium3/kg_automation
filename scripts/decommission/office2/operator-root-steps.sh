#!/usr/bin/env bash
# operator-root-steps.sh — office2 QA pipeline teardown (root-only half).
#
# Mission qa-pipeline-decommission-01M219TT (kentonium3/kg-automation#970, WP01/T002).
#
# Kent runs this MANUALLY after felix-deployer has applied the teardown
# manifest (Tier-0 hard lock: agents never execute root actions on office2):
#
#     ssh office2-kgale
#     sudo bash /data/services/host-state/decommission/qa-pipeline-2026-09-08/operator-root-steps.sh
#
# What it does (idempotent — safe to re-run):
#   1. archive /etc/qa-webhook.env into the bundle (0600 root:root) and
#      record its sha256 in ROOT-MANIFEST.txt, then remove /etc/qa-webhook.env
#   2. capture the current Tailscale funnel config into the bundle
#   3. turn Funnel OFF for :8443 only (the :443 tailnet-only serve -> :3456 is
#      a DIFFERENT service and is deliberately untouched)
#   4. verify ROOT-MANIFEST.txt and write operator-complete.txt — the marker
#      that lets the deploy manifest's verification gate (and the deferred
#      rebaseline) finally pass
#
# NEVER prints the contents of qa-webhook.env (it holds credentials).
set -euo pipefail

BUNDLE="${QA_OPERATOR_BUNDLE:-/data/services/host-state/decommission/qa-pipeline-2026-09-08}"
ENV_SRC="${QA_OPERATOR_ENV_SRC:-/etc/qa-webhook.env}"
FUNNEL_PORT=8443

log() { printf '[operator-root] %s\n' "$*"; }
die() { printf '[operator-root] ERROR: %s\n' "$*" >&2; exit 1; }

# --- root-only guard ---------------------------------------------------------
[ "$(id -u)" -eq 0 ] || die "must run as root (sudo). Agents never run this."

command -v tailscale >/dev/null 2>&1 || die "tailscale CLI not found"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum not found"

mkdir -p "$BUNDLE"

manifest_has() {  # basename — is this file already listed in ROOT-MANIFEST.txt?
  [ -f "$BUNDLE/ROOT-MANIFEST.txt" ] && grep -q "  $1\$" "$BUNDLE/ROOT-MANIFEST.txt"
}
manifest_add() {  # basename — append the file's sha256 line
  ( cd "$BUNDLE" && sha256sum "$1" ) >> "$BUNDLE/ROOT-MANIFEST.txt"
  log "ROOT-MANIFEST.txt: recorded $1"
}

# --- step 1: archive /etc/qa-webhook.env, then remove it ---------------------
if [ -f "$ENV_SRC" ]; then
  if [ ! -f "$BUNDLE/qa-webhook.env" ]; then
    install -m 0600 -o root -g root "$ENV_SRC" "$BUNDLE/qa-webhook.env"
    log "archived $ENV_SRC -> $BUNDLE/qa-webhook.env (0600 root)"
  fi
  manifest_has qa-webhook.env || manifest_add qa-webhook.env
  # verify the archived copy before destroying the original (C-003)
  ( cd "$BUNDLE" && grep "  qa-webhook.env\$" ROOT-MANIFEST.txt | sha256sum -c --quiet - ) \
    || die "archived qa-webhook.env does not verify — NOT removing $ENV_SRC"
  rm -f "$ENV_SRC"
  log "removed $ENV_SRC"
elif [ -f "$BUNDLE/qa-webhook.env" ]; then
  log "$ENV_SRC already removed; archived copy present (no-op)"
  manifest_has qa-webhook.env || manifest_add qa-webhook.env
else
  log "WARNING: $ENV_SRC absent and no archived copy — nothing to archive"
fi

# --- step 2: capture current funnel config (first run only) ------------------
if [ ! -f "$BUNDLE/funnel-config-before.json" ]; then
  tailscale funnel status --json > "$BUNDLE/funnel-config-before.json"
  chmod 0644 "$BUNDLE/funnel-config-before.json"
  log "captured funnel config -> funnel-config-before.json"
  manifest_add funnel-config-before.json
else
  log "funnel config already captured (no-op)"
  manifest_has funnel-config-before.json || manifest_add funnel-config-before.json
fi

# --- step 3: turn Funnel off for :8443 only ----------------------------------
# Syntax verified read-only on office2 2026-09-08 (tailscale 1.102.2):
# `tailscale funnel --help` shows `USAGE: tailscale funnel <target>` with flag
# `--https value` ("Expose an HTTPS server at the specified port"). The
# documented per-port disable form is the target keyword `off` scoped by the
# port flag — `tailscale funnel --https=8443 off` — which removes only the
# :8443 funnel handler (https://tailscale.com/kb/1223/funnel). We deliberately
# do NOT use `tailscale funnel reset`: serve and funnel share one config and a
# reset risks clobbering the unrelated :443 tailnet-only serve -> :3456.
if tailscale funnel status | grep -q ":$FUNNEL_PORT"; then
  log "turning Funnel off for :$FUNNEL_PORT"
  tailscale funnel --https="$FUNNEL_PORT" off
else
  log "Funnel already off for :$FUNNEL_PORT (no-op)"
fi

# post-conditions: :8443 gone, the :443 serve -> :3456 untouched
tailscale funnel status | grep -q ":$FUNNEL_PORT" \
  && die "funnel status still lists :$FUNNEL_PORT after off"
if ! tailscale serve status 2>/dev/null | grep -q "3456"; then
  log "WARNING: the :443 tailnet-only serve -> :3456 no longer appears in 'tailscale serve status' — investigate before proceeding (it must NOT be affected by this teardown)"
fi

# --- step 4: verify ROOT-MANIFEST.txt and write the completion marker --------
if [ -f "$BUNDLE/ROOT-MANIFEST.txt" ]; then
  ( cd "$BUNDLE" && sha256sum -c --quiet ROOT-MANIFEST.txt ) \
    || die "ROOT-MANIFEST.txt verification failed — not writing operator-complete.txt"
  ROOT_VERIFIED="yes"
else
  # Nothing root-produced existed to archive; record that honestly.
  ROOT_VERIFIED="no-root-artifacts"
fi

{
  printf 'mission: qa-pipeline-decommission-01M219TT\n'
  printf 'completed_at_utc: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'root-manifest-verified: %s\n' "$ROOT_VERIFIED"
  printf 'funnel-8443: off\n'
} > "$BUNDLE/operator-complete.txt"
chmod 0644 "$BUNDLE/operator-complete.txt"
log "wrote operator-complete.txt — the deploy gate can now pass on the next felix-deployer tick"
exit 0
