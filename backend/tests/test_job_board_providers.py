"""Ashby and SmartRecruiters job boards: India only, the source's own date only, the posting text kept; discovery
reports which candidate boards answer with India postings and adds only those."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TERMS = ["india", "bengaluru", "hyderabad", "pune"]


def _fetcher():
    spec = importlib.util.spec_from_file_location("fos_providers", ROOT / "scripts/acquisition/fetch_official_sources.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fos_providers"] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeFetcher:
    def __init__(self, responses):
        self.responses, self.urls, self.dry = responses, [], False

    def get(self, url, binary=False, timeout=60):
        self.urls.append(url)
        for prefix, body in self.responses.items():
            if url.startswith(prefix):
                if isinstance(body, Exception):
                    raise body
                return body
        raise OSError(f"HTTP 404 for {url}")


class Providers(unittest.TestCase):
    def setUp(self):
        self.f = _fetcher()

    def test_ashby(self):
        data = {"jobs": [
            {"id": "a", "title": "ML Engineer", "location": "Bengaluru", "publishedAt": "2026-10-02T08:00:00Z",
             "isRemote": False, "descriptionPlain": "PyTorch and MLOps", "jobUrl": "https://jobs/a", "isListed": True},
            {"id": "b", "title": "AE", "location": "London", "publishedAt": "2026-10-01T00:00:00Z"},
            {"id": "c", "title": "Hidden", "location": "Pune", "isListed": False},
            {"id": "d", "title": "Data Engineer", "location": "Remote",
             "secondaryLocations": [{"location": "Hyderabad, India"}], "descriptionHtml": "<p>Spark</p>"}]}
        rows, skipped = self.f.ashby_rows("acme", "Acme", data, TERMS)
        self.assertEqual([r["job_title"] for r in rows], ["ML Engineer", "Data Engineer"])
        self.assertEqual(skipped, 1)
        self.assertEqual((rows[0]["posted_date"], rows[1]["posted_date"]), ("2026-10-02", ""))  # never invented
        self.assertEqual(rows[1]["job_description"], "Spark")
        self.assertEqual(rows[0]["is_remote"], "false")

    def test_smartrecruiters_lists_then_reads_each_posting(self):
        base = "https://api.smartrecruiters.com/v1/companies/Acme/postings"
        f = FakeFetcher({
            base + "?country=in": {"totalFound": 2, "content": [
                {"id": "1", "name": "SDE", "releasedDate": "2026-09-30T10:00:00Z",
                 "location": {"city": "Pune", "country": "in", "remote": False}},
                {"id": "2", "name": "Sales", "location": {"city": "Paris", "country": "fr"}}]},
            base + "/1": {"postingUrl": "https://jobs.smartrecruiters.com/Acme/1", "jobAd": {"sections": {
                "jobDescription": {"text": "<p>Java and Docker</p>"}, "qualifications": {"text": "B.E."}}}}})
        rows, skipped, total = self.f.smartrecruiters_rows("Acme", "Acme", f, TERMS)
        self.assertEqual((len(rows), skipped, total), (1, 1, 2))
        self.assertEqual(rows[0]["posted_date"], "2026-09-30")
        self.assertIn("Java and Docker", rows[0]["job_description"])
        self.assertNotIn(base + "/2", f.urls)  # no detail request for a posting outside India

    def test_discover_adds_only_boards_with_india_postings(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path, cand = Path(d) / "official.json", Path(d) / "data" / "metadata" / "job_board_candidates.json"
            cand.parent.mkdir(parents=True)
            cfg = {"job_boards": {"boards": [{"provider": "lever", "board": "known", "employer": "K"}],
                                  "india_terms": TERMS}}
            cfg_path.write_text(json.dumps(cfg))
            cand.write_text(json.dumps({"candidates": [
                {"provider": "ashby", "board": "good", "employer": "Good"},
                {"provider": "ashby", "board": "abroad", "employer": "Abroad"},
                {"provider": "greenhouse", "board": "nope", "employer": "Nope"},
                {"provider": "lever", "board": "known", "employer": "K"}]}))
            f = FakeFetcher({
                "https://api.ashbyhq.com/posting-api/job-board/good": {"jobs": [{"title": "x", "location": "Pune"}]},
                "https://api.ashbyhq.com/posting-api/job-board/abroad": {"jobs": [{"title": "x", "location": "Berlin"}]}})
            with mock.patch.object(self.f, "ROOT", Path(d)), mock.patch.object(self.f, "CONFIG", cfg_path):
                out = self.f.discover(json.loads(cfg_path.read_text()), f, add=True, today="2026-10-21")
            status = {o["board"]: o["status"] for o in out}
            self.assertEqual(status, {"good": "INDIA_POSTINGS", "abroad": "NO_INDIA_POSTINGS", "nope": "NOT_A_BOARD",
                                      "known": "ALREADY_CONFIGURED"})
            boards = json.loads(cfg_path.read_text())["job_boards"]["boards"]
            self.assertEqual([b["board"] for b in boards], ["known", "good"])
            self.assertEqual(boards[1]["verified_on"], "2026-10-21")


if __name__ == "__main__":
    unittest.main()
