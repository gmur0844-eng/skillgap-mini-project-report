"""
Explicit comparison targets and duplicate submissions.

  * a client chooses peers from GET /analysis/comparison-targets; only the chosen peers are compared
  * an unknown peer, or one of another discipline, is refused -- never replaced by another institution
  * an empty selection is a curriculum analysis without peers (NOT_REQUESTED, as with peers: false)
  * submitting the same upload with the same options while its job runs returns that job (no duplicate run)
  * the job records the discipline profile it was analysed under
"""
import json
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import analysis_jobs as aj  # noqa: E402
from tests.test_standalone_analysis import BASE, NEW_COLLEGE, _JobDirs  # noqa: E402

CSE = "Computer Science and Engineering"
WITH_DISCIPLINES = {**BASE, "documents": [
    {**d, "discipline": CSE} for d in BASE["documents"]] + [
    {"doc_id": "mech-peer", "role": "PEER", "institution": "Some College", "programme": "B.Tech Mechanical",
     "discipline": "Mechanical Engineering", "path": "e.pdf", "expected_sha256": "e" * 64}]}


class Options(unittest.TestCase):
    def test_peer_ids_are_normalised(self):
        self.assertEqual(aj.normalise_options({"peer_ids": ["b", "a", "a", " "]}),
                         {"peers": True, "industry": True, "peer_ids": ["a", "b"]})
        self.assertEqual(aj.normalise_options({"peer_ids": []}), {"peers": False, "industry": True})
        self.assertEqual(aj.normalise_options({"peer_ids": "iitk"}), {"peers": True, "industry": True})
        self.assertEqual(aj.normalise_options({"peers": False, "peer_ids": ["iitk"]}), {"peers": False, "industry": True})

    def test_only_selected_peers_enter_the_context(self):
        base = {**WITH_DISCIPLINES, "documents": WITH_DISCIPLINES["documents"] + [
            {"doc_id": "nitw", "role": "PEER", "discipline": CSE, "path": "f.pdf", "expected_sha256": "f" * 64}]}
        m, notes = aj.derived_manifest(base, NEW_COLLEGE, aj.normalise_options({"peer_ids": ["nitw"]}))
        peers = [d["doc_id"] for d in m["documents"] if d["role"] == "PEER"]
        self.assertEqual(peers, ["nitw"])
        self.assertTrue(any("selected peers only (nitw)" in n for n in notes))
        self.assertNotIn("analysis_scope", m)


class Selection(_JobDirs):
    def setUp(self):
        super().setUp()
        aj.MANIFEST.write_text(json.dumps(WITH_DISCIPLINES))

    def test_targets_say_which_peers_are_comparable(self):
        up = self.stage()
        t = aj.comparison_targets(up["upload_id"])
        self.assertEqual(t["upload_discipline_profile"], "cse")
        by = {p["doc_id"]: p for p in t["peers"]}
        self.assertTrue(by["iitk"]["comparable"])
        self.assertFalse(by["mech-peer"]["comparable"])
        self.assertEqual(by["mech-peer"]["reason"], "another discipline")
        self.assertNotIn("comparable", aj.comparison_targets()["peers"][0])  # no upload: just the list
        typed = {p["doc_id"]: p["comparable"] for p in aj.comparison_targets(discipline="Mechanical")["peers"]}
        self.assertEqual(typed, {"iitk": False, "mech-peer": True})  # a discipline typed before uploading
        self.assertEqual(aj.comparison_targets(discipline="Mechanical")["discipline_profile"]["id"], "mech")

    def test_unknown_or_other_discipline_peers_are_refused(self):
        up = self.stage()
        for ids in (["no-such-peer"], ["iitk", "mech-peer"]):
            with self.subTest(ids=ids):
                job, err = aj.start_job(up["upload_id"], runner=lambda p: {"run_id": "a" * 16},
                                        options={"peer_ids": ids})
                self.assertEqual((job, err), (None, "INVALID_PEER_SELECTION"))
        self.assertEqual(aj.peer_selection_problems(up["upload_id"], ["iitk", "mech-peer"]),
                         [("mech-peer", "another discipline")])
        self.assertEqual(aj.jobs(), [])  # nothing was started

    def test_a_valid_selection_runs_and_records_profile_and_choice(self):
        up = self.stage()
        seen = {}

        def runner(path):
            seen["m"] = json.loads(Path(path).read_text())
            return {"run_id": "c" * 16, "analytics_gates": {}}
        job, err = aj.start_job(up["upload_id"], runner=runner, options={"peer_ids": ["iitk"]})
        self.assertIsNone(err)
        done = self.wait(job["job_id"])
        self.assertEqual(done["options"]["peer_ids"], ["iitk"])
        self.assertEqual(done["discipline_profile"]["id"], "cse")
        self.assertEqual([d["doc_id"] for d in seen["m"]["documents"] if d["role"] == "PEER"], ["iitk"])

    def test_duplicate_submission_returns_the_running_job(self):
        up = self.stage()
        gate = threading.Event()

        def runner(path):
            gate.wait(2)
            return {"run_id": "d" * 16, "analytics_gates": {}}
        first, _ = aj.start_job(up["upload_id"], runner=runner)
        time.sleep(0.05)
        again, err = aj.start_job(up["upload_id"], runner=runner)
        self.assertIsNone(err)
        self.assertEqual(again["job_id"], first["job_id"])
        self.assertTrue(again["duplicate_submission"])
        # different options are a different analysis: refused while one runs, never merged
        self.assertEqual(aj.start_job(up["upload_id"], runner=runner, options={"industry": False}), (None, "JOB_RUNNING"))
        gate.set()
        self.wait(first["job_id"])
        self.assertEqual(len(aj.jobs()), 1)


class Routes(_JobDirs):
    def setUp(self):
        super().setUp()
        aj.MANIFEST.write_text(json.dumps(WITH_DISCIPLINES))
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from app.api.v1 import evidence_api
            from app.core.errors import install as install_error_handlers
        except ImportError as exc:
            raise unittest.SkipTest(f"FastAPI not available: {exc}") from exc
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(evidence_api.analysis_router)
        app.include_router(evidence_api.metadata_router)
        self.c = TestClient(app)

    def test_profiles_and_targets_routes(self):
        r = self.c.get("/api/v1/metadata/discipline-profiles").json()
        self.assertIn("cse", [p["id"] for p in r["profiles"]])
        up = self.stage()
        t = self.c.get(f"/api/v1/analysis/comparison-targets?upload_id={up['upload_id']}").json()
        self.assertEqual(len(t["peers"]), 2)
        self.assertEqual(self.c.get("/api/v1/analysis/comparison-targets?upload_id=upl-000000000000").status_code, 404)

    def test_invalid_selection_is_a_clear_error(self):
        up = self.stage()
        r = self.c.post("/api/v1/analysis/jobs", json={"upload_id": up["upload_id"],
                                                        "options": {"peer_ids": ["mech-peer"]}})
        self.assertEqual(r.status_code, 422)
        self.assertIn("mech-peer: another discipline", json.dumps(r.json()))
        self.assertIn("no other peer is used in their place", json.dumps(r.json()))


if __name__ == "__main__":
    unittest.main()
