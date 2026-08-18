#!/bin/bash
# check-critical-files-map.sh — WP-529 Ф1 acceptance check for
# docs/critical-files-map.yaml: (1) every category/special_route references
# a bash array that still exists in generate-manifest.sh (catches the map
# silently drifting from the real classification), (2) every git-tracked
# file lands in exactly one delivery category — none skipped, none double-
# counted, (3) every category and special_route has a non-empty owner
# (category only) and proof_of_delivery.
#
# Reuses generate-manifest.sh's own classification arrays instead of
# re-implementing them — a second independent classifier would drift from
# the real one exactly like update-manifest.json itself drifted (WP-529,
# found 2026-08-18).
#
# Usage: bash scripts/check-critical-files-map.sh
# Exit 0 = map is consistent with the tree. Exit 1 = a check failed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAP="$SCRIPT_DIR/docs/critical-files-map.yaml"
GENERATOR="$SCRIPT_DIR/generate-manifest.sh"
MANIFEST="$SCRIPT_DIR/update-manifest.json"

[ -f "$MAP" ] || { echo "ERROR: $MAP не найден"; exit 2; }
[ -f "$GENERATOR" ] || { echo "ERROR: $GENERATOR не найден"; exit 2; }

# generate-manifest.sh regenerates $MANIFEST as a side effect — same
# technique scripts/verify-manifest.sh already uses safely in CI.
BACKUP=$(mktemp)
WORKDIR=$(mktemp -d)
trap 'cp "$BACKUP" "$MANIFEST" 2>/dev/null; rm -rf "$BACKUP" "$WORKDIR"' EXIT
cp "$MANIFEST" "$BACKUP"

# Sourced *from this script* generate-manifest.sh would see $0 pointing at
# this file (bash keeps $0 unchanged across `source`), so its own
# `dirname "$0"` would resolve to scripts/ instead of the repo root. Run it
# in a throwaway `bash -c` invocation where $0 is set explicitly to
# $GENERATOR, then hand only the specific arrays back via `declare -p`.
ARRAY_DUMP=$(bash -c 'source "$0" >/dev/null; declare -p \
    SKIP_PATTERNS EXCLUDED_PATTERNS EXCLUDED_EXACT EXCLUDED_SCRIPTS \
    FILES_EXCLUDE_PATTERNS FILES_EXCLUDE_EXACT GITHUB_EXPLICIT_INCLUDE \
    GITHUB_CI_ONLY_EXCLUDE SETUP_EXPLICIT_INCLUDE SCRIPT_CONTRACT_EXPLICIT_INCLUDE \
    FILES EXCLUDED_PATHS' "$GENERATOR")
eval "$ARRAY_DUMP"

FAIL=0
fail() { echo "  ❌ $*" >&2; FAIL=1; }
ok() { echo "  ✅ $*"; }

echo "[1/3] Блоки generate-manifest.sh, на которые ссылается карта..."
python3 - "$MAP" > "$WORKDIR/referenced_blocks.txt" <<'PY'
import re
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as fh:
    data = yaml.safe_load(fh)

blocks = set()
for cat in data.get("categories", []):
    val = cat.get("derived_from_block") or ""
    if val.startswith("("):
        continue  # free-text — no literal array to check
    blocks.update(name.strip() for name in re.split(r",\s*", val) if name.strip())
print("\n".join(sorted(blocks)))
PY

while IFS= read -r block; do
    [ -z "$block" ] && continue
    if declare -p "$block" 2>/dev/null | grep -q '^declare -a'; then
        ok "$block существует в generate-manifest.sh"
    else
        fail "$block, на который ссылается карта, не найден как массив в generate-manifest.sh — карта разошлась с кодом"
    fi
done < "$WORKDIR/referenced_blocks.txt"

echo "[2/3] Покрытие: каждый git-tracked файл — ровно в одной категории..."
declare -A FILES_SET EXCLUDED_SET
for f in "${FILES[@]}"; do FILES_SET["$f"]=1; done
for f in "${EXCLUDED_PATHS[@]}"; do EXCLUDED_SET["$f"]=1; done

is_in() {
    local rel="$1"; shift
    local item
    for item in "$@"; do [ "$rel" = "$item" ] && return 0; done
    return 1
}

