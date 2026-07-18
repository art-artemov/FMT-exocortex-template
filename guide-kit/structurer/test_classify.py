"""
test_classify.py — guide-kit structurer tests.
Run: cd structurer && pytest
"""
from __future__ import annotations

import json

from classify import classify_file, main, walk_and_classify, write_type_index
from extractors import ExtractorRule
from homes import HomeRule, load_homes, match_home
from signals import detect_event_date, read_frontmatter, read_frontmatter_override


# ---------------------------------------------------------------------------
# homes.py — segment matching + specificity scoring
# ---------------------------------------------------------------------------

def test_double_star_matches_nested_path():
    rules = [HomeRule("daily-notes/**", "2.2")]
    assert match_home("daily-notes/2026/note.md", rules).type == "2.2"


def test_single_star_does_not_cross_slash():
    rules = [HomeRule("daily-notes/*", "2.2")]
    assert match_home("daily-notes/note.md", rules) is not None
    assert match_home("daily-notes/2026/note.md", rules) is None


def test_more_specific_pattern_wins():
    rules = [
        HomeRule("daily-notes/**", "2.2"),
        HomeRule("daily-notes/2026/**", "2.3"),
    ]
    assert match_home("daily-notes/2026/note.md", rules).type == "2.3"


def test_more_specific_prefix_beats_root_wildcard():
    # "daily-notes/**" (1 literal segment before its wildcard) outranks
    # "**/archive.md" (0 literal segments before its wildcard) — not a tie.
    rules = [
        HomeRule("**/archive.md", "2.4"),
        HomeRule("daily-notes/**", "2.2"),
    ]
    assert match_home("daily-notes/archive.md", rules).type == "2.2"


def test_tie_keeps_first_rule_in_file_order():
    # Both patterns have identical specificity (1 literal segment, "notes", 5 chars,
    # before their respective wildcard segment) and both match "notes/foo.md" —
    # a genuine tie, broken by file order.
    rules = [
        HomeRule("notes/*.md", "2.4"),
        HomeRule("notes/**", "2.2"),
    ]
    assert match_home("notes/foo.md", rules).type == "2.4"


def test_consecutive_double_star_matches():
    # "a/**/**/b" must behave exactly like "a/**/b".
    rules = [HomeRule("a/**/**/b.md", "2.3")]
    assert match_home("a/x/y/z/b.md", rules).type == "2.3"


def test_no_matching_rule_returns_none():
    rules = [HomeRule("daily-notes/**", "2.2")]
    assert match_home("concepts/idea.md", rules) is None


def test_non_adjacent_double_star_does_not_blow_up():
    # Naive backtracking on several non-adjacent "**" segments is exponential
    # (verified: 12 alternating "**"/"*" segments took 12s unmemoized). The
    # memoized matcher must stay fast regardless — this is the actual regression
    # this test guards, not just the narrow "consecutive **" case above.
    pattern = "/".join(["**", "*"] * 12) + "/target.md"
    rules = [HomeRule(pattern, "2.3")]
    non_matching_path = "/".join(["seg"] * 24) + "/not-the-target.md"
    assert match_home(non_matching_path, rules) is None  # must return promptly, not hang


def test_load_homes_skips_malformed_rule_not_fatal(tmp_path):
    # A rule missing "type" must not abort parsing every other rule in the file.
    f = tmp_path / "homes.yaml"
    f.write_text("homes:\n  - path: broken/**\n  - path: ok/**\n    type: \"2.3\"\n")
    rules = load_homes(str(f))
    assert [r.pattern for r in rules] == ["ok/**"]


def test_load_homes_skips_unrecognized_type(tmp_path):
    f = tmp_path / "homes.yaml"
    f.write_text('homes:\n  - path: "weird/**"\n    type: "2.99"\n')
    assert load_homes(str(f)) == []


def test_load_homes_accepts_auto(tmp_path):
    f = tmp_path / "homes.yaml"
    f.write_text('homes:\n  - path: "archive/**"\n    type: "auto"\n')
    rules = load_homes(str(f))
    assert rules[0].type == "auto"


# ---------------------------------------------------------------------------
# signals.py — frontmatter override + event-date
# ---------------------------------------------------------------------------

