---
name: agent-fault
description: Регистрация косяка агента в системе учёта WP-316 L1. Без LLM — детерминированный скрипт без WP Gate.
argument-hint: "record --severity {critical|major|minor} --fault '<description>'"
version: 0.1.0
status: active
layer: L1
agents: none
interaction: one-shot
triggers:
  slash: [/agent-fault]
  phrases: []
gates_required: []
gates_enforced: []
gates_rationale: "детерминированный script-executor; WP Gate и IntegrationGate не применимы"
routing:
  executor: script
  deterministic: true
  script_path: "DS-strategy/scripts/iwe_checklist_memory.py"
---

# /agent-fault — регистрация косяка агента

## When to use

При обнаружении повторяющегося косяка агента — зарегистрировать немедленно через `/agent-fault`.
Примеры: пропуск WP Gate, игнорирование чеклиста, лишние yes/no вопросы, пропуск Pull-on-Touch.
Скилл не требует LLM и не создаёт РП — это запись в базу паттернов WP-316.

## Algorithm

Передать косяк в `iwe_checklist_memory.py record` с указанием severity и описания. Скрипт
живёт в governance-репо (не в `$IWE_SCRIPTS`/шаблоне — согласуется с `script_path` в
frontmatter этого файла), и на части установок его ещё нет (issue #409) — деградировать
без блокировки:

```bash
AGENT_FAULT_SCRIPT="$HOME/IWE/${IWE_GOVERNANCE_REPO:-DS-strategy}/scripts/iwe_checklist_memory.py"
if [ -f "$AGENT_FAULT_SCRIPT" ]; then
  python3 "$AGENT_FAULT_SCRIPT" \
    record --severity major --fault "агент пропустил чеклист"
else
  echo "iwe_checklist_memory.py недоступен на этой установке — косяк не записан в WP-316 L1"
fi
```

Допустимые значения `--severity`: `critical` | `major` | `minor`.

<!-- USER-SPACE -->
<!-- /USER-SPACE -->
