"""
build-snapshot.py — packages CAT.001-003 curriculum cards into a downloadable
archive for DP.SC.060 scenario 2 (autonomous user, no platform connection at all).

Source: DS-principles-curriculum/data/curriculum/CAT.001-003 (sibling repo —
same source `_load_cat001()` in generator/planner.py reads via
GUIDE_KIT_CURRICULUM_PATH for a connected local clone; this script is for the
disconnected case instead). Cards are copied verbatim — unlike the 9-part
universal guides (WP-452), these already carry no IWE-only frontmatter
(ontology_anchor/cp_check/bh_check/subsection_id — see CONCEPT-portable-guide-
generator.md §6.4), so no cleaning step is needed here.

`status: draft` cards are excluded — the same filter sync-catalogs.py applies,
kept even though no CAT.00X card is currently in draft (a future one may be).

Output: a .tar.gz under dist/ plus a manifest.json (schema_version,
snapshot_date, per-catalog counts) — read by the client before trusting the
archive's freshness (DRR-snapshot-service.md, NBR #1/#3).

CLI:
    python3 scripts/build-snapshot.py [--curriculum-path PATH] [--out-dir dist]
        [--snapshot-date YYYY-MM-DD]

--snapshot-date is required, not defaulted to today: this script must stay
free of Date.now()-style hidden state so a CI run and a local run of the same
inputs produce byte-identical archives (reproducibility, DRR NBR #3).
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tarfile
from datetime import date
from pathlib import Path

SCHEMA_VERSION = 1
CATALOGS = ("CAT.001", "CAT.002", "CAT.003")

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _read_status(text: str) -> str | None:
    """Reads the `status:` frontmatter field without a full YAML parse — this
    script only needs one field, and the source cards' frontmatter is a flat
    key: value list (see sync-catalogs.py's parse_frontmatter for the same
    assumption)."""
    m = _FM_RE.match(text)
    if not m:
        return None
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            if key.strip() == "status":
                return val.strip().strip('"').strip("'")
    return None


def collect_cards(curriculum_path: Path) -> dict[str, list[Path]]:
    """Returns {catalog_name: [card paths]}, draft cards excluded, README.md skipped.
    A missing catalog directory yields an empty list for it — a partial source
    tree degrades to a smaller snapshot, not a crash (mirrors planner.py's
    honest-empty-index posture for a missing GUIDE_KIT_CURRICULUM_PATH)."""
    result: dict[str, list[Path]] = {}
    for catalog in CATALOGS:
        cat_dir = curriculum_path / catalog
        cards = []
        if cat_dir.is_dir():
            for f in sorted(cat_dir.glob("*.md")):
                if f.name == "README.md":
                    continue
                text = f.read_text(encoding="utf-8")
                if _read_status(text) == "draft":
                    continue
                cards.append(f)
        result[catalog] = cards
    return result


def build_manifest(cards_by_catalog: dict[str, list[Path]], snapshot_date: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_date": snapshot_date,
        "catalogs": {
            catalog: {"count": len(paths), "files": sorted(p.name for p in paths)}
            for catalog, paths in cards_by_catalog.items()
        },
    }


def build_archive(curriculum_path: Path, out_dir: Path, snapshot_date: str) -> Path:
    """Builds dist/guide-kit-snapshot-{snapshot_date}.tar.gz containing
    baseline/CAT.00X/*.md (verbatim card copies) + baseline/manifest.json.
    Returns the archive path. Raises FileNotFoundError if every catalog is
    empty — an archive with zero cards is not a useful snapshot, and silently
    shipping one would violate DP.SC.060's honest-degradation invariant."""
    cards_by_catalog = collect_cards(curriculum_path)
    total = sum(len(paths) for paths in cards_by_catalog.values())
    if total == 0:
        raise FileNotFoundError(
            f"no cards found under {curriculum_path!r} for any of {CATALOGS!r} — "
            "refusing to build an empty snapshot"
        )

    manifest = build_manifest(cards_by_catalog, snapshot_date)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive_path = out_dir / f"guide-kit-snapshot-{snapshot_date}.tar.gz"

    with tarfile.open(archive_path, "w:gz") as tar:
        for catalog, paths in cards_by_catalog.items():
            for path in paths:
                tar.add(path, arcname=f"baseline/{catalog}/{path.name}")

        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        manifest_info = tarfile.TarInfo(name="baseline/manifest.json")
        manifest_info.size = len(manifest_bytes)
        tar.addfile(manifest_info, io.BytesIO(manifest_bytes))

    counts_str = ", ".join(f"{k}={v['count']}" for k, v in manifest["catalogs"].items())
    print(f"OK: {archive_path} — {total} cards ({counts_str})", file=sys.stderr)
    return archive_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="guide-kit build-snapshot — package CAT.001-003 into a downloadable archive"
    )
    parser.add_argument(
        "--curriculum-path",
        required=True,
        help="Path to DS-principles-curriculum/data/curriculum (contains CAT.001/002/003)",
    )
    parser.add_argument("--out-dir", default="dist", help="Output directory (default: dist)")
    parser.add_argument(
        "--snapshot-date",
        required=True,
        help="Snapshot date, YYYY-MM-DD — no implicit 'today' (reproducibility)",
    )
    return parser


if __name__ == "__main__":
    args = _build_parser().parse_args()
    try:
        date.fromisoformat(args.snapshot_date)
    except ValueError as e:
        print(f"ERROR: --snapshot-date must be YYYY-MM-DD: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        build_archive(Path(args.curriculum_path), Path(args.out_dir), args.snapshot_date)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
