#!/usr/bin/env python3
"""
Compare two analysis runs: which GOLD outputs changed, and how the evidence and its conclusions moved.

  python3 scripts/audit/compare_runs.py --base <run dir> --new <run dir> [--out file.json]

Files are compared with the lineage tool's normalisation (run ids and ids derived from them replaced, JSONL compared
as sorted lines), so a file that differs only by run-scoped ids counts as unchanged. The metrics are read from the GOLD files of each run (nothing is recomputed): evidence counts,
populations and periods, trend status, demand support, gap classification, recommendations, occupations, peers,
mappings. The verdict says whether the new run materially improved the evidence -- it never assumes that more data
is better.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine.recompute import diff_runs  # noqa: E402  (run ids and run-derived ids normalised)
from app.knowledge_engine.intelligence_stage import WITHHELD_FOR_REVIEW_CODES  # noqa: E402


def jl(p):
    p = Path(p)
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def js(p, default=None):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def changed_files(base, new):
    d = diff_runs(base, new)
    return {k: d[k] for k in ("added", "removed", "changed", "unchanged")}


def metrics(run_dir):
    d = Path(run_dir)
    rep = js(d / "run_report.json", {})
    scope = js(d / "industry/population_scope.json", {}) or {}
    pops = (js(d / "industry_v2/temporal_populations.json", {}) or {}).get("populations", [])
    demand = jl(d / "industry/industry_demand.jsonl")
    gaps = jl(d / "intelligence/skill_gaps_v2.jsonl")
    recs = jl(d / "industry/recommendations.jsonl")
    sups = jl(d / "industry/recommendation_suppressions.jsonl")
    occ = js(d / "industry_v2/occupation_summary.json", {}) or {}
    peers = js(d / "peers/peer_status.json", {}) or {}
    mappings = jl(d / "topic_mappings.jsonl")
    skills = jl(d / "industry/skills.jsonl")
    withheld = [s for s in sups if any((r or {}).get("code") in WITHHELD_FOR_REVIEW_CODES
                                       for r in s.get("reasons") or [])]
    supported = {"SUPPORTED", "HIGH_SUPPORT"}
    return {
        "run_id": rep.get("run_id"),
        "documents": {x.get("doc_id"): x.get("role") for x in rep.get("documents", []) if isinstance(x, dict)},
        "postings": scope.get("eligible_postings"),
        "companies": scope.get("distinct_companies"),
        "posting_date_range": scope.get("date_range"),
        "populations": [{"population_id": p.get("population_id"), "eligible_postings": p.get("eligible_postings"),
                         "trend_status": p.get("trend_status"), "granularity": p.get("granularity"),
                         "qualifying_periods": ((p.get("missing") or {}).get("have") or {}).get("qualifying_periods"),
                         "date_basis": p.get("date_basis")} for p in pops],
        "skills_normalized": len(skills),
        "skills_eligible": sum(1 for s in skills if s.get("eligible_for_analytics")),
        "demand_skills": len(demand),
        "demand_by_support": dict(Counter(x.get("support_state") for x in demand)),
        "gaps_v2": dict(Counter(g.get("classification_v2") for g in gaps)),
        "curriculum_scope": (rep.get("curriculum_scope") or {}).get("status", "NOT_ASSESSED"),
        "gaps_scope_limited": sum(1 for g in gaps if g.get("scope_limited")),
        "confirmed_gaps": sum(1 for g in gaps if g.get("classification_v2") in ("PARTIAL", "MISSING")
                              and g.get("support_state") in supported and g.get("evidence_status") != "REVIEW_REQUIRED"),
        "gaps_needing_review": sum(1 for g in gaps if g.get("review")),
        "recommendations_issued": len(recs),
        "withheld_for_review": len(withheld),
        "not_recommended": len(sups) - len(withheld),
        "occupations_established": occ.get("established"),
        "occupations_by_state": occ.get("by_state"),
        "peers_available": [p.get("institution") for p in peers.get("available", [])],
        "peers_missing": [p.get("name") for p in peers.get("missing", [])],
        "topic_mappings_by_status": dict(Counter(m.get("evidence_status") for m in mappings)),
        "concepts": len(jl(d / "concepts.jsonl")),
    }


def verdict(b, n):
    notes, improved = [], False
    if (n["postings"] or 0) > (b["postings"] or 0):
        notes.append(f"industry evidence {b['postings']} -> {n['postings']} postings")
        improved = True
    bt = {p["population_id"]: p["trend_status"] for p in b["populations"]}
    nt = {p["population_id"]: p["trend_status"] for p in n["populations"]}
    if any(v == "COMPUTED" for v in nt.values()) and not any(v == "COMPUTED" for v in bt.values()):
        notes.append("trend analysis became supported")
        improved = True
    elif not any(v == "COMPUTED" for v in nt.values()):
        notes.append("trends remain not established")
    if len(n["peers_available"]) > len(b["peers_available"]):
        notes.append(f"peer curricula {len(b['peers_available'])} -> {len(n['peers_available'])}")
        improved = True
    if (n["occupations_established"] or 0) != (b["occupations_established"] or 0):
        notes.append(f"established occupations {b['occupations_established']} -> {n['occupations_established']}")
    sb, sn = b["demand_by_support"], n["demand_by_support"]
    sup_b = sum(sb.get(k, 0) for k in ("SUPPORTED", "HIGH_SUPPORT"))
    sup_n = sum(sn.get(k, 0) for k in ("SUPPORTED", "HIGH_SUPPORT"))
    if sup_n != sup_b:
        notes.append(f"skills with supported demand {sup_b} -> {sup_n}")
        improved = improved or sup_n > sup_b
    if n["confirmed_gaps"] != b["confirmed_gaps"]:
        notes.append(f"confirmed gaps {b['confirmed_gaps']} -> {n['confirmed_gaps']}")
    if n["recommendations_issued"] != b["recommendations_issued"]:
        notes.append(f"recommendations issued {b['recommendations_issued']} -> {n['recommendations_issued']}")
    return {"materially_improved": improved, "notes": notes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    b, n = metrics(a.base), metrics(a.new)
    out = {"base": b, "new": n, "files": changed_files(a.base, a.new), "verdict": verdict(b, n)}
    out["files_summary"] = {k: len(v) for k, v in out["files"].items()}
    text = json.dumps(out, indent=1, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(json.dumps({"files": out["files_summary"], "changed": out["files"]["changed"], "verdict": out["verdict"]}, indent=1))


if __name__ == "__main__":
    main()
