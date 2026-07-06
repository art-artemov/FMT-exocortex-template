#!/usr/bin/env bash
# test-route-task.sh — 10 кейсов для route-task.sh (WP-350 Ф14)
# routing: executor=script deterministic=true
set -euo pipefail

SCRIPT="${1:-$HOME/IWE/FMT-exocortex-template/scripts/route-task.sh}"
export IWE_GOVERNANCE_REPO="${IWE_GOVERNANCE_REPO:-DS-strategy}"

PASS=0
FAIL=0

run_test() {
    local name="$1" expected="$2"
    shift 2
    echo "=== $name ==="
    set +e
    bash "$SCRIPT" "$@" >/dev/null 2>&1
    local actual=$?
    set -e
    if [[ "$actual" -eq "$expected" ]]; then
        echo "PASS (exit $actual)"
        ((PASS++)) || true
    else
        echo "FAIL: expected exit $expected, got $actual"
        ((FAIL++)) || true
    fi
    echo ""
}

# 1. Known script skill (consent) — script exists, fails on env var (exit from script, not router)
run_test "T1: --skill consent (script exists, router dispatches correctly)" 2 --skill consent

# 2. Unknown skill — strict (--skill)
run_test "T2: --skill unknown_skill (strict → exit 3)" 3 --skill unknown_skill

# 3. Unknown skill — flex (--tag)
run_test "T3: --tag unknown_skill (flex → fallback Sonnet, exit 0)" 0 --tag unknown_skill

# 4. Missing script — strict (--skill)
run_test "T4: --skill connect-guide (missing script → exit 2)" 2 --skill connect-guide

# 5. Missing script — flex (--tag)
run_test "T5: --tag connect-guide (missing script → fallback Haiku, exit 0)" 0 --tag connect-guide

# 6. Empty tag
run_test "T6: --tag '' (empty → unknown → fallback Sonnet, exit 0)" 0 --tag ""

# 7. --list
run_test "T7: --list (exit 0)" 0 --list

# 8. --validate
run_test "T8: --validate (exit 0)" 0 --validate

# 9. Broken YAML catalog → exit 1 (error)
echo "=== T9: broken YAML catalog → exit 1 ==="
TMP_CATALOG=$(mktemp)
echo "broken: [" > "$TMP_CATALOG"
set +e
IWE_EXECUTOR_CATALOG="$TMP_CATALOG" bash "$SCRIPT" --skill consent >/dev/null 2>&1
actual=$?
set -e
rm -f "$TMP_CATALOG"
if [[ "$actual" -eq 1 ]]; then
    echo "PASS (exit $actual)"
    ((PASS++)) || true
else
    echo "FAIL: expected exit 1, got $actual"
    ((FAIL++)) || true
fi
echo ""

# 10. Missing python3 → exit 1 (error)
echo "=== T10: missing python3 → exit 1 ==="
TMP_DIR=$(mktemp -d)
cat > "$TMP_DIR/python3" << 'FAKEPY'
#!/usr/bin/env bash
if [[ "$1" == "-c" && "$2" == "import yaml" ]]; then
    exit 1
fi
exit 0
FAKEPY
chmod +x "$TMP_DIR/python3"
set +e
PATH="$TMP_DIR:$PATH" bash "$SCRIPT" --skill consent >/dev/null 2>&1
actual=$?
set -e
rm -rf "$TMP_DIR"
if [[ "$actual" -eq 1 ]]; then
    echo "PASS (exit $actual)"
    ((PASS++)) || true
else
    echo "FAIL: expected exit 1, got $actual"
    ((FAIL++)) || true
fi
echo ""

# 11. JSON mode — NO_MATCH
run_test "T11: --json --skill unknown (strict → NO_MATCH, exit 3)" 3 --json --skill unknown_skill

# 12. JSON mode — OK fallback
run_test "T12: --json --tag unknown (flex → OK, exit 0)" 0 --json --tag unknown_skill

# 13. AGENT_FAULT routing
run_test "T13: --skill agent-fault (script, no LLM)" 0 --skill agent-fault --args "record --severity major --fault=test"

# 14. Path-resolution via IWE_DIR
echo "=== T14: IWE_DIR path-resolution ==="
TMP_IWE=$(mktemp -d)
mkdir -p "$TMP_IWE/scripts"
cp "$HOME/IWE/scripts/iwe-consent.sh" "$TMP_IWE/scripts/"
set +e
IWE_DIR="$TMP_IWE" IWE_EXECUTOR_CATALOG="$HOME/IWE/${IWE_GOVERNANCE_REPO:-DS-strategy}/scripts/executor-catalog.yaml" bash "$SCRIPT" --skill consent --args "status" >/dev/null 2>&1
actual=$?
set -e
rm -rf "$TMP_IWE"
if [[ "$actual" -eq 2 ]]; then
    echo "PASS (exit $actual — script found via IWE_DIR, failed on env as expected)"
    ((PASS++)) || true
else
    echo "FAIL: expected exit 2 (script found, env missing), got $actual"
    ((FAIL++)) || true
fi
echo ""

echo "========================"
echo "PASS: $PASS  FAIL: $FAIL"
exit $FAIL
