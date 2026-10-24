"""SQLite storage for headlines (stdlib sqlite3, thread-safe via a lock).

Headlines are tagged with the full taxonomy: continent > region > country
(ADMIN name). Migrated from the old single `region` column (which held the
six continent slugs) in SMA-360.
"""
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from . import config
from .textclean import clean_summary, clean_title

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

FEED_HEALTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS feed_health (
    url TEXT PRIMARY KEY,
    name TEXT,
    last_attempt TEXT,
    last_success TEXT,
    last_item_count INTEGER,
    newest_entry_at TEXT,
    last_error TEXT
);
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
            conn.executescript(FEED_HEALTH_SCHEMA)
            conn.commit()
        finally:
            conn.close()
    clamp_future_dates()
    clean_stored_text()


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def _sanitize_published_at(published_at, fallback_iso):
    """SMA-693: feeds sometimes emit nonsense future dates (Taipei Times
    date-only entries landing tomorrow, ADIAC items dated 2029/2030). A
    future-dated row sorts above everything forever, pinning the world
    list and emitting an invalid JSON-LD datePublished. Anything later
    than now + 1h is replaced with the fetch time; unparseable values
    are dropped (ordering then falls back to fetched_at)."""
    if not published_at:
        return None
    try:
        pub = datetime.fromisoformat(published_at)
    except (ValueError, TypeError):
        return None
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    horizon = datetime.now(timezone.utc) + timedelta(hours=1)
    if pub > horizon:
        return fallback_iso
    return published_at


def clamp_future_dates():
    """One-shot cleanup for rows already stored with future dates.

    Runs at startup (init_db) so a deploy immediately un-pins any world
    list held hostage by a bad feed date. Returns rows fixed.
    """
    horizon = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "UPDATE headlines SET published_at = fetched_at"
                " WHERE published_at IS NOT NULL AND published_at > ?",
                (horizon,),
            )
            fixed = cur.rowcount
            conn.commit()
            return fixed
        finally:
            conn.close()


def clean_stored_text():
    """SMA-694: run the crawl-time text cleaning over rows stored before
    it existed (raw-HTML titles, entity-laden and boilerplate summaries).
    Runs at startup; idempotent, so repeat runs are no-ops. Returns the
    number of rows rewritten."""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute("SELECT id, title, summary FROM headlines").fetchall()
            changed = 0
            for row in rows:
                title = clean_title(row["title"] or "")
                summary = clean_summary(row["summary"] or "", title=title)
                if title != row["title"] or summary != (row["summary"] or ""):
                    conn.execute(
                        "UPDATE headlines SET title = ?, summary = ? WHERE id = ?",
                        (title, summary, row["id"]),
                    )
                    changed += 1
            conn.commit()
            return changed
        finally:
            conn.close()


def upsert_headline(continent, region, country, title, summary, url, source, published_at):
    fetched = utcnow_iso()
    published_at = _sanitize_published_at(published_at, fetched)
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO headlines
                   (continent, region, title, summary, url, source, published_at, fetched_at, country)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (continent, region, title, summary, url, source, published_at, fetched, country),
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


# --- Freshness (SMA-692) -----------------------------------------------------
# Nothing enforces staleness today except prune_country's 100-row cap, so a
# dead feed's last items stay on its country page forever (Bangladesh was
# serving July 2022 stories in Oct 2026; Belgium's newest was Jun 2025).
# A story is servable when its effective date COALESCE(published_at,
# fetched_at) is within FRESH_HOURS — or, per-country fallback, within
# FALLBACK_DAYS when the country has nothing fresher (keeps slow-publishing
# countries on the map without letting genuinely dead feeds linger).
FRESH_HOURS = 72
FALLBACK_DAYS = 7


def _fresh_cutoffs():
    now = datetime.now(timezone.utc)
    return (
        (now - timedelta(hours=FRESH_HOURS)).isoformat(),
        (now - timedelta(days=FALLBACK_DAYS)).isoformat(),
    )


_FRESH_PREDICATE = (
    "(COALESCE(published_at, fetched_at) >= ?"
    " OR (COALESCE(published_at, fetched_at) >= ?"
    "     AND NOT EXISTS (SELECT 1 FROM headlines f2"
    "                     WHERE f2.country = headlines.country"
    "                     AND COALESCE(f2.published_at, f2.fetched_at) >= ?)))"
)


