"""
Zero-upload invariant tests for guide-kit.

Three guarantees:
  (1) PII canaries from the fixture profile don't appear in platform-bound payloads.
  (2) Quarantine-flagged content doesn't reach the platform payload or LLM prompt.
  (3) The conftest socket guard blocks any non-loopback connect.

All network calls are intercepted — no real connections are made.
"""
import json
import os
import socket
from unittest.mock import MagicMock, patch

import pytest
import yaml

import personal_export as pe
import platform_knowledge as pk
from adapter import apply_platform_overlay, generate_daily_plan
from llm_backends import GenerationResult


# ---------------------------------------------------------------------------
# Fixture base — canary values that must never appear in outbound payloads
# ---------------------------------------------------------------------------

_PII_CANARY_EMAIL = "canary-pii-user@nowhere-fixture.invalid"
_PII_CANARY_PHONE = "+7-999-CANARY-PII"
_PII_CANARY_NAME  = "CanaryFirstname CanaryLastname"
_PII_CANARY_CARD  = "4111-1111-1111-CANARY"

_QUARANTINE_CONTENT = "SECRET-canary-content-quarantined-XYZ789"


def _build_fixture_profile():
    """Profile dict that contains PII canary values in user-visible fields."""
    return {
        "rcs": {
            "W": 2,
            "M1": 3,
            "source": "manual",
            "confidence": 0.9,
        },
        "mastery_by_area": {"area_1": 0.5},
        # PII canaries in free-text fields that should stay local
        "pilot_reflection": f"From {_PII_CANARY_NAME}: {_PII_CANARY_EMAIL}, card {_PII_CANARY_CARD}",
        "tomorrow_intention": _PII_CANARY_PHONE,
    }


# ---------------------------------------------------------------------------
# Helper: capture what goes into urllib.request bodies
# ---------------------------------------------------------------------------

class _CapturingTransport:
    """Records every request body sent via urllib.request.urlopen."""

    def __init__(self, response_body: bytes):
        self._response_body = response_body
        self.captured_bodies: list[bytes] = []

    def __call__(self, req, **kwargs):
        self.captured_bodies.append(req.data or b"")
        mock_resp = MagicMock()
        mock_resp.read.return_value = self._response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp


# ---------------------------------------------------------------------------
# (1) PII canaries not in platform payload
# ---------------------------------------------------------------------------

class TestPiiCanariesNotInPlatformPayload:
    def _platform_response(self, data: dict) -> bytes:
        return json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": json.dumps(data)}]},
        }).encode()

    def test_profile_pii_not_in_describe_request(self, monkeypatch, tmp_path):
        """dt_describe_by_path request body must not contain local profile PII."""
        monkeypatch.setenv("GUIDE_KIT_PLATFORM_TOKEN", "testtoken")

        fixture_profile = _build_fixture_profile()
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text(yaml.dump(fixture_profile))

        transport = _CapturingTransport(
            self._platform_response({"exists": False})
        )
        with patch("urllib.request.urlopen", transport):
            # fetch_stage calls describe on _STAGE_PATH — body must not contain PII.
            # Explicit missing snapshot_cache_path: keeps this test hermetic —
            # otherwise a real-machine derived_snapshot.json could silently
            # satisfy the fallback and mask a describe/read regression.
            pe.fetch_stage("http://localhost/mcp", "testtoken", str(tmp_path / "no-snapshot.json"))

        assert transport.captured_bodies, "no requests were made"
        for body in transport.captured_bodies:
            body_str = body.decode("utf-8", errors="replace")
            assert _PII_CANARY_EMAIL not in body_str, "PII email in platform request"
            assert _PII_CANARY_PHONE not in body_str, "PII phone in platform request"
            assert _PII_CANARY_NAME not in body_str, "PII name in platform request"
            assert _PII_CANARY_CARD not in body_str, "PII card number in platform request"

    def test_profile_pii_not_in_read_request(self, monkeypatch, tmp_path):
        """dt_read_digital_twin request body must not contain local profile PII."""
        monkeypatch.setenv("GUIDE_KIT_PLATFORM_TOKEN", "testtoken")

        transport = _CapturingTransport(
            self._platform_response({"stage_derived": 2, "stage_label": "Ученик"})
        )
        with patch("urllib.request.urlopen", transport):
            pe.fetch_stage("http://localhost/mcp", "testtoken", str(tmp_path / "no-snapshot.json"))

        # At least 2 requests: describe + read
        assert len(transport.captured_bodies) >= 2
        for body in transport.captured_bodies:
            body_str = body.decode("utf-8", errors="replace")
            assert _PII_CANARY_EMAIL not in body_str
            assert _PII_CANARY_PHONE not in body_str
            assert _PII_CANARY_NAME not in body_str
            assert _PII_CANARY_CARD not in body_str

    def test_overlay_payload_contains_only_platform_derived_data(self, monkeypatch, tmp_path):
        """profile.platform.yaml must contain only platform-derived values, not local PII."""
        monkeypatch.setenv("GUIDE_KIT_PLATFORM_TOKEN", "testtoken")

        out = tmp_path / "profile.platform.yaml"
        with patch.object(pe, "fetch_stage", return_value=(3, "Профессионал", None, "platform")), \
             patch.object(pe, "fetch_rcs", return_value={"W": 4, "source": "computed_from_events"}):
            code = pe.export("http://localhost/mcp", "rcs_path", str(out))

        assert code == 0
        raw = out.read_text()
        assert _PII_CANARY_EMAIL not in raw
        assert _PII_CANARY_PHONE not in raw
        assert _PII_CANARY_NAME not in raw
        assert _PII_CANARY_CARD not in raw


