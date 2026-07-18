"""
test_residency.py — guide-kit structurer tests, residency access-check slice
Run: cd structurer && pytest
"""
from __future__ import annotations

from residency import check_access, load_residency_state


def test_missing_state_file_is_cold_start(tmp_path):
    assert load_residency_state(str(tmp_path)) == {}


def test_malformed_state_file_treated_as_no_denials(tmp_path):
    state_dir = tmp_path / ".structurer"
    state_dir.mkdir()
    (state_dir / "residency-state.yaml").write_text("consents: [unclosed\n")
    assert load_residency_state(str(tmp_path)) == {}


def test_no_entry_defaults_to_allowed():
    assert check_access({}, "2.1-derived") is True


def test_explicit_denial_blocks_access():
    state = {"2.1-derived_inbound_structurer": "denied"}
    assert check_access(state, "2.1-derived") is False


def test_granted_entry_allows_access():
    state = {"2.1-derived_inbound_structurer": "granted"}
    assert check_access(state, "2.1-derived") is True


def test_denial_is_scoped_to_its_own_data_type():
    state = {"2.1-derived_inbound_structurer": "denied"}
    assert check_access(state, "2.2") is True


def test_state_roundtrip_from_disk(tmp_path):
    state_dir = tmp_path / ".structurer"
    state_dir.mkdir()
    (state_dir / "residency-state.yaml").write_text(
        "schema_version: 1\nconsents:\n  2.3_inbound_structurer: denied\n"
    )
    state = load_residency_state(str(tmp_path))
    assert check_access(state, "2.3") is False
    assert check_access(state, "2.2") is True
