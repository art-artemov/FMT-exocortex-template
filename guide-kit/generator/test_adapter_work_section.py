"""Tests for adapter.py's work_section wiring.

adapter.py itself had no prior test file (render_markdown/generate_daily_plan
were previously untested) — these cover only the new work_section param and
its integration into generate_daily_plan, not a full adapter.py suite.
"""

import json
import os
from unittest.mock import patch

from adapter import generate_daily_plan, render_markdown
from llm_backends import GenerationResult


class TestRenderMarkdownWorkSection:
    def test_no_work_section_is_unchanged(self):
        md = render_markdown("narrative text", [], [])
        assert "## Рабочая часть" not in md

    def test_work_section_appears_before_onboarding_appendix(self):
        md = render_markdown(
            "narrative text",
            [],
            [],
            onboarding_appendix="### Дальше — платформа",
            work_section_markdown="## Рабочая часть\n\n- **item**",
        )
        work_pos = md.index("## Рабочая часть")
        onboarding_pos = md.index("### Дальше")
        assert work_pos < onboarding_pos

    def test_empty_work_section_adds_nothing(self):
        md = render_markdown("narrative text", [], [], work_section_markdown="")
        assert "Рабочая часть" not in md


class TestGenerateDailyPlanWorkSectionIntegration:
    def _fake_llm_ok(self, *_args, **_kwargs):
        return GenerationResult(
            text='{"narrative": "текст", "plan_day": [{"label": "задание", "tomatoes": 1}]}',
            backend_id="fake",
            model="fake",
        )

    def test_work_section_off_by_default(self, tmp_path):
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text("{}", encoding="utf-8")
        with patch("adapter.llm_generate", side_effect=self._fake_llm_ok):
            result = generate_daily_plan(str(profile_path))
        assert result.ok
        assert "Рабочая часть" not in result.markdown

    def test_base_path_null_in_yaml_does_not_crash(self, tmp_path):
        """guide-kit.config.yaml.example ships base_path: null — a present key
        with value None, not an absent key. config.get("base_path", ".") would
        return None (not the default) and crash os.path.join downstream
        (found during code review, reproduced with a traceback)."""
        os.makedirs(tmp_path / ".structurer")
        index = {"schema_version": 1, "files": {"notes/task.md": {"type": "2.2"}}}
        (tmp_path / ".structurer" / "type-index.json").write_text(json.dumps(index), encoding="utf-8")

        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text("{}", encoding="utf-8")
        config_path = tmp_path / "guide-kit.config.yaml"
        # base_path: null with work_section run from tmp_path's cwd wouldn't find
        # the fixture — so this test only asserts it doesn't crash, matching the
        # example file's literal shape (a present null key).
        config_path.write_text("work_section: generic\nbase_path: null\n", encoding="utf-8")

        with patch("adapter.llm_generate", side_effect=self._fake_llm_ok):
            result = generate_daily_plan(str(profile_path), str(config_path))
        assert result.ok

    def test_work_section_generic_lists_2_2_files(self, tmp_path):
        os.makedirs(tmp_path / ".structurer")
        index = {"schema_version": 1, "files": {"notes/task.md": {"type": "2.2"}}}
        (tmp_path / ".structurer" / "type-index.json").write_text(json.dumps(index), encoding="utf-8")

        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text("{}", encoding="utf-8")
        config_path = tmp_path / "guide-kit.config.yaml"
        config_path.write_text(f"work_section: generic\nbase_path: {tmp_path}\n", encoding="utf-8")

        with patch("adapter.llm_generate", side_effect=self._fake_llm_ok):
            result = generate_daily_plan(str(profile_path), str(config_path))
        assert result.ok
        assert "## Рабочая часть" in result.markdown
        assert "task" in result.markdown

    def test_work_section_decision_log_entries_are_merged(self, tmp_path):
        os.makedirs(tmp_path / ".structurer")
        index = {"schema_version": 1, "files": {"notes/task.md": {"type": "2.2"}}}
        (tmp_path / ".structurer" / "type-index.json").write_text(json.dumps(index), encoding="utf-8")

        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text("{}", encoding="utf-8")
        config_path = tmp_path / "guide-kit.config.yaml"
        config_path.write_text(f"work_section: generic\nbase_path: {tmp_path}\n", encoding="utf-8")

        with patch("adapter.llm_generate", side_effect=self._fake_llm_ok):
            result = generate_daily_plan(str(profile_path), str(config_path))
        assert result.ok
        decision_log_start = result.markdown.index("<!-- decision_log:")
        decision_log_json = result.markdown[decision_log_start:].split("\n", 1)[1].rsplit("-->", 1)[0]
        entries = json.loads(decision_log_json)
        assert any(e["slot"] == "work_section" for e in entries)
