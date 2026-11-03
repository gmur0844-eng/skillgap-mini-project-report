"""
Standalone analysis of a previously unseen institution, optional capabilities, live progress and recovery.

  * a new college's curriculum is analysed without a prior curriculum or peer baseline; another institution's
    curriculum is never substituted
  * peers / industry can be left out: their sources leave the analysis context and their gates are NOT_REQUESTED
    (not BLOCKED); a requested capability that is blocked still needs review (unchanged rule)
  * the analysed curriculum failing its own document checks is the review reason, stated in plain words
  * progress phases come from real stage events, in execution order, with no percentages; a client can reconnect at
    any time (the job record is the state); an interrupted job is reported, and can be retried
"""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import pipeline  # noqa: E402
from app.knowledge_engine.observability import RunObserver  # noqa: E402
from app.pipelines.ingestion import outcome as oc  # noqa: E402
from app.services import analysis_jobs as aj  # noqa: E402
from app.services import analysis_progress as ap  # noqa: E402

BASE = {
    "documents": [
        {"doc_id": "aicte", "role": "REFERENCE", "institution": "AICTE", "programme": "Model", "path": "a.pdf",
         "expected_sha256": "a" * 64},
        {"doc_id": "cbit-r22", "role": "PREVIOUS_VERSION", "institution": "Chaitanya Bharathi Institute of Technology",
         "programme": "B.E. CSE", "path": "b.pdf", "expected_sha256": "b" * 64},
        {"doc_id": "cbit-r22a", "role": "TARGET", "institution": "Chaitanya Bharathi Institute of Technology",
         "programme": "B.E. CSE", "path": "c.pdf", "expected_sha256": "c" * 64},
        {"doc_id": "iitk", "role": "PEER", "institution": "IIT Kanpur", "programme": "B.Tech CSE", "path": "d.pdf",
         "expected_sha256": "d" * 64},
    ],
    "requested_peer_sources": [{"name": "nitw", "status": "SUPPLIED"}],
    "industry_sources": [{"path": "jobs.csv"}], "taxonomy_sources": [{"path": "esco.zip"}],
}
NEW_COLLEGE = {"upload_id": "upl-11ead4024c66", "sha256": "1" * 64, "path": "data/raw/curricula/uploads/x/v.pdf",
               "file_name": "01-syllabus-2026-27.pdf", "document_role": "TARGET", "staged_at": "2026-10-11T03:54:00+00:00",
               "metadata": {"institution": "Vasavi College of Engineering", "programme": "B.E. CSE (AIML)",
                            "discipline": "Computer Science and Engineering", "curriculum_version": "R26"}}


class StandaloneManifest(unittest.TestCase):
    def test_new_institution_is_analysed_on_its_own_curriculum(self):
        m, notes = aj.derived_manifest(BASE, NEW_COLLEGE)
        roles = {d["doc_id"]: d["role"] for d in m["documents"]}
        self.assertEqual(roles["upl-11ead4024c66"], "TARGET")
        # another institution's curriculum is never the target or an earlier version of the upload
        self.assertNotIn("cbit-r22a", roles)
        self.assertNotIn("cbit-r22", roles)
        self.assertEqual([d for d, r in roles.items() if r == "TARGET"], ["upl-11ead4024c66"])
        self.assertEqual(roles["iitk"], "PEER")          # peers stay comparison-only
        self.assertNotIn("analysis_scope", m)             # nothing left out: identical behaviour to before
        self.assertTrue(any("not part of this analysis context" in n for n in notes))

    def test_curriculum_only_analysis_leaves_out_peers_and_industry(self):
        m, notes = aj.derived_manifest(BASE, NEW_COLLEGE, {"peers": False, "industry": False})
        self.assertFalse([d for d in m["documents"] if d["role"] == "PEER"])
        self.assertEqual((m["industry_sources"], m["taxonomy_sources"], m["requested_peer_sources"]), ([], [], []))
        self.assertEqual(m["analysis_scope"], {"peers": False, "industry": False})
        self.assertTrue(any("curriculum-only" in n for n in notes))
        self.assertTrue(any("peer comparison was not requested" in n for n in notes))

    def test_options_default_to_included_and_ignore_non_booleans(self):
        self.assertEqual(aj.normalise_options(None), {"peers": True, "industry": True})
        self.assertEqual(aj.normalise_options({"peers": "no", "industry": False}), {"peers": True, "industry": False})

    def test_pipeline_marks_left_out_capabilities_not_requested(self):
        # the gate names each capability owns, and their reasons, are fixed data the pipeline applies
        self.assertEqual(set(pipeline.NOT_REQUESTED_GATES), {"peers", "industry"})
        self.assertIn("peer_benchmark", pipeline.NOT_REQUESTED_GATES["peers"])
        self.assertEqual(set(pipeline.NOT_REQUESTED_GATES["industry"]),
                         {"industry_gap", "industry_demand", "recommendations", "skill_taxonomy"})
        src = (Path(pipeline.__file__)).read_text()
        self.assertIn('{"status": "NOT_REQUESTED", "reasons": [NOT_REQUESTED_REASONS[capability]]}', src)
        # a run without a scope keeps its run id: the scope only enters the id when present
        self.assertIn('if manifest.get("analysis_scope") else []', src)


