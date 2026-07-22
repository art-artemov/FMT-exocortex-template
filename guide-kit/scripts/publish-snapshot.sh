#!/bin/bash
# publish-snapshot.sh — build the CAT.001-003 snapshot archive and publish it
# as a GitHub Release asset on this repo (DP.SC.060 scenario 2, system #16:
# DRR-snapshot-service.md). This IS the autonomous download service — a
# versioned static asset, not a running server (guide-kit "zero servers"
# principle, DP.SC.056 И3).
#
# Versioning: snapshot tags (snapshot-YYYY-MM-DD) live in their own namespace,
# separate from code release tags (vX.Y.Z) — the two have independent
# lifecycles (snapshot changes with curriculum content, code changes with
# features), conflating them would force a code release every time the
# curriculum data changes and vice versa.
#
# Contract:
#   * one snapshot per calendar date, matching the archive's own manifest
#     snapshot_date — a tag collision means this date was already published,
#     the script refuses to silently overwrite it;
#   * publishes to THIS repo (iwesys/guide-kit) — the client (component 4/5)
#     already tracks this repo for code, so the snapshot has one home instead
#     of a second repository to poll;
#   * requires `gh` authenticated with push access — no fallback to an
#     unauthenticated path, a failed publish must be loud, not silent.
#
# Usage: bash scripts/publish-snapshot.sh --curriculum-path PATH --snapshot-date YYYY-MM-DD [--dry-run]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CURRICULUM_PATH=""
SNAPSHOT_DATE=""
DRY_RUN=false

usage() {
    grep '^# Usage' -A 1 "$0" | sed 's/^# \{0,1\}//'
}

# Strict parsing: an unknown flag is an error, not a silently ignored no-op
# (same posture as guide-kit-sync.sh's --dryrun incident, WP-483 Ф1.5).
while [ $# -gt 0 ]; do
    case "$1" in
        --curriculum-path) CURRICULUM_PATH="${2:?--curriculum-path requires a value}"; shift 2 ;;
        --snapshot-date)   SNAPSHOT_DATE="${2:?--snapshot-date requires a value}"; shift 2 ;;
        --dry-run)         DRY_RUN=true; shift ;;
        *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 1 ;;
    esac
done

if [ -z "$CURRICULUM_PATH" ] || [ -z "$SNAPSHOT_DATE" ]; then
    echo "ERROR: --curriculum-path and --snapshot-date are both required." >&2
    usage >&2
    exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
    echo "ERROR: gh CLI not found — required to create the release and upload the asset." >&2
    exit 1
fi

TAG="snapshot-${SNAPSHOT_DATE}"

# Refuse to overwrite an already-published snapshot for this date — a repeat
# run with the same date is almost always a mistake (stale invocation, wrong
# --snapshot-date), and the release asset should be an append-only ledger.
if gh release view "$TAG" --repo iwesys/guide-kit >/dev/null 2>&1; then
    echo "ERROR: release $TAG already exists — refusing to overwrite. Use a different --snapshot-date." >&2
    exit 1
fi

DIST_DIR=$(mktemp -d)
trap 'rm -rf "$DIST_DIR"' EXIT

echo "Building snapshot archive for $SNAPSHOT_DATE ..."
python3 "$REPO_ROOT/scripts/build-snapshot.py" \
    --curriculum-path "$CURRICULUM_PATH" \
    --out-dir "$DIST_DIR" \
    --snapshot-date "$SNAPSHOT_DATE"

ARCHIVE_PATH="$DIST_DIR/guide-kit-snapshot-${SNAPSHOT_DATE}.tar.gz"
if [ ! -f "$ARCHIVE_PATH" ]; then
    echo "ERROR: build-snapshot.py did not produce the expected archive at $ARCHIVE_PATH" >&2
    exit 1
fi

if $DRY_RUN; then
    echo "Dry run — would create release $TAG on iwesys/guide-kit with asset:"
    ls -lh "$ARCHIVE_PATH"
    echo "Dry run: nothing published."
    exit 0
fi

echo "Publishing $TAG on iwesys/guide-kit ..."
gh release create "$TAG" "$ARCHIVE_PATH" \
    --repo iwesys/guide-kit \
    --title "Curated materials snapshot: $SNAPSHOT_DATE" \
    --notes "Autonomous-user snapshot of CAT.001-003 curated curriculum cards, dated $SNAPSHOT_DATE. Built by scripts/build-snapshot.py. See DRR-snapshot-service.md for the delivery model."

echo "OK: published $TAG"
