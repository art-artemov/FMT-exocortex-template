"""
media.py — guide-kit structurer: media preprocessing cascade (FORMAT.md §1),
consulted for every non-text file before homes.yaml/the per-file classifier.

Order per FORMAT.md §1 rule 3: sidecar override wins over extraction — a file
the sidecar already types skips transcription outright, so an hour of audio
with a hand-written sidecar never gets transcribed just to guess something
the human already declared by hand.
"""
from __future__ import annotations

import datetime
import logging
import os
import subprocess

from extractors import ExtractorRule, extractor_available, find_extractor
from sidecar import read_sidecar, read_sidecar_type, sidecar_forces_quarantine

logger = logging.getLogger(__name__)

TRANSCRIPT_DIR = ".structurer/transcripts"
_EXTRACT_TIMEOUT_SECONDS = 600

# media.kind (FORMAT.md §4's worked example: "kind": "video" for an .mp4) is a
# semantic label for the ORIGINAL file, distinct from ExtractorRule.output
# (the extractor's output *format*, e.g. "text" — see extractors.yaml §6's own
# example, where the audio rule's output is "text" too). Conflating the two
# reported every transcribed file as kind="text" regardless of whether it was
# audio, video, or a PDF (cold-review finding, 2026-07-15). Extension-derived
# only, same declared-provenance posture as the rest of this module — never
# guessed from content.
_MEDIA_KIND_BY_EXTENSION = {
    ".mp3": "audio", ".m4a": "audio", ".wav": "audio",
    ".mp4": "video",
    ".pdf": "pdf",
}


def _media_kind(rel_path: str) -> str:
    return _MEDIA_KIND_BY_EXTENSION.get(os.path.splitext(rel_path)[1].lower(), "unknown")


def transcript_path(base_dir: str, rel_path: str) -> str:
    return os.path.join(base_dir, TRANSCRIPT_DIR, rel_path + ".md")


def run_extractor(rule: ExtractorRule, abs_path: str) -> str | None:
    """Runs the configured command as `<command> <abs_path>`, capturing stdout
    as the extracted text. Any failure (non-zero exit, timeout, binary
    disappearing mid-run) yields `None` — an honest "extraction failed" is the
    same downstream outcome as "no extractor configured", not a crash of the
    whole walk over one bad file."""
    try:
        result = subprocess.run(
            [rule.command, abs_path],
            capture_output=True, text=True, errors="replace",
            timeout=_EXTRACT_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("extractor %r failed on %r: %s", rule.command, abs_path, e)
        return None
    if result.returncode != 0:
        logger.warning("extractor %r exited %d on %r: %s", rule.command, result.returncode, abs_path, result.stderr.strip())
        return None
    return result.stdout


def write_transcript(base_dir: str, rel_path: str, text: str, extractor: str) -> str:
    """FORMAT.md §1 rule 1: the transcript is a derived file, never inside the
    user's own vault — it lives under `.structurer/transcripts/`, mirroring
    the original's relative path with `.md` appended. Its frontmatter carries
    provenance (`derived_from`, `extractor`, `extracted_at`) so a human or the
    Generator can trace it back to the original; `review_status: unreviewed`
    flags that nobody has confirmed the transcription is accurate yet."""
    out_path = transcript_path(base_dir, rel_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    frontmatter = (
        "---\n"
        f"derived_from: \"{rel_path}\"\n"
        f"extractor: \"{extractor}\"\n"
        f"extracted_at: \"{datetime.date.today().isoformat()}\"\n"
        "review_status: unreviewed\n"
        "---\n\n"
    )
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(frontmatter)
        fh.write(text)
    return out_path


def preprocess_media(base_dir: str, rel_path: str, abs_path: str, extractor_rules: list[ExtractorRule]) -> dict | None:
    """Returns one of three shapes:

    - `{"final": <complete type-index.json entry>}` — sidecar already decided
      (type or forced quarantine), no transcription needed.
    - `{"transcript_path": <abs path>, "media": <complete media block>}` —
      extraction ran; classify.py still has to run quarantine + typing on the
      transcript's text (FORMAT.md §1 rule 4) and merge the result with this
      media block.
    - `None` — no sidecar type, no extractor available: falls through to
      classify.py's existing homes.yaml/`needs-extractor` handling.

    Media kind (audio/video/pdf) is read only from the extractors.yaml
    extension mapping, never guessed from content — same declared-provenance
    invariant as classify.py's type assignment."""
    sidecar = read_sidecar(abs_path)

    if sidecar_forces_quarantine(sidecar, rel_path):
        return {"final": {"type": None, "quarantine": {"reason": "third-party-pii", "excluded_from_generation": True, "detected_by": "forced-flag"}}}

    sidecar_type = read_sidecar_type(sidecar, rel_path)
    if sidecar_type is not None:
        return {"final": {"type": sidecar_type, "mode": "index", "confidence": 1.0, "source": "sidecar"}}

    ext = os.path.splitext(rel_path)[1].lower()
    rule = find_extractor(ext, extractor_rules)
    if rule is None or not extractor_available(rule):
        return None

    text = run_extractor(rule, abs_path)
    if text is None:
        return None

    derived_path = write_transcript(base_dir, rel_path, text, rule.command)
    return {
        "transcript_path": derived_path,
        "media": {
            "kind": _media_kind(rel_path),
            "derived_text": os.path.relpath(derived_path, base_dir).replace(os.sep, "/"),
            "extractor": rule.command,
            "extracted_at": datetime.date.today().isoformat(),
        },
    }
