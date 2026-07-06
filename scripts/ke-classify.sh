#!/bin/bash
# ke-classify.sh — классификатор captures-отчёта для auto-batch
# see: peer-сессия 2026-05-30-07-gap-list-day-open подэтап 5
# see: WP-356 «Pipeline Day Open: auto-run checks»
#
# Назначение: определить, можно ли отчёт принять автоматически (Haiku/trivial)
#             или требуется human-review.
#
# Алгоритм (peer-консенсус):
# 1. Primary: frontmatter `domain:` tag.
#    - domain не указан → auto-reject (pending-review, no tag).
#    - domain ∈ {system, infrastructure, meta-skill} → блок auto-accept.
#    - domain ∈ {course-content, personal-notes, bot-conversation} → проверить Secondary.
#    - другой domain → pending-review (неизвестная категория).
# 2. Secondary (для разрешённых domain):
#    - Объём тела (без frontmatter) ≤30 строк
#    - Нет regex-матчей по путям: `.claude/`, `scripts/`, `extensions/`, `memory/feedback_*.md`
#    Оба условия → auto-accept. Иначе → pending-review.
#
# Вывод stdout одной строкой:
#   AUTO_ACCEPT
#   PENDING_REVIEW: <причина>
#
# Использование:
#   bash ke-classify.sh <path-to-capture.md>
#
# Exit code:
#   0 — auto-accept
#   1 — pending-review (с причиной в stdout)
#   2 — ошибка (файл не найден / не читается)

set -uo pipefail

FILE="${1:-}"
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  echo "PENDING_REVIEW: file not found or not specified"
  exit 2
fi

# Извлечь domain tag из frontmatter
DOMAIN=$(awk '/^---$/{p++; next} p==1 && /^domain:/ {sub(/^domain:[[:space:]]*/, ""); gsub(/^["'"'"'[:space:]]+|["'"'"'[:space:]]+$/, ""); print; exit}' "$FILE" 2>/dev/null)

if [ -z "$DOMAIN" ]; then
  echo "PENDING_REVIEW: no domain tag in frontmatter"
  exit 1
fi

case "$DOMAIN" in
  system|infrastructure|meta-skill)
    echo "PENDING_REVIEW: domain=$DOMAIN (system/meta-skill never auto-accept)"
    exit 1
    ;;
  course-content|personal-notes|bot-conversation)
    # Разрешённые domain — продолжить проверки
    ;;
  *)
    echo "PENDING_REVIEW: unknown domain=$DOMAIN"
    exit 1
    ;;
esac

# Объём тела (после frontmatter)
BODY_LINES=$(awk 'BEGIN{p=0} /^---$/{p++; next} p>=2 {print}' "$FILE" | wc -l | tr -d ' ')
if [ "$BODY_LINES" -gt 30 ]; then
  echo "PENDING_REVIEW: body too long ($BODY_LINES lines > 30)"
  exit 1
fi

# Regex по путям к коду/feedback
if grep -qE '\.claude/|scripts/|extensions/|memory/feedback_' "$FILE"; then
  MATCHES=$(grep -oE '\.claude/[^[:space:]]*|scripts/[^[:space:]]*|extensions/[^[:space:]]*|memory/feedback_[^[:space:]]*' "$FILE" | head -2 | tr '\n' ' ')
  echo "PENDING_REVIEW: contains code/feedback paths ($MATCHES)"
  exit 1
fi

echo "AUTO_ACCEPT"
exit 0
