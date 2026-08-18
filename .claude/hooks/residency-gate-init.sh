#!/bin/bash
# claude-hook: false — sourced consent library с обязательными аргументами
# ResidencyGate Point A: Activation-time consent check
# Runs when a function starts (launchd trigger, day-open, etc.)
# Usage: source residency-gate-init.sh <function_id> <manifest_file>

set -e

if [ $# -lt 2 ]; then
  echo "Usage: source residency-gate-init.sh <function_id> <manifest_file>" >&2
  return 1
fi

FUNCTION_ID="$1"
MANIFEST_FILE="$2"
# CLAUDE_ROOT = project root that CONTAINS .claude/ (default: cwd). The old
# default ".claude" produced ".claude/.claude/skills/..." — a path that never
# exists (issue #323).
RESIDENCY_GATE_PY="${CLAUDE_ROOT:-.}/.claude/skills/residency-gate/residency-gate.py"

# Check consent at activation
RESULT=$(python3 "$RESIDENCY_GATE_PY" check-activation "$FUNCTION_ID" "$MANIFEST_FILE" 2>/dev/null || echo '{"allowed":false,"blocking":["error"]}')

# Parse JSON response
ALLOWED=$(echo "$RESULT" | grep -o '"allowed":[^,}]*' | head -1 | grep -o 'true\|false')
BLOCKING=$(echo "$RESULT" | grep -o '"blocking":\[\([^]]*\)' | sed 's/.*:\[//')

if [ "$ALLOWED" != "true" ]; then
  echo "[ResidencyGate] Function '$FUNCTION_ID' blocked at activation time" >&2
  echo "[ResidencyGate] Blocking reasons: $BLOCKING" >&2
  return 1
fi

return 0
