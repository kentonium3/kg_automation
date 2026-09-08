#!/usr/bin/env bash
# teardown.sh — office2 QA pipeline teardown (claude-executable half).
#
# Mission qa-pipeline-decommission-01M219TT (kentonium3/kg-automation#970, WP01/T001).
# Invoked on office2 by the deploy entrypoint
# scripts/deploy/deploy-qa-pipeline-decommission.sh (manifest
# deploys/queued/0030-qa-pipeline-decommission.yaml). Runs as the claude user.
#
# Step order per plan.md §Approach (archive-before-REMOVAL, C-003; stopping is
# reversible and precedes the archive so SQLite is copied cold):
#   1. docker stop every qa-register container (stop, NOT remove)
#   2. build the claude archive bundle + CLAUDE-MANIFEST.txt (sha256)
#   3. verify CLAUDE-MANIFEST.txt BEFORE any removal
#   4. SIGTERM the webhook pid and confirm process exit
#   5. remove the launcher trio (start-webhook.sh, qa-webhook.pid, qa-webhook.log)
#   6. remove container(s), all qa-register-repo images,
#      /data/services/qa-register/, /home/claude/spec-kitty-qa/
#
# Idempotent: each step no-ops cleanly when its surface is already absent, so
# the deployer may re-run this on every tick while the operator gate is open.
# NEVER prints the contents of any env file (they hold credentials).
set -euo pipefail

# --- constants (env-overridable for local tests only; production defaults) ---
BUNDLE="${QA_TEARDOWN_BUNDLE:-/data/services/host-state/decommission/qa-pipeline-2026-09-08}"
SERVICE_DIR="${QA_TEARDOWN_SERVICE_DIR:-/data/services/qa-register}"
# Principle 15: never operate on $HOME implicitly — the claude home is named
# explicitly and does not depend on the invoking environment's HOME.
CLAUDE_HOME="${QA_TEARDOWN_CLAUDE_HOME:-/home/claude}"
CODE_DIR="$CLAUDE_HOME/spec-kitty-qa"
IMAGE_REPO="qa-register"
WEBHOOK_PATTERN='qa_dispatch_webhook\.py --serve'

log() { printf '[teardown] %s\n' "$*"; }
die() { printf '[teardown] ERROR: %s\n' "$*" >&2; exit 1; }

MODE="${1:-}"
case "$MODE" in
  --dry-run|--apply) ;;
  *) echo "usage: $0 --dry-run|--apply" >&2; exit 2 ;;
esac

if [ "$MODE" = "--dry-run" ]; then
  log "DRY-RUN action list (no side effects):"
  log "would: docker stop every container whose image repository is $IMAGE_REPO"
  log "would: mkdir -p $BUNDLE"
  log "would: archive register.db{,-shm,-wal} + register.pre-005-* + service.env from $SERVICE_DIR"
  log "would: archive start-webhook.sh + qa-webhook.log from $CLAUDE_HOME"
  log "would: tar $CODE_DIR -> $BUNDLE/spec-kitty-qa-copy.tar.gz"
  log "would: docker save $IMAGE_REPO -> $BUNDLE/qa-register-image.tar"
  log "would: docker inspect qa-register container(s) -> $BUNDLE/qa-register-inspect.json"
  log "would: write + verify $BUNDLE/CLAUDE-MANIFEST.txt (sha256) BEFORE any removal"
  log "would: SIGTERM webhook pid from $CLAUDE_HOME/qa-webhook.pid and confirm exit"
  log "would: rm launcher trio: start-webhook.sh qa-webhook.pid qa-webhook.log"
  log "would: docker rm qa-register container(s); docker rmi all $IMAGE_REPO images"
  log "would: remove $SERVICE_DIR and $CODE_DIR"
  exit 0
fi

# --- docker access: direct, else via sg docker -c (claude is in the docker
# group, but a fresh non-login shell may lack the supplementary group) --------
DOCKER_VIA="direct"
docker_probe_access() {
  if docker info >/dev/null 2>&1; then
    DOCKER_VIA="direct"
  elif sg docker -c "docker info" >/dev/null 2>&1; then
    DOCKER_VIA="sg"
  else
    die "docker unreachable (direct and via sg docker); refusing to proceed blind"
  fi
}
dkr() {
  if [ "$DOCKER_VIA" = "direct" ]; then
    docker "$@"
  else
    local q=""
    local a
    for a in "$@"; do q="$q $(printf '%q' "$a")"; done
    sg docker -c "docker$q"
  fi
}

docker_probe_access
log "docker access: $DOCKER_VIA"

qa_container_ids() {  # all states
  dkr ps -a --format '{{.ID}} {{.Image}}' | awk -v r="$IMAGE_REPO" \
    '$2 == r || index($2, r ":") == 1 {print $1}'
}
qa_running_ids() {
  dkr ps --format '{{.ID}} {{.Image}}' | awk -v r="$IMAGE_REPO" \
    '$2 == r || index($2, r ":") == 1 {print $1}'
}
qa_image_ids() {
  dkr images --format '{{.Repository}} {{.ID}}' | awk -v r="$IMAGE_REPO" \
    '$1 == r {print $2}' | sort -u
}

