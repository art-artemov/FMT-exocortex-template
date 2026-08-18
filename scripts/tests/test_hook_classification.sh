#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/.claude/hooks" "$TMP/.claude"
cp "$ROOT/setup/validate-template.sh" "$TMP/validate-template.sh"
cp "$ROOT/.claude/settings.json" "$TMP/.claude/settings.json"
cp "$ROOT/.claude/hooks/"*.sh "$TMP/.claude/hooks/"

OUTPUT=$(bash "$TMP/validate-template.sh" "$TMP" 2>&1 || true)
for name in agent-trace-uploader residency-gate-init residency-gate-lazy rule-engine; do
  if grep -q "WARN: hook $name.sh" <<<"$OUTPUT"; then
    echo "FAIL: explicitly classified $name.sh still reported as orphan" >&2
    exit 1
  fi
done

printf '#!/bin/sh\n' > "$TMP/.claude/hooks/unknown-orphan.sh"
OUTPUT=$(bash "$TMP/validate-template.sh" "$TMP" 2>&1 || true)
grep -q 'WARN: hook unknown-orphan.sh' <<<"$OUTPUT"

echo "PASS: explicit non-hook classification is quiet; unknown orphan still warns"
