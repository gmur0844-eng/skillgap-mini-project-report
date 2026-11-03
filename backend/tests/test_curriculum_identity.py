"""Curriculum identity: versions of one programme are compared as curriculum changes; another programme of the same
institution only as a cross-programme comparison; another institution only as a peer. One rule for uploads and the
pipeline; nothing names an institution or discipline in code."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import identity  # noqa: E402
from app.services import analysis_jobs as aj  # noqa: E402

CBIT_FULL = {"institution": "Chaitanya Bharathi Institute of Technology", "programme": "B.E. Computer Science and Engineering",
             "discipline": "Computer Science and Engineering"}


class Names(unittest.TestCase):
    def test_acronyms_and_expansions(self):
        self.assertTrue(identity.same_name("CBIT", "Chaitanya Bharathi Institute of Technology"))
        self.assertTrue(identity.same_name("cbit", "Chaitanya Bharathi Institute of Technology (CBIT)"))
        self.assertTrue(identity.same_name("AIML", "Artificial Intelligence and Machine Learning"))
        self.assertTrue(identity.same_name("AI & ML", "AIML"))
        self.assertTrue(identity.same_name("AI&DS", "Artificial Intelligence and Data Science"))

    def test_different_names_and_empty_names_never_match(self):
        self.assertFalse(identity.same_name("AIML", "AI & DS"))
        self.assertFalse(identity.same_name("Indian Institute of Technology Kanpur", "Chaitanya Bharathi Institute of Technology"))
        self.assertFalse(identity.same_name("", "CBIT"))
        self.assertFalse(identity.same_name(None, None))


class Relations(unittest.TestCase):
    def test_two_versions_of_one_programme(self):
        r = identity.relation(CBIT_FULL, {"institution": "CBIT", "programme": "BE", "discipline": "Computer Science and Engineering"})
        self.assertEqual(r["relation"], identity.SAME_PROGRAMME)

    def test_degree_words_in_the_title_do_not_make_a_different_programme(self):
        a = {"institution": "X University", "programme": "B.Tech Mechanical Engineering"}
        b = {"institution": "X University", "programme": "BTech Mechanical Engineering"}
        self.assertEqual(identity.relation(a, b)["relation"], identity.SAME_PROGRAMME)

    def test_a_specialisation_is_a_different_programme(self):
        r = identity.relation(CBIT_FULL, {"institution": "CBIT", "programme": "BE", "discipline": "Computer Science and Engineering",
                                          "specialization": "AIML"})
        self.assertEqual(r["relation"], identity.SAME_INSTITUTION_OTHER_PROGRAMME)
        self.assertIn("specialisation", r["reasons"][0])

    def test_different_disciplines_of_one_institution(self):
        r = identity.relation({"institution": "X University", "programme": "B.E. Civil Engineering"},
                              {"institution": "X University", "programme": "B.E. Electrical Engineering"})
        self.assertEqual(r["relation"], identity.SAME_INSTITUTION_OTHER_PROGRAMME)

    def test_different_degree_levels(self):
        r = identity.relation({**CBIT_FULL, "degree_level": "undergraduate"}, {**CBIT_FULL, "degree_level": "postgraduate"})
        self.assertEqual(r["relation"], identity.SAME_INSTITUTION_OTHER_PROGRAMME)

    def test_another_institution_is_a_peer(self):
        r = identity.relation(CBIT_FULL, {"institution": "Indian Institute of Technology Kanpur", "programme": "B.Tech CSE",
                                          "discipline": "Computer Science and Engineering"})
        self.assertEqual(r["relation"], identity.DIFFERENT_INSTITUTION)

    def test_missing_institution_infers_nothing(self):
        self.assertEqual(identity.relation({"institution": "(not institution-specific)"}, CBIT_FULL)["relation"], identity.UNKNOWN)

    def test_uploads_and_pipeline_share_the_rule(self):
        self.assertIs(aj.same_institution, identity.same_institution)
        src = (Path(__file__).resolve().parents[1] / "app/knowledge_engine/pipeline.py").read_text()
        self.assertIn("identity.relation(prev_doc, target_doc)", src)
        self.assertNotIn('prev_doc["institution"] == target_doc["institution"]', src)  # the exact-string rule is gone


class NotApplicableIsNotAFailure(unittest.TestCase):
    """A comparison that does not apply (no earlier version of the programme) must not mark the analysis as needing
    review; only a BLOCKED requirement does."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self._saved = {k: getattr(aj, k) for k in ("REPO", "UPLOAD_DIR", "STAGED_DIR", "CONTEXT_DIR", "JOB_DIR", "MANIFEST", "GOLD")}
        aj.REPO, aj.UPLOAD_DIR, aj.STAGED_DIR = t, t / "u", t / "s"
        aj.CONTEXT_DIR, aj.JOB_DIR, aj.GOLD, aj.MANIFEST = t / "c", t / "g/jobs", t / "g", t / "m.json"
        aj.MANIFEST.write_text(json.dumps({"documents": []}))
        (t / "g").mkdir(parents=True)
        (t / "g/latest_run.json").write_text(json.dumps({"run_id": "0" * 16}))
        self.file = t / "c.pdf"
        self.file.write_bytes(b"%PDF-1.4 x")

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(aj, k, v)
        self.tmp.cleanup()

    def _run(self, gates):
        from app.pipelines.ingestion import outcome as oc
        up = aj.stage_upload(self.file, "TARGET", {"institution": "Inst", "programme": "P"}, {"outcome": oc.SUCCESSFUL_AND_USABLE})
        job, _ = aj.start_job(up["upload_id"], runner=lambda p: {"run_id": "5" * 16, "analytics_gates": gates})
        for _ in range(200):
            j = aj.job(job["job_id"])
            if j["status"] != aj.PENDING:
                return j
            import time
            time.sleep(0.02)
        return aj.job(job["job_id"])

    def test_not_applicable_drift_leaves_the_analysis_ready(self):
        j = self._run({"concept_drift": {"status": "NOT_APPLICABLE", "reasons": ["no earlier curriculum"]},
                       "programme_comparison": {"status": "ALLOWED", "reasons": []}})
        self.assertEqual(j["status"], aj.READY)

    def test_an_upload_analysis_never_replaces_the_published_default_run(self):
        from app.knowledge_engine import pipeline
        seen = {}
        original = pipeline.run
        pipeline.run = lambda **kw: seen.update(kw) or {"run_id": "6" * 16, "analytics_gates": {}}
        try:
            aj._default_runner("manifest.json")
        finally:
            pipeline.run = original
        self.assertIs(seen.get("set_latest"), False)
        src = (Path(__file__).resolve().parents[1] / "app/knowledge_engine/pipeline.py").read_text()
        self.assertIn("if set_latest:", src)

    def test_a_blocked_requirement_still_needs_review(self):
        j = self._run({"industry_gap": {"status": "BLOCKED", "reasons": ["no postings"]}})
        self.assertEqual(j["status"], aj.REVIEW)


if __name__ == "__main__":
    unittest.main()
