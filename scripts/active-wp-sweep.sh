#!/usr/bin/env bash
# routing: helper  called-by=day-open,session-prep  deterministic=true
# see DP.SC.159, DP.ROLE.059
# active-wp-sweep.sh — heartbeat sweep активных РП
# see WP-283 Шаг E (${IWE_GOVERNANCE_REPO:-DS-strategy}/inbox/WP-283-server-day-open-crossplatform.md)
#
# Обходит ${IWE_GOVERNANCE_REPO:-DS-strategy}/inbox/WP-*.md, находит файлы с status: in_progress | active | awaiting-batch,
# плюс union с WP-IDs из текущего WeekPlan (для pending-РП, которые в плане недели),
# кросс-чекает с git activity, выводит markdown-таблицу кандидатов.
#
# Совместимость: bash 3.2+ (macOS), bash 4+ (Linux/NixOS)
#
# Использование:
#   bash active-wp-sweep.sh [INBOX_DIR] [IWE_ROOT]

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# SELF_DIR: iwe-env-bootstrap.sh (sourced next) reassigns SCRIPT_DIR to ITS OWN
# directory (.claude/lib/) — it's sourced, not run in a subshell, so that
# clobbers ours. Capture our own location under a name it can't collide with
# before sourcing it (issue #298 migration needs this script's own dir below
# to find wp-list.py).
SELF_DIR="$SCRIPT_DIR"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../.claude/lib/iwe-env-bootstrap.sh" || exit 1
IWE="${2:-$IWE_ROOT}"
INBOX="${1:-$IWE/${IWE_GOVERNANCE_REPO:-DS-strategy}/inbox}"
GIT_DAYS="${WP_SWEEP_GIT_DAYS:-7}"

# --- Найти python3 с yaml ---
_find_python3() {
  if python3 -c "import yaml" 2>/dev/null; then echo "python3"; return; fi
  local p
  for p in \
    /nix/store/aj1smkrsnv16lbz9g8qancb04b3kv0va-python3-3.12.8-env/bin/python3 \
    /usr/bin/python3 /usr/local/bin/python3; do
    [[ -x "$p" ]] && "$p" -c "import yaml" 2>/dev/null && { echo "$p"; return; }
  done
  echo ""
}

PYTHON=$(_find_python3)

if [[ -z "$PYTHON" ]]; then
  echo "<!-- active-wp-sweep: python3+yaml не найден, sweep пропущен -->"
  exit 0
fi

if [[ ! -d "$INBOX" ]]; then
  echo "<!-- active-wp-sweep: INBOX не найден: $INBOX -->"
  exit 0
fi

