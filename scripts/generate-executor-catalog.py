#!/usr/bin/env python3
"""
generate-executor-catalog.py — собрать executor-catalog.yaml из routing: секций SKILL.md.

Читает все SKILL.md из ~/.claude/skills/, извлекает routing: блок,
генерирует executor-catalog.yaml для Маршрутизатора (DP.ROLE.059, WP-350 Ф8).

Запуск:
    python3 generate-executor-catalog.py [--validate] [--output PATH]

Exit: 0 = OK, 1 = error, 2 = validation failure (missing routing: sections)

see DP.SC.159, DP.ROLE.059
"""

import os
import re
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SKILLS_DIR = Path.home() / "IWE" / ".claude" / "skills"
DEFAULT_OUTPUT = Path.home() / "IWE" / os.environ.get("IWE_GOVERNANCE_REPO", "DS-strategy") / "scripts" / "executor-catalog.yaml"

VALID_EXECUTORS = {"script", "haiku", "sonnet", "opus", "mcp-direct"}
FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---\n', re.DOTALL)
ROUTING_BLOCK_RE = re.compile(
    r'^routing:\n((?:[ \t]+[^\n]+\n?)*)',
    re.MULTILINE
)


def extract_routing_block(fm_content: str) -> Optional[dict]:
    """Extract routing: block from raw frontmatter string (handles unquoted colon values)."""
    m = ROUTING_BLOCK_RE.search(fm_content)
    if not m:
        return None
    block_text = "routing:\n" + m.group(1)
    try:
        data = yaml.safe_load(block_text)
        return data.get("routing") if data else None
    except yaml.YAMLError:
        return None


def extract_name(fm_content: str) -> Optional[str]:
    m = re.search(r'^name:\s*(.+)$', fm_content, re.MULTILINE)
    return m.group(1).strip() if m else None


def extract_description(fm_content: str) -> Optional[str]:
    m = re.search(r'^description:\s*(.+)$', fm_content, re.MULTILINE)
    if not m:
        return None
    desc = m.group(1).strip()
    # Truncate long descriptions for catalog readability
    return desc[:120] + "..." if len(desc) > 120 else desc


def extract_triggers(fm_content: str) -> list[str]:
    m = re.search(r'^  slash:\s*\[([^\]]*)\]', fm_content, re.MULTILINE)
    if not m:
        return []
    raw = m.group(1)
    return [t.strip() for t in raw.split(",") if t.strip()]


def process_skill(skill_dir: Path) -> Optional[dict]:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None

    text = skill_file.read_text(encoding="utf-8")
    fm_match = FRONTMATTER_RE.match(text)
    if not fm_match:
        return None

    fm_content = fm_match.group(1)
    name = extract_name(fm_content)
    if not name:
        return None

    routing = extract_routing_block(fm_content)
    if not routing:
        return None  # skill has no routing: — skip

    return {
        "name": name,
        "type": "skill",
        "path": f".claude/skills/{skill_dir.name}/SKILL.md",
        "slash": extract_triggers(fm_content),
        "description": extract_description(fm_content),
        "routing": routing,
    }


def validate_entry(entry: dict) -> list[str]:
    errors = []
    r = entry.get("routing", {})
    executor = r.get("executor")
    if executor not in VALID_EXECUTORS:
        errors.append(f"{entry['name']}: invalid executor '{executor}', expected {VALID_EXECUTORS}")
    if "deterministic" not in r:
        errors.append(f"{entry['name']}: routing.deterministic missing")
    if executor == "script" and "script_path" not in r:
        # Warning, not error — script_path may be added later
        pass
    return errors


def build_catalog(skills_dir: Path) -> dict:
    entries = []
    skipped = []
    all_errors = []

    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        entry = process_skill(skill_dir)
        if entry is None:
            skipped.append(skill_dir.name)
            continue
        errors = validate_entry(entry)
        if errors:
            all_errors.extend(errors)
            continue
        entries.append(entry)

    if all_errors:
        print("Validation errors:", file=sys.stderr)
        for e in all_errors:
            print(f"  {e}", file=sys.stderr)
        sys.exit(2)

    # Group by executor for catalog sections
    by_executor: dict[str, list] = {}
    for e in entries:
        executor = e["routing"]["executor"]
        by_executor.setdefault(executor, []).append(e)

    # Build summary stats
    stats = {ex: len(items) for ex, items in by_executor.items()}

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": "1.0",
        "generated_at": now,
        "source": ".claude/skills/*/SKILL.md",
        "generator": "${IWE_GOVERNANCE_REPO:-DS-strategy}/scripts/generate-executor-catalog.py",
        "wp": "WP-350",
        "total_entries": len(entries),
        "skipped_no_routing": len(skipped),
        "by_executor": stats,
        "entries": entries,
    }


def print_summary(catalog: dict):
    print(f"OK: executor-catalog generated")
    print(f"    total entries : {catalog['total_entries']}")
    print(f"    skipped       : {catalog['skipped_no_routing']} (no routing: section)")
    print(f"    by executor:")
    for ex, count in sorted(catalog["by_executor"].items()):
        print(f"      {ex:12s}: {count}")
    # Show optimization candidates
    candidates = [
        e for e in catalog["entries"]
        if e["routing"].get("optimization_priority") is not None
    ]
    if candidates:
        print(f"    optimization candidates ({len(candidates)}):")
        for c in sorted(candidates, key=lambda x: x["routing"]["optimization_priority"]):
            prio = c["routing"]["optimization_priority"]
            print(f"      [{prio}] {c['name']} → {c['routing']['executor']}")


def main():
    validate_only = "--validate" in sys.argv
    output_path = DEFAULT_OUTPUT
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--output" and i + 2 < len(sys.argv):
            output_path = Path(sys.argv[i + 2])

    if not SKILLS_DIR.exists():
        print(f"ERROR: {SKILLS_DIR} not found", file=sys.stderr)
        sys.exit(1)

    catalog = build_catalog(SKILLS_DIR)

    if validate_only:
        print(f"OK: {catalog['total_entries']} entries validated")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(catalog, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    print_summary(catalog)
    print(f"    output        : {output_path}")


if __name__ == "__main__":
    main()
