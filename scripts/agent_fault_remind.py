#!/usr/bin/env python3
"""
WP-316: Agent Fault Reminder — выдаёт 2-3 напоминания перед сессией.
Читает SQLite (zero deps), выводит markdown для вставки в system prompt.

Usage:
    python3 agent_fault_remind.py --protocol close
    python3 agent_fault_remind.py --protocol open
    python3 agent_fault_remind.py --protocol work
"""

import sqlite3
import json
import argparse
import os
from pathlib import Path

# Parameterized paths: read from env (set by .exocortex.env or shell)
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", str(Path.home() / "IWE")))
GOVERNANCE_REPO = os.environ.get("GOVERNANCE_REPO", "DS-strategy")
DB_PATH = WORKSPACE_DIR / GOVERNANCE_REPO / "exocortex" / "agent-fault-profile" / "iwe_memory.db"


def _fetch_agent_faults(c, protocol: str) -> list:
    """Fetch agent_fault rows filtered by protocol, returns (display, trust, source='fault')."""
    c.execute("SELECT content, trust_score, context FROM facts WHERE fact_type='agent_fault' ORDER BY trust_score DESC, id DESC")
    specific, fallback = [], []
    seen = set()
    for content, trust, ctx_raw in c.fetchall():
        try:
            ctx = json.loads(ctx_raw)
            protos = ctx.get('protocols', ['work'])
        except Exception:
            ctx, protos = {}, ['work']

        display = ctx.get('short_content') or content
        if '): ' in display:
            display = display.split('): ', 1)[1]
        elif ': ' in display and display.index(': ') < 40:
            display = display.split(': ', 1)[1]

        key = display[:80]
        if key in seen:
            continue
        seen.add(key)

        label = f"[{ctx.get('severity','medium').upper()} | n={ctx.get('occurrences',1)}]"
        entry = (trust, label, display, 'fault')

        if protocol != 'all' and protocol in protos:
            specific.append(entry)
        elif protocol == 'all' or 'work' in protos:
            fallback.append(entry)

    return specific + fallback


def _fetch_checklist_misses(c, protocol: str) -> list:
    """Fetch checklist_missed rows for the protocol, returns (display, trust, source='checklist')."""
    c.execute("""
        SELECT content, trust_score
        FROM facts
        WHERE fact_type = 'checklist_missed'
          AND context LIKE ?
        ORDER BY trust_score DESC
    """, (f'%"protocol": "{protocol}"%',))
    results = []
    seen = set()
    for content, trust in c.fetchall():
        if content in seen:
            continue
        seen.add(content)
        results.append((trust, '[ЧЕКЛИСТ]', content, 'checklist'))
    return results


def _context_score(display: str, keywords: list[str]) -> float:
    """Score how relevant an entry is to the given context keywords."""
    text = display.lower()
    return sum(1 for kw in keywords if kw.lower() in text)


def remind(protocol: str, limit: int = 3, context: str = ""):
    if not DB_PATH.exists():
        print("<!-- iwe_memory.db not found. Run sync_feedback_to_memory.py first -->")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    faults = _fetch_agent_faults(c, protocol)
    misses = _fetch_checklist_misses(c, protocol)
    conn.close()

    # Context-aware boost: re-score entries if --context provided
    keywords = [w.strip() for w in context.split() if len(w.strip()) > 2] if context else []

    def sort_key(entry):
        trust, _label, display, _source = entry
        if keywords:
            boost = _context_score(display, keywords) * 0.3
            return -(trust + boost)
        return -trust

    combined = sorted(misses + faults, key=sort_key)

    # Deduplicate by display text
    seen, rows = set(), []
    for entry in combined:
        key = entry[2][:60]
        if key not in seen:
            seen.add(key)
            rows.append(entry)
        if len(rows) >= limit:
            break

    if not rows:
        print(f"<!-- No reminders for '{protocol}' -->")
        return

    ctx_label = f" + context: '{context}'" if context else ""
    print(f"\n🧠 Agent Fault Profile (before '{protocol}'{ctx_label}):")
    print("=" * 60)
    for trust, label, display, source in rows:
        marker = "🔴" if trust >= 0.8 else "🟡" if trust >= 0.65 else "🟢"
        print(f"{marker} {label} {display}")
    print("=" * 60)
    checklist_count = sum(1 for r in rows if r[3] == 'checklist')
    if checklist_count:
        print(f"  ↑ {checklist_count} из чеклиста (живые сессии) · {len(rows)-checklist_count} из feedback-архива")
    print("💡 Применить до начала работы.\n")


def stats():
    if not DB_PATH.exists():
        print("<!-- iwe_memory.db not found -->")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), AVG(trust_score) FROM facts WHERE fact_type='agent_fault'")
    total, avg_trust = c.fetchone()
    c.execute("SELECT COUNT(DISTINCT context) FROM facts WHERE fact_type='agent_fault'")
    unique = c.fetchone()[0]
    conn.close()
    print(f"\n📊 Agent Fault Profile Stats:")
    print(f"  Total patterns: {total}")
    print(f"  Unique rules: {unique}")
    print(f"  Avg trust: {avg_trust:.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent Fault Reminder")
    parser.add_argument("--protocol", choices=["open", "close", "day_close", "work", "all"], default="work")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--context", default="", help="Описание текущей задачи для контекстного буста")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    args = parser.parse_args()

    if args.stats:
        stats()
    else:
        remind(args.protocol, args.limit, args.context)
