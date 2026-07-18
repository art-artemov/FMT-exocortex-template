"""
quarantine.py — guide-kit structurer: "off-axis" quarantine (FORMAT.md §4a).

Scope decision (peer-session 2026-07-15-01, turns 0-2 — Kimi unavailable on turn 3,
design finished solo under the pilot's direct instruction "if Kimi doesn't answer
twice — do it yourself"): the source concept (CONCEPT-full-architecture.md §10) frames the whole
bucket as "someone else's PII, secrets, payment data" — "someone else's" grammatically
attaches to PII specifically, not to secrets/payment (a credit card number is
contraband regardless of whose it is). Regex cannot distinguish "my own PII" from
"someone else's" (no identity source exists in this pipeline) — so automatic
detection in this slice covers only `secret` and `payment`, where ownership is
irrelevant. `pii` and `third-party-pii` stay valid `reason` values but are reachable
here only via an explicit forced flag, never a guess — same honest-gap pattern as
classify.py's 2.4 default and the missing-extractor case.
"""
from __future__ import annotations

import logging
import re

from signals import read_bool_field

logger = logging.getLogger(__name__)

QUARANTINE_REASONS = frozenset({"pii", "secret", "payment", "third-party-pii"})

# Known vendor token formats — zero ambiguity, the shape alone is the signal.
_VENDOR_SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),                          # AWS access key
    re.compile(r"sk-ant-api\d{2}-[A-Za-z0-9_-]{30,}"),        # Anthropic
    re.compile(r"gh[poshru]_[A-Za-z0-9]{30,}"),               # GitHub
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),              # Slack
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),                     # Google API key
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)?PRIVATE KEY-----"),
]

# Labeled high-entropy assignment — catches arbitrary third-party keys the vendor
# list above doesn't know about. The label anchors intent (this is a "secret",
# not just any long string); the length floor keeps placeholders like
# "password: changeme" out.
_LABELED_SECRET_RE = re.compile(
    r"\b(?:api[_-]?key|secret|token|access[_-]?key)\b\s*[:=]\s*['\"]?([A-Za-z0-9_\-/+=]{20,})['\"]?",
    re.IGNORECASE,
)
_PLACEHOLDER_VALUES = frozenset({
    "changeme", "your_api_key_here", "your-api-key-here", "insert_key_here",
    "xxxxxxxxxxxxxxxxxxxx", "redacted", "example_key_do_not_use",
})


def _looks_like_secret_value(value: str) -> bool:
    """Length alone doesn't distinguish a real token from an ordinary long path or
    dashed phrase (cold-review finding, 2026-07-15: "access_key: my-bucket/path/to/..."
    and "secret: this-is-a-fairly-long-dashed-phrase" both matched the length-only
    check). Real vendor tokens mix case and digits; prose and file paths after a
    "key:"/"token:" label typically don't — requiring both is a cheap, explainable
    filter, not a claim of true entropy measurement."""
    return any(c.isdigit() for c in value) and any(c.isupper() for c in value)

_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _iban_valid(candidate: str) -> bool:
    """ISO 7064 mod-97-10 checksum — rejects the vast majority of alnum strings
    that happen to start with 2 letters + 2 digits (e.g. hashes, IDs)."""
    rearranged = candidate[4:] + candidate[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97 == 1


def _detect_secret(text: str) -> str | None:
    for pattern in _VENDOR_SECRET_PATTERNS:
        if pattern.search(text):
            return "known-vendor-format"
    for match in _LABELED_SECRET_RE.finditer(text):
        value = match.group(1)
        if value.lower() not in _PLACEHOLDER_VALUES and _looks_like_secret_value(value):
            return "labeled-high-entropy-assignment"
    return None


def _detect_payment(text: str) -> str | None:
    for match in _CARD_RE.finditer(text):
        digits = match.group(0).replace(" ", "").replace("-", "")
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            return "luhn-valid-card-number"
    for match in _IBAN_RE.finditer(text):
        if _iban_valid(match.group(0)):
            return "iban-checksum"
    return None


def detect_quarantine(text: str, rel_path: str, frontmatter: dict) -> dict | None:
    """One quarantine check, run before any type assignment (FORMAT.md §3: quarantine
    "takes priority over whatever type the step would otherwise have assigned" — so a
    file that homes.yaml would type doesn't get a chance to skip this check).

    Order: forced flag first, then escape hatch, then heuristics. The two frontmatter
    signals answer different questions — `speakers_third_party: true` is a human
    stating "this specific file exposes someone else's PII", `quarantine: false` is a
    human stating "the heuristic below is wrong about my own data". They're not meant
    to contradict each other, but if a stale `quarantine: false` survives an edit
    alongside a freshly-added `speakers_third_party: true`, the explicit third-party
    claim must win — silently honoring the escape hatch here would leak exactly the
    PII this module exists to catch. `pii`/`third-party-pii` heuristic detection is
    out of scope here (see module docstring) — reachable only via the forced flag.
    """
    if read_bool_field(frontmatter, "speakers_third_party", rel_path) is True:
        return {"reason": "third-party-pii", "excluded_from_generation": True, "detected_by": "forced-flag"}
    if read_bool_field(frontmatter, "quarantine", rel_path) is False:
        return None

    detected_by = _detect_secret(text)
    if detected_by is not None:
        return {"reason": "secret", "excluded_from_generation": True, "detected_by": detected_by}

    detected_by = _detect_payment(text)
    if detected_by is not None:
        return {"reason": "payment", "excluded_from_generation": True, "detected_by": detected_by}

    return None