# --- step 1: stop container(s) — quiesce SQLite for a cold copy -------------
RUNNING="$(qa_running_ids || true)"
if [ -n "$RUNNING" ]; then
  for id in $RUNNING; do
    log "step1: docker stop $id"
    dkr stop "$id" >/dev/null
  done
else
  log "step1: no running $IMAGE_REPO container (no-op)"
fi

# --- step 2: build the archive bundle ---------------------------------------
mkdir -p "$BUNDLE"
COPIED=0

archive_file() {  # src dst-basename
  local src="$1" dst="$BUNDLE/$2"
  if [ -e "$dst" ]; then
    # Skip-if-exists is only safe when the live source (if still present)
    # matches the archived copy byte-for-byte. Across deployer retry ticks a
    # source could have changed after the first archive pass — proceeding
    # would remove state the bundle does not actually hold.
    if [ -e "$src" ]; then
      local h_src h_dst
      h_src="$(sha256sum "$src" | awk '{print $1}')"
      h_dst="$(sha256sum "$dst" | awk '{print $1}')"
      [ "$h_src" = "$h_dst" ] \
        || die "archived $2 differs from live $src — stale archive; refusing to proceed"
    fi
    return 0
  fi
  if [ -e "$src" ]; then
    cp -p "$src" "$dst"
    COPIED=$((COPIED + 1))
    log "step2: archived $src"
  fi
}

for f in register.db register.db-shm register.db-wal service.env; do
  archive_file "$SERVICE_DIR/$f" "$f"
done
# pre-005 backup trio (glob; nullglob-safe under set -u)
for src in "$SERVICE_DIR"/register.pre-005-*; do
  [ -e "$src" ] || continue
  archive_file "$src" "$(basename "$src")"
done
archive_file "$CLAUDE_HOME/start-webhook.sh" "start-webhook.sh"
archive_file "$CLAUDE_HOME/qa-webhook.log" "qa-webhook.log"

if [ -d "$CODE_DIR" ] && [ ! -e "$BUNDLE/spec-kitty-qa-copy.tar.gz" ]; then
  log "step2: tarring $CODE_DIR"
  tar -czf "$BUNDLE/spec-kitty-qa-copy.tar.gz" -C "$CLAUDE_HOME" spec-kitty-qa
  COPIED=$((COPIED + 1))
fi

IMAGES="$(qa_image_ids || true)"
if [ -n "$IMAGES" ] && [ ! -e "$BUNDLE/qa-register-image.tar" ]; then
  log "step2: docker save $IMAGE_REPO"
  dkr save -o "$BUNDLE/qa-register-image.tar" "$IMAGE_REPO"
  COPIED=$((COPIED + 1))
fi

CONTAINERS="$(qa_container_ids || true)"
if [ -n "$CONTAINERS" ] && [ ! -e "$BUNDLE/qa-register-inspect.json" ]; then
  log "step2: docker inspect container(s)"
  # shellcheck disable=SC2086 — ids are docker-generated hex, unquoted split intended
  dkr inspect $CONTAINERS > "$BUNDLE/qa-register-inspect.json"
  COPIED=$((COPIED + 1))
fi

# Remove the container(s) right after save+inspect are captured: a
# restart-policy resurrection during the operator-gate window would write new
# SQLite state and recreate divergence between the archive and the live tree.
# Only once its archive artifacts exist is the container's removal safe.
if [ -n "$CONTAINERS" ] && [ -e "$BUNDLE/qa-register-inspect.json" ]; then
  for id in $CONTAINERS; do
    log "step2: docker rm $id (resurrection guard — save+inspect captured)"
    dkr rm -f "$id" >/dev/null
  done
fi

# Manifest covers exactly the claude-produced archive artifacts — never
# ROOT-MANIFEST.txt / qa-webhook.env / funnel capture / operator-complete.txt
# (root-produced) and never itself.
claude_bundle_files() {
  ( cd "$BUNDLE" &&
    for f in register.db register.db-shm register.db-wal register.pre-005-* \
             service.env start-webhook.sh qa-webhook.log \
             spec-kitty-qa-copy.tar.gz qa-register-image.tar \
             qa-register-inspect.json; do
      [ -e "$f" ] && printf '%s\n' "$f"
    done
    true )
}

BUNDLE_FILES="$(claude_bundle_files)"
if [ -n "$BUNDLE_FILES" ]; then
  if [ "$COPIED" -gt 0 ] || [ ! -f "$BUNDLE/CLAUDE-MANIFEST.txt" ]; then
    log "step2: writing CLAUDE-MANIFEST.txt ($(printf '%s\n' "$BUNDLE_FILES" | wc -l | tr -d ' ') entries)"
    ( cd "$BUNDLE" && printf '%s\n' "$BUNDLE_FILES" | xargs sha256sum ) \
      > "$BUNDLE/CLAUDE-MANIFEST.txt.tmp"
    mv "$BUNDLE/CLAUDE-MANIFEST.txt.tmp" "$BUNDLE/CLAUDE-MANIFEST.txt"
  else
    log "step2: CLAUDE-MANIFEST.txt already present, nothing new copied (no-op)"
  fi
