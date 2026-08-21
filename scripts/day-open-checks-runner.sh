#!/bin/bash
# day-open-checks-runner.sh — парсер и исполнитель bash-блоков из extensions/day-open.checks.md
# see WP-7 Ф-DayOpen-Enforcement DOE2
# NOTE: checks.md is a trusted local source (not shared/untrusted input).

set -uo pipefail
# -u: fail on unset variables
# -o pipefail: catch errors in pipelines
# Intentionally no -e: we collect errors across blocks, not abort on first failure.

IWE="${IWE_ROOT:-$HOME/IWE}"
EXT_DIR="$IWE/extensions"
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

# Same convention as .claude/scripts/load-extensions.sh: single file
# `day-open.checks.md` or split files `day-open.checks.*.md` (issue #466 —
# the old hardcoded single path made the split convention invisible here).
CHECKS_FILES=$(find -L "$EXT_DIR" -maxdepth 1 \( -name "day-open.checks.md" -o -name "day-open.checks.*.md" \) -type f 2>/dev/null | sort)

if [ -z "$CHECKS_FILES" ]; then
  echo "❌ day-open-checks-runner: no day-open.checks*.md found in $EXT_DIR — nothing to check"
  exit 1
fi

ERR_FILE=$(mktemp)
BLOCKS_RUN=0

while IFS= read -r checks_file; do
  # Extract and execute each bash block from this checks file.
  # awk's exit status is intentionally ignored here: it can only fail on a
  # missing/unreadable file, and CHECKS_FILES was just built from `find`
  # results, so that path is already excluded — the real gap this fixes
  # (issue #466) was zero check blocks silently reporting success, not awk
  # itself failing.
  while IFS= read -r -d '' block; do
    BLOCKS_RUN=$((BLOCKS_RUN + 1))
    # Execute block in subshell with set -e so any error is caught
    (
      set -e
      eval "$block"
    ) 2>&1
    EXIT=$?
    if [ $EXIT -ne 0 ]; then
      echo "1" >> "$ERR_FILE"
    fi
  done < <(awk '
    /^```bash$/ { block=""; in_block=1; next }
    /^```$/     { if(in_block){ printf "%s", block; printf "%c", 0 }; in_block=0; next }
    in_block    { block = block $0 "\n" }
  ' "$checks_file")
done <<< "$CHECKS_FILES"

ERRORS=$(wc -l < "$ERR_FILE" | tr -d ' ')
rm -f "$ERR_FILE"

if [ "$BLOCKS_RUN" -eq 0 ]; then
  echo "❌ day-open-checks-runner: found checks file(s) but extracted 0 bash blocks — check the \`\`\`bash fencing. Commit BLOCKED."
  exit 1
fi

if [ "$ERRORS" -gt 0 ]; then
  echo ""
  echo "❌ day-open-checks-runner: $ERRORS/$BLOCKS_RUN block(s) failed. Commit BLOCKED."
  exit 1
else
  echo "✅ day-open-checks-runner: all $BLOCKS_RUN check(s) passed."
  exit 0
fi
