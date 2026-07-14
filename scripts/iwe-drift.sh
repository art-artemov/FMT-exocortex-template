#!/usr/bin/env bash
# routing: helper  skill=iwe-rules-review  called-by=haiku  deterministic=true
# see DP.SC.159, DP.ROLE.059
# iwe-drift.sh — MVP drift-отчёт по .claude/sync-manifest.yaml
#
# WP-217 Ф3b, черновик 2026-04-10.
# НЕ переносить в scripts/ до ревью владельца.
#
# РОЛЬ (уточнение 10 апр): R23-детектор для пар (A(pair), M1 compliance
# «синхронны ли источник и производное»). Только ДЕТЕКЦИЯ, не применяет fix.
# Fix — отдельные операторные скрипты (R8 Синхронизатор):
#   template-sync.sh, update.sh, dt_sync.py.
# Правило: детектор отчитывается, оператор делает. Не смешивать.
#
# Usage:
#   bash iwe-drift.sh                  # полный отчёт
#   bash iwe-drift.sh --critical       # только critical
#   bash iwe-drift.sh --top N          # топ N по lag
#   bash iwe-drift.sh --manifest PATH  # указать путь к манифесту
#
# Требования: bash, git, stat, awk (POSIX). Без внешних зависимостей.
# Формат вывода: markdown-таблица, пригодная для вставки в DayPlan/Week Report.

set -eu

# Detect stat mtime flag once — GNU/Linux uses -c %Y, BSD/macOS uses -f %m.
# NOTE: GNU stat accepts `-f %m` too (it prints the mount point), so we must
# detect GNU first by testing the flag it supports and BSD does not.
# Use unquoted $_STAT_FLAG in xargs pipelines (word-split is required for multi-token flags).
if stat -c %Y /dev/null >/dev/null 2>&1; then
    _STAT_FLAG="-c %Y"  # GNU/Linux
else
    _STAT_FLAG="-f %m"  # BSD/macOS
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# iwe-env-bootstrap.sh sets its own top-level SCRIPT_DIR when sourced, clobbering ours —
# save this script's own directory under a distinct name before sourcing (issue #259).
IWE_DRIFT_SCRIPT_DIR="$SCRIPT_DIR"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../.claude/lib/iwe-env-bootstrap.sh" || exit 1
MANIFEST="${MANIFEST:-$IWE_ROOT/.claude/sync-manifest.yaml}"
MODE="all"
TOP_N=0

while [ $# -gt 0 ]; do
    case "$1" in
        --critical) MODE="critical"; shift ;;
        --top) TOP_N="$2"; shift 2 ;;
        --manifest) MANIFEST="$2"; shift 2 ;;
        -h|--help)
            grep '^#' "$0" | head -20
            exit 0
            ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [ ! -f "$MANIFEST" ]; then
    echo "Manifest not found: $MANIFEST" >&2
    exit 1
fi

# Получить mtime файла в днях от сегодня (использует $_STAT_FLAG, определяется выше)
mtime_days_ago() {
    local path="$1"
    if [ ! -e "$path" ]; then
        echo "-1"
        return
    fi
    local mtime
    # shellcheck disable=SC2086  # $_STAT_FLAG intentionally unquoted (multi-token flag)
    mtime=$(stat $_STAT_FLAG "$path")
    local now
    now=$(date +%s)
    echo $(( (now - mtime) / 86400 ))
}

# Получить самый свежий mtime в директории (рекурсивно)
dir_newest_mtime_days_ago() {
    local dir="$1"
    if [ ! -d "$dir" ]; then
        mtime_days_ago "$dir"
        return
    fi
    local newest
    # shellcheck disable=SC2086  # $_STAT_FLAG intentionally unquoted (multi-token flag)
    newest=$(find "$dir" -type f -not -path '*/.git/*' -print0 2>/dev/null \
        | xargs -0 stat $_STAT_FLAG 2>/dev/null \
        | sort -nr | head -1)
    if [ -z "${newest:-}" ]; then
        echo "-1"
        return
    fi
    local now
    now=$(date +%s)
    echo $(( (now - newest) / 86400 ))
}

