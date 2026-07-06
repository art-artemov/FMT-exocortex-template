#!/usr/bin/env python3
"""
WP-295 Ф1 Шаг 6: CLI iwe trace — чтение и загрузка agent trace.

Команды:
  iwe-trace.py show <session-id|last>
  iwe-trace.py search [--wp WP-N] [--date YYYY-MM-DD] [--agent X] [--limit N]
  iwe-trace.py upload <ndjson-file>

Требует: AGENT_TRACE_READER_URL (для show/search), AGENT_TRACE_GATEWAY (для upload).
Загрузить переменные: source ~/.secrets/neon

see DP.SC.037 (agent-trace store), DP.ROLE.047 (Trace Recorder).
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None


# ── helpers ──────────────────────────────────────────────────────────────────

def get_conn():
    url = os.environ.get("AGENT_TRACE_READER_URL")
    if not url:
        sys.exit("AGENT_TRACE_READER_URL not set. Run: source ~/.secrets/neon")
    if psycopg2 is None:
        sys.exit("psycopg2 not installed. Run: pip install psycopg2-binary")
    return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)


def fmt_ts(ts):
    if ts is None:
        return "—"
    if hasattr(ts, "strftime"):
        return ts.strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(ts)


def fmt_duration(start, end):
    if start is None or end is None:
        return "—"
    delta = end - start
    total = int(delta.total_seconds())
    if total < 60:
        return f"{total}s"
    return f"{total // 60}m{total % 60:02d}s"


# ── show ─────────────────────────────────────────────────────────────────────

def cmd_show(session_id_arg: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if session_id_arg == "last":
                cur.execute(
                    "SELECT * FROM agent_trace.session ORDER BY started_at DESC LIMIT 1"
                )
            else:
                cur.execute(
                    "SELECT * FROM agent_trace.session WHERE session_id = %s",
                    (session_id_arg,),
                )
            row = cur.fetchone()

    if not row:
        sys.exit(f"Session not found: {session_id_arg}")

    sid = str(row["session_id"])
    print(f"\n{'─' * 60}")
    print(f"  Session: {sid}")
    print(f"  Agent:   {row['agent_id']}")
    print(f"  Started: {fmt_ts(row['started_at'])}")
    print(f"  Ended:   {fmt_ts(row['ended_at'])}")
    print(f"  Status:  {row['closed_status'] or '(open)'}")
    print(f"  Dur:     {fmt_duration(row['started_at'], row['ended_at'])}")
    if row["wp_id"]:
        print(f"  WP:      {row['wp_id']}")
    if row["context_summary"]:
        print(f"  Context: {row['context_summary']}")
    artifacts = row["produced_artifact_ids"] or []
    if artifacts:
        print(f"  Artifacts: {', '.join(artifacts)}")
    print(f"{'─' * 60}")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tool_name, called_at, response_size_bytes
                FROM agent_trace.tool_call
                WHERE session_id = %s
                ORDER BY called_at
                """,
                (sid,),
            )
            tool_calls = cur.fetchall()

            cur.execute(
                """
                SELECT d.sequence, d.decided_at, d.decision_text, d.chosen_hypothesis,
                       d.rationale,
                       array_agg(h.hypothesis_text ORDER BY h.id) FILTER (WHERE h.id IS NOT NULL) AS hypotheses
                FROM agent_trace.decision d
                LEFT JOIN agent_trace.hypothesis h ON h.decision_id = d.id AND h.status = 'rejected'
                WHERE d.session_id = %s
                GROUP BY d.id
                ORDER BY d.sequence
                """,
                (sid,),
            )
            decisions = cur.fetchall()

    if tool_calls:
        print(f"\n  Tool calls ({len(tool_calls)}):")
        for tc in tool_calls:
            ts = fmt_ts(tc["called_at"])
            print(f"    [{ts}] {tc['tool_name']}  ({tc['response_size_bytes']} bytes)")

    if decisions:
        print(f"\n  Decisions ({len(decisions)}):")
        for d in decisions:
            print(f"\n  #{d['sequence']} [{fmt_ts(d['decided_at'])}]")
            print(f"    {d['decision_text']}")
            print(f"    → {d['chosen_hypothesis']}")
            if d["rationale"]:
                print(f"    rationale: {d['rationale'][:120]}{'…' if len(d['rationale']) > 120 else ''}")
            if d["hypotheses"]:
                print(f"    rejected:  {'; '.join(d['hypotheses'])}")

    print()


# ── search ────────────────────────────────────────────────────────────────────

