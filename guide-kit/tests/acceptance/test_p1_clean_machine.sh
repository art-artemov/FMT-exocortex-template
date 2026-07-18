#!/usr/bin/env bash
# P.1 acceptance check (MVP acceptance): a guide assembles end-to-end
# from a throwaway clone of this repo — zero pre-existing local state, zero
# real LLM calls (stub server on an ephemeral port), zero network egress
# beyond that stub. Also serves as evidence for P.2(b) "new device <1 day":
# every step below is timestamped, so the log is the proof, not a claim.
#
# Usage: tests/acceptance/test_p1_clean_machine.sh
# Exit 0 = guide assembled non-empty from the demo catalog. Exit 1 = failure,
# with the failing step named on stderr.
set -euo pipefail

step() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLONE_DIR="$(mktemp -d)"
STUB_PID=""

cleanup() {
    if [ -n "$STUB_PID" ]; then
        kill "$STUB_PID" 2>/dev/null || true
        wait "$STUB_PID" 2>/dev/null || true  # reap before exit — else bash prints an async "Terminated" job notice
    fi
    rm -rf "$CLONE_DIR"
}
trap cleanup EXIT

step "start"

step "clone --depth 1 (fresh checkout, no repo state carried over)"
git clone --quiet --depth 1 "file://$REPO_ROOT" "$CLONE_DIR"

step "start stub LLM server on an ephemeral port"
STUB_PORT_FILE="$(mktemp)"
python3 "$REPO_ROOT/tests/acceptance/stub_llm_server.py" > "$STUB_PORT_FILE" &
STUB_PID=$!
for _ in $(seq 1 50); do
    [ -s "$STUB_PORT_FILE" ] && break
    sleep 0.1
done
STUB_PORT="$(cat "$STUB_PORT_FILE")"
rm -f "$STUB_PORT_FILE"
if [ -z "$STUB_PORT" ]; then
    echo "FAIL: stub server did not report a port" >&2
    exit 1
fi
step "stub server up on 127.0.0.1:$STUB_PORT (pid $STUB_PID)"

step "write sanitized config (no api_key, no vendor backend, no prod paths)"
SANDBOX_CONFIG="$CLONE_DIR/acceptance.config.yaml"
cat > "$SANDBOX_CONFIG" <<EOF
curriculum_path: $CLONE_DIR/demo/curriculum
cards_path: $CLONE_DIR/demo/cards
llm_backend: openai_compatible
llm_base_url: http://127.0.0.1:$STUB_PORT/v1
onboarding_ctas: false
personal_export: off
work_section: off
EOF

step "run generator against the fresh clone + demo catalog (cold-start profile)"
cd "$CLONE_DIR/generator"
set +e  # OUTPUT capture must survive a non-zero exit long enough to read STATUS below
# env -u, not just "config has no llm_api_key": generate_daily_plan falls back to
# this env var when the config omits one — if the operator's own shell already
# has a real vendor key exported, it would silently attach to the stub request
# (still loopback-only, but defeats the "sanitized, no real credential" intent).
OUTPUT="$(env -u GUIDE_KIT_LLM_API_KEY python3 - "$SANDBOX_CONFIG" <<'PYEOF'
import sys
sys.path.insert(0, ".")
from adapter import generate_daily_plan

result = generate_daily_plan(
    profile_path="does-not-exist-profile.yaml",  # cold start is a valid state (see README)
    config_path=sys.argv[1],
)
if not result.ok:
    print(f"DIAGNOSTIC (not necessarily a failure — see policy):\n{result.diagnostic}")
    sys.exit(1)
print(result.markdown)
PYEOF
)"
STATUS=$?
set -e

if [ "$STATUS" -ne 0 ] || [ -z "$OUTPUT" ]; then
    step "FAIL: no guide text produced"
    echo "$OUTPUT" >&2
    exit 1
fi

step "done — guide text length: ${#OUTPUT} chars"
echo "$OUTPUT"
