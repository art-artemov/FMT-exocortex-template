"""Minimal OpenAI-compatible Chat Completions stub (guide-kit acceptance).

stdlib-only, no real network egress, no API key. Binds an ephemeral port
(never a hardcoded one — a fixed port on the pilot's machine may already be
taken by a real local model server, which would silently test that server
instead of this stub). Used by both the P.1 clean-machine cycle and the
P.2(c) open-protocols backend test.

CLI mode prints the bound port to stdout as the first line, then serves
until killed — a caller shell script captures that line to build
llm_base_url. Importable mode (start_stub_server) is for pytest fixtures.
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# adapter.py parses the message content as JSON with narrative + plan_day
# (see generate_daily_plan's json.loads(llm_result.text)) — a plain string
# reply fails that parse before the guide ever renders, so the stub must
# speak the same shape a real backend's completion would.
STUB_REPLY_TEXT = json.dumps({
    "narrative": "stub-acceptance-reply: guide-kit acceptance harness, no real model was called",
    "plan_day": [{"label": "acceptance-stub-task", "tomatoes": 1, "rationale": "stub reply, not a real recommendation"}],
})


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A002 — silence default stderr access log
        pass

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)  # request body isn't inspected — stub always answers the same way
        body = json.dumps({
            "choices": [{"message": {"content": STUB_REPLY_TEXT}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_stub_server() -> tuple[HTTPServer, int]:
    """Binds an ephemeral port, starts serving in a daemon thread. Caller stops via server.shutdown()."""
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


if __name__ == "__main__":
    server, port = start_stub_server()
    print(port, flush=True)
    try:
        threading.Event().wait()  # serve_forever runs on the daemon thread; block main thread until killed
    except KeyboardInterrupt:
        sys.exit(0)
