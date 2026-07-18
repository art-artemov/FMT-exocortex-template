"""Standalone acceptance runner for the work-section feature (MVP
acceptance, "main scenario"). Imports ONLY work_section.render_work_section
— never adapter.py or llm_backends — so this tool cannot make an LLM call or
touch a platform token by construction, not by promise. Safe to run directly
against a pilot's real base_path for a read-only accuracy check.

Usage:
    python3 render_work_section_runner.py --config path/to/config.yaml [--base PATH]

Exits 0 and prints the rendered section (or "(empty)") plus one decision_log
line per referenced item. Exits 1 on a config load error.
"""
from __future__ import annotations

import argparse
import sys

import yaml

from work_section import render_work_section


def _load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="sanitized config.yaml (work_section, dayplan_path)")
    parser.add_argument("--base", default=None, help="override config's base_path (default: config.base_path, then cwd)")
    args = parser.parse_args(argv)

    try:
        config = _load_config(args.config)
    except (OSError, yaml.YAMLError) as e:
        print(f"ERROR: could not load config at {args.config!r}: {e}", file=sys.stderr)
        return 1
    if not isinstance(config, dict):
        print(f"ERROR: config at {args.config!r} is not a YAML mapping (got {type(config).__name__})", file=sys.stderr)
        return 1
    # base_path/dayplan_path are the two config values work_section.py actually
    # consumes as paths/templates (os.path.join, str.format) — a wrong type here
    # (e.g. a YAML list from a stray indent) would otherwise surface as a raw
    # TypeError/AttributeError instead of the diagnostic this tool promises
    # (found by independent verification, 2026-07-17).
    for key in ("base_path", "dayplan_path"):
        value = config.get(key)
        if value is not None and not isinstance(value, str):
            print(f"ERROR: config key {key!r} must be a string (got {type(value).__name__}: {value!r})", file=sys.stderr)
            return 1

    # Mirrors adapter.py's own call site exactly (generate_daily_plan), so this
    # runner is a faithful proxy for the real work-section behavior, not an
    # approximation with its own default.
    base = args.base or config.get("base_path") or "."
    markdown, log = render_work_section(config, base)

    print(markdown or "(empty)")
    print("\n--- decision_log ---", file=sys.stderr)
    for entry in log:
        print(f"  wp={entry.get('value')!r} method={entry['extraction_method']!r} note={entry.get('note')!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