# Парсинг YAML (наивный, только для фиксированного формата этого манифеста)
parse_manifest() {
    local manifest="$1"
    awk '
        /^  - id:/ { if (id != "") print_record(); id = clean($3) }
        /^    source:/ { source = clean($2) }
        /^    derived:/ { derived = clean($2) }
        /^    relation:/ { relation = clean($2) }
        /^    check:/ { check = clean($2) }
        /^    threshold_days:/ { thresh = clean($2) }
        /^    critical_days:/ { crit = clean($2) }
        /^    owner_role:/ { owner = clean($2) }
        /^    symptom:/ {
            sub(/^[[:space:]]*symptom:[[:space:]]*"?/, "", $0)
            sub(/"[[:space:]]*$/, "", $0)
            symptom = $0
        }
        END { if (id != "") print_record() }

        function clean(v) {
            gsub(/^["[:space:]]+|["[:space:]]+$/, "", v)
            return v
        }

        function print_record() {
            printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n", id, source, derived, relation, check, thresh, crit, owner, symptom
            id=""; source=""; derived=""; relation=""; check=""; thresh=""; crit=""; owner=""; symptom=""
        }
    ' "$manifest"
}

# Собрать записи → строки markdown
collect() {
    local records_file="$1"

    while IFS=$'\t' read -r id source derived relation check thresh crit owner symptom; do
        [ -z "$id" ] && continue

        # issue #220: check: script:<path> раньше читался, но никогда не исполнялся —
        # такие пары молча трактовались как mtime-lag (source==derived → lag всегда 0 → всегда "ok").
        case "$check" in
            script:*)
                # issue #259: хелперы шаблонные (живут рядом со scripts/iwe-drift.sh), а не
                # часть workspace-root — резолвим относительно SCRIPT_DIR, не IWE_ROOT.
                local helper_path="$IWE_DRIFT_SCRIPT_DIR/../${check#script:}"
                local script_status
                if [ ! -f "$helper_path" ]; then
                    script_status="missing"
                elif bash "$helper_path" >/dev/null 2>&1; then
                    script_status="ok"
                else
                    case "$?" in
                        2) script_status="critical" ;;
                        # 1/3: хелпер нашёлся и запустился, но источник пары не подходит для
                        # этой инсталляции (например нет WP-REGISTRY.md) — не путать с "missing"
                        # (сам хелпер не найден).
                        1|3) script_status="unavailable" ;;
                        *) script_status="missing" ;;
                    esac
                fi
                printf "%s\t%s\t%s\t%s\t%s\t%s\n" "?" "$id" "$relation" "$script_status" "$owner" "$symptom"
                continue
                ;;
        esac

        local src_path="$source"
        local dst_path="$derived"
        case "$src_path" in /*) ;; *) src_path="$IWE_ROOT/$src_path" ;; esac
        case "$dst_path" in /*) ;; *) dst_path="$IWE_ROOT/$dst_path" ;; esac

        local src_age dst_age lag status
        src_age=$(dir_newest_mtime_days_ago "$src_path")
        dst_age=$(dir_newest_mtime_days_ago "$dst_path")

        if [ "$src_age" -lt 0 ] || [ "$dst_age" -lt 0 ]; then
            lag="?"
            status="missing"
        else
            # lag = dst_age - src_age (положительный = derived отстаёт)
            lag=$(( dst_age - src_age ))
            if [ "$lag" -lt 0 ]; then lag=0; fi
            if [ -z "$crit" ] || [ -z "$thresh" ]; then
                status="ok"
            elif [ "$lag" -ge "$crit" ]; then
                status="critical"
            elif [ "$lag" -ge "$thresh" ]; then
                status="warn"
            else
                status="ok"
            fi
        fi

        printf "%s\t%s\t%s\t%s\t%s\t%s\n" "$lag" "$id" "$relation" "$status" "$owner" "$symptom"
    done < "$records_file"
}

TMP_RECORDS=$(mktemp)
TMP_ROWS=$(mktemp)
trap 'rm -f "$TMP_RECORDS" "$TMP_ROWS"' EXIT

parse_manifest "$MANIFEST" > "$TMP_RECORDS"
collect "$TMP_RECORDS" > "$TMP_ROWS"

# Фильтрация
if [ "$MODE" = "critical" ]; then
    awk -F'\t' '$4 == "critical"' "$TMP_ROWS" > "$TMP_ROWS.filtered"
    mv "$TMP_ROWS.filtered" "$TMP_ROWS"
fi

# Сортировка по lag (numeric descending, '?' в конец)
sort -t$'\t' -k1,1 -rn "$TMP_ROWS" > "$TMP_ROWS.sorted"
mv "$TMP_ROWS.sorted" "$TMP_ROWS"

# Top-N
if [ "$TOP_N" -gt 0 ]; then
    head -n "$TOP_N" "$TMP_ROWS" > "$TMP_ROWS.top"
    mv "$TMP_ROWS.top" "$TMP_ROWS"
fi

# Вывод markdown-таблицы
echo "## Drift-отчёт ($(date +%Y-%m-%d))"
echo ""
if [ ! -s "$TMP_ROWS" ]; then
    echo "_Нет drift'а по выбранному фильтру._"
    exit 0
fi
echo "| lag (дней) | ID | relation | статус | владелец | симптом |"
echo "|---:|---|---|---|---|---|"
while IFS=$'\t' read -r lag id relation status owner symptom; do
    # иконка
    case "$status" in
        critical) icon="critical" ;;
        warn)     icon="warn" ;;
        ok)       icon="ok" ;;
        missing)  icon="missing" ;;
        *)        icon="$status" ;;
    esac
    printf "| %s | %s | %s | %s | %s | %s |\n" "$lag" "$id" "$relation" "$icon" "$owner" "$symptom"
done < "$TMP_ROWS"
