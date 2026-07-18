"""
classify.py — guide-kit structurer: orchestrates media preprocessing, homes.yaml,
structural signals, freshness, and the Structurer's own residency check into
type-index.json (FORMAT.md §1-§7). Pipeline order (FORMAT.md, top): media
preprocessing → quarantine → homes.yaml → per-file classifier → freshness.
The LLM fallback (§3 step 4) is a separate slice, not implemented here.

CLI:
    python3 classify.py --base <path> [--homes homes.yaml] [--out .structurer/type-index.json]
"""
from __future__ import annotations

import argparse
import json
import logging
import os

from extractors import load_extractors
from freshness import build_freshness
from homes import HomeRule, load_homes, match_home
from media import preprocess_media
from quarantine import detect_quarantine
from residency import check_access, load_residency_state
from signals import EVENT_DATE_CONFIDENCE, detect_event_date, read_frontmatter, read_frontmatter_override

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
TEXT_EXTENSIONS = frozenset({".md", ".txt", ".canvas"})
_SKIP_DIRS = frozenset({".structurer", ".git"})
# guide-kit's own config artifacts, not user content — classifying them as
# "needs-extractor" would misreport them in the unplaced-files summary.
_SKIP_FILES = frozenset({"homes.yaml", "guide-kit.config.yaml", "extractors.yaml"})
_TEXT_READ_LIMIT_BYTES = 2 * 1024 * 1024  # 2MB of actual bytes, bounds a pathological giant file


def read_text_body(abs_path: str) -> str:
    """Full text for quarantine scanning (FORMAT.md §4a) — deliberately not limited to
    the frontmatter head like signals.read_frontmatter: a secret or card number can
    appear anywhere in the file, not just its first 64KB. Same tolerance as
    read_frontmatter for unreadable files (deleted/permission-denied mid-walk).

    Reads bytes, not characters: `open(..., encoding="utf-8").read(N)` counts decoded
    characters, so a limit meant to bound file size would silently read up to ~2x more
    bytes than stated for two-byte-per-character scripts like Cyrillic — the majority
    script in this project's own user base (cold-review finding, 2026-07-15)."""
    try:
        with open(abs_path, "rb") as fh:
            raw = fh.read(_TEXT_READ_LIMIT_BYTES)
    except OSError as e:
        logger.warning("cannot read %r: %s — quarantine scan sees empty text", abs_path, e)
        return ""
    return raw.decode("utf-8", errors="replace")


def _classify_by_signals(rel_path: str, frontmatter: dict, homes: list[HomeRule]) -> tuple[str, float, str]:
    """The homes.yaml → frontmatter-override → event-date → default 2.4
    precedence (FORMAT.md §3 steps 2-3, 5), shared between a normal text file
    and a transcript standing in for its non-text original — the transcript
    still gets typed by the same rules, just against `rel_path` (for
    homes.yaml) and the transcript's own frontmatter (for the rest)."""
    home = match_home(rel_path, homes)
    home_type = home.type if home is not None and home.type != "auto" else None
    if home_type is not None:
        return home_type, 1.0, "homes"

    override = read_frontmatter_override(frontmatter, rel_path)
    if override is not None:
        return override, 1.0, "frontmatter"

    if detect_event_date(rel_path, frontmatter):
        return "2.2", EVENT_DATE_CONFIDENCE, "classifier"

    return "2.4", 0.0, "default"


def _apply_residency(entry: dict, residency_state: dict) -> dict:
    """Every entry that got a real type (not quarantined, not already
    pending) passes through the Structurer's own access check
    (function_id=structurer, flow_direction=inbound — residency.py) before
    being accepted as classified. This checks the Structurer's own permission
    to read this data_type, not the file's origin (see residency.py
    docstring) — an origin question is out of scope here."""
    if entry.get("type") is None:
        return entry
    if not check_access(residency_state, entry["type"]):
        return {"type": None, "pending": "needs-consent"}
    return entry


def classify_file(
    rel_path: str,
    abs_path: str,
    homes: list[HomeRule],
    extractor_rules: list | None = None,
    base_dir: str | None = None,
    residency_state: dict | None = None,
) -> dict:
    """One type-index.json entry, per FORMAT.md §3 precedence, quarantine (§4a) run
    first for text files: quarantine → homes.yaml (non-"auto") → frontmatter override
    → event-date signal → default 2.4, then freshness (§7) and the residency check.

    Non-text files go through the media cascade (§1) first — sidecar override,
    then a configured extractor producing a transcript that's classified the
    same way as any text file. `extractor_rules`/`base_dir` are optional so
    existing text-only callers (and tests) don't have to supply them; passing
    neither disables the media cascade, matching the pre-Phase-2-media behavior.

    Quarantine runs before homes.yaml, not after: §3 says quarantine "takes priority
    over whatever type the step would otherwise have assigned" — checking after a type
    is already decided would mean undoing that decision instead of skipping it."""
    residency_state = residency_state if residency_state is not None else {}
    ext = os.path.splitext(rel_path)[1].lower()

    if ext not in TEXT_EXTENSIONS:
        if extractor_rules is not None and base_dir is not None:
            media_result = preprocess_media(base_dir, rel_path, abs_path, extractor_rules)
            if media_result is not None and "final" in media_result:
                return _apply_residency(media_result["final"], residency_state)
            if media_result is not None and "transcript_path" in media_result:
                transcript_path = media_result["transcript_path"]
                transcript_frontmatter = read_frontmatter(transcript_path)
                transcript_text = read_text_body(transcript_path)
                # FORMAT.md §1 rule 4: quarantine heuristics run on transcripts too.
                quarantine = detect_quarantine(transcript_text, rel_path, transcript_frontmatter)
                if quarantine is not None:
                    return {"type": None, "quarantine": quarantine}
                file_type, confidence, _source = _classify_by_signals(rel_path, transcript_frontmatter, homes)
                entry = {
                    "type": file_type, "mode": "pointer", "confidence": confidence,
                    "source": "classifier-on-transcript", "media": media_result["media"],
                }
                freshness = build_freshness(transcript_frontmatter, rel_path)
                if freshness is not None:
                    entry["freshness"] = freshness
                return _apply_residency(entry, residency_state)

        # FORMAT.md §4 field reference: type is null whenever pending is present —
        # homes.yaml assigns a category but doesn't manufacture readable content
        # that isn't there (cold-review finding, 2026-07-15: an earlier version
        # put home_type directly in "type" here, contradicting the spec's own
        # whiteboard.png example and skipping _apply_residency below).
        home = match_home(rel_path, homes)
        home_type = home.type if home is not None and home.type != "auto" else None
        if home_type is not None:
            entry = {"type": None, "pending": "needs-extractor", "note": f"placement-only ({home_type}) if an extractor is added"}
        else:
            entry = {"type": None, "pending": "needs-extractor"}
        return _apply_residency(entry, residency_state)

    frontmatter = read_frontmatter(abs_path)
    quarantine = detect_quarantine(read_text_body(abs_path), rel_path, frontmatter)
    if quarantine is not None:
        return {"type": None, "quarantine": quarantine}

    file_type, confidence, source = _classify_by_signals(rel_path, frontmatter, homes)
    entry = {"type": file_type, "mode": "index", "confidence": confidence, "source": source}
    freshness = build_freshness(frontmatter, rel_path)
    if freshness is not None:
        entry["freshness"] = freshness
    return _apply_residency(entry, residency_state)


