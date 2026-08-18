#!/bin/bash
# codex-peer-adapter.sh — Codex CLI (ChatGPT) adapter for peer-conversation.sh.
# Sibling of kimi-peer-adapter.sh (same PII/.agentigore/content-filter reuse,
# same exit-code contract) — second peer-agent vendor, issue #296.
#
# Not ported from kimi-peer-adapter.sh in this first cut (parity gap, ok for now):
#   - IWE_PEER_DIFF (session-state diff) — optional feature, default off
#   - IWE_PEER_INLINE (inline files into prompt) — optional feature, default off
#
# Env overrides:
#   CODEX_BIN     — override codex binary path
#   IWE_TEMPLATE  — path to FMT-exocortex-template (default: $HOME/IWE/FMT-exocortex-template)
#   IWE_PEER_LOCK_DIR, IWE_HINDSIGHT_RETAIN — same as kimi-peer-adapter.sh
#
# Exit codes (same contract as kimi-peer-adapter.sh):
#   0 — OK
#   1 — general error (codex not found, args, timeout, empty output)
#   2 — .agentigore filter violation (Python filter error)
#   3 — PII Hard Block
#   4 — --add-dir too large (>100MB or >5000 files)
#   5 — peer session already running (pidfile lock)

set -uo pipefail

IWE_TEMPLATE="${IWE_TEMPLATE:-$HOME/IWE/FMT-exocortex-template}"
TEMPLATE_SCRIPTS="$IWE_TEMPLATE/scripts"

