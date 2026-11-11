"""Recent session paths for the Global News Map (SMA-816, mirrors Timeline
Compare's SMA-528 report).

Fetches the anonymous per-session event log via
https://globalnewsmap.net/api/analytics/sessions and prints the last N
sessions as ordered step sequences, plus stage reach over the returned
window. GA4 (ga_report.py) stays the topline source; this is the per-visit
path view GA cannot give at our traffic levels.

The session ids are random per-tab values (sessionStorage, dies with the tab);
the report truncates them to 8 chars. No PII ever enters this log — props are
paths, taxonomy slugs / country names, sources and story URLs only.

Usage: .venv/bin/python analytics/sessions_report.py [--limit 25] [--base http://localhost:8000]
"""
import argparse
import sys
from datetime import datetime, timezone

import requests

PROD_BASE = "https://globalnewsmap.net"

STAGES = [
    "session_start",
    "hook_shown",
    "hook_explore",
    "select_any",
    "select_country",
    "search_any",
    "stories_shown",
    "click_story",
    "share_country",
    "session_end",
]

PROP_KEYS = ("path", "ref", "continent", "region", "country", "level", "kind",
             "value", "query", "source", "via", "method", "count", "story")


def fmt_props(props):
    if not props:
        return ""
    bits = []
    for key in PROP_KEYS:
        if key in props and props[key] not in (None, ""):
            bits.append(f"{key}={props[key]}")
    return " {" + ", ".join(bits) + "}" if bits else ""


def fmt_session(session):
    events = session.get("events", [])
    if not events:
        return None
    start = events[0]["ts"]
    end = events[-1]["ts"]
    dur = max(0, round((end - start) / 1000))
    started = datetime.fromtimestamp(start / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"Session {session['session_id'][:8]}… ({len(events)} steps, {dur}s, started {started} UTC):"
    ]
    for e in events:
        rel = max(0, round((e["ts"] - start) / 1000))
        lines.append(f"  +{rel:>4}s  {e['event']}{fmt_props(e.get('props', {}))}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--base", default=PROD_BASE,
                        help="app base URL (default: production)")
    args = parser.parse_args()
    limit = max(1, min(100, args.limit))

    resp = requests.get(args.base.rstrip("/") + "/api/analytics/sessions",
                        params={"limit": limit}, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    sessions = data.get("sessions", [])
    summary = data.get("summary", {})

    print(f"Last {len(sessions)} sessions (most recent first):\n")
    shown = 0
    for s in sessions:
        block = fmt_session(s)
        if block:
            print(block)
            print()
            shown += 1
    if not shown:
        print("(no sessions recorded yet)\n")

    print("Stage reach (sessions in this window that reached each stage):")
    total = summary.get("sessions", len(sessions)) or 0
    for stage in STAGES:
        n = summary.get(stage, 0)
        pct = f"{100 * n / total:.0f}%" if total else "n/a"
        print(f"- {stage}: {n}/{total} ({pct})")

    stc = summary.get("start_to_click")
    if stc is not None:
        print(f"\nStart -> story click conversion: {100 * stc:.0f}%")


if __name__ == "__main__":
    sys.exit(main())
