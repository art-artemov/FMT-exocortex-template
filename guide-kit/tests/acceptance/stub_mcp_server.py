"""Minimal JSON-RPC 2.0 MCP stub (guide-kit acceptance) for platform_knowledge.py.

stdlib-only, no real network egress. Binds an ephemeral port (never a fixed
one — see stub_llm_server.py's rationale). Speaks the same envelope shape
platform_knowledge._rpc_call expects: {jsonrpc, id, result: {content: [...]}}.
Used by the P.2(c)-style live round-trip test for the public knowledge-mcp
fallback (DP.SC.060 scenario 1) — a real HTTP request/response cycle, not a
mocked transport, so a serialization/parsing regression is actually caught.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

STUB_CARD = {
    "results": [
        {
            "content": "stub-acceptance material: no real platform was called",
            "title": "Acceptance stub card",
        }
    ]
}


class _StubMcpHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A002 — silence default stderr access log
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        request = json.loads(raw)  # exercised only to prove the request is valid JSON-RPC

        if request.get("method") != "tools/call" or "Authorization" in self.headers:
            # Public slope must never send a token — a stray Authorization header
            # here would mean a regression toward the personal_export transport.
            self.send_response(400)
            self.end_headers()
            return

        body = json.dumps({
            "jsonrpc": "2.0",
            "id": request.get("id", 1),
            "result": {"content": [{"type": "text", "text": json.dumps(STUB_CARD)}]},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_stub_mcp_server() -> tuple[HTTPServer, int]:
    """Binds an ephemeral port, starts serving in a daemon thread. Caller stops via server.shutdown()."""
    server = HTTPServer(("127.0.0.1", 0), _StubMcpHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port
