"""Polite RSS crawler: fetches top headlines per region.

- Proper User-Agent, request timeouts, 1s pause between feeds.
- Per-feed error handling: one dead feed can never kill a run.
"""
import logging
import re
import time
from datetime import datetime, timezone

import feedparser
import requests

from . import config, db

log = logging.getLogger("global-news-map.crawler")

_session = requests.Session()
_session.headers.update({"User-Agent": config.USER_AGENT})

_TAG_RE = re.compile(r"<[^>]+>")


def _fetch(url):
    resp = _session.get(url, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def _published_iso(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
        except Exception:
            return None
    return None


def _clean(text, limit=2000):
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def crawl_feed(feed):
    """Fetch and parse one feed. Returns a list of headline dicts. Never raises."""
    try:
        raw = _fetch(feed["url"])
    except Exception as exc:
        log.warning("feed fetch failed: %s (%s): %s", feed["name"], feed["url"], exc)
        return []
    try:
        parsed = feedparser.parse(raw)
    except Exception as exc:
        log.warning("feed parse failed: %s: %s", feed["name"], exc)
        return []
    if getattr(parsed, "bozo", False) and not parsed.entries:
        log.warning("feed bozo with no entries: %s", feed["name"])
        return []
    items = []
    for entry in parsed.entries[:25]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        summary = _clean(entry.get("summary") or entry.get("description") or "")
        items.append(
            {
                "region": feed["region"],
                "title": title[:500],
                "summary": summary,
                "url": link,
                "source": feed["name"],
                "published_at": _published_iso(entry),
            }
        )
    time.sleep(1)  # be polite to publishers
    return items


def crawl_all_regions():
    """Crawl every configured feed, upsert headlines, prune old rows."""
    log.info("starting crawl of %d feeds", len(config.FEEDS))
    counts = {}
    for feed in config.FEEDS:
        items = crawl_feed(feed)
        for item in items:
            db.upsert_headline(**item)
        counts[feed["region"]] = counts.get(feed["region"], 0) + len(items)
        log.info("feed %-22s region %-14s items %d", feed["name"], feed["region"], len(items))
    for region in config.REGIONS:
        db.prune_region(region["slug"])
    log.info("crawl finished: %s", counts)
    return counts
