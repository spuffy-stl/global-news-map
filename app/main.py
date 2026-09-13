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

REGION_SLUGS = {r["slug"] for r in config.REGIONS}


def run_crawl():
    try:
        crawler.crawl_all_regions()
    except Exception:
        log.exception("crawl failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    scheduler.add_job(
        run_crawl, "interval", hours=config.CRAWL_INTERVAL_HOURS,
        id="hourly_crawl", replace_existing=True, max_instances=1,
    )
    # Crawl once on startup so the map has headlines immediately.
    scheduler.add_job(
        run_crawl, "date", run_date=datetime.now(timezone.utc),
        id="startup_crawl", replace_existing=True, max_instances=1,
    )
    scheduler.start()
    log.info("scheduler started; crawl interval %sh", config.CRAWL_INTERVAL_HOURS)
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


@app.get("/api/regions")
def list_regions():
    return config.REGIONS


@app.get("/api/headlines")
def get_headlines(region: str = Query(...), limit: int = Query(10, ge=1, le=50)):
    if region not in REGION_SLUGS:
        raise HTTPException(status_code=404, detail="unknown region")
    return db.get_headlines(region, limit)


@app.get("/api/status")
def get_status():
    return {
        "regions": db.get_status(),
        "crawl_interval_hours": config.CRAWL_INTERVAL_HOURS,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/refresh")
def trigger_refresh(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_crawl)
    return {"status": "refresh started"}
