#!/usr/bin/env bash
# routing: utility  deterministic=true
# see DP.SC.159, DP.ROLE.059
#
# check-component-parity.sh — asserts setup.sh (fresh install) and update.sh
# deliver the SAME set of .claude/<component>/ directories.
#
# Why a dedicated check (not parity-contract.yaml): the contract verifies that
# named regex patterns appear in both scripts (instance-level). It cannot express
# "both scripts deliver the same component SET" (class-level). The rules-lazy gap
# (CI red on 2026-06-29) slipped because setup.sh hand-maintains its list in a
# for-loop while update.sh hand-maintains it as a glob alternation — three hand
# lists total, no single source. This check diffs the two sets directly.
#
# Exit codes:
#   0 — component sets match
#   3 — mismatch (missing in setup.sh or update.sh)
#   2 — could not extract a list from one of the scripts
#
# Related: peer-session 2026-06-29-03, WP-315 Ф4, DP.SC.125

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
SETUP="$REPO_ROOT/setup.sh"
UPDATE="$REPO_ROOT/update.sh"

if [[ -t 1 ]]; then
  RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
else
  RED=''; GREEN=''; NC=''
fi

for f in "$SETUP" "$UPDATE"; do
  [[ -f "$f" ]] || { echo "ERROR: not found: $f" >&2; exit 2; }
done

# setup.sh: components live in the `for subdir in skills hooks ... ; do` loop that
# copies $TEMPLATE_DIR/.claude/$subdir. Anchor on `for subdir in ... ; do` alone
# (token-order-independent — reordering the loop must not break extraction); the
# non-empty guard below turns any misfire into a loud exit 2.
setup_list=$(
  grep -E 'for subdir in .+; do' "$SETUP" \
    | head -1 \
    | sed -E 's/.*for subdir in (.*); do.*/\1/' \
    | tr ' ' '\n' \
    | grep -v '^$' \
    | LC_ALL=C sort -u
) || true

# update.sh: components live in the `.claude/skills/*|.claude/hooks/*|...` glob
# alternation (case patterns). Pull every .claude/<name>/* capture, drop the
# settings.json file entry (handled separately in both scripts, not a dir).
# Alphabet covers underscore/digit/case so a future dir name (e.g. rules_v2)
# cannot silently drop out of extraction and produce a false-PASS parity.
update_list=$(
  grep -oE '\.claude/[a-zA-Z0-9_-]+/\*' "$UPDATE" \
    | sed -E 's#\.claude/([a-zA-Z0-9_-]+)/\*#\1#' \
    | grep -v '^$' \
    | LC_ALL=C sort -u
) || true

if [[ -z "$setup_list" ]]; then
  echo "ERROR: could not extract component list from setup.sh" >&2; exit 2
fi
if [[ -z "$update_list" ]]; then
  echo "ERROR: could not extract component list from update.sh" >&2; exit 2
fi

echo "=== Component Parity Check ==="
echo "setup.sh delivers:  $(echo "$setup_list" | tr '\n' ' ')"
echo "update.sh delivers: $(echo "$update_list" | tr '\n' ' ')"
echo ""

# Set difference both ways. LC_ALL=C so comm's sort-order assumption matches the
# C-sorted inputs regardless of the runner's locale.
only_setup=$(LC_ALL=C comm -23 <(echo "$setup_list") <(echo "$update_list") || true)
only_update=$(LC_ALL=C comm -13 <(echo "$setup_list") <(echo "$update_list") || true)

if [[ -z "$only_setup" && -z "$only_update" ]]; then
  echo -e "${GREEN}OK: setup.sh and update.sh deliver the same component set${NC}"
  exit 0
fi

echo -e "${RED}FAIL: component set mismatch${NC}"
[[ -n "$only_setup" ]]  && echo "  in setup.sh but NOT update.sh:  $(echo "$only_setup" | tr '\n' ' ')"
[[ -n "$only_update" ]] && echo "  in update.sh but NOT setup.sh:  $(echo "$only_update" | tr '\n' ' ')"
echo ""
echo "→ Add the missing component(s) to both scripts (setup.sh for-loop + update.sh glob)."
exit 3