class _JobDirs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self._saved = {k: getattr(aj, k) for k in ("UPLOAD_DIR", "STAGED_DIR", "CONTEXT_DIR", "JOB_DIR", "MANIFEST", "GOLD", "REPO")}
        aj.REPO, aj.UPLOAD_DIR, aj.STAGED_DIR = t, t / "up", t / "st"
        aj.CONTEXT_DIR, aj.JOB_DIR, aj.MANIFEST, aj.GOLD = t / "ctx", t / "jobs", t / "m.json", t / "g"
        aj.MANIFEST.write_text(json.dumps(BASE))
        (t / "g").mkdir(parents=True)
        (t / "g/latest_run.json").write_text(json.dumps({"run_id": "0" * 16}))
        self.file = t / "v.pdf"
        self.file.write_bytes(b"%PDF-1.4 vasavi")

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(aj, k, v)
        self.tmp.cleanup()

    def stage(self, outcome=oc.SUCCESSFUL_AND_USABLE):
        return aj.stage_upload(self.file, "TARGET", NEW_COLLEGE["metadata"], {"outcome": outcome})

    def wait(self, job_id):
        for _ in range(300):
            j = aj.job(job_id)
            if j and j["status"] != aj.PENDING:
                return j
            time.sleep(0.02)
        self.fail("job did not finish")


class CapabilityStatus(_JobDirs):
    def test_not_requested_capabilities_leave_the_analysis_ready(self):
        up = self.stage()
        seen = {}

        def runner(path):
            seen.update(json.loads(Path(path).read_text()))
            return {"run_id": "7" * 16, "health": {up["upload_id"]: "PASS"}, "analytics_gates": {
                "concept_discovery": {"status": "ALLOWED", "reasons": []},
                "peer_benchmark": {"status": "NOT_REQUESTED", "reasons": ["peer comparison was not requested"]},
                "industry_gap": {"status": "NOT_REQUESTED", "reasons": ["industry evidence was not requested"]}}}
        j = self.wait(aj.start_job(up["upload_id"], runner=runner, options={"peers": False, "industry": False})[0]["job_id"])
        self.assertEqual(j["status"], aj.READY)
        self.assertEqual(j["options"], {"peers": False, "industry": False})
        self.assertEqual(j["capabilities"]["peer_benchmark"]["status"], "NOT_REQUESTED")
        self.assertEqual(seen["analysis_scope"], {"peers": False, "industry": False})
        statuses = {p["id"]: p["status"] for p in j["phases"]}
        self.assertEqual(statuses["peer_comparison"], "NOT_REQUESTED")
        self.assertEqual(statuses["gap_reasoning"], "NOT_REQUESTED")

    def test_a_requested_but_blocked_capability_still_needs_review(self):
        up = self.stage()
        j = self.wait(aj.start_job(up["upload_id"], runner=lambda p: {
            "run_id": "8" * 16, "analytics_gates": {"industry_gap": {"status": "BLOCKED", "reasons": ["no postings"]}}})[0]["job_id"])
        self.assertEqual(j["status"], aj.REVIEW)
        self.assertIn("no postings", j["reason"])

    def test_the_analysed_curriculum_failing_its_checks_is_the_reason(self):
        up = self.stage()
        run = "9" * 16
        (aj.GOLD / run).mkdir(parents=True)
        (aj.GOLD / run / "health.json").write_text(json.dumps({"documents": {up["upload_id"]: {"status": "FAIL", "checks": [
            {"check": "valid_courses", "status": "FAIL", "value": 0, "threshold": 5},
            {"check": "raw_hash_verified", "status": "PASS", "value": "x", "threshold": "x"}]}}}))
        j = self.wait(aj.start_job(up["upload_id"], runner=lambda p: {
            "run_id": run, "health": {up["upload_id"]: "FAIL"},
            "analytics_gates": {"reference_mapping": {"status": "BLOCKED", "reasons": ["needs a healthy TARGET"]}}})[0]["job_id"])
        self.assertEqual(j["status"], aj.REVIEW)
        self.assertEqual(j["review"]["code"], "TARGET_DOCUMENT_FAILED")
        self.assertIn("valid courses 0 (needs 5)", j["reason"])
        self.assertNotIn("raw hash", j["reason"])
        self.assertNotIn("analytics gates blocked", j["reason"])


