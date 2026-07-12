#!/usr/bin/env bash
#
# agent-heartbeat.sh
# Update a heartbeat timestamp in the active session semaphore.
# Agents must call this at least every 180 seconds during long operations
# to prove the session is not stuck.
#
# Usage: bash scripts/agent-heartbeat.sh [--agent kimi|claude-code|hermes]

set -euo pipefail

IWE_ROOT="${IWE_ROOT:-$HOME/IWE}"
SESSION_DIR="$IWE_ROOT/.iwe-runtime/sessions"
# Parse args
AGENT="${IWE_AGENT:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) AGENT="$2"; shift 2 ;;
    -a)      AGENT="$2"; shift 2 ;;
    *)       shift ;;
  esac
done

if [ -z "$AGENT" ]; then
  # Try to infer from current session pointer
  if [ -f "$SESSION_DIR/current-kimi.ptr" ]; then
    AGENT="kimi"
  elif [ -f "$SESSION_DIR/current-claude-code.ptr" ]; then
    AGENT="claude-code"
  elif [ -f "$SESSION_DIR/current-hermes.ptr" ]; then
    AGENT="hermes"
  else
    echo "ERROR: --agent or IWE_AGENT required" >&2
    exit 1
  fi
fi

PTR_FILE="$SESSION_DIR/current-${AGENT}.ptr"
if [ ! -f "$PTR_FILE" ]; then
  echo "ERROR: no active $AGENT session pointer" >&2
  exit 1
fi

SEM_FILE="$(cat "$PTR_FILE")"
if [ ! -f "$SEM_FILE" ]; then
  echo "ERROR: session semaphore not found: $SEM_FILE" >&2
  exit 1
fi

{
  echo "heartbeat_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "heartbeat_pid: $$"
} >> "$SEM_FILE"
