"""
Tests for platform_knowledge.py (DP.SC.060 scenario 1: live public MCP fallback
for card content) and its wiring into adapter.load_card_content.

Unit coverage:
- allowlist rejects an unlisted tool before network
- no Authorization header is sent (public slope, no token — unlike personal_export)
- degradations: HTTP error, empty body, non-JSON, empty/malformed results → None, no raise
- adapter.load_card_content: local hit wins over platform; local miss + flag off → None
  (no network attempted); local miss + flag on → platform fallback used
"""
import json
import os
import sys
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

import platform_knowledge as pk
from adapter import load_card_content

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests", "acceptance"))
from stub_mcp_server import start_stub_mcp_server  # noqa: E402 — path setup must precede this import


@pytest.fixture
def stub_mcp_server():
    server, port = start_stub_mcp_server()
    yield port
    server.shutdown()


# ---------------------------------------------------------------------------
# allowlist
# ---------------------------------------------------------------------------

class TestAllowlist:
    def test_unknown_tool_rejected_before_network(self):
        with pytest.raises(ValueError, match="not in allowlist"):
            pk._rpc_call("http://localhost/mcp", "some_other_tool", {})

    def test_read_tools_allowed(self):
        for tool in pk._READ_TOOLS:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}'
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = pk._rpc_call("http://localhost/mcp", tool, {})
            assert result == {"ok": True}


# ---------------------------------------------------------------------------
# no token on the public slope (unlike personal_export._rpc_call)
# ---------------------------------------------------------------------------

class TestNoAuthHeader:
    def test_request_carries_no_authorization_header(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"jsonrpc":"2.0","id":1,"result":{}}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        captured_req = {}

        def _capture(req, timeout=None):
            captured_req["req"] = req
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=_capture):
            pk._rpc_call("http://localhost/mcp", "knowledge_search", {"query": "x"})

        assert "Authorization" not in captured_req["req"].headers


# ---------------------------------------------------------------------------
# degradations — never raise out of fetch_card_content
# ---------------------------------------------------------------------------

def _make_http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url="http://test", code=code, msg="error", hdrs=None, fp=None)


class TestDegradations:
    def test_http_error_returns_none(self):
        with patch("urllib.request.urlopen", side_effect=_make_http_error(500)):
            assert pk.fetch_card_content("CAT.001.A1", "http://x") is None

    def test_empty_body_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b""
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert pk.fetch_card_content("CAT.001.A1", "http://x") is None

    def test_non_json_body_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert pk.fetch_card_content("CAT.001.A1", "http://x") is None

    def test_empty_results_list_returns_none(self):
        with patch.object(pk, "_rpc_call", return_value={"content": [{"type": "text", "text": json.dumps({"results": []})}]}):
            assert pk.fetch_card_content("CAT.001.A1") is None

    def test_result_missing_text_field_returns_none(self):
        payload = {"results": [{"title": "no content or text field"}]}
        with patch.object(pk, "_rpc_call", return_value={"content": [{"type": "text", "text": json.dumps(payload)}]}):
            assert pk.fetch_card_content("CAT.001.A1") is None


# ---------------------------------------------------------------------------
# success path
# ---------------------------------------------------------------------------

class TestFetchSuccess:
    def test_returns_text_title_and_source(self):
        payload = {"results": [{"content": "материал по теме", "title": "Заголовок"}]}
        with patch.object(pk, "_rpc_call", return_value={"content": [{"type": "text", "text": json.dumps(payload)}]}):
            found = pk.fetch_card_content("CAT.001.A1", "http://platform.example/mcp")
        assert found["text"] == "материал по теме"
        assert found["title"] == "Заголовок"
        assert found["source"] == "platform-mcp"
        assert found["platform_url"] == "http://platform.example/mcp"


# ---------------------------------------------------------------------------
# live round-trip — real HTTP against a loopback stub, not a mocked transport
# (same acceptance pattern as test_acceptance_backends.py)
# ---------------------------------------------------------------------------

class TestLiveRoundTrip:
    def test_fetch_card_content_against_live_stub(self, stub_mcp_server):
        found = pk.fetch_card_content("CAT.001.A1", f"http://127.0.0.1:{stub_mcp_server}/mcp")
        assert found is not None
        assert found["text"] == "stub-acceptance material: no real platform was called"
        assert found["title"] == "Acceptance stub card"
        assert found["source"] == "platform-mcp"


# ---------------------------------------------------------------------------
# adapter.load_card_content wiring
# ---------------------------------------------------------------------------

class TestLoadCardContentWiring:
    def test_local_hit_wins_no_platform_call_attempted(self, tmp_path):
        (tmp_path / "CAT.001.A1.json").write_text(
            json.dumps({"text": "local card"}), encoding="utf-8"
        )
        with patch("adapter.fetch_platform_card") as mock_fetch:
            result = load_card_content("CAT.001.A1", str(tmp_path), platform_knowledge_on=True)
        assert result == {"text": "local card"}
        mock_fetch.assert_not_called()

    def test_local_miss_flag_off_returns_none_no_network(self, tmp_path):
        with patch("adapter.fetch_platform_card") as mock_fetch:
            result = load_card_content("CAT.001.A1", str(tmp_path), platform_knowledge_on=False)
        assert result is None
        mock_fetch.assert_not_called()

    def test_local_miss_flag_on_uses_platform_fallback(self, tmp_path):
        with patch(
            "adapter.fetch_platform_card",
            return_value={"text": "live", "source": "platform-mcp"},
        ) as mock_fetch:
            result = load_card_content(
                "CAT.001.A1", str(tmp_path), platform_knowledge_on=True, platform_url="http://x"
            )
        assert result == {"text": "live", "source": "platform-mcp"}
        mock_fetch.assert_called_once_with("CAT.001.A1", "http://x")

    def test_no_element_id_returns_none_no_network(self, tmp_path):
        with patch("adapter.fetch_platform_card") as mock_fetch:
            result = load_card_content(None, str(tmp_path), platform_knowledge_on=True)
        assert result is None
        mock_fetch.assert_not_called()

    def test_platform_unreachable_degrades_to_none(self, tmp_path):
        with patch("adapter.fetch_platform_card", return_value=None):
            result = load_card_content("CAT.001.A1", str(tmp_path), platform_knowledge_on=True)
        assert result is None
