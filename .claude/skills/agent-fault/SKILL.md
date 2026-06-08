---
name: agent-fault
description: Register an agent fault in the WP-316 tracking system (L1). No LLM — deterministic script.
argument-hint: "record --severity {critical|major|minor} --fault '<description>'"
routing:
  executor: script
  deterministic: true
  script_path: DS-strategy/scripts/iwe_checklist_memory.py
---

# Agent Fault Registrar

Задача: передать косяк агента в `iwe_checklist_memory.py record`.

Использование:
```bash
python3 "${IWE_SCRIPTS:-$HOME/IWE/scripts}/iwe_checklist_memory.py" record --severity major --fault "агент пропустил чеклист"
```
