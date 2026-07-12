#!/usr/bin/env bash
#
# kimi-session-watchdog.sh
# External mechanical guard against silent/hung Kimi sessions.
# Monitors active Kimi semaphores and alerts the pilot if the agent
# has not sent a heartbeat within 180 seconds.
#
# Run manually:
#   bash scripts/kimi-session-watchdog.sh
# Or via launchd (see exocortex/launchd/com.iwe.kimi-watchdog.plist).

set -euo pipefail

IWE_ROOT="${IWE_ROOT:-$HOME/IWE}"
SESSION_DIR="$IWE_ROOT/.iwe-runtime/sessions"
SILENCE_THRESHOLD_S=180
CHECK_INTERVAL_S=60

now_epoch() { date +%s; }

notify_pilot() {
  local session_file="$1"
  local age="$2"
  local wp task
  wp="$(grep "^wp: " "$session_file" | cut -d' ' -f2- || echo "unknown")"
  task="$(grep "^task: " "$session_file" | cut -d' ' -f2- || echo "unknown")"

  local msg="Kimi молчит ${age}s в WP:${wp}. Возможно, зависание."

  # macOS notification center
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display notification \"$msg\" with title \"IWE Kimi Watchdog\" subtitle \"$task\" sound name \"Purr\"" 2>/dev/null || true
  fi

  # Also append to a local alert log
  echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") | $msg | $session_file" >> "$IWE_ROOT/.iwe-runtime/logs/kimi-watchdog.log"
}

latest_heartbeat_age() {
  local session_file="$1"
  local last_hb
  last_hb="$(grep "^heartbeat_at: " "$session_file" | tail -1 | cut -d' ' -f2- || true)"
  if [ -z "$last_hb" ]; then
    # No heartbeat yet: use session open time
    last_hb="$(grep "^opened_at: " "$session_file" | cut -d' ' -f2- || true)"
  fi
  if [ -z "$last_hb" ]; then
    echo "9999"
    return
  fi
  local hb_epoch now
  # heartbeat_at пишется в UTC с суффиксом Z. macOS date -j -f интерпретирует
  # литеральный Z как часть формата и парсит время как локальное, завышая возраст
  # на смещение часового пояса. Убираем Z и парсим как UTC (-u).
  hb_epoch="$(date -j -u -f "%Y-%m-%dT%H:%M:%S" "${last_hb%Z}" +%s 2>/dev/null || date -d "$last_hb" +%s 2>/dev/null || echo "0")"
  now="$(now_epoch)"
  echo "$((now - hb_epoch))"
}

mkdir -p "$IWE_ROOT/.iwe-runtime/logs"

while true; do
  for session in "$SESSION_DIR"/kimi-*.open; do
    [ -f "$session" ] || continue
    age="$(latest_heartbeat_age "$session")"
    if [ "$age" -gt "$SILENCE_THRESHOLD_S" ]; then
      notify_pilot "$session" "$age"
    fi
  done
  sleep "$CHECK_INTERVAL_S"
done
