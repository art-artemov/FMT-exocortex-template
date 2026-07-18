"""guide-kit LLM backend dispatch.

Three backends behind one dispatch function — not one unified contract,
because the Anthropic Messages API is not shape-compatible with the OpenAI
Chat Completions API (system prompt placement, response envelope differ).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PromptSpec:
    system: str
    user_json: dict[str, Any]


@dataclass
class GenerationContext:
    backend: str
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    timeout_s: float = 60.0


@dataclass
class GenerationResult:
    text: str
    backend_id: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def generate(prompt_spec: PromptSpec, context: GenerationContext) -> GenerationResult:
    """Dispatch to the configured backend. Never raises — failures come back as .error."""
    from . import anthropic as _anthropic
    from . import local as _local
    from . import openai_compatible as _openai_compatible

    dispatch = {
        "anthropic": _anthropic.generate,
        "openai_compatible": _openai_compatible.generate,
        "local": _local.generate,
    }
    fn = dispatch.get(context.backend)
    if fn is None:
        from datetime import datetime, timezone

        return GenerationResult(
            text="",
            backend_id=context.backend,
            model=context.model or "",
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=f"unknown backend {context.backend!r} (expected one of {sorted(dispatch)})",
        )
    return fn(prompt_spec, context)
