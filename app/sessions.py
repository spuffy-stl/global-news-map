"""Anonymous per-session engagement log (SMA-816, mirrors Timeline Compare's
SMA-528).

GA4 stays the topline source, but it aggregates and thresholds tiny numbers
and cannot return one visit's step-by-step path. This log records the same
funnel the frontend already fires to GA (selections, story clicks, search,
share, landing hook) plus session_start/session_end, keyed by a random
per-tab session id the client keeps in sessionStorage (dies with the tab).

Privacy (2026-09-27 analytics stance — anonymous session analytics only):
no cookies, no IP, no user agent, no persistent or cross-session id. Event
names and prop keys are allow-listed; props are limited to taxonomy slugs /
country names, view levels, source names, story URLs, landing path,
referrer host and the truncated search text GA already receives.

Storage: its own SQLite file (`sessions.db`) in DATA_DIR, separate from the
rebuildable headline cache. In production DATA_DIR is the host directory
/opt/news-data bind-mounted into the container (deploy/deploy.sh), so the
log survives app restarts, container redeploys and VM reboots.
"""
import json
import os
import re
import sqlite3
import threading
import time

from . import config

_lock = threading.Lock()
DB_PATH = os.path.join(config.DATA_DIR, "sessions.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    ts INTEGER NOT NULL,
    event TEXT NOT NULL,
    props TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_session_events_session_ts
    ON session_events(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_session_events_ts
    ON session_events(ts);
"""

# The GA funnel (app/static/app.js trackEvent call sites) + session bounds.
EVENTS = frozenset({
    "session_start", "page_load", "session_end",
    "select_world", "select_continent", "select_region", "select_country",
    "stories_shown", "click_story",
    "search_focus", "search_country", "search_story", "search_no_results",
    "share_country",
    "hook_shown", "hook_explore", "hook_dismiss",
    "return_visit", "return_badge_click",
    "reset_zoom",
})

# Allowed prop keys -> max string length. Anything else is dropped.
PROP_LIMITS = {
    "path": 200, "ref": 100,
    "continent": 60, "region": 60, "country": 80,
    "level": 20, "source": 120, "via": 20, "method": 20, "kind": 20,
    "value": 80, "query": 40, "story": 400,
    "count": 0, "hours_away": 0, "new_count": 0,  # integers
}

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9-]{16,64}$")
MAX_BODY_BYTES = 4096
MAX_EVENTS_PER_SESSION = 300
RETENTION_DAYS = 180
MAX_ROWS = 500_000  # hard ceiling against junk POSTs on the e2-micro disk
_PRUNE_EVERY = 500

_inserts_since_prune = 0


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
            _prune(conn)
            conn.commit()
        finally:
            conn.close()


def _prune(conn):
    cutoff = int((time.time() - RETENTION_DAYS * 86400) * 1000)
    conn.execute("DELETE FROM session_events WHERE ts < ?", (cutoff,))
    total = conn.execute("SELECT COUNT(*) FROM session_events").fetchone()[0]
    if total > MAX_ROWS:
        conn.execute(
            "DELETE FROM session_events WHERE id IN "
            "(SELECT id FROM session_events ORDER BY id LIMIT ?)",
            (total - MAX_ROWS,),
        )


def clean_props(props):
    """Allow-listed keys only; strings truncated, integers coerced."""
    out = {}
    if not isinstance(props, dict):
        return out
    for key, limit in PROP_LIMITS.items():
        val = props.get(key)
        if val is None or isinstance(val, (dict, list)):
            continue
        if limit == 0:
            if isinstance(val, bool):
                continue
            try:
                out[key] = int(val)
            except (TypeError, ValueError):
                continue
        else:
            s = " ".join(str(val).split())[:limit]
            if s:
                out[key] = s
    return out


def parse_event(payload):
    """Validate a POST /api/events body. Returns (session_id, event, props)
    or None when it is not an event we record."""
    if not isinstance(payload, dict):
        return None
    sid = payload.get("session_id")
    event = payload.get("event")
    if not isinstance(sid, str) or not SESSION_ID_RE.match(sid):
        return None
    if event not in EVENTS:
        return None
    return sid, event, clean_props(payload.get("props"))


def record_event(session_id, event, props, ts_ms=None):
    """Append one event. Returns False when the session hit its cap."""
    global _inserts_since_prune
    ts_ms = int(ts_ms if ts_ms is not None else time.time() * 1000)
    with _lock:
        conn = _connect()
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM session_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            if n >= MAX_EVENTS_PER_SESSION:
                return False
            conn.execute(
                "INSERT INTO session_events (session_id, ts, event, props)"
                " VALUES (?, ?, ?, ?)",
                (session_id, ts_ms, event, json.dumps(props, separators=(",", ":"))),
            )
            _inserts_since_prune += 1
            if _inserts_since_prune >= _PRUNE_EVERY:
                _inserts_since_prune = 0
                _prune(conn)
            conn.commit()
            return True
        finally:
            conn.close()


# Stage reach in the summary: a session "reached" a stage if it fired any of
# the listed events.
STAGES = [
    ("session_start", ("session_start",)),
    ("hook_shown", ("hook_shown",)),
    ("hook_explore", ("hook_explore",)),
    ("select_any", ("select_continent", "select_region", "select_country")),
    ("select_country", ("select_country",)),
    ("search_any", ("search_country", "search_story", "search_no_results")),
    ("stories_shown", ("stories_shown",)),
    ("click_story", ("click_story",)),
    ("share_country", ("share_country",)),
    ("session_end", ("session_end",)),
]


def get_sessions(limit=25):
    """Last `limit` sessions (by latest activity, most recent first), each
    with its events in order, plus stage reach over that window."""
    with _lock:
        conn = _connect()
        try:
            sids = [
                r["session_id"] for r in conn.execute(
                    "SELECT session_id, MAX(ts) AS last_ts FROM session_events"
                    " GROUP BY session_id ORDER BY last_ts DESC LIMIT ?",
                    (limit,),
                )
            ]
            events = {sid: [] for sid in sids}
            if sids:
                marks = ",".join("?" * len(sids))
                rows = conn.execute(
                    "SELECT session_id, ts, event, props FROM session_events"
                    " WHERE session_id IN ({}) ORDER BY ts, id".format(marks),
                    sids,
                ).fetchall()
                for r in rows:
                    events[r["session_id"]].append({
                        "ts": r["ts"],
                        "event": r["event"],
                        "props": json.loads(r["props"] or "{}"),
                    })
        finally:
            conn.close()

    sessions = [{"session_id": sid, "events": events[sid]} for sid in sids]
    summary = {"sessions": len(sessions)}
    for stage, names in STAGES:
        summary[stage] = sum(
            1 for s in sessions if any(e["event"] in names for e in s["events"])
        )
    # Of the sessions whose start is in the window, the share that clicked
    # through to at least one story.
    started = [
        s for s in sessions if any(e["event"] == "session_start" for e in s["events"])
    ]
    clicked = sum(
        1 for s in started if any(e["event"] == "click_story" for e in s["events"])
    )
    summary["start_to_click"] = round(clicked / len(started), 3) if started else None
    return {"sessions": sessions, "summary": summary}
