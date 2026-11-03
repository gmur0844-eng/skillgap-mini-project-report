"""
Comparing two stored runs separates curriculum change, industry-evidence change and method change, and says in words
what a difference in results can be attributed to. Fixture runs are synthetic (small run reports written here); one
test reads the two real stored runs, read-only.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import run_comparison as rc  # noqa: E402

DOCS = [
    {"doc_id": "ref", "role": "REFERENCE", "sha256": "r" * 64},
    {"doc_id": "old", "role": "PREVIOUS_VERSION", "sha256": "p" * 64},
    {"doc_id": "new", "role": "TARGET", "sha256": "t" * 64, "institution": "X", "programme": "B.E. CSE"},
]
METHOD = {"pipeline_version": "2.0", "parser_fingerprint": "p1", "code_fingerprint": "c1", "config_hash": "h1",
          "semantic_identity": "s1", "backend_resolution": {"used": "tfidf"}, "discipline_profile": {"id": "cse"}}


def write_run(gold, run_id, docs=DOCS, method=None, inputs_key="k1", files=("a.csv",)):
    d = Path(gold) / run_id
    (d / "industry").mkdir(parents=True)
    (d / "run_report.json").write_text(json.dumps({"generated_at": "2026-10-16", "documents": docs, **(method or METHOD)}))
    (d / "industry/industry_health.json").write_text(json.dumps({"inputs_key": inputs_key}))
    (d / "industry/population_scope.json").write_text(json.dumps({"source_files": [{"source_file": f} for f in files]}))


class Compare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gold = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_identical_inputs_say_results_should_match(self):
        write_run(self.gold, "a" * 16)
        write_run(self.gold, "b" * 16)
        r, err = rc.compare("a" * 16, "b" * 16, self.gold)
        self.assertIsNone(err)
        self.assertFalse(r["curriculum"]["changed"] or r["industry_evidence"]["changed"] or r["method"]["changed"])
        self.assertIn("should be identical", r["attribution"][0])

    def test_only_the_curriculum_changed(self):
        write_run(self.gold, "a" * 16)
        write_run(self.gold, "b" * 16, docs=DOCS[:2] + [{**DOCS[2], "sha256": "u" * 64, "doc_id": "newer"}])
        r, _ = rc.compare("a" * 16, "b" * 16, self.gold)
        self.assertTrue(r["curriculum"]["changed"])
        statuses = {(d["doc_id"], d["status"]) for d in r["curriculum"]["documents"]}
        self.assertIn(("newer", "ADDED"), statuses)
        self.assertIn(("new", "REMOVED"), statuses)
        self.assertTrue(any("come from the curriculum" in s for s in r["attribution"]))

    def test_only_the_industry_evidence_changed(self):
        write_run(self.gold, "a" * 16)
        write_run(self.gold, "b" * 16, inputs_key="k2", files=("a.csv", "b.csv"))
        r, _ = rc.compare("a" * 16, "b" * 16, self.gold)
        self.assertEqual(r["industry_evidence"]["posting_files_added"], ["b.csv"])
        self.assertTrue(any("come from the industry evidence" in s for s in r["attribution"]))

    def test_a_method_change_is_never_attributed_to_the_curriculum(self):
        write_run(self.gold, "a" * 16)
        write_run(self.gold, "b" * 16, docs=DOCS[:2] + [{**DOCS[2], "sha256": "u" * 64}],
                  method={**METHOD, "parser_fingerprint": "p2"})
        r, _ = rc.compare("a" * 16, "b" * 16, self.gold)
        self.assertEqual([m["component"] for m in r["method"]["differences"]], ["parser"])
        text = " ".join(r["attribution"])
        self.assertIn("not only changes in the curriculum", text)
        self.assertNotIn("come from the curriculum", text)

    def test_unknown_or_malformed_runs_are_refused(self):
        write_run(self.gold, "a" * 16)
        self.assertEqual(rc.compare("a" * 16, "f" * 16, self.gold), (None, ("UNKNOWN_RUN", "f" * 16)))
        self.assertEqual(rc.compare("../../etc", "a" * 16, self.gold)[1][0], "UNKNOWN_RUN")


class RealRuns(unittest.TestCase):
    def test_protected_release_and_published_run_differ_only_in_method(self):
        r, err = rc.compare("c066b227857f9eaf", "0534d6e1d06a617f")
        if err:
            raise unittest.SkipTest("the stored runs are not present")
        self.assertFalse(r["curriculum"]["changed"])
        self.assertFalse(r["industry_evidence"]["changed"])
        self.assertTrue(r["method"]["changed"])
        self.assertIn("comes from the method", r["attribution"][0])


if __name__ == "__main__":
    unittest.main()
