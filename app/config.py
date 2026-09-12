"""Configuration: regions, feeds, paths, environment knobs."""
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(PROJECT_ROOT, "data"))

REGIONS = [
    {"slug": "north-america", "name": "North America", "lat": 42.0, "lon": -100.0},
    {"slug": "latin-america", "name": "Latin America", "lat": -15.0, "lon": -62.0},
    {"slug": "europe", "name": "Europe", "lat": 50.0, "lon": 12.0},
    {"slug": "africa", "name": "Africa", "lat": 4.0, "lon": 20.0},
    {"slug": "middle-east", "name": "Middle East", "lat": 26.0, "lon": 44.0},
    {"slug": "asia-pacific", "name": "Asia-Pacific", "lat": 22.0, "lon": 118.0},
]

# 2 reputable RSS feeds per region. No API keys needed.
FEEDS = [
    # North America
    {"region": "north-america", "name": "NPR", "url": "https://feeds.npr.org/1001/rss.xml"},
    {"region": "north-america", "name": "CBC", "url": "https://www.cbc.ca/webfeed/rss/rss-topstories"},
    # Latin America
    {"region": "latin-america", "name": "BBC Latin America", "url": "https://feeds.bbci.co.uk/news/world/latin_america/rss.xml"},
    {"region": "latin-america", "name": "France 24 Americas", "url": "https://www.france24.com/en/americas/rss"},
    # Europe
    {"region": "europe", "name": "BBC Europe", "url": "https://feeds.bbci.co.uk/news/world/europe/rss.xml"},
    {"region": "europe", "name": "DW Europe", "url": "https://rss.dw.com/rdf/rss-en-eu"},
    # Africa
    {"region": "africa", "name": "BBC Africa", "url": "https://feeds.bbci.co.uk/news/world/africa/rss.xml"},
    {"region": "africa", "name": "France 24 Africa", "url": "https://www.france24.com/en/africa/rss"},
    # Middle East
    {"region": "middle-east", "name": "BBC Middle East", "url": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
    {"region": "middle-east", "name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    # Asia-Pacific
    {"region": "asia-pacific", "name": "BBC Asia", "url": "https://feeds.bbci.co.uk/news/world/asia/rss.xml"},
    {"region": "asia-pacific", "name": "ABC News Australia", "url": "https://www.abc.net.au/news/feed/51120/rss.xml"},
]

CRAWL_INTERVAL_HOURS = int(os.environ.get("CRAWL_INTERVAL_HOURS", "1"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "20"))
USER_AGENT = os.environ.get(
    "USER_AGENT", "GlobalNewsMap/1.0 (world news map aggregator)"
)

# Google Analytics 4 measurement ID, e.g. "G-XXXXXXXXXX".
# When empty, no analytics snippet is injected and the page stays fully self-contained.
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "").strip()
