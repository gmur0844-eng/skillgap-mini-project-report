"""Experimental discipline-relevance audit of an existing run (default: the published release).

Reads the run's GOLD, the SILVER postings and curricula and the ESCO classification named in the manifest; writes
only to data/experiments/relevance/<run_id>/ and docs/industry_relevance_evaluation.md. The run itself, its demand,
gaps and recommendations are not touched.

    python3 scripts/analysis/relevance_audit.py [--run c066b227857f9eaf]
"""
from __future__ import annotations

import argparse
import ast
import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.knowledge_engine import industry, industry_stage  # noqa: E402
from app.knowledge_engine import relevance as rel  # noqa: E402

TRACE_LABELS = ("reproductive health", "help customers", "financial statements")


def jl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def lit(v):
    return ast.literal_eval(v) if isinstance(v, str) and v[:1] in "[{(" else v


class _Quarantine:
    def add(self, *args):
        print("source problem:", args, file=sys.stderr)


def load(run_id):
    run = REPO / "data/gold/knowledge" / run_id
    report = json.loads((run / "run_report.json").read_text())
    roles = {d["doc_id"]: d["role"] for d in report["documents"]}
    uids = {p["posting_uid"] for p in jl(run / "industry/postings.jsonl")}
    postings = [p for f in sorted(glob.glob(str(REPO / "data/silver/jobs/*/postings.jsonl"))) for p in jl(f)
                if p["posting_uid"] in uids]
    postings = list({p["posting_uid"]: p for p in postings}.values())
    missing = uids - {p["posting_uid"] for p in postings}
    if missing:
        raise SystemExit(f"{len(missing)} postings of the run have no SILVER record; re-run the pipeline first")
    topics, courses = {}, defaultdict(list)
    for doc_id in roles:
        for f in glob.glob(str(REPO / f"data/silver/curricula/{doc_id}/*/topics.jsonl")):
            topics.update({t["topic_uid"]: t["doc_id"] for t in jl(f)})
        for f in glob.glob(str(REPO / f"data/silver/curricula/{doc_id}/*/courses.jsonl")):
            courses[doc_id] += [c.get("title") or "" for c in jl(f)]
    manifest = json.loads((REPO / "data/metadata/curriculum_sources.json").read_text())
    _, taxonomies = industry_stage.verify_sources(manifest, REPO, _Quarantine())
    vocab, _ = industry_stage.load_esco(taxonomies)
    store = vocab["_store"]
    return {
        "run": run, "run_id": run_id, "roles": roles, "postings": postings, "topic_doc": topics, "courses": courses,
        "skill_mentions": jl(run / "industry/skill_mentions.jsonl"),
        "curriculum_mentions": jl(run / "industry/curriculum_skill_mentions.jsonl"),
        "coverage": jl(run / "intelligence/coverage_depth.jsonl"),
        "demand": {d["skill_key"]: d for d in jl(run / "industry/industry_demand.jsonl")},
        "gaps": {g["skill_key"]: g for g in jl(run / "industry/skill_gaps.jsonl")},
        "gaps_v2": {g["skill_key"]: g for g in jl(run / "intelligence/skill_gaps_v2.jsonl")},
        "recommendations": jl(run / "industry/recommendations.jsonl"),
        "esco_maps": {m.get("skill_key"): m for m in jl(run / "industry/esco_mappings.jsonl")},
        "occupations": {r["posting_uid"]: r for r in jl(run / "industry_v2/occupation_resolution.jsonl")},
        "store": store,
        "cfg": json.loads((REPO / "backend/app/knowledge_engine/engine_config.json").read_text())["industry"],
    }


