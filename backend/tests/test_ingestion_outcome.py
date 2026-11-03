"""Ingestion outcome, metadata policy and analysis-job gating: a zero-content extraction can never read as a usable
curriculum, and never reaches downstream intelligence silently."""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.pipelines.ingestion import outcome as oc  # noqa: E402
from app.services import analysis_jobs as aj  # noqa: E402
from app.services import evidence_metadata as em  # noqa: E402

GOOD = {"status": "succeeded", "courses_found": 374, "modules_found": 900, "topics_found": 4942, "outcomes_found": 805,
        "extraction_confidence": 0.86, "flagged_for_review": False}


class CurriculumOutcome(unittest.TestCase):
    def test_successful_and_usable(self):
        o = oc.curriculum_outcome(GOOD)
        self.assertEqual(o["outcome"], oc.SUCCESSFUL_AND_USABLE)
        self.assertTrue(o["usable_for_analysis"])
        self.assertEqual((o["execution_status"], o["extraction_status"], o["review_status"]), ("SUCCEEDED", "EXTRACTED", "NOT_REQUIRED"))
        self.assertEqual(o["headline"], "Successfully extracted — ready for analysis")

    def test_the_reported_case_is_not_success(self):
        # the exact result that was shown as "Succeeded": status succeeded, everything zero, flagged
        o = oc.curriculum_outcome({"status": "succeeded", "courses_found": 0, "modules_found": 0, "topics_found": 0,
                                   "outcomes_found": 0, "extraction_confidence": 0, "flagged_for_review": True})
        self.assertEqual(o["outcome"], oc.NO_USABLE_CONTENT)
        self.assertEqual(o["execution_status"], "SUCCEEDED")          # execution and extraction are separate
        self.assertEqual(o["extraction_status"], "NO_USABLE_CONTENT")
        self.assertEqual(o["review_status"], "NEEDS_REVIEW")
        self.assertFalse(o["usable_for_analysis"])
        self.assertIn("no usable curriculum content", o["headline"])

    def test_zero_courses_or_zero_topics_or_zero_confidence(self):
        for patch in ({"courses_found": 0}, {"topics_found": 0}, {"extraction_confidence": 0.0}):
            o = oc.curriculum_outcome({**GOOD, **patch})
            self.assertEqual(o["outcome"], oc.NO_USABLE_CONTENT, patch)
            self.assertFalse(o["usable_for_analysis"])

    def test_missing_outcomes_or_flag_needs_review(self):
        for patch in ({"outcomes_found": 0}, {"flagged_for_review": True, "extraction_confidence": 0.2}):
            o = oc.curriculum_outcome({**GOOD, **patch})
            self.assertEqual(o["outcome"], oc.NEEDS_REVIEW, patch)
            self.assertEqual(o["extraction_status"], "PARTIAL_EXTRACTION")
            self.assertFalse(o["usable_for_analysis"])
            self.assertTrue(o["reasons"])

    def test_execution_failed(self):
        o = oc.curriculum_outcome({"status": "failed", "reason": "extracted_text_too_short"})
        self.assertEqual(o["outcome"], oc.EXECUTION_FAILED)
        self.assertEqual(o["headline"], "Processing failed — review error details")
        self.assertIn("extracted_text_too_short", o["reasons"][0])

    def test_three_states_never_collapse(self):
        states = {oc.curriculum_outcome(GOOD)["headline"],
                  oc.curriculum_outcome({**GOOD, "courses_found": 0})["headline"],
                  oc.curriculum_outcome({"status": "failed"})["headline"]}
        self.assertEqual(len(states), 3)

    def test_job_postings(self):
        self.assertEqual(oc.job_postings_outcome({"records_accepted": 50})["outcome"], oc.SUCCESSFUL_AND_USABLE)
        self.assertEqual(oc.job_postings_outcome({"records_accepted": 0, "records_rejected": 9})["outcome"], oc.NO_USABLE_CONTENT)
        self.assertEqual(oc.job_postings_outcome({"records_accepted": 5, "records_rejected": 2})["outcome"], oc.NEEDS_REVIEW)


