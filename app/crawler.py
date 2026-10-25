"""Polite RSS crawler: fetches top headlines per country from local sources.

- Sources come from app/sources.yaml (continent > region > country > feeds).
- Each unique feed URL is fetched once per run, then attributed to every
  subscribed country.
- Proper User-Agent, request timeouts, 1s pause between feeds.
- Per-feed error handling: one dead feed can never kill a run.
"""
import logging
import time
from datetime import datetime, timezone

import feedparser
import requests

from . import config, db
from .textclean import clean_summary, clean_title

log = logging.getLogger("global-news-map.crawler")

_session = requests.Session()
_session.headers.update({"User-Agent": config.USER_AGENT})


def _fetch(url):
    # One retry with a short backoff: transient network/proxy failures are
    # common across 234 feeds (observed with a Cloudflare-fronted feed that
    # succeeded on retry), and a single failed attempt leaves a country empty
    # until the next crawl (twice daily).
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


def crawl_feed(feed):
    """Fetch and parse one feed. Returns (items, error): error is None on a
    usable fetch, else a short string. Never raises. (SMA-692: the error
    used to be swallowed, leaving feed health invisible.)"""
    try:
        raw = _fetch(feed["url"])
    except Exception as exc:
        log.warning("feed fetch failed: %s (%s): %s", feed["name"], feed["url"], exc)
        return [], "fetch: {}".format(str(exc)[:120])
    try:
        parsed = feedparser.parse(raw)
    except Exception as exc:
        log.warning("feed parse failed: %s: %s", feed["name"], exc)
        return [], "parse: {}".format(str(exc)[:120])
    if getattr(parsed, "bozo", False) and not parsed.entries:
        log.warning("feed bozo with no entries: %s", feed["name"])
        return [], "unparseable feed"
    items = []
    for entry in parsed.entries[:25]:
        # SMA-694: clean titles too — previously only summaries were
        # cleaned, which is how raw <a href> HTML reached the site.
        title = clean_title(entry.get("title") or "")
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        summary = clean_summary(
            entry.get("summary") or entry.get("description") or "", title=title
        )
        items.append(
            {
                "title": title,
                "summary": summary,
                "url": link,
                "published_at": _published_iso(entry),
            }
        )
    time.sleep(1)  # be polite to publishers
    return items, None


def crawl_all(continents=None):
    """Crawl every unique feed, attribute items to subscribed countries.

    SMA-632: `continents` (an iterable of continent slugs) restricts the
    crawl to feeds whose subscribers belong to those continents, so the
    scheduler can stagger one continent per hour instead of bursting all
    six at once. No feed in sources.yaml serves more than one continent
    (verified 2026-10-19: 0 of 235 feeds are multi-continent), so a
    filtered crawl fetches each feed exactly as often as a full crawl —
    same total load, phases only.
    """
    wanted = set(continents) if continents else None
    feeds = config.iter_feeds()
    if wanted is not None:
        feeds = [
            f for f in feeds
            if any(s["continent"] in wanted for s in f["subscribers"])
        ]
    log.info("starting crawl of %d unique feeds (continents=%s)",
             len(feeds), sorted(wanted) if wanted else "all")
    counts = {}
    touched = set()
    for feed in feeds:
        items, error = crawl_feed(feed)
        # SMA-692: record per-feed health (last success, item count, newest
        # entry date) so dead/stale feeds are visible in /api/status instead
        # of silently leaving countries stale.
        newest = max(
            (i["published_at"] for i in items if i.get("published_at")),
            default=None,
        )
        if error is None and not items:
            error = "no usable entries"
        try:
            db.record_feed_health(
                url=feed["url"], name=feed["name"],
                ok=error is None, item_count=len(items),
                newest_entry_at=newest, error=error,
            )
        except Exception:
            log.exception("feed health record failed for %s", feed["url"])
        subs = feed["subscribers"]
        if wanted is not None:
            subs = [s for s in subs if s["continent"] in wanted]
        for sub in subs:
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
    # SMA-713: prune health rows for feeds removed from sources.yaml.
    # Uses the FULL configured URL set — a staggered (continent-filtered)
    # crawl must not delete rows for feeds it simply didn't visit.
    try:
        pruned = db.prune_feed_health({f["url"] for f in config.iter_feeds()})
        if pruned:
            log.info("pruned %d stale feed-health rows", pruned)
    except Exception:
        log.exception("feed health prune failed")
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
