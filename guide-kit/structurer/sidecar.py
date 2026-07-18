"""
sidecar.py — guide-kit structurer: `<file>.meta.yaml` override for binaries with
no frontmatter of their own (FORMAT.md §5).

Sidecar and frontmatter never compete on the same file (FORMAT.md §3 rule 1) —
this module is only consulted for non-text files; a text file's own
frontmatter is read via signals.read_frontmatter instead.
"""
from __future__ import annotations

import logging

import yaml

from signals import VALID_TYPES, read_bool_field

logger = logging.getLogger(__name__)


def read_sidecar(abs_path: str) -> dict:
    """Returns {} when `<abs_path>.meta.yaml` doesn't exist (most binaries
    won't have one), is unreadable, or doesn't parse to a mapping — same
    tolerance as signals.read_frontmatter for its own missing/malformed case."""
    sidecar_path = abs_path + ".meta.yaml"
    try:
        with open(sidecar_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError:
        return {}
    except OSError as e:
        logger.warning("cannot read sidecar %r: %s — treating as absent", sidecar_path, e)
        return {}
    except yaml.YAMLError as e:
        logger.warning("malformed sidecar %r: %s — treating as absent", sidecar_path, e)
        return {}
    if not isinstance(data, dict):
        logger.warning("sidecar %r is not a mapping (%s) — treating as absent", sidecar_path, type(data).__name__)
        return {}
    return data


def read_sidecar_type(sidecar: dict, rel_path: str) -> str | None:
    """An unrecognized `type:` value falls through to None rather than
    failing the run — same posture as signals.read_frontmatter_override."""
    value = sidecar.get("type")
    if value is None:
        return None
    value = str(value)
    if value not in VALID_TYPES:
        logger.warning("sidecar type %r for %r is not a recognized type — ignoring", value, rel_path)
        return None
    return value


def sidecar_forces_quarantine(sidecar: dict, rel_path: str) -> bool:
    """`speakers_third_party: true` in the sidecar — same forced-quarantine
    field FORMAT.md §4a documents for text frontmatter, here for binaries
    that can't carry frontmatter of their own."""
    return read_bool_field(sidecar, "speakers_third_party", rel_path) is True
