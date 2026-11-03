"""Structured errors, request ids, health components, run-id validation and configuration validation.
Runs on plain Starlette (installed everywhere); the FastAPI app itself is exercised by scripts/api/*."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starlette.applications import Starlette  # noqa: E402
from starlette.exceptions import HTTPException  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app.core import errors, health  # noqa: E402
from app.core.config import Settings, validate_settings  # noqa: E402
from app.knowledge_engine.config import load_config, validate_engine_config  # noqa: E402
from app.services import knowledge_service as ks  # noqa: E402

KEYS = {"error", "code", "message", "details", "request_id"}


def _app():
    async def ok(request):
        return JSONResponse({"ok": True})

    async def boom(request):
        raise RuntimeError("secret-token-abc should never reach the client")

    async def coded(request):
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND", "message": "no such run"})

    async def api_err(request):
        raise errors.ApiError(409, "CONFLICT_X", "conflict", {"id": 1})
    app = Starlette(routes=[Route("/ok", ok), Route("/boom", boom), Route("/coded", coded), Route("/api", api_err)])
    return errors.install(app)


def test_every_error_has_the_structured_shape_and_no_stack_trace():
    c = TestClient(_app(), raise_server_exceptions=False)
    for path, status, code in (("/missing", 404, "NOT_FOUND"), ("/boom", 500, "INTERNAL_ERROR"),
                               ("/coded", 404, "RUN_NOT_FOUND"), ("/api", 409, "CONFLICT_X")):
        r = c.get(path)
        body = r.json()
        assert r.status_code == status and set(body) == KEYS and body["code"] == code, (path, body)
        assert "Traceback" not in r.text and "secret-token" not in r.text
        assert body["request_id"] == r.headers["x-request-id"]
    r = c.post("/ok")
    assert r.status_code == 405 and r.json()["code"] == "METHOD_NOT_ALLOWED"


def test_request_id_is_propagated_only_when_well_formed():
    c = TestClient(_app())
    assert c.get("/ok", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"] == "abc-123"
    rid = c.get("/ok", headers={"X-Request-ID": "bad id; drop table"}).headers["x-request-id"]
    assert rid != "bad id; drop table" and rid.isalnum()
    assert float(c.get("/ok").headers["x-response-time-ms"]) >= 0


def test_access_log_is_json_without_headers_or_bodies(caplog=None):
    import logging
    records = []
    h = logging.Handler()
    h.emit = records.append
    errors.log.addHandler(h)
    errors.log.setLevel(logging.INFO)
    try:
        TestClient(_app()).get("/ok?run_id=0123456789abcdef&token=SECRET", headers={"Authorization": "Bearer SECRET"})
    finally:
        errors.log.removeHandler(h)
    line = json.loads(records[-1].getMessage())
    assert line["path"] == "/ok" and line["run_id"] == "0123456789abcdef" and line["status"] == 200
    assert "SECRET" not in records[-1].getMessage()


def test_run_id_is_validated_before_any_file_access():
    for bad in ("../../etc", "d658c97abebca9f5/../x", "D658C97ABEBCA9F5", "abc"):
        try:
            ks.KnowledgeRun(bad)
            raise AssertionError(bad)
        except ks.InvalidRunId:
            pass


def _gold(tmp, gate_passed=False, docs_pass=True):
    root = Path(tmp)
    run = root / "0123456789abcdef"
    (run / "industry").mkdir(parents=True)
    (run / "intelligence").mkdir()
    (root / "latest_run.json").write_text(json.dumps({"run_id": run.name, "generated_at": "t", "content_digest": "d"}))
    (run / "run_report.json").write_text(json.dumps({"pipeline_version": "x"}))
    (run / "health.json").write_text(json.dumps({"documents": {"a": {"status": "PASS" if docs_pass else "FAIL"}},
                                                 "analytics_gates": {"g": {"status": "ALLOWED"}}}))
    (run / "industry/population_scope.json").write_text(json.dumps({"eligible_postings": 100,
                                                                    "representativeness_warning": "w"}))
    (run / "intelligence/intelligence_report.json").write_text(json.dumps({"semantic_adjudication": {
        "mode": "REPLAY_VERIFIED_RUN", "status": "AI_PROVIDER_REPLAYED", "effects": {}, "effects_blocked": 3,
        "gate": {"passed": gate_passed, "checks": {"c1": {"pass": gate_passed}}}}}))
    return root


def test_health_reports_each_component_and_safe_mode_is_not_unready():
    with tempfile.TemporaryDirectory() as t:
        root = _gold(t)
        r = health.health_report(cfg={}, gold_root=root, probe_model=False)
        c = r["components"]
        assert r["ready"] and c["api"]["status"] == "HEALTHY" and c["data"]["status"] == "HEALTHY"
        assert c["semantic"]["status"] == "SAFE_MODE" and "c1" in c["semantic"]["reason"]
        assert c["semantic"]["human_validated_decisions"] == 0
        assert c["database"]["status"] == "NOT_CONFIGURED" and c["pipeline"]["last_successful_run"] == "0123456789abcdef"
        assert health.semantic_component(_gold(t + "/p", gate_passed=True))["status"] == "ACTIVE"


def test_readiness_requires_database_only_when_the_app_needs_one():
    with tempfile.TemporaryDirectory() as t:
        root = _gold(t)
        down = lambda: (_ for _ in ()).throw(ConnectionError("refused"))  # noqa: E731
        r = health.health_report(cfg={}, db_check=down, db_required=True, gold_root=root, probe_model=False)
        assert not r["ready"] and r["not_ready_reasons"] == ["DATABASE_UNAVAILABLE"]
        assert r["components"]["database"]["status"] == "UNAVAILABLE"
        assert health.health_report(cfg={}, db_check=lambda: {"ok": True}, db_required=True, gold_root=root,
                                    probe_model=False)["ready"]
        empty = Path(t) / "empty"
        empty.mkdir()
        r = health.health_report(cfg={}, gold_root=empty, probe_model=False)
        assert not r["ready"] and "DATA_MISSING" in r["not_ready_reasons"]


def test_model_probe_distinguishes_connected_missing_model_and_unreachable():
    import io
    cfg = {"semantic_ai": {"providers": [{"kind": "ollama", "base_url": "http://m:1", "model": "q"}]}}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    health._probe_cache.clear()
    assert health.model_component(cfg, opener=lambda u, timeout: Resp(b'{"models":[{"name":"q"}]}'))["status"] == "CONNECTED"
    health._probe_cache.clear()
    r = health.model_component(cfg, opener=lambda u, timeout: Resp(b'{"models":[]}'))
    assert r["status"] == "UNAVAILABLE" and "not installed" in r["reason"]
    health._probe_cache.clear()

    def refuse(u, timeout):
        raise ConnectionRefusedError()
    assert health.model_component(cfg, opener=refuse)["status"] == "UNAVAILABLE"
    assert health.model_component({})["status"] == "NOT_CONFIGURED"


def test_settings_validation_rejects_unsafe_production_config():
    assert validate_settings(Settings()) == []
    bad = validate_settings(Settings(environment="production", debug=True, cors_origins="*",
                                     database_url="sqlite:///x.db", ollama_url="ftp://x", min_periods_for_trend=1))
    text = " | ".join(bad)
    for needle in ("DEBUG", "PostgreSQL", "CORS", "OLLAMA_URL", "MIN_PERIODS_FOR_TREND"):
        assert needle in text, needle
    assert validate_settings(Settings(environment="staging"))
    assert Settings(environment="production").create_schema_at_startup is False
    assert Settings().create_schema_at_startup is True
    assert Settings(environment="production").cors_origin_regex is None


def test_engine_config_validation():
    cfg = load_config()
    assert validate_engine_config(cfg) == []
    bad = json.loads(json.dumps(cfg))
    bad["mapping"]["min_similarity"] = 1.7
    bad["families"]["k_min"] = 99
    bad["semantic_ai"]["providers"][0]["api_key"] = "literal"
    bad["semantic_replay"]["runs"] = [{"name": "x"}]
    problems = " | ".join(validate_engine_config(bad))
    for needle in ("mapping.min_similarity", "k_min", "literal api_key", "lacks cache_sha256"):
        assert needle in problems, needle
