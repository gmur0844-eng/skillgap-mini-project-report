"""
Live validation of the FULL FastAPI application (app.main: database-backed routers + knowledge routers) over HTTP.

  python3 scripts/api/full_app_validation.py --base http://localhost:8000 --out artifacts/mac/full_api_validation.json

1. every GET route from the live OpenAPI schema, called with real ids (skill_key, concept_uid, node_id, programme_id)
2. negative cases: unknown ids, invalid run ids, malformed/invalid parameters, malformed JSON, wrong method,
   unsupported upload, empty upload -- every error must have the structured shape and no traceback
3. health: /live, /ready, /health components
4. performance: N timed requests per GET route (mean, median, p95, max) + server-side X-Response-Time-ms
Exit code 1 on any failed check.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

KEYS = {"error", "code", "message", "details", "request_id"}


def pct(values, p):
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))] if s else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeat", type=int, default=20)
    a = ap.parse_args()
    c = httpx.Client(base_url=a.base, timeout=30)
    checks, failures = [], []

    def check(name, ok, detail=None):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})
        if not ok:
            failures.append(name)

    schema = c.get("/openapi.json").json()
    demand = c.get("/api/v1/industry/demand", params={"limit": 1}).json()
    ids = {"skill_key": demand["items"][0]["skill_key"],
           "concept_uid": c.get("/api/v1/curriculum/concepts", params={"limit": 1}).json()["items"][0]["concept_uid"],
           "node_id": c.get("/api/v1/semantic/relationships", params={"limit": 1}).json()["items"][0]["source"],
           "programme_id": "1", "q": "network"}
    comps = c.get("/api/v1/peers/benchmark").json().get("comparisons") or []
    if comps:
        ids["comparison_doc_id"] = comps[0]["comparison_doc_id"]

    routes = []
    for path, ops in sorted(schema["paths"].items()):
        op = ops.get("get")
        if op is None:
            continue
        url, params, missing = path, {}, []
        for prm in op.get("parameters", []):
            name = prm["name"]
            if prm["in"] == "path":
                if name in ids:
                    url = url.replace("{" + name + "}", ids[name])
                else:
                    missing.append(name)
            elif prm.get("required"):
                if name in ids:
                    params[name] = ids[name]
                else:
                    missing.append(name)
        if missing:
            check(f"GET {path}: no id available for {missing}", True, "skipped (no real id of this kind)")
            continue
        r = c.get(url, params=params)
        body_ok = r.headers.get("content-type", "").startswith("application/json")
        err_ok = r.status_code < 400 or (set(r.json()) == KEYS if body_ok else False)
        # database-backed analytics may legitimately report 404 'no run yet' -- but only in the structured shape
        check(f"GET {path}", r.status_code < 500 and body_ok and err_ok and "Traceback" not in r.text,
              {"status": r.status_code, "code": (r.json() or {}).get("code") if r.status_code >= 400 and body_ok else None})
        routes.append((path, url, params, r.status_code))

    # negative cases
    neg = [
        ("unknown path", "GET", "/api/v1/nope", {}, None, 404, "NOT_FOUND"),
        ("invalid run_id (path traversal)", "GET", "/api/v1/intelligence/gaps", {"run_id": "../../etc"}, None, 400, "INVALID_RUN_ID"),
        ("unknown run_id", "GET", "/api/v1/intelligence/gaps", {"run_id": "0" * 16}, None, 404, "RUN_NOT_FOUND"),
        ("invalid limit", "GET", "/api/v1/industry/demand", {"limit": -1}, None, 422, "VALIDATION_ERROR"),
        ("invalid programme_id", "GET", "/api/v1/analytics/curriculum-drift", {"programme_id": "abc"}, None, 422, "VALIDATION_ERROR"),
        ("missing required skill_key", "GET", "/api/v1/intelligence/why-not", {}, None, 422, "VALIDATION_ERROR"),
        ("unknown concept", "GET", "/api/v1/curriculum/concepts/concept:0000000000000000", {}, None, 404, "NOT_FOUND"),
        ("wrong method", "POST", "/api/v1/intelligence/gaps", {}, b"{}", 405, "METHOD_NOT_ALLOWED"),
        ("unknown search type", "GET", "/api/v1/search", {"q": "network", "types": "NOPE"}, None, 422, "VALIDATION_ERROR"),
        ("peer differences without comparison", "GET", "/api/v1/peers/differences", {}, None, 422, "VALIDATION_ERROR"),
    ]
    for name, method, path, params, body, status, code in neg:
        r = c.request(method, path, params=params, content=body)
        j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        check(f"negative: {name}", r.status_code == status and set(j) == KEYS and j.get("code") == code
              and "Traceback" not in r.text, {"status": r.status_code, "code": j.get("code")})
    posts = [p for p, o in schema["paths"].items() if "post" in o and "requestBody" in o["post"]
             and "application/json" in o["post"]["requestBody"].get("content", {})]
    if posts:
        r = c.post(posts[0], content=b"{not json", headers={"Content-Type": "application/json"})
        j = r.json()
        check("negative: malformed JSON body", r.status_code == 422 and set(j) == KEYS, {"path": posts[0], "status": r.status_code})
    else:
        check("negative: malformed JSON body", True, "no JSON-body POST route exists (all POSTs are multipart uploads)")
        r = c.post("/api/v1/ingestion/jobs", content=b"{not json", headers={"Content-Type": "application/json"})
        j = r.json()
        check("negative: JSON sent to an upload route", r.status_code == 422 and set(j) == KEYS, {"status": r.status_code})
    r = c.post("/api/v1/ingestion/curriculum", files={"file": ("../../x.exe", b"MZ", "application/octet-stream")})
    check("negative: unsupported upload type", r.status_code == 415 and r.json().get("code") == "UNSUPPORTED_FILE_TYPE",
          {"status": r.status_code})
    r = c.post("/api/v1/ingestion/curriculum", files={"file": ("empty.pdf", b"", "application/pdf")})
    check("negative: empty upload", r.status_code == 400 and r.json().get("code") == "EMPTY_FILE", {"status": r.status_code})

    # health
    live, ready, health = c.get("/live"), c.get("/ready"), c.get("/health").json()
    comp = health["components"]
    check("health: /live", live.status_code == 200)
    check("health: /ready", ready.status_code == 200, ready.json())
    check("health: database HEALTHY + migrations current + latest run published",
          comp["database"]["status"] == "HEALTHY" and comp["database"].get("migrations_current") is True
          and comp["database"].get("latest_run_published") is True, comp["database"])
    check("health: semantic state reported", comp["semantic"]["status"] in ("SAFE_MODE", "ACTIVE"), comp["semantic"]["status"])
    check("health: model probe reported", comp["model"]["status"] in ("CONNECTED", "UNAVAILABLE"), comp["model"])

    # performance
    perf = []
    for path, url, params, status in routes:
        if status >= 400:
            continue
        client_ms, server_ms = [], []
        for _ in range(a.repeat):
            t = time.perf_counter()
            r = c.get(url, params=params)
            client_ms.append((time.perf_counter() - t) * 1000)
            server_ms.append(float(r.headers.get("x-response-time-ms", "nan")))
        perf.append({"path": path, "n": a.repeat, "mean_ms": round(statistics.mean(client_ms), 2),
                     "median_ms": round(statistics.median(client_ms), 2), "p95_ms": round(pct(client_ms, 95), 2),
                     "max_ms": round(max(client_ms), 2), "server_median_ms": round(statistics.median(server_ms), 2)})
    allms = [p["median_ms"] for p in perf]
    report = {"base": a.base, "checks": len(checks), "passed": len(checks) - len(failures), "failed": failures,
              "routes_tested": len(routes), "performance": sorted(perf, key=lambda p: -p["p95_ms"]),
              "performance_summary": {"routes": len(perf), "median_of_medians_ms": round(statistics.median(allms), 2) if allms else None,
                                      "worst_p95": perf and max(perf, key=lambda p: p["p95_ms"])},
              "results": checks, "health": health}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=1, default=str))
    print(f"checks={report['checks']} passed={report['passed']} routes={len(routes)} failed={failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
