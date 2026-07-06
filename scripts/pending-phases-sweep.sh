#!/usr/bin/env bash
# routing: utility  deterministic=true
# see Backlog B-005 (Week Close §5b helper)
# pending-phases-sweep.sh — обходит активные WP-context файлы и выводит pending фазы
#
# Использование:
#   bash pending-phases-sweep.sh                  # обход активных РП в ${IWE_GOVERNANCE_REPO:-DS-strategy}/inbox/
#   bash pending-phases-sweep.sh --all            # включить файлы без status
#   bash pending-phases-sweep.sh --repo <path>    # указать другой governance-репо
#
# Output: для каждого активного WP с pending-фазами — заголовок + список фаз
#
# Совместимость: macOS bash 3.2 (без mapfile, без assoc-arrays)

set -uo pipefail

IWE="${IWE_WORKSPACE:-$HOME/IWE}"
GOV_REPO="${IWE_GOVERNANCE_REPO:-${IWE_GOVERNANCE_REPO:-DS-strategy}}"
INBOX_DIR="$IWE/$GOV_REPO/inbox"

include_all=false
custom_repo=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all) include_all=true; shift ;;
        --repo) custom_repo="$2"; shift 2 ;;
        -h|--help)
            sed -n '1,/^$/p' "$0" | grep -E '^#' | sed 's/^# *//'
            exit 0
            ;;
        *)
            echo "Unknown arg: $1" >&2
            exit 1
            ;;
    esac
done

[[ -n "$custom_repo" ]] && INBOX_DIR="$custom_repo/inbox"

if [[ ! -d "$INBOX_DIR" ]]; then
    echo "[ERROR] Inbox directory not found: $INBOX_DIR" >&2
    exit 1
fi

# Список активных WP-файлов через temp-файл (без mapfile для bash 3.2 совместимости)
tmp_wp_list=$(mktemp)
tmp_active_list=$(mktemp)
trap "rm -f '$tmp_wp_list' '$tmp_active_list'" EXIT

find "$INBOX_DIR" -maxdepth 2 -name "WP-*.md" -type f 2>/dev/null | sort > "$tmp_wp_list"

if [[ ! -s "$tmp_wp_list" ]]; then
    echo "Нет WP-*.md файлов в $INBOX_DIR"
    exit 0
fi

# Фильтр: status: in_progress (или без status если --all)
while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    status_line=$(grep -m1 -iE "^status:" "$f" 2>/dev/null || true)
    if echo "$status_line" | grep -qiE "in_progress|active|in-progress"; then
        echo "$f" >> "$tmp_active_list"
    elif [[ "$include_all" == "true" && -z "$status_line" ]]; then
        echo "$f" >> "$tmp_active_list"
    fi
done < "$tmp_wp_list"

if [[ ! -s "$tmp_active_list" ]]; then
    echo "Нет активных WP-* файлов (status: in_progress) в $INBOX_DIR"
    [[ "$include_all" != "true" ]] && echo "Запусти с --all чтобы включить файлы без явного status"
    exit 0
fi

total_wp=0
total_pending=0

# Для каждого активного — извлечь pending фазы
while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    wp_name=$(basename "$f" .md)
    # Ищем строки вида: | Фx | ... | ⏳ pending | или | Фx | ... | pending |
    pending_lines=$(grep -nE "^\|\s*\*?\*?Ф[0-9.]+\*?\*?\s*\|" "$f" 2>/dev/null | \
        grep -iE "pending|⏳|⏸" | \
        grep -ivE "✅|done|completed|❌|cancelled|skipped|blocked" || true)

    if [[ -n "$pending_lines" ]]; then
        count=$(echo "$pending_lines" | wc -l | tr -d ' ')
        total_pending=$((total_pending + count))
        total_wp=$((total_wp + 1))

        echo ""
        echo "=== $wp_name: pending фазы ($count) ==="
        echo "$pending_lines" | while IFS= read -r line; do
            content="${line#*:}"
            phase=$(echo "$content" | awk -F'|' '{gsub(/\*\*/, "", $2); gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2}')
            desc=$(echo "$content" | awk -F'|' '{gsub(/\*\*/, "", $3); gsub(/^[[:space:]]+|[[:space:]]+$/, "", $3); print substr($3, 1, 100)}')
            echo "  $phase — $desc"
        done
    fi
done < "$tmp_active_list"

active_count=$(wc -l < "$tmp_active_list" | tr -d ' ')

echo ""
echo "---"
if [[ $total_wp -eq 0 ]]; then
    echo "Pending фаз не найдено в $active_count активных РП"
else
    echo "Итого: $total_pending pending-фаз в $total_wp активных РП (из $active_count просмотренных)"
    echo "Решение для каждой: (a) делать на след. неделе → W+1; (b) переоценить (блокер/устарела); (c) оставить с ожидаемым триггером"
fi
