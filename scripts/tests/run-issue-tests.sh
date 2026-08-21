#!/usr/bin/env bash
# run-issue-tests.sh — single versioned runner for issue-regression tests
# (WP-529 F6, peer-session 2026-08-19-01, codex В3).
#
# A new scripts/tests/test_issue_*.sh is picked up by mere existence of the
# file: stable order (glob sort), shebang sanity check, run all, fail on any.
# This closes the recurring class "test sat in the repo, never wired into CI"
# (issue #226 in July; then the entire test_issue_* family found unwired on
# 18.08 by an external user). *.py siblings need the pytest context of
# scripts/tests and are listed here, not run — silence would read as coverage.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
shopt -s nullglob

fail=0
ran=0
for t in "$ROOT"/scripts/tests/test_issue_*.sh; do
    name=$(basename "$t")
    if ! head -1 "$t" | grep -q '^#!'; then
        echo "❌ $name: нет shebang — файл не запускаем"
        fail=$((fail+1))
        continue
    fi
    echo "=== $name ==="
    if bash "$t"; then
        ran=$((ran+1))
    else
        echo "❌ $name: упал"
        fail=$((fail+1))
    fi
done

for t in "$ROOT"/scripts/tests/test_issue_*.py; do
    echo "ℹ $(basename "$t"): python-тест, запускается через pytest — вне scope этого раннера"
done

echo "---"
echo "issue-tests: прошло=$ran, упало=$fail"
# Cold review 2026-08-19: an empty family must not read as green — zero
# executed tests means the glob/layout broke, not that everything passed.
[ "$fail" -eq 0 ] && [ "$ran" -gt 0 ]
