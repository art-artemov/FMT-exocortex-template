"""
test_media.py — guide-kit structurer tests, media preprocessing slice (FORMAT.md §1).
Run: cd structurer && pytest

Uses `cat` as a stand-in extractor command — it's present on every CI/dev
machine this suite runs on, and its behavior (stdout = file contents) is
exactly what a real extractor's contract requires for these tests.
"""
from __future__ import annotations

from extractors import ExtractorRule
from media import preprocess_media, transcript_path


CAT_RULE = ExtractorRule(frozenset({".m4a"}), "cat", output="audio")


def test_sidecar_forced_quarantine_short_circuits_extraction(tmp_path):
    audio = tmp_path / "recording.m4a"
    audio.write_text("fake audio bytes")
    (tmp_path / "recording.m4a.meta.yaml").write_text("speakers_third_party: true\n")

    result = preprocess_media(str(tmp_path), "recording.m4a", str(audio), [CAT_RULE])
    assert result == {"final": {"type": None, "quarantine": {"reason": "third-party-pii", "excluded_from_generation": True, "detected_by": "forced-flag"}}}


def test_sidecar_type_wins_over_extraction(tmp_path):
    audio = tmp_path / "recording.m4a"
    audio.write_text("fake audio bytes")
    (tmp_path / "recording.m4a.meta.yaml").write_text('type: "2.2"\n')

    result = preprocess_media(str(tmp_path), "recording.m4a", str(audio), [CAT_RULE])
    assert result == {"final": {"type": "2.2", "mode": "index", "confidence": 1.0, "source": "sidecar"}}
    assert not (tmp_path / ".structurer" / "transcripts").exists()


def test_no_extractor_configured_falls_through(tmp_path):
    image = tmp_path / "whiteboard.png"
    image.write_bytes(b"\x89PNG")

    result = preprocess_media(str(tmp_path), "whiteboard.png", str(image), [CAT_RULE])
    assert result is None


def test_extraction_writes_transcript_and_returns_media_block(tmp_path):
    audio = tmp_path / "standup.m4a"
    audio.write_text("hello from the meeting")

    result = preprocess_media(str(tmp_path), "standup.m4a", str(audio), [CAT_RULE])
    assert result is not None
    assert "transcript_path" in result
    assert result["media"]["kind"] == "audio"
    assert result["media"]["extractor"] == "cat"
    assert result["media"]["derived_text"] == ".structurer/transcripts/standup.m4a.md"

    out = transcript_path(str(tmp_path), "standup.m4a")
    content = open(out, encoding="utf-8").read()
    assert 'derived_from: "standup.m4a"' in content
    assert "review_status: unreviewed" in content
    assert "hello from the meeting" in content


def test_media_kind_comes_from_extension_not_extractor_output_field(tmp_path):
    # Cold-review finding, 2026-07-15: an earlier version set media.kind to
    # rule.output (the extractor's output *format*, e.g. "text" per FORMAT.md
    # §6's own mp3/mp4/m4a/wav example) instead of a semantic kind — every
    # zero-config audio/video/PDF file was reported as kind="text". This rule
    # deliberately sets output="text" (matching the real DEFAULT_EXTRACTORS
    # shape) to prove kind isn't read from that field.
    audio = tmp_path / "standup.mp4"
    audio.write_text("hello from the meeting")
    rule = ExtractorRule(frozenset({".mp4"}), "cat", output="text")

    result = preprocess_media(str(tmp_path), "standup.mp4", str(audio), [rule])
    assert result["media"]["kind"] == "video"


def test_failed_extractor_falls_through(tmp_path):
    audio = tmp_path / "standup.m4a"
    audio.write_text("hello")
    failing_rule = ExtractorRule(frozenset({".m4a"}), "false", output="audio")  # `false` always exits 1

    result = preprocess_media(str(tmp_path), "standup.m4a", str(audio), [failing_rule])
    assert result is None
