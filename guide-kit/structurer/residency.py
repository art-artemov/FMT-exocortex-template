"""
residency.py — guide-kit structurer: local consent check for the Structurer's
own read access to a data category.

Answers exactly one question: "may the Structurer (function_id=structurer,
flow_direction=inbound) read files the classifier assigns to this
data_type?" It does NOT answer "was the file's original arrival into this
base legitimate?" — that question belongs to whatever imported it (a sync
job, a manual export, a platform pull), each with its own function_id and
its own consent check at pull time. The Structurer sees files already on
disk; it can't and doesn't retroactively adjudicate their provenance.

Deliberately its own file-backed store, `.structurer/residency-state.yaml`
inside the base being processed — not the author's personal
`~/IWE/current/data-residency.yaml` (FMT-exocortex-template's ResidencyGate
skill, `lib/state.py`). That path is hardcoded to one person's exocortex
layout; importing code tied to it would break guide-kit's own portability
invariant (DP.SC.056 — zero servers, runs on a stranger's machine with no
`~/IWE` in sight). The consent *model* (function_id × data_type ×
flow_direction, granted/denied/not_asked) is the same idea reused, not
the same storage.
"""
from __future__ import annotations

import logging
import os

import yaml

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
FUNCTION_ID = "structurer"
FLOW_DIRECTION = "inbound"
STATE_FILENAME = ".structurer/residency-state.yaml"


def _need_key(data_type: str) -> str:
    return f"{data_type}_{FLOW_DIRECTION}_{FUNCTION_ID}"


def load_residency_state(base_dir: str) -> dict:
    """A missing or malformed state file is a valid cold start — same posture
    as a missing `profile.yaml` in `generator/adapter.py`. The Structurer does
    not refuse to run just because nobody has ever recorded a decision."""
    path = os.path.join(base_dir, STATE_FILENAME)
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}
    except (OSError, yaml.YAMLError) as e:
        logger.warning("cannot read %r: %s — treating as no consent decisions on record", path, e)
        return {}
    consents = data.get("consents")
    return consents if isinstance(consents, dict) else {}


def check_access(state: dict, data_type: str) -> bool:
    """True unless this data_type is explicitly `denied` in state — absence
    of an entry ("not_asked") defaults to allowed, matching the rest of
    guide-kit's cold-start-is-valid posture rather than fail-closed."""
    return state.get(_need_key(data_type)) != "denied"
