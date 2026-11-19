"""SMA-862: persistent translation cache.

Offline only: TRANSLATION_PROVIDER is forced to the "dev" stub, the real
provider functions are replaced with failing stubs, and the HTTP session is
disabled, so no test can ever spend real translation budget.

Run: python -m unittest discover -s tests
"""
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from app import config, db, i18n

COUNTRY = "France"


def _no_network(*a, **kw):
    raise AssertionError("tests must never call a real translation provider")


class CacheTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = {
            "DATA_DIR": config.DATA_DIR,
            "DB_PATH": db.DB_PATH,
            "TRANSLATION_ENABLED": config.TRANSLATION_ENABLED,
            "TRANSLATION_PROVIDER": config.TRANSLATION_PROVIDER,
            "BUDGET": config.TRANSLATION_MONTHLY_CHAR_BUDGET,
            "PROVIDERS": dict(i18n.PROVIDERS),
            "post": i18n._http.post,
        }
        config.DATA_DIR = self.tmp
        db.DB_PATH = os.path.join(self.tmp, "news.db")
        config.TRANSLATION_ENABLED = True
        config.TRANSLATION_PROVIDER = "dev"
        config.TRANSLATION_MONTHLY_CHAR_BUDGET = 2_000_000
        i18n._backoff_until = 0.0
        i18n._http.post = _no_network
        self.calls = []  # one entry per provider request: list of texts

        def counting_dev(texts, lang):
            self.calls.append(list(texts))
            return self._saved["PROVIDERS"]["dev"](texts, lang)

        i18n.PROVIDERS.update(azure=_no_network, google=_no_network, dev=counting_dev)
        db.init_db()

    def tearDown(self):
        config.DATA_DIR = self._saved["DATA_DIR"]
        db.DB_PATH = self._saved["DB_PATH"]
        config.TRANSLATION_ENABLED = self._saved["TRANSLATION_ENABLED"]
        config.TRANSLATION_PROVIDER = self._saved["TRANSLATION_PROVIDER"]
        config.TRANSLATION_MONTHLY_CHAR_BUDGET = self._saved["BUDGET"]
        i18n.PROVIDERS.clear()
        i18n.PROVIDERS.update(self._saved["PROVIDERS"])
        i18n._http.post = self._saved["post"]
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers
    def add(self, title, url, source="Le Monde"):
        db.upsert_headline("europe", "western-europe", COUNTRY, title, "",
                           url, source, datetime.now(timezone.utc).isoformat())

    def view(self, lang="en"):
        items = db.get_headlines("country", COUNTRY, limit=50)
        return {it["url"]: it for it in i18n.localize(items, lang)}

    def usage(self):
        return db.get_translation_usage(i18n._month())


class PrunedHeadlineTest(CacheTestBase):
    def test_pruned_headline_translation_is_reused_with_zero_provider_calls(self):
        old_url = "https://lemonde.fr/a/1"
        self.add("Grève générale à Paris ce jeudi", old_url)
        first = self.view()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(first[old_url]["title_translated"],
                         "[en] Grève générale à Paris ce jeudi")
        chars_after_first = self.usage()["chars"]

        # The crawl pushes the story out: newer headline, prune to 1 row,
        # then the age-only translation eviction the crawler runs.
        self.add("Élections municipales: résultats", "https://lemonde.fr/a/2")
        db.prune_country(COUNTRY, keep=1)
        db.prune_translations()
        urls = [it["url"] for it in db.get_headlines("country", COUNTRY)]
        self.assertNotIn(old_url, urls)
        self.assertEqual(len(db.get_translations(
            [db.title_hash("Grève générale à Paris ce jeudi")], "en")), 1,
            "pruning a headline must not delete its translation")

        # The feed re-surfaces the pruned story; only the genuinely new
        # headline (a/2) may reach the provider.
        self.calls.clear()
        self.add("Grève générale à Paris ce jeudi", old_url)
        again = self.view()
        self.assertEqual(again[old_url]["title_translated"],
                         "[en] Grève générale à Paris ce jeudi")
        sent = [t for call in self.calls for t in call]
        self.assertNotIn("Grève générale à Paris ce jeudi", sent)
        self.assertEqual(self.usage()["chars"] - chars_after_first,
                         len("Élections municipales: résultats"))

    def test_ttl_eviction_is_age_only(self):
        self.add("Grève générale à Paris", "https://lemonde.fr/a/1")
        self.view()
        conn = sqlite3.connect(db.DB_PATH)
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        conn.execute("UPDATE headline_translations SET created_at = ?", (old,))
        conn.commit()
        conn.close()
        self.assertEqual(db.prune_translations(), 1)


