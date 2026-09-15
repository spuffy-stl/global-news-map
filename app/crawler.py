"""Polite RSS crawler: fetches top headlines per country from local sources.

- Sources come from app/sources.yaml (continent > region > country > feeds).
- Each unique feed URL is fetched once per run, then attributed to every
  subscribed country.
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
    # One retry with a short backoff: transient network/proxy failures are
    # common across 234 feeds (observed with a Cloudflare-fronted feed that
    # succeeded on retry), and a single failed attempt leaves a country empty
    # until the next daily crawl.
    last_exc = None
    for attempt in (1, 2):
        try:
            resp = _session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:
            last_exc = exc
            if attempt == 1:
                time.sleep(3)
    raise last_exc


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
                "title": title[:500],
                "summary": summary,
                "url": link,
                "published_at": _published_iso(entry),
            }
        )
    time.sleep(1)  # be polite to publishers
    return items


def crawl_all():
    """Crawl every unique feed, attribute items to subscribed countries."""
    feeds = config.iter_feeds()
    log.info("starting crawl of %d unique feeds", len(feeds))
    counts = {}
    touched = set()
    for feed in feeds:
        items = crawl_feed(feed)
        for sub in feed["subscribers"]:
            for item in items:
                db.upsert_headline(
                    continent=sub["continent"],
                    region=sub["region"],
                    country=sub["country"],
                    title=item["title"],
                    summary=item["summary"],
                    url=item["url"],
                    source=sub["source_name"],
                    published_at=item["published_at"],
                )
            key = (sub["continent"], sub["country"])
            counts[key] = counts.get(key, 0) + len(items)
            touched.add(sub["country"])
        log.info("feed %-28s subscribers %2d items %d",
                 feed["name"], len(feed["subscribers"]), len(items))
    for country in touched:
        db.prune_country(country)
    purged = db.purge_unknown_continents({c["slug"] for c in config.CONTINENTS})
    if purged:
        log.info("purged %d headlines with retired continent slugs", purged)
    log.info("crawl finished: %d countries touched", len(touched))
    return counts


# Backwards-compatible alias (old scheduler entry point).
def crawl_all_regions():
    return crawl_all()
