"""Configuration: source taxonomy (continent > region > country > feeds),
paths, environment knobs. The taxonomy lives in app/sources.yaml."""
import json
import os

import yaml

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(PROJECT_ROOT, "data"))

SOURCES_PATH = os.path.join(APP_DIR, "sources.yaml")
GEOJSON_PATH = os.path.join(APP_DIR, "static", "data", "countries-110m.geojson")


def _load_taxonomy():
    with open(SOURCES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("continents", [])


CONTINENTS = _load_taxonomy()

# ADMIN name -> {continent, region, country} for quick lookup.
_COUNTRY_INDEX = {}
# Feed URL -> {name, url, subscribers: [{continent, region, country, source_name}]}
_FEED_INDEX = {}


def _build_indexes():
    for cont in CONTINENTS:
        for region in cont.get("regions", []):
            for country in region.get("countries", []):
                name = country["name"]
                _COUNTRY_INDEX[name] = {
                    "continent": cont["slug"],
                    "region": region["slug"],
                    "country": name,
                }
                for src in country.get("sources", []) or []:
                    url = src["url"]
                    entry = _FEED_INDEX.setdefault(url, {"name": src["name"], "url": url, "subscribers": []})
                    entry["subscribers"].append(
                        {
                            "continent": cont["slug"],
                            "region": region["slug"],
                            "country": name,
                            "source_name": src["name"],
                        }
                    )


_build_indexes()


def country_location(admin):
    """ADMIN -> (continent_slug, region_slug) or None."""
    return _COUNTRY_INDEX.get(admin)


def iter_countries():
    """Yield (continent, region, country_dict) for every country."""
    for cont in CONTINENTS:
        for region in cont.get("regions", []):
            for country in region.get("countries", []):
                yield cont, region, country


def iter_feeds():
    """Yield each unique feed once: {name, url, subscribers}."""
    return list(_FEED_INDEX.values())


def country_count():
    return len(_COUNTRY_INDEX)


def feed_count():
    return len(_FEED_INDEX)


# --- Map positions -----------------------------------------------------------
# Country positions come from the vendored Natural Earth GeoJSON (LABEL_X/Y,
# falling back to the feature centroid). Region positions are the mean of
# their countries' positions; continents keep hand-picked coordinates.

def _load_positions():
    positions = {}
    try:
        with open(GEOJSON_PATH, encoding="utf-8") as f:
            gj = json.load(f)
    except OSError:
        return positions
    for feat in gj.get("features", []):
        props = feat.get("properties", {})
        admin = props.get("ADMIN")
        if not admin:
            continue
        lon, lat = props.get("LABEL_X"), props.get("LABEL_Y")
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            try:
                # crude centroid: average of first ring's coordinates
                ring = feat["geometry"]["coordinates"][0]
                if feat["geometry"]["type"] == "MultiPolygon":
                    ring = feat["geometry"]["coordinates"][0][0]
                xs = [p[0] for p in ring]
                ys = [p[1] for p in ring]
                lon, lat = sum(xs) / len(xs), sum(ys) / len(ys)
            except Exception:
                continue
        positions[admin] = (lon, lat)
    return positions


_POSITIONS = _load_positions()


def country_pos(admin):
    return _POSITIONS.get(admin)


def region_pos(region_countries):
    pts = [_POSITIONS[c["name"]] for c in region_countries if c["name"] in _POSITIONS]
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


# --- Misc --------------------------------------------------------------------

# Daily crawl time (UTC). 13:00 UTC = 06:00 PDT / 09:00 EDT.
CRAWL_HOUR_UTC = int(os.environ.get("CRAWL_HOUR_UTC", "13"))
CRAWL_MINUTE_UTC = int(os.environ.get("CRAWL_MINUTE_UTC", "0"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "20"))
USER_AGENT = os.environ.get(
    "USER_AGENT", "GlobalNewsMap/1.0 (world news map aggregator)"
)

# Google Analytics 4 measurement ID, e.g. "G-XXXXXXXXXX".
# When empty, no analytics snippet is injected and the page stays fully self-contained.
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "").strip()
