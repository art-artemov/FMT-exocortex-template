---
name: consent
description: Manage consent in learning.tracking_consent — opt-in / opt-out / status / revoke. Required for the stage_evaluator worker (WP-253 Block 2). GDPR-compliant.
argument-hint: "status | opt-in [scope] | opt-out | revoke"
version: 1.0.0
layer: L1
status: active
triggers:
  slash: [/consent]
  phrases: []
routing:
  executor: script
  deterministic: true
  script_path: "scripts/iwe-consent.sh"
  optimization_priority: 1
---

# Consent — управление согласием на трекинг

> **Назначение:** пилот сам управляет своим consent на обработку поведенческих данных (события day_plan_*, wp_*, w_reflections и т.д.). Без `opt_in=TRUE` worker `stage_evaluator` пропускает пилота.
>
> **Архитектурный принцип:** consent хранится в `learning.tracking_consent` (BC = `learning`, не персона). Это разрешение на агрегирование, не персональные данные.

## Аргументы

- `status` (default) — показать текущее состояние consent
- `opt-in [scope1,scope2,...]` — дать согласие (default scope: `stage_evaluation`)
- `opt-out` — отозвать согласие (opt_in=FALSE, история сохраняется)
- `revoke` — полное удаление row (GDPR right to erasure)

## Шаг

```bash
bash "$IWE_SCRIPTS/route-task.sh" --skill consent --args "$ARGUMENTS"
```

Скрипт читает `IWE_OWNER_ORY_UUID` из окружения. Пишет через роль `consent_writer` (миграция 113); fallback на `DATABASE_URL_LEARNING_DIRECT`.

## Возможные scopes

- `stage_evaluation` — оценка ступени мастерства через RCS-индикаторы (FORM.089)
- `club_activity` — учёт активности в клубе (WP-296, post/topic)

## Примеры

```bash
/consent status
/consent opt-in                              # default: stage_evaluation
/consent opt-in stage_evaluation,club_activity
/consent opt-out                             # сохраняет данные, отключает обработку
/consent revoke                              # удаляет row полностью
```

## Различение opt-out vs revoke

- **opt-out** — пилот говорит «не обрабатывайте больше», но данные остаются для аудита. Worker пропускает.
- **revoke** — пилот реализует право на удаление (GDPR). Row удалена; для повторного включения нужен новый opt-in.

> **Note:** удаление *production-данных* (events, reflections, transitions) — отдельный процесс через `anonymization_worker`. Эта команда управляет только записью в `tracking_consent`.

## Зависимости

- Миграция `113-consent-writer-grants.sql` (в директории миграций инфраструктурного репозитория)
- Privacy spec: [`B7.3.6-stage-evaluation-privacy-spec.md`](../../../DS-ecosystem-development/C.IT-Platform/C2.IT-Platform/C2.2.Architecture/Data-Governance/B7.3.6-stage-evaluation-privacy-spec.md)
