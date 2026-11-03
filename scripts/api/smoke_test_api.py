"""
Runtime smoke test of every GET route of the standalone Knowledge API
(app.knowledge_api) against the published GOLD run, in-process via
fastapi.testclient (needs fastapi + httpx).

For each route: status 200, JSON body, and -- for engine-2.0 routes -- the
`evidence_state` + `scope` envelope. Routes that need an id are called with a
real id read from the run (first demand skill, first concept, first graph node)
and once with an unknown id (must be 404 or an explicit empty/NOT_FOUND body,
never a fabricated record). Writes a JSON report.

    python3 scripts/api/smoke_test_api.py [--out artifacts/api_validation.json]
"""
import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.knowledge_api import app  # noqa: E402
from app.services import knowledge_service as ks  # noqa: E402


def first_jsonl(path, key):
    with open(path) as f:
        for line in f:
            return json.loads(line).get(key)


EXPLANATION_KEYS = {"scope", "evidence_state", "skill_key", "node_id", "reasons", "recommendation_exists"}


def empty_answer(body):
    """An unknown id must yield no records: only explanation keys, and every other value empty or a
    'no recommendation' explanation. Anything else would be a fabricated answer."""
    if not isinstance(body, dict):
        return body in (None, [], {})
    for k, v in body.items():
        if k in EXPLANATION_KEYS:
            continue
        if isinstance(v, dict) and v.get("recommendation_exists") is False:
            continue
        if isinstance(v, dict) and not empty_answer(v):
            return False
        if isinstance(v, list) and v:
            return False
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "artifacts/api_validation.json"))
    a = ap.parse_args()
    run = ks.load_run(None)
    ids = {"skill_key": first_jsonl(run.dir / "industry/industry_demand.jsonl", "skill_key"),
           "concept_uid": first_jsonl(run.dir / "concepts.jsonl", "concept_uid"),
           "node_id": first_jsonl(run.dir / "intelligence/graph_nodes.jsonl", "node_id")}
    client = TestClient(app)
    results = []
    # routes come from the OpenAPI schema: independent of how a FastAPI version stores included routers
    schema = app.openapi()
    for route_path in sorted(schema["paths"]):
        op = schema["paths"][route_path].get("get")
        if op is None:
            continue
        path, params = route_path, {}
        if "{concept_uid}" in path:
            path = path.replace("{concept_uid}", ids["concept_uid"])
        for prm in op.get("parameters", []):
            if prm.get("in") == "query" and prm.get("required") and prm["name"] in ids:
                params[prm["name"]] = ids[prm["name"]]
        t = time.time()
        r = client.get(path, params=params)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
        checks = {"status_200": r.status_code == 200, "json": body is not None}
        if route_path.startswith(("/api/v1/semantic", "/api/v1/intelligence")) or route_path in (
                "/api/v1/curriculum/topic-hierarchy", "/api/v1/curriculum/coverage", "/api/v1/curriculum/drift",
                "/api/v1/curriculum/course-drift", "/api/v1/curriculum/benchmark", "/api/v1/industry/occupations",
                "/api/v1/industry/trends", "/api/v1/industry/skill-taxonomy"):
            checks["envelope"] = isinstance(body, dict) and body.get("evidence_state") in ("AVAILABLE", "NOT_PRODUCED") \
                and "scope" in (body or {})
        unknown = None
        if params or "{concept_uid}" in route_path:
            upath = route_path.replace("{concept_uid}", "concept:0000000000000000")
            uparams = {k: "unknown:does-not-exist" for k in params}
            u = client.get(upath, params=uparams)
            ub = u.json() if u.status_code == 200 else None
            unknown = {"status": u.status_code, "no_fabrication": u.status_code == 404 or empty_answer(ub)}
            checks["unknown_id_safe"] = unknown["no_fabrication"]
        results.append({"path": route_path, "params": params, "status": r.status_code, "ms": round((time.time() - t) * 1000, 1),
                        "bytes": len(r.content), "checks": checks, "unknown_id": unknown, "passed": all(checks.values())})
    report = {"run_id": run.run_id, "routes_tested": len(results), "passed": sum(r["passed"] for r in results),
              "failed": [r for r in results if not r["passed"]], "results": results}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=2))
    print(f"routes={report['routes_tested']} passed={report['passed']} failed={len(report['failed'])} run={run.run_id}")
    for r in report["failed"]:
        print("FAIL", r["path"], r["status"], r["checks"])
    sys.exit(1 if report["failed"] else 0)


if __name__ == "__main__":
    main()
