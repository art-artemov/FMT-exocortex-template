"""OpenAI-compatible Chat Completions backend (guide-kit).

User supplies base_url + api_key — any server implementing the Chat
Completions shape qualifies (OpenAI itself, most third-party proxies).
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import GenerationContext, GenerationResult, PromptSpec

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def generate(prompt_spec: PromptSpec, context: GenerationContext) -> GenerationResult:
    model = context.model or DEFAULT_MODEL
    base_url = (context.base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt_spec.system},
            {"role": "user", "content": json.dumps(prompt_spec.user_json, ensure_ascii=False)},
        ],
        "temperature": 0.7,
    }
    headers = {"Content-Type": "application/json"}
    if context.api_key:
        headers["Authorization"] = f"Bearer {context.api_key}"

    timestamp = datetime.now(timezone.utc).isoformat()
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=context.timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        # ValueError covers json.JSONDecodeError/UnicodeDecodeError: user-supplied
        # base_url can point at anything (proxy error page, wrong port) — a non-JSON
        # or non-UTF-8 response must not crash past this boundary as an unhandled exc.
        logger.error("openai_compatible backend call to %s failed: %s", url, e)
        return GenerationResult(
            text="", backend_id="openai_compatible", model=model, timestamp=timestamp, error=str(e)
        )

    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        logger.error("openai_compatible backend: unexpected response shape: %s", e)
        return GenerationResult(
            text="",
            backend_id="openai_compatible",
            model=model,
            timestamp=timestamp,
            error=f"unexpected response shape: {e}",
        )

    return GenerationResult(
        text=text,
        backend_id="openai_compatible",
        model=model,
        usage=body.get("usage", {}),
        timestamp=timestamp,
    )