class RetitleTest(CacheTestBase):
    def test_retitled_same_url_story_reuses_cache(self):
        url = "https://lemonde.fr/a/42"
        self.add("Grève générale à Paris ce jeudi", url)
        self.view()
        self.assertEqual(len(self.calls), 1)
        db.prune_country(COUNTRY, keep=0)

        # Re-surfaces with an edge-only edit and tracking params on the URL.
        self.calls.clear()
        self.add("DIRECT - Grève générale à Paris ce jeudi", url + "?utm_source=rss")
        out = self.view()
        self.assertEqual(self.calls, [])
        self.assertEqual(out[url]["title"], "DIRECT - Grève générale à Paris ce jeudi")
        self.assertEqual(out[url]["title_translated"],
                         "[en] Grève générale à Paris ce jeudi")

    def test_material_retitle_is_retranslated(self):
        url = "https://lemonde.fr/a/43"
        self.add("Séisme: 3 morts dans le sud", url)
        self.view()
        db.prune_country(COUNTRY, keep=0)
        self.calls.clear()
        self.add("Séisme: 12 morts dans le sud", url)
        out = self.view()
        self.assertEqual(self.calls, [["Séisme: 12 morts dans le sud"]])
        self.assertEqual(out[url]["title_translated"], "[en] Séisme: 12 morts dans le sud")

    def test_same_language_retitle_shows_current_title(self):
        url = "https://bbc.co.uk/news/1"
        self.add("Strike shuts Paris metro", url, source="BBC")
        self.view("en")  # dev stub detects ASCII as English: cached as-is
        db.prune_country(COUNTRY, keep=0)
        self.calls.clear()
        self.add("LIVE: Strike shuts Paris metro", url, source="BBC")
        out = self.view("en")
        self.assertEqual(self.calls, [])
        self.assertNotIn("title_translated", out[url])

    def test_rule(self):
        m = i18n.is_material_retitle
        n = i18n.normalize_title
        self.assertFalse(m(n("Strike shuts Paris metro"), n("Strike shuts Paris Metro!")))
        self.assertFalse(m(n("Strike shuts Paris metro today"),
                           n("UPDATE: Strike shuts Paris metro today")))
        self.assertFalse(m(n("Strike shuts the Paris metro - BBC News"),
                           n("Strike shuts the Paris metro")))
        self.assertTrue(m(n("Minister will resign"), n("Minister will not resign")))
        self.assertTrue(m(n("3 dead in quake"), n("12 dead in quake")))
        self.assertTrue(m(n("Minister resigns"), n("Minister resigns amid bribery scandal")))
        self.assertTrue(m("", n("Anything")))


class RepeatViewTest(CacheTestBase):
    def test_repeat_views_make_zero_provider_calls(self):
        for i in range(5):
            self.add("Titre numéro %d en français" % i, "https://lemonde.fr/r/%d" % i)
        self.view()
        self.assertEqual(len(self.calls), 1)
        usage = self.usage()
        self.calls.clear()
        for _ in range(10):
            out = self.view()
            self.assertTrue(all("title_translated" in it for it in out.values()))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.usage(), usage)

    def test_title_known_in_reader_language_skips_provider(self):
        # Translated into French once (detected English), then an English
        # reader asks: already known to be English, no provider call.
        self.add("Strike shuts Paris metro", "https://bbc.co.uk/news/2", source="BBC")
        self.view("fr")
        self.calls.clear()
        out = self.view("en")
        self.assertEqual(self.calls, [])
        self.assertNotIn("title_translated", out["https://bbc.co.uk/news/2"])


class CeilingTest(CacheTestBase):
    def test_ceiling_still_caps_spend(self):
        titles = ["Titre français numéro %02d" % i for i in range(6)]
        size = len(titles[0])
        for i, t in enumerate(titles):
            self.add(t, "https://lemonde.fr/c/%d" % i)
        config.TRANSLATION_MONTHLY_CHAR_BUDGET = 2 * size + size // 2  # room for 2
        out = self.view()
        self.assertEqual(self.usage()["chars"], 2 * size)
        self.assertEqual(sum("title_translated" in it for it in out.values()), 2)
        # At the ceiling nothing more is sent, however often it is viewed.
        self.calls.clear()
        self.view()
        self.view()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.usage()["chars"], 2 * size)
        self.assertLessEqual(self.usage()["chars"], config.TRANSLATION_MONTHLY_CHAR_BUDGET)


class MigrationTest(CacheTestBase):
    def test_existing_cache_is_preserved_and_backfilled(self):
        # Simulate a pre-SMA-862 cache: old schema, one row whose headline
        # still exists and one whose headline was already pruned.
        os.remove(db.DB_PATH)
        conn = sqlite3.connect(db.DB_PATH)
        conn.executescript(db.TABLE_SCHEMA + db.INDEXES)
        conn.execute("""CREATE TABLE headline_translations (
            title_hash TEXT NOT NULL, lang TEXT NOT NULL, translated TEXT NOT NULL,
            source_lang TEXT, created_at TEXT NOT NULL,
            PRIMARY KEY (title_hash, lang))""")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO headlines (continent, region, country, title, summary, url,"
            " source, published_at, fetched_at, title_norm) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("europe", "western-europe", COUNTRY, "Grève à Paris", "",
             "https://lemonde.fr/m/1", "Le Monde", now, now, "grève à paris"))
        conn.executemany(
            "INSERT INTO headline_translations VALUES (?,?,?,?,?)",
            [(db.title_hash("Grève à Paris"), "en", "Strike in Paris", "fr", now),
             (db.title_hash("Pruned story"), "en", "Pruned translated", "fr", now)])
        conn.commit()
        conn.close()

        db.init_db()
        self.assertEqual(len(db.get_translations(
            [db.title_hash("Grève à Paris"), db.title_hash("Pruned story")], "en")), 2)
        by_url = db.get_translations_by_url(["https://lemonde.fr/m/1"], "en")
        self.assertEqual(by_url["https://lemonde.fr/m/1"][0][:2],
                         ("grève à paris", "Strike in Paris"))
        out = self.view()
        self.assertEqual(out["https://lemonde.fr/m/1"]["title_translated"], "Strike in Paris")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