# --- Discovery: single entrypoint (issue #298) ---
# wp-list.py encodes the two-level inbox layout (flat WP-NNN.md + nested
# WP-NNN/WP-NNN.md, WP-434) in ONE place — this script used to reimplement it
# independently (_gather_wp_files/_find_wp_context), the exact duplication
# issue #298 asked to retire. status_raw + registry_done come back as
# SEPARATE fields on purpose: this script's whole drift-detection point is
# comparing them (frontmatter still says active, REGISTRY already ✅) — a
# merged "status" field would silently hide that mismatch (see wp-list.py's
# own field docstring).
#
# Standard callers (day-open-scaffold.sh, both copies) always pass
# "$IWE/$GOV/inbox" — derive GOV back out of INBOX so wp-list.py's own path
# construction matches exactly what INBOX resolved to; fall back to the env
# default for any caller that passes something else.
GOV_REPO_FOR_LIST="${IWE_GOVERNANCE_REPO:-DS-strategy}"
case "$INBOX" in
  "$IWE"/*/inbox)
    GOV_REPO_FOR_LIST="${INBOX#"$IWE"/}"
    GOV_REPO_FOR_LIST="${GOV_REPO_FOR_LIST%/inbox}"
    ;;
esac

WP_LIST_SCRIPT="$SELF_DIR/wp-list.py"
if [[ ! -f "$WP_LIST_SCRIPT" ]]; then
  echo "<!-- active-wp-sweep: wp-list.py не найден, sweep пропущен -->"
  exit 0
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "<!-- active-wp-sweep: jq не найден, sweep пропущен -->"
  exit 0
fi

# --format json + jq, не --format tsv: bash `IFS=$'\t' read` COLLAPSES an
# empty field sitting between two tabs — tab is always "IFS whitespace" in
# bash's field-splitting rules regardless of what IFS is explicitly set to,
# so a card with no title (WP-401 has `name:`, not `title:`, in this
# governance repo) silently shifted every field after it left by one and
# corrupted the row (found live testing this migration — title column showed
# the STATUS value). \x1f (Unit Separator, jq join) is not IFS whitespace,
# so empty fields survive `read` correctly.
WP_LIST_US=$("$PYTHON" "$WP_LIST_SCRIPT" --list-cards --source inbox \
  --fields wp,title,status_raw,registry_done,card \
  --format json --governance-repo "$GOV_REPO_FOR_LIST" --iwe-root "$IWE" 2>/dev/null \
  | jq -r '.[] | [.wp,.title,.status_raw,.registry_done,.card] | join("\u001f")')

# _wp_list_row: look up an already-fetched row by WP number (used by the
# WeekPlan-union pass below — no second wp-list.py call, same dataset).
_wp_list_row() {
  printf '%s\n' "$WP_LIST_US" | awk -F'\x1f' -v n="$1" '$1==n {print; exit}'
}

# --- Union: WP-IDs из текущего WeekPlan (для pending-РП в плане недели) ---
# Находит первый файл WeekPlan W*.md в current/ и извлекает все WP-NNN из него.
_weekplan_wp_ids() {
  local weekplan
  weekplan=$(ls -t "$IWE/${IWE_GOVERNANCE_REPO:-DS-strategy}/current/WeekPlan"*.md 2>/dev/null | head -1)
  [[ -f "$weekplan" ]] || return
  grep -oE 'WP-[0-9]+' "$weekplan" 2>/dev/null | grep -oE '[0-9]+' | sort -u
}

WEEKPLAN_IDS=$(_weekplan_wp_ids)

# --- Собрать WP-файлы с in_progress, active или awaiting-batch ---
FOUND=0
DRIFT_ROWS=""
OUTPUT_ROWS=""
SEEN_WP_NUMS=""

_git_activity_cell() {
  local wp_num="$1" git_info="" git_dir repo_dir hit
  while IFS= read -r git_dir; do
    repo_dir="$(dirname "$git_dir")"
    hit=$(git -C "$repo_dir" log \
      --since="${GIT_DAYS} days ago" --oneline --grep="WP-${wp_num}" --all 2>/dev/null | head -1)
    if [[ -n "$hit" ]]; then git_info="$hit"; break; fi
  done < <(find "$IWE" -maxdepth 2 -name ".git" -type d 2>/dev/null)
  if [[ -n "$git_info" ]]; then echo "${git_info:0:55}"; else echo "нет (${GIT_DAYS}д)"; fi
}

while IFS=$'\x1f' read -r WP_NUM WP_TITLE STATUS_RAW REGISTRY_DONE WP_FILE; do
  [[ -z "$WP_NUM" ]] && continue

  case "$STATUS_RAW" in
    in_progress|active|awaiting-batch) ;;
    *) continue ;;
  esac

  WP_LABEL="WP-${WP_NUM:-??}"
  [[ -z "$WP_TITLE" ]] && WP_TITLE="$(basename "$WP_FILE" .md)"
  # 60-char cap — table-readability choice this script always made (long
  # titles used to blow out the markdown column); wp-list.py itself returns
  # full titles for other consumers, truncation belongs here at display time.
  WP_TITLE="${WP_TITLE:0:60}"

  # Drift-check: если в REGISTRY помечен ✅ — это zombie, вывести предупреждение
  if [[ "$REGISTRY_DONE" == "true" ]]; then
    DRIFT_ROWS="${DRIFT_ROWS}| ⚠️ **${WP_LABEL}** ${WP_TITLE} | frontmatter=active, REGISTRY=✅ done — archive: \`mv inbox/ → archive/wp-contexts/\` |
"
    continue
  fi

  FOUND=$((FOUND + 1))
  # Запомнить номер — чтобы не дублировать в union-блоке
  SEEN_WP_NUMS="${SEEN_WP_NUMS} ${WP_NUM} "

  GIT_CELL=$(_git_activity_cell "$WP_NUM")
  OUTPUT_ROWS="${OUTPUT_ROWS}| **${WP_LABEL}** ${WP_TITLE} | ${GIT_CELL} |
"
done <<< "$WP_LIST_US"

# --- Union: добавить pending-РП из WeekPlan, которых ещё нет в результатах ---
if [[ -n "$WEEKPLAN_IDS" ]]; then
  while IFS= read -r WP_NUM; do
    [[ -z "$WP_NUM" ]] && continue
    # Пропустить если уже найден через inbox-статус
    [[ " $SEEN_WP_NUMS " == *" $WP_NUM "* ]] && continue
    ROW=$(_wp_list_row "$WP_NUM")
    [[ -n "$ROW" ]] || continue
    IFS=$'\x1f' read -r _ WP_TITLE _ REGISTRY_DONE _ <<< "$ROW"
    # Пропустить если помечен ✅ в REGISTRY
    [[ "$REGISTRY_DONE" == "true" ]] && continue
    [[ -z "$WP_TITLE" ]] && WP_TITLE="WP-${WP_NUM}"
    WP_TITLE="${WP_TITLE:0:60}"
    WP_LABEL="WP-${WP_NUM}"
    FOUND=$((FOUND + 1))
    GIT_CELL=$(_git_activity_cell "$WP_NUM")
    OUTPUT_ROWS="${OUTPUT_ROWS}| **${WP_LABEL}** ${WP_TITLE} | ${GIT_CELL} |
"
  done <<< "$WEEKPLAN_IDS"
fi

# --- Вывод ---
if [[ $FOUND -eq 0 ]] && [[ -z "$DRIFT_ROWS" ]]; then
  echo "<!-- active-wp-sweep: активных РП не найдено -->"
  exit 0
fi

if [[ $FOUND -gt 0 ]]; then
  echo ""
  echo "### 🔄 Активные РП (sweep по inbox/WP-*.md)"
  echo ""
  echo "| РП | Последний коммит (${GIT_DAYS}д) |"
  echo "|----|---------------------------------|"
  printf '%s' "$OUTPUT_ROWS"
  echo ""
fi

if [[ -n "$DRIFT_ROWS" ]]; then
  echo ""
  echo "### ⚠️ Drift: frontmatter=active, REGISTRY=✅ (нужна архивация)"
  echo ""
  echo "| РП | Расхождение |"
  echo "|----|-------------|"
  printf '%s' "$DRIFT_ROWS"
  echo ""
fi
