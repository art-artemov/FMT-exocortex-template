#!/usr/bin/env python3
"""
generate-executor-catalog.py — собрать executor-catalog.yaml из routing: секций SKILL.md.

Читает все SKILL.md из ~/.claude/skills/, извлекает routing: блок,
генерирует executor-catalog.yaml для Маршрутизатора (DP.ROLE.059, WP-350 Ф8).

Запуск:
    python3 generate-executor-catalog.py [--validate] [--skills-dir PATH] [--output PATH]

Exit: 0 = OK, 1 = error, 2 = validation failure (missing routing: sections)

see DP.SC.159, DP.ROLE.059
"""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Optional

import yaml

# issue #222: таксономия де-факто — нормативного источника в docs/ нет,
# список описывает реально используемые режимы исполнения скиллов.
# agent = прогон как subagent; script+judgment = скрипт с LLM-слоем суждения.
VALID_EXECUTORS = {"script", "haiku", "sonnet", "opus", "mcp-direct", "agent", "script+judgment"}
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
    if executor == "agent" and r.get("model") not in {"haiku", "sonnet", "opus"}:
        errors.append(
            f"{entry['name']}: agent executor requires model: haiku|sonnet|opus"
        )
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
        "generator": "scripts/generate-executor-catalog.py",
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


def _workspace_root() -> Path:
    configured = os.environ.get("IWE_ROOT") or os.environ.get("IWE_WORKSPACE")
    return Path(configured).expanduser() if configured else Path.home() / "IWE"


def _parse_args() -> argparse.Namespace:
    workspace = _workspace_root()
    governance_repo = os.environ.get("IWE_GOVERNANCE_REPO", "DS-strategy")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate routing entries without writing the catalog",
    )
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=workspace / ".claude" / "skills",
        help="Directory containing skill subdirectories",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=workspace / governance_repo / "scripts" / "executor-catalog.yaml",
        help="Catalog output path",
    )
    return parser.parse_args()


def _without_generation_time(catalog: dict) -> dict:
    """Return the semantic catalog payload used for idempotency checks."""
    return {key: value for key, value in catalog.items() if key != "generated_at"}


def _write_catalog_if_changed(catalog: dict, output_path: Path) -> bool:
    """Atomically replace output only when its semantic content changed."""
    if output_path.is_file():
        try:
            existing = yaml.safe_load(output_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            existing = None
        if isinstance(existing, dict) and _without_generation_time(existing) == _without_generation_time(catalog):
            return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            yaml.safe_dump(
                catalog,
                temporary,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
            temporary_path = Path(temporary.name)
        temporary_path.chmod(0o644)
        temporary_path.replace(output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return True


def main():
    args = _parse_args()
    skills_dir = args.skills_dir.expanduser()
    output_path = args.output.expanduser()

    if not skills_dir.is_dir():
        print(f"ERROR: {skills_dir} not found", file=sys.stderr)
        sys.exit(1)

    catalog = build_catalog(skills_dir)

    if args.validate:
        print(f"OK: {catalog['total_entries']} entries validated")
        return

    changed = _write_catalog_if_changed(catalog, output_path)
    print_summary(catalog)
    print(f"    output        : {output_path} ({'updated' if changed else 'unchanged'})")


if __name__ == "__main__":
    main()
