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

ADD_DIRS=()
MODEL_ARG=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p)                shift ;;
    --model)           MODEL_ARG=("--model" "$2"); shift 2 ;;
    --add-dir)         ADD_DIRS+=("$2"); shift 2 ;;
    --permission-mode) shift 2 ;;
    *)                 shift ;;
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
PRIMARY_DIR="${FILTERED_DIRS[1]:-$PWD}"

CODEX_EXEC_ARGS=(exec -s workspace-write -C "$PRIMARY_DIR" -o "$OUT_FILE")
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

if [ ! -s "$OUT_FILE" ]; then
  echo "ERROR: codex returned empty output (network/auth/quota?)" >&2
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

# cleanup_peer() через trap удалит lock и temp
echo "$CODEX_OUTPUT"
