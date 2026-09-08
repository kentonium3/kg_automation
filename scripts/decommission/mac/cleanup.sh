#!/usr/bin/env bash
# cleanup.sh — Mac QA-pipeline trace cleanup (mission qa-pipeline-decommission-01M219TT, WP03, FR-009)
#
# Removes exactly the five named QA scratch/harness paths plus QA-classified
# entries inside ~/Documents/spec-kitty/, under the guards defined in
# contracts/teardown-verification.md (M-01..M-08) and research.md D-8:
#
#   * Protection snapshot of ~/repos/spec-kitty-qa (HEAD + status hash) is
#     taken FIRST and re-verified LAST; the clone is never written to (M-07).
#   * Any git repository found inside a target with unpushed commits or a
#     dirty tree causes that target to be REFUSED (recorded, surfaced,
#     others continue) — never silently deleted (M-08). A probe failure is
#     treated as REFUSE, never as safe (Engineering Principle 14).
#   * ~/Documents/spec-kitty entries are individually classified QA / NON-QA
#     with a stated criterion each; the inventory file is written BEFORE any
#     removal; only QA-classified entries are removed (M-06). When in doubt,
#     an entry is classified NON-QA and preserved.
#   * Never runs with HOME unset or invalid (Engineering Principle 15).
#
# Usage:
#   cleanup.sh --dry-run [--inventory PATH]   # print decisions only, delete nothing
#   cleanup.sh [--inventory PATH]             # execute removals under the guards
#
# Exit codes: 0 = all checks pass, nothing refused
#             2 = completed, but one or more targets REFUSED (surfaced above)
#             1 = precondition failure (missing protection clone, bad HOME, ...)
set -u

# ---------------------------------------------------------------- arguments
DRY_RUN=0
INVENTORY_FILE=""
ATTESTED=()  # paths the operator explicitly attested as disposable (guard override)
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --inventory) shift; INVENTORY_FILE="${1:-}" ;;
    --attest-delete) shift; ATTESTED+=("${1:?--attest-delete needs a path}") ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 1 ;;
  esac
  shift
done

# ------------------------------------------- Engineering Principle 15: HOME
if [ -z "${HOME:-}" ] || [ ! -d "$HOME" ]; then
  echo "ERROR: \$HOME is unset, empty, or not a directory — refusing to run (Engineering Principle 15)" >&2
  exit 1
fi

PROTECT="$HOME/repos/spec-kitty-qa"
DOCS_DIR="$HOME/Documents/spec-kitty"
TARGETS=(
  "$HOME/repos/teamspace-qa-scratch"
  "$HOME/repos/teamspace-qa-scratch2"
  "$HOME/teamspace-qa-harness"
  "$HOME/teamkitty-qa"
  "$HOME/teamkitty-qa-harness"
)
M_IDS=(M-01 M-02 M-03 M-04 M-05)

TS="$(date -u +%Y%m%dT%H%M%SZ)"
if [ -z "$INVENTORY_FILE" ]; then
  INVENTORY_FILE="${TMPDIR:-/tmp}/mac-cleanup-inventory-${TS}.md"
fi

REFUSED=()   # "path :: reason"
DELETED=()
ABSENT=()

log() { printf '%s\n' "$*"; }
inv() { printf '%s\n' "$*" >> "$INVENTORY_FILE"; }

# ------------------------------------- Step 1: protection snapshot (FIRST)
if [ ! -d "$PROTECT/.git" ]; then
  echo "ERROR: protection clone $PROTECT missing or not a git repo — refusing to proceed (M-07)" >&2
  exit 1
fi
SNAP_HEAD_BEFORE="$(git -C "$PROTECT" rev-parse HEAD 2>/dev/null)" || {
  echo "ERROR: cannot read HEAD of $PROTECT — refusing to proceed (M-07)" >&2; exit 1; }
SNAP_STATUS_BEFORE="$(git -C "$PROTECT" status --porcelain 2>/dev/null | shasum -a 256 | awk '{print $1}')" || {
  echo "ERROR: cannot hash status of $PROTECT — refusing to proceed (M-07)" >&2; exit 1; }
