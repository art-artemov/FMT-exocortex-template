"""
fetch-snapshot.py — client for the autonomous curated-materials snapshot
service (DP.SC.060 scenario 2, system #16: DRR-snapshot-service.md).

Downloads the latest (or a pinned) `snapshot-YYYY-MM-DD` GitHub Release asset
from iwesys/guide-kit, verifies the manifest, and extracts it locally — no
token, public GitHub Releases API only (`gh release download`, same tool
publish-snapshot.sh already depends on).

After a successful fetch, the extracted directory is a valid
GUIDE_KIT_CURRICULUM_PATH — point guide-kit.config.yaml's `curriculum_path`
at it (or the printed --out-dir path).

Honest degradation (DRR NBR #1/#3):
  - schema_version mismatch → refuse to use the archive, not a silent
    best-effort parse of a shape this script wasn't written for.
  - snapshot older than --max-age-days → warning printed, extraction still
    proceeds (a stale snapshot is still more useful than none for an
    offline user — this is advisory, not a hard-fail).

CLI:
    python3 fetch-snapshot.py --out-dir baseline [--tag snapshot-YYYY-MM-DD]
        [--max-age-days 90] [--today YYYY-MM-DD]

--today must be passed explicitly by the caller (no implicit "now") — same
reproducibility posture as build-snapshot.py's --snapshot-date, and it keeps
this script free of hidden wall-clock state for testing.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import date
from pathlib import Path

SUPPORTED_SCHEMA_VERSION = 1
_REPO = "iwesys/guide-kit"


class SnapshotFetchError(Exception):
    """Raised for any failure that should stop the fetch honestly — a caller
    checks for this instead of guessing from a partial baseline/ directory."""


def _gh_download(out_dir: Path, tag: str | None) -> Path:
    """Downloads the release asset (the single .tar.gz) via `gh release download`
    into out_dir. Returns the downloaded archive path. Raises SnapshotFetchError
    on any gh failure (missing binary, no such release, network error) — gh's
    own stderr is preserved in the message, not swallowed."""
    if shutil.which("gh") is None:
        raise SnapshotFetchError("gh CLI not found — required to download the release asset")

    cmd = ["gh", "release", "download"]
    if tag:
        cmd.append(tag)
    # No tag → gh defaults to the latest release on its own (a positional
    # argument, not a --latest flag — this CLI has no such flag; --pattern
    # below satisfies gh's own requirement that a tag-less call must narrow
    # by --pattern or --archive).
    cmd += ["--repo", _REPO, "--pattern", "*.tar.gz", "--dir", str(out_dir), "--clobber"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SnapshotFetchError(f"gh release download failed: {result.stderr.strip()}")

    archives = sorted(out_dir.glob("*.tar.gz"))
    if not archives:
        raise SnapshotFetchError("gh release download reported success but no .tar.gz was found")
    return archives[0]


def _read_manifest(archive_path: Path) -> dict:
    """Extracts and parses baseline/manifest.json from the archive without
    unpacking the rest yet — schema_version must be checked before any card
    content is trusted."""
    with tarfile.open(archive_path, "r:gz") as tar:
        try:
            member = tar.extractfile("baseline/manifest.json")
        except KeyError as e:
            raise SnapshotFetchError("archive has no baseline/manifest.json") from e
        if member is None:
            raise SnapshotFetchError("baseline/manifest.json is not a regular file in the archive")
        try:
            return json.loads(member.read())
        except json.JSONDecodeError as e:
            raise SnapshotFetchError(f"baseline/manifest.json is not valid JSON: {e}") from e


def _check_freshness(manifest: dict, today: str, max_age_days: int) -> str | None:
    """Returns a warning string if the snapshot is older than max_age_days,
    else None. Malformed/missing snapshot_date is itself a freshness warning
    (can't vouch for an archive whose own age is unknown)."""
    snapshot_date = manifest.get("snapshot_date")
    if not snapshot_date:
        return "manifest has no snapshot_date — cannot verify freshness"
    try:
        age_days = (date.fromisoformat(today) - date.fromisoformat(snapshot_date)).days
    except ValueError:
        return f"manifest snapshot_date {snapshot_date!r} is not a valid YYYY-MM-DD date"
    if age_days > max_age_days:
        return (
            f"snapshot is {age_days} days old (dated {snapshot_date}, max recommended "
            f"{max_age_days}) — consider checking for a newer release"
        )
    return None


def fetch_snapshot(
    out_dir: Path,
    today: str,
    tag: str | None = None,
    max_age_days: int = 90,
) -> tuple[Path, str | None]:
    """Downloads, verifies, and extracts the snapshot into out_dir/baseline.
    Returns (extracted_path, freshness_warning_or_None).
    Raises SnapshotFetchError on download failure or a schema_version this
    script doesn't understand — no partial/best-effort extraction in that case.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        archive_path = _gh_download(Path(tmp), tag)
        manifest = _read_manifest(archive_path)

        schema_version = manifest.get("schema_version")
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            raise SnapshotFetchError(
                f"unsupported manifest schema_version {schema_version!r} "
                f"(this script understands {SUPPORTED_SCHEMA_VERSION!r}) — "
                "refusing to extract an archive shaped differently than expected"
            )

        warning = _check_freshness(manifest, today, max_age_days)

        extracted = out_dir / "baseline"
        if extracted.exists():
            shutil.rmtree(extracted)
        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                # tarfile.data_filter (not the "data" string alias) — the alias
                # form is only accepted from 3.12, the function form works on
                # the 3.11 CI runner too (PEP 706, backported to 3.11.4+).
                tar.extractall(out_dir, filter=tarfile.data_filter)
        except tarfile.TarError as e:
            raise SnapshotFetchError(
                f"archive failed a safety check during extraction ({e}) — "
                "refusing a malformed or unsafe (path traversal / symlink) archive"
            ) from e

    return extracted, warning


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="guide-kit fetch-snapshot — download and extract the autonomous curated-materials snapshot"
    )
    parser.add_argument("--out-dir", default=".", help="Directory to extract baseline/ into (default: cwd)")
    parser.add_argument("--tag", default=None, help="Specific snapshot-YYYY-MM-DD tag (default: latest release)")
    parser.add_argument(
        "--today", required=True, help="Today's date, YYYY-MM-DD — used for freshness checks, no implicit 'now'"
    )
    parser.add_argument("--max-age-days", type=int, default=90, help="Warn if the snapshot is older than this (default: 90)")
    return parser


if __name__ == "__main__":
    args = _build_parser().parse_args()
    try:
        date.fromisoformat(args.today)
    except ValueError as e:
        print(f"ERROR: --today must be YYYY-MM-DD: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        extracted_path, freshness_warning = fetch_snapshot(
            Path(args.out_dir), args.today, tag=args.tag, max_age_days=args.max_age_days
        )
    except SnapshotFetchError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if freshness_warning:
        print(f"WARNING: {freshness_warning}", file=sys.stderr)
    print(f"OK: snapshot extracted to {extracted_path}", file=sys.stderr)
    print(f"Set curriculum_path: {extracted_path}/CAT.001  # or the extracted dir's parent, per your layout", file=sys.stderr)