# === Codex binary auto-detect: env override → PATH → VS Code extension (bundled, versioned dir) ===
CODEX_BIN="${CODEX_BIN:-$(command -v codex 2>/dev/null || true)}"
if [ -z "$CODEX_BIN" ]; then
  for base in \
    "$HOME/.vscode/extensions" \
    "$HOME/.vscode-server/extensions" \
    "$HOME/.cursor/extensions"; do
    [ -d "$base" ] || continue
    candidate=$(ls -d "$base"/openai.chatgpt-*/bin/*/codex 2>/dev/null | sort -V | tail -1)
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      CODEX_BIN="$candidate"
      break
    fi
  done
fi

if [ -z "$CODEX_BIN" ] || [ ! -x "$CODEX_BIN" ]; then
  echo "ERROR: codex binary not found. Install the 'ChatGPT' (Codex) VS Code extension or set CODEX_BIN env var." >&2
  echo "  Looked in: PATH, ~/.vscode/extensions/openai.chatgpt-*/bin/*/codex (and .vscode-server/.cursor variants)" >&2
  exit 1
fi

# Auto-source OpenRouter key (hosts without a ChatGPT login route codex
# through OpenRouter, see reference_codex_peer_openrouter_linux.md).
CODEX_USES_OPENROUTER=false
grep -q '^env_key = "OPENROUTER_API_KEY"' "$HOME/.codex/config.toml" 2>/dev/null && CODEX_USES_OPENROUTER=true

if [ -z "${OPENROUTER_API_KEY:-}" ] && [ "$CODEX_USES_OPENROUTER" = true ]; then
  OPENROUTER_KEY_FILE="$HOME/.secrets/openrouter_key.env"
  if [ -f "$OPENROUTER_KEY_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$OPENROUTER_KEY_FILE"
    set +a
  fi
fi

ADD_DIRS=()
MODEL_ARG=()

# WP-516 Ф5: межвендорский whitelist (§0в.1) = {-p, --model, --add-dir}.
# Неизвестный флаг — явная ошибка, не молчаливый игнор: иначе запрошенный
# режим (напр. безопасности) может не примениться незаметно для вызывающего.
# --permission-mode исключён из whitelist: способен ослабить read-only
# гарантию sandbox; claude-адаптер отклоняет его всегда (exit 64).
while [[ $# -gt 0 ]]; do
  case "$1" in
    -p)                shift ;;
    --model)
      [ $# -ge 2 ] || { echo "ERROR: --model requires a value" >&2; exit 1; }
      MODEL_ARG=("--model" "$2"); shift 2 ;;
    --add-dir)
      [ $# -ge 2 ] || { echo "ERROR: --add-dir requires a value" >&2; exit 1; }
      ADD_DIRS+=("$2"); shift 2 ;;
    *)
      echo "ERROR: unknown flag '$1'. Known: -p, --model, --add-dir" >&2
      exit 1
      ;;
  esac
done

if [ ${#MODEL_ARG[@]} -ge 2 ]; then
  case "${MODEL_ARG[1]-}" in
    sonnet|opus|haiku|claude-*) MODEL_ARG=() ;;
  esac
fi

# === Фильтрация --add-dir через .agentigore + PII sanity-check (шаблонные скрипты, read-only reuse) ===

FILTERED_DIRS=()
# `-t template` is BSD/GNU compatible in practice but its exact semantics
# differ (docs/PLATFORM-COMPAT.md) — a fully-qualified template path avoids
# `-t` entirely and is identical on both.
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/codex-peer-XXXXXX")

MERGED_AGENTIGORE="$TMP_ROOT/.agentigore"
: > "$MERGED_AGENTIGORE"
[ -f "$HOME/.iwe/.agentigore" ] && cat "$HOME/.iwe/.agentigore" >> "$MERGED_AGENTIGORE"

for ADD_DIR in "${ADD_DIRS[@]+"${ADD_DIRS[@]}"}"; do
  [ ! -d "$ADD_DIR" ] && continue
  GIT_ROOT=$(git -C "$ADD_DIR" rev-parse --show-toplevel 2>/dev/null || true)
  [ -n "$GIT_ROOT" ] && [ -f "$GIT_ROOT/.agentigore" ] && cat "$GIT_ROOT/.agentigore" >> "$MERGED_AGENTIGORE"
  [ -f "$ADD_DIR/.agentigore" ] && cat "$ADD_DIR/.agentigore" >> "$MERGED_AGENTIGORE"
done

# === Fail-fast на размер ===
for ADD_DIR in "${ADD_DIRS[@]+"${ADD_DIRS[@]}"}"; do
  [ ! -d "$ADD_DIR" ] && continue
  SIZE_MB=$(du -sm "$ADD_DIR" 2>/dev/null | awk '{print $1}')
  FILES=$(find "$ADD_DIR" -type f 2>/dev/null | wc -l | tr -d ' ')
  if [ "${SIZE_MB:-0}" -gt 100 ] || [ "${FILES:-0}" -gt 5000 ]; then
    echo "ABORT: --add-dir $ADD_DIR too large (${SIZE_MB}MB / ${FILES} files; limit 100MB/5000)" >&2
    exit 4
  fi
done

# === Фильтрация через Python fnmatch + PII sanity-check (шаблонный peer-adapter-filter.py) ===
for ADD_DIR in "${ADD_DIRS[@]+"${ADD_DIRS[@]}"}"; do
  [ ! -d "$ADD_DIR" ] && continue
  CLEAN_DIR="$TMP_ROOT/$(basename "$ADD_DIR")"
  mkdir -p "$CLEAN_DIR"

  AGENTIGORE_FILE="$MERGED_AGENTIGORE" SRC_DIR="$ADD_DIR" DST_DIR="$CLEAN_DIR" \
    python3 "$TEMPLATE_SCRIPTS/peer-adapter-filter.py"
  RC=$?
  if [ $RC -eq 3 ]; then
    exit 3
  elif [ $RC -ne 0 ]; then
    echo "ABORT: filter failed with code $RC" >&2
    exit 2
  fi

  FILTERED_DIRS+=("--add-dir" "$CLEAN_DIR")
done

# === Content-filter guard (переиспользуем шаблонную content-filter-map.txt) ===
PROMPT_FILE="$TMP_ROOT/peer-prompt.in"
cat > "$PROMPT_FILE"

CONTENT_FILTER_MAP="$TEMPLATE_SCRIPTS/content-filter-map.txt"
if [ -f "$CONTENT_FILTER_MAP" ] && [ -s "$CONTENT_FILTER_MAP" ]; then
  if python3 "$TEMPLATE_SCRIPTS/content-filter-apply.py" "$CONTENT_FILTER_MAP" \
       < "$PROMPT_FILE" > "$PROMPT_FILE.filtered" 2>/dev/null \
     && [ -s "$PROMPT_FILE.filtered" ]; then
    PROMPT_FILE="$PROMPT_FILE.filtered"
  fi
fi

# === Sanitize surrogate characters before Codex call ===
if python3 - "$PROMPT_FILE" << 'PYEOF'
import sys
try:
    with open(sys.argv[1], 'r', encoding='utf-8') as f:
        f.read()
    sys.exit(0)
except (UnicodeDecodeError, UnicodeError):
    sys.exit(1)
PYEOF
then
    :
else
    python3 - "$PROMPT_FILE" "$PROMPT_FILE.clean" << 'PYEOF'
import codecs, sys
reader = codecs.getreader('utf-8')(open(sys.argv[1], 'rb'), errors='surrogateescape')
text = reader.read()
sanitized = text.encode('utf-8', errors='replace').decode('utf-8')
with open(sys.argv[2], 'w', encoding='utf-8') as f:
    f.write(sanitized)
PYEOF
    PROMPT_FILE="$PROMPT_FILE.clean"
fi

# === Pidfile lock: предотвращаем параллельные/зависшие копии одной peer-сессии ===
CODEX_TASK="$(basename "${ADD_DIRS[0]:-}" 2>/dev/null)"
if [ -z "$CODEX_TASK" ]; then CODEX_TASK="codex-peer-ppid-${PPID:-$$}"; fi
CODEX_SESSION_ID="$CODEX_TASK"

LOCK_DIR="${IWE_PEER_LOCK_DIR:-/tmp/codex-peer-locks}"
mkdir -p "$LOCK_DIR"
LOCK_FILE="$LOCK_DIR/${CODEX_SESSION_ID//\//_}.pid"
OUR_PID="$$"

if [ -f "$LOCK_FILE" ]; then
  OLD_PID=$(cat "$LOCK_FILE" 2>/dev/null | tr -d '[:space:]')
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "ABORT: peer session '$CODEX_SESSION_ID' already running (PID $OLD_PID)" >&2
    exit 5
  fi
fi
echo "$OUR_PID" > "$LOCK_FILE"

_IWE_ARS="$HOME/IWE/scripts/agent-status-report.sh"

cleanup_peer() {
  rm -f "$LOCK_FILE"
  [ -x "$_IWE_ARS" ] && bash "$_IWE_ARS" --session-id "$CODEX_SESSION_ID" codex idle 2>/dev/null &
  rm -rf "$TMP_ROOT"
}
trap cleanup_peer EXIT INT TERM
[ -x "$_IWE_ARS" ] && bash "$_IWE_ARS" --session-id "$CODEX_SESSION_ID" codex peer-session "$CODEX_TASK" 2>/dev/null &

# === Запуск Codex headless: `codex exec`, -o для чистого файла с финальным ответом + 5min timeout ===
OUT_FILE="$TMP_ROOT/codex-output.txt"
# BUGFIX (found by review, issue #296): -C is Codex's sandbox root — Codex reads
# from and writes to whatever this points at. Using $ADD_DIRS[0] (the RAW,
# unfiltered original directory) here defeated the whole PII/.agentigore filter
# above: FILTERED_DIRS holds the scrubbed copies in $TMP_ROOT, but the sandbox
# root itself was still the unfiltered source. Must be the FILTERED copy of the
# first --add-dir (FILTERED_DIRS[1] — [0] is the literal "--add-dir" token).
#
# WP-516 Ф5 (peer-session 2026-08-11-22-wp516-f5-contract-adapter): без
# --add-dir корнем sandbox был $PWD писателя, причём в режиме workspace-write —
# неявный write-доступ к рабочему дереву писателя. Теперь: без --add-dir
# корень = пустой временный каталог; режим ВСЕГДА read-only (контракт §0в.1:
# peer не пишет файлы; --add-dir даёт чтение контекста, не согласие на запись).
if [ ${#FILTERED_DIRS[@]} -ge 2 ]; then
  PRIMARY_DIR="${FILTERED_DIRS[1]}"
else
  PRIMARY_DIR="$TMP_ROOT/empty-root"
  mkdir -p "$PRIMARY_DIR"
fi

# --skip-git-repo-check: PRIMARY_DIR is the PII-filtered temp copy (mktemp -d
# above), never a git worktree — codex exec otherwise refuses with
# "Not inside a trusted directory" and the adapter reports it as empty output.
CODEX_EXEC_ARGS=(exec -s read-only -C "$PRIMARY_DIR" --skip-git-repo-check -o "$OUT_FILE")
# Start at 3, not 1: FILTERED_DIRS[0..1] is the pair already consumed as
# PRIMARY_DIR above — re-adding it as --add-dir would just be a harmless-but-
# redundant duplicate, skip it.
for ((i=3; i<${#FILTERED_DIRS[@]}; i+=2)); do
  CODEX_EXEC_ARGS+=("--add-dir" "${FILTERED_DIRS[$i]}")
done
if [ ${#MODEL_ARG[@]} -ge 2 ]; then
  CODEX_EXEC_ARGS+=("-m" "${MODEL_ARG[1]}")
fi
CODEX_EXEC_ARGS+=("-")

perl -e 'alarm 300; exec @ARGV' -- "$CODEX_BIN" "${CODEX_EXEC_ARGS[@]}" < "$PROMPT_FILE" >/dev/null 2>&1
PERL_EXIT=$?

if [ "$PERL_EXIT" -eq 142 ]; then
  echo "ERROR: Codex peer call timed out after 5 minutes (SIGALRM)" >&2
  echo "CODEX_TIMEOUT: peer call exceeded 5min limit — check for network problems" >&2
  exit 1
fi

# WP-516 Ф5 (§0в.1, находка Codex 12.08): non-timeout ненулевой exit CLI
# обязан нормализоваться в 1 — иначе упавший CLI с непустым output-файлом
# мог вернуть успешный 0 адаптера.
if [ "$PERL_EXIT" -ne 0 ]; then
  echo "ERROR: Codex peer call failed with exit code $PERL_EXIT (cli_exit=$PERL_EXIT)" >&2
  exit 1
fi

if [ ! -s "$OUT_FILE" ]; then
  # WP-524 Ф1 (12.08): reproduced live — provider is OpenRouter on hosts without
  # a ChatGPT login (see reference_codex_peer_openrouter_linux.md), and a missing
  # OPENROUTER_API_KEY in the caller's shell produces this exact symptom with no
  # other signal. Distinguishing it here turns a silent bootstrap failure into an
  # actionable message instead of leaving the caller to guess network/auth/quota.
  if [ -z "${OPENROUTER_API_KEY:-}" ] && [ "$CODEX_USES_OPENROUTER" = true ]; then
    echo "ERROR: codex returned empty output — OPENROUTER_API_KEY is not set." >&2
    echo "HINT: this adapter already tried auto-sourcing ~/.secrets/openrouter_key.env and it didn't take." >&2
    echo "  Check the file exists and is readable: ls -la ~/.secrets/openrouter_key.env" >&2
  else
    echo "ERROR: codex returned empty output (network/auth/quota?)" >&2
  fi
  exit 1
fi

CODEX_OUTPUT=$(cat "$OUT_FILE")

# === Hindsight L2 retain — writer-only per-turn (opt-in via env) ===
HINDSIGHT_SCRIPT="$TEMPLATE_SCRIPTS/hindsight_trigger.py"
if [ "${IWE_HINDSIGHT_RETAIN:-}" = "1" ] && [ -n "$CODEX_OUTPUT" ] && [ -f "$HINDSIGHT_SCRIPT" ]; then
  {
    echo "{\"action\":\"retain\",\"source\":\"codex-peer\",\"text\":$(echo "$CODEX_OUTPUT" | head -c 4000 | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" \
    | python3 "$HINDSIGHT_SCRIPT" 2>/dev/null || true
  } &
fi

# WP-516 Ф5 (§0в.1): stdout обязан начинаться с frontmatter; ответ без
# frontmatter = нарушение формата → exit 1 с диагностикой.
# Проверка — для peer-реплик turn-loop. Служебные вызовы писателя
# (review/verify/synth), чей вывод — НЕ peer-реплика, отключают её
# через IWE_PEER_PLAIN=1 (слой IWE-интеграции, §0в.1).
if [ "${IWE_PEER_PLAIN:-0}" != "1" ]; then
  # awk одним процессом: 'sed | head' под pipefail ловит SIGPIPE на длинной
  # валидной реплике и роняет адаптер без диагностики (review-02, WP-516 Ф5).
  _FIRST_LINE=$(printf '%s\n' "$CODEX_OUTPUT" | awk 'length { print; exit }')
  _FM_FENCES=$(printf '%s\n' "$CODEX_OUTPUT" | grep -c '^---$' || true)
  if [ "$_FIRST_LINE" != "---" ] || [ "${_FM_FENCES:-0}" -lt 2 ]; then
    echo "ERROR: peer response missing frontmatter (first non-empty line must be '---' with a closing '---')." >&2
    exit 1
  fi

  # WP-484 Ф89: alert-only self-check — доля кириллицы в ответе после
  # вычитания кода/путей/A2-глосс. Никогда не блокирует вывод, только
  # предупреждает в stderr — не peer-реплика (IWE_PEER_PLAIN=1) её не видит.
  _LANG_CHECK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/language-check.py"
  if [ -f "$_LANG_CHECK" ]; then
    _LANG_RESULT=$(printf '%s' "$CODEX_OUTPUT" | python3 "$_LANG_CHECK" 2>/dev/null || true)
    if printf '%s' "$_LANG_RESULT" | grep -q '"alert": true'; then
      echo "WARNING: peer response may not be in Russian (language-check alert) — $_LANG_RESULT" >&2
    fi
  fi
fi

# cleanup_peer() через trap удалит lock и temp
echo "$CODEX_OUTPUT"
