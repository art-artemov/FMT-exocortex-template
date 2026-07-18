"""Anthropic Messages API backend (guide-kit).

Separate driver, not a variant of openai_compatible: the Messages API puts
`system` at the top level (not inside `messages`), uses `x-api-key` +
`anthropic-version` headers instead of a Bearer token, and wraps content in
a list of typed blocks rather than a flat string.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import GenerationContext, GenerationResult, PromptSpec

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_MODEL = "claude-sonnet-5"
ANTHROPIC_VERSION = "2023-06-01"


def generate(prompt_spec: PromptSpec, context: GenerationContext) -> GenerationResult:
    model = context.model or DEFAULT_MODEL
    base_url = (context.base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base_url}/v1/messages"
    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": prompt_spec.system,
        "messages": [
            {"role": "user", "content": json.dumps(prompt_spec.user_json, ensure_ascii=False)},
        ],
    }
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": ANTHROPIC_VERSION,
    }
    if context.api_key:
        headers["x-api-key"] = context.api_key

    timestamp = datetime.now(timezone.utc).isoformat()
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=context.timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        # ValueError covers json.JSONDecodeError/UnicodeDecodeError — see
        # openai_compatible.py for why a non-JSON response must not raise here.
        logger.error("anthropic backend call to %s failed: %s", url, e)
        return GenerationResult(
            text="", backend_id="anthropic", model=model, timestamp=timestamp, error=str(e)
        )

    try:
        text = "".join(block["text"] for block in body["content"] if block.get("type") == "text")
    except (KeyError, TypeError, AttributeError) as e:
        logger.error("anthropic backend: unexpected response shape: %s", e)
        return GenerationResult(
            text="",
            backend_id="anthropic",
            model=model,
            timestamp=timestamp,
            error=f"unexpected response shape: {e}",
        )

    return GenerationResult(
        text=text,
        backend_id="anthropic",
        model=model,
        usage=body.get("usage", {}),
        timestamp=timestamp,
    )