fi

# --- step 3: verify the manifest BEFORE any removal (C-003 gate) ------------
surfaces_remaining() {
  [ -e "$SERVICE_DIR" ] && return 0
  [ -e "$CODE_DIR" ] && return 0
  [ -e "$CLAUDE_HOME/start-webhook.sh" ] && return 0
  [ -n "$(qa_container_ids || true)" ] && return 0
  [ -n "$(qa_image_ids || true)" ] && return 0
  return 1
}

if [ -f "$BUNDLE/CLAUDE-MANIFEST.txt" ]; then
  log "step3: verifying CLAUDE-MANIFEST.txt"
  ( cd "$BUNDLE" && sha256sum -c --quiet CLAUDE-MANIFEST.txt ) \
    || die "archive manifest verification FAILED — refusing to remove anything"
  log "step3: archive verified"
elif surfaces_remaining; then
  die "no CLAUDE-MANIFEST.txt but removal surfaces still exist — refusing to remove without a verified archive"
else
  log "step3: nothing archived and nothing left to remove (already torn down)"
fi

# --- step 4: stop the webhook (SIGTERM + confirm exit) ----------------------
webhook_pids() {
  # pgrep rc 1 = no match (fine); rc >= 2 = probe failure (fail loud).
  local out rc
  set +e
  out="$(pgrep -f "$WEBHOOK_PATTERN" 2>/dev/null)"
  rc=$?
  set -e
  [ "$rc" -ge 2 ] && die "pgrep failed (rc=$rc) — cannot determine webhook state"
  printf '%s' "$out"
}

# NEVER call webhook_pids inside a bare test substitution: `die` inside
# `$( )` only exits the subshell, so `[ -n "$(webhook_pids)" ]` would read a
# pgrep probe failure (rc>=2) as "no pids" and let removal proceed. Assign
# first — a failing command substitution in an assignment propagates the
# failure under set -e and aborts before any removal step.
PIDS="$(webhook_pids)"
if [ -n "$PIDS" ]; then
  for pid in $PIDS; do
    log "step4: SIGTERM webhook pid $pid"
    kill -TERM "$pid" 2>/dev/null || true
  done
  i=0
  REMAIN="$PIDS"
  while [ -n "$REMAIN" ] && [ "$i" -lt 30 ]; do
    sleep 1
    i=$((i + 1))
    REMAIN="$(webhook_pids)"
  done
  [ -z "$REMAIN" ] || die "webhook still running after SIGTERM + 30s"
  log "step4: webhook exited"
else
  log "step4: no webhook process (no-op)"
fi

# --- step 5: remove the launcher trio ---------------------------------------
for f in start-webhook.sh qa-webhook.pid qa-webhook.log; do
  if [ -e "$CLAUDE_HOME/$f" ]; then
    rm -f "$CLAUDE_HOME/$f"
    log "step5: removed $CLAUDE_HOME/$f"
  fi
done

# --- step 6: remove container(s), images, directories -----------------------
CONTAINERS="$(qa_container_ids || true)"
if [ -n "$CONTAINERS" ]; then
  for id in $CONTAINERS; do
    log "step6: docker rm $id"
    dkr rm -f "$id" >/dev/null
  done
else
  log "step6: no $IMAGE_REPO container (no-op)"
fi

IMAGES="$(qa_image_ids || true)"
if [ -n "$IMAGES" ]; then
  for img in $IMAGES; do
    log "step6: docker rmi $img"
    dkr rmi -f "$img" >/dev/null
  done
else
  log "step6: no $IMAGE_REPO image (no-op)"
fi

if [ -e "$SERVICE_DIR" ]; then
  log "step6: removing $SERVICE_DIR"
  rm -rf "$SERVICE_DIR"
fi
if [ -e "$CODE_DIR" ]; then
  log "step6: removing $CODE_DIR"
  rm -rf "$CODE_DIR"
fi

# Write-once completion stamp: the V-13 reference time. verify.sh --since
# only accepts a canary tick that POSTdates this moment, so a pre-teardown
# tick can never vouch for post-teardown collateral health. Write-once so
# idempotent retry ticks do not keep pushing the reference forward.
if [ ! -e "$BUNDLE/teardown-complete.txt" ]; then
  {
    date -u +%s
    date -u +%Y-%m-%dT%H:%M:%SZ
  } > "$BUNDLE/teardown-complete.txt"
  log "wrote teardown-complete.txt (V-13 --since reference time)"
fi

log "teardown complete (claude half). Operator half: sudo bash $BUNDLE/operator-root-steps.sh"
exit 0
