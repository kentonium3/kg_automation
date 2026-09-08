#!/usr/bin/env bash
# verify.sh — tri-state teardown verification for the office2 QA pipeline.
#
# Mission qa-pipeline-decommission-01M219TT (kentonium3/kg-automation#970, WP01/T003).
# Contract: kitty-specs/qa-pipeline-decommission-01M219TT/contracts/teardown-verification.md
#
# Prints one line per check:  <check-id> ABSENT|PRESENT|UNCHECKABLE <evidence>
# (integrity/health checks V-12/V-13 report OK|FAIL|UNCHECKABLE).
#
# Engineering Principle 14: a probe error (ssh failure, permission denial,
# missing tool, unparseable output) yields UNCHECKABLE — NEVER a pass. Exit 0
# only when every removal check is ABSENT and every integrity/health check is
# OK, with zero UNCHECKABLE.
#
# Modes:
#   (no args)    office2 checks V-01..V-13, V-15 (run as claude on office2)
#   --external   V-14 only: curl probe of the public funnel URL (run from Mac)
set -u

# --- surfaces (env-overridable for tests; production defaults) ---------------
BUNDLE="${QA_VERIFY_BUNDLE:-/data/services/host-state/decommission/qa-pipeline-2026-09-08}"
SERVICE_DIR="${QA_VERIFY_SERVICE_DIR:-/data/services/qa-register}"
# Principle 15: the claude home is named explicitly, never inferred from $HOME.
CLAUDE_HOME="${QA_VERIFY_CLAUDE_HOME:-/home/claude}"
ROOT_ENV="${QA_VERIFY_ROOT_ENV:-/etc/qa-webhook.env}"
CANARY_STATE="${QA_VERIFY_CANARY_STATE:-/data/services/felix-canary/state/last-tick.json}"
CANARY_MAX_AGE="${QA_VERIFY_CANARY_MAX_AGE:-2100}"
FUNNEL_URL="${QA_VERIFY_FUNNEL_URL:-https://office2.tail0f5f56.ts.net:8443/}"
CODE_DIR="$CLAUDE_HOME/spec-kitty-qa"
IMAGE_REPO="qa-register"
WEBHOOK_PATTERN='qa_dispatch_webhook\.py --serve'

FAILS=0
UNCHECKABLES=0

emit() {  # id verdict evidence...
  local id="$1" verdict="$2"
  shift 2
  printf '%s %s %s\n' "$id" "$verdict" "$*"
  case "$verdict" in
    ABSENT|OK) ;;
    UNCHECKABLE) UNCHECKABLES=$((UNCHECKABLES + 1)) ;;
    *) FAILS=$((FAILS + 1)) ;;   # PRESENT / FAIL
  esac
}

# --- V-14: external funnel probe (Mac-side; --external mode only) ------------
check_external() {
  if ! command -v curl >/dev/null 2>&1; then
    emit V-14 UNCHECKABLE "curl not found"
    return
  fi
  curl -sS -o /dev/null -m 20 "$FUNNEL_URL" 2>/dev/null
  local rc=$?
  # curl rc taxonomy: 0 = an HTTP response arrived (any status) -> the
  # endpoint still answers -> PRESENT. 7 (connect refused/failed),
  # 35 (TLS handshake rejected), 56 (connection reset) = transport-level
  # refusal with no HTTP answer -> ABSENT. Anything else (6 DNS, 28 timeout,
  # ...) cannot distinguish "refused" from "probe never reached the host"
  # -> UNCHECKABLE, never ABSENT (Principle 14).
  case "$rc" in
    0)        emit V-14 PRESENT "HTTP response received from $FUNNEL_URL" ;;
    7|35|56)  emit V-14 ABSENT "connection refused/reset (curl rc=$rc)" ;;
    *)        emit V-14 UNCHECKABLE "transport ambiguity (curl rc=$rc)" ;;
  esac
}

