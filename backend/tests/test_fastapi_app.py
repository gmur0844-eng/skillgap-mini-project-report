"""The real FastAPI applications in-process (runs wherever FastAPI is installed; skipped otherwise).
Full app: SQLite database created by the Alembic migrations in a temp dir."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    raise unittest.SkipTest("FastAPI not installed in this environment") from None

KEYS = {"error", "code", "message", "details", "request_id"}


from tests.data_requirements import requires_published_run  # noqa: E402

def _knowledge():
    from app.knowledge_api import app
    return TestClient(app)


def test_knowledge_api_structured_errors_and_validation():
    c = _knowledge()
    r = c.get("/api/v1/intelligence/gaps", params={"run_id": "../../etc/passwd"})
    assert r.status_code == 400 and set(r.json()) == KEYS and r.json()["code"] == "INVALID_RUN_ID"
    r = c.get("/api/v1/intelligence/gaps", params={"run_id": "0" * 16})
    assert r.status_code == 404 and r.json()["code"] == "RUN_NOT_FOUND"
    r = c.get("/api/v1/intelligence/gaps", params={"limit": -5})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR" and r.json()["details"]
    r = c.get("/api/v1/does-not-exist")
    assert r.status_code == 404 and set(r.json()) == KEYS
    r = c.post("/api/v1/intelligence/gaps", content=b"{not json")
    assert r.status_code == 405 and r.json()["code"] == "METHOD_NOT_ALLOWED"
    assert "Traceback" not in r.text


@requires_published_run
def test_knowledge_api_health_endpoints():
    c = _knowledge()
    assert c.get("/live").json() == {"status": "ALIVE"}
    r = c.get("/ready")
    assert r.status_code == 200 and r.json()["components"]["database"] == "NOT_CONFIGURED"
    h = c.get("/health").json()["components"]
    assert set(h) == {"api", "database", "model", "semantic", "data", "pipeline"}
    assert h["semantic"]["status"] in ("SAFE_MODE", "ACTIVE") and h["semantic"]["human_validated_decisions"] == 0
    sh = c.get("/api/v1/intelligence/system-health").json()
    assert "components" in sh and sh["evidence_state"] == "AVAILABLE"
    assert c.get("/api/v1/intelligence/evidence-status").json()["items"]


def test_cors_allows_local_dev_origins_and_exposes_request_id():
    c = _knowledge()
    r = c.options("/api/v1/intelligence/gaps", headers={"Origin": "http://localhost:8080",
                                                        "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:8080"
    r = c.get("/live", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    assert c.get("/live").headers.get("x-request-id")


def test_full_app_on_a_migrated_database():
    with tempfile.TemporaryDirectory() as d:
        os.environ["DATABASE_URL"] = f"sqlite:///{d}/app.db"
        os.environ["AUTO_CREATE_SCHEMA"] = "false"
        from app.core.config import get_settings
        get_settings.cache_clear()
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
        import importlib
        import app.db.session as session
        importlib.reload(session)
        import app.main as main
        importlib.reload(main)
        c = TestClient(main.app)
        ready = c.get("/ready").json()
        assert ready["components"]["database"] == "HEALTHY", ready
        h = c.get("/health").json()["components"]["database"]
        assert h["migrations_current"] is True
        for path in ("/api/v1/data-sources", "/api/v1/jobs", "/api/v1/skills"):
            r = c.get(path)
            assert r.status_code in (200, 404, 422) and "Traceback" not in r.text, (path, r.status_code)
        r = c.get("/api/v1/analytics/curriculum-drift", params={"programme_id": "abc"})
        assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
        r = c.post("/api/v1/ingestion/curriculum", files={"file": ("../../evil.exe", b"MZ", "application/octet-stream")})
        assert r.status_code == 415 and r.json()["code"] == "UNSUPPORTED_FILE_TYPE"
        r = c.post("/api/v1/ingestion/curriculum", files={"file": ("empty.pdf", b"", "application/pdf")})
        assert r.status_code == 400 and r.json()["code"] == "EMPTY_FILE"
        del os.environ["DATABASE_URL"], os.environ["AUTO_CREATE_SCHEMA"]
        get_settings.cache_clear()


@requires_published_run
def test_agents_endpoints_describe_the_pipeline_and_label_experimental_output():
    c = _knowledge()
    r = c.get("/api/v1/agents")
    assert r.status_code == 200
    body = r.json()
    assert [a["order"] for a in body["items"]] == [1, 2, 3, 4, 5]
    assert all(a["status"] in ("AVAILABLE", "PARTIAL", "NOT_PRODUCED") for a in body["items"])
    r = c.get("/api/v1/agents/gap-review")
    assert r.status_code == 200
    g = r.json()
    assert g["evidence_state"] in ("AVAILABLE", "NOT_PRODUCED")
    if g["evidence_state"] == "AVAILABLE":
        assert g["authority"] == "EXPERIMENTAL" and all("authoritative_classification" in i for i in g["items"])
    assert c.get("/api/v1/agents", params={"run_id": "../x"}).status_code == 400
