"""
extractors.py — guide-kit structurer: FORMAT.md §6 pluggable media extractors.

Zero-config default matches the example in FORMAT.md §6 exactly: audio/video
route to `whisper-mlx` if installed, PDF text layer to `pdf-text-layer` with an
OCR fallback. A user's own `extractors.yaml` (at the base root, alongside
`homes.yaml`) replaces this default outright — this module never merges the
two, so a user who configures one extension doesn't silently inherit the
others they didn't ask for.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass

import yaml

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


@dataclass
class ExtractorRule:
    extensions: frozenset[str]
    command: str
    output: str = "text"
    fallback: str | None = None


DEFAULT_EXTRACTORS: list[ExtractorRule] = [
    ExtractorRule(frozenset({".mp3", ".mp4", ".m4a", ".wav"}), "whisper-mlx", output="text"),
    ExtractorRule(frozenset({".pdf"}), "pdf-text-layer", fallback="needs-ocr"),
]


def load_extractors(path: str) -> list[ExtractorRule]:
    """A missing extractors.yaml is the documented zero-config state
    (FORMAT.md §6) — falls back to DEFAULT_EXTRACTORS, not an empty list. A
    malformed file falls back the same way; an individual malformed entry is
    skipped, the rest of the file still loads (same per-entry tolerance as
    homes.load_homes)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        logger.info("no extractors.yaml at %r — using zero-config defaults", path)
        return DEFAULT_EXTRACTORS
    except yaml.YAMLError as e:
        logger.error("malformed extractors.yaml at %r: %s — using zero-config defaults", path, e)
        return DEFAULT_EXTRACTORS

    rules: list[ExtractorRule] = []
    for entry in data.get("extractors", []):
        try:
            extensions = frozenset(str(ext).lower() for ext in entry["extensions"])
            rules.append(ExtractorRule(extensions, str(entry["command"]), str(entry.get("output", "text")), entry.get("fallback")))
        except (KeyError, TypeError) as e:
            logger.warning("malformed extractors.yaml rule %r: %s — skipping", entry, e)
            continue
    return rules if rules else DEFAULT_EXTRACTORS


def find_extractor(ext: str, rules: list[ExtractorRule]) -> ExtractorRule | None:
    ext = ext.lower()
    for rule in rules:
        if ext in rule.extensions:
            return rule
    return None


def extractor_available(rule: ExtractorRule) -> bool:
    """Zero-config posture: a configured extractor whose command isn't on
    PATH is the same as no extractor at all (FORMAT.md §6 — "otherwise audio/
    video fall through to pending: needs-extractor"), not a hard failure."""
    return shutil.which(rule.command) is not None