# --- helpers -----------------------------------------------------------------
check_path_absent() {  # id path label
  local id="$1" path="$2" label="$3" parent
  if [ -e "$path" ] || [ -L "$path" ]; then
    emit "$id" PRESENT "$label still exists: $path"
    return
  fi
  parent="$(dirname "$path")"
  if [ -d "$parent" ] && [ -r "$parent" ] && [ -x "$parent" ]; then
    emit "$id" ABSENT "$label gone: $path"
  else
    emit "$id" UNCHECKABLE "parent $parent not traversable — cannot confirm $label absent"
  fi
}

check_port() {  # id port
  local id="$1" port="$2" out rc
  out="$(ss -tln 2>/dev/null)"
  rc=$?
  if [ "$rc" -ne 0 ] || [ -z "$out" ]; then
    emit "$id" UNCHECKABLE "ss probe failed (rc=$rc)"
    return
  fi
  if printf '%s\n' "$out" | grep -Eq "[]:.]$port[[:space:]]"; then
    emit "$id" PRESENT "listening socket on :$port"
  else
    emit "$id" ABSENT "no listener on :$port"
  fi
}

docker_lines() {  # docker args... -> stdout lines; rc 0 ok, 1 unreachable
  local out
  if out="$(docker "$@" 2>/dev/null)"; then
    printf '%s\n' "$out"
    return 0
  fi
  if out="$(sg docker -c "docker $*" 2>/dev/null)"; then
    printf '%s\n' "$out"
    return 0
  fi
  return 1
}

# --- office2 checks ----------------------------------------------------------
check_office2() {
  local out rc

  # V-01 webhook process (pgrep: rc0=match, rc1=no match, rc>=2=probe failure)
  if command -v pgrep >/dev/null 2>&1; then
    pgrep -f "$WEBHOOK_PATTERN" >/dev/null 2>&1
    rc=$?
    case "$rc" in
      0) emit V-01 PRESENT "process matching $WEBHOOK_PATTERN" ;;
      1) emit V-01 ABSENT "no process matches webhook pattern" ;;
      *) emit V-01 UNCHECKABLE "pgrep probe failed (rc=$rc)" ;;
    esac
  else
    emit V-01 UNCHECKABLE "pgrep not found"
  fi

  # V-02..V-04 ports
  check_port V-02 3457
  check_port V-03 8443
  check_port V-04 8788

  # V-05 funnel entry (local view)
  if ! command -v tailscale >/dev/null 2>&1; then
    emit V-05 UNCHECKABLE "tailscale CLI not found"
  else
    out="$(tailscale funnel status 2>/dev/null)"
    rc=$?
    if [ "$rc" -ne 0 ]; then
      emit V-05 UNCHECKABLE "tailscale funnel status failed (rc=$rc)"
    elif printf '%s\n' "$out" | grep -q ':8443'; then
      emit V-05 PRESENT "funnel status still lists :8443"
    else
      emit V-05 ABSENT "funnel status has no :8443 entry"
    fi
  fi

  # V-06 container (any state) by image repo
  if out="$(docker_lines ps -a --format '{{.Image}}')"; then
    if printf '%s\n' "$out" | grep -Eq "^${IMAGE_REPO}(:|\$)"; then
      emit V-06 PRESENT "container with image repo $IMAGE_REPO exists"
    else
      emit V-06 ABSENT "no container with image repo $IMAGE_REPO"
    fi
  else
    emit V-06 UNCHECKABLE "docker unreachable (direct and via sg)"
  fi

  # V-07 images by repo (any tag or ID)
  if out="$(docker_lines images --format '{{.Repository}}')"; then
    if printf '%s\n' "$out" | grep -Fxq "$IMAGE_REPO"; then
      emit V-07 PRESENT "local image(s) with repository $IMAGE_REPO"
    else
      emit V-07 ABSENT "zero local images with repository $IMAGE_REPO"
    fi
  else
    emit V-07 UNCHECKABLE "docker unreachable (direct and via sg)"
  fi

  # V-08 / V-09 directories
  check_path_absent V-08 "$SERVICE_DIR" "service dir"
  check_path_absent V-09 "$CODE_DIR" "code copy"

  # V-10 launcher trio
  local trio_present="" trio_uncheckable=""
  local f
  for f in start-webhook.sh qa-webhook.pid qa-webhook.log; do
    if [ -e "$CLAUDE_HOME/$f" ]; then
      trio_present="$trio_present $f"
    elif ! { [ -d "$CLAUDE_HOME" ] && [ -r "$CLAUDE_HOME" ] && [ -x "$CLAUDE_HOME" ]; }; then
      trio_uncheckable="yes"
    fi
  done
  if [ -n "$trio_present" ]; then
    emit V-10 PRESENT "launcher file(s) remain:$trio_present"
  elif [ -n "$trio_uncheckable" ]; then
    emit V-10 UNCHECKABLE "$CLAUDE_HOME not traversable"
  else
    emit V-10 ABSENT "launcher trio gone from $CLAUDE_HOME"
  fi

  # V-11 root env file
  check_path_absent V-11 "$ROOT_ENV" "root env file"

  # V-12 archive integrity (OK/FAIL/UNCHECKABLE, reported as archive_ok)
  check_archive

  # V-13 collateral health: felix-canary latest tick green + fresh. The canary
  # runs every inventory health check each 15-min pass, so a fresh green tick
  # IS the "no inventory check newly failing" signal.
  check_canary

  # V-15 persistence re-scan
  check_persistence
}