def _emit(progress, stage, **attrs):
    progress("start", {"stage": stage, **attrs})
    progress("end", {"stage": stage, "status": "OK", "duration_s": 0.1, **attrs})


class Progress(_JobDirs):
    def test_phases_follow_real_stage_events(self):
        up = self.stage()
        gate, snapshots = threading.Event(), []

        def runner(path, progress):
            _emit(progress, "raw.verify", documents=2)
            progress("start", {"stage": "bronze.extract", "doc_id": "aicte"})
            snapshots.append(json.loads(json.dumps(aj.job(job_id))))     # mid-stage: what a client sees
            progress("end", {"stage": "bronze.extract", "doc_id": "aicte", "status": "OK", "duration_s": 1.0, "pages": 214})
            _emit(progress, "silver.structure", doc_id="aicte", valid_courses=40)
            _emit(progress, "health.gate")
            snapshots.append(json.loads(json.dumps(aj.job(job_id))))
            gate.wait(2)
            return {"run_id": "a" * 16, "analytics_gates": {
                "peer_benchmark": {"status": "BLOCKED", "reasons": ["needs at least one healthy PEER curriculum"]}},
                "health": {}}
        job, _ = aj.start_job(up["upload_id"], runner=runner)
        job_id = job["job_id"]
        self.assertTrue(all(p["status"] == "PENDING" for p in job["phases"]))
        for _ in range(200):
            if len(snapshots) == 2:
                break
            time.sleep(0.01)
        mid, later = snapshots
        ex = next(p for p in mid["phases"] if p["id"] == "extraction")
        self.assertEqual(ex["status"], "RUNNING")
        self.assertEqual(ex["steps"][-1]["detail"], "document 1 of 2")
        self.assertEqual(mid["current"]["stage"], "bronze.extract")
        statuses = {p["id"]: p["status"] for p in later["phases"]}
        self.assertEqual(statuses["extraction"], "COMPLETED")             # a later phase started
        self.assertEqual(statuses["curriculum_understanding"], "RUNNING")
        self.assertEqual(statuses["skill_intelligence"], "PENDING")
        self.assertGreater(later["progress_seq"], mid["progress_seq"])
        gate.set()
        j = self.wait(job_id)
        statuses = {p["id"]: p["status"] for p in j["phases"]}
        self.assertEqual(statuses["curriculum_understanding"], "COMPLETED")
        self.assertEqual(statuses["peer_comparison"], "NOT_RUN")
        peer = next(p for p in j["phases"] if p["id"] == "peer_comparison")
        self.assertIn("PEER", peer["reason"])
        self.assertIsNone(j["current"])
        self.assertFalse(any("percent" in k for p in j["phases"] for k in p))  # no invented percentages
        step = next(p for p in j["phases"] if p["id"] == "extraction")["steps"][1]
        self.assertEqual(step["counts"], {"pages": 214})

    def test_a_failing_stage_fails_its_phase_and_the_job(self):
        up = self.stage()

        def runner(path, progress):
            observer = RunObserver(listener=progress)
            with observer.stage("raw.verify"):
                pass
            with observer.stage("bronze.extract", doc_id="x"):
                raise RuntimeError("pdftotext crashed")
        j = self.wait(aj.start_job(up["upload_id"], runner=runner)[0]["job_id"])
        self.assertEqual(j["status"], aj.FAILED)
        ex = next(p for p in j["phases"] if p["id"] == "extraction")
        self.assertEqual(ex["status"], "FAILED")
        self.assertIn("pdftotext crashed", ex["steps"][-1]["error"])
        later = next(p for p in j["phases"] if p["id"] == "finalisation")
        self.assertEqual((later["status"], later["reason"]), ("NOT_RUN", "the analysis stopped before this step"))

    def test_a_final_status_is_never_published_with_a_running_step(self):
        up = self.stage()
        seen, original = [], aj._write

        def recording_write(path, data):
            if "phases" in data:
                seen.append((data["status"], [p["status"] for p in data["phases"]]))
            original(path, data)
        aj._write = recording_write
        try:
            # parent run != new run: the job writes lineage as a step of its own (it fails here: no run folders)
            j = self.wait(aj.start_job(up["upload_id"], runner=lambda p, progress: (
                _emit(progress, "raw.verify", documents=1) or {"run_id": "c" * 16, "analytics_gates": {}}))[0]["job_id"])
        finally:
            aj._write = original
        self.assertEqual(j["status"], aj.READY)
        self.assertIn("lineage_error", j)
        for status, phases in seen:
            if status != aj.PENDING:
                self.assertNotIn("RUNNING", phases)
        lineage = next(p for p in j["phases"] if p["id"] == "finalisation")["steps"][-1]
        self.assertEqual((lineage["stage"], lineage["status"]), ("lineage", "FAILED"))
        self.assertEqual(next(p for p in j["phases"] if p["id"] == "finalisation")["status"], "COMPLETED")

    def test_a_listener_error_never_breaks_the_run(self):
        observer = RunObserver(listener=lambda e, r: 1 / 0)
        with observer.stage("raw.verify") as st:
            st["documents"] = 1
        self.assertEqual(observer.stages[0]["status"], "OK")

    def test_reconnect_and_active_job(self):
        up = self.stage()
        gate = threading.Event()

        def runner(path, progress):
            _emit(progress, "raw.verify", documents=1)
            gate.wait(2)
            return {"run_id": "b" * 16, "analytics_gates": {}}
        job, _ = aj.start_job(up["upload_id"], runner=runner)
        time.sleep(0.1)
        active = aj.active_job()
        self.assertEqual(active["job_id"], job["job_id"])                # a reloaded page finds the running job
        again = aj.job(job["job_id"])
        self.assertEqual(again["status"], aj.PENDING)                     # reading it does not disturb it
        gate.set()
        self.wait(job["job_id"])
        self.assertIsNone(aj.active_job())

    def test_interrupted_job_is_reported_and_can_be_retried(self):
        up = self.stage()
        stale = {"job_id": "job-0123456789ab", "upload_id": up["upload_id"], "status": aj.PENDING, "stage": "analysing",
                 "created_at": "2026-10-11T03:54:03+00:00", "finished_at": None, "run_id": None, "parent_run": None,
                 "reason": None, "options": {"peers": False, "industry": True}, "reviewed_by": None,
                 "phases": ap.initial_phases(), "progress_seq": 3}
        aj._write(aj.JOB_DIR / "job-0123456789ab.json", stale)
        j = aj.job("job-0123456789ab")
        self.assertEqual(j["status"], aj.FAILED)
        self.assertTrue(j["interrupted"])
        self.assertIn("interrupted", j["reason"])
        new, err = aj.retry_job("job-0123456789ab")
        self.assertIsNone(err)
        self.assertEqual((new["retry_of"], new["options"]), ("job-0123456789ab", {"peers": False, "industry": True}))
        self.wait(new["job_id"])
        self.assertEqual(aj.retry_job("job-ffffffffffff")[1], "JOB_NOT_FOUND")


