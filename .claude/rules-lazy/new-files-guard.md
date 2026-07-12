# New-files guard: current/ и docs/ — полная спецификация

> Hot-триггер: `${IWE_GOVERNANCE_REPO:-DS-strategy}/CLAUDE.md` § New-files guard. Этот файл — элаборация (WP-450 Ф1). Источник: peer-audit Claude + Kimi, `sessions/2026-06/2026-06-04-current-docs-audit/report.md`.

**БЛОКИРУЮЩЕЕ.** commit-msg хук блокирует коммит при появлении новых файлов (Added или Renamed-into) в `current/` или `docs/`.

**Критерий для .gitignore:** файл с `generated_at:` в frontmatter или `AUTO-GENERATED` в первых строках — обязан быть в `.gitignore`, не коммитится.

**Bypass:** тег `[allow:current]` или `[allow:docs]` в сообщении коммита.

**После клона:** обязательно `bash scripts/install-hooks.sh` — иначе guard неактивен.