TOTAL=0
INVISIBLE_VCS=0
INVISIBLE_SETUP=0
INVISIBLE_USERSPACE=0
UNCLASSIFIED=()

while IFS= read -r rel; do
    TOTAL=$((TOTAL + 1))
    [ -n "${FILES_SET[$rel]:-}" ] && continue
    [ -n "${EXCLUDED_SET[$rel]:-}" ] && continue

    matched=false
    for pattern in "${SKIP_PATTERNS[@]}"; do
        case "$rel" in "$pattern"*) matched=true; break ;; esac
    done
    [ "$(basename "$rel")" = ".gitkeep" ] && matched=true
    if $matched; then INVISIBLE_VCS=$((INVISIBLE_VCS + 1)); continue; fi

    if [[ "$rel" == setup/* ]] && ! is_in "$rel" "${SETUP_EXPLICIT_INCLUDE[@]}"; then
        INVISIBLE_SETUP=$((INVISIBLE_SETUP + 1)); continue
    fi

    for pattern in "${FILES_EXCLUDE_PATTERNS[@]}"; do
        case "$rel" in "$pattern"*) matched=true; break ;; esac
    done
    is_in "$rel" "${FILES_EXCLUDE_EXACT[@]}" && matched=true
    if $matched; then INVISIBLE_USERSPACE=$((INVISIBLE_USERSPACE + 1)); continue; fi

    UNCLASSIFIED+=("$rel")
done < <(git -C "$SCRIPT_DIR" ls-files)

ACCOUNTED=$((${#FILES_SET[@]} + ${#EXCLUDED_SET[@]} + INVISIBLE_VCS + INVISIBLE_SETUP + INVISIBLE_USERSPACE))

echo "  Всего файлов в git: $TOTAL"
echo "  delivered-default/explicit-include (files[]): ${#FILES_SET[@]}"
echo "  видимые исключения (excluded_paths[]): ${#EXCLUDED_SET[@]}"
echo "  vcs-tooling-internal: $INVISIBLE_VCS"
echo "  setup-install-time-only: $INVISIBLE_SETUP"
echo "  user-space-excluded: $INVISIBLE_USERSPACE"

if [ "${#UNCLASSIFIED[@]}" -gt 0 ]; then
    fail "${#UNCLASSIFIED[@]} файл(ов) не попали ни в одну известную карте категорию:"
    for f in "${UNCLASSIFIED[@]}"; do echo "      - $f" >&2; done
elif [ "$ACCOUNTED" -eq "$TOTAL" ]; then
    ok "все $TOTAL файлов классифицированы ровно один раз (сумма категорий $ACCOUNTED)"
else
    fail "сумма категорий ($ACCOUNTED) не совпадает с общим числом файлов ($TOTAL) — возможен двойной учёт"
fi

echo "[3/3] owner + proof_of_delivery непустые для каждой категории/special_route..."
if python3 - "$MAP" <<'PY'
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as fh:
    data = yaml.safe_load(fh)

fail = False
for cat in data.get("categories", []):
    problems = []
    if not str(cat.get("owner", "")).strip():
        problems.append("пустой owner")
    if not str(cat.get("proof_of_delivery", "")).strip():
        problems.append("пустой proof_of_delivery")
    if problems:
        print(f"  ❌ категория {cat.get('id')}: {', '.join(problems)}", file=sys.stderr)
        fail = True
    else:
        print(f"  ✅ категория {cat.get('id')}: owner и proof_of_delivery заполнены")

known_ids = {cat.get("id") for cat in data.get("categories", [])}
for route in data.get("special_routes", []):
    if route.get("category") not in known_ids:
        print(f"  ❌ special_route {route.get('path')}: category '{route.get('category')}' не существует в categories", file=sys.stderr)
        fail = True
    elif not str(route.get("proof_of_delivery", "")).strip():
        print(f"  ❌ special_route {route.get('path')}: пустой proof_of_delivery", file=sys.stderr)
        fail = True
    else:
        print(f"  ✅ special_route {route.get('path')}: согласован")

sys.exit(1 if fail else 0)
PY
then
    :
else
    FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
    echo ""
    echo "✅ critical-files-map: карта согласована с деревом и generate-manifest.sh"
else
    echo ""
    echo "❌ critical-files-map: найдены расхождения (см. выше)"
fi
exit $FAIL
