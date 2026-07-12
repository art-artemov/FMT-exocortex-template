#!/usr/bin/env python3
"""Unit tests for manifest parser."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from parser import ManifestParser, DataNeed


def test_parse_yaml_needs():
    """Test parsing YAML-style data-needs in markdown."""
    content = """
# SKILL.md

data_needs:
  - type: 2.1, flow: inbound, name: user-profile
  - type: 2.2, flow: outbound, name: data-export
"""
    needs = ManifestParser.parse_markdown(content, "test-skill")
    assert len(needs) == 2
    assert needs[0].type == "2.1"
    assert needs[0].flow_direction == "inbound"
    assert needs[0].name == "user-profile"
    assert needs[1].type == "2.2"
    assert needs[1].flow_direction == "outbound"


def test_parse_bash_manifest():
    """Test parsing bash-style # --- data-needs --- block."""
    content = """#!/bin/bash
# --- data-needs
# type: 2.2, flow_direction: inbound, name: daily-summary
# schema_version: 1
# ---
"""
    needs = ManifestParser.parse_bash_manifest(content, "day-open-hook")
    assert len(needs) == 1
    assert needs[0].type == "2.2"
    assert needs[0].flow_direction == "inbound"
    assert needs[0].schema_version == 1


def test_data_need_key():
    """Test DataNeed key generation."""
    need = DataNeed(
        name="test-data",
        type="2.1",
        flow_direction="inbound",
        schema_version=1
    )
    assert need.key() == "2.1_inbound_test-data"


def test_empty_manifest():
    """Test parsing file with no data-needs."""
    content = "# Some markdown without data needs"
    needs = ManifestParser.parse_markdown(content, "empty-skill")
    assert len(needs) == 0


if __name__ == "__main__":
    test_parse_yaml_needs()
    test_parse_bash_manifest()
    test_data_need_key()
    test_empty_manifest()
    print("✓ All tests passed")
