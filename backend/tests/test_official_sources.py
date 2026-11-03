"""Evidence expansion from official sources: job-board conversion, source-only dates, snapshot temporal semantics,
and the rule that periods of different populations are never compared."""
import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine import industry, industry_intel, jobs  # noqa: E402


def _fetcher():
    spec = importlib.util.spec_from_file_location("fos", ROOT / "scripts/acquisition/fetch_official_sources.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TERMS = ["india", "bengaluru", "bangalore", "hyderabad", "pune"]


class JobBoardConversion(unittest.TestCase):
    def setUp(self):
        self.f = _fetcher()

    def test_greenhouse_keeps_india_and_source_date_only(self):
        data = {"jobs": [
            {"id": 1, "title": "Backend Engineer", "absolute_url": "https://x/1", "first_published": "2026-08-14T10:00:00-04:00",
             "location": {"name": "Bengaluru, India"}, "content": "&lt;p&gt;Build APIs in &lt;b&gt;Go&lt;/b&gt;&lt;/p&gt;"},
            {"id": 2, "title": "Analyst", "absolute_url": "https://x/2", "location": {"name": "Pune"}, "content": "&lt;p&gt;SQL&lt;/p&gt;"},
            {"id": 3, "title": "AE", "absolute_url": "https://x/3", "first_published": "2026-08-01T00:00:00Z",
             "location": {"name": "Dublin, Ireland"}, "content": "x"},
        ]}
        rows, skipped = self.f.greenhouse_rows("acme", "Acme", data, TERMS)
        self.assertEqual(skipped, 1)
        self.assertEqual([r["posted_date"] for r in rows], ["2026-08-14", ""])  # no first_published -> undated
        self.assertEqual(rows[0]["job_description"], "Build APIs in Go")
        self.assertEqual(rows[0]["company_industry"], "")  # never inferred
        self.assertEqual(rows[0]["seniority"], "")

    def test_lever_uses_created_at_and_country(self):
        data = [
            {"id": "a", "text": "SRE", "hostedUrl": "https://jobs.lever.co/acme/a", "createdAt": 1790573982021, "country": "IN",
             "categories": {"location": "Remote", "commitment": "Full-time"}, "workplaceType": "remote",
             "descriptionPlain": "Run infrastructure.", "lists": [{"text": "Requirements", "content": "<li>Kubernetes</li>"}]},
            {"id": "b", "text": "PM", "hostedUrl": "https://jobs.lever.co/acme/b", "createdAt": 1790573982021,
             "categories": {"location": "London"}, "descriptionPlain": "x"},
        ]
        rows, skipped = self.f.lever_rows("acme", "Acme", data, TERMS)
        self.assertEqual(skipped, 1)
        self.assertEqual(rows[0]["posted_date"], "2026-09-28")
        self.assertIn("Kubernetes", rows[0]["job_description"])
        self.assertEqual(rows[0]["is_remote"], "true")
        self.assertEqual(rows[0]["employment_status"], "Full-time")

    def test_india_term_is_a_whole_word(self):
        self.assertFalse(self.f._india(["Indianapolis, IN"], TERMS))
        self.assertTrue(self.f._india(["Remote - India"], TERMS))

    def test_config_lists_only_official_sources(self):
        cfg = json.loads((ROOT / "data/metadata/official_sources.json").read_text())
        for b in cfg["job_boards"]["boards"]:
            self.assertIn(b["provider"], self.f.API)  # an official ATS read API the script supports
        for d in cfg["peer_documents"]:
            self.assertTrue(d["url"].startswith("https://"))
            self.assertTrue(d["licence_note"])
        self.assertEqual(cfg["job_boards"]["date_semantics"], "OPEN_POSTINGS_SNAPSHOT")


class SnapshotTemporalSemantics(unittest.TestCase):
    def test_csv_postings_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "b.csv"
            with p.open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=["job_title", "url", "posted_date"])
                w.writeheader()
                w.writerow({"job_title": "T", "url": "https://x/1", "posted_date": ""})
            rows = jobs.read_raw_file(str(p))
        self.assertEqual(rows, [{"job_title": "T", "url": "https://x/1", "posted_date": None}])

    def test_snapshot_source_dates_by_snapshot(self):
        src = {"provenance": {"date_semantics": "OPEN_POSTINGS_SNAPSHOT", "collected_on": "2026-10-01"}}
        self.assertEqual(jobs.temporal_date_of(src), "2026-10-01")
        self.assertIsNone(jobs.temporal_date_of({"provenance": {}}))  # supplied files: publication date

    def test_one_snapshot_is_one_period_whatever_the_publication_dates(self):
        postings = [{"posting_uid": f"p{i}", "posted_date": f"2026-0{m}-15", "temporal_date": "2026-10-01",
                     "date_semantics": "OPEN_POSTINGS_SNAPSHOT"} for i, m in enumerate([5, 6, 7, 8, 9] * 20)]
        settings = {"min_periods_for_trend": 2, "min_eligible_postings_per_period": 30, "min_skill_postings_for_trend": 5}
        chosen, ev = industry_intel.evaluate_granularities(postings, settings)
        self.assertIsNone(chosen)
        self.assertEqual(ev["month"]["postings_by_period"], {"2026-10": 100})

    def test_v1_never_compares_periods_of_different_populations(self):
        postings = [{"posting_uid": f"a{i}", "posted_date": "2026-09-22"} for i in range(40)] + \
                   [{"posting_uid": f"b{i}", "posted_date": "2026-08-01", "temporal_date": "2026-10-01"} for i in range(40)]
        pops = ["A"] * 40 + ["B"] * 40
        settings = {"min_periods_for_trend": 2, "min_eligible_postings_per_period": 30, "min_skill_postings_for_trend": 5}
        out = industry.temporal_demand([("sql", "a1")], postings, settings, population_ids=pops)
        self.assertEqual(out["trend_status"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("not compared", out["reason"])


if __name__ == "__main__":
    unittest.main()


class PostingIdentity(unittest.TestCase):
    def test_greenhouse_job_id_in_query_is_the_identity(self):
        a = jobs.posting_identity("https://stripe.com/jobs/search?gh_jid=6209187")
        b = jobs.posting_identity("https://stripe.com/jobs/search?gh_jid=6209188")
        self.assertEqual(a, ("greenhouse", "6209187", "url_external_id"))
        self.assertNotEqual(a, b)  # two jobs on one careers page are two postings

    def test_other_urls_unchanged(self):
        self.assertEqual(jobs.posting_identity("https://jobs.lever.co/acme/0d25-x")[0], "jobs.lever.co")
        self.assertEqual(jobs.posting_identity("https://www.naukri.com/job-listings-a-b-1234567")[0], "naukri")