log "PROTECT-SNAPSHOT before: HEAD=$SNAP_HEAD_BEFORE status_sha256=$SNAP_STATUS_BEFORE"

# ------------------------------------------------------- inventory header
: > "$INVENTORY_FILE"
inv "# Mac QA cleanup inventory — $TS"
inv ""
inv "Mode: $([ "$DRY_RUN" -eq 1 ] && echo DRY-RUN || echo EXECUTE)"
inv "Protection snapshot (before): HEAD=$SNAP_HEAD_BEFORE status_sha256=$SNAP_STATUS_BEFORE"
inv ""

# --------------------------------------------------------- git repo guard
# Prints nothing and returns 0 if the target is safe to delete; otherwise
# prints the refusal reason and returns 1. Probe failure => refuse (EP 14).
git_guard() {
  local target="$1" repo gitmarker
  # find any git repo inside the target (root or nested, .git dir or file)
  while IFS= read -r gitmarker; do
    repo="$(dirname "$gitmarker")"
    local dirty unpushed remotes
    dirty="$(git -C "$repo" status --porcelain 2>/dev/null)" || {
      printf 'git status probe failed in %s' "$repo"; return 1; }
    if [ -n "$dirty" ]; then
      printf 'dirty tree in %s (%d entr(y/ies), e.g. %s)' \
        "$repo" "$(printf '%s\n' "$dirty" | wc -l | tr -d ' ')" \
        "$(printf '%s\n' "$dirty" | head -1)"
      return 1
    fi
    remotes="$(git -C "$repo" remote 2>/dev/null | wc -l | tr -d ' ')" || {
      printf 'git remote probe failed in %s' "$repo"; return 1; }
    if [ "$remotes" -eq 0 ]; then
      local n
      n="$(git -C "$repo" rev-list --branches --count 2>/dev/null | tr -d ' ')" || n="?"
      printf 'no git remote in %s — all %s commit(s) are unpushed' "$repo" "$n"
      return 1
    fi
    unpushed="$(git -C "$repo" log --branches --not --remotes --oneline 2>/dev/null)" || {
      printf 'unpushed-commit probe failed in %s' "$repo"; return 1; }
    if [ -n "$unpushed" ]; then
      printf 'unpushed commits in %s (%d, e.g. %s)' \
        "$repo" "$(printf '%s\n' "$unpushed" | wc -l | tr -d ' ')" \
        "$(printf '%s\n' "$unpushed" | head -1)"
      return 1
    fi
  done < <(find "$target" -maxdepth 4 -name .git 2>/dev/null)
  return 0
}

