#!/bin/bash
# day-open-checks-runner.sh — парсер и исполнитель bash-блоков из extensions/day-open.checks.md
# see WP-7 Ф-DayOpen-Enforcement DOE2
# NOTE: checks.md is a trusted local source (not shared/untrusted input).

set -uo pipefail
# -u: fail on unset variables
# -o pipefail: catch errors in pipelines
# Intentionally no -e: we collect errors across blocks, not abort on first failure.

IWE="${IWE_ROOT:-$HOME/IWE}"
CHECKS_FILE="$IWE/extensions/day-open.checks.md"
DAYPLAN="${1:-}"

# Find current DayPlan if not provided
if [ -z "$DAYPLAN" ]; then
  DAYPLAN=$(find "$IWE/${IWE_GOVERNANCE_REPO:-DS-strategy}/current" -maxdepth 1 -name "DayPlan *.md" -type f 2>/dev/null | head -1)
fi

if [ -z "$DAYPLAN" ] || [ ! -f "$DAYPLAN" ]; then
  echo "❌ DayPlan not found in current/ — nothing to check"
  exit 1
fi

export FILE="$DAYPLAN"
export CFG="$IWE/${IWE_GOVERNANCE_REPO:-DS-strategy}/exocortex/day-rhythm-config.yaml"
export HOME
export IWE

ERR_FILE=$(mktemp)

# Extract and execute each bash block from checks.md
awk '
/^```bash$/ { block=""; in_block=1; next }
/^```$/     { if(in_block){ print block; print "\x00" }; in_block=0; next }
in_block    { block = block $0 "\n" }
' "$CHECKS_FILE" | while IFS= read -r -d '' block; do
  # Execute block in subshell with set -e so any error is caught
  (
    set -e
    eval "$block"
  ) 2>&1
  EXIT=$?
  if [ $EXIT -ne 0 ]; then
    echo "1" >> "$ERR_FILE"
  fi
done

ERRORS=$(wc -l < "$ERR_FILE" | tr -d ' ')
rm -f "$ERR_FILE"

if [ "$ERRORS" -gt 0 ]; then
  echo ""
  echo "❌ day-open-checks-runner: $ERRORS block(s) failed. Commit BLOCKED."
  exit 1
else
  echo "✅ day-open-checks-runner: all checks passed."
  exit 0
fi