class MetadataPolicy(unittest.TestCase):
    def test_roles_come_from_data(self):
        roles = {r["role"]: r for r in em.document_roles()["roles"]}
        self.assertLessEqual({"TARGET", "PREVIOUS_VERSION", "PEER", "REFERENCE", "GENERAL_REFERENCE"}, set(roles))
        self.assertIn("institution", roles["TARGET"]["required"])
        self.assertNotIn("institution", roles["REFERENCE"]["required"])          # institution-independent reference
        self.assertEqual(roles["GENERAL_REFERENCE"]["required"], ["title"])
        self.assertFalse(roles["GENERAL_REFERENCE"]["analysed_by_curriculum_pipeline"])

    def test_validation(self):
        self.assertEqual(em.validate_metadata("TARGET", {"institution": "X", "programme": "Y", "discipline": "Z",
                                                          "curriculum_version": "R1"}), [])
        self.assertEqual(em.validate_metadata("TARGET", {"institution": " "}),
                         ["institution", "programme", "discipline", "curriculum_version"])
        self.assertEqual(em.validate_metadata("REFERENCE", {"discipline": "Pharmacy", "curriculum_version": "2024"}), [])
        self.assertEqual(em.validate_metadata("NOT_A_ROLE", {}), ["document_role"])

    def test_discipline_is_open_ended(self):
        # no hardcoded branch list: the policy file names no discipline, and any string validates
        text = (ROOT / "data/metadata/document_roles.json").read_text().lower()
        for branch in ("computer science", "mechanical", "civil", "electronics", "pharmacy"):
            self.assertNotIn(branch, text)
        self.assertEqual(em.validate_metadata("REFERENCE", {"discipline": "Agricultural Economics", "curriculum_version": "v"}), [])

    def test_source_wording_never_implies_scraping(self):
        s = em.sources()
        self.assertIn("never means the application may collect", s["note"])
        for src in s["sources"]:
            self.assertIn(src["configuration_status"], ("CONFIGURED", "NOT_CONFIGURED", "DISABLED"))
            self.assertIn("access_method", src)
            self.assertIn("licence", src)


