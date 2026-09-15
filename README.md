# Global News Map

A public web service that shows top news headlines per world region on an
interactive world map. Self-contained: the map is rendered from a **bundled
Natural Earth GeoJSON** with **bundled D3.js** — there are no external map
tile servers or runtime CDN dependencies, so the map can never go blank
because a third-party tile layer failed.

## Links

| | |
| --- | --- |
| 🌍 Live site | https://globalnewsmap.net |
| 📊 Google Analytics | [analytics.google.com](https://analytics.google.com/) — property **Global News Map** (`G-E1LGTHLXZ0`) |
| 💻 GitHub repo | [spuffy-stl/global-news-map](https://github.com/spuffy-stl/global-news-map) |

## Built with

- **Backend** — [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/), [APScheduler](https://apscheduler.readthedocs.io/) (daily crawl), [feedparser](https://feedparser.readthedocs.io/) (RSS parsing), [PyYAML](https://pyyaml.org/) (source taxonomy)
- **Map** — [D3.js](https://d3js.org/) v7.9.0 (vendored) + [Natural Earth](https://www.naturalearthdata.com/) 110m admin-0 GeoJSON (vendored)
- **Analytics** — [Google Analytics 4](https://analytics.google.com/) via `gtag.js` (server-injected only when `GA_MEASUREMENT_ID` is set); daily reporting via the [Analytics Data API](https://developers.google.com/analytics/devguides/reporting/data/v1) — `analytics/ga_report.py` ([google-auth](https://github.com/googleapis/google-auth-library-python), GCP service account with Viewer access on the property)
- **Infra** — [Docker](https://www.docker.com/), [Google Cloud](https://cloud.google.com/) (e2-micro VM, static IP), [GitHub Actions](https://github.com/features/actions) (auto-deploy on push to `main`)
- **Domain & TLS** — [Cloudflare](https://www.cloudflare.com/) (Registrar for `globalnewsmap.net`, DNS, CDN/proxy, Universal SSL edge cert), [Caddy](https://caddyserver.com/) on the VM (reverse proxy, automatic [Let's Encrypt](https://letsencrypt.org/) certs with auto-renewal)

## News sources (local RSS feeds per country)

News comes from **local outlets** — sources based in and read in each country
(English preferred; major national press in the local language where that is
what locals read). The full taxonomy lives in
[`app/sources.yaml`](app/sources.yaml):

```yaml
continents:
  - slug: europe
    name: Europe
    lat: 50
    lon: 15
    regions:
      - slug: nordics
        name: Nordics
        countries:
          - name: Sweden          # MUST match the GeoJSON ADMIN name
            sources:
              - name: The Local Sweden
                url: https://feeds.thelocal.com/rss/builder/se
```

- **Hierarchy** — continent → region → country → sources (141 countries,
  ~230 validated local feeds as of 2026-09-13).
- **Country `name`** must match the `ADMIN` property in the vendored Natural
  Earth GeoJSON; `label` gives a shorter display name.
- **Validation** — every URL is checked before it ships:
  `python scripts/validate_feeds.py` fetches each unique feed, requires
  HTTP 200 + a parseable RSS/Atom feed with ≥ 3 usable entries, and reports
  per-country coverage. Countries with no working local feed ship with an
  empty source list and are filled in by the daily growth loop.

## How it works

- **Backend** — Python FastAPI serves the single-page frontend and a JSON API.
- **Crawler** — A polite RSS crawler (proper User-Agent, timeouts, 1s pause
  between feeds, per-feed error isolation) fetches each unique feed URL once
  per run and attributes headlines to every subscribed country. It runs once
  on startup and then daily at 13:00 UTC via APScheduler, and can be
  triggered manually.
- **Database** — SQLite file (`data/news.db`) with a `headlines` table
  (`continent, region, country, title, summary, url, source, published_at,
  fetched_at`). Headlines are deduped by URL and pruned to the latest 100
  per country.
- **Frontend** — Dark-themed, mobile-friendly map UI. Zoom out for 6
  continent markers; zoom in for ~26 region markers; zoom further for
  country markers sized by story count. Clicking any marker opens a headlines
  panel with title, summary, source link and timestamp; country panels also
  list that country's news sources.

## API

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/` | The map UI |
| GET | `/api/hierarchy` | Continent → region → country taxonomy with map positions, story counts, sources |
| GET | `/api/top-headlines?limit=15` | Freshest headlines across all continents (world view) |
| GET | `/api/headlines?continent=<slug>&limit=15` | Headlines for a continent |
| GET | `/api/headlines?region=<slug>&limit=15` | Headlines for a region |
| GET | `/api/headlines?country=<ADMIN name>&limit=15` | Headlines for a country |
| GET | `/api/status` | Per-continent counts, last fetch time, server time |
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
| `CRAWL_HOUR_UTC` / `CRAWL_MINUTE_UTC` | `13` / `0` | Daily crawl time in UTC |
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
- Static assets are served with a 4-hour cache. The index handler versions
  the `app.js` script URL from the file's mtime at server startup
  (`?v=<mtime>`), so every deploy produces a fresh URL and browsers pick up
  new JS without needing a hard refresh.
