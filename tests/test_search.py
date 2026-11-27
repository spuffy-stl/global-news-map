"""SMA-893: headline search falls back to nearest matches instead of a
dead end, for the recorded failed queries ('industry accident(s)',
'solarvest'), while exact matches and failed-search recording stay as-is.

Offline: the handler is called directly against a throwaway SQLite file.

Run: python -m unittest discover -s tests -t .
"""
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

from app import config, db, main


def _add(country, title, summary=""):
    db.upsert_headline("africa", "west-africa", country, title, summary,
                       "https://example.com/" + str(abs(hash(title))), "Example",
                       datetime.now(timezone.utc).isoformat())


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = (config.DATA_DIR, db.DB_PATH)
        config.DATA_DIR = self.tmp
        db.DB_PATH = os.path.join(self.tmp, "news.db")
        db.init_db()
        _add("Chad", "Three injured in a road accident near N'Djamena")
        _add("Ghana", "Cocoa industry braces for lower prices")
        _add("Ghana", "Mining industry welcomes new tax rules")
        _add("Nigeria", "Solar park expansion doubles clean energy capacity")
        _add("Senegal", "Parliament passes the budget")

    def tearDown(self):
        config.DATA_DIR, db.DB_PATH = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _search(self, q):
        return main.search(q, limit=8, lang=None)

    def _titles(self, rows):
        return [r["title"] for r in rows]

    def _failed(self):
        return {f["query"] for f in db.get_failed_searches()}

    def test_exact_match_unchanged(self):
        rows = self._search("road accident")
        self.assertEqual(self._titles(rows), ["Three injured in a road accident near N'Djamena"])
        self.assertNotIn("match", rows[0])
        self.assertEqual(self._failed(), set())

    def test_plural_folds_to_singular(self):
        rows = self._search("road accidents")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("match", rows[0])

    def test_industry_accident_returns_near_matches(self):
        for q in ("industry accident", "industry accidents"):
            rows = self._search(q)
            self.assertTrue(rows, q)
            self.assertTrue(all(r["match"] == "near" for r in rows))
            # The rarer word ('accident': 1 story vs 2 for 'industry') ranks first.
            self.assertIn("accident", rows[0]["title"])
            self.assertEqual(len(rows), 3)
        # Still a dead end for the daily-loop readout.
        self.assertEqual(self._failed(), {"industry accident", "industry accidents"})

    def test_unknown_word_retried_as_prefix(self):
        for q in ("solarvest", "solarve"):
            rows = self._search(q)
            self.assertEqual(self._titles(rows),
                             ["Solar park expansion doubles clean energy capacity"], q)
            self.assertEqual(rows[0]["match"], "near")
        self.assertEqual(self._failed(), {"solarvest", "solarve"})

    def test_nothing_close_stays_empty(self):
        self.assertEqual(self._search("ra;;l"), [])
        self.assertEqual(self._search("zzqx"), [])
        self.assertEqual(self._failed(), {"ra;;l", "zzqx"})


if __name__ == "__main__":
    unittest.main()
