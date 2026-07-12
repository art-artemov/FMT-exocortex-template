#!/usr/bin/env python3
"""Patch DayPlan budget line with deterministic sum from plan table.

Replaces whatever the LLM wrote with the actual sum of the h column.
Reads optional phys_hours override from priorities.yaml; defaults to h_rp
(multiplier = 1.0x) when not set.
"""

import re
import sys
import argparse
from pathlib import Path

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


BUDGET_RE = re.compile(
    r"\*\*Бюджет дня:\*\* ~[\d.]+h РП / ~[\d.]+h физ / Плановый мультипликатор ~[\d.]+x"
)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dayplan", required=True, help="Path to DayPlan .md")
    p.add_argument("--priorities", default=None, help="Path to priorities.yaml (optional)")
    return p.parse_args()


def detect_h_col(header_cells):
    """Return index of 'h' column in split table row, or None."""
    for i, cell in enumerate(header_cells):
        if cell.strip() == "h":
            return i
    return None


def sum_plan_hours(text):
    """Sum h column from the plan table (header row must contain 'h')."""
    in_table = False
    h_col = None
    total = 0.0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue
        cells = stripped.split("|")
        # Separator row: all cells are dashes/colons
        if all(re.match(r"^[-:\s]*$", c) for c in cells):
            continue
        # Header detection
        if not in_table:
            h_col = detect_h_col(cells)
            if h_col is not None:
                in_table = True
            continue
        # Data row — only parse cells that look like numbers (skip text/emoji)
        if h_col is not None and len(cells) > h_col:
            val = cells[h_col].strip()
            if re.match(r"^\d+(\.\d+)?$", val):
                total += float(val)
    return total


def read_phys_hours(priorities_path):
    """Return phys_hours from priorities.yaml if explicitly set, else None."""
    if not priorities_path:
        return None
    path = Path(priorities_path)
    if not path.exists():
        return None
    if _YAML_AVAILABLE:
        with open(path, encoding="utf-8") as f:
            data = _yaml.safe_load(f) or {}
        val = data.get("phys_hours")
        return float(val) if val else None
    # PyYAML unavailable: fall back to single-line regex for this one key only
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^phys_hours:\s*([\d.]+)", line)
        if m:
            print("budget-patch: PyYAML not installed, using regex fallback for phys_hours", file=sys.stderr)
            return float(m.group(1))
    return None


def patch_budget(text, h_rp, h_phys):
    mult = h_rp / h_phys if h_phys else 1.0
    replacement = (
        f"**Бюджет дня:** ~{h_rp:.0f}h РП"
        f" / ~{h_phys:.0f}h физ"
        f" / Плановый мультипликатор ~{mult:.1f}x"
    )
    return BUDGET_RE.sub(replacement, text)


def main():
    args = parse_args()
    dayplan = Path(args.dayplan)
    text = dayplan.read_text(encoding="utf-8")

    h_rp = sum_plan_hours(text)
    if h_rp == 0.0:
        print("budget-patch: no plan hours found — skipping", file=sys.stderr)
        return

    h_phys = read_phys_hours(args.priorities) or h_rp
    patched = patch_budget(text, h_rp, h_phys)

    if patched == text:
        print(f"budget-patch: budget line not found or already correct (h_rp={h_rp})", file=sys.stderr)
        return

    dayplan.write_text(patched, encoding="utf-8")
    mult = h_rp / h_phys if h_phys else 1.0
    print(f"budget-patch: ~{h_rp:.0f}h РП / ~{h_phys:.0f}h физ / ~{mult:.1f}x", file=sys.stderr)


if __name__ == "__main__":
    main()
