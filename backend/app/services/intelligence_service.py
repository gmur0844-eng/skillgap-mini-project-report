"""
Read-only service over the engine-2.0 intelligence outputs (data/gold/knowledge/<run>/intelligence).

Every response carries:
  scope           which run, which documents, the job-posting population and its representativeness warning
  evidence_state  AVAILABLE / NOT_PRODUCED (with the reason) -- a run without these outputs never returns numbers
Nothing is recomputed here.
"""
from collections import Counter

from app.knowledge_engine.curriculum_scope import not_assessed
from app.services import knowledge_service as ks
from app.services.knowledge_service import _json, _jsonl, _page


class IntelligenceRun:
    def __init__(self, run):
        self.run = run
        d = run.dir / "intelligence"
        self.available = (d / "intelligence_report.json").exists()
        self.report = _json(d / "intelligence_report.json", {})
        self.files = d

    def rows(self, name):
        return _jsonl(self.files / name)

    def json(self, name):
        return _json(self.files / name)


def load(run_id=None):
    return IntelligenceRun(ks.load_run(run_id))


def _scope(ir):
    run = ir.run
    return {"run_id": run.run_id, "pipeline_version": run.report.get("pipeline_version"),
            "documents": [{"doc_id": d.get("doc_id"), "role": d.get("role")} for d in run.report.get("documents", [])]
            if isinstance(run.report.get("documents"), list) else None,
            "population_scope": ks._scope_header(run),
            "curriculum_scope": (run.report or {}).get("curriculum_scope") or not_assessed()}


def _envelope(ir, payload):
    if not ir.available:
        return {"evidence_state": "NOT_PRODUCED", "scope": _scope(ir),
                "reason": "this run has no intelligence outputs (engine < 2.0 or full ESCO not loaded)", "items": []}
    return {"evidence_state": "AVAILABLE", "scope": _scope(ir), **payload}


def _filter(rows, **eq):
    return [r for r in rows if all(v is None or r.get(k) == v for k, v in eq.items())]


# ---------------- /semantic ----------------
def semantic_concepts(ir, q=None, limit=100, offset=0):
    items = [ir.run._concept_summary(c) for c in ir.run.concepts.values()]
    if q:
        items = [c for c in items if q.lower() in (c.get("name") or "").lower()]
    return _envelope(ir, {"note": "CONCEPT = cluster of topics (TF-IDF, lexical); not an ESCO skill", **_page(items, limit, offset)})


def semantic_relationships(ir, relationship=None, limit=200, offset=0):
    items = _filter(ir.rows("graph_edges.jsonl"), relationship=relationship)
    return _envelope(ir, _page(items, limit, offset))


def semantic_decisions(ir, kind=None, state=None, limit=100, offset=0):
    items = _filter(ir.rows("semantic_decisions.jsonl"), candidate_kind=kind, decision_state=state)
    return _envelope(ir, {"adjudication": ir.report.get("semantic_adjudication"), **_page(items, limit, offset)})


def semantic_evidence(ir, node_id):
    edges = [e for e in ir.rows("graph_edges.jsonl") if node_id in (e["source"], e["target"])]
    # additive: labels of the node and its neighbours, from the run's own graph_nodes (no invented labels)
    ids = {node_id} | {e["source"] for e in edges} | {e["target"] for e in edges}
    nodes = {n["node_id"]: {"label": n.get("label"), "node_type": n.get("node_type")}
             for n in ir.rows("graph_nodes.jsonl") if n.get("node_id") in ids}
    return _envelope(ir, {"node_id": node_id, "edges": edges, "nodes": nodes})


def semantic_contradictions(ir):
    c = ir.json("graph_consistency.json") or {}
    return _envelope(ir, {"checks": c.get("checks"), "items": c.get("contradictions", []), "examples": c.get("examples")})


def semantic_review(ir, limit=100, offset=0):
    items = [d for d in ir.rows("semantic_decisions.jsonl") if d["relationship"] in ("AMBIGUOUS", "INSUFFICIENT_EVIDENCE")
             or d["decision_state"] in ("REVIEW_REQUIRED", "RULE_VERDICT_NO_MODEL")]
    return _envelope(ir, {"review_state": "REVIEW_AVAILABLE", "human_labels": 0, **_page(items, limit, offset)})


