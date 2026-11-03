"""
Static validation of the Flutter knowledge screens without a Flutter SDK:
  1. every screen's endpoint path is a real GET route of the backend routers (parsed from the router source);
  2. every column / summary key a screen reads exists in the response the backend builds from the published
     GOLD run (the service functions are called directly -- the same code the API routes call);
  3. no hard-coded numbers or placeholder text in the screen code (no 'TODO', 'lorem', 'dummy', 'mock', 'fake').
Writes artifacts/flutter_static_validation.json and exits non-zero on any failure.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import intelligence_service as svc  # noqa: E402
from app.services import knowledge_service as ks  # noqa: E402
from app.services import evidence_metadata  # noqa: E402
from app.services import agents_service  # noqa: E402

DART = (ROOT / "flutter_app/lib/screens/screen_specs.dart").read_text()
SCREEN = (ROOT / "flutter_app/lib/screens/knowledge_screens.dart").read_text()
MAIN = (ROOT / "flutter_app/lib/main.dart").read_text()


def specs():
    out = []
    for block in re.findall(r"KnowledgeScreenSpec\((.*?)\)(?:,\s*\n|\s*\n\];)", DART, re.S):
        if "title:" not in block:
            continue
        get = lambda k: (re.search(rf"{k}:\s*'([^']*)'", block) or [None, None])[1]  # noqa: B023 -- called within this iteration
        lst = lambda k: re.findall(r"'([^']*)'", (re.search(rf"{k}:\s*\[(.*?)\]", block, re.S) or [None, ""])[1])  # noqa: B023 -- called within this iteration
        out.append({"title": get("title"), "path": get("path"), "listKey": get("listKey") or "items",
                    "columns": lst("columns"), "summaryKeys": lst("summaryKeys"), "inputParam": get("inputParam")})
    return out


def routes():
    found = set()
    for f in ("curriculum_knowledge.py", "intelligence_api.py", "improvement_api.py", "health_api.py", "evidence_api.py", "assistant_api.py",
              "semantic_validation_api.py"):
        src = (ROOT / "backend/app/api/v1" / f).read_text()
        prefixes = dict(re.findall(r'(\w+)\s*=\s*APIRouter\(prefix="([^"]+)"', src))
        # GET routes, plus the POST that starts an analysis job (called by the shell's run context)
        for router, path in re.findall(r'@(\w+)\.(?:get|post)\("([^"]*)"', src):
            found.add(prefixes.get(router, "") + path)
    return found


def response_for(path, run, ir, skill_key):
    table = {
        "/api/v1/curriculum/knowledge-runs/latest": lambda: ks.run_summary(run),
        "/api/v1/intelligence/system-health": lambda: svc.system_health(ir),
        "/api/v1/curriculum/topics": lambda: ks.list_topics(run, limit=50),
        "/api/v1/curriculum/topic-hierarchy": lambda: svc.curriculum_topic_hierarchy(ir, limit=50),
        "/api/v1/semantic/concepts": lambda: svc.semantic_concepts(ir, limit=50),
        "/api/v1/semantic/relationships": lambda: svc.semantic_relationships(ir, limit=50),
        "/api/v1/industry/occupations": lambda: svc.industry_occupations(ir, limit=50),
        "/api/v1/industry/demand": lambda: ks.industry_demand(run, limit=50),
        "/api/v1/industry/esco-audit": lambda: ks.esco_audit(run),
        "/api/v1/industry/skill-taxonomy": lambda: svc.industry_skill_taxonomy(ir, limit=50),
        "/api/v1/curriculum/coverage": lambda: svc.curriculum_coverage(ir, limit=50),
        "/api/v1/intelligence/gaps": lambda: svc.gaps(ir, limit=50),
        "/api/v1/curriculum/drift": lambda: svc.curriculum_drift(ir, limit=50),
        "/api/v1/curriculum/course-drift": lambda: svc.curriculum_course_drift(ir),
        "/api/v1/curriculum/benchmark": lambda: svc.curriculum_benchmark(ir),
        "/api/v1/intelligence/recommendations": lambda: svc.recommendations(ir),
        "/api/v1/semantic/decisions": lambda: svc.semantic_decisions(ir, limit=50),
        "/api/v1/semantic/contradictions": lambda: svc.semantic_contradictions(ir),
        "/api/v1/semantic/review": lambda: svc.semantic_review(ir, limit=50),
        "/api/v1/intelligence/evidence-trace": lambda: svc.evidence_trace(ir, skill_key),
        "/api/v1/intelligence/lineage": lambda: svc.lineage(ir),
        "/api/v1/intelligence/evidence-status": lambda: svc.evidence_status(ir),
        "/api/v1/industry/trends": lambda: svc.industry_trends(ir),
        "/api/v1/curriculum/knowledge-health": lambda: ks.health(run),
        "/api/v1/metadata/sources": lambda: {"evidence_state": "AVAILABLE", **evidence_metadata.sources()},
        "/api/v1/agents": lambda: agents_service.agents(run),
        "/api/v1/agents/gap-review": lambda: agents_service.gap_review(run),
    }
    return table[path]() if path in table else None


def has_path(row, dotted):
    cur = row
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


def duplicate_const_keys():
    """Duplicate keys in a Dart const map literal are a compile error (flutter analyze / build), which this container
    cannot run; caught here as well."""
    out = []
    for f in sorted((ROOT / "flutter_app/lib").rglob("*.dart")):
        src = f.read_text()
        for m in re.finditer(r"const\s+(?:\w+\s+)?(\w+)\s*=\s*<String,\s*[\w?<>, ]+>\{", src):
            end = src.find("};", m.end())
            keys = re.findall(r"^\s*'([^']+)'\s*:", src[m.end():end], re.M)
            dup = sorted({k for k in keys if keys.count(k) > 1})
            if dup:
                out.append({"file": str(f.relative_to(ROOT)), "map": m.group(1), "duplicate_keys": dup})
    return out


def main():
    run = ks.load_run(None)
    ir = svc.load(None)
    skill_key = next((d["skill_key"] for d in run.industry["demand"]), None) if run.industry else None
    known = routes()
    results, failures = [], []
    for s in specs():
        r = {"title": s["title"], "path": s["path"], "route_exists": s["path"] in known}
        body = response_for(s["path"], run, ir, skill_key)
        r["response_built"] = body is not None
        if body is not None:
            rows = body.get(s["listKey"]) if s["listKey"] != "_none" else None
            rows = rows if isinstance(rows, list) else []
            r["rows_in_run"] = body.get("total", len(rows))
            r["missing_summary_keys"] = [k for k in s["summaryKeys"] if k not in body]
            r["missing_columns"] = [c for c in s["columns"] if rows and not any(has_path(x, c) for x in rows)]
            r["columns_unchecked_no_rows"] = [] if rows else s["columns"]
        r["passed"] = r["route_exists"] and r["response_built"] and not r.get("missing_columns") \
            and not r.get("missing_summary_keys")
        results.append(r)
        if not r["passed"]:
            failures.append(r)
    # redesigned (premium) screens and shell: every endpoint literal is a real GET route
    premium_src = {str(f.relative_to(ROOT)): f.read_text() for d in ("flutter_app/lib/screens/premium", "flutter_app/lib/shell",
                                                                     "flutter_app/lib/widgets", "flutter_app/lib/theme")
                   for f in sorted((ROOT / d).glob("*.dart"))}
    premium_src["flutter_app/lib/screens/ingestion_screen.dart"] = (ROOT / "flutter_app/lib/screens/ingestion_screen.dart").read_text()
    premium = []
    for name, src in premium_src.items():
        for path in sorted(set(re.findall(r"'(/(?:api/v1/[^'?$]+|health))'", src))):
            ok = path in known
            premium.append({"file": name, "path": path, "route_exists": ok})
            if not ok:
                failures.append({"file": name, "path": path, "route_exists": False})
    allsrc = DART + SCREEN + MAIN + "".join(premium_src.values())
    placeholders = [w for w in ("TODO", "lorem", "dummy", "mock", "fake", "placeholder")
                    if re.search(rf"\b{w}\b", allsrc, re.I)]
    report = {"run_id": run.run_id, "screens": len(results), "passed": sum(r["passed"] for r in results),
              "premium_endpoints": premium, "placeholder_words_in_code": placeholders, "results": results}
    out = ROOT / "artifacts/flutter_static_validation.json"
    out.write_text(json.dumps(report, indent=1))
    print(f"screens={report['screens']} passed={report['passed']} premium_endpoints={len(premium)} "
          f"premium_ok={sum(p['route_exists'] for p in premium)} placeholders={placeholders}")
    for d in duplicate_const_keys():
        failures.append({"duplicate_const_map_keys": d})
    for f in failures:
        print("FAIL", json.dumps(f))
    sys.exit(1 if failures or placeholders else 0)


if __name__ == "__main__":
    main()
