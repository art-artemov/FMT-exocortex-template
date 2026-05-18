#!/usr/bin/env python3
"""
WP-316: Синхронизация feedback-файлов → SQLite Agent Fault Profile.
Сканирует feedback_*.md, извлекает паттерны косяков агента, пишет в iwe_memory.db.

Usage:
    python3 sync_feedback_to_memory.py
"""

import sqlite3
import re
import json
import os
from pathlib import Path
from datetime import datetime

# Parameterized paths: read from env (set by .exocortex.env or shell)
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", str(Path.home() / "IWE")))
GOVERNANCE_REPO = os.environ.get("GOVERNANCE_REPO", "DS-strategy")
IWE_ROOT = WORKSPACE_DIR
# IWE/memory/ is a symlink to auto-memory and may have files not in exocortex
FEEDBACK_DIRS = [
    IWE_ROOT / GOVERNANCE_REPO / "exocortex",
    IWE_ROOT / "memory",
]
DB_PATH = IWE_ROOT / GOVERNANCE_REPO / "exocortex" / "agent-fault-profile" / "iwe_memory.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_type TEXT NOT NULL,
            content TEXT NOT NULL,
            context TEXT,
            trust_score REAL DEFAULT 0.5,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            session_id TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS feedback_sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT,
            rule_name TEXT,
            synced_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def parse_feedback_file(path: Path):
    """Parse a feedback_*.md file and extract agent fault patterns."""
    text = path.read_text(encoding="utf-8")
    faults = []

    # Extract frontmatter name/description
    frontmatter_match = re.search(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    file_name = path.stem
    file_desc = ""
    if frontmatter_match:
        fm = frontmatter_match.group(1)
        name_m = re.search(r'^name:\s*(.+)', fm, re.MULTILINE)
        desc_m = re.search(r'^description:\s*(.+)', fm, re.MULTILINE)
        if name_m:
            file_name = name_m.group(1).strip()
        if desc_m:
            file_desc = desc_m.group(1).strip()

    # Find ## Правило / ## Rule sections
    rule_pattern = re.compile(r'^##\s+([^\n]+)\n(.*?)(?=^##\s|\Z)', re.MULTILINE | re.DOTALL)
    for match in rule_pattern.finditer(text):
        rule_title = match.group(1).strip()
        rule_body = match.group(2)

        # Extract "Журнал:" or "Journal:" entries
        journal_entries = 0
        journal_match = re.search(r'\*\*Журнал:\*\*(.*?)(?=^##\s|\Z)', rule_body, re.DOTALL | re.IGNORECASE)
        if journal_match:
            journal_text = journal_match.group(1)
            # Count incidents by WP references + dated entries + sentence-like chunks
            wp_refs = len(re.findall(r'WP-\d+', journal_text))
            dates = len(re.findall(r'\b(\d{1,2}\s+[а-яa-z]+(?:\s+\d{4})?|\d{4}-\d{2}-\d{2})\b', journal_text, re.IGNORECASE))
            # Use max of wp_refs and dates, or estimate from text length
            journal_entries = max(wp_refs, dates, len(journal_text) // 300)

        # Determine protocol relevance from text (use set to avoid duplicates)
        proto_set = set()
        lower_body = rule_body.lower()
        if 'day open' in lower_body or 'day_open' in lower_body or 'protocol-open' in lower_body:
            proto_set.add('open')
        if 'open' in lower_body and 'protocol' in lower_body:
            proto_set.add('open')
        if 'day close' in lower_body or 'day_close' in lower_body or 'protocol-close' in lower_body:
            proto_set.add('close')
        if 'close' in lower_body and 'protocol' in lower_body:
            proto_set.add('close')
        if 'work' in lower_body or 'session' in lower_body:
            proto_set.add('work')
        protocols = list(proto_set) or ['work']

        # Severity based on journal length / incident count
        severity = 'medium'
        if journal_entries >= 3:
            severity = 'high'
        if journal_entries >= 5:
            severity = 'critical'

        # Build content (verbose, for dedup key; short_content for display)
        content = f"{file_name}: {rule_title}"
        if file_desc:
            content = f"{file_name} ({file_desc}): {rule_title}"

        # short_content = just the rule title, used in remind output
        short_content = rule_title

        # Use stem (filename without extension) as dedup key — avoids path-based duplicates
        # when the same file exists in both exocortex/ and memory/ directories
        file_stem = path.stem

        context = {
            'source_file': file_stem,
            'rule_name': rule_title,
            'short_content': short_content,
            'protocols': protocols,
            'severity': severity,
            'occurrences': journal_entries,
            'last_sync': datetime.utcnow().isoformat(),
        }

        faults.append({
            'content': content,
            'context': json.dumps(context, ensure_ascii=False),
            'trust_score': min(0.95, 0.5 + 0.1 * journal_entries),
            'source_file': file_stem,
            'rule_name': rule_title,
        })

    # Also handle files without explicit rules (whole-file feedback)
    if not faults and file_desc:
        stem = path.stem
        context = {
            'source_file': stem,
            'rule_name': file_name,
            'short_content': file_desc,
            'protocols': ['work'],
            'severity': 'medium',
            'occurrences': 1,
            'last_sync': datetime.utcnow().isoformat(),
        }
        faults.append({
            'content': f"{file_name}: {file_desc}",
            'context': json.dumps(context, ensure_ascii=False),
            'trust_score': 0.6,
            'source_file': stem,
            'rule_name': file_name,
        })

    return faults


def sync():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # In-memory dedup: (file_stem, rule_name) → row_id
    # This avoids read-before-write issues in SQLite implicit transactions
    processed: dict = {}

    # Pre-load existing entries from DB
    c.execute("SELECT id, trust_score, context FROM facts WHERE fact_type='agent_fault'")
    for row_id, trust, ctx_raw in c.fetchall():
        try:
            ctx = json.loads(ctx_raw)
            key = (ctx.get('source_file', ''), ctx.get('rule_name', ''))
            processed[key] = (row_id, trust)
        except Exception:
            pass

    total = 0

    for fb_dir in FEEDBACK_DIRS:
        if not fb_dir.exists():
            continue
        for fp in sorted(fb_dir.glob("feedback_*.md")):
            faults = parse_feedback_file(fp)
            for fault in faults:
                key = (fault['source_file'], fault['rule_name'])
                if key in processed:
                    row_id, old_trust = processed[key]
                    if abs(old_trust - fault['trust_score']) > 0.01:
                        c.execute(
                            "UPDATE facts SET trust_score=?, context=? WHERE id=?",
                            (fault['trust_score'], fault['context'], row_id)
                        )
                        processed[key] = (row_id, fault['trust_score'])
                else:
                    c.execute(
                        "INSERT INTO facts (fact_type, content, context, trust_score, session_id) VALUES (?, ?, ?, ?, ?)",
                        ('agent_fault', fault['content'], fault['context'], fault['trust_score'], 'sync-feedback')
                    )
                    processed[key] = (-1, fault['trust_score'])
                    total += 1

    conn.commit()
    conn.close()
    print(f"✅ Sync complete: {total} new agent fault patterns added to {DB_PATH}")


if __name__ == "__main__":
    sync()
