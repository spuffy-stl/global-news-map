"""SMA-866: region-page meta description + country -> region internal link.

Offline: the handlers are called directly against a throwaway SQLite file.

Run: python -m unittest discover -s tests -t .
"""
import os
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

from starlette.requests import Request

from app import config, db, main


def _request(path):
    return Request({"type": "http", "method": "GET", "path": path,
                    "headers": [], "query_string": b""})


class RegionSeoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = (config.DATA_DIR, db.DB_PATH)
        config.DATA_DIR = self.tmp
        db.DB_PATH = os.path.join(self.tmp, "news.db")
        db.init_db()
        db.upsert_headline("americas", "caribbean", "Jamaica", "Kingston headline", "",
                           "https://jamaica-gleaner.com/a/1", "Jamaica Gleaner",
                           datetime.now(timezone.utc).isoformat())

    def tearDown(self):
        config.DATA_DIR, db.DB_PATH = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _html(self, resp):
        self.assertEqual(resp.status_code, 200)
        return resp.body.decode()

    def test_region_description_names_region_and_countries(self):
        page = self._html(main.region_page("caribbean", _request("/region/caribbean")))
        desc = re.search(r'<meta name="description" content="([^"]*)"', page).group(1)
        self.assertEqual(
            desc,
            "Today&#x27;s top Caribbean news from 7 local outlets in Cuba, Haiti, "
            "Dominican Republic, Jamaica and Puerto Rico, updated every 6 hours "
            "by the Global News Map.")
        self.assertIn("<title>Caribbean News — Today&#x27;s Headlines on the News Map</title>", page)

    def test_large_region_description_is_capped(self):
        page = self._html(main.region_page("south-america", _request("/region/south-america")))
        desc = re.search(r'<meta name="description" content="([^"]*)"', page).group(1)
        self.assertIn(" and 6 more countries, updated every 6 hours", desc)

    def test_country_breadcrumb_links_to_its_region(self):
        page = self._html(main.country_page("jamaica", _request("/country/jamaica")))
        self.assertIn('<a class="crumb" href="/region/caribbean">Caribbean</a>', page)
        page = self._html(main.country_page("albania", _request("/country/albania")))
        self.assertIn('<a class="crumb" href="/region/southeast-europe">Southeast Europe</a>', page)


if __name__ == "__main__":
    unittest.main()