def test_frontmatter_override_accepted(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("---\ntype: 2.3\n---\nbody\n")
    fm = read_frontmatter(str(f))
    assert read_frontmatter_override(fm, str(f)) == "2.3"


def test_frontmatter_that_is_not_a_mapping_does_not_crash(tmp_path):
    # "---\n- a\n- b\n---" is syntactically valid YAML (a list), but not a valid
    # frontmatter block — must degrade to "no frontmatter", not raise.
    f = tmp_path / "note.md"
    f.write_text("---\n- a\n- b\n---\nbody\n")
    assert read_frontmatter(str(f)) == {}


def test_frontmatter_override_unknown_value_falls_through(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("---\ntype: not-a-real-type\n---\nbody\n")
    fm = read_frontmatter(str(f))
    assert read_frontmatter_override(fm, str(f)) is None


def test_event_date_from_frontmatter():
    assert detect_event_date("note.md", {"event_date": "2026-06-01"}) is True


def test_bare_date_key_is_not_a_signal():
    assert detect_event_date("note.md", {"date": "2026-06-01"}) is False


def test_event_date_from_filename():
    assert detect_event_date("daily-notes/2026-06-01.md", {}) is True


def test_date_in_directory_name_is_not_a_signal():
    # A folder named after a date (e.g. an archived project kickoff) must not tag
    # every file inside it as an event — only the filename itself counts.
    assert detect_event_date("archive/2026-06-01-project-kickoff/notes.md", {}) is False


def test_real_date_after_invalid_date_shaped_prefix_is_still_found():
    # A template/export filename can have a placeholder "1234-99-99" prefix followed
    # by a real date — the first regex match being calendar-invalid must not stop the
    # search for a later, real one.
    assert detect_event_date("notes/1234-99-99-2026-06-01-standup.md", {}) is True


def test_invalid_filename_date_is_not_a_signal():
    assert detect_event_date("weird/1234-99-99.md", {}) is False


def test_no_signal_at_all():
    assert detect_event_date("concepts/idea.md", {}) is False


# ---------------------------------------------------------------------------
# classify.py — end-to-end precedence + walk
# ---------------------------------------------------------------------------

def test_homes_takes_precedence_over_event_date_signal(tmp_path):
    (tmp_path / "daily-notes").mkdir()
    f = tmp_path / "daily-notes" / "2026-06-01.md"
    f.write_text("body\n")
    homes = [HomeRule("daily-notes/**", "2.3")]
    entry = classify_file("daily-notes/2026-06-01.md", str(f), homes)
    assert entry["type"] == "2.3"
    assert entry["source"] == "homes"


def test_homes_auto_falls_through_to_classifier(tmp_path):
    (tmp_path / "archive").mkdir()
    f = tmp_path / "archive" / "2026-06-01.md"
    f.write_text("body\n")
    homes = [HomeRule("archive/**", "auto")]
    entry = classify_file("archive/2026-06-01.md", str(f), homes)
    assert entry["type"] == "2.2"
    assert entry["source"] == "classifier"


def test_homes_takes_precedence_over_frontmatter_override(tmp_path):
    f = tmp_path / "2026-06-01.md"
    f.write_text("---\ntype: 2.3\n---\nbody\n")
    homes = [HomeRule("*.md", "2.2")]
    entry = classify_file("2026-06-01.md", str(f), homes)
    assert entry["type"] == "2.2"
    assert entry["source"] == "homes"


def test_frontmatter_override_takes_precedence_over_event_date(tmp_path):
    f = tmp_path / "2026-06-01.md"
    f.write_text("---\ntype: 2.3\n---\nbody\n")
    entry = classify_file("2026-06-01.md", str(f), [])
    assert entry["type"] == "2.3"
    assert entry["source"] == "frontmatter"


def test_default_is_2_4_not_a_guess(tmp_path):
    f = tmp_path / "musings.md"
    f.write_text("just some thoughts, no signal at all\n")
    entry = classify_file("musings.md", str(f), [])
    assert entry["type"] == "2.4"
    assert entry["confidence"] == 0.0
    assert entry["source"] == "default"


def test_non_text_file_is_pending_not_skipped(tmp_path):
    f = tmp_path / "photo.png"
    f.write_bytes(b"\x89PNG\r\n")
    entry = classify_file("photo.png", str(f), [])
    assert entry == {"type": None, "pending": "needs-extractor"}


def test_non_text_file_under_homes_rule_stays_null_type_but_notes_the_category(tmp_path):
    # FORMAT.md §4's own whiteboard.png example: homes.yaml's category is surfaced
    # as a note, but "type" stays null while "pending" is present (field reference:
    # "type ... null whenever quarantine is present ... or when pending is present") —
    # homes.yaml doesn't manufacture text content that isn't there (cold-review
    # finding, 2026-07-15: an earlier version put the homes type directly into
    # "type" here, contradicting this spec table and skipping the residency check).
    (tmp_path / "photos").mkdir()
    f = tmp_path / "photos" / "whiteboard.png"
    f.write_bytes(b"\x89PNG\r\n")
    homes = [HomeRule("photos/**", "2.3")]
    entry = classify_file("photos/whiteboard.png", str(f), homes)
    assert entry == {"type": None, "pending": "needs-extractor", "note": "placement-only (2.3) if an extractor is added"}


def test_transcript_branch_carries_freshness(tmp_path):
    # Cold-review finding, 2026-07-15: freshness was computed for plain-text
    # files but never for a transcript's own frontmatter, even though it's a
    # real markdown file that can carry valid_from/superseded_by like any other.
    audio = tmp_path / "standup.m4a"
    audio.write_text("hello from the meeting")
    rule = ExtractorRule(frozenset({".m4a"}), "cat", output="text")
    entry = classify_file("standup.m4a", str(audio), [], extractor_rules=[rule], base_dir=str(tmp_path))
    assert entry["source"] == "classifier-on-transcript"
    # `cat`'s stdout has no frontmatter, so no freshness block is expected here —
    # this asserts the transcript path doesn't crash while wiring build_freshness
    # in; the field's presence is exercised end-to-end in test_media.py's
    # write_transcript coverage of the frontmatter shape build_freshness reads.
    assert "freshness" not in entry


def test_residency_denial_blocks_classified_type(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("just a note")
    residency_state = {"2.4_inbound_structurer": "denied"}
    entry = classify_file("note.md", str(note), [], residency_state=residency_state)
    assert entry == {"type": None, "pending": "needs-consent"}


def test_homes_pending_branch_type_stays_null_regardless_of_residency():
    # Residency is a no-op when type is already null (nothing to gate), but the
    # call must not raise for this branch either.
    entry = classify_file(
        "photos/whiteboard.png", "/nonexistent/photos/whiteboard.png",
        [HomeRule("photos/**", "2.3")], residency_state={"2.3_inbound_structurer": "denied"},
    )
    assert entry == {"type": None, "pending": "needs-extractor", "note": "placement-only (2.3) if an extractor is added"}


def test_walk_skips_structurer_output_dir(tmp_path):
    (tmp_path / "note.md").write_text("body\n")
    structurer_dir = tmp_path / ".structurer"
    structurer_dir.mkdir()
    (structurer_dir / "type-index.json").write_text("{}")
    files = walk_and_classify(str(tmp_path), [])
    assert "note.md" in files
    assert not any(p.startswith(".structurer") for p in files)


def test_walk_skips_own_config_files(tmp_path):
    (tmp_path / "note.md").write_text("body\n")
    (tmp_path / "homes.yaml").write_text("homes: []\n")
    files = walk_and_classify(str(tmp_path), [])
    assert "note.md" in files
    assert "homes.yaml" not in files


def test_write_type_index_wraps_with_schema_version(tmp_path):
    out = tmp_path / ".structurer" / "type-index.json"
    write_type_index({"a.md": {"type": "2.4"}}, str(out))
    written = json.loads(out.read_text())
    assert written["schema_version"] == 1
    assert written["files"]["a.md"]["type"] == "2.4"


# ---------------------------------------------------------------------------
# classify.py — main() CLI
# ---------------------------------------------------------------------------

def test_default_homes_path_resolves_against_base_not_cwd(tmp_path, monkeypatch):
    # Cold-review finding, 2026-07-15 (round 2): the default `--homes homes.yaml`
    # was resolved against the process's CWD, not --base — a homes.yaml sitting in
    # the base was silently ignored, and one sitting in whatever the CWD happened to
    # be was silently applied instead. Move the CWD elsewhere with its own unrelated
    # homes.yaml, and confirm the base's own rule wins.
    base = tmp_path / "base"
    base.mkdir()
    (base / "daily-notes").mkdir()
    (base / "daily-notes" / "note.md").write_text("body\n")
    (base / "homes.yaml").write_text('homes:\n  - path: "daily-notes/**"\n    type: "2.2"\n')

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "homes.yaml").write_text('homes:\n  - path: "daily-notes/**"\n    type: "2.3"\n')
    monkeypatch.chdir(elsewhere)

    monkeypatch.setattr("sys.argv", ["classify.py", "--base", str(base)])
    main()

    written = json.loads((base / ".structurer" / "type-index.json").read_text())
    assert written["files"]["daily-notes/note.md"]["type"] == "2.2"