def walk_and_classify(
    base_dir: str,
    homes: list[HomeRule],
    extractor_rules: list | None = None,
    residency_state: dict | None = None,
) -> dict[str, dict]:
    """Walks base_dir, skipping dotfiles/dotdirs and .structurer/.git (a repeat run
    must not classify its own output). Returns the "files" section of type-index.json."""
    files: dict[str, dict] = {}
    for root, dirs, filenames in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        is_base_root = os.path.abspath(root) == os.path.abspath(base_dir)
        for filename in filenames:
            if filename.startswith("."):
                continue
            # Config files are only skipped at the base root — a user's own note
            # happening to share a name (e.g. "homes.yaml" in a subfolder) is content.
            if is_base_root and filename in _SKIP_FILES:
                continue
            abs_path = os.path.join(root, filename)
            rel_path = os.path.relpath(abs_path, base_dir).replace(os.sep, "/")
            files[rel_path] = classify_file(rel_path, abs_path, homes, extractor_rules, base_dir, residency_state)
    return files


def write_type_index(files: dict[str, dict], out_path: str) -> None:
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"schema_version": SCHEMA_VERSION, "files": files}, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def write_quarantine_report(files: dict[str, dict], out_path: str) -> int:
    """FORMAT.md §4a: "a plain-language list of quarantined paths and reasons, meant
    for the human to skim and correct false positives, not a second source of truth."
    Always written, even with zero quarantined files — an absent report would be
    indistinguishable from "the run never happened" instead of "nothing to report".
    Returns the quarantined count for the caller's own log line."""
    quarantined = sorted((path, entry["quarantine"]) for path, entry in files.items() if "quarantine" in entry)
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        if not quarantined:
            fh.write("# Quarantine report\n\nNo files quarantined.\n")
            return 0
        fh.write(f"# Quarantine report\n\n{len(quarantined)} file(s) excluded from generation.\n")
        fh.write("If any of these are false positives, add `quarantine: false` to the file's frontmatter.\n\n")
        for path, q in quarantined:
            fh.write(f"- `{path}` — {q['reason']} (detected by: {q['detected_by']})\n")
    return len(quarantined)


def main() -> None:
    parser = argparse.ArgumentParser(description="guide-kit structurer: classify a note base into type-index.json")
    parser.add_argument("--base", required=True, help="path to the user's note base")
    parser.add_argument("--homes", default="homes.yaml", help="relative to --base unless absolute; tolerant of absence")
    parser.add_argument("--extractors", default="extractors.yaml", help="relative to --base unless absolute; tolerant of absence")
    parser.add_argument("--out", default=".structurer/type-index.json", help="relative to --base unless absolute")
    parser.add_argument("--quarantine-report", default=".structurer/quarantine-report.md", help="relative to --base unless absolute")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Resolved against --base, not the process's CWD (cold-review finding, 2026-07-15
    # round 2): an unresolved relative path here silently picked up whatever
    # homes.yaml happened to sit in the caller's working directory — sometimes none
    # (silent no-op), sometimes an unrelated one (silent misclassification with the
    # wrong rules). Same resolution pattern already used for --out below.
    homes_path = args.homes if os.path.isabs(args.homes) else os.path.join(args.base, args.homes)
    homes = load_homes(homes_path)
    extractors_path = args.extractors if os.path.isabs(args.extractors) else os.path.join(args.base, args.extractors)
    extractor_rules = load_extractors(extractors_path)
    residency_state = load_residency_state(args.base)
    files = walk_and_classify(args.base, homes, extractor_rules, residency_state)
    out_path = args.out if os.path.isabs(args.out) else os.path.join(args.base, args.out)
    write_type_index(files, out_path)
    report_path = args.quarantine_report if os.path.isabs(args.quarantine_report) else os.path.join(args.base, args.quarantine_report)
    quarantined_count = write_quarantine_report(files, report_path)
    logger.info("classified %d files (%d quarantined) → %s", len(files), quarantined_count, out_path)


if __name__ == "__main__":
    main()
