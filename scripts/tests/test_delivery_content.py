"""
Содержательные тесты доставки перевода (WP-415 Ф-В2): перевод корректен.

Tier-1 термины глоссария, оставшиеся непереведёнными — блокирующая ошибка.
Tier-2/3 — предупреждение (не блокирует workflow). Кириллица внутри
блоков кода игнорируется — это код, а не проза.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from delivery_checks import GlossaryTerm, check_content  # noqa: E402


def test_fully_translated_text_has_no_findings():
    terms = [GlossaryTerm("Пак", tier=1), GlossaryTerm("Конвейер", tier=1)]
    output = "The Pack ships through the pipeline automatically.\n"

    report = check_content(output, terms)

    assert report.passed
    assert report.tier1_violations == []
    assert report.warnings == []


def test_leftover_tier1_term_is_a_violation():
    terms = [GlossaryTerm("Пак", tier=1)]
    output = "The Пак ships automatically.\n"

    report = check_content(output, terms)

    assert not report.passed
    assert len(report.tier1_violations) == 1
    assert "Пак" in report.tier1_violations[0]


def test_leftover_tier3_term_is_only_a_warning():
    terms = [GlossaryTerm("Различение", tier=3)]
    output = "This section covers a Различение in detail.\n"

    report = check_content(output, terms)

    assert report.passed  # warnings do not block
    assert report.tier1_violations == []
    assert len(report.warnings) == 1


def test_leftover_term_inside_code_block_is_exempt():
    terms = [GlossaryTerm("Пак", tier=1)]
    output = "Run the command:\n\n```bash\necho Пак\n```\n"

    report = check_content(output, terms)

    assert report.passed
    assert report.tier1_violations == []


def test_missing_tier_column_defaults_to_warning_not_failure():
    terms = [GlossaryTerm("Скилл", tier=3)]  # tier=3 is the loader's default for blank tier
    output = "The Скилл concept is central here.\n"

    report = check_content(output, terms)

    assert report.passed
    assert len(report.warnings) == 1


def test_term_as_substring_of_longer_word_is_not_a_false_positive():
    # "Поток" is a real glossary term; "Потоковый" contains it as a substring
    # but is a different word — must not trigger a false Tier-1 failure.
    terms = [GlossaryTerm("Поток", tier=1)]
    output = "This describes a Потоковый process, translated as streaming.\n"

    report = check_content(output, terms)

    assert report.passed
    assert report.tier1_violations == []
