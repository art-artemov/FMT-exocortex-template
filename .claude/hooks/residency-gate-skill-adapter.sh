#!/bin/bash
# claude-hook: true
# Event: PreToolUse (matcher: Skill)
#
# Mechanizes ResidencyGate Point A (activation-time consent) for the one place
# Claude Code itself knows "a function is starting": the Skill tool call. Before
# this hook, a skill author had to remember to `source residency-gate-init.sh`
# at the top of their own script — a cognitive gate (issue #323, WP-7
# ResidencyGate-Event-Adapter): nothing enforced the call existed, so a skill
# with declared data_needs but a forgotten source line ran with no consent
# check at all. This hook reads the same manifest (SKILL.md `data_needs`) and
# runs the same check (residency-gate.py check-activation) unconditionally,
# before the skill's own code runs — the check now happens whether or not the
# skill remembered to ask for it.
#
# Scope, honestly stated: this covers Point A only, and only for skills
# invoked through Claude Code's own Skill tool. Point B (lazy, mid-execution
# data access — "about to fetch the digital twin right now") has no Claude
# Code tool-call boundary to hook: it fires from inside a skill's own running
# code, not from a tool call Claude Code can see. Point B stays a library call
# (residency-gate-lazy.sh) by design, not a gap this adapter forgot. The same
# is true for functions that never go through Claude Code at all (day-open's
# own launchd-triggered pipeline, bot handlers) — residency-gate-init.sh
# remains their integration point; there is no Claude Code hook to mechanize
# for a process Claude Code never launches.
set -euo pipefail

INPUT=$(cat)
SKILL_NAME=$(jq -r '.tool_input.skill // empty' <<<"$INPUT" 2>/dev/null || true)
[ -z "$SKILL_NAME" ] && exit 0

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "$HOOK_DIR/../.." && pwd -P)"
MANIFEST="$PROJECT_ROOT/.claude/skills/$SKILL_NAME/SKILL.md"

# No manifest, or the skill directory doesn't exist under this project root:
# not this hook's business to validate skill names — that's the Skill tool's
# own resolution. Absence of a manifest is not a data_needs declaration to
# enforce; residency-gate.py itself already treats "no needs found" as
# allowed, so a skill with no data_needs block reaches the same place either
# way, just without a subprocess.
[ -f "$MANIFEST" ] || exit 0

RESIDENCY_GATE_PY="$PROJECT_ROOT/.claude/skills/residency-gate/residency-gate.py"
[ -f "$RESIDENCY_GATE_PY" ] || exit 0

RESULT=$(python3 "$RESIDENCY_GATE_PY" check-activation "$SKILL_NAME" "$MANIFEST" 2>&1) && RC=0 || RC=$?

if [ "$RC" -eq 0 ]; then
  exit 0
fi

# check-activation exits 1 on both "blocked" and "malformed declaration"
# (ManifestError) — the library's own fail-closed choice (see residency-gate.py
# check-activation: a malformed manifest blocks activation, it does not warn
# and continue). This hook does not second-guess that: any non-zero exit here
# blocks the skill the same way, with the library's own reason surfaced.
BLOCKING=$(jq -r '.blocking // [] | join("; ")' <<<"$RESULT" 2>/dev/null || echo "$RESULT")
echo "BLOCKED: ResidencyGate — skill '$SKILL_NAME' requires data consent not yet granted." >&2
echo "  $BLOCKING" >&2
echo "  Выдать согласие: python3 $RESIDENCY_GATE_PY grant $SKILL_NAME <type> <flow> <name>" >&2
exit 2
