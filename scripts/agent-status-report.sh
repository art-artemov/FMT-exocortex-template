#!/bin/bash
# agent-status-report.sh — РП-395 Ф3 fail-safe writer.
#
# НАЗНАЧЕНИЕ: детерминированная запись runtime-статуса агента (Claude/Kimi) в
# платформенный реестр indicators.agent_status, КОГДА агент-LLM не отчитался сам.
#
# Это FAIL-SAFE, не primary. Primary write-path = поведенческий вызов MCP-инструмента
# agent_status_update самим агентом (см. Agent Core в CLAUDE.md/AGENTS.md). Этот helper
# пишет напрямую в БД (degraded-путь) — осознанное исключение для надёжности, т.к. OAuth
# у Claude/Kimi не рефрешится как у Hermes-runtime, а dashboard должен видеть статус даже
# если LLM забыл позвать инструмент (fault-profile ~15-20%).
#
# Вызывается: Claude SessionStart/SessionEnd-хук (settings) + kimi-peer-adapter.sh (Kimi headless).
# Пишет под user_id пилота (тот же Ory sub, что и MCP-путь) — строки консистентны.
#
# КОНТРАКТ STALENESS (cold-review H1/R1): SessionEnd/idle не гарантирован при крэше/kill.
# Поэтому читатель (dashboard, agent_status_list) ОБЯЗАН трактовать `working`/`peer-session`
# с устаревшим updated_at (> ~15 мин) как stale.
#
# Использование:
#   agent-status-report.sh [--session-id <id>] <agent> <status> [task] [files-csv]
#   agent-status-report.sh claude-code working "WP-395 Ф3" "src/a.ts,src/b.ts"
#   agent-status-report.sh --session-id 20260604-s1 kimi idle
#   agent-status-report.sh --gc                    # one-time stale cleanup (client-side)
#
# WP-398 Ф2: --session-id <id> (default 'default') — многосессионный режим.
# Без флага = 'default' (backward-compat, одиночная сессия). Флаг можно ставить в любом
# месте до позиционных аргументов; парсится отдельно от <agent>/<status>/[task]/[files].
#
# Никогда не валит вызвавший процесс: всегда exit 0, ошибки тихо в stderr.

GC_MODE=""
SESSION_ID="default"
POSITIONAL=()
while [ $# -gt 0 ]; do
  case "$1" in
    --session-id) SESSION_ID="${2:-default}"; shift 2 ;;
    --gc)         GC_MODE="1"; shift ;;
    *)            POSITIONAL+=("$1"); shift ;;
  esac
done
set -- "${POSITIONAL[@]+"${POSITIONAL[@]}"}"

AGENT="${1:-}"
STATUS="${2:-idle}"
TASK="${3:-}"
FILES_CSV="${4:-}"
[ -z "$SESSION_ID" ] && SESSION_ID="default"

SECRETS_DIR="${IWE_SECRETS_DIR:-$HOME/IWE/.secrets}"
NEON_ENV="$SECRETS_DIR/neon-urls.env"
UID_FILE="$SECRETS_DIR/pilot-user-id"

fail() { echo "agent-status-report: $1" >&2; exit 0; }   # fail-safe: never break caller

# В GC mode agent не требуется — skip validation
if [ -z "$GC_MODE" ]; then
  [ -z "$AGENT" ] && fail "agent required (claude-code|kimi|hermes)"
  # Enum синхронизирован с AGENT_STATUS_VALUES (gateway-mcp/src/agent-status.ts).
  # При расширении enum в TS — обновить и здесь.
  case "$STATUS" in idle|working|peer-session|blocked) ;; *) fail "bad status '$STATUS'";; esac
fi

# user_id пилота (Ory sub) — из секрета или env. tr -d: устойчивость к случайному \n в файле.
USER_ID="${IWE_PILOT_USER_ID:-}"
[ -z "$USER_ID" ] && [ -f "$UID_FILE" ] && USER_ID="$(tr -d '[:space:]' < "$UID_FILE")"
[ -z "$USER_ID" ] && fail "pilot user_id not found ($UID_FILE)"

# DSN базы indicators
INDICATORS_URL="${INDICATORS_URL:-}"
if [ -z "$INDICATORS_URL" ] && [ -f "$NEON_ENV" ]; then
  # shellcheck disable=SC1090
  set -a; . "$NEON_ENV"; set +a
fi
[ -z "${INDICATORS_URL:-}" ] && fail "INDICATORS_URL not found ($NEON_ENV)"

command -v psql >/dev/null 2>&1 || fail "psql not installed"

# === GC mode: one-time stale cleanup (client-side fallback until server-side GC) ===
if [ -n "$GC_MODE" ]; then
  psql "$INDICATORS_URL" -v ON_ERROR_STOP=1 -v uid="$USER_ID" \
    >/dev/null 2>&1 <<'SQL' || fail "gc failed"
UPDATE agent_status
SET status = 'idle'
WHERE user_id = :'uid'::uuid
  AND status = 'working'
  AND updated_at < now() - interval '4 hours';
UPDATE agent_status
SET status = 'idle'
WHERE user_id = :'uid'::uuid
  AND status = 'peer-session'
  AND updated_at < now() - interval '2 hours';
UPDATE agent_status
SET status = 'idle'
WHERE user_id = :'uid'::uuid
  AND status = 'blocked'
  AND updated_at < now() - interval '24 hours';
SQL
  exit 0
fi

# UPSERT (зеркалит gateway-mcp/src/agent-status.ts). psql :'var' квотирование = защита от инъекций.
# files: CSV → text[] через string_to_array; пустое → '{}'.
psql "$INDICATORS_URL" -v ON_ERROR_STOP=1 \
  -v uid="$USER_ID" -v ag="$AGENT" -v st="$STATUS" -v tk="$TASK" -v fl="$FILES_CSV" -v sid="$SESSION_ID" \
  >/dev/null 2>&1 <<'SQL' || fail "db write failed"
INSERT INTO agent_status (user_id, agent, session_id, status, task, files, updated_at)
VALUES (
  :'uid'::uuid,
  :'ag',
  :'sid',
  :'st',
  NULLIF(:'tk', ''),
  CASE WHEN :'fl' = '' THEN '{}'::text[] ELSE string_to_array(:'fl', ',') END,
  now()
)
ON CONFLICT (user_id, agent, session_id) DO UPDATE SET
  status = EXCLUDED.status,
  task = EXCLUDED.task,
  files = EXCLUDED.files,
  updated_at = now();
SQL

exit 0
