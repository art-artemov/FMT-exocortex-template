#!/usr/bin/env python3
"""
Синхронизирует communication-style слои с downstream-файлами.

Трёхслойная архитектура (WP-388 Ф8):
  L0 (платформа) — memory/communication-style-base.md  → все downstream
  L1 (автор)     — $AUTHOR_STYLE_FILE (опционально)     → авторские downstream
  L2 (пользователь) — у каждого свой, не синхронизируется скриптом

Вставляет L0 между маркерами COMMUNICATION-STYLE-BASE-START/END.
Если передан --author-style, генерирует объединённый L0+L1 блок для авторских файлов.

Запуск:
    # Только L0 (платформенные downstream)
    python3 scripts/sync-communication-style.py

    # L0 + L1 (авторские downstream)
    python3 scripts/sync-communication-style.py \\
        --author-style /path/to/communication-style-author.md

    # Дополнительно: сгенерировать Hermes memory export
    python3 scripts/sync-communication-style.py \\
        --author-style /path/to/communication-style-author.md \\
        --hermes-export /path/to/hermes-style-rules.txt
"""

import argparse
import re
import sys
from pathlib import Path

# Относительно корня FMT-шаблона
BASE_FILE = Path("memory/communication-style-base.md")

# Маркеры для markdown-файлов
MD_START = "<!-- COMMUNICATION-STYLE-BASE-START -->"
MD_END = "<!-- COMMUNICATION-STYLE-BASE-END -->"

# Маркеры для JS/TS файлов
JS_START = "// COMMUNICATION-STYLE-BASE-START"
JS_END = "// COMMUNICATION-STYLE-BASE-END"

# Downstream-файлы внутри FMT-шаблона.
# type: "l0" = только база, "l0+l1" = база + авторский слой
DOWNSTREAM_FILES = [
    ("AGENTS.md", "markdown", "l0"),
    ("CLAUDE.md", "markdown", "l0"),
]


def strip_frontmatter(text: str) -> str:
    """Убирает YAML frontmatter."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text.strip()


def read_base_content(fmt_root: Path) -> str:
    """Читает L0 communication-style-base.md."""
    path = fmt_root / BASE_FILE
    if not path.exists():
        print(f"ERROR: L0 base file not found: {path}", file=sys.stderr)
        sys.exit(1)
    return strip_frontmatter(path.read_text(encoding="utf-8"))


def read_author_content(author_path: str) -> str:
    """Читает L1 communication-style-author.md."""
    path = Path(author_path)
    if not path.exists():
        print(f"WARNING: L1 author file not found: {path}, skipping L1 merge")
        return ""
    return strip_frontmatter(path.read_text(encoding="utf-8"))


def merge_l0_l1(l0: str, l1: str) -> str:
    """Объединяет L0 + L1 в один блок для авторских downstream."""
    if not l1:
        return l0
    return f"""{l0}

---

<!-- L1: авторские правила (поверх L0) -->

{l1}"""


def generate_hermes_export(l0: str, l1: str, output_path: str) -> None:
    """Генерирует компактный текст правил для Hermes memory/skill."""
    merged = merge_l0_l1(l0, l1)

    # Извлекаем нумерованные правила (строки начинающиеся с цифры и точки)
    rules = []
    for line in merged.split("\n"):
        line = line.strip()
        if re.match(r"^\d+\.\s+\*\*", line) or re.match(r"^###\s+R\d+", line):
            # Убираем markdown bold
            clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
            rules.append(clean)

    header = "# Правила разговорного стиля IWE (L0 + L1)\n"
    header += "# Автогенерация: sync-communication-style.py\n"
    header += f"# Правил: {len(rules)}\n\n"

    content = header + "\n".join(rules) + "\n"

    Path(output_path).write_text(content, encoding="utf-8")
    print(f"  HERMES  {output_path} ({len(rules)} rules)")


def update_markdown(path: Path, content: str) -> bool:
    """Обновляет markdown-файл между MD маркерами."""
    if not path.exists():
        print(f"WARNING: file not found: {path}")
        return False

    text = path.read_text(encoding="utf-8")
    pattern = f"({re.escape(MD_START)})\\n*.*?\\n*({re.escape(MD_END)})"
    replacement = f"{MD_START}\\n\\n{content}\\n\\n{MD_END}"
    new_text, count = re.subn(pattern, replacement, text, flags=re.DOTALL)

    if count == 0:
        print(f"WARNING: markers not found in {path}")
        return False

    path.write_text(new_text, encoding="utf-8")
    print(f"  OK  {path}")
    return True


def update_js(path: Path, content: str) -> bool:
    """Обновляет JS/TS файл между JS маркерами."""
    if not path.exists():
        print(f"WARNING: file not found: {path}")
        return False

    text = path.read_text(encoding="utf-8")
    escaped = content.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
    pattern = f"({re.escape(JS_START)})\\n*.*?\\n*({re.escape(JS_END)})"
    replacement = f"{JS_START}\\n{escaped}\\n{JS_END}"
    new_text, count = re.subn(pattern, replacement, text, flags=re.DOTALL)

    if count == 0:
        print(f"WARNING: markers not found in {path}")
        return False

    path.write_text(new_text, encoding="utf-8")
    print(f"  OK  {path}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Sync communication style layers to downstream files"
    )
    parser.add_argument(
        "--author-style",
        help="Path to L1 author style file (communication-style-author.md)",
    )
    parser.add_argument(
        "--hermes-export",
        help="Path to write Hermes-compatible rules export",
    )
    args = parser.parse_args()

    fmt_root = Path(__file__).parent.parent
    l0 = read_base_content(fmt_root)
    l1 = read_author_content(args.author_style) if args.author_style else ""

    ok_count = 0
    skip_count = 0

    print(f"Syncing L0 ({len(l0)} chars)" + (f" + L1 ({len(l1)} chars)" if l1 else "") + "...")

    for rel_path, ftype, layer_mode in DOWNSTREAM_FILES:
        path = fmt_root / rel_path
        if not path.exists():
            print(f"SKIP {rel_path} (not found)")
            skip_count += 1
            continue

        # Выбираем контент в зависимости от слоя
        if layer_mode == "l0+l1" and l1:
            content = merge_l0_l1(l0, l1)
        else:
            content = l0

        if ftype == "markdown":
            if update_markdown(path, content):
                ok_count += 1
        elif ftype == "js":
            if update_js(path, content):
                ok_count += 1
        else:
            print(f"UNKNOWN type {ftype} for {rel_path}")
            skip_count += 1

    # Hermes export
    if args.hermes_export:
        generate_hermes_export(l0, l1, args.hermes_export)

    print(f"Done: {ok_count} updated, {skip_count} skipped.")
    return 0 if skip_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
