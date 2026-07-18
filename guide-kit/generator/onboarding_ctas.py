"""
onboarding_ctas.py — the two optional invitation blocks.

Renders a static markdown appendix to the generated guide: an invitation to
connect to the hosted platform, and an invitation to adopt the full IWE
template. Both are pure text — this module holds no onboarding state and
makes no branching decision on the user's behalf. The next onboarding step
is always something the platform itself answers; this module never guesses
it (lesson learned the hard way: a locally duplicated onboarding state machine
drifts from the platform's and rots).

An explicitly blanked-out platform_connect_url (config sets it to "") degrades
to a link-less pointer instead of a sentinel placeholder — a literal
placeholder string ending up in someone's guide would be a defect, not a
valid degraded state.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The hosted platform's public MCP connector — a real, stable artifact
# (documented in DS-MCP/gateway-mcp/docs/IWE-USER-GUIDE-RU.md), not something
# guide-kit invents. A fork pointing at a different platform overrides this
# via config; an explicit empty string in config suppresses the link entirely.
DEFAULT_PLATFORM_CONNECT_URL = "https://mcp.aisystant.com/mcp"

_PLATFORM_BLOCK_HEADER = "### Дальше — платформа (опционально)"
_PLATFORM_BLOCK_BODY = (
    "Подключи своего ИИ-агента к MCP-серверу платформы и попроси показать "
    "следующий шаг — платформа сама поведёт тебя дальше, в твоём темпе."
)

_IWE_BLOCK = (
    "### Дальше — полный набор инструментов IWE (опционально)\n"
    "Если твой ИИ-агент — Claude Code, можно поставить поверх этого комплекта "
    "полный шаблон IWE командой `setup.sh` — он даёт доступ к остальным "
    "инструментам платформы поверх того, что уже собрано локально."
)


def render_onboarding_ctas(config: dict) -> str:
    """Returns the appendix markdown, or "" if disabled or nothing to show.

    config keys (both optional):
      onboarding_ctas (bool, default True) — master on/off switch.
      platform_connect_url (str, default DEFAULT_PLATFORM_CONNECT_URL) —
        connect link. Absent or null (the repo's usual "not configured"
        sentinel, same as curriculum_path/cards_path in adapter.py) → defaults
        to the hosted platform's own connector. Explicitly set to "" →
        the platform block still renders, just without a link line, and a
        warning is logged so the gap is visible at build time rather than
        silently missing (e.g. a fork that hasn't set its own URL yet).
    """
    if not config.get("onboarding_ctas", True):
        return ""

    platform_url = config.get("platform_connect_url")
    if platform_url is None:
        platform_url = DEFAULT_PLATFORM_CONNECT_URL
    platform_block = f"{_PLATFORM_BLOCK_HEADER}\n{_PLATFORM_BLOCK_BODY}"
    if platform_url:
        platform_block += f"\n\nСсылка: {platform_url}"
    else:
        logger.warning(
            "platform_connect_url is blank — rendering the platform invitation "
            "without a link (this is a valid degraded state, not an error)"
        )

    return "\n\n".join(["---", "## Дальше — опционально", platform_block, _IWE_BLOCK])
