#!/usr/bin/env bash
# shellcheck disable=SC2034,SC2329  # globals/functions are evaluated from update.sh.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

eval "$(awk '
  /^resolve_delivery_ref\(\)/ { capture=1 }
  capture { print }
  capture && /^}/ { exit }
' "$ROOT/update.sh")"
declare -F resolve_delivery_ref >/dev/null

REPO='example/fixture'
BRANCH='main'
API_BASE="https://api.github.com/repos/$REPO"
CURL_BASE_OPTS=''
_CURL_SSL_OPT=''
PY_BIN=python3
py_available() { command -v "$PY_BIN" >/dev/null 2>&1; }

curl() {
    printf '%s\n' '{"sha":"0123456789abcdef0123456789abcdef01234567"}'
}

RAW_BASE="https://raw.githubusercontent.com/$REPO/$BRANCH"
resolve_delivery_ref > "$TMP/pinned.out"
OUT=$(<"$TMP/pinned.out")
if [ "$RAW_BASE" != "https://raw.githubusercontent.com/$REPO/0123456789abcdef0123456789abcdef01234567" ]; then
    echo 'delivery ref did not pin raw downloads to the resolved commit' >&2
    exit 1
fi
if ! grep -Fq 'Снимок поставки: 0123456789ab' <(printf '%s' "$OUT"); then
    echo 'delivery ref did not report the pinned snapshot' >&2
    exit 1
fi

curl() {
    printf '%s\n' '{"sha":"not-a-commit"}'
}

RAW_BASE="https://raw.githubusercontent.com/$REPO/$BRANCH"
resolve_delivery_ref > "$TMP/fallback.out"
OUT=$(<"$TMP/fallback.out")
if [ "$RAW_BASE" != "https://raw.githubusercontent.com/$REPO/$BRANCH" ]; then
    echo 'delivery ref changed the base after an invalid API response' >&2
    exit 1
fi
if ! grep -Fq 'используется подвижная ветка' <(printf '%s' "$OUT"); then
    echo 'delivery ref hid the fallback to the moving branch' >&2
    exit 1
fi

echo 'PASS: update pins manifest and files to one delivery commit'
