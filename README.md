# Global News Map

A public web service that shows top news headlines per world region on an
interactive world map. Self-contained: the map is rendered from a **bundled
Natural Earth GeoJSON** with **bundled D3.js** — there are no external map
tile servers or runtime CDN dependencies, so the map can never go blank
because a third-party tile layer failed.

## Links

| | |
| --- | --- |
| 🌍 Live site | http://136.69.140.76 |
| 📊 Google Analytics | [analytics.google.com](https://analytics.google.com/) — property **Global News Map** (`G-E1LGTHLXZ0`) |
| 💻 GitHub repo | [spuffy-stl/global-news-map](https://github.com/spuffy-stl/global-news-map) |

## Built with

- **Backend** — [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/), [APScheduler](https://apscheduler.readthedocs.io/) (hourly crawl), [feedparser](https://feedparser.readthedocs.io/) (RSS parsing)
- **Map** — [D3.js](https://d3js.org/) v7.9.0 (vendored) + [Natural Earth](https://www.naturalearthdata.com/) 110m admin-0 GeoJSON (vendored)
- **Analytics** — [Google Analytics 4](https://analytics.google.com/) via `gtag.js` (server-injected only when `GA_MEASUREMENT_ID` is set); daily reporting via the [Analytics Data API](https://developers.google.com/analytics/devguides/reporting/data/v1) — `analytics/ga_report.py` ([google-auth](https://github.com/googleapis/google-auth-library-python), GCP service account with Viewer access on the property)
- **Infra** — [Docker](https://www.docker.com/), [Google Cloud](https://cloud.google.com/) (e2-micro VM, static IP), [GitHub Actions](https://github.com/features/actions) (auto-deploy on push to `main`)

## News sources (public RSS feeds)

| Region | Feeds |
| ------ | ----- |
| North America | [NPR](https://www.npr.org/), [CBC](https://www.cbc.ca/) |
| Latin America | [BBC Latin America](https://www.bbc.com/news/world/latin_america), [France 24 Americas](https://www.france24.com/en/americas/) |
| Europe | [BBC Europe](https://www.bbc.com/news/world/europe), [DW Europe](https://www.dw.com/en/europe/s-1433) |
| Africa | [BBC Africa](https://www.bbc.com/news/world/africa), [France 24 Africa](https://www.france24.com/en/africa/) |
| Middle East | [BBC Middle East](https://www.bbc.com/news/world/middle_east), [Al Jazeera](https://www.aljazeera.com/) |
| Asia-Pacific | [BBC Asia](https://www.bbc.com/news/world/asia), [ABC News Australia](https://www.abc.net.au/news/) |

## How it works

- **Backend** — Python FastAPI serves the single-page frontend and a JSON API.
- **Crawler** — A polite RSS crawler (proper User-Agent, timeouts, 1s pause
  between feeds, per-feed error isolation) fetches top headlines for 6 world
  regions from reputable public RSS feeds (BBC regional desks, NPR, CBC,
  France 24, DW, Al Jazeera, NHK World). It runs once on startup and then
  hourly via APScheduler, and can be triggered manually.
- **Database** — SQLite file (`data/news.db`) with a `headlines` table
  (`region, title, summary, url, source, published_at, fetched_at`).
  Headlines are deduped by URL and pruned to the latest 60 per region.
- **Frontend** — Dark-themed, mobile-friendly map UI. Region markers are
  clickable and open a headlines panel with title, summary, source link and
  timestamp.

## API

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/` | The map UI |
| GET | `/api/regions` | The 6 regions (slug, name, lat, lon) |
| GET | `/api/headlines?region=<slug>&limit=10` | Headlines for a region |
| GET | `/api/status` | Per-region counts, last fetch time, server time |
| POST | `/api/refresh` | Trigger a crawl in the background |

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
# open http://localhost:8000
```

Environment variables:

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `PORT` | `8000` | HTTP port (set automatically by Render/Railway) |
| `DATA_DIR` | `<repo>/data` | Directory for the SQLite database |
| `CRAWL_INTERVAL_HOURS` | `1` | Hours between scheduled crawls |
| `GA_MEASUREMENT_ID` | *(empty)* | Google Analytics 4 measurement ID (e.g. `G-XXXXXXXXXX`). When set, the GA4 `gtag.js` snippet is injected into the page and these events are tracked: `select_region` (with `region`), `click_story` (with `region` and `source`), `refresh_headlines`. When empty, no analytics code is loaded at all. |

## Run with Docker

```bash
docker build -t global-news-map .
docker run -p 8000:8000 -v $(pwd)/data:/srv/data global-news-map
```

## Deploy

### Render

1. Push this repo to GitHub.
2. Render dashboard → **New → Web Service** → select the repo.
3. Runtime: **Docker**. Render sets `PORT` automatically.
4. Add a **persistent disk** mounted at `/srv/data` (free instances have
   ephemeral disks, so without this the headline database resets on each
   deploy/restart).
5. Deploy. The service crawls on startup, so headlines appear within a minute.

### Railway

1. Push this repo to GitHub.
2. Railway → **New Project → Deploy from GitHub repo** → select the repo.
3. Railway sets `PORT` automatically; the Dockerfile is detected.
4. Add a **volume** mounted at `/srv/data` so the SQLite database survives
   restarts/redeploys.
5. Deploy.

## Notes

- No API keys are required; all feeds are public RSS.
- Be a good citizen: the crawler identifies itself, spaces out requests, and
  isolates feed failures so one dead feed can't break a crawl.
- Vendored assets: `app/static/vendor/d3.min.js` (D3 v7.9.0) and
  `app/static/data/countries-110m.geojson` (Natural Earth 110m admin-0).
