"""P.2(c) acceptance test: guide-kit works against open-protocol backends,
not just the vendor one (MVP acceptance, portability promise in
README.md "speak only open protocols").

Real HTTP round-trip against tests/acceptance/stub_llm_server.py on a
loopback ephemeral port — not a mock of the transport. conftest.py's
zero-upload socket guard allows loopback, so this stays inside that
invariant while still exercising the real urllib code path.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests", "acceptance"))
from stub_llm_server import start_stub_server  # noqa: E402 — path setup must precede this import

from llm_backends import GenerationContext, PromptSpec, generate


@pytest.fixture
def stub_server():
    server, port = start_stub_server()
    yield port
    server.shutdown()


class TestOpenProtocolBackends:
    @pytest.mark.parametrize("backend", ["openai_compatible", "local"])
    def test_backend_completes_against_live_stub(self, stub_server, backend):
        ctx = GenerationContext(backend=backend, base_url=f"http://127.0.0.1:{stub_server}/v1")
        result = generate(PromptSpec(system="test", user_json={"k": "v"}), ctx)
        assert result.ok
        assert result.text
        assert result.backend_id == backend

    @pytest.mark.parametrize("module_name", ["openai_compatible", "local"])
    def test_open_protocol_backends_do_not_import_vendor_sdk(self, module_name):
        """openai_compatible/local must stay usable with zero vendor SDK installed —
        that's what makes them 'open protocol'. Static source check, not a runtime
        import probe: sys.modules can already hold `anthropic` from an unrelated
        test in the same session, which would make a runtime check unreliable."""
        backend_dir = os.path.join(os.path.dirname(__file__), "llm_backends")
        with open(os.path.join(backend_dir, f"{module_name}.py"), encoding="utf-8") as fh:
            source = fh.read()
        # covers both "import anthropic" and "from anthropic import X" — the latter
        # is the form Anthropic's own SDK docs use, so it's the likelier regression
        assert not re.search(r"^\s*(import anthropic\b|from anthropic\b)", source, re.MULTILINE)
