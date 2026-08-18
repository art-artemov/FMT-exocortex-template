#!/usr/bin/env bash
# WP-5 Ф38 / #430: Hindsight documentation must not promise automation that
# the default IWE installation does not wire.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
DOC="$ROOT/docs/hindsight-setup.md"

require_text() {
    local text="$1"
    grep -Fq "$text" "$DOC" || {
        echo "FAIL: hindsight guide is missing required contract text: $text" >&2
        exit 1
    }
}

reject_text() {
    local text="$1"
    if grep -Fq "$text" "$DOC"; then
        echo "FAIL: hindsight guide still promises unsupported automation: $text" >&2
        exit 1
    fi
}

reject_text "No manual action required."
reject_text "Once running, IWE agents automatically:"
require_text "A standard IWE installation does not"
require_text "automatically invoke Recall, Retain, or Reflect."
require_text "\`IWE_HINDSIGHT_RETAIN=1\`"
require_text "Recall and Reflect require a separately"

expected_retain_gate="[ \"\${IWE_HINDSIGHT_RETAIN:-}\" = \"1\" ]"
for adapter in scripts/kimi-peer-adapter.sh scripts/codex-peer-adapter.sh; do
    grep -Fq "$expected_retain_gate" "$ROOT/$adapter" || {
        echo "FAIL: $adapter no longer gates peer retain with IWE_HINDSIGHT_RETAIN=1" >&2
        exit 1
    }
done

if grep -R --include='*.json' -Fq 'hindsight_trigger.py' "$ROOT/.claude"; then
    echo "FAIL: default Claude configuration registers hindsight_trigger.py" >&2
    exit 1
fi

echo "PASS: Hindsight guide matches the manual and peer-opt-in delivery contract"
