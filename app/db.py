"""SQLite storage for headlines (stdlib sqlite3, thread-safe via a lock)."""
import os
import sqlite3
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()
DB_PATH = os.path.join(config.DATA_DIR, "news.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS headlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT NOT NULL UNIQUE,
    source TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_headlines_region_fetched
    ON headlines(region, fetched_at DESC);
"""

MAX_PER_REGION = 60


def _connect():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock:
        conn = _connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def upsert_headline(region, title, summary, url, source, published_at):
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO headlines
                   (region, title, summary, url, source, published_at, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (region, title, summary, url, source, published_at, utcnow_iso()),
            )
            conn.commit()
        finally:
            conn.close()


def prune_region(region, keep=MAX_PER_REGION):
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """DELETE FROM headlines WHERE region = ? AND id NOT IN (
                       SELECT id FROM headlines WHERE region = ?
                       ORDER BY fetched_at DESC, id DESC LIMIT ?
                   )""",
                (region, region, keep),
            )
            conn.commit()
        finally:
            conn.close()


def get_headlines(region, limit=10):
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                """SELECT region, title, summary, url, source, published_at, fetched_at
                   FROM headlines WHERE region = ?
                   ORDER BY fetched_at DESC, id DESC LIMIT ?""",
                (region, limit),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def get_status():
    """Per-region headline counts and latest fetch timestamps."""
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                """SELECT region, COUNT(*) AS count, MAX(fetched_at) AS last_fetched
                   FROM headlines GROUP BY region"""
            )
            return {
                r["region"]: {"count": r["count"], "last_fetched": r["last_fetched"]}
                for r in cur.fetchall()
            }
        finally:
            conn.close()
