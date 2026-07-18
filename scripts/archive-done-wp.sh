#!/usr/bin/env bash
# routing: helper  called-by=day-close  deterministic=true
# see DP.SC.159, DP.ROLE.059
# archive-done-wp.sh — атомарная архивация завершённого РП
# see DP.M.010, DP.SC.033 (WP-297)
# see WP-5 (фаза «Проверка полноты переноса перед архивацией inbox/WP-N»,
# 2026-07-10) — переписан под папочную конвенцию WP-434 + подключён
# check-wp-transfer-completeness.sh
#
# Шаги:
#   1. Найти inbox/WP-{N}/WP-{N}.md (папочная конвенция WP-434);
#      fallback — устаревший плоский inbox/WP-{N}-*.md.
#   2. Прогнать check-wp-transfer-completeness.sh (warn-not-block).
#   3. Обновить frontmatter: status → done.
#   4. git mv папку (или файл) inbox/ → archive/wp-contexts/.
#
# Использование:
#   bash archive-done-wp.sh <WP_NUM> [IWE_ROOT]
#
# Совместимость: bash 3.2+ (macOS), bash 4+ (Linux)

set -uo pipefail

WP_NUM="${1:-}"
IWE="${2:-${IWE_ROOT:-$HOME/IWE}}"
GOV_REPO="${IWE_GOVERNANCE_REPO:-DS-strategy}"
INBOX="$IWE/$GOV_REPO/inbox"
ARCHIVE="$IWE/$GOV_REPO/archive/wp-contexts"
STRATEGY_REPO="$IWE/$GOV_REPO"
# check-wp-transfer-completeness.sh lives next to this script — resolve relative to
# self so both the root copy and the promoted template copy find their own sibling.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_SCRIPT="$SCRIPT_DIR/check-wp-transfer-completeness.sh"

if [[ -z "$WP_NUM" ]]; then
  echo "Использование: $0 <WP_NUM> [IWE_ROOT]" >&2
  exit 1
fi

# Убрать префикс WP- если передали
WP_NUM="${WP_NUM#WP-}"

WP_DIR="$INBOX/WP-${WP_NUM}"
WP_FILE_FOLDER="$WP_DIR/WP-${WP_NUM}.md"
WP_FILE_FLAT=$(find "$INBOX" -maxdepth 1 -name "WP-${WP_NUM}-*.md" 2>/dev/null | head -1)

if [[ -f "$WP_FILE_FOLDER" ]]; then
  MODE="folder"
  WP_FILE="$WP_FILE_FOLDER"
elif [[ -n "$WP_FILE_FLAT" ]]; then
  MODE="flat"
  WP_FILE="$WP_FILE_FLAT"
  echo "⚠️  WP-${WP_NUM}: найден только устаревший плоский файл (не папочная конвенция WP-434)" >&2
else
  echo "❌ WP-${WP_NUM}: не найден ни $WP_FILE_FOLDER, ни плоский inbox/WP-${WP_NUM}-*.md" >&2
  exit 1
fi

FILENAME=$(basename "$WP_FILE")

if [[ "$MODE" == "folder" ]]; then
  ARCHIVE_TARGET="$ARCHIVE/WP-${WP_NUM}"
  MOVE_SRC="inbox/WP-${WP_NUM}"
  MOVE_DST="archive/wp-contexts/WP-${WP_NUM}"
else
  ARCHIVE_TARGET="$ARCHIVE/$FILENAME"
  MOVE_SRC="inbox/$FILENAME"
  MOVE_DST="archive/wp-contexts/$FILENAME"
fi

echo "📦 Архивирую WP-${WP_NUM} ($MODE): $FILENAME"

# Проверка полноты переноса (warn-not-block) — WP-5, 2026-07-10
if [[ -x "$CHECK_SCRIPT" ]]; then
  bash "$CHECK_SCRIPT" "$WP_NUM" "$IWE" || true
fi

# Guard (issue #224): create-wp.sh уже мог создать pending-заготовку по этому
# же пути (Шаг 2/6 "archive stub") — перезаписываем только саму
# pending-заготовку, не случайный уже-заполненный §Закрытие. Проверка ДО
# правки inbox-файла — иначе при отказе inbox остаётся тронутым (frontmatter
# уже переписан), а archive нет: смоук-тест 2026-07-05 поймал именно этот
# порядок как баг.
if [[ -e "$ARCHIVE_TARGET" ]]; then
  STUB_FILE="$ARCHIVE_TARGET"
  [[ -d "$ARCHIVE_TARGET" ]] && STUB_FILE="$ARCHIVE_TARGET/WP-${WP_NUM}.md"
  if [[ ! -f "$STUB_FILE" ]] || ! grep -q "^status: pending" "$STUB_FILE" 2>/dev/null; then
    echo "❌ $ARCHIVE_TARGET уже существует и не помечен status: pending — не перезаписываю, проверьте вручную" >&2
    exit 1
  fi
  # Это pending-заготовка — безопасно освободить путь под git mv.
  rm -rf "$ARCHIVE_TARGET"
