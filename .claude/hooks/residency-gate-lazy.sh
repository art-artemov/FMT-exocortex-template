#!/bin/bash
# ResidencyGate Point B: Lazy consent check at data access time
# Runs when a function tries to access specific data
# Usage: residency-gate-lazy.sh <function_id> <data_type> <flow_direction> <need_name>

set -e

if [ $# -lt 4 ]; then
  echo "Usage: residency-gate-lazy.sh <function_id> <type> <flow> <name>" >&2
  exit 1
fi

FUNCTION_ID="$1"
DATA_TYPE="$2"
FLOW_DIRECTION="$3"
NEED_NAME="$4"
RESIDENCY_GATE_PY="${CLAUDE_ROOT:-.claude}/.claude/skills/residency-gate/residency-gate.py"

# Check lazy consent
RESULT=$(python3 "$RESIDENCY_GATE_PY" check-lazy "$FUNCTION_ID" "$DATA_TYPE" "$FLOW_DIRECTION" "$NEED_NAME" 2>/dev/null)

ALLOWED=$(echo "$RESULT" | grep -o '"allowed":[^,}]*' | head -1 | grep -o 'true\|false')
REASON=$(echo "$RESULT" | grep -o '"reason":"[^"]*' | sed 's/.*:"//')

if [ "$ALLOWED" != "true" ]; then
  echo "[ResidencyGate] Access denied for $FUNCTION_ID/$NEED_NAME: $REASON" >&2
  exit 1
fi

echo "[ResidencyGate] Access allowed: $REASON" >&2
exit 0
