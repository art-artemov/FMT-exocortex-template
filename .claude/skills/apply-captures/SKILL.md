---
name: apply-captures
description: Разбор extraction-reports со status pending-review — решение R15 (accept/reject/defer), запись в Pack, обновление статуса, коммит. Вызывать при Close при наличии N>0 pending-review отчётов.
argument-hint: "[путь к конкретному отчёту | пусто = все pending-review]"
version: 1.0.0
layer: L1
status: active
triggers:
  slash: [/apply-captures]
  phrases: []
routing:
  executor: sonnet
  deterministic: false
---

# /apply-captures — разбор кандидатов экстрактора

Полная ВДВ-карта цикла: `{{GOVERNANCE_REPO}}/inbox/WP-247-ke-pipeline-vdv.md`
Контракт скилла взят из шагов 5, 6, 6.5, 7 этой карты.

## Scope

**Этот скилл делает:**
- Читает `{{GOVERNANCE_REPO}}/inbox/extraction-reports/*.md` со `status: pending-review`.
- Для каждого кандидата в отчёте — запрашивает решение R15 (accept / reject / defer).
- Accept → опциональная редактура → валидация → запись файла в Pack → обновление MAP → коммит.
- Reject → запись причины + паттерна в `feedback-log.md`.
- Defer → запись причины + `defer_until` в отчёт.
- Обновляет `status` отчёта на `applied` / `partially-applied` / `rejected` / `deferred`.

**Этот скилл НЕ делает:**
- Не запускает агента R2 (экстрактор) — это `/ke` и launchd `extractor.sh`.
- Не создаёт extraction-reports — это R2.
- Не редактирует содержимое captures.md / fleeting-notes.md.

## ВДВ-контракт (шаги 5–7 из ke-pipeline-vdv.md)

```
Вход:   {{GOVERNANCE_REPO}}/inbox/extraction-reports/*.md  со  status: pending-review
Роль:   R15 Валидатор (accept/reject/defer)
        R4 Автор (conditional: редактура при edits_needed: yes)
        Скилл (автоматика записи, валидации, коммита)
Действие:
  Для каждого pending-review отчёта, для каждого кандидата:
    1. Показать кандидата (id, тип, предложенный target_path, текст).
    2. Запросить решение R15 по схеме ниже.
    3. Accept + edits_needed=yes → R4 редактирует текст.
    4. Шаг 6.5: валидация Pack-сущности (frontmatter, уникальность ID, путь).
    5. Accept + valid → записать файл в Pack, обновить MAP, дописать feedback-log (паттерн), коммит.
    6. Reject → записать в feedback-log причину + паттерн.
    7. Defer → записать defer_reason + defer_until в отчёт.
  Обновить status отчёта по итогам.
Выход:
  - Обновлённый Pack (новые файлы сущностей).
  - Обновлённый `{{GOVERNANCE_REPO}}/inbox/feedback-log.md` (reject-паттерны).
  - Отчёт со финальным status (applied / partially-applied / rejected / deferred).
  - Коммит в PACK-* (при accept).
```

## Формат решения R15

Каждый кандидат — структурированное решение:

```yaml
candidate_id: 3
decision: accept        # accept | reject | defer
# --- при accept ---
edits_needed: no        # yes | no
target_path: PACK-digital-platform/pack/.../02-domain-entities/DP.D.NNN.md
# --- при reject ---
reason: "дубликат PD.METHOD.006"
pattern: "проверять существующие METHOD перед предложением нового"
# --- при defer ---
reason: "ждёт ArchGate WP-245"
defer_until: "после WP-245 Ф22"
```

## Шаг 1. Найти pending-review отчёты

```bash
find "${IWE_WORKSPACE:-$HOME/IWE}/{{GOVERNANCE_REPO}}/inbox/extraction-reports" -name "*.md" \
  -exec grep -l "^status: pending-review" {} \; | sort
```

Если `$ARGUMENTS` задан путь — работать только с ним.
Если отчётов нет → сообщить «Нет pending-review отчётов. Ничего делать не нужно.»

## Шаг 2. Для каждого отчёта: показать кандидатов

Прочитать отчёт. Для каждого кандидата (frontmatter + тело) показать:
- `id`, `type`, предложенный `target_path`
- Первые 15-20 строк текста (без служебного frontmatter)
- Флаг `edits_needed` из отчёта (если проставлен R2)

Запросить решение R15 по схеме выше. Один вопрос = один кандидат.

## Шаг 3. Accept — редактура (conditional)

