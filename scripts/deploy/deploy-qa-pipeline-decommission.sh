#!/usr/bin/env bash
# deploy-qa-pipeline-decommission.sh — manifest entrypoint for the office2 QA
# pipeline teardown (mission qa-pipeline-decommission-01M219TT, #970, WP01/T004).
#
# The manifest schema requires the entrypoint to live under scripts/deploy/;
# the real teardown logic lives in scripts/decommission/office2/ (the WP's
# authoritative surface). This wrapper:
#   --dry-run  delegates to teardown.sh --dry-run (prints the action list)
#   --apply    copies the three decommission scripts into the archive bundle
#              (so the operator has stable copies at a path that survives the
#              repo checkout's evolution), then runs teardown.sh --apply
#
# The manifest's verification.post is the completion gate: it fails every
# felix-deployer tick until Kent has run operator-root-steps.sh (root half)
# AND verify.sh exits 0 — only then is the deploy recorded applied and the
# deferred rebaseline (listening-ports.txt, docker-images.txt) stamped.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC_DIR="$REPO_ROOT/scripts/decommission/office2"
BUNDLE="${QA_TEARDOWN_BUNDLE:-/data/services/host-state/decommission/qa-pipeline-2026-09-08}"

MODE="${1:-}"
case "$MODE" in
  --dry-run|--apply) ;;
  *) echo "usage: $0 --dry-run|--apply" >&2; exit 2 ;;
esac

for f in teardown.sh operator-root-steps.sh verify.sh; do
  [ -f "$SRC_DIR/$f" ] || { echo "missing $SRC_DIR/$f" >&2; exit 1; }
done

if [ "$MODE" = "--dry-run" ]; then
  echo "would: mkdir -p $BUNDLE"
  echo "would: copy teardown.sh operator-root-steps.sh verify.sh -> $BUNDLE/"
  bash "$SRC_DIR/teardown.sh" --dry-run
  echo "would: leave verification.post gating on operator-complete.txt + verify.sh"
  exit 0
fi

mkdir -p "$BUNDLE"
for f in teardown.sh operator-root-steps.sh verify.sh; do
  cp -p "$SRC_DIR/$f" "$BUNDLE/$f"
done
echo "copied decommission scripts into $BUNDLE"

exec bash "$SRC_DIR/teardown.sh" --apply
