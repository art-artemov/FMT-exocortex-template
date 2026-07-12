# see DP.SC.053 §2.bis L-B mode invariant, WP-425 Level 2a
"""
Periodic updater for the local derived_snapshot.json (WP-425 Level 2a).

Fetches cp-profile from Aisystant Cloud MCP via headless claude subprocess,
parses 3_4_qualification schema, writes to local cache.

Design: runs in launchd (Sunday 08:00) and optionally from Day Open (--if-stale-days).
Zero network calls during guide assembly; this script is the separated update channel.

Usage:
  python3 scripts/update-derived-snapshot.py
  python3 scripts/update-derived-snapshot.py --if-stale-days 10
  python3 scripts/update-derived-snapshot.py --dry-run
"""
import argparse
import datetime
import json
import logging
import pathlib
import subprocess
import sys

IWE_ROOT = pathlib.Path.home() / "IWE"
GOVERNANCE = IWE_ROOT / "${IWE_GOVERNANCE_REPO:-DS-strategy}"
SNAPSHOT_PATH = GOVERNANCE / "inbox/WP-425/cache/derived_snapshot.json"

# Maps stage_id strings from 3_4_qualification to integer stage levels.
# Source: render-pilot-guides.py _STAGE_ID_TO_INT (OwnerIntegrity: single mapping table).
_STAGE_ID_TO_INT = {
    "STG.Student.Random": 1,
    "STG.Student.Practicing": 2,
    "STG.Student.Systematic": 3,
    "STG.Student.Disciplined": 4,
    "STG.Student.Proactive": 5,
}

_STAGE_INT_TO_LABEL = {
    1: "Случайный", 2: "Практикующий", 3: "Систематический",
    4: "Дисциплинированный", 5: "Проактивный",
}

# RCS slots tracked in rcs_indices (M3/IT/A are rarely bottlenecks but included for completeness).
_RCS_SLOTS = ["W", "M1", "M2", "M3", "M4", "IT", "A"]


def _is_stale(stale_days: int) -> bool:
    """Return True if snapshot is missing or older than stale_days."""
    if not SNAPSHOT_PATH.exists():
        return True
    try:
        data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        snap_date = datetime.date.fromisoformat(data.get("snapshot_date", "2000-01-01"))
        age = (datetime.date.today() - snap_date).days
        return age >= stale_days
    except (json.JSONDecodeError, ValueError):
        return True


def _fetch_derived_via_headless_claude() -> dict:
    """
    Call headless claude to read 3_derived path from Aisystant MCP.

    Returns the parsed qualification dict, or raises RuntimeError on failure.
    """
    prompt = (
        "Use the dt_read_digital_twin MCP tool with path='3_derived'. "
        "Return ONLY a valid JSON object with the full response content — "
        "no explanation, no markdown fences, just raw JSON."
    )
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--allowedTools", "dt_read_digital_twin",
             "--output-format", "text"],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("claude CLI not found — ensure it is in PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("claude subprocess timed out after 120s") from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"claude exited {result.returncode}: {result.stderr[:300]}"
        )

    raw = result.stdout.strip()
    if not raw:
        raise RuntimeError("claude returned empty output")

    # Strip markdown code fences if claude adds them despite the prompt.
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse JSON from claude output: {exc}\nOutput: {raw[:200]}") from exc


def _parse_qualification(response: dict) -> dict:
    """
    Extract stage, bottleneck, rcs_indices from dt_read_digital_twin response.

    Expected shape (from digital_twins.data->'3_derived'->'3_4_qualification'):
      {"stage_id": "STG.Student.Proactive", "rcs_indices": {"W": N, "M1": N, ...}}
    The MCP response may wrap this under a content key.
    """
    # Unwrap common MCP response envelope shapes.
    data = response
    for key in ("content", "data", "3_derived", "result"):
        if isinstance(data, dict) and key in data and isinstance(data[key], dict):
            data = data[key]

    # Locate 3_4_qualification — may be nested or top-level.
    qual = data.get("3_4_qualification") or data.get("3_derived", {}).get("3_4_qualification") or data
    if not isinstance(qual, dict):
        raise RuntimeError(f"Cannot locate 3_4_qualification in response: {str(response)[:300]}")

    stage_id = qual.get("stage_id", "")
    stage = _STAGE_ID_TO_INT.get(stage_id)
    if not stage:
        raw_stage = qual.get("stage")
        stage = int(raw_stage) if raw_stage and str(raw_stage).isdigit() and int(raw_stage) >= 1 else None
    if not stage:
        raise RuntimeError(f"Unknown stage_id '{stage_id}' and no fallback stage in response")

    rcs = qual.get("rcs_indices", {})
    slot_vals = {s: rcs.get(s, 0) for s in _RCS_SLOTS if rcs.get(s) is not None}
    if not slot_vals:
        raise RuntimeError("rcs_indices missing or empty in qualification data")

    # Bottleneck = slot with minimum value; M1 preferred on ties.
    bottleneck = min(slot_vals, key=lambda k: (slot_vals[k], k != "M1"))

    return {
        "stage_raw": stage,
        "stage_label": _STAGE_INT_TO_LABEL.get(stage, f"Ступень {stage}"),
        "bottleneck_slot": bottleneck,
        "rcs": {s: slot_vals[s] for s in ["W", "M1", "M2", "M4"] if s in slot_vals},
    }


def _build_snapshot(parsed: dict, existing: dict) -> dict:
    """Merge parsed qualification into existing snapshot, updating fields."""
    now = datetime.date.today().isoformat()
    snapshot = dict(existing)
    snapshot.update({
        "snapshot_date": now,
        "stage_raw": parsed["stage_raw"],
        "stage_label": parsed["stage_label"],
        "bottleneck_slot": parsed["bottleneck_slot"],
        "rcs": parsed["rcs"],
        "valid_for_stage": parsed["stage_raw"],
        "source": "mcp-fetched",
        "refresh_channel": "periodic-bundle",
    })
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="WP-425 Level 2a: periodic derived_snapshot updater"
    )
    parser.add_argument(
        "--if-stale-days", type=int, default=0, metavar="N",
        help="Skip update if snapshot is fresher than N days (0 = always update)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and parse data but do not write to disk"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(levelname)s %(message)s")

    if args.if_stale_days > 0 and not _is_stale(args.if_stale_days):
        logging.info("Snapshot is fresh (< %d days old) — skipping update", args.if_stale_days)
        return 0

    logging.info("Fetching 3_derived via headless claude...")
    try:
        response = _fetch_derived_via_headless_claude()
    except RuntimeError as exc:
        logging.error("Fetch failed: %s", exc)
        return 1

    logging.info("Parsing 3_4_qualification...")
    try:
        parsed = _parse_qualification(response)
    except RuntimeError as exc:
        logging.error("Parse failed: %s", exc)
        return 1

    existing = {}
    if SNAPSHOT_PATH.exists():
        try:
            existing = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logging.warning("Existing snapshot is corrupt — overwriting")

    snapshot = _build_snapshot(parsed, existing)
    logging.info(
        "stage=%s bottleneck=%s (was: stage=%s bottleneck=%s)",
        snapshot["stage_raw"], snapshot["bottleneck_slot"],
        existing.get("stage_raw", "?"), existing.get("bottleneck_slot", "?"),
    )

    if args.dry_run:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0

    SNAPSHOT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("Wrote snapshot to %s", SNAPSHOT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
