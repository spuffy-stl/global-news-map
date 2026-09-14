"""FastAPI app: serves the map UI and the headlines JSON API."""
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
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
