#!/bin/bash
# Extensions Gate Hook
# Event: PreToolUse (matcher: Edit, Write)
# Блокирует прямое редактирование .claude/skills/, memory/protocol-*.md и
# update-manifest.json (манифест определяет, какие скиллы платформенные, —
# правка одного файла отключала бы гейт целиком).
#
# Инвариант (отчёт Константина 14.08.2026, WP-7 Ф71): разрешение выдаётся
# только при ДОКАЗАННО успешной проверке; отсутствие или отказ любого
# инструмента (jq, python3, битый манифест) — блокировка, не пропуск.
# До этого гейт был fail-open: пустой вывод `jq ... 2>/dev/null` читался как
# «скилла нет в манифесте» → разрешение; путь с «..» давал имя чужого скилла;
# симлинк из своей папки на платформенный файл проходил.
#
# Исключения:
#   - FMT-exocortex-template (шаблон — всегда разрешён, кроме манифеста)
#   - author_mode: true в params.yaml (автор шаблона — source-of-truth в IWE,
#     пропагация в FMT через template-sync.sh)
#   - issue #311: новая директория .claude/skills/<name>/, которой нет в
#     update-manifest.json — свой навык, update.sh её не тронет. extend/SKILL.md
#     документирует ровно этот путь как штатный.

block() {
  printf '{"decision": "block", "reason": "⛔ Extensions Gate: %s"}\n' "$1"
  exit 0
}

INPUT=$(cat)

# Fail-closed parsing: no jq → we cannot classify the path at all.
if ! command -v jq >/dev/null 2>&1; then
  block "jq не найден — гейт не может проверить путь. Установи jq (brew install jq / apt install jq) и повтори."
fi
FILE_PATH=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
if [ -n "$INPUT" ] && [ -z "$FILE_PATH" ]; then
  # Matcher is Edit|Write: a payload without file_path is an anomaly, not a norm.
  block "не удалось извлечь путь файла из вызова (битый payload) — правка не классифицируется, блокирую."
fi

# Traversal is rejected before any classification: «..» внутри пути позволяет
# получить имя своего скилла, а записать в платформенный.
case "$FILE_PATH" in
  *"/../"*|"../"*|*"/.."|"..")
    block "путь содержит «..» — не классифицируется, блокирую. Используй прямой путь без переходов вверх."
    ;;
esac

# Resolve symlinks: симлинк из своей папки скилла на платформенный файл обязан
# классифицироваться по ЦЕЛИ, не по имени симлинка. Без резолвера защита молча
# исчезает — поэтому его отказ = блок, не откат к сырому пути.
REAL_PATH=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$FILE_PATH" 2>/dev/null)
if [ -z "$REAL_PATH" ]; then
  block "python3 недоступен или не смог нормализовать путь — без этого не проверить симлинки, блокирую."
fi

# Манифест — always-block, ДО исключения для путей шаблона: управляющая копия
# лежит внутри клона шаблона, и правка её через Edit/Write отключала бы гейт.
# Штатный путь изменения манифеста — bash generate-manifest.sh, не Edit.
case "$REAL_PATH" in
  */update-manifest.json)
    block "update-manifest.json правится только генератором (bash generate-manifest.sh), не напрямую — файл определяет, какие скиллы платформенные."
    ;;
esac

# Проверяем: это L1 файл? (по нормализованному пути — симлинки уже раскрыты)
if printf '%s' "$REAL_PATH" | grep -qE '\.claude/skills/|memory/protocol-'; then

  # Исключение 1: FMT-exocortex-template — всегда разрешён
  if printf '%s' "$REAL_PATH" | grep -q 'FMT-exocortex-template'; then
    exit 0
  fi

  WORKSPACE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

  # Исключение 2: author_mode в params.yaml
  if [ -f "$WORKSPACE_DIR/params.yaml" ] && grep -qE '^author_mode:\s*true' "$WORKSPACE_DIR/params.yaml" 2>/dev/null; then
    exit 0
  fi

  # Исключение 3 (issue #311): свой навык — .claude/skills/<name>/ отсутствует
  # в манифесте платформы, update.sh его не затронет и не затрёт.
  # Требуем ИМЕННО поддиректорию (name/...) — плоский файл прямо в .claude/skills/
  # (напр. SKILL-INDEX.yaml) НЕ подпадает и блокируется ниже.
  if printf '%s' "$REAL_PATH" | grep -qE '\.claude/skills/[^/]+/'; then
    SKILL_NAME=$(printf '%s' "$REAL_PATH" | sed -E 's#.*\.claude/skills/([^/]+)/.*#\1#')
    MANIFEST="$WORKSPACE_DIR/update-manifest.json"
    if [ -n "$SKILL_NAME" ] && [ -f "$MANIFEST" ]; then
      # Разрешение только при ДОКАЗАННО прочитанном манифесте: сначала проверка,
      # что jq видит непустой .files (битый JSON / нет ключа / пустой список =
      # отказ инструмента, не «скилла нет»), и только потом поиск совпадения.
      if jq -e '.files | type=="array" and length>0' "$MANIFEST" >/dev/null 2>&1; then
        IN_MANIFEST=$(jq -r --arg prefix ".claude/skills/${SKILL_NAME}/" \
          '.files[]? | select(.path | startswith($prefix)) | .path' \
          "$MANIFEST" 2>/dev/null | head -1)
        if [ -z "$IN_MANIFEST" ]; then
          exit 0
        fi
      else
        block "манифест платформы не читается (битый JSON или пустой список файлов) — принадлежность скилла не доказать, блокирую. Восстанови update-manifest.json (git checkout или update.sh)."
      fi
    fi
  fi

  # Блокировать для обычных пользователей
  block "платформенные (L1) и пользовательские (L3) файлы — разные слои. Правило (CLAUDE.md §9): Авторская кастомизация → extensions/*.md. Платформенное изменение → FMT-exocortex-template → update.sh. Смешение слоёв = хрупкость при обновлении. Создай или обнови нужный файл в extensions/."
fi

# Разрешить редактирование обычных файлов
echo '{}'
exit 0