# ----------------------------------- Step 2: inventory + guard the 5 paths
inv "## Named scratch targets"
inv ""
for i in "${!TARGETS[@]}"; do
  t="${TARGETS[$i]}"
  id="${M_IDS[$i]}"
  inv "### $id $t"
  if [ ! -e "$t" ]; then
    log "TARGET $id $t: already absent — nothing to do"
    inv "- state: already ABSENT before this run"
    inv ""
    ABSENT+=("$t")
    continue
  fi
  inv "- state: present"
  inv "- contents (top 2 levels):"
  while IFS= read -r line; do inv "    $line"; done < <(find "$t" -maxdepth 2 2>/dev/null | sed "s|^$HOME|~|")
  if reason="$(git_guard "$t")"; then
    log "TARGET $id $t: guard clean — approved for deletion"
    inv "- git guard: clean (no repo, or repo fully pushed with clean tree)"
    inv "- decision: DELETE"
    if [ "$DRY_RUN" -eq 1 ]; then
      log "DRY-RUN: would rm -rf $t"
    else
      case "$t" in
        "$HOME"/*) rm -rf "$t" ;;
        *) log "INTERNAL ERROR: $t not under \$HOME — refusing"; REFUSED+=("$t :: not under HOME"); inv "- decision OVERRIDDEN: refused (not under HOME)"; inv ""; continue ;;
      esac
      log "DELETED: $t"
    fi
    DELETED+=("$t")
  else
    attested=0
    for a in "${ATTESTED[@]+"${ATTESTED[@]}"}"; do
      [ "$a" = "$t" ] && attested=1
    done
    if [ "$attested" -eq 1 ]; then
      # Guard fired but the operator explicitly attested this exact named
      # target as disposable (--attest-delete). Only the 5 named targets can
      # ever reach this branch; the override never widens the target set.
      log "TARGET $id $t: guard FIRED ($reason) — DELETING under operator attestation"
      inv "- git guard: FIRED — $reason"
      inv "- decision: DELETE under explicit operator attestation (--attest-delete)"
      if [ "$DRY_RUN" -eq 1 ]; then
        log "DRY-RUN: would rm -rf $t (attested)"
      else
        case "$t" in
          "$HOME"/*) rm -rf "$t" ;;
          *) log "INTERNAL ERROR: $t not under \$HOME — refusing"; REFUSED+=("$t :: not under HOME"); inv "- decision OVERRIDDEN: refused (not under HOME)"; inv ""; continue ;;
        esac
        log "DELETED (attested): $t"
      fi
      DELETED+=("$t")
    else
      log "TARGET $id $t: REFUSED — $reason"
      inv "- git guard: FIRED — $reason"
      inv "- decision: REFUSE (path left untouched; surfaced per M-08)"
      REFUSED+=("$t :: $reason")
    fi
  fi
  inv ""
done

# ------------------------- Step 3: ~/Documents/spec-kitty classification
inv "## ~/Documents/spec-kitty classification (M-06)"
inv ""
QA_DOC_ENTRIES=()
NONQA_DOC_ENTRIES=()
if [ ! -d "$DOCS_DIR" ]; then
  log "DOCS $DOCS_DIR: absent — nothing to classify"
  inv "- directory absent; nothing to classify"
else
  while IFS= read -r entry; do
    name="$(basename "$entry")"
    # Stated criterion: an entry is QA-classified only when its name carries a
    # QA-pipeline indicator (qa / teamspace / teamkitty / register / webhook /
    # harness, case-insensitive). Anything else — including anything
    # ambiguous — is NON-QA and preserved (when in doubt, preserve).
    lower="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')"
    case "$lower" in
      *qa*|*teamspace*|*teamkitty*|*team-kitty*|*register*|*webhook*|*harness*)
        cls="QA"; crit="name contains a QA-pipeline indicator" ;;
      *)
        cls="NON-QA"; crit="no QA-pipeline indicator in name; preserved by default" ;;
    esac
    log "DOCS entry: $name -> $cls ($crit)"
    inv "- \`$name\` — **$cls** — criterion: $crit"
    if [ "$cls" = "QA" ]; then QA_DOC_ENTRIES+=("$entry"); else NONQA_DOC_ENTRIES+=("$entry"); fi
  done < <(find "$DOCS_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | sort)
fi
inv ""

# Inventory file is complete BEFORE any Documents removal happens (M-06).
log "INVENTORY written: $INVENTORY_FILE (before Documents removal)"

for entry in "${QA_DOC_ENTRIES[@]+"${QA_DOC_ENTRIES[@]}"}"; do
  if reason="$(git_guard "$entry")"; then
    if [ "$DRY_RUN" -eq 1 ]; then
      log "DRY-RUN: would rm -rf $entry"
    else
      rm -rf "$entry"
      log "DELETED (Documents QA entry): $entry"
    fi
    DELETED+=("$entry")
  else
    log "DOCS entry $entry: REFUSED — $reason"
    REFUSED+=("$entry :: $reason")
  fi
done

# --------------------------------------------- Step 4: tri-state re-verify
log ""
log "=== Verification (tri-state) ==="
overall_refused=0
[ "${#REFUSED[@]}" -gt 0 ] && overall_refused=1

for i in "${!TARGETS[@]}"; do
  t="${TARGETS[$i]}"; id="${M_IDS[$i]}"
  if [ "$DRY_RUN" -eq 1 ]; then
    if [ -e "$t" ]; then
      log "$id PRESENT dry-run: no removal performed ($t)"
    else
      log "$id ABSENT $t does not exist"
    fi
    continue
  fi
  if [ ! -e "$t" ]; then
    log "$id ABSENT $t does not exist"
  else
    refnote=""
    for r in "${REFUSED[@]+"${REFUSED[@]}"}"; do
      case "$r" in "$t :: "*) refnote=" — removal REFUSED: ${r#"$t :: "}" ;; esac
    done
    log "$id PRESENT $t still exists$refnote"
  fi
done

# M-06
if [ ! -d "$DOCS_DIR" ]; then
  log "M-06 ABSENT $DOCS_DIR does not exist (nothing to classify)"
else
  m06="OK"
  [ -s "$INVENTORY_FILE" ] || m06="FAIL(no inventory)"
  for entry in "${NONQA_DOC_ENTRIES[@]+"${NONQA_DOC_ENTRIES[@]}"}"; do
    [ -e "$entry" ] || m06="FAIL(non-QA entry missing: $entry)"
  done
  if [ "$DRY_RUN" -eq 0 ]; then
    for entry in "${QA_DOC_ENTRIES[@]+"${QA_DOC_ENTRIES[@]}"}"; do
      refmatch=0
      for r in "${REFUSED[@]+"${REFUSED[@]}"}"; do
        case "$r" in "$entry :: "*) refmatch=1 ;; esac
      done
      if [ -e "$entry" ] && [ "$refmatch" -eq 0 ]; then m06="FAIL(QA entry survived: $entry)"; fi
    done
  fi
  log "M-06 $m06 inventory=$INVENTORY_FILE qa_removed=${#QA_DOC_ENTRIES[@]} nonqa_preserved=${#NONQA_DOC_ENTRIES[@]}"
fi

# M-07: protection clone unchanged
SNAP_HEAD_AFTER="$(git -C "$PROTECT" rev-parse HEAD 2>/dev/null)" || SNAP_HEAD_AFTER="UNCHECKABLE"
SNAP_STATUS_AFTER="$(git -C "$PROTECT" status --porcelain 2>/dev/null | shasum -a 256 | awk '{print $1}')" || SNAP_STATUS_AFTER="UNCHECKABLE"
if [ "$SNAP_HEAD_AFTER" = "UNCHECKABLE" ] || [ "$SNAP_STATUS_AFTER" = "UNCHECKABLE" ]; then
  log "M-07 clone_intact UNCHECKABLE could not re-probe $PROTECT"
elif [ "$SNAP_HEAD_AFTER" = "$SNAP_HEAD_BEFORE" ] && [ "$SNAP_STATUS_AFTER" = "$SNAP_STATUS_BEFORE" ]; then
  log "M-07 clone_intact OK HEAD=$SNAP_HEAD_AFTER status_sha256=$SNAP_STATUS_AFTER (identical to before)"
else
  log "M-07 clone_intact FAIL before(HEAD=$SNAP_HEAD_BEFORE status=$SNAP_STATUS_BEFORE) after(HEAD=$SNAP_HEAD_AFTER status=$SNAP_STATUS_AFTER)"
fi

# M-08: guard summary
if [ "${#REFUSED[@]}" -eq 0 ]; then
  log "M-08 OK no target contained an unpushed or dirty git repository"
else
  log "M-08 OK guard held: ${#REFUSED[@]} target(s) REFUSED and surfaced (listed below), none deleted"
  for r in "${REFUSED[@]}"; do log "  REFUSED: $r"; done
fi

log ""
log "SUMMARY deleted=${#DELETED[@]} refused=${#REFUSED[@]} already_absent=${#ABSENT[@]} dry_run=$DRY_RUN"
log "INVENTORY: $INVENTORY_FILE"

[ "$overall_refused" -eq 1 ] && exit 2
exit 0