# ---------------- /curriculum (engine 2.0 additions) ----------------
def curriculum_topic_hierarchy(ir, course_uid=None, limit=200, offset=0):
    return _envelope(ir, {"stats": ir.report.get("topic_hierarchy"),
                          **_page(_filter(ir.rows("topic_hierarchy.jsonl"), course_uid=course_uid), limit, offset)})


def curriculum_coverage(ir, role=None, level=None, limit=200, offset=0):
    items = _filter(ir.rows("coverage_depth.jsonl"), role=role, coverage_level=level)
    return _envelope(ir, {"levels": ir.report.get("coverage_levels"), **_page(items, limit, offset)})


def curriculum_drift(ir, category=None, limit=200, offset=0):
    items = _filter(ir.rows("semantic_drift.jsonl"), semantic_drift_category=category)
    return _envelope(ir, {"categories": ir.report.get("semantic_drift_categories"),
                          "not_detected": ir.report.get("semantic_drift_not_detected"), **_page(items, limit, offset)})


def curriculum_course_drift(ir, status=None, limit=200, offset=0):
    rows = _jsonl(ir.run.dir / "course_drift.jsonl")
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return _envelope(ir, {"statuses": dict(sorted(counts.items())),
                          "excluded": ir.run.report.get("course_drift_excluded"),
                          "note": "course lineage (RENAMED/EVOLVED/MERGED/SPLIT) is shared-concept correspondence, "
                                  "not a statement of the institution's intent",
                          **_page(_filter(rows, status=status), limit, offset)})


def curriculum_programme_comparison(ir, level="course", status=None, limit=200, offset=0):
    """Two different programmes of one institution compared on the semesters both cover (e.g. a specialisation and the
    institution's general programme). Kept apart from curriculum changes: differences between programmes are not
    changes over time."""
    meta = ir.run.report.get("programme_comparison") or {"status": "NOT_APPLICABLE",
                                                         "relation": None}
    name = "concept_differences.jsonl" if level == "concept" else "course_differences.jsonl"
    rows = _jsonl(ir.run.dir / "programme_comparison" / name) if meta.get("status") == "ALLOWED" else []
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return _envelope(ir, {"comparison": meta, "level": "concept" if level == "concept" else "course",
                          "statuses": dict(sorted(counts.items())), **_page(_filter(rows, status=status), limit, offset)})


def curriculum_benchmark(ir):
    return _envelope(ir, {"benchmark": ir.json("peer_benchmark.json")})


# ---------------- /industry (engine 2.0 additions) ----------------
def industry_occupations(ir, status=None, limit=200, offset=0):
    return _envelope(ir, {"summary": ir.report.get("occupations"),
                          **_page(_filter(ir.rows("posting_occupations.jsonl"), status=status), limit, offset)})


def industry_trends(ir):
    return _envelope(ir, {"states": ir.report.get("industry_trends"), "items": ir.rows("industry_trends.jsonl")})


def industry_skill_taxonomy(ir, limit=200, offset=0):
    return _envelope(ir, _page(ir.rows("skill_taxonomy_context.jsonl"), limit, offset))


# ---------------- /intelligence ----------------
def gaps(ir, classification=None, limit=200, offset=0):
    demand = {d["skill_key"]: d for d in ((ir.run.industry or {}).get("demand") or [])}
    # the demand figures of the same run are attached for reading (posting count + denominator); nothing recomputed
    items = [dict(g, posting_count=demand.get(g["skill_key"], {}).get("posting_count"),
                  eligible_postings=demand.get(g["skill_key"], {}).get("eligible_postings"))
             for g in _filter(ir.rows("skill_gaps_v2.jsonl"), classification_v2=classification)]
    return _envelope(ir, {"v1_to_v2": ir.report.get("gaps_v1_to_v2"), **_page(items, limit, offset)})


