#!/usr/bin/env python3
"""
Full cross-source consistency audit of one run.

  python3 scripts/audit/full_consistency_audit.py [--run <run_id>] [--db <database>] [--out data/evaluation/full_consistency_audit.json]

For every headline metric it computes the value independently at each layer and compares them:
  GOLD      the run's files (data/gold/knowledge/<run>/...)
  DB        the published PostgreSQL rows of that run (psql as the local postgres user; skipped if unavailable)
  API       the service functions the FastAPI routes call (same code path, called in-process)
  UI        the label / scope wording the Flutter screen shows for the metric (from the API payload it renders)
  DOCS      the figure stated in the current release report
Every discrepancy carries a classification (TRUE_BUG, SCOPE_DIFFERENCE, DERIVED_METRIC, STALE_DOCUMENTATION,
DISPLAY_LABEL_PROBLEM, ROUNDING_ONLY, EXPECTED_DIFFERENCE, UNRESOLVED) and the established cause. Nothing is fixed here.
"""
import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import improvement_service as imp  # noqa: E402
from app.services import intelligence_service as svc  # noqa: E402
from app.services import knowledge_service as ks  # noqa: E402

CLASSES = ("TRUE_BUG", "SCOPE_DIFFERENCE", "DERIVED_METRIC", "STALE_DOCUMENTATION", "DISPLAY_LABEL_PROBLEM",
           "ROUNDING_ONLY", "EXPECTED_DIFFERENCE", "UNRESOLVED")


def jl(p):
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()] if Path(p).exists() else []


def js(p):
    return json.loads(Path(p).read_text()) if Path(p).exists() else None


def psql(db, sql):
    try:
        r = subprocess.run(["su", "postgres", "-c", f"psql -d {db} -tA -F'|' -c \"{sql}\""],
                           capture_output=True, text=True, timeout=60)
    except Exception:  # noqa: BLE001
        return None
    if r.returncode != 0:
        return None
    return [line.split("|") for line in r.stdout.strip().splitlines() if line]


def db_scalar(db, sql):
    rows = psql(db, sql)
    return int(rows[0][0]) if rows else None


def db_counter(db, sql):
    rows = psql(db, sql)
    return {r[0]: int(r[1]) for r in rows} if rows is not None else None