def audit(d, min_shared=rel.OCCUPATION_MIN_SHARED, boiler=None, mentions=None):
    store = d["store"]
    reuse = {u: s.get("reuse_level") for u, s in store["skills"].items()}
    occ_skills = {u: set(o["essential_skills"]) | set(o["optional_skills"]) for u, o in store["occupations"].items()}
    programme = {doc for doc, role in d["roles"].items() if role in ("TARGET", "PREVIOUS_VERSION", "REFERENCE")}
    coverage = [{**c, "role": c["role"]} for c in d["coverage"] if c["doc_id"] in programme]
    profile = rel.programme_profile(d["curriculum_mentions"], d["topic_doc"], programme, coverage)
    labels = {(store["skills"].get(u) or {}).get("pref_label", "").lower() for u in profile}
    labels |= {(d["demand"].get(u) or {}).get("skill_label", "").lower() for u in profile}
    labels = {x for x in labels if x}
    course_bigrams = set().union(*(rel._bigrams(t) for doc in programme for t in d["courses"][doc]))
    broader = {u: lit(s.get("broader")) or [] for u, s in store["skills"].items()}
    near = rel.neighbourhood(profile, broader)
    boiler = boiler or rel.boilerplate(d["postings"])
    mentions = mentions or rel.mention_rows(d["skill_mentions"], set(d["demand"]), boiler)
    jobs = {}
    for p in d["postings"]:
        job_skills = {k for k, v in mentions.get(p["posting_uid"], {}).items() if v["job"]}
        jobs[p["posting_uid"]] = rel.job_relevance(p, job_skills, d["occupations"].get(p["posting_uid"]), profile,
                                                   labels, course_bigrams, occ_skills, reuse, min_shared, near)
    state = {u: j["relevance"] for u, j in jobs.items()}
    company = {p["posting_uid"]: p.get("company_key") for p in d["postings"]}
    eligible = {u for u, s in state.items() if s in rel.ELIGIBLE}
    positive = {u for u, s in state.items() if s in rel.POSITIVE}
    skills = {}
    for key, row in d["demand"].items():
        current = set(lit(row["posting_uids"]) or [])
        job_text = {u for u in current if mentions.get(u, {}).get(key, {}).get("job")}
        new = job_text & eligible
        strict = job_text & positive
        skills[key] = {
            "skill_key": key, "skill_label": row["skill_label"],
            "skill_relevance": rel.skill_relevance(key, profile, reuse, job_text, state),
            "reuse_level": reuse.get(key),
            "current": {"postings": len(current), "companies": len({company[u] for u in current}),
                        "support_state": row["support_state"]},
            "job_specific_postings": len(job_text),
            "boilerplate_only_postings": len(current - job_text),
            "new": {"postings": len(new), "companies": len({company[u] for u in new}),
                    "support_state": industry.support_state(len(new), len({company[u] for u in new}), d["cfg"])},
            "strict": {"postings": len(strict), "companies": len({company[u] for u in strict}),
                       "support_state": industry.support_state(len(strict), len({company[u] for u in strict}), d["cfg"])},
            "current_gap": (d["gaps"].get(key) or {}).get("classification"),
            "current_gap_v2": (d["gaps_v2"].get(key) or {}).get("classification_v2"),
            "excluded_postings_by_state": dict(Counter(state[u] for u in current - new)),
        }
    return {"profile": profile, "jobs": jobs, "skills": skills, "boiler": boiler, "mentions": mentions,
            "eligible": eligible, "positive": positive, "min_shared": min_shared, "near": near}