def recommendation_evidence(ir, rec):
    """Everything a recommendation rests on, joined from the same run (nothing recomputed)."""
    run = ir.run
    key = rec["skill_key"]
    cfg = run.report.get("config") or {}
    demand = next(({k: v for k, v in d.items() if k != "posting_uids"} for d in run.industry["demand"]
                   if d["skill_key"] == key), None)
    gap = next((g for g in run.industry["gaps"] if g["skill_key"] == key), None)
    skill = run.industry["skills"].get(key) or {}
    decisions = [d for d in ir.rows("semantic_decisions.jsonl") if d.get("candidate_entity") == key or d.get("right") ==
                 skill.get("label")]
    return {
        "skill": {"skill_key": key, "label": rec.get("skill_label"), "esco_uri": key if key.startswith("http") else None,
                  "esco_status": skill.get("esco_status")},
        "target_programme": next(({"doc_id": d.get("doc_id"), "programme": d.get("programme"),
                                   "institution": d.get("institution")} for d in run.report.get("documents", [])
                                  if d.get("role") == "TARGET"), None),
        "target_courses": rec.get("target_course_codes"),
        "industry_evidence": demand,
        "curriculum_evidence": {"gap": gap, "coverage_depth": [r for r in ir.rows("coverage_depth.jsonl")
                                                               if r["skill_key"] == key and r.get("role") == "TARGET"]},
        "semantic_evidence": {"decisions": len(decisions),
                              "effects_applied": sum(1 for d in decisions if d.get("effect")),
                              "note": "model decisions never create or change a recommendation; with the promotion gate "
                                      "failed they have no effect at all"},
        "thresholds": {"support": (cfg.get("industry") or {}).get("support"),
                       "recommendation": (cfg.get("industry") or {}).get("recommendation"),
                       "existing_settings": cfg.get("existing_settings")},
        "source_ids": {"gap_uid": rec.get("gap_uid"), "recommendation_uid": rec.get("recommendation_uid"),
                       "population_scope": (demand or {}).get("population_scope_ref")},
        "run_id": run.run_id,
        "explanation": rec.get("rule_reasons"),
    }


WITHHELD_CODES = ("CLASSIFICATION_CONFLICT_REVIEW_REQUIRED", "COURSE_TITLE_CONFLICT_REVIEW_REQUIRED",
                  "CURRICULUM_SCOPE_REVIEW_REQUIRED")


_LEVEL_WORDS = {"MENTION": "mentioned", "INTRODUCTORY": "introductory", "SUBSTANTIAL": "substantial",
                "ADVANCED": "advanced"}


def verification_criteria(rec, reasoning=None):
    """How the institution can check that a recommendation worked, derived from the recommendation's own gap and
    evidence (Curriculum Recommendation agent: "provide ways to evaluate the proposed improvement"). Each criterion is
    something the next analysis run measures; nothing here is a prediction."""
    label = rec.get("skill_label") or "the skill"
    courses = ", ".join(rec.get("target_course_codes") or []) or None
    action = rec.get("action_type")
    out = []
    if rec.get("classification") == "MISSING" or action in ("ADD_ELECTIVE", "ADD_NEW_SUBJECT", "CONSIDER_ELECTIVE"):
        out.append(f"The revised curriculum teaches {label} in a named course (with topics or outcomes that state it), "
                   "and the next analysis no longer classifies the gap as missing.")
    else:
        level = _LEVEL_WORDS.get((reasoning or {}).get("target_coverage_level"), None)
        out.append(f"After the change, the next analysis finds {label} taught"
                   + (f" in {courses}" if courses else "")
                   + (f" beyond its current {level} coverage" if level else " at greater depth than now")
                   + ", and the gap is no longer classified partial.")
    out.append("The course's learning outcomes name the skill, so the coverage is assessed, not only mentioned.")
    out.append(f"The demand evidence still supports it when the analysis is re-run with newer postings (support "
               f"is currently {str(rec.get('support_state') or 'not stated').replace('_', ' ').lower()}).")
    return out


