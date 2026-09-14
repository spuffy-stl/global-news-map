#!/usr/bin/env python3
"""Validate every feed URL in app/sources.yaml.

Fetches each unique URL, requires HTTP 200 + a parseable RSS/Atom feed with
at least MIN_ENTRIES entries that have title + link. Prints a per-feed report
and a per-country coverage summary. Exits 1 if any country has zero working
feeds (gate for merging new sources).
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import feedparser
import requests
import yaml

MIN_ENTRIES = 3
WORKERS = 8
TIMEOUT = 25

SOURCES = os.path.join(os.path.dirname(__file__), "..", "app", "sources.yaml")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def check(url):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        return ("http_error", str(e)[:100])
    try:
        p = feedparser.parse(r.content)
    except Exception as e:
        return ("parse_error", str(e)[:100])
    good = [e for e in p.entries if (e.get("title") or "").strip() and (e.get("link") or "").strip()]
    if len(good) < MIN_ENTRIES:
        return ("no_entries", f"only {len(good)} usable entries (bozo={getattr(p, 'bozo', '?')})")
    return ("ok", f"{len(good)} entries")


def main():
    with open(SOURCES, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    feeds = {}  # url -> {name, countries}
    for cont in data.get("continents", []):
        for region in cont.get("regions", []):
            for country in region.get("countries", []):
                for src in country.get("sources", []) or []:
                    e = feeds.setdefault(src["url"], {"name": src["name"], "countries": []})
                    e["countries"].append(country["name"])
    urls = list(feeds)
    print(f"checking {len(urls)} unique feeds...\n")
    results = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for url, res in zip(urls, ex.map(check, urls)):
            results[url] = res
    ok = sum(1 for s, _ in results.values() if s == "ok")
    for url in urls:
        status, detail = results[url]
        mark = "OK " if status == "ok" else "FAIL"
        print(f"[{mark}] {feeds[url]['name']:28s} {url}\n       -> {status}: {detail}")
    print(f"\n{ok}/{len(urls)} feeds working")
    # coverage: a country FAILS only if it has configured sources but none work.
    # Countries with an explicitly empty source list are reported separately
    # (documented gaps to be filled by the daily growth loop, not regressions).
    gaps, unconfigured = [], []
    for cont in data.get("continents", []):
        for region in cont.get("regions", []):
            for country in region.get("countries", []):
                configured = country.get("sources", []) or []
                if not configured:
                    unconfigured.append(country["name"])
                    continue
                working = sum(
                    1 for src in configured
                    if results.get(src["url"], ("?",))[0] == "ok"
                )
                if working == 0:
                    gaps.append(country["name"])
    if unconfigured:
        print(f"\n{len(unconfigured)} countries with no sources configured (explicit gaps):")
        for g in unconfigured:
            print("  -", g)
    if gaps:
        print(f"\n{len(gaps)} countries with ZERO working feeds:")
        for g in gaps:
            print("  -", g)
        return 1
    print("\nEvery configured country has at least one working feed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
