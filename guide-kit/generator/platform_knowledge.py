"""
platform_knowledge.py — live client for the platform's public curated-materials MCP layer.

Implements DP.SC.060 scenario 1 (connected user, daily assembly): when a
worldview/practice card is not found locally (demo catalog / cards_path), fetch
fresh material from the platform's public guides-mcp / knowledge-mcp instead of
carrying a stale static copy. No token — this is the public slope only
(DP.SC.060 explicitly excludes the private knowledge-mcp layer for now).

Honest degradation, not a hard-fail: the platform being unreachable means the
adapter proceeds without fresh material (decision_log records the gap), never
a crashed run — invariant I2 (honest degradation) of DP.SC.060.

CLI (manual/debug use only — the adapter calls fetch_card_content() directly):
    python3 platform_knowledge.py --query "тема" [--platform-url URL]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


_READ_TOOLS = ("knowledge_search", "semantic_search")
_DEFAULT_PLATFORM_URL = "https://mcp.aisystant.com/mcp"


def _rpc_call(platform_url: str, tool_name: str, arguments: dict) -> dict:
    """Single JSON-RPC 2.0 tools/call against the public MCP layer — no Authorization
    header (DP.SC.060: guides-mcp/knowledge-mcp public slope needs no token).

    Raises ValueError before touching the network if tool_name is not in the allowlist.
    Raises RuntimeError on any network / HTTP / server error.
    """
    if tool_name not in _READ_TOOLS:
        raise ValueError(
            f"tool {tool_name!r} not in allowlist {_READ_TOOLS!r} — refused before network"
        )

    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }).encode("utf-8")

    req = urllib.request.Request(
        platform_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"сетевая ошибка: {e.reason}") from e

    if not body:
        raise RuntimeError("платформа вернула пустой ответ")

    try:
        rpc_resp = json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"не-JSON ответ от платформы: {e}") from e

    if "error" in rpc_resp:
        raise RuntimeError(f"ошибка JSON-RPC: {rpc_resp['error']}")

    return rpc_resp.get("result") or {}


def _unwrap_content(result: dict) -> list | dict | None:
    """Unwrap MCP content wrapper {content: [{type: text, text: ...}]}; return None if empty."""
    if not result:
        return None
    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if not isinstance(first, dict):
            return None
        text = first.get("text", "")
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    if isinstance(content, dict):
        return content
    if isinstance(result, dict) and "content" not in result:
        return result or None
    return None


def fetch_card_content(
    element_id: str, platform_url: str = _DEFAULT_PLATFORM_URL
) -> dict | None:
    """Fetch fresh material for element_id from the platform's public knowledge layer.

    Honest degradation: platform unreachable, empty, or unparseable response → None
    (same contract as adapter.load_card_content's local-file miss). Never raises —
    a caller checks for None, same as the local-cards_path path.

    Returns a dict with at least {"text": ..., "source": "platform-mcp"} on success,
    or None if nothing usable was found.
    """
    try:
        result = _rpc_call(platform_url, "knowledge_search", {"query": element_id, "limit": 1})
    except (RuntimeError, ValueError) as e:
        print(f"NOTE: platform_knowledge недоступен для {element_id!r}: {e}", file=sys.stderr)
        return None

    data = _unwrap_content(result)
    results = data.get("results") if isinstance(data, dict) else data
    if not isinstance(results, list) or not results:
        return None

    top = results[0]
    if not isinstance(top, dict):
        return None

    text = top.get("content") or top.get("text") or top.get("summary")
    if not text:
        return None

    return {
        "text": text,
        "title": top.get("title", ""),
        "source": "platform-mcp",
        "platform_url": platform_url,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="guide-kit platform_knowledge — manual/debug query against the public MCP layer"
    )
    parser.add_argument("--query", required=True, help="element_id or free-text query")
    parser.add_argument("--platform-url", default=_DEFAULT_PLATFORM_URL)
    return parser


if __name__ == "__main__":
    args = _build_parser().parse_args()
    found = fetch_card_content(args.query, args.platform_url)
    if found is None:
        print("NOTE: ничего не найдено", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(found, ensure_ascii=False, indent=2))
