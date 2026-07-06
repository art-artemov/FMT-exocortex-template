#!/bin/bash
# routing: helper  skill=week-close,day-close  called-by=haiku
# see DP.SC.159, DP.ROLE.059
# staging-audit.sh — детектор B12e Decay drift в STAGING.md
#
# Парсит STAGING.md (inline таблица S-NN | name | files | status | date | criteria),
# выявляет записи со статусом `testing` старше N дней (default 30) и записи
# с пройденными prose-дедлайнами (формат «при Week Close WNN» / «до D мая»).
#
# Использование:
#   bash staging-audit.sh                     # отчёт по умолчанию (testing >30d)
#   bash staging-audit.sh --threshold 14      # порог в днях
#   bash staging-audit.sh --check             # exit 1 если найдены zombies
#   bash staging-audit.sh --staging <path>    # путь к STAGING.md (default $IWE/STAGING.md)
#
# MVP-cut: machine-readable per-row frontmatter (decay_after, ready_signals) отложено
# в полную версию. Сейчас работает с inline-таблицей через regex по дате 5-й колонки.

set -uo pipefail

IWE="${IWE_WORKSPACE:-$HOME/IWE}"
STAGING="${IWE}/STAGING.md"
THRESHOLD=30
check_mode=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --threshold) THRESHOLD="$2"; shift 2 ;;
        --check) check_mode=true; shift ;;
        --staging) STAGING="$2"; shift 2 ;;
        --help|-h)
            grep "^# " "$0" | head -20 | sed 's/^# //'
            exit 0
            ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

[[ -f "$STAGING" ]] || { echo "[ERROR] STAGING.md not found: $STAGING" >&2; exit 1; }

TODAY=$(date +%Y-%m-%d)
TODAY_EPOCH=$(date +%s)
threshold_epoch=$((TODAY_EPOCH - THRESHOLD * 86400))

# Подсчёт глобальных метрик
total=$(grep -cE "^\| S-[0-9]+ " "$STAGING" || echo 0)
promoted=$(grep -cE "^\| S-[0-9]+ .*\| promoted " "$STAGING" || echo 0)
testing=$(grep -cE "^\| S-[0-9]+ .*\| testing " "$STAGING" || echo 0)
rejected=$(grep -cE "^\| S-[0-9]+ .*\| rejected " "$STAGING" || echo 0)

echo "=== STAGING.md audit ($STAGING) ==="
echo "Дата отчёта: $TODAY · Порог decay: ${THRESHOLD} дней"
echo ""
echo "Всего записей: $total"
echo "  promoted: $promoted"
echo "  testing:  $testing"
echo "  rejected: $rejected"
echo ""

# Поиск zombies — testing-записей с датой 5-й колонки старше порога
zombies=0
echo "=== Zombie кандидаты (testing >${THRESHOLD}d) ==="

while IFS= read -r line; do
    # Извлечь S-NN, status, date (формат YYYY-MM-DD в 5-й колонке)
    id=$(echo "$line" | grep -oE "^\| S-[0-9]+" | tr -d '| ')
    [[ -z "$id" ]] && continue
    status=$(echo "$line" | awk -F'|' '{ for(i=1;i<=NF;i++) if($i ~ /testing|promoted|rejected/) { gsub(/ /,"",$i); print $i; break }}')
    [[ "$status" != "testing" ]] && continue
    # Дата — первый матч YYYY-MM-DD в строке после статуса
    date=$(echo "$line" | grep -oE "20[0-9]{2}-[0-9]{2}-[0-9]{2}" | head -1)
    [[ -z "$date" ]] && { echo "  $id: testing (нет даты в строке) — нужен ручной аудит"; ((zombies++)); continue; }
    if [[ "$(uname)" == "Darwin" ]]; then
        date_epoch=$(date -j -f "%Y-%m-%d" "$date" "+%s" 2>/dev/null || echo 0)
    else
        date_epoch=$(date -d "$date" "+%s" 2>/dev/null || echo 0)
    fi
    [[ "$date_epoch" -eq 0 ]] && continue
    if [[ "$date_epoch" -lt "$threshold_epoch" ]]; then
        age_days=$(( (TODAY_EPOCH - date_epoch) / 86400 ))
        # Извлечь короткое описание (2-я колонка, первые 50 символов)
        desc=$(echo "$line" | awk -F'|' '{print $3}' | sed 's/^ *//;s/ *$//' | cut -c1-50)
        echo "  $id (${age_days}d): $desc..."
        ((zombies++))
    fi
done < <(grep -E "^\| S-[0-9]+ " "$STAGING")

echo ""
echo "Найдено zombies: $zombies"

# Gap-check нумерации
echo ""
echo "=== Gap-check нумерации S-* ==="
nums=$(grep -oE "^\| S-[0-9]+" "$STAGING" | grep -oE "[0-9]+" | sort -n | uniq)
prev=0
gaps=0
for n in $nums; do
    if [[ $prev -gt 0 ]] && [[ $((n - prev)) -gt 1 ]]; then
        for ((i=prev+1; i<n; i++)); do
            echo "  GAP: S-$i отсутствует (между S-$prev и S-$n)"
            ((gaps++))
        done
    fi
    prev=$n
done
echo "Gaps в нумерации: $gaps"

# Prose-deadline detector (best-effort)
echo ""
echo "=== Прозаичные дедлайны проверь вручную ==="
prose_deadlines=$(grep -cE "Week Close W[0-9]+|до [0-9]+ мая|до [0-9]+ июн" "$STAGING" || echo 0)
echo "Записей с prose-deadline: $prose_deadlines (требуют машинных критериев — см. B12e)"

# Exit-код в check mode
if $check_mode; then
    if [[ $zombies -gt 0 ]]; then
        echo ""
        echo "❌ FAIL: найдено $zombies zombie(s)"
        exit 1
    fi
    echo ""
    echo "✅ PASS: zombies не обнаружены"
fi

exit 0
