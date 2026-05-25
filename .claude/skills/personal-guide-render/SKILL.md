---
name: personal-guide-render
description: Собирает (или пересобирает) персональное руководство в УЖЕ существующем репо `personal-guide` (плоское имя, один на пилота) — читает RCS из Память.Derived, выбирает заготовки stage×domain, пишет 6 файлов через personal_write. Используй когда пилот просит «пересобери руководство», «обнови мой план», «обнови methods» — или когда репо создан, а контента ещё нет.
argument-hint: "[необязательно: override домена — knowledge-worker / generic] [необязательно: first-run — пропустить Шаг 5 архивации, используется при делегировании из /personal-guide-start]"
experimental: true
sunset: "после DONE WP-222 (Портной, ~июнь 2026) и WP-149 Ф6 (книга ЛР v3)"
related: [WP-245, WP-222, WP-149, PD.FORM.089, PD.CAT.003, personal-guide-start]
routing:
  executor: sonnet
  deterministic: false
---

# Render персонального руководства

> ⚡ **Алгоритм, не диалог.** Выполни шаги 1-7 последовательно. Вопросы — только если `dt_read_digital_twin` вернул пустой результат или нет ни одного RCS-слота (W/M1/M2/M4). Наличие знаний о домене в MCP (Pack, сущности, концепции) ≠ Память.Derived. Диагностика «что ты создаёшь», «какова твоя главная система» — запрещена.

