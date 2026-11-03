#!/usr/bin/env python3
"""
Release QA of the evidence-supported gaps and the issued recommendations (read-only; changes nothing).

  python3 scripts/audit/release_gap_qa.py [--run <run_id>] [--db <database>] [--out data/evaluation/release_gap_qa_<run>.json]

For every confirmed gap (intelligence_stage.is_confirmed_gap) the complete chain is re-derived from the run's own files
and checked against the DECLARED rules (engine_config.json), never against new ones:

  postings -> skill mentions -> normalized skill -> taxonomy mapping -> demand (posting/company counts and the support
  thresholds) -> curriculum coverage (target-curriculum evidence) -> gap class v2 -> evidence sufficiency
  (not REVIEW_REQUIRED, identity not ambiguous) -> recommendation -> evidence trace (the API's own function)

A gap that fails a declared rule is reported HOLD; nothing is changed here. The release counts are read from GOLD and,
when a database is given, from the published rows.
"""
import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.knowledge_engine.intelligence_stage import is_confirmed_gap  # noqa: E402
from app.services import intelligence_service as isv  # noqa: E402

SUPPORTED = ("SUPPORTED", "HIGH_SUPPORT")
from app.knowledge_engine.intelligence_stage import WITHHELD_FOR_REVIEW_CODES as WITHHELD  # noqa: E402


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()] if Path(p).exists() else []


def js(p, default=None):
    return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default


def expected_support(n_postings, n_companies, cfg):
    s = cfg["industry"]["support"]
    if n_postings >= s["high_support_min_postings"] and n_companies >= s["high_support_min_companies"]:
        return "HIGH_SUPPORT"
    if n_postings >= s["supported_min_postings"] and n_companies >= s["supported_min_companies"]:
        return "SUPPORTED"
    if n_postings >= s["observed_min_postings"]:
        return "OBSERVED"
    return "INSUFFICIENT_EVIDENCE"


