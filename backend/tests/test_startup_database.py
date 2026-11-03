"""Startup must not crash on a database that cannot be opened (regression, 2026-10-10).

`cd backend && uvicorn app.main:app --reload` with no DATABASE_URL and no .env used the default
sqlite:///./data/skillgap_dev.db, which resolves to backend/data/ -- a directory that does not exist -- and the
unguarded create_all in the lifespan aborted startup ("unable to open database file"). The project's policy for a
database that is down is: the API keeps serving the file-backed knowledge endpoints, database routes answer
503 DATABASE_UNAVAILABLE and /ready reports it. Startup now follows the same policy.

Also: .env.example ships `AUTO_CREATE_SCHEMA=` (documented as "empty = default"), which failed to parse.

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
from fastapi.testclient import TestClient
from app.main import app
out = {}
with TestClient(app) as c:                      # runs the lifespan (startup), like uvicorn
    out["schema_error"] = app.state.schema_error
    out["agents"] = c.get("/api/v1/agents").status_code
    out["overview"] = c.get("/api/v1/overview").status_code
    r = c.get("/ready"); out["ready"] = r.json()
    r = c.get("/api/v1/pipeline-runs"); body = r.json()
    out["db_route"] = [r.status_code, body.get("code") if isinstance(body, dict) else None]
print("RESULT" + json.dumps(out))
"""


def run_app(cwd, env_extra, unset=("DATABASE_URL", "AUTO_CREATE_SCHEMA", "ENVIRONMENT", "SEMANTIC_MODE")):
    env = {k: v for k, v in os.environ.items() if k not in unset}
    env.update(env_extra)
    env["PYTHONPATH"] = str(BACKEND)
    p = subprocess.run([sys.executable, "-c", PROBE], cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
    line = next((x for x in p.stdout.splitlines() if x.startswith("RESULT")), None)
    assert p.returncode == 0 and line, f"startup crashed (exit {p.returncode}):\n{p.stderr[-3000:]}"
    return json.loads(line[len("RESULT"):]), p.stderr


from tests.data_requirements import has_published_run  # noqa: E402

KNOWLEDGE_STATUS = 200 if has_published_run() else 404  # a fresh clone has no analysis yet: RUN_NOT_FOUND


class StartupWithoutAReachableDatabase(unittest.TestCase):
    def test_the_documented_command_without_database_url_starts_and_serves_the_knowledge_endpoints(self):
        with tempfile.TemporaryDirectory() as cwd:      # like backend/: no data/ directory, no .env
            out, log = run_app(cwd, {})
            self.assertFalse((Path(cwd) / "data").exists(), "no database file or directory may be created")
        self.assertIn("unable to open database file", out["schema_error"])
        self.assertEqual(out["agents"], KNOWLEDGE_STATUS)
        self.assertEqual(out["overview"], KNOWLEDGE_STATUS)
        self.assertEqual(out["ready"]["status"], "NOT_READY")
        self.assertIn("DATABASE_UNAVAILABLE", out["ready"]["not_ready_reasons"])
        self.assertEqual(out["db_route"], [503, "DATABASE_UNAVAILABLE"])
        self.assertIn("Database schema not ensured", log)      # an actionable message, not a traceback
        self.assertIn("DATABASE_URL=postgresql+psycopg2://localhost/skillgap_<run_id>", log)

    def test_an_unreachable_postgresql_server_does_not_abort_startup(self):
        with tempfile.TemporaryDirectory() as cwd:
            out, _ = run_app(cwd, {"DATABASE_URL": "postgresql+psycopg2://nobody@127.0.0.1:9/none"})
        self.assertTrue(out["schema_error"])
        self.assertEqual(out["agents"], KNOWLEDGE_STATUS)
        self.assertEqual(out["overview"], KNOWLEDGE_STATUS)
        self.assertIn("DATABASE_UNAVAILABLE", out["ready"]["not_ready_reasons"])

    def test_a_working_database_still_gets_its_development_schema(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "dev.db"
            out, _ = run_app(d, {"DATABASE_URL": f"sqlite:///{db}"})
            self.assertTrue(db.exists())
            import sqlite3
            tables = {r[0] for r in sqlite3.connect(db).execute("select name from sqlite_master where type='table'")}
        self.assertIsNone(out["schema_error"])
        self.assertGreater(len(tables), 5)
        self.assertEqual(out["agents"], KNOWLEDGE_STATUS)
        self.assertEqual(out["db_route"][0], 200)                 # database routes work on a reachable database


class EnvExample(unittest.TestCase):
    def test_env_example_parses_and_validates(self):
        """`cp .env.example backend/.env` is the documented setup; it must give a valid configuration."""
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".env").write_text((REPO / ".env.example").read_text())
            code = ("from app.core.config import Settings, validate_settings; s = Settings(); "
                    "print(repr(s.auto_create_schema), s.create_schema_at_startup, validate_settings(s))")
            env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "AUTO_CREATE_SCHEMA")}
            env["PYTHONPATH"] = str(BACKEND)
            p = subprocess.run([sys.executable, "-c", code], cwd=d, env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        self.assertEqual(p.stdout.strip(), "None True []")

    def test_blank_and_explicit_auto_create_schema(self):
        sys.path.insert(0, str(BACKEND))
        from app.core.config import Settings
        self.assertIsNone(Settings(_env_file=None, auto_create_schema="").auto_create_schema)
        self.assertIsNone(Settings(_env_file=None, auto_create_schema="  ").auto_create_schema)
        self.assertFalse(Settings(_env_file=None, auto_create_schema="false").create_schema_at_startup)
        self.assertTrue(Settings(_env_file=None, auto_create_schema="true").create_schema_at_startup)
        self.assertFalse(Settings(_env_file=None, environment="production").create_schema_at_startup)


class ProductionIsUnchanged(unittest.TestCase):
    def test_production_never_runs_create_all(self):
        src = (BACKEND / "app/main.py").read_text()
        self.assertIn("if settings.create_schema_at_startup:\n        _app.state.schema_error = ensure_development_schema()",
                      src)
