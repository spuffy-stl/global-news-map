"""FastAPI app: serves the map UI and the headlines JSON API."""
import html
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, crawler, db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("global-news-map")

scheduler = AsyncIOScheduler(timezone="UTC")

CONTINENT_SLUGS = {c["slug"] for c in config.CONTINENTS}


def run_crawl():
    try:
        crawler.crawl_all()
    except Exception:
        log.exception("crawl failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    # Purge rows from retired taxonomy versions (e.g. pre-hierarchy
    # 'latin-america' rows left by the SMA-360 rebuild) so /api/status
    # only reports live continents. crawl_all() repeats this after each crawl.
    purged = db.purge_unknown_continents(CONTINENT_SLUGS)
    if purged:
        log.info("startup purge removed %d headlines with retired continent slugs", purged)
    # Daily crawl: fresh headlines every morning for the user (06:00 PDT).
    scheduler.add_job(
        run_crawl, "cron",
        hour=config.CRAWL_HOUR_UTC, minute=config.CRAWL_MINUTE_UTC,
        id="daily_crawl", replace_existing=True, max_instances=1,
    )
    # Crawl once on startup so the map has headlines immediately.
    scheduler.add_job(
        run_crawl, "date", run_date=datetime.now(timezone.utc),
        id="startup_crawl", replace_existing=True, max_instances=1,
    )
    scheduler.start()
    log.info(
        "scheduler started; daily crawl at %02d:%02d UTC",
        config.CRAWL_HOUR_UTC, config.CRAWL_MINUTE_UTC,
    )
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Global News Map", lifespan=lifespan)

STATIC_DIR = os.path.join(config.APP_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
    INDEX_HTML = f.read()

# Cache-buster: version the app.js/style.css URLs from their mtimes at startup.
# FastAPI StaticFiles serves static assets with a 4h Cache-Control, so without
# versioned URLs browsers keep stale pre-deploy bundles (broke zoom on
# SMA-353, would break styling on SMA-354). Each deploy restarts the
# container -> new mtime -> new URL -> fresh fetch.
def _asset_version(name):
    return str(int(os.path.getmtime(os.path.join(STATIC_DIR, name))))

APP_JS_TAG = 'src="/static/app.js"'
APP_JS_TAG_VERSIONED = 'src="/static/app.js?v=' + _asset_version("app.js") + '"'
STYLE_TAG = 'href="/static/style.css"'
STYLE_TAG_VERSIONED = 'href="/static/style.css?v=' + _asset_version("style.css") + '"'

GA4_PLACEHOLDER = "<!--GA4-->"


def ga4_snippet(measurement_id):
    """Google tag (gtag.js) snippet. Only loaded when a measurement ID is set."""
    return (
        '<script async src="https://www.googletagmanager.com/gtag/js?id='
        + measurement_id
        + '"></script>\n'
        '<script>\n'
        "window.dataLayer = window.dataLayer || [];\n"
        "function gtag(){dataLayer.push(arguments);}\n"
        "gtag('js', new Date());\n"
        "gtag('config', '" + measurement_id + "');\n"
        "</script>"
    )


@app.get("/")
def index():
    # Inject the GA4 snippet only when a measurement ID is configured;
    # otherwise the page loads with zero third-party requests.
    html = INDEX_HTML.replace(
        GA4_PLACEHOLDER,
        ga4_snippet(config.GA_MEASUREMENT_ID) if config.GA_MEASUREMENT_ID else "",
    ).replace(APP_JS_TAG, APP_JS_TAG_VERSIONED).replace(STYLE_TAG, STYLE_TAG_VERSIONED)
    return HTMLResponse(html)


@app.get("/sitemap.xml")
def sitemap():
    """Sitemap for crawlers (SMA-394). Google auto-discovers /sitemap.xml;
    the live /robots.txt is served by Cloudflare's content-signals feature,
    so we cannot append a Sitemap: line there."""
    st = db.get_status()
    lastmod = st.get("last_fetched") or datetime.now(timezone.utc).isoformat()
    base = "https://globalnewsmap.net"
    urls = "".join(
        f'  <url><loc>{base}{path}</loc><lastmod>{lastmod}</lastmod></url>\n'
        for path in ("/", "/top")
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + urls
        + "</urlset>"
    )
    return Response(content=xml, media_type="application/xml")


@app.get("/top")
def top_stories():
    """Server-rendered list of today's top headlines (SMA-394): crawlable
    without JavaScript, for SEO and for readers who just want the list."""
    items = db.get_top_headlines(50)
    cards = []
    for it in items:
        title = html.escape(it.get("title") or "")
        url = html.escape(it.get("url") or "#", quote=True)
        source = html.escape(it.get("source") or "")
        country = html.escape(it.get("country") or "")
        when = html.escape(it.get("published_at") or it.get("fetched_at") or "")
        summary = html.escape(it.get("summary") or "")
        summary_html = f'<p class="summary">{summary}</p>' if summary else ""
        cards.append(
            f'<article class="story">\n'
            f'  <h2><a href="{url}" target="_blank" rel="noopener">{title}</a></h2>\n'
            f'  <div class="meta">{source} · {country} · {when}</div>\n'
            f"{summary_html}\n"
            f"</article>"
        )
    body = "\n".join(cards) or "<p>No headlines yet — the daily crawl is still running.</p>"
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Top world headlines today — Global News Map</title>
<meta name="description" content="Today's top world headlines from local news outlets across 141 countries, updated daily by the Global News Map.">
<link rel="canonical" href="https://globalnewsmap.net/top">
<style>
body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 0 auto; padding: 24px 16px; color: #1a1a1a; }}
header a {{ color: inherit; text-decoration: none; }}
.story {{ border-bottom: 1px solid #e5e5e5; padding: 12px 0; }}
.story h2 {{ font-size: 1.05rem; margin: 0 0 4px; }}
.story h2 a {{ color: #0b5fff; }}
.meta {{ font-size: 0.8rem; color: #666; }}
.summary {{ font-size: 0.9rem; color: #333; margin: 6px 0 0; }}
footer {{ margin-top: 24px; font-size: 0.8rem; color: #666; }}
</style>
</head>
<body>
<header><h1><a href="/">🌐 Global News Map</a></h1>
<p>Today's top world headlines from local news outlets worldwide. Updated daily.</p></header>
<main>
{body}
</main>
<footer>Headlines belong to their publishers and link out to the original articles.</footer>
</body>
</html>"""
    return HTMLResponse(page)


@app.get("/api/hierarchy")
def get_hierarchy():
    """Continent > region > country taxonomy with map positions and story counts."""
    counts = db.get_country_counts()
    continents = []
    for cont in config.CONTINENTS:
        regions = []
        for region in cont.get("regions", []):
            rpos = config.region_pos(region.get("countries", []))
            countries = []
            for country in region.get("countries", []):
                name = country["name"]
                cpos = config.country_pos(name)
                countries.append(
                    {
                        "name": name,
                        "label": country.get("label") or name,
                        "lat": cpos[1] if cpos else None,
                        "lon": cpos[0] if cpos else None,
                        "stories": counts.get(name, 0),
                        "sources": [s["name"] for s in country.get("sources", []) or []],
                    }
                )
            regions.append(
                {
                    "slug": region["slug"],
                    "name": region["name"],
                    "lat": rpos[1] if rpos else None,
                    "lon": rpos[0] if rpos else None,
                    "countries": countries,
                }
            )
        continents.append(
            {
                "slug": cont["slug"],
                "name": cont["name"],
                "lat": cont["lat"],
                "lon": cont["lon"],
                "regions": regions,
            }
        )
    return {"continents": continents}


@app.get("/api/headlines")
def get_headlines(
    continent: str = Query(None),
    region: str = Query(None),
    country: str = Query(None),
    limit: int = Query(12, ge=1, le=50),
):
    """Headlines at any taxonomy level. `region` also accepts a continent slug
    (backwards compatibility with pre-SMA-360 clients)."""
    if country:
        return db.get_headlines("country", country, limit)
    if region:
        if region in CONTINENT_SLUGS:
            return db.get_headlines("continent", region, limit)
        return db.get_headlines("region", region, limit)
    if continent:
        if continent not in CONTINENT_SLUGS:
            raise HTTPException(status_code=404, detail="unknown continent")
        return db.get_headlines("continent", continent, limit)
    raise HTTPException(status_code=400, detail="pass continent, region or country")


@app.get("/api/top-headlines")
def get_top_headlines(limit: int = Query(15, ge=1, le=50)):
    """Most recent headlines across all continents (world view / first-visit hook)."""
    return db.get_top_headlines(limit)


@app.get("/api/status")
def get_status():
    st = db.get_status()
    return {
        "continents": st["continents"],
        "total_count": st["total_count"],
        "last_fetched": st["last_fetched"],
        "crawl": "daily",
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/refresh")
def trigger_refresh(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_crawl)
    return {"status": "refresh started"}
