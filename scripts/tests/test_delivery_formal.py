"""
Формальные тесты доставки перевода (WP-415 Ф-В2): файл физически дошёл.

Проверяем check_formal() на синтетических парах source/output — без сети,
без вызова LLM. Реальный прогон translate.py --mode=delta тестируется
отдельно (test_translate_delta.py) на уровне выбора файлов, не перевода.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from delivery_checks import check_formal  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_valid_pair_passes(tmp_path):
    source = tmp_path / "docs" / "README.md"
    output = tmp_path / "en-out" / "docs" / "README.md"
    _write(source, "---\ntitle: Пример\n---\nТело.\n")
    _write(output, "---\ntitle: Example\n---\nBody.\n")

    assert check_formal(source, output) == []


def test_missing_output_fails(tmp_path):
    source = tmp_path / "docs" / "README.md"
    output = tmp_path / "en-out" / "docs" / "README.md"
    _write(source, "Текст.\n")

    violations = check_formal(source, output)
    assert len(violations) == 1
    assert "missing" in violations[0]


def test_empty_output_fails(tmp_path):
    source = tmp_path / "docs" / "README.md"
    output = tmp_path / "en-out" / "docs" / "README.md"
    _write(source, "Текст.\n")
    _write(output, "")

    violations = check_formal(source, output)
    assert any("empty" in v for v in violations)


def test_output_without_frontmatter_when_source_has_it_fails(tmp_path):
    source = tmp_path / "docs" / "README.md"
    output = tmp_path / "en-out" / "docs" / "README.md"
    _write(source, "---\ntitle: Пример\n---\nТело.\n")
    _write(output, "Body without frontmatter.\n")

    violations = check_formal(source, output)
    assert any("frontmatter" in v for v in violations)


def test_stale_output_older_than_source_fails(tmp_path):
    source = tmp_path / "docs" / "README.md"
    output = tmp_path / "en-out" / "docs" / "README.md"
    _write(output, "Old translation.\n")
    time.sleep(0.05)
    _write(source, "Изменённый текст.\n")  # source edited AFTER output was generated

    violations = check_formal(source, output)
    assert any("stale" in v for v in violations)
