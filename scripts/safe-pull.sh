#!/usr/bin/env bash
# safe-pull.sh — drop-in replacement for `git pull --rebase --quiet`.
# Prevents silent loss of local commits when upstream (e.g., auto-sync)
# already contains an equivalent patch.
#
# Usage:
#   bash ~/IWE/scripts/safe-pull.sh [--push] [-C <repo>]
#   git config --global alias.safe-pull '!bash ~/IWE/scripts/safe-pull.sh'

set -euo pipefail

PUSH_IF_AHEAD=0

# --- helpers ---
fail() { echo "safe-pull: $1" >&2; exit "${2:-1}"; }
usage() {
  cat <<EOF
Usage: safe-pull.sh [--push] [-C <repo>]
  --push   If only local commits are ahead, run git push.
  -C       Path to repository (default: current directory).
EOF
}

# --- args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --push) PUSH_IF_AHEAD=1; shift ;;
    -C) cd "$2" || fail "cannot cd to $2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*) fail "unknown option: $1" ;;
    *) fail "unexpected argument: $1" ;;
  esac
done

# --- repo sanity checks ---
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  fail "not inside a git repository"
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" = "HEAD" ]; then
  fail "detached HEAD; safe-pull only works on a branch"
fi

if ! git diff --quiet --ignore-submodules || ! git diff --cached --quiet --ignore-submodules; then
  fail "working tree or index is dirty; commit or stash first"
fi

# --- upstream detection ---
UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)
if [ -z "${UPSTREAM:-}" ]; then
  if git show-ref --verify --quiet refs/remotes/origin/main; then
    UPSTREAM=origin/main
  elif git show-ref --verify --quiet refs/remotes/origin/master; then
    UPSTREAM=origin/master
  else
    fail "no tracked upstream and no origin/main or origin/master"
  fi
fi

REMOTE=${UPSTREAM%%/*}
git fetch --quiet "$REMOTE"

# --- compare branches ---
AHEAD=$(git rev-list --count "$UPSTREAM"..HEAD 2>/dev/null || echo 0)
BEHIND=$(git rev-list --count HEAD.."$UPSTREAM" 2>/dev/null || echo 0)

if [ "$AHEAD" -eq 0 ] && [ "$BEHIND" -eq 0 ]; then
  echo "Already up to date with $UPSTREAM."
  exit 0
fi

if [ "$AHEAD" -eq 0 ] && [ "$BEHIND" -gt 0 ]; then
  echo "Only upstream is ahead ($BEHIND commits). Fast-forwarding..."
  git merge --ff-only "$UPSTREAM"
  exit 0
fi

if [ "$BEHIND" -eq 0 ] && [ "$AHEAD" -gt 0 ]; then
  echo "Only local is ahead ($AHEAD commits). Nothing to pull."
  if [ "$PUSH_IF_AHEAD" -eq 1 ]; then
    git push
  else
    echo "Run 'git push' or call safe-pull with --push."
  fi
  exit 0
fi

# --- diverged: both sides have commits ---
echo "Diverged from $UPSTREAM:"
echo "  upstream ahead by $BEHIND commit(s)"
echo "  local    ahead by $AHEAD commit(s)"
echo ""
echo "Upstream commits:"
git log --oneline HEAD.."$UPSTREAM"
echo ""
echo "Local commits:"
git log --cherry-mark --oneline --right-only "$UPSTREAM"...HEAD

# Detect commits that rebase would silently drop (same patch already upstream).
ALREADY_UPSTREAM=$(git cherry "$UPSTREAM" HEAD | grep -c '^-' || true)
if [ "$ALREADY_UPSTREAM" -gt 0 ]; then
  echo ""
  echo "WARNING: $ALREADY_UPSTREAM local commit(s) already have an equivalent patch in $UPSTREAM."
  echo "A plain 'git rebase' would DROP them. Aborting."
  echo "Review with: git log --cherry-mark --oneline --right-only $UPSTREAM...HEAD"
  exit 2
fi

# Require explicit confirmation before rebasing.
if [ -t 0 ] && [ -t 1 ]; then
  echo ""
  read -r -p "Rebase $BRANCH onto $UPSTREAM? [y/N] " ANSWER
  case "$ANSWER" in
    [yY]*) ;;
    *) echo "Aborted."; exit 2 ;;
  esac
else
  echo ""
  echo "Diverged and not running interactively. Aborting rebase."
  exit 2
fi

# --- record original patch-ids before rebase ---
ORIG_PIDS=()
while IFS= read -r SHA; do
  [ -n "$SHA" ] || continue
  PID=$(git diff-tree -p "$SHA" | git patch-id --stable | awk '{print $1}')
  ORIG_PIDS+=("$PID")
done < <(git rev-list --reverse "$UPSTREAM"..HEAD)

if [ "${#ORIG_PIDS[@]}" -eq 0 ]; then
  fail "failed to capture local patch-ids"
fi

# --- rebase ---
echo "Rebasing $BRANCH onto $UPSTREAM..."
if ! git rebase "$UPSTREAM"; then
  echo ""
  echo "Rebase stopped (conflict or error). Resolve manually or run:"
  echo "  git rebase --abort"
  exit 3
fi

# --- verify no local patch was lost ---
NEW_PIDS=()
while IFS= read -r SHA; do
  [ -n "$SHA" ] || continue
  PID=$(git diff-tree -p "$SHA" | git patch-id --stable | awk '{print $1}')
  NEW_PIDS+=("$PID")
done < <(git rev-list --reverse "$UPSTREAM"..HEAD)

MISSING=0
for OPID in "${ORIG_PIDS[@]}"; do
  FOUND=0
  for NPID in "${NEW_PIDS[@]}"; do
    if [ "$OPID" = "$NPID" ]; then
      FOUND=1
      break
    fi
  done
  if [ "$FOUND" -eq 0 ]; then
    echo "ERROR: local patch $OPID was lost during rebase." >&2
    MISSING=1
  fi
done

if [ "$MISSING" -ne 0 ]; then
  echo ""
  echo "Rebase dropped local commits. Recover with:"
  echo "  git rebase --abort"
  echo "or inspect the reflog:"
  echo "  git reflog $BRANCH"
  exit 4
fi

echo "Rebase complete. Verified ${#ORIG_PIDS[@]} local patch(es) preserved."
exit 0
