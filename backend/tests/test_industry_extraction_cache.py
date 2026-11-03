"""
The industry-extraction cache only returns a stored result when every input matches, never fails a run, and can be
switched off. (Identity of cached and uncached runs was proven on the full corpus; see
docs/performance/PERFORMANCE_AUDIT.md section 7.)
"""
import gzip
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine.industry_stage import ExtractionCache  # noqa: E402

IDENTITY = {"code": "c1", "config": "h1", "backend": "tfidf", "taxonomy": ["t1"], "esco_mode": "full",
            "numeric": {"numpy": "1"}}
POSTINGS = [{"posting_uid": "p1", "clean_description": "Python and SQL"}]
TOPICS = [{"topic_uid": "t1", "clean_text": "Databases"}]
RESULT = {"posting_mentions": [{"normalized_text": "python"}], "curriculum_mentions": [], "mappings": {}}


class Cache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"INDUSTRY_EXTRACTION_CACHE": ""})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def cache(self, **identity):
        return ExtractionCache(self.dir, {**IDENTITY, **identity})

    def test_round_trip(self):
        c = self.cache()
        k = c.key(POSTINGS, TOPICS)
        self.assertIsNone(c.load(k))
        self.assertTrue(c.store(k, RESULT))
        self.assertEqual(c.load(k), RESULT)

    def test_every_input_changes_the_key(self):
        base = self.cache().key(POSTINGS, TOPICS)
        variants = [
            self.cache().key([{**POSTINGS[0], "clean_description": "Java"}], TOPICS),
            self.cache().key(POSTINGS, [{**TOPICS[0], "clean_text": "Networks"}]),
            self.cache().key(POSTINGS + POSTINGS, TOPICS),
        ] + [self.cache(**{field: "changed"}).key(POSTINGS, TOPICS) for field in IDENTITY]
        self.assertNotIn(base, variants)
        self.assertEqual(len(set(variants)), len(variants))

    def test_corrupt_or_foreign_entries_are_misses(self):
        c = self.cache()
        k = c.key(POSTINGS, TOPICS)
        (self.dir / f"{k}.json.gz").write_bytes(b"not gzip")
        self.assertIsNone(c.load(k))
        with gzip.open(self.dir / f"{k}.json.gz", "wt") as fh:
            fh.write('{"version": "industry-extraction-v0", "key": "%s", "result": {}}' % k)
        self.assertIsNone(c.load(k))
        with gzip.open(self.dir / f"{k}.json.gz", "wt") as fh:
            fh.write('{"version": "%s", "key": "other", "result": {}}' % ExtractionCache.VERSION)
        self.assertIsNone(c.load(k))

    def test_switched_off(self):
        with mock.patch.dict(os.environ, {"INDUSTRY_EXTRACTION_CACHE": "off"}):
            c = self.cache()
        k = c.key(POSTINGS, TOPICS)
        self.assertFalse(c.enabled)
        self.assertFalse(c.store(k, RESULT))
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_unwritable_directory_does_not_fail(self):
        blocker = self.dir / "file"
        blocker.write_text("x")
        c = ExtractionCache(blocker / "sub", IDENTITY)
        k = c.key(POSTINGS, TOPICS)
        self.assertFalse(c.store(k, RESULT))
        self.assertIsNone(c.load(k))


if __name__ == "__main__":
    unittest.main()