def get_headlines(level, key, limit=10):
    """level: 'continent' | 'region' | 'country'. Fresh stories only
    (SMA-692 — see _FRESH_PREDICATE)."""
    if level not in ("continent", "region", "country"):
        raise ValueError("bad level")
    cut_fresh, cut_fallback = _fresh_cutoffs()
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT continent, region, country, title, summary, url, source,"
                " published_at, fetched_at FROM headlines WHERE {} = ?"
                " AND {}"
                " ORDER BY COALESCE(published_at, fetched_at) DESC, id DESC LIMIT ?".format(
                    level, _FRESH_PREDICATE
                ),
                (key, cut_fresh, cut_fallback, cut_fresh, limit),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def get_top_headlines(limit=15):
    """Most recent headlines across all continents (world view / first-visit hook).

    SMA-607: a plain global recency sort lets one feed's fresh crawl batch
    fill the whole world panel (live check 2026-10-14: 11/15 Sri Lanka, all
    one source). Select from a larger recent pool with per-country (<=3) and
    per-source (<=4) caps, preserving recency order, then backfill by recency
    if the caps leave the list short.

    SMA-668: those caps still let the staggered crawl's freshest feeds fill
    the list — live check 2026-10-22: 15 stories from just 5 countries /
    5 sources (3 each). Tighten to per-country <=2, per-source <=2 and add
    per-continent <=5, so the world list spans >=8 countries and >=4
    continents; recency backfill still guarantees a full list.

    SMA-693: undated items (published_at NULL) must rank below every dated
    item — previously the COALESCE fell back to fetched_at, so a just-fetched
    undated story outranked genuinely newer dated stories and took top
    slots (live check 2026-10-22: 4 of the top 15 had published_at null).

    SMA-692: the world list is strictly fresh — no per-country fallback
    here; a week-old story never belongs in "Top stories right now".
    """
    pool_limit = max(limit * 20, 100)
    cut_fresh, _ = _fresh_cutoffs()
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT continent, region, country, title, summary, url, source,"
                " published_at, fetched_at FROM headlines"
                " WHERE COALESCE(published_at, fetched_at) >= ?"
                " ORDER BY (published_at IS NULL) ASC,"
                " COALESCE(published_at, fetched_at) DESC, id DESC LIMIT ?",
                (cut_fresh, pool_limit),
            )
            pool = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    picked, deferred = [], []
    per_country, per_source, per_continent = {}, {}, {}
    for row in pool:
        c, s = row.get("country"), row.get("source")
        cont = row.get("continent")
        if (
            per_country.get(c, 0) < 2
            and per_source.get(s, 0) < 2
            and per_continent.get(cont, 0) < 5
        ):
            picked.append(row)
            per_country[c] = per_country.get(c, 0) + 1
            per_source[s] = per_source.get(s, 0) + 1
            per_continent[cont] = per_continent.get(cont, 0) + 1
            if len(picked) >= limit:
                return picked
        else:
            deferred.append(row)
    for row in deferred:
        if len(picked) >= limit:
            break
        picked.append(row)
    return picked


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
    """ADMIN name -> fresh story count (SMA-692: only stories inside the
    freshness window count, so countries whose feeds died drop off the map
    — markers render only when stories > 0 — and out of the sitemap)."""
    cut_fresh, cut_fallback = _fresh_cutoffs()
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT country, COUNT(*) AS count FROM headlines"
                " WHERE country != '' AND " + _FRESH_PREDICATE +
                " GROUP BY country",
                (cut_fresh, cut_fallback, cut_fresh),
            )
            return {r["country"]: r["count"] for r in cur.fetchall()}
        finally:
            conn.close()


# --- Feed health (SMA-692) ---------------------------------------------------

def record_feed_health(url, name, ok, item_count, newest_entry_at, error):
    """Upsert one feed's health row after a crawl attempt."""
    now = utcnow_iso()
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO feed_health
                       (url, name, last_attempt, last_success, last_item_count,
                        newest_entry_at, last_error)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET
                       name = excluded.name,
                       last_attempt = excluded.last_attempt,
                       last_success = CASE WHEN excluded.last_success IS NOT NULL
                                           THEN excluded.last_success
                                           ELSE feed_health.last_success END,
                       last_item_count = excluded.last_item_count,
                       newest_entry_at = excluded.newest_entry_at,
                       last_error = excluded.last_error""",
                (url, name, now, now if ok else None, item_count,
                 newest_entry_at, error),
            )
            conn.commit()
        finally:
            conn.close()


def get_feed_health():
    """All recorded feed-health rows, worst first (never-succeeded, then
    oldest newest-entry), so /api/status surfaces problems at the top."""
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT url, name, last_attempt, last_success, last_item_count,"
                " newest_entry_at, last_error FROM feed_health"
                " ORDER BY (last_success IS NULL) DESC, newest_entry_at ASC"
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
