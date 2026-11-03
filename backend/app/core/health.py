"""
Component health for /live, /ready, /health and /api/v1/intelligence/system-health.

Framework-free (plain functions over files + injectable checks) so it is unit-tested without a server.
Each component reports its own status; nothing is rolled up into a single green light:

  API        HEALTHY (the process answers)
  DATABASE   HEALTHY | UNAVAILABLE | NOT_CONFIGURED (+ whether the latest GOLD run is published, migration head)
  MODEL      CONNECTED | UNAVAILABLE | NOT_CONFIGURED      (live probe of the configured semantic model)
  SEMANTIC   ACTIVE | SAFE_MODE (+ reason)                 (promotion gate of the replayed/live run)
  DATA       HEALTHY | DEGRADED | MISSING                  (GOLD run, document health, analytics gates, ESCO,
                                                            industry population, freshness)
  PIPELINE   READY | NOT_READY                             (last successful run)

Readiness = DATA is not MISSING, PIPELINE is READY and, when a database is required, DATABASE is HEALTHY.
SAFE_MODE and an unavailable model do NOT make the service unready: the system is designed to run without them.
"""
import json
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GOLD_ROOT = REPO / "data" / "gold" / "knowledge"

_probe_cache = {}


def _json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def latest_run_dir(gold_root=None):
    root = Path(gold_root or GOLD_ROOT)
    pointer = _json(root / "latest_run.json")
    if not pointer or not (root / pointer.get("run_id", "") / "run_report.json").exists():
        return None, pointer
    return root / pointer["run_id"], pointer


def data_component(gold_root=None):
    d, pointer = latest_run_dir(gold_root)
    if d is None:
        return {"status": "MISSING", "reason": "no published GOLD run (run scripts/pipeline/run_knowledge_pipeline.py)"}
    report = _json(d / "run_report.json", {})
    health = _json(d / "health.json", {})
    scope = _json(d / "industry" / "population_scope.json", {}) or {}
    esco = _json(d / "industry" / "esco_audit.json", {}) or {}
    gates = {k: v.get("status") for k, v in (health.get("analytics_gates") or {}).items()}
    docs = {k: v.get("status") for k, v in (health.get("documents") or {}).items()}
    # NOT_APPLICABLE is a correct outcome (e.g. no second programme to compare), not a blocked analysis; a WARN
    # document passed the health gate with warnings and is used. Only BLOCKED analyses and FAILed documents (which
    # the pipeline excludes) degrade the data.
    blocked = sorted(k for k, v in gates.items() if v == "BLOCKED")
    failed_docs = sorted(k for k, v in docs.items() if v == "FAIL")
    warnings = sorted(k for k, v in docs.items() if v == "WARN")
    status = "HEALTHY" if not blocked and not failed_docs else "DEGRADED"
    return {"status": status, "run_id": d.name, "generated_at": pointer.get("generated_at"),
            "curriculum_documents": docs, "analytics_gates": gates, "blocked_analytics": blocked,
            "failed_documents": failed_docs, "documents_with_warnings": warnings,
            "not_applicable_analytics": sorted(k for k, v in gates.items() if v == "NOT_APPLICABLE"),
            "not_requested_analytics": sorted(k for k, v in gates.items() if v == "NOT_REQUESTED"),
            "esco": {"taxonomy_mode": esco.get("taxonomy_mode"), "scope": esco.get("reconstruction_scope"),
                     "skill_concepts": esco.get("skill_concepts_reconstructed")},
            "industry_population": {"eligible_postings": scope.get("eligible_postings"),
                                    "date_range": scope.get("date_range"),
                                    "representativeness_warning": scope.get("representativeness_warning")},
            "pipeline_version": report.get("pipeline_version")}


def pipeline_component(gold_root=None):
    d, pointer = latest_run_dir(gold_root)
    if d is None:
        return {"status": "NOT_READY", "reason": "no GOLD run"}
    return {"status": "READY", "last_successful_run": d.name, "generated_at": pointer.get("generated_at"),
            "content_digest": pointer.get("content_digest")}


