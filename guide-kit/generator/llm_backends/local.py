"""Local LLM backend (guide-kit).

Not a separate protocol: an abstract interface over "some OpenAI-compatible
server on localhost" — MLX server (see the /local-llm skill), llama.cpp
server, Ollama's OpenAI-compat mode all qualify. guide-kit does not require
a local model to be running; if none is configured, this backend fails
honestly (openai_compatible's own connection-error handling) instead of
guide-kit shipping a bespoke local-server dependency.
"""
from __future__ import annotations

from . import GenerationContext, GenerationResult, PromptSpec
from . import openai_compatible

DEFAULT_LOCAL_BASE_URL = "http://localhost:8080/v1"
DEFAULT_LOCAL_MODEL = "local-model"


def generate(prompt_spec: PromptSpec, context: GenerationContext) -> GenerationResult:
    local_context = GenerationContext(
        backend="local",
        base_url=context.base_url or DEFAULT_LOCAL_BASE_URL,
        api_key=context.api_key,  # most local servers ignore the key, but we don't forbid it
        model=context.model or DEFAULT_LOCAL_MODEL,
        timeout_s=context.timeout_s,
    )
    result = openai_compatible.generate(prompt_spec, local_context)
    result.backend_id = "local"
    return result