fi

# 1. Обновить frontmatter status → done
# Ищем первый фронтматтер (между --- и ---)
TMP=$(mktemp)
python3 - "$WP_FILE" "$TMP" <<'PYEOF'
import sys, re

src, dst = sys.argv[1], sys.argv[2]
with open(src, "r", encoding="utf-8") as f:
    content = f.read()

# Заменить status: in_progress | status: active → status: done
# Только внутри первого frontmatter блока
lines = content.split("\n")
in_fm = False
fm_closed = False
new_lines = []
for line in lines:
    if line.strip() == "---" and not fm_closed:
        if not in_fm:
            in_fm = True
        else:
            in_fm = False
            fm_closed = True
        new_lines.append(line)
        continue
    if in_fm and re.match(r"^status:\s*(in_progress|active)\s*$", line):
        line = "status: done"
    new_lines.append(line)

with open(dst, "w", encoding="utf-8") as f:
    f.write("\n".join(new_lines))
print("ok")
PYEOF

if [[ $? -ne 0 ]]; then
  echo "❌ Ошибка обновления frontmatter" >&2
  rm -f "$TMP"
  exit 1
fi

# Проверить что статус изменился
if ! grep -q "^status: done" "$TMP" 2>/dev/null; then
  echo "⚠️  frontmatter status уже done или не найден — продолжаю"
fi

cp "$TMP" "$WP_FILE"
rm -f "$TMP"

# 2. git mv (из STRATEGY_REPO); -f — см. guard-комментарий выше (issue #224)
if ! git -C "$STRATEGY_REPO" mv -f "$MOVE_SRC" "$MOVE_DST" 2>/dev/null; then
  echo "⚠️  git mv -f не удался — пробую обычный mv + ручной re-stage"
  mkdir -p "$(dirname "$STRATEGY_REPO/$MOVE_DST")"
  mv "$STRATEGY_REPO/$MOVE_SRC" "$STRATEGY_REPO/$MOVE_DST"
  git -C "$STRATEGY_REPO" add "$MOVE_DST" 2>/dev/null
  if [[ "$MODE" == "folder" ]]; then
    git -C "$STRATEGY_REPO" rm -r --cached "$MOVE_SRC" 2>/dev/null
  else
    git -C "$STRATEGY_REPO" rm --cached "$MOVE_SRC" 2>/dev/null
  fi
fi

echo "✅ WP-${WP_NUM} → $MOVE_DST"
echo "   Следующий шаг: сверить WP-REGISTRY.md (если статус там ещё не done) + коммит"

# ОПТ-7: уведомление related.enables
ARCHIVED_FILE="$STRATEGY_REPO/$MOVE_DST"
[[ "$MODE" == "folder" ]] && ARCHIVED_FILE="$STRATEGY_REPO/$MOVE_DST/WP-${WP_NUM}.md"

ENABLES=$(python3 - "$ARCHIVED_FILE" "$WP_NUM" <<'PYEOF'
import sys, re

archive_file, closed_wp = sys.argv[1], sys.argv[2]
enables = []
try:
    with open(archive_file, "r", encoding="utf-8") as f:
        content = f.read()
    # Найти frontmatter (между первыми ---)
    fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not fm_match:
        sys.exit(0)
    fm = fm_match.group(1)
    # Найти блоки - wp: N / relation: enables
    # YAML-like поиск без yaml-парсера (bash 3.2 совместимость)
    blocks = re.split(r"\n\s*-\s+", fm)
    for block in blocks:
        if re.search(r"relation:\s*enables", block):
            m = re.search(r"wp:\s*(\d+)", block)
            if m:
                enables.append(m.group(1))
except Exception:
    pass

for n in enables:
    print(n)
PYEOF
)

if [[ -n "$ENABLES" ]]; then
  echo ""
  echo "🔓 WP-${WP_NUM} закрыт → разблокированы РП (relation: enables):"
  while IFS= read -r wp_n; do
    echo "   → WP-${wp_n} (проверьте: был ли blocked_by WP-${WP_NUM}?)"
  done <<< "$ENABLES"
fi