check_archive() {
  if [ ! -d "$BUNDLE" ]; then
    emit V-12 FAIL "archive_ok bundle dir missing: $BUNDLE"
    return
  fi
  if ! command -v sha256sum >/dev/null 2>&1; then
    emit V-12 UNCHECKABLE "archive_ok sha256sum not found"
    return
  fi
  if [ ! -f "$BUNDLE/CLAUDE-MANIFEST.txt" ]; then
    emit V-12 FAIL "archive_ok CLAUDE-MANIFEST.txt missing"
    return
  fi
  if ! ( cd "$BUNDLE" && sha256sum -c --quiet CLAUDE-MANIFEST.txt >/dev/null 2>&1 ); then
    emit V-12 FAIL "archive_ok CLAUDE-MANIFEST.txt does not verify"
    return
  fi
  if [ ! -f "$BUNDLE/ROOT-MANIFEST.txt" ]; then
    emit V-12 FAIL "archive_ok ROOT-MANIFEST.txt missing"
    return
  fi
  if [ ! -f "$BUNDLE/operator-complete.txt" ]; then
    emit V-12 FAIL "archive_ok operator-complete.txt missing"
    return
  fi
  # ROOT-MANIFEST entries: the archived qa-webhook.env is 0600 root, so the
  # claude user CANNOT hash it. Root verified the manifest when it wrote
  # operator-complete.txt (root-manifest-verified: yes). Here: verify every
  # readable entry directly; for an unreadable-but-existing entry accept the
  # root attestation; a missing entry or hash mismatch is FAIL; an unreadable
  # entry WITHOUT the attestation is UNCHECKABLE (not a pass).
  local line hash file verdict="OK" evidence="both manifests verified"
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    hash="${line%% *}"
    file="${line##* }"
    if [ ! -e "$BUNDLE/$file" ]; then
      verdict="FAIL"; evidence="ROOT-MANIFEST entry missing: $file"; break
    elif [ -r "$BUNDLE/$file" ]; then
      if ! ( cd "$BUNDLE" && printf '%s  %s\n' "$hash" "$file" | sha256sum -c --quiet - >/dev/null 2>&1 ); then
        verdict="FAIL"; evidence="ROOT-MANIFEST hash mismatch: $file"; break
      fi
    else
      if ! grep -q '^root-manifest-verified: yes$' "$BUNDLE/operator-complete.txt" 2>/dev/null; then
        verdict="UNCHECKABLE"
        evidence="cannot read $file and no root verification attestation"
        break
      fi
    fi
  done < "$BUNDLE/ROOT-MANIFEST.txt"
  emit V-12 "$verdict" "archive_ok $evidence"
}