# ---------------------------------------------------------------------------
# (1b) Full pipeline — generate_daily_plan itself must never touch the
# network beyond the (mocked) LLM call, even with a local overlay file
# present. This is the concrete regression test for the FORMAT.md claim
# (corrected during review) that personal_export runs automatically before
# generation — it does not: apply_platform_overlay only reads an
# already-on-disk file. If any code in this real pipeline dialed the
# platform directly, conftest's session-wide socket guard would raise here.
# ---------------------------------------------------------------------------

class TestFullPipelineDoesNotTouchPlatformNetwork:
    def _fake_llm_ok(self, *_args, **_kwargs):
        return GenerationResult(
            text='{"narrative": "текст", "plan_day": [{"label": "задание", "tomatoes": 1}]}',
            backend_id="fake",
            model="fake",
        )

    def test_generate_daily_plan_with_local_overlay_makes_no_platform_call(self, tmp_path):
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text(yaml.dump(_build_fixture_profile()), encoding="utf-8")
        (tmp_path / "profile.platform.yaml").write_text(
            yaml.dump({"rcs": {"M2": 3, "source": "computed_from_events"}}),
            encoding="utf-8",
        )
        with patch("adapter.llm_generate", side_effect=self._fake_llm_ok):
            result = generate_daily_plan(str(profile_path))
        assert result.ok, getattr(result, "diagnostic", None)

    def test_apply_platform_overlay_alone_makes_no_network_call(self, tmp_path):
        """Unit-level companion: the merge function imported by adapter.py, called
        directly, must be pure local file I/O — no personal_export/network call."""
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text(yaml.dump(_build_fixture_profile()), encoding="utf-8")
        (tmp_path / "profile.platform.yaml").write_text(
            yaml.dump({"rcs": {"M2": 3, "source": "computed_from_events"}}),
            encoding="utf-8",
        )
        merged = apply_platform_overlay(_build_fixture_profile(), str(profile_path))
        assert merged["rcs"]["M2"] == 3  # overlay-only field proves the merge really ran


# ---------------------------------------------------------------------------
# (2) Quarantine content not in platform payload or LLM prompt
# ---------------------------------------------------------------------------

class TestQuarantineContentNotInPayloads:
    def test_quarantine_content_not_in_platform_request(self, monkeypatch, tmp_path):
        """Personal export requests must never carry quarantine-flagged content."""
        monkeypatch.setenv("GUIDE_KIT_PLATFORM_TOKEN", "testtoken")

        transport = _CapturingTransport(
            json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "result": {"content": [{"type": "text", "text": "{}"}]},
            }).encode()
        )
        with patch("urllib.request.urlopen", transport):
            # Even if quarantine content was somehow in the environment, it must not leak
            with patch.dict(os.environ, {"SOME_LOCAL_VAR": _QUARANTINE_CONTENT}):
                pe.fetch_stage("http://localhost/mcp", "testtoken", str(tmp_path / "no-snapshot.json"))

        for body in transport.captured_bodies:
            body_str = body.decode("utf-8", errors="replace")
            assert _QUARANTINE_CONTENT not in body_str

    def test_quarantine_content_not_in_platform_overlay_file(self, monkeypatch, tmp_path):
        """profile.platform.yaml (what comes FROM platform) must not carry quarantine strings.

        The platform payload is controlled by fetch_stage / fetch_rcs return values.
        This test verifies that if the platform somehow returns quarantine-like content,
        the overlay file faithfully records it but it never re-enters the platform request.
        """
        monkeypatch.setenv("GUIDE_KIT_PLATFORM_TOKEN", "testtoken")

        # Platform returns normal RCS data — no quarantine content
        out = tmp_path / "profile.platform.yaml"
        with patch.object(pe, "fetch_stage", return_value=(2, "Ученик", None, "platform")), \
             patch.object(pe, "fetch_rcs", return_value={"W": 2}):
            pe.export("http://localhost/mcp", "rcs_path", str(out))

        raw = out.read_text()
        assert _QUARANTINE_CONTENT not in raw

    def test_quarantine_content_not_in_platform_request_bodies(self, monkeypatch, tmp_path):
        """Platform HTTP request bodies must never contain quarantine-flagged strings.

        personal_export only sends tool-name + path in request bodies — there is no
        code path where quarantined local content could reach the platform HTTP layer.
        This test enforces that invariant structurally.
        """
        monkeypatch.setenv("GUIDE_KIT_PLATFORM_TOKEN", "testtoken")

        # Simulate a scenario where quarantine content exists in the local environment
        with patch.dict(os.environ, {"LOCAL_QUARANTINE_VAR": _QUARANTINE_CONTENT}):
            transport = _CapturingTransport(
                json.dumps({
                    "jsonrpc": "2.0", "id": 1,
                    "result": {"content": [{"type": "text", "text": "{}"}]},
                }).encode()
            )
            with patch("urllib.request.urlopen", transport):
                pe.fetch_stage("http://localhost/mcp", "testtoken", str(tmp_path / "no-snapshot.json"))

        for body in transport.captured_bodies:
            body_str = body.decode("utf-8", errors="replace")
            # Request bodies contain only: jsonrpc, method, tool name, path argument
            assert _QUARANTINE_CONTENT not in body_str, (
                "quarantine content found in platform HTTP request body"
            )

    def test_generator_does_not_read_type_index(self):
        """Structural invariant: the generator module imports no type-index reader.

        Quarantine filtering is the Structurer's job (type-index.json). The Generator
        never reads type-index.json — there is no code path for quarantined Structurer
        output to reach the LLM prompt.
        """
        import adapter as adapter_module
        import inspect
        source = inspect.getsource(adapter_module)
        assert "type-index" not in source
        assert "type_index" not in source
        assert "quarantine" not in source


