"""
test_extractors.py — guide-kit structurer tests, extractors.yaml slice (FORMAT.md §6).
Run: cd structurer && pytest
"""
from __future__ import annotations

from extractors import DEFAULT_EXTRACTORS, ExtractorRule, extractor_available, find_extractor, load_extractors


def test_missing_file_returns_defaults(tmp_path):
    assert load_extractors(str(tmp_path / "extractors.yaml")) == DEFAULT_EXTRACTORS


def test_malformed_file_returns_defaults(tmp_path):
    path = tmp_path / "extractors.yaml"
    path.write_text("extractors: [unclosed\n")
    assert load_extractors(str(path)) == DEFAULT_EXTRACTORS


def test_custom_file_replaces_defaults_outright(tmp_path):
    path = tmp_path / "extractors.yaml"
    path.write_text(
        "schema_version: 1\n"
        "extractors:\n"
        "  - extensions: [\".pdf\"]\n"
        "    command: \"my-ocr\"\n"
    )
    rules = load_extractors(str(path))
    assert rules == [ExtractorRule(frozenset({".pdf"}), "my-ocr", "text", None)]


def test_malformed_entry_skipped_rest_of_file_loads(tmp_path):
    path = tmp_path / "extractors.yaml"
    path.write_text(
        "extractors:\n"
        "  - command: \"missing-extensions-key\"\n"
        "  - extensions: [\".pdf\"]\n"
        "    command: \"my-ocr\"\n"
    )
    rules = load_extractors(str(path))
    assert rules == [ExtractorRule(frozenset({".pdf"}), "my-ocr", "text", None)]


def test_find_extractor_matches_extension_case_insensitive():
    rule = find_extractor(".MP3", DEFAULT_EXTRACTORS)
    assert rule is not None
    assert rule.command == "whisper-mlx"


def test_find_extractor_no_match_returns_none():
    assert find_extractor(".png", DEFAULT_EXTRACTORS) is None


def test_extractor_unavailable_command_not_on_path():
    rule = ExtractorRule(frozenset({".xyz"}), "definitely-not-a-real-command-xyzxyz", "text")
    assert extractor_available(rule) is False


def test_extractor_available_when_command_on_path():
    # "python3" is guaranteed present — this suite itself runs under it.
    rule = ExtractorRule(frozenset({".xyz"}), "python3", "text")
    assert extractor_available(rule) is True