class AnalysisJobs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self._saved = {k: getattr(aj, k) for k in ("REPO", "UPLOAD_DIR", "STAGED_DIR", "CONTEXT_DIR", "JOB_DIR", "MANIFEST", "GOLD")}
        aj.REPO, aj.UPLOAD_DIR, aj.STAGED_DIR = t, t / "data/raw/curricula/uploads", t / "data/metadata/staged_uploads"
        aj.CONTEXT_DIR, aj.JOB_DIR, aj.GOLD = t / "data/metadata/analysis_contexts", t / "gold/jobs", t / "gold"
        aj.MANIFEST = t / "manifest.json"
        aj.MANIFEST.write_text(json.dumps({"documents": [
            {"doc_id": "old-target", "role": "TARGET", "expected_sha256": "a" * 64},
            {"doc_id": "old-prev", "role": "PREVIOUS_VERSION", "expected_sha256": "b" * 64},
            {"doc_id": "ref", "role": "REFERENCE", "expected_sha256": "c" * 64}]}))
        (t / "gold").mkdir(parents=True)
        (t / "gold/latest_run.json").write_text(json.dumps({"run_id": "0" * 16}))
        self.file = t / "cur.pdf"
        self.file.write_bytes(b"%PDF-1.4 a curriculum")

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(aj, k, v)
        self.tmp.cleanup()

    def _stage(self, outcome, role="TARGET"):
        return aj.stage_upload(self.file, role, {"institution": "Inst", "programme": "Prog", "discipline": "Architecture",
                                                 "curriculum_version": "2025"}, {"outcome": outcome})

    def test_derived_manifest_target_replaces_target_and_previous(self):
        up = self._stage(oc.SUCCESSFUL_AND_USABLE)
        m, notes = aj.derived_manifest(json.loads(aj.MANIFEST.read_text()), up)
        roles = {d["doc_id"]: d["role"] for d in m["documents"]}
        self.assertEqual(roles, {"ref": "REFERENCE", up["upload_id"]: "TARGET"})
        self.assertTrue(notes)
        up2 = self._stage(oc.SUCCESSFUL_AND_USABLE, role="PEER")
        m2, _ = aj.derived_manifest(json.loads(aj.MANIFEST.read_text()), up2)
        self.assertEqual(len(m2["documents"]), 4)   # a peer is added, nothing replaced

    def _upload_against(self, earlier_fields, upload_fields):
        base = json.loads(aj.MANIFEST.read_text())
        base["documents"][0].update(earlier_fields)
        up = aj.stage_upload(self.file, "TARGET", {"curriculum_version": "R26", **upload_fields},
                             {"outcome": oc.SUCCESSFUL_AND_USABLE})
        m, notes = aj.derived_manifest(base, up)
        return up, {d["doc_id"]: d["role"] for d in m["documents"]}, notes

    def test_same_programme_upload_measures_changes_against_the_current_curriculum(self):
        up, roles, notes = self._upload_against(
            {"institution": "Chaitanya Bharathi Institute of Technology", "programme": "B.E. Computer Science and Engineering",
             "discipline": "Computer Science and Engineering"},
            {"institution": "CBIT", "programme": "BE", "discipline": "Computer Science and Engineering"})
        self.assertEqual(roles, {"old-target": "PREVIOUS_VERSION", "ref": "REFERENCE", up["upload_id"]: "TARGET"})
        self.assertTrue(any("earlier version of the upload" in n for n in notes))
        self.assertFalse(any("cross-programme" in n for n in notes))

    def test_other_programme_of_the_same_institution_is_a_cross_programme_comparison(self):
        up, roles, notes = self._upload_against(
            {"institution": "Chaitanya Bharathi Institute of Technology", "programme": "B.E. Computer Science and Engineering",
             "discipline": "Computer Science and Engineering"},
            {"institution": "CBIT", "programme": "BE", "discipline": "Computer Science and Engineering",
             "specialization": "AIML"})
        self.assertEqual(roles["old-target"], "PREVIOUS_VERSION")      # the comparison document, by role
        self.assertTrue(any("cross-programme comparison" in n and "not as an earlier version" in n for n in notes))

    def test_another_institution_is_never_an_earlier_version(self):
        up, roles, notes = self._upload_against(
            {"institution": "Indian Institute of Technology Kanpur", "programme": "B.Tech CSE",
             "discipline": "Computer Science and Engineering"},
            {"institution": "CBIT", "programme": "BE", "discipline": "Computer Science and Engineering"})
        self.assertEqual(roles, {"ref": "REFERENCE", up["upload_id"]: "TARGET"})

    def test_institution_names_and_acronyms(self):
        self.assertTrue(aj.same_institution("CBIT", "Chaitanya Bharathi Institute of Technology"))
        self.assertFalse(aj.same_institution("Indian Institute of Technology Kanpur", "Chaitanya Bharathi Institute of Technology"))
        self.assertFalse(aj.same_institution(None, "Chaitanya Bharathi Institute of Technology"))

    def test_project_manifest_is_never_edited(self):
        before = aj.MANIFEST.read_text()
        up = self._stage(oc.SUCCESSFUL_AND_USABLE)
        job, err = aj.start_job(up["upload_id"], runner=lambda p: {"run_id": "1" * 16, "analytics_gates": {}})
        self.assertIsNone(err)
        self._wait(job["job_id"])
        self.assertEqual(aj.MANIFEST.read_text(), before)

    def test_unusable_uploads_are_refused(self):
        up = self._stage(oc.NO_USABLE_CONTENT)
        self.assertEqual(aj.start_job(up["upload_id"])[1], "NOT_ANALYSABLE")
        up = self._stage(oc.NEEDS_REVIEW)
        self.assertEqual(aj.start_job(up["upload_id"])[1], "REVIEW_REQUIRED")
        self.assertEqual(aj.start_job("upl-000000000000")[1], "UPLOAD_NOT_FOUND")

    def _wait(self, job_id):
        for _ in range(200):
            j = aj.job(job_id)
            if j and j["status"] != aj.PENDING:
                return j
            time.sleep(0.02)
        self.fail("job did not finish")

    def test_job_states(self):
        up = self._stage(oc.SUCCESSFUL_AND_USABLE)
        j = self._wait(aj.start_job(up["upload_id"], runner=lambda p: {"run_id": "1" * 16, "analytics_gates": {}})[0]["job_id"])
        self.assertEqual((j["status"], j["run_id"], j["parent_run"]), (aj.READY, "1" * 16, "0" * 16))
        j = self._wait(aj.start_job(up["upload_id"], runner=lambda p: {
            "run_id": "2" * 16, "analytics_gates": {"industry": {"status": "BLOCKED", "reasons": ["no target"]}}})[0]["job_id"])
        self.assertEqual(j["status"], aj.REVIEW)
        self.assertIn("no target", j["reason"])

        def boom(p):
            raise RuntimeError("pipeline broke")
        j = self._wait(aj.start_job(up["upload_id"], runner=boom)[0]["job_id"])
        self.assertEqual(j["status"], aj.FAILED)
        self.assertIn("pipeline broke", j["reason"])

    def test_reviewed_upload_records_the_reviewer(self):
        up = self._stage(oc.NEEDS_REVIEW)
        job, err = aj.start_job(up["upload_id"], reviewed_by="curriculum office",
                                runner=lambda p: {"run_id": "3" * 16, "analytics_gates": {}})
        self.assertIsNone(err)
        self.assertEqual(self._wait(job["job_id"])["reviewed_by"], "curriculum office")

    def test_one_job_at_a_time(self):
        gate = threading.Event()
        up = self._stage(oc.SUCCESSFUL_AND_USABLE)

        def slow(p):
            gate.wait(2)
            return {"run_id": "4" * 16, "analytics_gates": {}}
        job, _ = aj.start_job(up["upload_id"], runner=slow)
        # a second analysis (other options) is refused while one runs; repeating the same submission returns the
        # running job instead of starting another (test_comparison_selection covers the duplicate case in full)
        self.assertEqual(aj.start_job(up["upload_id"], runner=slow, options={"industry": False})[1], "JOB_RUNNING")
        again, err = aj.start_job(up["upload_id"], runner=slow)
        self.assertEqual((again["job_id"], err), (job["job_id"], None))
        gate.set()
        self._wait(job["job_id"])