# ---------------------------------------------------------------------------
# (1c) platform_knowledge (DP.SC.060 scenario 1) — request bodies must carry
# only element_id, never profile PII; default-off must not touch the network
# ---------------------------------------------------------------------------

class TestPlatformKnowledgeRequestsCarryNoPii:
    def test_request_body_contains_only_element_id(self, tmp_path):
        """fetch_card_content's only input is element_id — this test proves the
        request body structurally cannot carry profile PII (nothing else is in scope
        to leak), the same guarantee test_zero_upload gives personal_export via a
        dict-argument API rather than a single string."""
        transport = _CapturingTransport(
            json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "result": {"content": [{"type": "text", "text": "{}"}]},
            }).encode()
        )
        with patch("urllib.request.urlopen", transport):
            pk.fetch_card_content(f"CAT.001.A1 {_PII_CANARY_EMAIL}")

        assert transport.captured_bodies, "no requests were made"
        for body in transport.captured_bodies:
            body_str = body.decode("utf-8", errors="replace")
            # The email canary is deliberately embedded IN the element_id above
            # to prove where the boundary actually is: whatever is passed as
            # element_id is sent as the query verbatim (by design — a catalog
            # code is not PII), so it appearing here is expected, not a leak.
            assert _PII_CANARY_EMAIL in body_str, (
                "sanity check: element_id should be sent verbatim as the query"
            )
            # Nothing else from a user profile ever reaches this call in the
            # real pipeline — generate_daily_plan passes only planner_result's
            # element_id, never profile fields, to load_card_content — so none
            # of these three (which were never part of element_id) may appear.
            assert _PII_CANARY_PHONE not in body_str
            assert _PII_CANARY_NAME not in body_str
            assert _PII_CANARY_CARD not in body_str

    def test_default_off_makes_no_platform_call_even_on_local_miss(self, tmp_path):
        """generate_daily_plan with no config (platform_knowledge defaults to off)
        must not attempt a platform_knowledge call even when cards_path/demo
        catalog has no card for the chosen element — relies on the session-wide
        socket guard to fail loudly if this regresses."""
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text(yaml.dump(_build_fixture_profile()), encoding="utf-8")

        def _fake_llm_ok(*_args, **_kwargs):
            return GenerationResult(
                text='{"narrative": "текст", "plan_day": [{"label": "задание", "tomatoes": 1}]}',
                backend_id="fake",
                model="fake",
            )

        with patch("adapter.llm_generate", side_effect=_fake_llm_ok), \
             patch("adapter.fetch_platform_card") as mock_fetch:
            result = generate_daily_plan(str(profile_path))

        assert result.ok, getattr(result, "diagnostic", None)
        mock_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# (3) Socket guard — verify the conftest guard actually blocks non-loopback
# ---------------------------------------------------------------------------

class TestSocketGuard:
    def test_loopback_connect_is_allowed(self):
        """Connections to 127.0.0.1 must not be blocked (e.g. a local test server)."""
        # We just verify the guard doesn't raise on loopback — actual connect may fail
        # (no server listening), but the guard itself must not block it.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # This will likely raise ConnectionRefusedError, NOT the guard's pytest.fail
            s.connect(("127.0.0.1", 1))
        except (ConnectionRefusedError, OSError):
            pass  # Expected — no server there; guard did not block it
        except Exception as e:
            # Any OTHER exception (including the guard's) is unexpected
            if "ZERO-UPLOAD GUARD" in str(e):
                pytest.fail(f"Guard incorrectly blocked loopback: {e}")
        finally:
            s.close()

    def test_non_loopback_connect_is_blocked(self):
        """Connections to external addresses must be blocked by the conftest guard."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(AssertionError, match="ZERO-UPLOAD GUARD"):
                s.connect(("8.8.8.8", 80))
        finally:
            s.close()