def trace(d, a, label):
    key = next((k for k, r in d["demand"].items() if r["skill_label"].lower() == label), None)
    if key is None:
        return {"label": label, "found": False}
    s = a["skills"][key]
    by = {p["posting_uid"]: p for p in d["postings"]}
    rows = []
    for u in sorted(lit(d["demand"][key]["posting_uids"])):
        p, j, m = by[u], a["jobs"][u], a["mentions"].get(u, {}).get(key, {})
        rows.append({"posting_uid": u, "title": p.get("job_title"), "company": p.get("company_name"),
                     "industry": p.get("company_industry"),
                     "occupation": (d["occupations"].get(u) or {}).get("occupation_label"),
                     "mention_text_kind": dict(m.get("states", {})), "job_relevance": j["relevance"],
                     "signals": {k: v["state"] for k, v in j["signals"].items()},
                     "counts_in_new_demand": u in a["eligible"] and bool(m.get("job")),
                     "counts_in_strict_demand": u in a["positive"] and bool(m.get("job"))})
    mp = d["esco_maps"].get(key) or {}
    return {"label": label, "found": True, "skill_key": key,
            "normalisation": {"esco_status": d["demand"][key].get("esco_status"),
                              "esco_label": mp.get("esco_pref_label") or mp.get("pref_label"),
                              "method": mp.get("method") or mp.get("mapping_method")},
            "skill_relevance": s["skill_relevance"], "reuse_level": s["reuse_level"],
            "current": s["current"], "new": s["new"], "current_gap": s["current_gap"],
            "current_gap_v2": s["current_gap_v2"], "strict": s["strict"], "postings": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=json.loads((REPO / "data/gold/knowledge/latest_run.json").read_text())["run_id"])
    args = ap.parse_args()
    d = load(args.run)
    a = audit(d)
    out = REPO / "data/experiments/relevance" / args.run
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "job_relevance.jsonl", "w") as fh:
        for u in sorted(a["jobs"]):
            fh.write(json.dumps(a["jobs"][u], sort_keys=True) + "\n")
    with open(out / "skill_relevance.jsonl", "w") as fh:
        for k in sorted(a["skills"]):
            fh.write(json.dumps(a["skills"][k], sort_keys=True) + "\n")
    seg = Counter(s for rows in a["boiler"].values() for _, _, s, _ in rows)
    ment = Counter(st for per in a["mentions"].values() for v in per.values() for st, n in v["states"].items()
                   for _ in range(n))
    states = Counter(j["relevance"] for j in a["jobs"].values())
    sens = {}
    for k in (1, 2, 3):
        b = audit(d, k, a["boiler"], a["mentions"])
        sens[k] = {"states": dict(Counter(j["relevance"] for j in b["jobs"].values())), "eligible": len(b["eligible"]),
                   "eligible_strict": len(b["positive"]),
                   "skills_supported_or_high": sum(1 for s in b["skills"].values()
                                                   if s["new"]["support_state"] in ("SUPPORTED", "HIGH_SUPPORT"))}
    sk = a["skills"].values()
    support_now = Counter(s["current"]["support_state"] for s in sk)
    support_new = Counter(s["new"]["support_state"] for s in sk)
    support_strict = Counter(s["strict"]["support_state"] for s in sk)
    recs = []
    for r in d["recommendations"]:
        s = a["skills"].get(r["skill_key"])
        if s:
            recs.append({"skill": s["skill_label"], "action": r.get("action_type"),
                         "current_support": s["current"]["support_state"], "new_support": s["new"]["support_state"],
                         "strict_support": s["strict"]["support_state"],
                         "skill_relevance": s["skill_relevance"]})
    summary = {
        "run_id": args.run, "method": rel.METHOD, "occupation_min_shared": a["min_shared"],
        "programme_documents": sorted(doc for doc, r in d["roles"].items() if r in ("TARGET", "PREVIOUS_VERSION", "REFERENCE")),
        "programme_profile_skills": len(a["profile"]),
        "postings": len(a["jobs"]), "job_relevance": dict(states), "eligible_postings": len(a["eligible"]),
        "signals": {k: dict(Counter(j["signals"][k]["state"] for j in a["jobs"].values()))
                    for k in ("skills", "occupation", "title")},
        "segments": dict(seg), "skill_mentions_by_text_kind": dict(ment),
        "skills_in_demand": len(a["skills"]),
        "skill_relevance": dict(Counter(s["skill_relevance"] for s in sk)),
        "support_current": dict(support_now), "support_new": dict(support_new),
        "eligible_postings_strict": len(a["positive"]), "support_strict": dict(support_strict),
        "programme_neighbourhood_skills": len(a["near"]),
        "skills_entering_demand_new": sum(1 for s in sk if s["new"]["postings"] > 0),
        "skills_excluded_new": sum(1 for s in sk if s["new"]["postings"] == 0),
        "skills_losing_supported_status": sorted(
            s["skill_label"] for s in sk if s["current"]["support_state"] in ("SUPPORTED", "HIGH_SUPPORT")
            and s["new"]["support_state"] not in ("SUPPORTED", "HIGH_SUPPORT")),
        "recommendations": recs, "sensitivity_occupation_min_shared": sens,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    traces = [trace(d, a, t) for t in TRACE_LABELS]
    (out / "traces.json").write_text(json.dumps(traces, indent=2, sort_keys=True))
    print(json.dumps({k: summary[k] for k in ("job_relevance", "eligible_postings", "eligible_postings_strict",
                                               "skill_relevance", "support_current", "support_new",
                                               "support_strict")}, indent=1))
    print("written", out)


if __name__ == "__main__":
    main()
