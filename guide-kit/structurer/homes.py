"""
homes.py — guide-kit structurer: homes.yaml loader + placement-based typing (FORMAT.md §2).

Segment-based glob matching, not fnmatch.translate on the full path: "*" matches exactly
one path segment, "**" matches zero or more segments — gitignore-style semantics, not
fnmatch's (where "*" crosses "/"). FORMAT.md's specificity precedence rule is itself
flagged "proposed, not backed by an existing convention" (peer-session finding,
2026-07-14) — the tuple scoring below is this implementation's concrete choice for that
open flag, not a second independent decision.
"""
from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass

import yaml

from signals import VALID_TYPES

logger = logging.getLogger(__name__)

_ALLOWED_HOME_TYPES = VALID_TYPES | {"auto"}


@dataclass
class HomeRule:
    pattern: str
    type: str
    note: str = ""


def load_homes(path: str) -> list[HomeRule]:
    """Tolerant of a missing file (no homes.yaml means every path falls through to
    the per-file classifier, FORMAT.md §3), of individual malformed rules (skipped
    with a warning, not fatal to the whole file — the same tolerance §3's frontmatter
    override already gets), and of an unrecognized `type` (skipped, same reasoning:
    a typo should degrade to "no rule", not silently propagate a garbage type into
    type-index.json)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        logger.info("no homes.yaml at %r — every path falls through to the classifier", path)
        return []
    except yaml.YAMLError as e:
        logger.error("malformed homes.yaml at %r: %s — treating as absent", path, e)
        return []

    rules: list[HomeRule] = []
    for entry in data.get("homes", []):
        try:
            rule = HomeRule(entry["path"], str(entry["type"]), entry.get("note", ""))
        except (KeyError, TypeError) as e:
            logger.warning("malformed homes.yaml rule %r: %s — skipping", entry, e)
            continue
        if rule.type not in _ALLOWED_HOME_TYPES:
            logger.warning("homes.yaml rule %r has unrecognized type %r — skipping", rule.pattern, rule.type)
            continue
        rules.append(rule)
    return rules


def _segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s != ""]


def _segment_matches(rel_segments: list[str], pattern_segments: list[str]) -> bool:
    """"**" (only valid as a whole segment) consumes zero or more remaining segments;
    every other pattern segment matches exactly one segment via single-segment fnmatch
    (no "/" left inside a segment, so "*"/"?"/"[...]" can't accidentally cross a
    boundary). Memoized on (rel_index, pattern_index): naive backtracking on multiple
    non-adjacent "**" segments is exponential (verified: a 12-deep alternating
    "**"/"*" pattern took 12s unmemoized) — this is the standard DP formulation for
    wildcard matching, O(len(rel) * len(pattern)) regardless of how many "**" appear
    or whether they're adjacent."""
    memo: dict[tuple[int, int], bool] = {}

    def match(ri: int, pi: int) -> bool:
        key = (ri, pi)
        if key in memo:
            return memo[key]
        if pi == len(pattern_segments):
            result = ri == len(rel_segments)
        else:
            head = pattern_segments[pi]
            if head == "**":
                result = match(ri, pi + 1) or (ri < len(rel_segments) and match(ri + 1, pi))
            else:
                result = ri < len(rel_segments) and fnmatch.fnmatch(rel_segments[ri], head) and match(ri + 1, pi + 1)
        memo[key] = result
        return result

    return match(0, 0)


def _specificity(pattern_segments: list[str]) -> tuple[int, int]:
    """(literal segments before the first wildcard segment, total literal chars in
    them). No metric is perfect here (e.g. "a/**" vs "**/b.md" tie on "a/b.md" under
    any reasonable scoring) — this is a documented, not a proven-optimal, choice."""
    literal_count = 0
    literal_chars = 0
    for segment in pattern_segments:
        if any(c in segment for c in "*?["):
            break
        literal_count += 1
        literal_chars += len(segment)
    return (literal_count, literal_chars)


def match_home(rel_path: str, rules: list[HomeRule]) -> HomeRule | None:
    """Most specific matching rule wins; ties keep the first match in file order."""
    rel_segments = _segments(rel_path)
    best: HomeRule | None = None
    best_score: tuple[int, int] | None = None
    for rule in rules:
        pattern_segments = _segments(rule.pattern)
        if not _segment_matches(rel_segments, pattern_segments):
            continue
        score = _specificity(pattern_segments)
        if best_score is None or score > best_score:
            best, best_score = rule, score
    return best