def db_value(db, sql):
    """The standard libpq environment first (a developer's own PostgreSQL, e.g. Homebrew on the Mac), then the
    `postgres` OS user (the development container)."""
    for cmd in (["psql", "-d", db, "-tAc", sql], ["su", "postgres", "-c", f'psql -d {db} -tAc "{sql}"']):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if out.returncode == 0:
                return out.stdout.strip()
        except Exception:  # noqa: BLE001
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run")
    ap.add_argument("--db")
    ap.add_argument("--out")
    a = ap.parse_args()
    gold = ROOT / "data/gold/knowledge"
    run = a.run or js(gold / "latest_run.json")["run_id"]
    D = gold / run
    cfg = js(ROOT / "backend/app/knowledge_engine/engine_config.json")
    rep = js(D / "run_report.json", {})
    ir = isv.load(run)

    postings = {p["posting_uid"]: p for p in jl(D / "industry/postings.jsonl")}
    mentions = jl(D / "industry/skill_mentions.jsonl")
    demand = {d["skill_key"]: d for d in jl(D / "industry/industry_demand.jsonl")}
    skills = {s["skill_key"]: s for s in jl(D / "industry/skills.jsonl")}
    gaps = jl(D / "intelligence/skill_gaps_v2.jsonl")
    depth = defaultdict(list)
    for r in jl(D / "intelligence/coverage_depth.jsonl"):
        depth[r["skill_key"]].append(r)
    recs = {r["skill_key"]: r for r in jl(D / "industry/recommendations.jsonl")}
    sups = jl(D / "industry/recommendation_suppressions.jsonl")
    scope = js(D / "industry/population_scope.json", {})

    by_skill = defaultdict(list)
    for m in mentions:
        by_skill[m.get("skill_key")].append(m)

    rows, holds = [], []
    for g in gaps:
        if not is_confirmed_gap(g):
            continue
        k, problems = g["skill_key"], []
        d = demand.get(k) or {}
        ms = [m for m in by_skill.get(k, []) if m.get("source_type") == "job_posting"]
        counted = set(d.get("posting_uids") or [])
        # 1 postings -> mentions: every counted posting exists, is eligible and carries a mention of this skill
        missing_posting = [u for u in counted if u not in postings]
        with_mention = {m["source_uid"] for m in ms}
        counted_without_mention = sorted(counted - with_mention)
        bad_context = [m["mention_uid"] for m in ms if m["source_uid"] in counted
                       and m["raw_mention"].lower() not in (m.get("context") or "").lower()]
        if missing_posting:
            problems.append(f"{len(missing_posting)} counted postings not in the eligible population")
        if counted_without_mention:
            problems.append(f"{len(counted_without_mention)} counted postings without a mention")
        if bad_context:
            problems.append(f"{len(bad_context)} mentions whose context does not contain the mention")
        # 2 demand: counts and the declared thresholds
        companies = {postings[u].get("company_key") for u in counted if u in postings}
        if d.get("posting_count") != len(counted):
            problems.append(f"posting_count {d.get('posting_count')} != {len(counted)} counted postings")
        exp = expected_support(len(counted), len(companies), cfg)
        if exp != d.get("support_state") or d.get("support_state") not in SUPPORTED:
            problems.append(f"support_state {d.get('support_state')} but thresholds give {exp}")
        # 3 taxonomy / identity
        sk = skills.get(k) or {}
        if (sk.get("identity_state") or sk.get("identity")) == "AMBIGUOUS":
            problems.append("ambiguous skill identity")
        # 4 curriculum coverage and gap rule
        if g["classification_v2"] not in ("PARTIAL", "MISSING") or g.get("evidence_status") == "REVIEW_REQUIRED":
            problems.append("gap class / evidence status not a confirmed gap")
        # 5 recommendation
        rec = recs.get(k)
        sup = next((s for s in sups if s.get("skill_key") == k), None)
        rec_state = rec["recommendation_state"] if rec else (
            "WITHHELD_FOR_REVIEW" if sup and any((r or {}).get("code") in WITHHELD for r in sup.get("reasons") or [])
            else "NOT_RECOMMENDED" if sup else "NONE")
        if rec is None:
            problems.append(f"no recommendation issued ({rec_state})")
        elif rec.get("gap_uid") != g.get("gap_uid"):
            problems.append("recommendation points to another gap")
        # 6 evidence trace through the API's own function
        tr = isv.evidence_trace(ir, k)
        t = (tr.get("trace") or {})
        trace_ok = bool(t.get("job_postings")) and bool(t.get("industry_demand")) and "curriculum" in t and bool(t.get("gap"))
        if not trace_ok:
            problems.append("evidence trace incomplete")
        cur = t.get("curriculum") or {}
        raw_forms = Counter(m["raw_mention"] for m in ms if m["source_uid"] in counted)
        titles = Counter((postings[u].get("job_title") or "") for u in counted if u in postings)
        row = {
            "skill": g["skill_label"], "skill_key": k,
            "eligible_postings": d.get("eligible_postings"),
            "demand": f'{d.get("posting_count")} postings / {len(companies)} companies ({d.get("posting_prevalence_pct")} %)',
            "support_state": d.get("support_state"),
            "qualification_only_postings": d.get("qualification_only_postings"),
            "taxonomy": f'{(t.get("esco") or {}).get("status")} ({(t.get("esco") or {}).get("mapping_method")})',
            "curriculum_coverage": f'{cur.get("target_courses_with_skill", 0)} target course(s) '
                                   f'{cur.get("target_course_codes") or []}, {len(cur.get("target_topic_evidence") or [])} topic span(s)',
            "coverage_level": g.get("coverage_level"),
            "gap_state": g["classification_v2"],
            "evidence_state": g.get("evidence_status"),
            "recommendation_state": rec_state,
            "recommendation_action": (rec or {}).get("action_type"),
            "evidence_trace_available": trace_ok,
            "mention_forms": dict(raw_forms.most_common(6)),
            "example_job_titles": [x for x, _ in titles.most_common(5)],
            "verdict": "HOLD" if problems else "CONFIRMED",
            "problems": problems,
        }
        rows.append(row)
        if problems:
            holds.append(g["skill_label"])

    # recommendations
    rec_rows = []
    for k, r in recs.items():
        g = next((x for x in gaps if x["skill_key"] == k), {})
        d = demand.get(k) or {}
        tr = (isv.evidence_trace(ir, k).get("trace") or {})
        counted = set(d.get("posting_uids") or [])
        titles = [postings[u].get("job_title") or "" for u in counted if u in postings]
        rec_rows.append({
            "skill": r["skill_label"], "action": r["action_type"], "state": r["recommendation_state"],
            "target_courses": r.get("target_course_codes") or [], "support_state": r.get("support_state"),
            "industry_evidence": d.get("statement"),
            "gap": f'{g.get("classification_v2")} / {g.get("coverage_level")} / {g.get("evidence_status")}',
            "is_confirmed_gap": is_confirmed_gap(g) if g else False,
            "reason": (r.get("rule_reasons") or [""])[0],
            "uncertainty": r.get("uncertainty") or [],
            "evidence_trace_available": bool(tr.get("job_postings")),
            "example_job_titles": sorted(Counter(titles), key=lambda x: -Counter(titles)[x])[:5],
            "scope_statement": scope.get("representativeness_warning"),
        })

    supported = sum(1 for d in demand.values() if d.get("support_state") in SUPPORTED)
    withheld = [s for s in sups if any((r or {}).get("code") in WITHHELD for r in s.get("reasons") or [])]
    occ = js(D / "industry_v2/occupation_summary.json", {}) or {}
    peers = js(D / "peers/peer_status.json", {}) or {}
    pops = (js(D / "industry_v2/temporal_populations.json", {}) or {}).get("populations", [])
    counts = {
        "job_postings": scope.get("eligible_postings"),
        "judgeable_skills (SUPPORTED + HIGH_SUPPORT demand)": supported,
        "confirmed_gaps": len(rows),
        "gaps_held_for_review (supported demand, evidence disagrees)": sum(
            1 for g in gaps if g["classification_v2"] in ("PARTIAL", "MISSING") and g["support_state"] in SUPPORTED
            and g.get("evidence_status") == "REVIEW_REQUIRED"),
        "recommendations_issued": len(recs),
        "recommendations_withheld_for_review": len(withheld),
        "not_recommended (suppressed with a reason)": len(sups) - len(withheld),
        "peer_curricula_available": [p.get("institution") for p in peers.get("available", [])],
        "peer_curricula_missing": [p.get("name") for p in peers.get("missing", [])],
        "occupation_established_postings": occ.get("established"),
        "trend_status_by_population": {p.get("population_id"): p.get("trend_status") for p in pops},
    }
    db = {}
    if a.db:
        R = f"run_id='{run}'"
        db = {"eligible_postings": db_value(a.db, f"select eligible_postings from knowledge.population_scope where {R} and segment='ALL_POSTINGS'"),
              "judgeable_skills": db_value(a.db, f"select count(*) from knowledge.industry_demand where {R} and support_state in ('SUPPORTED','HIGH_SUPPORT')"),
              "gap_v2_partial_or_missing": db_value(a.db, f"select count(*) from knowledge.skill_gap_v2 where {R} and classification_v2 in ('PARTIAL','MISSING')"),
              "recommendation_by_state": db_value(a.db, f"select string_agg(state || '=' || n, ', ' order by state) from (select state, count(*) n from knowledge.recommendation where {R} group by 1) x"),
              "occupation_established_postings (v2 resolver, title + description context; the reported figure)":
                  db_value(a.db, f"select count(*) from knowledge.occupation_resolution where {R} and established"),
              "occupation_established_postings_v1 (title-only resolver kept for comparison)":
                  db_value(a.db, f"select count(*) from knowledge.posting_occupation where {R} and established")}
    out = {"run_id": run, "content_digest": rep.get("content_digest"), "counts": counts, "database": db,
           "gaps": rows, "gaps_held": holds, "recommendations": rec_rows,
           "rules": {"support": cfg["industry"]["support"],
                     "confirmed_gap": "classification_v2 in PARTIAL/MISSING, support_state in SUPPORTED/HIGH_SUPPORT, "
                                      "evidence_status != REVIEW_REQUIRED (intelligence_stage.is_confirmed_gap)"}}
    path = Path(a.out or ROOT / f"data/evaluation/release_gap_qa_{run}.json")
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"run": run, "counts": counts, "database": db, "gaps_held": holds}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
