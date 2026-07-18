# How your guide gets assembled

This is the honest breakdown of every input that shapes your guide, and — if you're
running guide-kit standalone, with no account on the IWE platform — what you're
responsible for tracking yourself instead of getting it for free from a subscription.

guide-kit never invents a fact it doesn't have (see the hard-fail policy in
`FORMAT.md`). That cuts both ways: if you don't supply an input below and there's no
platform connection to pull it from, the guide is generated *without* that input,
honestly — not with a guessed substitute.

## Two things that sound alike but aren't

Russian has two words, one letter apart, for two different ideas the platform
tracks about you — mixing them up is an easy and consequential mistake:

- **Ступень (stage)** — how well you're doing *within* one of five roles (Ученик =
  Learner, Интеллектуал, Профессионал, Исследователь, Просветитель), 5 levels
  each. Low stakes: it only tunes how much the guide explains vs. assumes. You are
  allowed to self-report it — there's no council involved, no certificate at stake.
- **Степень квалификации (qualification degree)** — an 8-level ladder (Ученик →
  Работник → Стратег → Специалист → Практик → Мастер → Реформатор → Общественный
  деятель) assigned **only** by the МИМ methodological council, never computed,
  never self-assignable past the first level. guide-kit reads it as context (it
  changes the assumed depth of prior knowledge) and can help you work toward what
  the next one requires — but it cannot grant you one, on the platform or off it.
  Getting a new degree always means going through the council; a subscription
  doesn't skip that step, it just means the platform remembers the answer for you.

## The inputs, one by one

| Input | What it changes in your guide | With a platform subscription | Standalone — you track this yourself |
|---|---|---|---|
| Stage (`rcs.stage_derived`, 1-5 per role) | How much the guide explains vs. assumes | Computed from your actual activity, refreshed automatically | You state it in `profile.yaml`; update it yourself as you actually improve |
| Qualification degree (`qualification_degree.degree`) | The assumed depth of prior knowledge in the writing | Pulled automatically once the council has assigned one | You state your last known, already-certified degree; a *new* one still requires going through the council — subscribing doesn't grant one |
| Bottleneck / mastery gaps (`rcs.bottleneck`, `mastery_by_area`) | What the guide focuses on today | Computed from your data | You state it yourself, or leave it and the planner degrades to a generic focus |
| Quarter/month/week/day horizons (`profile.yaml`: `quarter`, `month`, `week`, `day`) | The larger arc the day's focus is framed against | Synced from the platform's own planning cascade | You fill them in yourself, or the guide works on the bottleneck alone, with no larger-scale narrative |
| Artifacts produced (`profile.yaml.artifacts`) | Avoids repeating what you've already made | Collected automatically | You fill it in, or leave it empty |
| Foundational curriculum (worldview/method cards) | The actual content of a fundamental-topic lesson | Live access to the full, current library | A small public-domain demo set ships in the kit (`demo/`); the full set needs its own source — clone one yourself and point `GUIDE_KIT_CURRICULUM_PATH` / `cards_path` at it |
| Curated world practice (applied topics) | Source material for topics you bring yourself | Searchable through the subscription | You find and vet it yourself |
| Decision log (`decision_log`) | Why today's guide focused on what it did — the audit trail | Same mechanism, same file | Same mechanism, same file — this one doesn't depend on a subscription at all |

## What guide-kit will never do

- Assign or infer a qualification degree. If none is known, the guide is written
  without assuming one — never a guessed "you're probably at level X."
- Let a stale, unmarked local edit silently overrule a fresher platform record. If
  you know your local data disagrees with the platform on purpose (not by
  accident), say so explicitly — see `manual_override` (stage) and
  `use_declared` (degree) in `FORMAT.md`.
- Treat the absence of a subscription as an error. Every row above degrades
  honestly to a narrower, self-tracked version of the same guide — never a broken
  one, never a faked one.
