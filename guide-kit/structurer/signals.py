"""
signals.py — guide-kit structurer: deterministic per-file structural signals (FORMAT.md §3).

Only two signals are implemented: an explicit frontmatter override, and an event-date
signal. FORMAT.md's remaining four structural signals (self-declared fact / stream-derived
mirror / conceptual form / decision-trail) have no marker portable across arbitrary user
bases without either domain-specific config or an LLM step — guessing them here would be
exactly the invented-type failure this format exists to avoid. Everything not caught by
these two deterministic signals is the honest 2.4 default (see classify.py).

A bare `date:` frontmatter key is deliberately NOT an event-date signal: in real user
vaults it usually means creation/publish date, not the event itself (peer-session
finding, 2026-07-14). Supporting it is a config opt-in, out of scope here.
"""
from __future__ import annotations

import datetime
import logging
import re

import yaml

logger = logging.getLogger(__name__)

VALID_TYPES = frozenset({"2.1-declared", "2.1-derived", "2.2", "2.3", "2.4"})

EVENT_DATE_CONFIDENCE = 0.7
_FRONTMATTER_READ_LIMIT = 64 * 1024  # a file without frontmatter in the first 64KB has none
_FILENAME_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def read_frontmatter(abs_path: str) -> dict:
    """Returns {} for files with no leading '---' block (most user files won't have
    one — not an error), for unreadable files (deleted/permission-denied mid-walk,
    common with cloud-synced-vault placeholders — not fatal to the whole run), and
    for frontmatter that parses to something other than a mapping (a bare list/string
    is syntactically valid YAML but not a valid frontmatter block)."""
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(_FRONTMATTER_READ_LIMIT)
    except OSError as e:
        logger.warning("cannot read %r: %s — treating as no frontmatter", abs_path, e)
        return {}
    if not head.startswith("---"):
        return {}
    end = head.find("\n---", 3)
    if end == -1:
        return {}
    try:
        loaded = yaml.safe_load(head[3:end])
    except yaml.YAMLError as e:
        logger.warning("malformed frontmatter in %r: %s — treating as absent", abs_path, e)
        return {}
    if not isinstance(loaded, dict):
        logger.warning("frontmatter in %r is not a mapping (%s) — treating as absent", abs_path, type(loaded).__name__)
        return {}
    return loaded


def read_bool_field(mapping: dict, key: str, context_for_log: str) -> bool | None:
    """YAML parses an unquoted `true`/`false` as a real bool, but a quoted
    `"true"`/`"false"` — a plausible habit, since every `type:` example in
    FORMAT.md is itself quoted — parses as a string that `is True`/`is False`
    silently fails to match (cold-review finding, 2026-07-15, originally found
    in quarantine's `speakers_third_party` handling; shared here because §5's
    sidecar file needs the identical parse for the same field name)."""
    value = mapping.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    if value is not None:
        logger.warning("field %r=%r in %r is not a recognized boolean — ignoring", key, value, context_for_log)
    return None


def read_frontmatter_override(frontmatter: dict, abs_path: str) -> str | None:
    """Explicit `type:`/`user_intent:` outranks every other signal. An unrecognized
    value falls through instead of failing the run — FORMAT.md's 2.4 default is the
    right outcome for a typo, not a crash.

    YAML parses an unquoted `type: 2.3` as a float, not the string "2.3" — a real
    hazard for anyone hand-writing this frontmatter without quotes. str() normalizes
    it; Python's float repr round-trips cleanly for one-decimal values like 2.1-2.4."""
    value = frontmatter.get("type") or frontmatter.get("user_intent")
    if value is None:
        return None
    value = str(value)
    if value not in VALID_TYPES:
        logger.warning("frontmatter override %r in %r is not a recognized type — ignoring", value, abs_path)
        return None
    return value


def detect_event_date(rel_path: str, frontmatter: dict) -> bool:
    """`event_date:` frontmatter key, or a filename containing YYYY-MM-DD (the
    daily-note convention) — both validated as real calendar dates, not regex shape
    alone.

    Matches against the filename only, not the full rel_path — a directory segment
    that happens to contain a date (e.g. "archive/2026-06-01-kickoff/notes.md") is
    not itself a daily-note filename, and matching the whole path would tag every
    file under such a folder as an event, not just the ones that actually are.

    Checks every YYYY-MM-DD-shaped substring, not just the first: a filename can
    have an earlier substring that looks date-shaped but isn't a real calendar date
    (e.g. an export template's "1234-99-99" placeholder prefix) followed by a real
    one — stopping at the first regex match would silently miss the real date."""
    event_date = frontmatter.get("event_date")
    if event_date is not None and _is_real_date(str(event_date)):
        return True
    filename = rel_path.rsplit("/", 1)[-1]
    return any(_is_real_date(m.group(1)) for m in _FILENAME_DATE_RE.finditer(filename))


def _is_real_date(value: str) -> bool:
    try:
        datetime.date.fromisoformat(value)
        return True
    except ValueError:
        return False
