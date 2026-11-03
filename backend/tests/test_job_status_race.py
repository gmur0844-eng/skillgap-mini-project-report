"""
A job's record read just before its thread writes the final status is stale, not interrupted: reading it again must
return the real outcome, never overwrite it with "interrupted".
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import analysis_jobs as aj  # noqa: E402
from tests.test_standalone_analysis import _JobDirs  # noqa: E402


class StaleRead(_JobDirs):
    def test_a_stale_pending_record_returns_the_final_outcome(self):
        stale = {"job_id": "job-000000000001", "status": aj.PENDING, "upload_id": "u"}
        final = {**stale, "status": aj.READY, "run_id": "1" * 16}
        aj._write(aj.JOB_DIR / "job-000000000001.json", final)  # the thread finished after the stale read
        aj._running["job_id"] = None
        self.assertEqual(aj._settle_interrupted(dict(stale))["status"], aj.READY)
        self.assertEqual(aj._read(aj.JOB_DIR / "job-000000000001.json")["status"], aj.READY)

    def test_a_pending_record_with_no_thread_is_interrupted(self):
        rec = {"job_id": "job-000000000002", "status": aj.PENDING, "upload_id": "u"}
        aj._write(aj.JOB_DIR / "job-000000000002.json", rec)
        aj._running["job_id"] = None
        settled = aj._settle_interrupted(dict(rec))
        self.assertEqual(settled["status"], aj.FAILED)
        self.assertTrue(settled["interrupted"])


if __name__ == "__main__":
    unittest.main()
