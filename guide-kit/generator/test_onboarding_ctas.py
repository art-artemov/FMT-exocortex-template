"""Tests for onboarding_ctas.py. Run: cd generator && pytest"""

from onboarding_ctas import DEFAULT_PLATFORM_CONNECT_URL, render_onboarding_ctas


class TestRenderOnboardingCtas:
    def test_disabled_returns_empty(self):
        assert render_onboarding_ctas({"onboarding_ctas": False}) == ""

    def test_default_is_enabled(self):
        assert render_onboarding_ctas({}) != ""

    def test_no_url_configured_uses_platform_default(self):
        appendix = render_onboarding_ctas({"onboarding_ctas": True})
        assert f"Ссылка: {DEFAULT_PLATFORM_CONNECT_URL}" in appendix

    def test_null_url_in_config_uses_platform_default(self):
        """guide-kit.config.yaml.example uses YAML `null` as its "not configured"
        sentinel for optional fields (same convention as curriculum_path/cards_path
        in adapter.py) — yaml.safe_load turns that into Python None, which must be
        treated the same as an absent key, not as an explicit blank override."""
        appendix = render_onboarding_ctas({"onboarding_ctas": True, "platform_connect_url": None})
        assert f"Ссылка: {DEFAULT_PLATFORM_CONNECT_URL}" in appendix

    def test_explicit_blank_url_omits_link_line(self):
        appendix = render_onboarding_ctas({"onboarding_ctas": True, "platform_connect_url": ""})
        assert "Ссылка:" not in appendix
        assert "MCP-серверу платформы" in appendix

    def test_custom_url_overrides_default(self):
        appendix = render_onboarding_ctas(
            {"onboarding_ctas": True, "platform_connect_url": "https://example.invalid/connect"}
        )
        assert "Ссылка: https://example.invalid/connect" in appendix
        assert DEFAULT_PLATFORM_CONNECT_URL not in appendix

    def test_no_cascade_enumeration(self):
        """The CTA text must never list the onboarding cascade as a procedure
        (account → subscription → consent → diagnostics → sensors) — that would
        be a soft copy of the platform's own state machine, the exact anti-pattern
        this phase's consensus forbids."""
        appendix = render_onboarding_ctas({})
        for word in ("аккаунт", "подписк", "согласи", "диагностик", "сенсор"):
            assert word not in appendix.lower()

    def test_includes_iwe_setup_step(self):
        appendix = render_onboarding_ctas({})
        assert "setup.sh" in appendix
        assert "Claude Code" in appendix
