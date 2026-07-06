#!/bin/bash
set -euo pipefail

# Smoke-test для новых scripts/*.sh в FMT. see WP-347 PD-1.

if [ $# -lt 1 ]; then
    echo "Usage: $0 <path-to-script>"
    exit 1
fi

file="$1"
FAIL=0

# 1. Syntax
if ! bash -n "$file" >/dev/null 2>&1; then
    echo "SYNTAX: FAIL"
    FAIL=1
else
    echo "SYNTAX: PASS"
fi

# 2. Safe-mode (warning only)
if ! grep -q '^set -euo pipefail' "$file" >/dev/null 2>&1; then
    echo "SAFE-MODE: missing"
else
    echo "SAFE-MODE: PASS"
fi

# 3. Shebang
if ! head -1 "$file" | grep -q '^#!/' >/dev/null 2>&1; then
    echo "SHEBANG: missing"
    FAIL=1
else
    echo "SHEBANG: PASS"
fi

# 4. Optional --help in env -i with timeout 5s
TIMEOUT_CMD=""
if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_CMD="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_CMD="gtimeout"
fi

if [ -n "$TIMEOUT_CMD" ]; then
    help_exit=0
    env -i HOME="$HOME" PATH="$PATH" "$TIMEOUT_CMD" 5 bash "$file" --help >/dev/null 2>&1 || help_exit=$?
    if [ "$help_exit" -eq 124 ] || [ "$help_exit" -eq 137 ]; then
        echo "HELP: timed out"
    elif [ "$help_exit" -ne 0 ] && [ "$help_exit" -ne 1 ] && [ "$help_exit" -ne 2 ]; then
        echo "HELP: unexpected exit $help_exit"
    else
        echo "HELP: PASS"
    fi
else
    echo "HELP: timeout utility not available, skipped"
fi

if [ "$FAIL" -eq 0 ]; then
    echo "smoke-clean-env: PASS $file"
    exit 0
else
    exit 1
fi
