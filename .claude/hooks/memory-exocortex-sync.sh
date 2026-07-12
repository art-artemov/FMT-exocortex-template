#!/bin/bash
# memory-exocortex-sync.sh — зеркалит изменённый файл memory/* или extensions/* → exocortex/ (WP-033)
# Event: PostToolUse (matcher: Write|Edit|MultiEdit)
# see TserenTserenov/FMT-exocortex-template#125 (restore — вторая половина истории портируемости)
# see TserenTserenov/FMT-exocortex-template#235 (extensions/ добавлен — DATA-POLICY.md
#   обещает ему ту же защиту, что memory/, а хук раньше проверял только memory/)
#
# Назначение: при каждом изменении файла памяти/расширения держать exocortex/ его
# зеркалом, чтобы переезд на другое устройство / сбой не терял правки, сделанные среди дня.
# Раньше это был ручной `cp + commit` (правило feedback_exocortex_sync) — теперь авто.
#
# Инвариант: exocortex/ ⊇ актуальное состояние memory/ и extensions/ в любой момент.
# extensions/ зеркалится в exocortex/extensions/ (отдельная подпапка — предотвращает
# коллизии имён с memory/, если когда-нибудь совпадут).
# Принципы:
#   - НИКОГДА не блокирует операцию (exit 0 всегда; зеркалирование — побочный эффект).
#   - Дёшево: ранний выход для не-memory/не-extensions файлов до любых тяжёлых операций.
#   - Commit/push НЕ делает — это происходит при Close (day-close backup + dirty-repo handling).
#     Хук отвечает только за файловое зеркало, не за git-транспорт.

set -uo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:${PATH:-}"

# jq нужен для парсинга stdin; нет jq — молча выходим (хук не критичен для операции)
command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
[ -z "$FILE_PATH" ] && exit 0

# Только .md / .yaml / .yml (memory/ и extensions/ оба состоят из таких файлов). Ранний выход для кода/прочего.
case "$FILE_PATH" in
    *.md|*.yaml|*.yml) ;;
    *) exit 0 ;;
esac

# Path-схема: override через env > симлинк $WORKSPACE_DIR/memory > пересборка slug.
# ВАЖНО: Claude Code слугифицирует путь проекта, заменяя на '-' не только '/', но и
# '_' и '.'. Если в $HOME есть '_' (напр. username john_doe), реальная папка проекта —
# '-home-john-doe-IWE', а 'tr / -' даёт фантом '-home-john_doe-IWE' → зеркало не пишется.
# Поэтому slug = tr '/_.' '-', а первичный источник — симлинк (не зависит от слугификации).
WORKSPACE_DIR="${WORKSPACE_DIR:-$HOME/IWE}"
GOVERNANCE_REPO="${GOVERNANCE_REPO:-${IWE_GOVERNANCE_REPO:-DS-strategy}}"
HOME_SLUG=$(echo "$HOME" | tr '/_.' '-')
MEMORY_SRC="${IWE_MEMORY_SRC:-$HOME/.claude/projects/${HOME_SLUG}-IWE/memory}"
EXOCORTEX_DST="$WORKSPACE_DIR/$GOVERNANCE_REPO/exocortex"

# Канонический реальный путь memory/. Приоритет — симлинк $WORKSPACE_DIR/memory
# (указывает на auto-memory независимо от правил слугификации); fallback — MEMORY_SRC.
if [ -z "${IWE_MEMORY_SRC:-}" ] && [ -d "$WORKSPACE_DIR/memory" ]; then
    MEMORY_REAL=$(cd "$WORKSPACE_DIR/memory" 2>/dev/null && pwd -P) || exit 0
else
    MEMORY_REAL=$(cd "$MEMORY_SRC" 2>/dev/null && pwd -P) || exit 0
fi
EXTENSIONS_REAL=$(cd "$WORKSPACE_DIR/extensions" 2>/dev/null && pwd -P) || EXTENSIONS_REAL=""

# Реальный каталог изменённого файла (резолвим возможный симлинк-путь)
FILE_DIR=$(cd "$(dirname "$FILE_PATH")" 2>/dev/null && pwd -P) || exit 0
FNAME=$(basename "$FILE_PATH")

mirror_file() {
    local src_dir="$1" dst_dir="$2"
    [ -f "$src_dir/$FNAME" ] || return 1
    mkdir -p "$dst_dir" 2>/dev/null || return 1
    cp "$src_dir/$FNAME" "$dst_dir/$FNAME" 2>/dev/null
}

# Файл должен лежать ПРЯМО в memory/ или в extensions/ (плоская структура обеих папок)
if [ "$FILE_DIR" = "$MEMORY_REAL" ]; then
    mirror_file "$MEMORY_REAL" "$EXOCORTEX_DST"
elif [ -n "$EXTENSIONS_REAL" ] && [ "$FILE_DIR" = "$EXTENSIONS_REAL" ]; then
    mirror_file "$EXTENSIONS_REAL" "$EXOCORTEX_DST/extensions"
fi

exit 0