def recommendations(ir):
    reasoning = {r["skill_key"]: r for r in ir.rows("recommendation_reasoning.jsonl")}
    recs = [dict(r, evidence=recommendation_evidence(ir, r), reasoning=reasoning.get(r["skill_key"]),
                 verification=verification_criteria(r, reasoning.get(r["skill_key"])))
            for r in (ir.run.industry["recommendations"] if ir.run.industry else [])]
    sups = ir.run.industry["suppressions"] if ir.run.industry else []
    # candidates withheld because two coverage measures disagree (reconciled in the pipeline): shown to the reader as
    # "withheld for review", never as issued recommendations
    from app.services.improvement_service import _withheld_statement
    demand_by = {d["skill_key"]: d for d in ((ir.run.industry or {}).get("demand") or [])}
    traces = (ir.run.industry or {}).get("traces") or {}
    withheld = [{"skill_key": s.get("skill_key"), "skill_label": s.get("skill_label"),
                 "statement": _withheld_statement(s, demand_by.get(s.get("skill_key"), {}), traces.get(s.get("skill_key"))),
                 "posting_count": demand_by.get(s.get("skill_key"), {}).get("posting_count"),
                 "curriculum_courses": ((traces.get(s.get("skill_key")) or {}).get("curriculum") or {}).get("target_courses_with_skill"),
                 "reasons": s.get("reasons"), "withheld_recommendation": s.get("withheld_recommendation"),
                 "gap_v2": s.get("gap_v2"), "evidence_status": s.get("evidence_status")}
                for s in sups if any((r or {}).get("code") in WITHHELD_CODES for r in s.get("reasons") or [])]
    by_reason = Counter((s.get("reasons") or [{}])[0].get("code") for s in sups)
    return _envelope(ir, {"v1": recs, "suppressed": len(sups),
                          "withheld_for_review": withheld,
                          "suppressed_by_reason": {str(k): v for k, v in by_reason.items()},
                          "why_not": "GET /api/v1/intelligence/why-not?skill_key=... explains every suppressed skill "
                                     "(WHY_NOT_RECOMMENDED)",
                          "prerequisite": ir.rows("prerequisite_recommendations.jsonl"),
                          "rules": ir.report.get("recommendation_rules"),
                          "note": "recommendations are inferences; is_source_evidence is always false"})


def why_not(ir, skill_key):
    base = ks.why_no_recommendation(ir.run, skill_key)
    gap2 = next((g for g in ir.rows("skill_gaps_v2.jsonl") if g["skill_key"] == skill_key), None)
    depth = [r for r in ir.rows("coverage_depth.jsonl") if r["skill_key"] == skill_key]
    return _envelope(ir, {"skill_key": skill_key, "v1": base, "gap_v2": gap2, "coverage_depth": depth})


def evidence_trace(ir, skill_key):
    trace = ks.evidence_trace(ir.run, skill_key)
    depth = [r for r in ir.rows("coverage_depth.jsonl") if r["skill_key"] == skill_key]
    tax = next((t for t in ir.rows("skill_taxonomy_context.jsonl") if t["skill_key"] == skill_key), None)
    return _envelope(ir, {"skill_key": skill_key, "trace": trace, "coverage_depth": depth, "taxonomy": tax,
                          "lag": next((r for r in ir.rows("curriculum_industry_lag.jsonl") if r["skill_key"] == skill_key), None)})


def lineage(ir):
    rep = ir.run.report
    return _envelope(ir, {"run_id": ir.run.run_id, "code_fingerprint": rep.get("code_fingerprint"),
                          "config_hash": rep.get("config_hash"), "content_digest": rep.get("content_digest"),
                          "sources": rep.get("sources") or rep.get("documents"),
                          "stages": [s.get("stage") for s in (rep.get("observability") or {}).get("stages", [])]})


def evidence_status(ir):
    doc = ir.json("evidence_status.json")
    if doc is None:
        return _envelope(ir, {"items": [], "reason": "this run predates evidence-status reporting"})
    reqs = doc["requirements"]
    return _envelope(ir, {"note": doc.get("note"), "statuses": {r["requirement_id"]: r["status"] for r in reqs},
                          "items": reqs, "total": len(reqs)})


def system_health(ir):
    return _envelope(ir, {"gates": ir.run.health.get("analytics_gates"), "graph_checks": (ir.json("graph_consistency.json") or {}).get("checks"),
                          "ai_provider": (ir.report.get("semantic_adjudication") or {}).get("status")})