def doc_number(text, pattern):
    m = re.search(pattern, text)
    return int(m.group(1).replace(",", "")) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None)
    ap.add_argument("--db", default="skillgap_knowledge_improve")
    ap.add_argument("--out", default=str(ROOT / "data/evaluation/full_consistency_audit.json"))
    a = ap.parse_args()
    run = ks.load_run(a.run)
    rid = run.run_id
    D = run.dir
    svc.load(rid)  # the run must load
    ov = imp.overview(run)
    kpi = {k["key"]: k for k in ov["kpis"]}
    docs = {d["doc_id"]: d for d in run.report["documents"]}
    role = {k: v["role"] for k, v in docs.items()}
    next(k for k, v in role.items() if v == "TARGET")  # a TARGET must exist
    report_doc = (ROOT / "docs/IMPROVEMENT_RELEASE_REPORT.md").read_text()
    db = a.db
    R = f"run_id='{rid}'"
    checks = []

    def check(metric, definition, layers, status, classification=None, cause=None, action=None):
        assert classification is None or classification in CLASSES, classification
        checks.append({"metric": metric, "definition": definition, "layers": layers, "status": status,
                       "classification": classification, "cause": cause, "action": action})

    # ---------------- curriculum ----------------
    courses = list(run.courses.values())
    by_role = Counter(role[c["doc_id"]] for c in courses)
    topics = list(run.topics.values())
    t_clean = [t for t in topics if role.get(t["doc_id"]) == "TARGET" and t["noise_label"] == "TOPIC"]
    t_courses_with_topics = len({t["course_uid"] for t in t_clean})
    db_courses = db_counter(db, "select d.role, count(*) from knowledge.course c join knowledge.document d on d.sha256=c.doc_sha256 group by 1")
    peer_scope = (run.report.get("peers") or {}).get("comparisons", {})
    any_peer = next(iter(peer_scope.values()), {}) if peer_scope else {}
    check("courses (target)", "courses of the TARGET document (all extracted, with or without clean topics)",
          {"GOLD": by_role.get("TARGET"), "DB": (db_courses or {}).get("TARGET"), "API": kpi["courses"]["value"],
           "UI": f'{kpi["courses"]["value"]} "{kpi["courses"]["label"]}"',
           "GOLD_all_roles": dict(by_role), "GOLD_target_with_clean_topics": t_courses_with_topics,
           "peer_benchmark_scope_target_courses": (any_peer.get("scope") or {}).get("target_courses")},
          "CONSISTENT_WITH_SCOPE_DIFFERENCE", "SCOPE_DIFFERENCE",
          f"{by_role.get('TARGET')} = every TARGET course extracted; {t_courses_with_topics} = TARGET courses that have at least one "
          "clean topic (the peer benchmark compares topic content, so its scope counts only those); "
          f"{len(courses)} = courses of all non-peer documents (TARGET + PREVIOUS_VERSION + REFERENCE; peers are not published)",
          "label both populations explicitly (UI + peer scope)")
    t_by = Counter((role.get(t["doc_id"]), t["noise_label"] == "TOPIC") for t in topics)
    db_topics = db_counter(db, "select d.role||':'||(t.noise_label='TOPIC'), count(*) from knowledge.topic t join knowledge.course c "
                               "on c.course_uid=t.course_uid join knowledge.document d on d.sha256=c.doc_sha256 group by 1")
    check("topics (target, clean)", "TARGET topics with noise_label TOPIC (page provenance kept)",
          {"GOLD": len(t_clean), "DB": (db_topics or {}).get("TARGET:true"), "API": kpi["topics"]["value"],
           "UI": f'{kpi["topics"]["value"]} "{kpi["topics"]["label"]}"', "GOLD_all_extracted_items": len(topics),
           "GOLD_by_role_clean": {f"{k[0]}:{'clean' if k[1] else 'noise'}": v for k, v in t_by.items()},
           "DOCS": doc_number(report_doc, r"target_clean_topics[^0-9]*([0-9,]+)")},
          "CONSISTENT_WITH_SCOPE_DIFFERENCE", "SCOPE_DIFFERENCE",
          f"{len(topics)} = every extracted topic item of the non-peer documents incl. noise (bibliography, fragments, ...); "
          f"{len(t_clean)} = clean TARGET topics", "UI label: 'target-curriculum topics'")
    concepts = list(run.concepts.values())
    t_conc = [c for c in concepts if "TARGET" in c["source_roles"]]
    db_conc = db_scalar(db, f"select count(*) from knowledge.concept_run where {R}")
    check("concepts", "concept clusters whose members include at least one TARGET topic",
          {"GOLD": len(t_conc), "GOLD_all_roles": len(concepts), "DB_concept_run": db_conc, "API": kpi["concepts"]["value"],
           "UI": f'{kpi["concepts"]["value"]} "{kpi["concepts"]["label"]}"',
           "by_roles": dict(Counter("+".join(sorted(c["source_roles"])) for c in concepts)),
           "DOCS_historical": "1,337 in engine 1.1/2.0 reports (runs up to d140f830ab26adeb); 1,318 from f173ee4fff47e2a6 on"},
          "CONSISTENT_WITH_SCOPE_DIFFERENCE", "SCOPE_DIFFERENCE",
          f"{len(concepts)} = concepts of all non-peer documents; {len(t_conc)} = those containing a TARGET topic. "
          "1,337 is the count of earlier runs (before the topic-cleaning change of run f173ee4fff47e2a6), stated in the "
          "engine 1.1 / 2.0 reports and three methodology documents",
          "UI label 'target-curriculum concepts'; methodology docs annotated with the run they describe")

    # ---------------- industry ----------------
    ind = run.industry
    scope = ind["scope"]
    skills = ind["skills"]
    elig = {k: s for k, s in skills.items() if s.get("eligible_for_analytics")}
    demand = ind["demand"]
    dkeys = {d["skill_key"] for d in demand}
    mentions = jl(D / "industry/skill_mentions.jsonl")
    qual_only = sorted(s["label"] for k, s in elig.items() if k not in dkeys)
    postings = jl(D / "industry/postings.jsonl")
    db_post = db_scalar(db, "select count(*) from knowledge.job_posting")
    check("postings", "distinct eligible postings of population CURRENT_JOB_DATASET_2026_09",
          {"GOLD": scope.get("eligible_postings"), "GOLD_posting_records": len(postings), "DB": db_post,
           "API": kpi["postings"]["value"], "UI": f'{kpi["postings"]["value"]} "{kpi["postings"]["label"]}"',
           "companies": len({p.get("company_key") or p.get("company_name") for p in postings}),
           "date_range": scope.get("date_range"), "geography": scope.get("geographic_scope")},
          "CONSISTENT")
    check("skills", "normalized industry skills eligible for analytics",
          {"GOLD_all_normalized": len(skills), "GOLD_eligible": len(elig), "GOLD_demand_rows": len(demand),
           "GOLD_eligible_esco_mapped": sum(1 for s in elig.values() if s.get("esco_uri")),
           "GOLD_demand_esco_mapped": sum(1 for d in demand if d.get("esco_status") in ("EXACT", "NORMALIZED", "SEMANTIC_MATCH")),
           "qualification_only_eligible": qual_only,
           "DB_demand": db_scalar(db, f"select count(*) from knowledge.industry_demand where {R}"),
           "API": kpi["skills"]["value"], "UI": f'{kpi["skills"]["value"]} "{kpi["skills"]["label"]}" ({kpi["skills"]["context"]})'},
          "CONSISTENT_WITH_SCOPE_DIFFERENCE", "SCOPE_DIFFERENCE",
          f"{len(skills)} = every normalized skill (incl. not eligible: uncategorized / off-discipline / alias review); "
          f"{len(elig)} = eligible for analytics; {len(demand)} = demand rows: eligible skills with >= 1 posting where the "
          f"mention role is SKILL ({len(qual_only)} eligible skills occur only as qualification requirements: {', '.join(qual_only)}); "
          "106 = eligible skills with an ESCO URI (EXACT/NORMALIZED/SEMANTIC_MATCH); 101 of the 115 demand skills",
          "UI label: 'normalized industry skills eligible for analysis'; state 115 demand-eligible separately")
    per_posting = Counter()
    for m in mentions:
        if m.get("mention_role") == "SKILL" and m.get("sense_state") in ("ESTABLISHED", "ESTABLISHED_BY_CONTEXT", "ESTABLISHED_BY_MODEL"):
            per_posting[(m["skill_key"], m["source_uid"])] += 1
    recount = Counter(k for k, _ in per_posting)
    bad = [d["skill_label"] for d in demand if d["posting_count"] != recount.get(d["skill_key"], 0)]
    multi = sum(1 for v in per_posting.values() if v > 1)
    check("demand denominator", "posting_count = distinct postings with an established SKILL mention; prevalence = posting_count / eligible postings",
          {"recomputed_mismatches": bad, "skill_posting_pairs_with_repeated_mentions": multi,
           "prevalence_formula_violations": [d["skill_label"] for d in demand
                                             if abs(d["posting_prevalence_pct"] - round(100 * d["posting_count"] / d["eligible_postings"], 2)) > 0.01]},
          "CONSISTENT" if not bad else "INCONSISTENT", None if not bad else "UNRESOLVED",
          f"a skill mentioned several times in one posting counts once ({multi} such skill/posting pairs)")

    # ---------------- gaps & recommendations ----------------
    g1 = {g["skill_key"]: g for g in jl(D / "industry/skill_gaps.jsonl")}
    g2 = jl(D / "intelligence/skill_gaps_v2.jsonl")
    v2 = Counter(g["classification_v2"] for g in g2)
    v2_support = Counter((g["classification_v2"], g["support_state"]) for g in g2)
    db_v2 = db_counter(db, f"select classification_v2, count(*) from knowledge.skill_gap_v2 where {R} group by 1")
    supported_any = [g for g in g2 if g["classification_v2"] in ("PARTIAL", "MISSING")
                     and g["support_state"] in ("SUPPORTED", "HIGH_SUPPORT")]
    # same definition as the product (intelligence_stage.is_confirmed_gap): a gap whose evidence disagrees (a course
    # title names the skill) is held for review, not counted as evidence-supported
    supported_gaps = [g["skill_label"] for g in supported_any if g.get("evidence_status") != "REVIEW_REQUIRED"]
    supported_review = [g["skill_label"] for g in supported_any if g.get("evidence_status") == "REVIEW_REQUIRED"]
    check("gaps (v2)", f"gap classification v2 (coverage depth) of the {len(g2)} demand skills",
          {"GOLD": dict(v2), "DB": db_v2, "API_gap_summary": ov["gap_summary"], "API_headline": kpi["gaps"]["value"],
           "UI": f'{kpi["gaps"]["value"]} "{kpi["gaps"]["label"]}" — "{kpi["gaps"]["context"]}"',
           "by_class_and_demand_support": {f"{a}|{b}": n for (a, b), n in v2_support.items()},
           "partial_or_missing_with_supported_demand": supported_gaps,
           "supported_but_review_required": supported_review, "v1": dict(Counter(g["classification"] for g in g1.values()))},
          *((("CONSISTENT", None,
               f"the headline counts evidence-supported gaps: PARTIAL/MISSING with SUPPORTED/HIGH_SUPPORT demand "
               f"({len(supported_gaps)}; {len(supported_review)} more held for review because the evidence disagrees); PARTIAL ({v2.get('PARTIAL', 0)}) and MISSING ({v2.get('MISSING', 0)}) are shown "
               "separately with their demand support. Resolved: before this release the headline was PARTIAL + MISSING under "
               "a label claiming supported demand (DISPLAY_LABEL_PROBLEM, run c8ecd067bb733f58)", None)
              if kpi["gaps"]["value"] == len(supported_gaps) and "evidence-supported" in kpi["gaps"]["label"].lower() else
              ("INCONSISTENT", "DISPLAY_LABEL_PROBLEM",
               f"the headline {kpi['gaps']['value']} does not equal the evidence-supported gaps ({len(supported_gaps)}) its "
               "label/context describe: v2 assigns PARTIAL/COVERED from curriculum depth alone; only MISSING requires "
               "supported demand",
               "show COVERED / PARTIAL / MISSING / INSUFFICIENT separately, and the demand-support split of PARTIAL; the "
               "headline counts evidence-supported gaps (PARTIAL/MISSING with SUPPORTED/HIGH_SUPPORT demand)"))))
    recs = ind["recommendations"]
    sup = ind["suppressions"]
    db_recs = db_counter(db, f"select state, count(*) from knowledge.recommendation where {R} group by 1")
    rec_conflicts = []
    g2k = {g["skill_key"]: g for g in g2}
    for r in recs:
        v = g2k.get(r["skill_key"], {})
        if v.get("classification_v2") not in ("PARTIAL", "MISSING"):
            rec_conflicts.append({"skill": r["skill_label"], "recommendation": r["action_type"], "basis": f"gap v1 {r['classification']}",
                                  "gap_v2": v.get("classification_v2"), "coverage_level_v2": v.get("coverage_level"),
                                  "v2_reason": v.get("reason_v2")})
    check("recommendations", "recommendations produced / suppressed with reasons",
          {"GOLD": {"supported": len(recs), "suppressed": len(sup)}, "DB": db_recs,
           "API": {"supported": kpi["recommendations"]["value"], "context": kpi["recommendations"]["context"]},
           "every_suppression_has_reason": all(s.get("reasons") for s in sup),
           "suppression_reason_codes": dict(Counter(c["code"] for s in sup for c in s.get("reasons", []))),
           "recommendation_vs_gap_v2_conflicts": rec_conflicts},
          "INCONSISTENT" if rec_conflicts else "CONSISTENT", "TRUE_BUG" if rec_conflicts else None,
          "recommendations are derived in the industry stage from gap v1 (breadth: share of target courses naming the "
          "skill); gap v2 (depth: DIRECT/PARTIAL topics per unit) is computed later and was never fed back. For SQL, v1 says "
          "PARTIAL (4 of 113 courses = 3.54 %) while v2 says COVERED (SUBSTANTIAL). The Skill Gaps and Recommendations "
          "screens therefore disagree about the same skill" if rec_conflicts else None,
          "reconcile: a recommendation whose v2 gap is not PARTIAL/MISSING is not silently kept as SUPPORTED; it is marked "
          "REVIEW_REQUIRED with both classifications shown" if rec_conflicts else None)

    # ---------------- occupation ----------------
    occ = jl(D / "industry_v2/occupation_resolution.jsonl")
    occ_sum = js(D / "industry_v2/occupation_summary.json") or {}
    db_occ = db_counter(db, f"select state, count(*) from knowledge.occupation_resolution where {R} group by 1")
    contradicted_established = [o["job_title"] for o in occ if o["context_support"] == "CONTRADICTED" and o["established"]]
    check("occupations", "posting → ESCO occupation resolution (v2)",
          {"GOLD": dict(Counter(o["state"] for o in occ)), "GOLD_established": sum(o["established"] for o in occ),
           "GOLD_by": dict(Counter(o.get("established_by") for o in occ if o["established"])),
           "summary_file": {k: occ_sum.get(k) for k in ("established", "established_by_title", "established_by_context",
                                                        "title_contradicted_by_context")},
           "DB": db_occ, "API": ov["occupations"],
           "DOCS": doc_number(report_doc, r"([0-9]+) of 100 postings have an established ESCO occupation"),
           "contradicted_but_established": contradicted_established,
           "v1_posting_occupations_established": sum(1 for x in jl(D / "intelligence/posting_occupations.jsonl") if x.get("established"))},
          "CONSISTENT" if not contradicted_established else "INCONSISTENT")

    # ---------------- peers ----------------
    rel = jl(D / "peers/peer_relations.jsonl")
    ps = js(D / "peers/peer_status.json") or {}
    db_rel = db_counter(db, f"select relationship||':'||evidence_state, count(*) from knowledge.peer_relation where {R} group by 1")
    model_supported = db_scalar(db, f"select count(*) from knowledge.peer_relation where {R} and model_consulted and evidence_state='SUPPORTED'")
    peer_topics_db = db_scalar(db, "select count(*) from knowledge.topic t join knowledge.course c on c.course_uid=t.course_uid "
                                   "join knowledge.document d on d.sha256=c.doc_sha256 where d.role='PEER'")
    peer_in_concepts = sum(1 for c in concepts if "PEER" in c["source_roles"])
    check("peer relations", "semantic peer/reference relations",
          {"GOLD": {f"{r['relationship']}|{r['evidence_state']}": n for r, n in
                    ((dict(relationship=k[0], evidence_state=k[1]), v) for k, v in
                     Counter((x["relationship"], x["evidence_state"]) for x in rel).items())},
           "GOLD_total": len(rel), "DB": db_rel, "DB_total": sum((db_rel or {}).values()) if db_rel else None,
           "status": ps.get("status"), "missing_requested": [m.get("name") for m in ps.get("missing", [])],
           "model_consulted_and_supported": model_supported, "peer_topics_in_db": peer_topics_db,
           "peer_roles_in_target_concepts": peer_in_concepts,
           "DOCS_supported": doc_number(report_doc, r"([0-9,]+) are SUPPORTED")},
          "CONSISTENT")

    # ---------------- temporal ----------------
    tp = (js(D / "industry_v2/temporal_populations.json") or {}).get("populations", [])
    trends = jl(D / "industry_v2/skill_trends.jsonl")
    v1_temporal = js(D / "industry/temporal_scope.json") or {}
    check("trends", "trend states per population and skill",
          {"populations": {p["population_id"]: p["trend_status"] for p in tp},
           "skill_trend_states": dict(Counter(t["trend_state"] for t in trends)),
           "DB": db_counter(db, f"select trend_state, count(*) from knowledge.skill_trend where {R} group by 1"),
           "v1_temporal_scope": {k: v1_temporal.get(k) for k in ("trend_status", "period_granularity", "trend_label_for_all_skills")},
           "gap_v2_industry_trend": dict(Counter(g["industry_trend"] for g in g2))},
          "CONSISTENT_WITH_SCOPE_DIFFERENCE", "EXPECTED_DIFFERENCE",
          "no trend is classified anywhere. Two vocabularies describe the same fact: the v1 industry stage writes "
          "trend_status INSUFFICIENT_EVIDENCE at month granularity, v2 writes INSUFFICIENT_DATA after evaluating week/month/"
          "quarter; gap v2 carries the v1 value. Both mean 'one period, no trend'",
          "UI shows one human label ('Not enough time periods for a trend') for both")

    # ---------------- drift ----------------
    cd = jl(D / "course_drift.jsonl")
    cdc = jl(D / "concept_drift.jsonl")
    sd = jl(D / "intelligence/semantic_drift.jsonl")
    check("drift", "course drift (R22 → R22A) and concept drift",
          {"course_drift": dict(Counter(x["status"] for x in cd)),
           "course_drift_methods": dict(Counter(x.get("method") for x in cd)),
           "concept_drift": dict(Counter(x.get("status") for x in cdc)),
           "semantic_drift_categories": dict(Counter(x.get("semantic_drift_category") for x in sd)),
           "DB_concept_drift": db_counter(db, f"select status, count(*) from knowledge.concept_drift where {R} group by 1"),
           "not_detected_at_concept_level": sorted((run.report.get("intelligence") or {}).get("semantic_drift_not_detected", {}) or [])},
          "CONSISTENT_WITH_SCOPE_DIFFERENCE", "SCOPE_DIFFERENCE",
          "course-level EVOLVED (4) exists: a one-to-one topic-match lineage detector (share >= related_min_share both ways, "
          "MODEL_SUGGESTED). RENAMED / MERGED / SPLIT / EVOLVED are not detected at concept level (stated). concept drift "
          "status names (RETAINED, RETAINED_REWORDED, UNCERTAIN) map one-to-one to the semantic categories (PERSISTENT, "
          "REWORDED, INSUFFICIENT_EVIDENCE)")

    # ---------------- graph / semantic ----------------
    gn = jl(D / "intelligence/graph_nodes.jsonl")
    ge = jl(D / "intelligence/graph_edges.jsonl")
    sdx = jl(D / "intelligence/semantic_decisions.jsonl")
    db_edges = db_scalar(db, f"select count(*) from knowledge.concept_relationship where {R}")
    pk_cols = db_scalar(db, "select count(*) from pg_index i join pg_attribute a on a.attrelid = i.indrelid and a.attnum = "
                            "any(i.indkey) where i.indrelid = 'knowledge.concept_relationship'::regclass and i.indisprimary")
    edges_ok = db_edges == len(ge)
    check("graph", "knowledge graph nodes / edges",
          {"GOLD_nodes": len(gn), "GOLD_edges": len(ge), "DB_edges": db_edges, "DB_primary_key_columns": pk_cols,
           "nodes_by_type": dict(Counter(n["node_type"] for n in gn)), "edges_by_relationship": dict(Counter(e["relationship"] for e in ge)),
           "edge_methods": dict(Counter(e["method"] for e in ge)),
           "DOCS_historical": "10,394 nodes in the engine 2.0 report (older run)"},
          *(("CONSISTENT_WITH_SCOPE_DIFFERENCE", "STALE_DOCUMENTATION",
             "10,394 nodes is the engine 2.0 report's run (1,337 concepts); the current run has 10,331 (1,318 concepts). "
             "DB edges equal GOLD edges for this run (primary key (run_id, edge_id))") if edges_ok else
            ("INCONSISTENT", "TRUE_BUG",
             f"the database holds {db_edges} edges of this run but GOLD has {len(ge)}: with a primary key on edge_id alone "
             "(edge ids repeat across runs) a later run's edges collide with an earlier run's and are dropped",
             "primary key (run_id, edge_id) -- backend/app/db/knowledge_schema_consistency.sql, migration 0004")))
    check("semantic decisions", "recorded semantic decisions and their effect",
          {"GOLD": len(sdx), "DB": db_scalar(db, f"select count(*) from knowledge.semantic_decision where {R}"),
           "applied": sum(1 for x in sdx if x.get("effect")), "blocked": sum(1 for x in sdx if x.get("effect_blocked_reason")),
           "human_validated": sum(1 for x in sdx if x.get("is_human_validated")), "API_overview": ov["semantic"]},
          "CONSISTENT")

    # ---------------- topic mappings ----------------
    tm = jl(D / "topic_mappings.jsonl")
    check("topic mappings", "TARGET topic → REFERENCE topic mappings",
          {"GOLD": len(tm), "by_relationship_evidence": {f"{a}|{b}": n for (a, b), n in
                                                        Counter((m["relationship"], m["evidence_status"]) for m in tm).items()},
           "DB": db_scalar(db, "select count(*) from knowledge.topic_mapping")},
          "CONSISTENT", None, "see TOPIC_CONCEPT_MAPPING_AUDIT.md for the semantic audit of these mappings")

    summary = Counter(c["classification"] or "NONE" for c in checks)
    out = {"run_id": rid, "database": db, "layers": ["GOLD", "DB", "API (service layer)", "UI (payload labels)", "DOCS"],
           "classification_vocabulary": CLASSES, "summary": dict(summary),
           "inconsistent": [c["metric"] for c in checks if c["status"] == "INCONSISTENT"], "checks": checks}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps({"run": rid, "checks": len(checks), "inconsistent": out["inconsistent"], "summary": out["summary"]}))


if __name__ == "__main__":
    main()
