#!/usr/bin/env bash
#
# kimi-auto-heartbeat.sh
# Запускает фоновый heartbeat для активной Kimi standalone-сессии.
# Должен вызываться сразу после session-guard.sh open.
#
# Usage: bash scripts/kimi-auto-heartbeat.sh [--interval 120]

set -euo pipefail

IWE_ROOT="${IWE_ROOT:-$HOME/IWE}"
SESSION_DIR="$IWE_ROOT/.iwe-runtime/sessions"
INTERVAL="${IWE_HEARTBEAT_INTERVAL:-120}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interval) INTERVAL="$2"; shift 2 ;;
    -i)         INTERVAL="$2"; shift 2 ;;
    *)          shift ;;
  esac
done

# Bind to the semaphore referenced by current-kimi.ptr (the canonical active
# session). Fall back to the most recently modified semaphore only if the pointer
# is missing, for backward compatibility.
if [ -f "$SESSION_DIR/current-kimi.ptr" ]; then
  SEM_FILE="$(cat "$SESSION_DIR/current-kimi.ptr")"
else
  SEM_FILE=$(ls -t "$SESSION_DIR/kimi"-*.open 2>/dev/null | head -1 || true)
fi
if [ -z "$SEM_FILE" ] || [ ! -f "$SEM_FILE" ]; then
  echo "ERROR: no active kimi session semaphore found in $SESSION_DIR" >&2
  echo "Run session-guard.sh open first." >&2
  exit 1
fi

PID_FILE="$SESSION_DIR/kimi-heartbeat.pid"
HEARTBEAT_LOG="$IWE_ROOT/.iwe-runtime/logs/kimi-heartbeat.log"

echo "Starting auto-heartbeat for $(basename "$SEM_FILE") every ${INTERVAL}s"
echo "heartbeat_started_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")" >> "$HEARTBEAT_LOG"
echo "heartbeat_sem_file: $SEM_FILE" >> "$HEARTBEAT_LOG"

# Store PID
echo $$ > "$PID_FILE"

heartbeat_loop() {
  while true; do
    if [ ! -f "$SEM_FILE" ]; then
      echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") | semaphore gone, stopping heartbeat" >> "$HEARTBEAT_LOG"
      break
    fi
    # Guard: if current-kimi.ptr points to a different semaphore, a new session
    # has taken over. Stop this heartbeat to avoid leaving the old semaphore stale.
    if [ -f "$SESSION_DIR/current-kimi.ptr" ]; then
      local current_ptr
      current_ptr="$(cat "$SESSION_DIR/current-kimi.ptr")"
      if [ "$current_ptr" != "$SEM_FILE" ]; then
        echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") | current-kimi.ptr switched to $current_ptr, stopping heartbeat for $SEM_FILE" >> "$HEARTBEAT_LOG"
        break
      fi
    fi
    # Write heartbeat directly into the bound semaphore so it never "jumps"
    # to a newer session opened while this process is running.
    {
      echo "heartbeat_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
      echo "heartbeat_pid: $$"
    } >> "$SEM_FILE"
    sleep "$INTERVAL"
  done
}

heartbeat_loop
rm -f "$PID_FILE"
echo "heartbeat_stopped_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")" >> "$HEARTBEAT_LOG"