check_canary() {
  if ! command -v python3 >/dev/null 2>&1; then
    emit V-13 UNCHECKABLE "python3 not found for canary state parse"
    return
  fi
  local out
  out="$(python3 - "$CANARY_STATE" "$CANARY_MAX_AGE" <<'PYEOF' 2>/dev/null
import json, sys
from datetime import datetime, timezone
path, max_age = sys.argv[1], int(sys.argv[2])
try:
    with open(path) as f:
        d = json.load(f)
except Exception as e:
    print(f"UNCHECKABLE canary state unreadable: {e.__class__.__name__}")
    sys.exit(0)
try:
    status = d.get("status")
    ts = datetime.fromisoformat(str(d.get("completed_at_utc")).replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - ts).total_seconds()
except Exception as e:
    print(f"UNCHECKABLE canary state unparseable: {e.__class__.__name__}")
    sys.exit(0)
if status != "success":
    print(f"FAIL canary status={status}")
elif age > max_age:
    print(f"UNCHECKABLE canary tick stale ({int(age)}s > {max_age}s)")
else:
    print(f"OK canary green, tick age {int(age)}s")
PYEOF
)"
  if [ -z "$out" ]; then
    emit V-13 UNCHECKABLE "canary probe produced no output"
  else
    emit V-13 "${out%% *}" "${out#* }"
  fi
}

check_persistence() {
  # A positive finding outranks a later probe failure: once any scan surface
  # has produced a QA hit, the verdict is PRESENT even if another probe then
  # errors — a broken probe must never launder a known-surviving launcher
  # into UNCHECKABLE. UNCHECKABLE is only for "no hit found AND at least one
  # surface could not be scanned"; ABSENT requires every surface scanned clean.
  local hits="" uncheckable="" out rc
  # claude crontab
  out="$(crontab -l 2>&1)"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    printf '%s\n' "$out" | grep -Eiq 'qa[-_]?(register|webhook|dispatch)|spec-kitty-qa' \
      && hits="$hits crontab"
  elif ! printf '%s\n' "$out" | grep -qi 'no crontab'; then
    uncheckable="$uncheckable crontab(rc=$rc)"
  fi
  # systemd user units
  out="$(systemctl --user list-unit-files --no-legend --no-pager 2>/dev/null)"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    uncheckable="$uncheckable systemctl(rc=$rc)"
  else
    printf '%s\n' "$out" | grep -Eiq 'qa[-_]?(register|webhook|dispatch)|spec-kitty-qa' \
      && hits="$hits systemd-user"
  fi
  # launcher scripts in ~claude
  if [ -d "$CLAUDE_HOME" ] && [ -r "$CLAUDE_HOME" ] && [ -x "$CLAUDE_HOME" ]; then
    out="$(find "$CLAUDE_HOME" -maxdepth 1 -name '*.sh' -exec grep -l 'qa_dispatch_webhook' {} + 2>/dev/null)"
    [ -n "$out" ] && hits="$hits launcher:$out"
  else
    uncheckable="$uncheckable claude-home-not-traversable"
  fi
  if [ -n "$hits" ]; then
    emit V-15 PRESENT "QA launcher persistence found:$hits"
  elif [ -n "$uncheckable" ]; then
    emit V-15 UNCHECKABLE "probe failure(s):$uncheckable"
  else
    emit V-15 ABSENT "no QA launcher in crontab, systemd user units, or ~claude scripts"
  fi
}

# --- main --------------------------------------------------------------------
MODE="${1:-}"
case "$MODE" in
  --external) check_external ;;
  "")         check_office2 ;;
  *) echo "usage: $0 [--external]" >&2; exit 2 ;;
esac

if [ "$FAILS" -eq 0 ] && [ "$UNCHECKABLES" -eq 0 ]; then
  printf 'verify: PASS (all checks conclusive-clean)\n'
  exit 0
fi
printf 'verify: NOT PASSED (%d failing, %d uncheckable)\n' "$FAILS" "$UNCHECKABLES"
exit 1