def semantic_component(gold_root=None):
    d, _ = latest_run_dir(gold_root)
    rep = _json(d / "intelligence" / "intelligence_report.json", {}) if d else {}
    adj = (rep or {}).get("semantic_adjudication") or {}
    gate = adj.get("gate") or {}
    passed = bool(gate.get("passed"))
    failing = sorted(k for k, v in (gate.get("checks") or {}).items() if not v.get("pass"))
    if not adj:
        return {"status": "SAFE_MODE", "reason": "no semantic adjudication recorded in the latest run"}
    return {"status": "ACTIVE" if passed else "SAFE_MODE",
            "reason": None if passed else (
                "the pre-declared promotion gate did not pass on the internal development benchmark"
                + (f" (failing checks: {', '.join(failing)})" if failing else "")
                + "; model decisions are recorded but have no effect on demand, coverage, gaps, recommendations "
                  "or the graph"),
            "mode": adj.get("mode"), "provider_status": adj.get("status"),
            "decisions_by_validated_state": adj.get("decisions_by_validated_state"),
            "effects_applied": sum((adj.get("effects") or {}).values()) if adj.get("effects") else 0,
            "effects_blocked": adj.get("effects_blocked"),
            "human_validated_decisions": 0,
            "benchmark": "INTERNAL_DEVELOPMENT_EVALUATION (assistant-labelled; not independent ground truth)"}


def model_component(cfg=None, timeout=1.5, ttl=30.0, opener=urllib.request.urlopen):
    """Live probe of the configured Ollama model (cached for `ttl` seconds so /health stays cheap)."""
    import os
    spec = next((p for p in ((cfg or {}).get("semantic_ai") or {}).get("providers", []) if p.get("kind") == "ollama"), None)
    if spec is None:
        return {"status": "NOT_CONFIGURED"}
    base = os.environ.get("OLLAMA_URL", "") or os.environ.get(spec.get("base_url_env") or "", "") or spec.get("base_url")
    model = os.environ.get("MODEL_NAME", "") or spec.get("model")
    key = (base, model)
    hit = _probe_cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        with opener(base.rstrip("/") + "/api/tags", timeout=timeout) as r:
            names = [m.get("name") for m in json.loads(r.read().decode()).get("models", [])]
        out = ({"status": "CONNECTED", "model": model} if model in names else
               {"status": "UNAVAILABLE", "model": model, "reason": "endpoint reachable but the model is not installed"})
    except Exception as e:  # noqa: BLE001 -- unreachable model is a normal, reported state
        out = {"status": "UNAVAILABLE", "model": model, "reason": f"{type(e).__name__}: model endpoint not reachable"}
    out["endpoint"] = base
    _probe_cache[key] = (time.time(), out)
    return out


def database_component(check=None):
    """check() -> dict with at least {'ok': bool}; None = this app has no database."""
    if check is None:
        return {"status": "NOT_CONFIGURED", "reason": "the standalone knowledge API serves GOLD files only"}
    try:
        res = check() or {}
    except Exception as e:  # noqa: BLE001
        return {"status": "UNAVAILABLE", "reason": f"{type(e).__name__}"}
    return {"status": "HEALTHY" if res.get("ok") else "UNAVAILABLE", **{k: v for k, v in res.items() if k != "ok"}}


def health_report(cfg=None, db_check=None, db_required=False, gold_root=None, probe_model=True):
    comps = {"api": {"status": "HEALTHY"}, "database": database_component(db_check),
             "model": model_component(cfg) if probe_model else {"status": "NOT_PROBED"},
             "semantic": semantic_component(gold_root), "data": data_component(gold_root),
             "pipeline": pipeline_component(gold_root)}
    reasons = []
    if comps["data"]["status"] == "MISSING":
        reasons.append("DATA_MISSING")
    if comps["pipeline"]["status"] != "READY":
        reasons.append("PIPELINE_NOT_READY")
    if db_required and comps["database"]["status"] != "HEALTHY":
        reasons.append("DATABASE_UNAVAILABLE")
    ready = not reasons
    return {"status": "READY" if ready else "NOT_READY", "ready": ready, "not_ready_reasons": reasons,
            "components": comps}