> **Experimental MVP-скилл** (IntegrationGate exception по WP-245 Ф28 Open Decision #7). Парный к `/personal-guide-start`: тот создаёт репо (один раз), этот наполняет/обновляет содержание (N раз).

## Контракт скилла

- **Вход:** существующий GitHub-репо `personal-guide` под аккаунтом пилота (создаётся через `/personal-guide-start` или вручную; имя константно для всех пилотов — у каждого один личный аккаунт = один репо). Активная подписка «Бесконечное развитие» (DP.SC.112). Доступ к `dt_read_digital_twin`, `personal_write`.
- **Выход:** 6 файлов (`README.md`, `profile.md`, `worldview.md`, `methods.md`, `weekly/<YYYY-Www>.md`, `daily/<YYYY-MM-DD>.md`) перезаписаны актуальной версией под текущий RCS+домен. Прежние weekly/daily при пересборке — в `history/` (не удаляются). При первом запуске (`first-run`) дополнительно — раздача 5 скиллов в `.claude/skills/` пилотского репо (см. Шаг 6.7), чтобы они работали в любом канале Claude Code включая `claude.ai/code`.
- **Время:** ≤5 мин на пересборку (без диалога), ≤15 мин с диалогом сбора недостающего профиля.
- **Не делает:** не создаёт репо (это `/personal-guide-start`); не считает баллы (WP-109/WP-121); не запускает по расписанию (Портной, WP-222).

## Шаг 1. Прочитать Память.Derived

Вызови `dt_read_digital_twin(path: "/")`. Извлеки:

- **RCS-слоты:** `W`, `M1`, `M2`, `M3`, `M4`, `IT`, `A` с `baseline` (PD.FORM.089 §3). Если слотов нет — задай 4–5 уточняющих вопросов диалогом по рубрикам PD.FORM.089 §4 (минимум W/M1/M2/M4 для определения ступени). **Лимит диалога: ≤7 мин, ≤5 вопросов.** Без ответа — консервативно: все baseline=2, ступень Практикующий, домен generic.
- **Bottleneck:** слот с минимальным baseline из {W, M1, M2, M4}. Tie — пилот выбирает.
- **M3-домен:** `knowledge-worker` если M3 говорит «разработка / аналитика / архитектура / продакт / консалтинг в IT». Иначе `generic`. Override через аргумент скилла.
- **dissatisfactions:** 1–3 неудовлетворённости из Персоны-снимка. Нет — спросить одним вопросом.

## Шаг 2. Вычислить ступень

```
stage_raw = min(W.baseline, M1.baseline, M2.baseline, M4.baseline)
```

| stage_raw | Ступень | Заготовка |
|-----------|---------|-----------|
| 1 | Случайный | **НЕТ заготовки** — Шаг 2a |
| 2 | Практикующий | `stage-2-practicing.md` |
| 3 | Систематический | `stage-3-systematic.md` |
| 4 | Дисциплинированный | `stage-4-disciplined.md` |
| 5 | Проактивный | **НЕТ заготовки** — Шаг 2b |

### Шаг 2a. Ступень 1 — fallback

Не пиши полный core. Перезапиши только:
- `README.md` с заметкой про минимальный bootstrap для Случайного и инструкцию вызвать `/personal-guide-render` снова через 7-10 дней
- `profile.md` с одним вопросом «Какая неудовлетворённость привела тебя сюда?» + ссылкой на METHOD.001 степень 1

### Шаг 2b. Ступень 5 — fallback

Программа ЛР закончена. Перезапиши `README.md` указанием перейти в «Рабочее развитие» (WP-194). Остальные файлы не трогай.

## Шаг 3. Выбрать доменную вставку

Из `PACK-personal/pack/personal-development/04-work-products/personal-guide-seeds/`:
- `knowledge-worker` → `domain-knowledge-worker.md`
- `generic` → `domain-generic.md`

Неуверенность → `domain-generic.md`.

## Шаг 4. Прочитать заготовки

Прочитай 2 выбранных файла:
- ступенная: `stage-2-practicing.md` | `stage-3-systematic.md` | `stage-4-disciplined.md`
- доменная: `domain-knowledge-worker.md` | `domain-generic.md`

Плейсхолдеры:

| Плейсхолдер | Источник |
|-------------|----------|
| `{RCS.W}`, `{RCS.M1}`, `{RCS.M2}`, `{RCS.M4}` | Шаг 1 + рубрика PD.FORM.089 §4 |
| `{bottleneck}` | Шаг 1 |
| `{dissatisfactions}` | Шаг 1 |
| `{phase}` | PD.FORM.087 §5: ст. 2 → «Я могу меняться / Я — система», ст. 3 → «Окружение влияет на меня», ст. 4 → «Мир — система, и я в ней деятель» |
| `{domain.work_type}` | M3-слот из Память.Derived. Пусто — «уточним в первом диалоге» |
| `{domain.examples}` | 2–3 примера из Память.Derived. Нет — общие из доменной вставки |
| `{domain.focus_area}` | (только `domain-generic.md`) направление из Память.Derived / dissatisfactions. Пусто — «впиши сам» |

## Шаг 5. Архивировать прежние weekly/daily (только при пересборке)

Если в репо уже есть `weekly/<YYYY-Www>.md` или `daily/<YYYY-MM-DD>.md` за прошлые периоды — переместить в `history/<period>.md` через `personal_write`. Текущую неделю/день — НЕ архивировать (они будут перезаписаны Шагом 6).

При первом запуске (после `/personal-guide-start`) — пропустить.

## Шаг 6. Записать 6 файлов

Через `personal_write(source: "personal-guide", path: ..., content: ...)` — имя источника константа для всех пилотов.

### 6.1. `README.md`

```markdown
# Персональное руководство: {ФИО или GitHub-login}

> Собрано/обновлено скиллом /personal-guide-render {YYYY-MM-DD}.
> Ступень: {ступень} (PD.FORM.003). Домен: {домен}.

## Структура

- `profile.md` — RCS-профиль и ритм
- `worldview.md` — мировоззренческая фаза и мемы
- `methods.md` — методы под bottleneck
- `weekly/` — гипотезы недель
- `daily/` — тактика дней
- `history/` — архив прошлых weekly/daily

## Как обновлять

Это живой репо. Чтобы пересобрать — вызови `/personal-guide-render` снова (после изменений в Память.Derived) или попроси в чате:
- «Собери план на завтра» → новый `daily/<дата>.md`
- «Переделай methods.md под проект X» → пересборка методов
- «Итоги недели» → архив `weekly/<неделя>.md` в `history/` + новая гипотеза

Автоматизация по расписанию — Портной (WP-222) летом.

## Источники

- Заготовка ступени: `PACK-personal/.../personal-guide-seeds/stage-{N}-{name}.md`
- Доменная вставка: `PACK-personal/.../personal-guide-seeds/domain-{kw|generic}.md`
- RCS-модель: `PACK-personal/.../formalizations/PD.FORM.089-learner-rcs.md`
```

### 6.2. `profile.md`

Из «Блок → profile.md» ступенной заготовки + раздела «Как подставляется в профиль» доменной вставки. Все плейсхолдеры — из Шага 1.

### 6.3. `worldview.md`

Из «Блок → worldview.md» ступенной заготовки. Подставь `{phase}`. В конце +1 строка: «Мемы в работе на этой неделе: [dissatisfactions]».

### 6.4. `methods.md`

Из «Блок → methods.md» ступенной заготовки для конкретного bottleneck (выбери ветку). + таблица «Типы работ, в которые встраиваются методы» из доменной вставки.

### 6.5. `weekly/<YYYY-Www>.md`

Текущая ISO-неделя. Из «Блок → weekly/…» ступенной заготовки. Реальная дата начала недели.

### 6.6. `daily/<YYYY-MM-DD>.md`

Сегодняшняя дата. Из «Блок → daily/…» ступенной заготовки.

### 6.7. Раздача скиллов в `.claude/skills/` пилотского репо

**Зачем:** скиллы (`/lesson`, `/lesson-close`, `/connect-guide`, `/personal-guide-render`, `/personal-guide-start`) живут в `~/IWE/.claude/skills/` платформы. При работе пилота в **claude.ai/code** (cloud sandbox) user-global `~/.claude/skills/` не пробрасывается. Чтобы скиллы работали в любом канале (VS Code, CLI, browser), нужно их положить в **сам репо** пилота.

Идемпотентная проверка:
1. Через `personal_search(source: "personal-guide", path: ".claude/skills/lesson/SKILL.md")` проверь, есть ли уже скилл в репо.
2. Если нет ИЛИ если запуск `first-run` — записать пять скиллов:

```python
SKILLS_TO_DISTRIBUTE = [
    "lesson/SKILL.md",
    "lesson-close/SKILL.md",
    "connect-guide/SKILL.md",
    "personal-guide-render/SKILL.md",
    "personal-guide-start/SKILL.md",
]

for skill_path in SKILLS_TO_DISTRIBUTE:
    content = Read(f"~/IWE/.claude/skills/{skill_path}")
    personal_write(
        source="personal-guide",
        path=f".claude/skills/{skill_path}",
        content=content,
    )
```

3. После раздачи — пилот может открыть репо в `claude.ai/code` и сразу использовать `/lesson`, `/lesson-close` и т.д. без локальной установки.

**Failure mode:** если `~/IWE/.claude/skills/` недоступен (платформа другая) — пропустить шаг с warning. Не блокер для остальных 6 файлов.

### 6.8. Reflection-template в `history/` (при first-run)

**Зачем:** пилот ежедневно (≤5 мин) записывает рефлексию по фиксированной форме. Шаблон даёт формат, не уходит в свободный текст. Портной при следующем render читает ответы и подстраивает завтрашний `daily/`.

Идемпотентная проверка:
1. Через `personal_search(source: "personal-guide", path: "history/reflection-template.md")` проверь, есть ли уже template в репо.
2. Если нет ИЛИ если запуск `first-run` — записать шаблон:

```python
template_content = Read("~/IWE/.claude/skills/personal-guide-render/templates/reflection-template.md")
personal_write(
    source="personal-guide",
    path="history/reflection-template.md",
    content=template_content,
)
```

3. Подсказать пилоту в Шаге 7 подтверждения:
   - «Чтобы записать рефлексию: скопируй `history/reflection-template.md` → `history/<дата>-reflection.md`, заполни, закоммить»

**Обратный контракт (Портной → reflection):**
- В Шаге 1 следующего render — после `dt_read_digital_twin` дополнительно выполнить `personal_search(source: "personal-guide", path: "history/", pattern: "*-reflection.md")` за последние 7 дней.
- Ответ на «Что узнал» (раздел 3) → сигнал для PD.FORM.087 фазового перехода (Шаг 2 проверки ступени).
- Ответ на «Что завтра» (раздел 5) → input для пересборки `daily/<завтра>.md` (Шаг 6.6).

## Шаг 7. Подтверждение пилоту

```
Руководство в personal-guide обновлено.
Ступень: {ступень} ({stage_raw} = min(W={W}, M1={M1}, M2={M2}, M4={M4})).
Bottleneck: {bottleneck}.
Домен: {домен}.

Открой: code https://github.com/{login}/personal-guide
Изменилось: {список переписанных файлов; если первый запуск — все 6}.
```

## Failure modes

| Симптом | Причина | Решение |
|---------|---------|---------|
| 401 от Gateway | нет подписки или истёк JWT | Обновить Ory-сессию, повторить |
| Память.Derived пустая | RCS ещё не инициализирован | Диалог 5 вопросов → консервативный профиль |
| `personal_write` 404 на репо | репо не создан | Вызвать `/personal-guide-start` сначала |
| `personal_write` не сработал для weekly/ | подпапка не существует | Gateway создаёт автоматически. Если упало — уточнить путь |
| Пилот ст. 1 или 5 | см. Шаг 2a/2b | Минимальный fallback |

## Что скилл НЕ делает (граница)

- Не создаёт репо — это `/personal-guide-start` (`create_repository`).
- Не генерирует следующий `daily`/`weekly` автоматически — пилот просит в чате.
- Не считает баллы — WP-109/WP-121.
- Не обновляет Память.Derived по итогам недели — Портной + WP-203.
- Не читает коммиты/метрики — WP-203 Оркестратор.

Когда Портной (WP-222) выйдет — этот скилл уйдёт в архив.
