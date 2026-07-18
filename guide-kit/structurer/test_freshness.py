"""
test_freshness.py — guide-kit structurer tests, freshness slice (FORMAT.md §7).
Run: cd structurer && pytest
"""
from __future__ import annotations

from freshness import build_freshness


def test_no_valid_from_returns_none():
    assert build_freshness({}, "note.md") is None


def test_valid_from_with_ttl():
    result = build_freshness({"valid_from": "2026-05-01", "ttl_days": 180}, "note.md")
    assert result == {"valid_from": "2026-05-01", "ttl_days": 180}


def test_valid_from_with_superseded_by_null():
    result = build_freshness({"valid_from": "2026-05-01", "superseded_by": None}, "note.md")
    assert result == {"valid_from": "2026-05-01", "superseded_by": None}


def test_valid_from_with_superseded_by_set():
    result = build_freshness({"valid_from": "2026-05-01", "superseded_by": "notes/newer.md"}, "note.md")
    assert result == {"valid_from": "2026-05-01", "superseded_by": "notes/newer.md"}


def test_valid_from_with_both_mechanisms_is_malformed():
    result = build_freshness({"valid_from": "2026-05-01", "ttl_days": 180, "superseded_by": None}, "note.md")
    assert result is None


def test_valid_from_with_neither_mechanism_is_malformed():
    result = build_freshness({"valid_from": "2026-05-01"}, "note.md")
    assert result is None


def test_non_integer_ttl_days_ignored():
    assert build_freshness({"valid_from": "2026-05-01", "ttl_days": "a while"}, "note.md") is None
