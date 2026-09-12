"""Daily Google Analytics summary for the Global News Map.

Queries the GA4 Data API as muse-agent@muse-spuffy.iam.gserviceaccount.com
(Viewer on the property) and prints a Markdown summary for the daily loop.

Usage: .venv/bin/python analytics/ga_report.py
Config: analytics/config.json -> {"property_id": "<numeric GA4 property id>"}
"""
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gauth import get_token

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
BASE = "https://analyticsdata.googleapis.com/v1beta"
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
EVENTS = ["select_region", "click_story", "refresh_headlines"]


def run_report(token, property_id, body):
    url = f"{BASE}/properties/{property_id}:runReport"
    last = None
    for attempt in range(4):
        try:
            r = requests.post(
                url,
                headers={"Authorization": "Bearer " + token},
                json=body,
                timeout=60,
            )
            if r.status_code == 200:
                return r.json()
            last = f"GA API {r.status_code}: {r.text[:300]}"
        except Exception as e:  # transient proxy/network hiccup
            last = f"{type(e).__name__}: {e}"
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(last)


def rows(report):
    out = []
    for row in report.get("rows", []):
        dims = [v["value"] for v in row.get("dimensionValues", [])]
        vals = [v["value"] for v in row.get("metricValues", [])]
        out.append((dims, vals))
    return out


def main():
    with open(CONFIG) as f:
        pid = json.load(f)["property_id"]
    token = get_token(SCOPES)

    daily = run_report(token, pid, {
        "dateRanges": [{"startDate": "7daysAgo", "endDate": "yesterday"}],
        "dimensions": [{"name": "date"}],
        "metrics": [{"name": m} for m in
                    ["activeUsers", "sessions", "engagedSessions", "screenPageViews"]],
        "orderBys": [{"dimension": {"dimensionName": "date"}}],
    })
    new_ret = run_report(token, pid, {
        "dateRanges": [{"startDate": "7daysAgo", "endDate": "yesterday"}],
        "dimensions": [{"name": "newVsReturning"}],
        "metrics": [{"name": "activeUsers"}],
    })
    events = run_report(token, pid, {
        "dateRanges": [{"startDate": "7daysAgo", "endDate": "yesterday"}],
        "dimensions": [{"name": "eventName"}],
        "metrics": [{"name": "eventCount"}],
        "dimensionFilter": {"filter": {
            "fieldName": "eventName",
            "inListFilter": {"values": EVENTS},
        }},
    })

    days = rows(daily)
    tot = [0, 0, 0, 0]
    for _, vals in days:
        for i in range(4):
            tot[i] += int(vals[i])
    y = days[-1][1] if days else ["0"] * 4

    lines = ["## Google Analytics — Global News Map", ""]
    lines.append(f"Yesterday ({days[-1][0][0] if days else 'n/a'}): **{y[0]}** users, "
                 f"**{y[1]}** sessions, **{y[2]}** engaged sessions, **{y[3]}** page views.")
    lines.append(f"Last 7 days: **{tot[0]}** users, **{tot[1]}** sessions, "
                 f"**{tot[2]}** engaged sessions, **{tot[3]}** page views.")
    lines.append("")
    lines.append("Daily active users (last 7 days):")
    for dims, vals in days:
        lines.append(f"- {dims[0]}: {vals[0]}")
    lines.append("")
    lines.append("New vs returning (last 7 days):")
    for dims, vals in rows(new_ret):
        lines.append(f"- {dims[0]}: {vals[0]} users")
    lines.append("")
    lines.append("Custom events (last 7 days):")
    seen = {dims[0]: vals[0] for dims, vals in rows(events)}
    for ev in EVENTS:
        lines.append(f"- {ev}: {seen.get(ev, '0')}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