Если `edits_needed: yes` → предложить отредактировать текст совместно с пользователем.
Если `edits_needed: no` → использовать текст as-is из отчёта.

## Шаг 4 (= ВДВ шаг 6.5). Валидация Pack-сущности

Перед записью проверить три условия:

### 4а. Frontmatter по шаблону Pack

Обязательные поля (для большинства Pack-сущностей):
- `id:` — присутствует и соответствует типу (DP.D.NNN, PD.METHOD.NNN и т.д.)
- `type:` — присутствует
- `status:` — присутствует (обычно `draft` или `active`)
- `created:` — присутствует

Источник шаблонов: `DP.ROLE.033` и соседние сущности целевой директории.

### 4б. Уникальность ID

```bash
grep -r "^id: <ID>" ~/IWE/PACK-* | head -5
```

Если совпадение найдено → вернуть R15 на reject: паттерн `«ID уже занят: <путь>»`.

### 4в. Расположение файла

Путь `target_path` должен соответствовать типу сущности:
- `DP.D.*` → `.../02-domain-entities/`
- `DP.METHOD.*` → `.../03-methods/`
- `DP.ROLE.*` → `.../02-domain-entities/` или `.../roles/`
- `DP.SOTA.*` → `.../06-sota/`
- `PD.*` → аналогичная структура в `PACK-personal/` или доменном Pack'е

При сомнении — проверить соседние файлы в целевой директории.

**Результат валидации:**
- `valid` → переходить к Шагу 5
- `invalid` + причина → reject этого кандидата, записать в feedback-log, продолжить следующий кандидат

## Шаг 5. Запись в Pack и коммит

### 5а. Записать файл

```
Write target_path (из решения R15) ← текст кандидата (после редактуры если была)
```

### 5б. Обновить MAP (если есть)

Pack-реестры обычно в:
- `PACK-digital-platform/pack/.../MAP.md`
- `hard-distinctions.md` — при добавлении DP.D.*

Проверить, есть ли MAP в целевой директории. Добавить строку.

### 5в. Записать в feedback-log (при reject)

Файл: `{{GOVERNANCE_REPO}}/inbox/feedback-log.md` (создать если нет).
Формат записи:

```markdown
## <дата> — reject кандидата <id> из отчёта <filename>
**Причина:** <reason>
**Паттерн (для R2):** <pattern>
```

### 5г. Коммит

```bash
git add <target_path> [MAP если был] && git commit -m "feat(KE apply): <id> — <краткое название>"
```

Репо для коммита: то же, что `target_path` (PACK-digital-platform, PACK-personal и т.д.)

## Шаг 6. Обновить status отчёта

Правила:
- Все кандидаты resolved (accept/reject/defer) → `applied` если ≥1 applied, иначе `rejected` если все reject, `deferred` если есть defer без applied.
- Часть кандидатов pending → `partially-applied`.

Обновить `status:` в frontmatter отчёта и сохранить файл.

## Шаг 7. Итоговый отчёт

Вывести сводку:
```
Отчёт: <filename>
  Кандидатов всего: N
  Accept: N_a (записано в Pack)
  Reject: N_r (паттерны в feedback-log)
  Defer: N_d
  Статус отчёта: applied / partially-applied / rejected / deferred
```

## Состояния отчёта (справка)

| Статус | Очистка Session-Prep |
|--------|----------------------|
| `pending-review` | Не трогать |
| `partially-applied` | Не трогать |
| `deferred` | Не трогать |
| `applied` | Удалять через 7 дней |
| `rejected` | Удалять через 7 дней |
| `no-pending` | Удалять через 7 дней |

## Интеграция в рабочий процесс

**DayPlan (ежедневный обзор):** Шаблон DayPlan содержит секцию «Наработки ИИ → Экстрактор» с обзором:
- N pending-review отчётов
- Дата самого старого отчёта
- SLA-статус (✅ в норме / ⚠️ истёк)
- Напоминание: разбор в отдельной сессии `/apply-captures`

**Close Gate:** `extensions/protocol-close.checks.md` — при N > 0 pending-review выдаёт предупреждение ⚠️ и SLA-напоминание (DP.SC.004 §Hard gate). Soft gate — не блокирует Close, но требует решения ≤24ч.

**Полный цикл:**
1. Cron / `extractor.sh` → создаёт `extraction-reports/*.md` (status: `pending-review`)
2. Day Open → секция «Наработки ИИ → Экстрактор» в DayPlan показывает N ожидающих
3. Close → `protocol-close.checks.md` напоминает о SLA
4. Пользователь запускает `/apply-captures` в отдельной сессии → R15 разбор → запись в Pack