def cmd_search(wp, date, agent, limit):
    clauses = []
    params = []

    if wp:
        clauses.append("s.wp_id = %s")
        params.append(wp)
    if date:
        clauses.append("s.started_at::date = %s")
        params.append(date)
    if agent:
        clauses.append("s.agent_id ILIKE %s")
        params.append(f"%{agent}%")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    query = f"""
        SELECT s.session_id, s.agent_id, s.started_at, s.ended_at,
               s.closed_status, s.wp_id, s.context_summary,
               COUNT(DISTINCT tc.id) AS tool_calls,
               COUNT(DISTINCT d.id)  AS decisions
        FROM agent_trace.session s
        LEFT JOIN agent_trace.tool_call tc ON tc.session_id = s.session_id
        LEFT JOIN agent_trace.decision d  ON d.session_id  = s.session_id
        {where}
        GROUP BY s.session_id
        ORDER BY s.started_at DESC
        LIMIT %s
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    if not rows:
        print("No sessions found.")
        return

    col_w = 36
    print(f"\n  {'session_id':<{col_w}}  {'started_at':<20}  {'status':<10}  {'wp':<8}  {'tc':>3}  {'dec':>3}  context")
    print(f"  {'─' * col_w}  {'─' * 20}  {'─' * 10}  {'─' * 8}  {'─':>3}  {'─':>3}  {'─' * 30}")
    for r in rows:
        sid = str(r["session_id"])
        ts = fmt_ts(r["started_at"])[:19]
        status = r["closed_status"] or "(open)"
        wp_col = (r["wp_id"] or "")[:8]
        ctx = (r["context_summary"] or "")[:40]
        print(f"  {sid:<{col_w}}  {ts:<20}  {status:<10}  {wp_col:<8}  {r['tool_calls']:>3}  {r['decisions']:>3}  {ctx}")
    print(f"\n  {len(rows)} session(s) found.\n")


# ── upload ────────────────────────────────────────────────────────────────────

def cmd_upload(ndjson_path: str):
    path = Path(ndjson_path).expanduser()
    if not path.exists():
        sys.exit(f"File not found: {path}")

    endpoint = os.environ.get(
        "AGENT_TRACE_GATEWAY",
        "https://event-gateway.aisystant.workers.dev/events",
    )
    source_name = "agent-trace-recorder"
    session_uuid = path.stem  # filename without extension

    lines = [l for l in path.read_text().splitlines() if l.strip()]
    sent = failed = 0

    for idx, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"  line {idx}: JSON parse error — {e}", file=sys.stderr)
            failed += 1
            continue

        event_type = event.get("event_type", "")
        payload    = event.get("payload", {})
        occurred_at = event.get("emitted_at", "")
        schema_version = event.get("schema_version", "v1")
        external_id = f"{session_uuid}-{idx}-{event_type}"

        body_str = json.dumps({
            "source": source_name,
            "external_id": external_id,
            "event_type": event_type,
            "schema_version": schema_version,
            "payload": payload,
            "occurred_at": occurred_at,
        })

        try:
            result = subprocess.run(
                ["curl", "-s", "-w", "\n%{http_code}", "-X", "POST", endpoint,
                 "-H", "Content-Type: application/json", "-d", body_str],
                capture_output=True, text=True, timeout=15,
            )
            parts = result.stdout.rsplit("\n", 1)
            resp_text = parts[0].strip() if len(parts) > 1 else result.stdout.strip()
            http_code = int(parts[1].strip()) if len(parts) > 1 else 0
            if http_code in (200, 201):
                resp_body = json.loads(resp_text) if resp_text else {}
                sent += 1
                status = "new" if resp_body.get("inserted") else "dup"
                print(f"  line {idx} [{event_type}]: {status}")
            else:
                print(f"  line {idx}: HTTP {http_code} — {resp_text[:200]}", file=sys.stderr)
                failed += 1
        except Exception as e:
            print(f"  line {idx}: error — {e}", file=sys.stderr)
            failed += 1

    icon = "✓" if failed == 0 else "⚠"
    print(f"\n  {icon} {sent}/{len(lines)} sent, {failed} failed  (session {session_uuid})")
    if failed == 0 and sent > 0:
        dest = path.parent / "uploaded" / path.name
        dest.parent.mkdir(exist_ok=True)
        path.rename(dest)
        print(f"  moved → {dest}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="iwe trace",
        description="Agent trace CLI (WP-295 Ф1 Шаг 6)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_show = sub.add_parser("show", help="показать трейс сессии")
    p_show.add_argument("session_id", help="UUID или 'last'")

    p_search = sub.add_parser("search", help="поиск сессий")
    p_search.add_argument("--wp",    help="фильтр по WP (напр. WP-295)")
    p_search.add_argument("--date",  help="фильтр по дате YYYY-MM-DD")
    p_search.add_argument("--agent", help="фильтр по agent_id (подстрока)")
    p_search.add_argument("--limit", type=int, default=20, help="макс строк (default 20)")

    p_upload = sub.add_parser("upload", help="загрузить NDJSON в event-gateway")
    p_upload.add_argument("ndjson_file", help="путь к .ndjson файлу")

    args = parser.parse_args()

    if args.cmd == "show":
        cmd_show(args.session_id)
    elif args.cmd == "search":
        cmd_search(args.wp, args.date, args.agent, args.limit)
    elif args.cmd == "upload":
        cmd_upload(args.ndjson_file)


if __name__ == "__main__":
    main()
