"""Uploading a curriculum ("New analysis") without a reachable database (regression, 2026-10-22).

`scripts/local/run.sh` with no DATABASE_URL left the API on its built-in default, a SQLite file in backend/data/, a
folder that does not exist: every curriculum upload failed with "the file could not be ingested", which pointed at the
file rather than at the database. Now run.sh gives the local app its own SQLite file, and an ingestion endpoint whose
database cannot be reached answers 503 DATABASE_UNAVAILABLE like every other database route.

Each case runs the real application in a fresh interpreter (settings and the engine are created at import time).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

try:
    import fastapi  # noqa: F401
    import pydantic_settings  # noqa: F401
except ImportError:  # pragma: no cover
    raise unittest.SkipTest("FastAPI not installed in this environment") from None

PROBE = r"""
import json, sys
import os
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.services import analysis_jobs
box = Path(os.environ["UPLOAD_SANDBOX"])   # a successful upload is staged here, never in the project's data folders
analysis_jobs.REPO, analysis_jobs.UPLOAD_DIR, analysis_jobs.STAGED_DIR = box, box / "uploads", box / "staged"
from app.pipelines.preprocessing import artifact_writer
artifact_writer.DATA_ROOT = box / "data"     # the ingestion's raw / bronze / silver copies too
text = "B.E. Mechanical Engineering\nSEMESTER III\nME202 Fluid Mechanics\nUNIT-I\nFluid properties, viscosity\n"
with TestClient(app) as c:
    r = c.post("/api/v1/ingestion/curriculum", files={"file": ("syllabus.txt", text.encode(), "text/plain")},
               data={"institution": "Example College", "programme": "B.E. Mechanical Engineering",
                     "discipline": "Mechanical Engineering"})
    body = r.json()
print("RESULT" + json.dumps([r.status_code, body.get("code") or body.get("status")]))
"""


def upload(cwd, env_extra):
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "AUTO_CREATE_SCHEMA", "ENVIRONMENT")}
    env.update(env_extra, PYTHONPATH=str(BACKEND), UPLOAD_SANDBOX=cwd)
    p = subprocess.run([sys.executable, "-c", PROBE], cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
    line = next((x for x in p.stdout.splitlines() if x.startswith("RESULT")), None)
    assert p.returncode == 0 and line, f"probe failed (exit {p.returncode}):\n{p.stderr[-3000:]}"
    return json.loads(line[len("RESULT"):])


class UploadDatabase(unittest.TestCase):
    def test_an_unreachable_database_is_reported_as_such_not_as_a_bad_file(self):
        with tempfile.TemporaryDirectory() as cwd:  # like backend/ with no data/ folder and no DATABASE_URL
            self.assertEqual(upload(cwd, {}), [503, "DATABASE_UNAVAILABLE"])

    def test_the_local_sqlite_file_run_sh_sets_accepts_the_upload(self):
        with tempfile.TemporaryDirectory() as d:
            status, _ = upload(d, {"DATABASE_URL": f"sqlite:///{Path(d) / 'skillgap_local.db'}"})
        self.assertEqual(status, 200)

    def test_run_sh_sets_a_local_database_only_when_none_is_configured(self):
        script = (REPO / "scripts/local/run.sh").read_text()
        self.assertIn('[ -z "${DATABASE_URL:-}" ]', script)
        self.assertIn("artifacts/local/skillgap_local.db", script)


if __name__ == "__main__":
    unittest.main()
