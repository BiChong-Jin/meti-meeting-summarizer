"""Shared SQLite database setup and connection management."""

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path("data.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reports (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '(タイトルなし)',
    date        TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    sources     TEXT NOT NULL DEFAULT '[]',
    source_type TEXT NOT NULL DEFAULT 'pdf',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_source_type ON reports(source_type);
CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(date);

CREATE TABLE IF NOT EXISTS session_cache (
    session_id           TEXT PRIMARY KEY,
    pdf_texts            TEXT NOT NULL DEFAULT '[]',
    summary_result       TEXT,
    video_summary_result TEXT,
    auth_email           TEXT DEFAULT '',
    auth_role            TEXT DEFAULT '',
    updated_at           REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS monitor_state (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    last_update_date TEXT NOT NULL DEFAULT '',
    known_hrefs      TEXT NOT NULL DEFAULT '[]',
    last_checked     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS rss_seen_items (
    item_id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS users (
    email         TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',
    created_at    TEXT NOT NULL,
    last_login    TEXT
);
"""

_init_lock = threading.Lock()
_initialized_dbs: set[str] = set()


def _ensure_schema():
    """Initialize schema once per DB path. Thread-safe."""
    db_str = str(DB_PATH)
    if db_str in _initialized_dbs:
        return
    with _init_lock:
        if db_str in _initialized_dbs:
            return
        conn = sqlite3.connect(db_str, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
        conn.close()
        _initialized_dbs.add(db_str)


@contextmanager
def get_connection():
    """Yield a SQLite connection with WAL mode and auto-commit/rollback."""
    _ensure_schema()
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
