"""
test_sidecar.py — guide-kit structurer tests, sidecar slice (FORMAT.md §5).
Run: cd structurer && pytest
"""
from __future__ import annotations

from sidecar import read_sidecar, read_sidecar_type, sidecar_forces_quarantine


def test_missing_sidecar_returns_empty(tmp_path):
    abs_path = str(tmp_path / "recording.m4a")
    assert read_sidecar(abs_path) == {}


def test_sidecar_read_roundtrip(tmp_path):
    abs_path = tmp_path / "recording.m4a"
    (tmp_path / "recording.m4a.meta.yaml").write_text('type: "2.2"\nnote: "standup"\n')
    sidecar = read_sidecar(str(abs_path))
    assert sidecar == {"type": "2.2", "note": "standup"}


def test_malformed_sidecar_treated_as_absent(tmp_path):
    abs_path = tmp_path / "recording.m4a"
    (tmp_path / "recording.m4a.meta.yaml").write_text("type: [unclosed\n")
    assert read_sidecar(str(abs_path)) == {}


def test_sidecar_not_a_mapping_treated_as_absent(tmp_path):
    abs_path = tmp_path / "recording.m4a"
    (tmp_path / "recording.m4a.meta.yaml").write_text("- just\n- a\n- list\n")
    assert read_sidecar(str(abs_path)) == {}


def test_sidecar_type_recognized():
    assert read_sidecar_type({"type": "2.3"}, "recording.m4a") == "2.3"


def test_sidecar_type_unrecognized_ignored():
    assert read_sidecar_type({"type": "9.9"}, "recording.m4a") is None


def test_sidecar_type_absent():
    assert read_sidecar_type({}, "recording.m4a") is None


def test_sidecar_forces_quarantine_true():
    assert sidecar_forces_quarantine({"speakers_third_party": True}, "recording.m4a") is True


def test_sidecar_forces_quarantine_quoted_true():
    # Same YAML-quoting hazard signals.read_bool_field guards for frontmatter.
    assert sidecar_forces_quarantine({"speakers_third_party": "true"}, "recording.m4a") is True


def test_sidecar_forces_quarantine_absent():
    assert sidecar_forces_quarantine({"type": "2.2"}, "recording.m4a") is False
