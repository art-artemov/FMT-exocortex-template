# demo/

Public-domain sample content — enough to run the generator and see a real,
non-empty guide before you've set up any content of your own.

- **`curriculum/`** — one worldview card (`CAT.001.D1`), same file format as
  the platform's real CAT.001 catalog (frontmatter: `id`, `area`,
  `entry_stage`, `context`, `name`). Uses a `.D1`-style ID, never a real
  catalog ID — CAT.001 is loaded from a single directory
  (`GUIDE_KIT_CURRICULUM_PATH`), so a real and a demo catalog can never be
  mixed by accident, but the separate ID range keeps that true even if
  loading ever changes to merge multiple sources.
- **`cards/`** — full card content (JSON, same schema as `generator/prompt.md`
  §`card_content`) for two elements already public in `planner.py`'s
  hardcoded name tables: `CAT.002.A1` (a leisure practice) and
  `CAT.003.METHOD.001` (a learning practice). These use the *real* element
  IDs — a decision made explicitly for this catalog by the pilot (peer
  session 2026-07-16, escalation 1): CAT.002/CAT.003 practices are simple
  enough not to go stale the way the (deliberately time-bound) baseline
  snapshot does, so giving two of them demo content in the open repository
  doesn't create a second, drifting copy of anything.

Nothing here is meant to be a complete catalog — see `DP.SC.056`'s
"no servers, honest provenance" invariant for why the full CAT.001-003
catalogs stay off this repository (`CONCEPT-portable-guide-generator.md`
§340 "Ключевое отклонение").
