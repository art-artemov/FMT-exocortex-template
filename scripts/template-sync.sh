#!/bin/bash
# routing: utility  deterministic=true
# see DP.SC.159, DP.ROLE.059
# template-sync.sh — синхронизация CLAUDE.md из авторского IWE в FMT-exocortex-template
#
# Flow: $IWE_WORKSPACE/CLAUDE.md → placeholder sub → strip §9 авторское → FMT/CLAUDE.md
#
# Использование:
#   ./template-sync.sh            # синхронизировать
#   ./template-sync.sh --dry-run  # показать diff без записи
#   ./template-sync.sh --check    # проверить drift (exit 0 = OK, exit 1 = drift)

set -euo pipefail

# Guard: валидация IWE_TEMPLATE и IWE_WORKSPACE (не должны быть временными директориями)
if [[ "${IWE_TEMPLATE:-}" =~ ^/tmp/iwe-smoke ]]; then
    echo "[ERROR] IWE_TEMPLATE указывает на удалённую smoke-тестовую директорию: $IWE_TEMPLATE" >&2
    echo "Используется fallback: \$HOME/IWE/FMT-exocortex-template" >&2
    unset IWE_TEMPLATE
fi
if [[ "${IWE_WORKSPACE:-}" =~ ^/tmp/iwe-smoke ]]; then
    echo "[ERROR] IWE_WORKSPACE указывает на удалённую smoke-тестовую директорию: $IWE_WORKSPACE" >&2
    echo "Используется fallback: \$HOME/IWE" >&2
    unset IWE_WORKSPACE
fi

IWE="${IWE_WORKSPACE:-$HOME/IWE}"
FMT_DIR="${IWE_TEMPLATE:-$IWE/FMT-exocortex-template}"
SRC="$IWE/CLAUDE.md"
FMT="$FMT_DIR/CLAUDE.md"

# Валидация файлов
if [ ! -f "$SRC" ]; then
    echo "[ERROR] Исходный файл не найден: $SRC" >&2
    exit 1
fi

if [ ! -f "$FMT" ]; then
    echo "[ERROR] Файл шаблона не найден: $FMT" >&2
    exit 1
fi

# Авторское имя governance-репо (из env, обязательно) → template default
GOV_REPO_AUTHOR="${IWE_GOVERNANCE_REPO:?IWE_GOVERNANCE_REPO must be set (your governance repo name, e.g. DS-strategy)}"
GOV_REPO_TMPL="DS-strategy"

# Граница §9 (авторское — не идёт в шаблон)
AUTHOR_SECTION="^## 9\. Авторское"

dry_run=false
check_only=false
case "${1:-}" in
    --dry-run) dry_run=true ;;
    --check)   check_only=true ;;
    "") ;;
    *) echo "Usage: $0 [--dry-run|--check]" >&2; exit 1 ;;
esac

# 1. Извлечь §1-§8 из runtime (до границы §9)
l18=$(awk "/$AUTHOR_SECTION/{exit} {print}" "$SRC")

# 2. Применить placeholder-подстановки
l18_tmpl=$(printf '%s' "$l18" \
    | sed "s|$IWE|{{HOME_DIR}}/IWE|g" \
    | sed "s|$HOME|{{HOME_DIR}}|g" \
    | sed "s|~/IWE|{{HOME_DIR}}/IWE|g" \
    | sed "s|$GOV_REPO_AUTHOR|$GOV_REPO_TMPL|g")

# 3. Взять §9 из FMT без изменений (шаблонная версия, не авторская)
l9=$(awk "/$AUTHOR_SECTION/{found=1} found{print}" "$FMT")

# 4. Собрать результат
result="${l18_tmpl}
${l9}"

if $check_only; then
    if diff <(printf '%s\n' "$result") "$FMT" > /dev/null 2>&1; then
        echo "OK: FMT/CLAUDE.md синхронен с runtime"
        exit 0
    else
        echo "DRIFT: FMT/CLAUDE.md не синхронен с runtime"
        diff <(printf '%s\n' "$result") "$FMT" || true
        exit 1
    fi
fi

if $dry_run; then
    echo "=== CLAUDE.md diff (dry-run) ==="
    diff <(printf '%s\n' "$result") "$FMT" || true
else
    printf '%s\n' "$result" > "$FMT"
    echo "✅ Синхронизировано: CLAUDE.md → FMT/CLAUDE.md"
fi

# 4a. Расширенный allowlist — sync FMT/memory/protocol-*.md и FMT/.claude/rules/*.md
# WP-7/PZ-2 (2026-05-29): закрытие B12c Reverse drift для протоколов и правил.
# Каждый файл: strip <!-- AUTHOR-ONLY -->...<!-- /AUTHOR-ONLY --> блоков +
# placeholder-подстановка путей. ToRefresh-list см. ниже.
sync_allowlist_file() {
    local rel="$1"
    local src_path="$IWE/$rel"
    local dst_path="$FMT_DIR/$rel"
    [ -f "$src_path" ] || { echo "  skip: $rel (нет в авторе)"; return 0; }
    [ -f "$dst_path" ] || { echo "  skip: $rel (нет в FMT — добавлять руками первый раз)"; return 0; }
    local body
    body=$(awk '
        /<!-- AUTHOR-ONLY -->/  { skip=1; next }
        /<!-- \/AUTHOR-ONLY -->/{ skip=0; next }
        !skip { print }
    ' "$src_path" | sed \
        -e "s|$IWE|{{HOME_DIR}}/IWE|g" \
        -e "s|$HOME|{{HOME_DIR}}|g" \
        -e "s|~/IWE|{{HOME_DIR}}/IWE|g" \
        -e "s|$GOV_REPO_AUTHOR|$GOV_REPO_TMPL|g")
    if [ "$body" != "$(cat "$dst_path")" ]; then
        if $dry_run; then
            echo "  DIFF: $rel (будет обновлён)"
        else
            printf '%s\n' "$body" > "$dst_path"
            echo "  ✅ Синхронизировано: $rel"
        fi
    else
        echo "  OK: $rel"
    fi
}

echo ""
echo "Расширенный allowlist (PZ-2):"
for f in \
    memory/protocol-open.md \
    memory/protocol-work.md \
    memory/protocol-close.md \
    memory/protocol-month-close.md \
    .claude/rules/distinctions.md \
    .claude/rules/formatting.md \
    .claude/rules/wp-scope.md \
    .claude/rules/role-prefixes.md
do
    sync_allowlist_file "$f"
done

# 5. Валидация FMT/scripts/ на личные хардкоды (skip в dry-run)
if ! $dry_run; then
    VALIDATOR="$FMT_DIR/scripts/validate-fmt-scripts.sh"
    if [ -f "$VALIDATOR" ]; then
        echo ""
        bash "$VALIDATOR" "$FMT_DIR/scripts" || {
            echo "⚠️  Личные хардкоды в FMT/scripts/ — исправить до коммита" >&2
        }
    fi

    CHANGELOG_SCRIPT="$FMT_DIR/scripts/changelog-append.sh"
    [[ -f "$CHANGELOG_SCRIPT" ]] && bash "$CHANGELOG_SCRIPT" || true
fi

$dry_run && exit 0

echo ""
echo "Следующий шаг:"
echo "  cd $FMT_DIR && git diff CLAUDE.md && git add CLAUDE.md CHANGELOG.md && git commit"