class ApiRoutes(_JobDirs):
    """The job and inspect routes through FastAPI itself (skipped where FastAPI is not installed)."""

    def client(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from app.api.v1 import evidence_api, ingestion
        except ImportError as exc:
            raise unittest.SkipTest(f"FastAPI not available: {exc}") from exc
        app = FastAPI()
        app.include_router(evidence_api.analysis_router)
        app.include_router(ingestion.router)
        return TestClient(app), evidence_api

    def test_events_stream_the_job_until_it_ends_and_active_is_empty_after(self):
        c, api = self.client()
        api.EVENT_POLL_S = 0.01
        up = self.stage()
        job = self.wait(aj.start_job(up["upload_id"], runner=lambda p, progress: (
            _emit(progress, "raw.verify", documents=1) or {"run_id": "d" * 16, "analytics_gates": {}}))[0]["job_id"])
        with c.stream("GET", f"/api/v1/analysis/jobs/{job['job_id']}/events") as r:
            self.assertEqual(r.headers["content-type"].split(";")[0], "text/event-stream")
            body = "".join(r.iter_text())
        frames = [f for f in body.split("\n\n") if f.startswith("id: ")]
        self.assertEqual(len(frames), 1)                       # a finished job: its final state, then the stream ends
        data = json.loads(frames[0].split("data: ", 1)[1])
        self.assertEqual(data["status"], aj.READY)
        self.assertEqual(c.get("/api/v1/analysis/jobs/active").json()["job"], None)

    def test_retry_route_starts_the_same_upload_again(self):
        c, _ = self.client()
        up = self.stage()
        first = self.wait(aj.start_job(up["upload_id"], runner=lambda p: {"run_id": None})[0]["job_id"])  # no run: failed
        self.assertEqual(first["status"], aj.FAILED)
        r = c.post(f"/api/v1/analysis/jobs/{first['job_id']}/retry")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["retry_of"], first["job_id"])
        self.wait(r.json()["job_id"])

    def test_inspect_suggests_without_storing_anything(self):
        c, _ = self.client()
        text = ("JAWAHARLAL NEHRU TECHNOLOGICAL UNIVERSITY HYDERABAD\nB.Tech. in COMPUTER SCIENCE AND ENGINEERING\n"
                "COURSE STRUCTURE & SYLLABUS (R22 Regulations)\nApplicable from AY 2022-23 Batch\n").encode()
        before = sorted(p.name for p in aj.STAGED_DIR.glob("*")) if aj.STAGED_DIR.exists() else []
        r = c.post("/api/v1/ingestion/curriculum/inspect", files={"file": ("syllabus.txt", text, "text/plain")})
        self.assertEqual(r.status_code, 200)
        s = r.json()["suggestions"]
        self.assertEqual(s["curriculum_version"]["value"], "R22")
        self.assertEqual(s["institution"]["value"], "JAWAHARLAL NEHRU TECHNOLOGICAL UNIVERSITY HYDERABAD")
        self.assertEqual(s["academic_year"]["evidence"]["text"], "Applicable from AY 2022-23 Batch")
        after = sorted(p.name for p in aj.STAGED_DIR.glob("*")) if aj.STAGED_DIR.exists() else []
        self.assertEqual(before, after)


class EventStream(unittest.TestCase):
    def test_sse_frames_carry_the_whole_state(self):
        try:
            from app.api.v1 import evidence_api
        except ImportError as exc:  # FastAPI is not installed in every environment
            raise unittest.SkipTest(f"FastAPI not available: {exc}") from exc
        frame = evidence_api._sse({"job_id": "job-x", "status": aj.PENDING, "progress_seq": 4, "phases": [],
                                   "error_detail": "hidden"})
        self.assertTrue(frame.startswith("id: 4\nevent: job\ndata: "))
        self.assertTrue(frame.endswith("\n\n"))
        payload = json.loads(frame.split("data: ", 1)[1])
        self.assertEqual(payload["status"], aj.PENDING)
        self.assertNotIn("error_detail", payload)                      # technical detail stays out of the stream


if __name__ == "__main__":
    unittest.main()
