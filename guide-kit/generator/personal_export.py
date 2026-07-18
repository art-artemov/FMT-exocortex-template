"""
personal_export.py — platform pull client for guide-kit.

Fetches derived RCS profile, stage (mastery level within a role, 1-5), and
qualification degree (DP.D.050 ladder, council-assigned — see DP.D.252 for
why these are two separate axes) from the IWE platform via JSON-RPC 2.0 MCP
transport. Writes profile.platform.yaml (compact keys + provenance). Never
sends PII upstream — read-only calls only.

CLI:
    python3 personal_export.py
        [--platform-url URL]    default: https://mcp.aisystant.com/mcp
        [--rcs-path PATH]       no default; rcs fetch skipped if absent
        [--output FILE]         default: profile.platform.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

import yaml


_READ_TOOLS = ("dt_read_digital_twin", "dt_describe_by_path")
_DEFAULT_PLATFORM_URL = "https://mcp.aisystant.com/mcp"
_STAGE_PATH = "3_derived/3_4_qualification"
_DEGREE_PATH = "3_derived/3_8_degree"

_RCS_COMPACT_KEYS = frozenset({
    "W", "M1", "M2", "M3", "M4", "IT", "A",
    "bottleneck", "stage_derived", "source", "confidence",
})


def _rpc_call(platform_url: str, token: str, tool_name: str, arguments: dict) -> dict:
    """Single JSON-RPC 2.0 tools/call. Returns the result dict.

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
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError(
                f"HTTP {e.code} — подписочный источник недоступен"
            ) from e
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


def _unwrap_content(result: dict) -> dict | None:
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
    # Already unwrapped — no "content" wrapper
    if isinstance(result, dict) and "content" not in result:
        return result or None
    return None


def _describe_path(platform_url: str, token: str, path: str) -> bool:
    """Return True if path exists on platform (describe succeeds and returns data)."""
    try:
        result = _rpc_call(platform_url, token, "dt_describe_by_path", {"path": path})
        return bool(result)
    except RuntimeError:
        return False


def _read_path(platform_url: str, token: str, path: str) -> dict | None:
    """Read data at path. Returns None on any error or empty response."""
    try:
        result = _rpc_call(platform_url, token, "dt_read_digital_twin", {"path": path})
        return _unwrap_content(result)
    except RuntimeError:
        return None


def fetch_stage(
    platform_url: str, token: str
) -> tuple[int | None, str | None, str | None]:
    """Fetch stage (mastery level within a role) from 3_derived/3_4_qualification —
    the platform's own field path uses "qualification" in its name, but this is the
    per-role stage (DP.METHOD.020 §2), not the qualification degree (§3, DP.D.252).

    Returns (stage_derived, stage_label, raw_on_parse_failure).
    Success: (int, str, None). Parse failure: (None, None, raw). Path absent: (None, None, None).
    """
    if not _describe_path(platform_url, token, _STAGE_PATH):
        return None, None, None

    data = _read_path(platform_url, token, _STAGE_PATH)
    if data is None:
        return None, None, None

    raw = json.dumps(data, ensure_ascii=False)
    try:
        raw_val = data.get("stage_derived") or data.get("stage")
        stage_derived = int(raw_val or 0)
        if not 1 <= stage_derived <= 5:
            raise ValueError(f"stage_derived={stage_derived} вне диапазона 1-5")
        stage_label = str(data.get("stage_label") or "")
        return stage_derived, stage_label, None
    except (ValueError, TypeError) as e:
        print(
            f"WARNING: не удалось разобрать ступень из {_STAGE_PATH!r}: {e}",
            file=sys.stderr,
        )
        return None, None, raw[:500]


def fetch_degree(platform_url: str, token: str) -> tuple[str | None, str | None]:
    """Fetch qualification degree (DP.D.050, DP.D.252 — a separate axis from stage:
    only the methodological council assigns one, never computed or self-assigned)
    from 3_derived/3_8_degree. Working hypothesis for the path, by analogy with
    3_derived/3_4_qualification for stage — not verified against a live digital
    twin; an absent/wrong path degrades honestly (None, None), same as fetch_stage.

    Returns (degree, certified_at). certified_at is the most recent confirmation
    date from the history list, if present.
    """
    if not _describe_path(platform_url, token, _DEGREE_PATH):
        return None, None

    data = _read_path(platform_url, token, _DEGREE_PATH)
    if data is None:
        return None, None

    degree = data.get("current")
    if not degree:
        return None, None

    certified_at = None
    history = data.get("history")
    if isinstance(history, list) and history:
        last = history[-1]
        if isinstance(last, dict):
            certified_at = last.get("last_confirmed_at") or last.get("first_assigned_at")

    return str(degree), certified_at


_RCS_INT_SLOTS = frozenset({"W", "M1", "M2", "M3", "M4", "IT", "A", "stage_derived"})


