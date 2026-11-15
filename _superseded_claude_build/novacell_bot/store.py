"""SQLite-backed runtime state.

Holds: ops-managed content (with draft -> approved -> published flow and version
history), the content-gap queue, human handoffs, answer feedback, and PII-masked
conversation logs.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,          -- e.g. FAQ-7 (edit of seed row) or FAQ-N1 (new)
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL,             -- draft | published | retired | superseded
    author TEXT, approver TEXT,
    created_at REAL NOT NULL, published_at REAL
);
CREATE TABLE IF NOT EXISTS gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL, theme TEXT, reason TEXT,
    created_at REAL NOT NULL, resolved INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref TEXT, session_id TEXT, reason TEXT, theme TEXT, intent TEXT,
    channel TEXT, package TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT, message_id TEXT, kind TEXT, value TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT, message_id TEXT, role TEXT, text TEXT, meta TEXT, created_at REAL NOT NULL
);
"""

_lock = threading.Lock()


@contextmanager
def conn():
    config.STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        c = sqlite3.connect(config.STATE_DB)
        c.row_factory = sqlite3.Row
        try:
            c.executescript(_SCHEMA)
            yield c
            c.commit()
        finally:
            c.close()


def rows(sql: str, args: tuple = ()) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def execute(sql: str, args: tuple = ()) -> int:
    with conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


# ---- content management (FR-1.2 / 1.3) --------------------------------------

def published_content() -> list[dict]:
    return rows("SELECT * FROM content WHERE status IN ('published','retired') ORDER BY id")


def new_source_id() -> str:
    n = rows("SELECT COUNT(*) AS n FROM content WHERE source_id LIKE 'FAQ-N%'")[0]["n"]
    return f"FAQ-N{n + 1}"


def save_draft(source_id: str | None, question: str, answer: str, category: str, author: str) -> int:
    return execute(
        "INSERT INTO content (source_id, question, answer, category, status, author, created_at)"
        " VALUES (?,?,?,?, 'draft', ?, ?)",
        (source_id or new_source_id(), question, answer, category, author, time.time()),
    )


def publish(draft_id: int, approver: str) -> None:
    with conn() as c:
        d = c.execute("SELECT * FROM content WHERE id=? AND status='draft'", (draft_id,)).fetchone()
        if not d:
            raise ValueError("draft not found")
        if d["author"] and d["author"] == approver:
            raise ValueError("approver must be different from author (two-person rule)")
        c.execute("UPDATE content SET status='superseded' WHERE source_id=? AND status IN ('published','retired')",
                  (d["source_id"],))
        c.execute("UPDATE content SET status='published', approver=?, published_at=? WHERE id=?",
                  (approver, time.time(), draft_id))


def retire(source_id: str, approver: str) -> None:
    with conn() as c:
        c.execute("UPDATE content SET status='superseded' WHERE source_id=? AND status IN ('published','retired')",
                  (source_id,))
        c.execute(
            "INSERT INTO content (source_id, question, answer, category, status, approver, created_at, published_at)"
            " VALUES (?, '', '', '', 'retired', ?, ?, ?)",
            (source_id, approver, time.time(), time.time()),
        )


# ---- gaps, handoffs, feedback, transcripts ---------------------------------

def log_gap(question: str, theme: str, reason: str) -> None:
    execute("INSERT INTO gaps (question, theme, reason, created_at) VALUES (?,?,?,?)",
            (question, theme, reason, time.time()))


def log_handoff(session_id: str, reason: str, theme: str, intent: str, channel: str, package: dict) -> str:
    hid = execute(
        "INSERT INTO handoffs (session_id, reason, theme, intent, channel, package, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (session_id, reason, theme, intent, channel, json.dumps(package), time.time()),
    )
    ref = f"NC-{hid:05d}"
    execute("UPDATE handoffs SET ref=? WHERE id=?", (ref, hid))
    return ref


def log_feedback(session_id: str, message_id: str, kind: str, value: str) -> None:
    execute("INSERT INTO feedback (session_id, message_id, kind, value, created_at) VALUES (?,?,?,?,?)",
            (session_id, message_id, kind, value, time.time()))


def log_turn(session_id: str, message_id: str, role: str, text: str, meta: dict | None = None) -> None:
    execute("INSERT INTO turns (session_id, message_id, role, text, meta, created_at) VALUES (?,?,?,?,?,?)",
            (session_id, message_id, role, text, json.dumps(meta or {}), time.time()))
