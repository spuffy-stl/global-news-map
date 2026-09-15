"""SQLite storage for headlines (stdlib sqlite3, thread-safe via a lock).

Headlines are tagged with the full taxonomy: continent > region > country
(ADMIN name). Migrated from the old single `region` column (which held the
six continent slugs) in SMA-360.
"""
import os
import sqlite3
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()
DB_PATH = os.path.join(config.DATA_DIR, "news.db")

TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS headlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    continent TEXT NOT NULL,
    region TEXT NOT NULL,
    country TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT NOT NULL,
    source TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    UNIQUE(url, country)
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_headlines_country_fetched
    ON headlines(country, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_headlines_continent_fetched
    ON headlines(continent, fetched_at DESC);
"""

# Backwards-compatible alias (tests/scripts may import SCHEMA).
SCHEMA = TABLE_SCHEMA + INDEXES

MAX_PER_COUNTRY = 100


def _connect():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn):
    """Bring old databases (single `region` column) to the new schema."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(headlines)")}
    if not cols:
        return
    if "region" in cols and "continent" not in cols:
        # Old `region` held the six continent slugs: rename preserves data.
        conn.execute("ALTER TABLE headlines RENAME COLUMN region TO continent")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(headlines)")}
    if "region" not in cols:
        conn.execute("ALTER TABLE headlines ADD COLUMN region TEXT NOT NULL DEFAULT ''")
    if "country" not in cols:
        conn.execute("ALTER TABLE headlines ADD COLUMN country TEXT NOT NULL DEFAULT ''")
    _migrate_uniqueness(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_headlines_country_fetched "
        "ON headlines(country, fetched_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_headlines_continent_fetched "
        "ON headlines(continent, fetched_at DESC)"
    )


def _migrate_uniqueness(conn):
    """Replace the old global UNIQUE(url) with UNIQUE(url, country).

    A feed can be subscribed to by several countries (e.g. a shared
    English-language feed); the story must exist once per country, not once
    globally. SQLite cannot drop a constraint, so rebuild the table when the
    old single-column unique index is present.
    """
    auto = [
        r for r in conn.execute("PRAGMA index_list(headlines)")
        if r["origin"] == "u" and r["name"].startswith("sqlite_autoindex")
    ]
    needs_rebuild = False
    for idx in auto:
        quoted = '"' + idx["name"].replace('"', '""') + '"'
        cols = [r["name"] for r in conn.execute("PRAGMA index_info({})".format(quoted))]
        if cols == ["url"]:
            needs_rebuild = True
    if not needs_rebuild:
        return
    conn.execute(
        """CREATE TABLE headlines_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            continent TEXT NOT NULL,
            region TEXT NOT NULL,
            country TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT,
            url TEXT NOT NULL,
            source TEXT,
            published_at TEXT,
            fetched_at TEXT NOT NULL,
            UNIQUE(url, country)
        )"""
    )
    conn.execute(
        """INSERT INTO headlines_new
           (id, continent, region, country, title, summary, url, source, published_at, fetched_at)
           SELECT id, continent, region, country, title, summary, url, source, published_at, fetched_at
           FROM headlines"""
    )
    conn.execute("DROP TABLE headlines")
    conn.execute("ALTER TABLE headlines_new RENAME TO headlines")


def init_db():
    with _lock:
        conn = _connect()
        try:
            conn.executescript(TABLE_SCHEMA)
            _migrate(conn)
            conn.executescript(INDEXES)
            conn.commit()
        finally:
            conn.close()


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def upsert_headline(continent, region, country, title, summary, url, source, published_at):
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO headlines
                   (continent, region, title, summary, url, source, published_at, fetched_at, country)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (continent, region, title, summary, url, source, published_at, utcnow_iso(), country),
            )
            conn.commit()
        finally:
            conn.close()


def purge_unknown_continents(valid_slugs):
    """Delete headlines whose continent slug is not in the current taxonomy.

    Guards against stale rows from retired taxonomy versions (e.g. the
    pre-hierarchy 'latin-america' slug left behind by the SMA-360 rebuild):
    without this, /api/status keeps reporting dead continents. Returns the
    number of rows deleted.
    """
    valid = list(valid_slugs)
    with _lock:
        conn = _connect()
        try:
            if not valid:
                return 0
            placeholders = ",".join("?" for _ in valid)
            cur = conn.execute(
                f"DELETE FROM headlines WHERE continent NOT IN ({placeholders})",
                valid,
            )
            deleted = cur.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()


def prune_country(country, keep=MAX_PER_COUNTRY):
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """DELETE FROM headlines WHERE country = ? AND id NOT IN (
                       SELECT id FROM headlines WHERE country = ?
                       ORDER BY fetched_at DESC, id DESC LIMIT ?
                   )""",
                (country, country, keep),
            )
            conn.commit()
        finally:
            conn.close()


def get_headlines(level, key, limit=10):
    """level: 'continent' | 'region' | 'country'."""
    if level not in ("continent", "region", "country"):
        raise ValueError("bad level")
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT continent, region, country, title, summary, url, source,"
                " published_at, fetched_at FROM headlines WHERE {} = ?"
                " ORDER BY COALESCE(published_at, fetched_at) DESC, id DESC LIMIT ?".format(level),
                (key, limit),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def get_top_headlines(limit=15):
    """Most recent headlines across all continents (world view / first-visit hook)."""
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT continent, region, country, title, summary, url, source,"
                " published_at, fetched_at FROM headlines"
                " ORDER BY COALESCE(published_at, fetched_at) DESC, id DESC LIMIT ?",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def get_status():
    """Per-continent headline counts and latest fetch timestamps, plus totals."""
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                """SELECT continent, COUNT(*) AS count, MAX(fetched_at) AS last_fetched
                   FROM headlines GROUP BY continent"""
            )
            continents = {
                r["continent"]: {"count": r["count"], "last_fetched": r["last_fetched"]}
                for r in cur.fetchall()
            }
            cur = conn.execute(
                "SELECT COUNT(*) AS count, MAX(fetched_at) AS last_fetched FROM headlines"
            )
            total = cur.fetchone()
            return {
                "continents": continents,
                "total_count": total["count"],
                "last_fetched": total["last_fetched"],
            }
        finally:
            conn.close()


def get_country_counts():
    """ADMIN name -> story count (only countries with stories)."""
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT country, COUNT(*) AS count FROM headlines"
                " WHERE country != '' GROUP BY country"
            )
            return {r["country"]: r["count"] for r in cur.fetchall()}
        finally:
            conn.close()