def _validate_rcs_field(key: str, value):
    """Validate one RCS field value. Returns the validated value, or None to drop it
    (with a stderr warning) — a malformed field degrades gracefully instead of
    crashing RCSProfile.from_dict() downstream."""
    try:
        if key in _RCS_INT_SLOTS:
            v = int(value)
            if not 1 <= v <= 5:
                raise ValueError(f"{v} вне диапазона 1-5")
            return v
        if key == "confidence":
            v = float(value)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{v} вне диапазона 0-1")
            return v
        return value  # bottleneck, source — free-form strings, no fixed range to check
    except (TypeError, ValueError) as e:
        print(f"WARNING: rcs.{key}={value!r} отброшено — {e}", file=sys.stderr)
        return None


def fetch_rcs(platform_url: str, token: str, rcs_path: str) -> dict | None:
    """Fetch RCS data at rcs_path. Returns only compact keys actually returned by the
    platform, each individually validated — a malformed field is dropped, not fatal."""
    if not _describe_path(platform_url, token, rcs_path):
        print(f"NOTE: rcs_path {rcs_path!r} не найден на платформе — пропускаем", file=sys.stderr)
        return None

    data = _read_path(platform_url, token, rcs_path)
    if not data:
        return None

    result = {}
    for k, v in data.items():
        if k not in _RCS_COMPACT_KEYS:
            continue
        validated = _validate_rcs_field(k, v)
        if validated is not None:
            result[k] = validated
    return result or None


def export(platform_url: str, rcs_path: str | None, output_path: str) -> int:
    """Main export logic. Returns exit code (0=ok, 1=error).

    On any error: prints to stderr, does NOT write the output file.
    """
    # .lower(), not os.path.normcase(): normcase is a no-op on POSIX, but macOS's
    # default filesystem is case-insensitive regardless — "PROFILE.YAML" must
    # still be refused.
    if os.path.basename(output_path).lower() == "profile.yaml":
        print(
            "ERROR: --output не может называться profile.yaml — это перезаписало бы "
            "собственный файл пользователя чужим (платформенным) содержимым; "
            "выгрузка пишется отдельным файлом (по умолчанию profile.platform.yaml)",
            file=sys.stderr,
        )
        return 1

    token = os.environ.get("GUIDE_KIT_PLATFORM_TOKEN", "").strip()
    if not token:
        print(
            "ERROR: GUIDE_KIT_PLATFORM_TOKEN не задан — авторизация с платформой невозможна",
            file=sys.stderr,
        )
        return 1

    fetched_at = datetime.now(timezone.utc).isoformat()

    stage_derived, stage_label, stage_raw = fetch_stage(platform_url, token)
    degree, degree_certified_at = fetch_degree(platform_url, token)

    rcs_data: dict | None = None
    if rcs_path:
        rcs_data = fetch_rcs(platform_url, token, rcs_path)
    else:
        print("NOTE: --rcs-path не задан — выгрузка RCS пропускается", file=sys.stderr)

    if stage_derived is None and rcs_data is None and degree is None:
        print(
            "WARNING: платформа не вернула полезных данных — profile.platform.yaml не записан",
            file=sys.stderr,
        )
        return 1

    overlay: dict = {
        "origin": "platform",
        "platform_url": platform_url,
        "fetched_at": fetched_at,
        "is_derived": True,
    }

    # Build rcs block from fetched data; stage_derived goes into rcs, stage_label into provenance
    rcs_block: dict = dict(rcs_data) if rcs_data else {}
    if stage_derived is not None:
        rcs_block["stage_derived"] = stage_derived
    if rcs_block:
        rcs_block.setdefault("source", "computed_from_events")
        overlay["rcs"] = rcs_block

    # Provenance: stage_label (parse ok) or stage_label_raw (parse failed)
    if stage_derived is not None and stage_label is not None:
        overlay["provenance"] = {"stage_label": stage_label}
    elif stage_raw is not None:
        overlay["provenance"] = {"stage_label_raw": stage_raw}

    # Degree — a separate axis from stage (DP.D.252): council-assigned, never computed.
    if degree is not None:
        degree_block = {"degree": degree, "source": "platform"}
        if degree_certified_at:
            degree_block["certified_at"] = degree_certified_at
        overlay["qualification_degree"] = degree_block

    with open(output_path, "w", encoding="utf-8") as fh:
        yaml.dump(overlay, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)

    print(f"OK: profile.platform.yaml записан: {output_path}", file=sys.stderr)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Real CLI parser — also used directly by tests, so a swallowed-flag
    regression (the class of bug that caused a past production incident)
    is caught against the actual shipped parser, not a duplicated stand-in."""
    parser = argparse.ArgumentParser(
        description="guide-kit personal export — fetches derived profile from the IWE platform"
    )
    parser.add_argument(
        "--platform-url",
        default=_DEFAULT_PLATFORM_URL,
        help="Platform MCP endpoint URL",
    )
    parser.add_argument(
        "--rcs-path",
        default=None,
        help="Path in the digital twin for RCS data (no default — skipped if absent)",
    )
    parser.add_argument(
        "--output",
        default="profile.platform.yaml",
        help="Output file path (default: profile.platform.yaml)",
    )
    return parser


if __name__ == "__main__":
    args = _build_parser().parse_args()
    sys.exit(export(args.platform_url, args.rcs_path, args.output))
