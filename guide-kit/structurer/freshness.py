"""
freshness.py — guide-kit structurer: FORMAT.md §7 freshness block.

Freshness is optional per file — no `valid_from` means "age unknown", not an
error. But once a file asserts `valid_from` it must also assert exactly one
way to die: `ttl_days` (expiration) or `superseded_by` (explicit replacement,
present even if still null — the key's presence declares the mechanism, its
value tracks whether replacement has happened yet). Both keys present, or
neither, is the malformed state (FORMAT.md §7) — a partial or ambiguous
assertion, not a valid minimal one. Rejected as malformed, not silently
guessed at, same honest-gap posture as classify.py's 2.4 default.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_freshness(frontmatter: dict, rel_path: str) -> dict | None:
    """Returns None if the file has no `valid_from` (no freshness block at
    all) or if it declares valid_from with a malformed death mechanism
    (logged, not raised — a malformed block degrades to "no freshness data",
    consistent with how the rest of the classifier treats bad input)."""
    valid_from = frontmatter.get("valid_from")
    if valid_from is None:
        return None
    valid_from = str(valid_from)

    has_ttl = frontmatter.get("ttl_days") is not None
    has_supersede = "superseded_by" in frontmatter

    if has_ttl and has_supersede:
        logger.warning("%r declares both ttl_days and superseded_by — FORMAT.md §7 allows exactly one, ignoring freshness block", rel_path)
        return None
    if not has_ttl and not has_supersede:
        logger.warning("%r declares valid_from with neither ttl_days nor superseded_by — malformed per FORMAT.md §7, ignoring freshness block", rel_path)
        return None

    if has_ttl:
        try:
            return {"valid_from": valid_from, "ttl_days": int(frontmatter["ttl_days"])}
        except (TypeError, ValueError):
            logger.warning("%r has non-integer ttl_days=%r — ignoring freshness block", rel_path, frontmatter["ttl_days"])
            return None

    superseded_by = frontmatter["superseded_by"]
    return {"valid_from": valid_from, "superseded_by": str(superseded_by) if superseded_by is not None else None}
