"""
Read-only service over the improvement-release outputs:
  peers/        semantic peer benchmark (status, comparisons, relations, skill rows)
  industry_v2/  temporal populations and trends, dimensions, distributions, clusters, occupation resolution
  evaluation    independent semantic evaluation status (data/evaluation/.../results)
  overview      KPI snapshot assembled from GOLD only
  search        typed search over the run's courses, topics, concepts, skills, ESCO concepts, occupations,
                companies and job postings
  lineage       parent run -> source changes -> changed outputs (data/gold/knowledge/lineage)
Every response carries `evidence_state` (AVAILABLE / NOT_PRODUCED with the reason) and the run scope.
Nothing is recomputed; a run without an output never returns numbers for it.
"""
import re
from collections import Counter
from pathlib import Path

from app.services import knowledge_service as ks
from app.services.knowledge_service import _json, _jsonl, _page

REPO = Path(__file__).resolve().parents[3]
EVALUATION_FILE = REPO / "data/evaluation/semantic_benchmark_v1/results/semantic_ai_evaluation.json"
GATE_FILE = REPO / "data/evaluation/semantic_gate_v2.json"
GATE_V3_FILE = REPO / "data/evaluation/semantic_gate_v3.json"
PACKAGES_ROOT = REPO / "data/evaluation/semantic_gold"
LINEAGE_DIR = REPO / "data/gold/knowledge/lineage"
TREND_STATES = ("TRENDING_UP", "TRENDING_DOWN", "STABLE", "EMERGING", "DECLINING", "PERSISTENT", "INSUFFICIENT_DATA")


def _scope(run):
    return {"run_id": run.run_id, "pipeline_version": run.report.get("pipeline_version"),
            "generated_at": run.report.get("generated_at"), "population_scope": ks._scope_header(run)}


def _not_produced(run, what):
    return {"evidence_state": "NOT_PRODUCED", "scope": _scope(run), "items": [],
            "reason": f"run {run.run_id} has no {what} outputs (produced from the improvement release onwards)"}


def _ok(run, payload):
    return {"evidence_state": "AVAILABLE", "scope": _scope(run), **payload}


# ------------------------------------------------------------------ peers

def peer_status(run):
    st = _json(run.dir / "peers" / "peer_status.json")
    if st is None:
        return _not_produced(run, "peer benchmark")
    return _ok(run, {"peer_status": st["status"], "status": st, "badge": st["status"].replace("_", " ")})


def _benchmark(run):
    return _json(run.dir / "peers" / "peer_benchmark.json")


def peer_benchmark(run, comparison_doc_id=None):
    b = _benchmark(run)
    if b is None:
        return _not_produced(run, "peer benchmark")
    comps = [c for c in b["comparisons"] if comparison_doc_id in (None, c["comparison_doc_id"])]
    summary = [{k: c[k] for k in c if k not in ("skill_rows", "differences", "industry_alignment")}
               | {"differences_counts": {k: len(v) for k, v in c["differences"].items()},
                  "industry_alignment_counts": {k: (len(v) if isinstance(v, list) else v) for k, v in c["industry_alignment"].items()}}
               for c in comps]
    target = next((d for d in run.report.get("documents", []) if d.get("role") == "TARGET"), None)
    return _ok(run, {"peer_status": b["status"], "target": target, "method": b.get("method"), "config": b.get("config"),
                     "comparisons": summary,
                     "note": "factual comparison levels only; no institution is ranked and no composite score exists"})


def peer_differences(run, comparison_doc_id, kind=None, limit=40, offset=0):
    b = _benchmark(run)
    if b is None:
        return _not_produced(run, "peer benchmark")
    c = next((c for c in b["comparisons"] if c["comparison_doc_id"] == comparison_doc_id), None)
    if c is None:
        return {"evidence_state": "NOT_PRODUCED", "scope": _scope(run), "items": [],
                "reason": f"{comparison_doc_id!r} is not a comparison curriculum of this run"}
    kinds = [kind] if kind else list(c["differences"])
    return _ok(run, {"comparison_doc_id": comparison_doc_id,
                     "differences": {k: _page(c["differences"].get(k, []), limit, offset) for k in kinds},
                     "industry_alignment": c["industry_alignment"]})


def peer_relations(run, comparison_doc_id=None, relationship=None, evidence_state=None, q=None, limit=100, offset=0):
    rows = _jsonl(run.dir / "peers" / "peer_relations.jsonl")
    if not rows and _benchmark(run) is None:
        return _not_produced(run, "peer benchmark")
    items = [r for r in rows if comparison_doc_id in (None, r["comparison_doc_id"]) and relationship in (None, r["relationship"])
             and evidence_state in (None, r["evidence_state"])]
    if q:
        ql = q.lower()
        items = [r for r in items if ql in r["target"]["concept"].lower() or ql in r["comparison"]["concept"].lower()]
    counts = Counter(f"{r['relationship']}/{r['evidence_state']}" for r in items)
    return _ok(run, {"counts": dict(sorted(counts.items())), **_page(items, limit, offset)})


def peer_skills(run, comparison_doc_id, difference=None, limit=200, offset=0):
    b = _benchmark(run)
    if b is None:
        return _not_produced(run, "peer benchmark")
    c = next((c for c in b["comparisons"] if c["comparison_doc_id"] == comparison_doc_id), None)
    if c is None:
        return {"evidence_state": "NOT_PRODUCED", "scope": _scope(run), "items": [],
                "reason": f"{comparison_doc_id!r} is not a comparison curriculum of this run"}
    rows = [r for r in c["skill_rows"] if difference in (None, r["difference"])]
    return _ok(run, {"comparison_doc_id": comparison_doc_id, "comparison_role": c["comparison_role"],
                     "levels": c["coverage_levels"]["depth"], **_page(rows, limit, offset)})


# ------------------------------------------------------------------ industry v2

def _v2(run, name, jsonl=False):
    p = run.dir / "industry_v2" / name
    return _jsonl(p) if jsonl else _json(p)


def industry_trends(run, state=None, population_id=None, limit=200, offset=0):
    pops = _v2(run, "temporal_populations.json")
    if pops is None:
        return _not_produced(run, "temporal intelligence")
    rows = [r for r in _v2(run, "skill_trends.jsonl", True) if state in (None, r["trend_state"])
            and population_id in (None, r["population_id"])]
    rows.sort(key=lambda r: (-r.get("total_postings_with_skill", 0), r["skill_label"]))
    return _ok(run, {"populations": pops["populations"], "denominator": pops["denominator"],
                     "states": dict(Counter(r["trend_state"] for r in _v2(run, "skill_trends.jsonl", True))),
                     "segments": _v2(run, "segment_trend_scopes.jsonl", True), "state_filter": state,
                     "note": "a trend is shown only with both periods, both denominators, both counts and the population",
                     **_page(rows, limit, offset)})


def industry_intelligence(run):
    dist = _v2(run, "distributions.json")
    if dist is None:
        return _not_produced(run, "industry intelligence")
    mvp = _v2(run, "mentions_vs_postings.jsonl", True)
    occ = _v2(run, "occupation_summary.json") or {}
    return _ok(run, {"distributions": dist, "occupation_summary": {k: occ.get(k) for k in (
        "by_state", "established", "established_by_title", "established_by_context", "title_contradicted_by_context",
        "established_share", "distinct_occupations")},
        "skills_by_demand": mvp[:25], "denominator": "distinct eligible postings",
        "note": "mention counts are shown next to posting counts; only distinct postings are demand"})


def industry_dimensions(run, dimension=None):
    dims = _v2(run, "dimension_demand.json")
    if dims is None:
        return _not_produced(run, "industry dimensions")
    items = [v for k, v in dims.items() if dimension in (None, k)]
    return _ok(run, {"dimensions": sorted(dims), "items": items})


def industry_clusters(run):
    c = _v2(run, "skill_clusters.json")
    if c is None:
        return _not_produced(run, "skill clusters")
    return _ok(run, {"clusters": c["clusters"], "edges": c["edges"], "eligible_skills": c["eligible_skills"],
                     "config": c["config"], "items": c["clusters"],
                     "note": "CO_OCCURS_IN_POSTINGS is association in this population, never semantic equivalence"})


def occupation_resolution(run, state=None, limit=100, offset=0):
    rows = _v2(run, "occupation_resolution.jsonl", True)
    summary = _v2(run, "occupation_summary.json")
    if summary is None:
        return _not_produced(run, "occupation resolution")
    items = [r for r in rows if state in (None, r["state"])]
    return _ok(run, {"summary": summary, **_page(items, limit, offset)})


def occupation_analysis(run, level="occupation"):
    a = _v2(run, "occupation_analysis.json")
    if a is None:
        return _not_produced(run, "occupation analysis")
    return _ok(run, {"level": level, "note": a.get("note"), "items": a.get(level, [])})


# ------------------------------------------------------------------ semantic evaluation

def human_validation_packages():
    """Every validation package under data/evaluation/semantic_gold/<discipline>/<version> (any discipline)."""
    out = []
    for man_path in sorted(PACKAGES_ROOT.glob("*/*/MANIFEST.json")):
        m = _json(man_path) or {}
        metrics = _json(man_path.parent / "metrics.json") or {}
        out.append({"package": m.get("package"), "discipline": m.get("discipline"), "cases": m.get("case_count"),
                    "benchmark": m.get("benchmark_version"), "reviewers_target": (m.get("reviewer_design") or {}).get("target_reviewers"),
                    "reviewers": m.get("reviewers", []), "review_count": m.get("review_count", 0),
                    "agreement": m.get("agreement"), "gold_status": m.get("gold_status"),
                    "evaluation_status": metrics.get("status") or "PENDING_INDEPENDENT_LABELS",
                    "assistant_adjudication": "stored separately as ASSISTANT_ADJUDICATION; never human validation"})
    return out


def semantic_evaluation(include_cases=False):
    doc = _json(EVALUATION_FILE)
    if doc is None:
        return {"evidence_state": "NOT_PRODUCED", "status": "PENDING_INDEPENDENT_LABELS", "mode": "SAFE_MODE",
                "reason": "no evaluation has been run (scripts/semantic/benchmark_labelling.py evaluate)", "items": []}
    out = {k: v for k, v in doc.items() if k not in ("systems", "internal_development_preview")}
    def trim(systems):
        return {n: ({k: v for k, v in s.items() if include_cases or k != "per_case"}) for n, s in (systems or {}).items()}
    if doc.get("systems"):
        out["systems"] = trim(doc["systems"])
    if doc.get("internal_development_preview"):
        pv = doc["internal_development_preview"]
        out["internal_development_preview"] = {**{k: v for k, v in pv.items() if k != "systems"}, "systems": trim(pv["systems"])}
    gate = _json(GATE_V3_FILE) or _json(GATE_FILE) or {}
    out["gate_declaration"] = {k: gate.get(k) for k in ("version", "declared_at", "declared_before", "evaluated_system",
                                                         "criteria", "severe_errors", "promotable_classes", "if_failed", "if_passed",
                                                         "supersedes")}
    out["human_validation"] = human_validation_packages()
    out["evidence_state"] = "AVAILABLE"
    out["items"] = []
    return out


# ------------------------------------------------------------------ overview

SUPPORTED_DEMAND = ("SUPPORTED", "HIGH_SUPPORT")
# every reason meaning "withheld until a reviewer decides" (one definition: intelligence_stage)
WITHHELD_CODES = ("CLASSIFICATION_CONFLICT_REVIEW_REQUIRED", "COURSE_TITLE_CONFLICT_REVIEW_REQUIRED",
                  "CURRICULUM_SCOPE_REVIEW_REQUIRED")


def curriculum_scope(run):
    """The run's curriculum scope as recorded by the pipeline; runs made before the assessment existed are reported
    NOT_ASSESSED (never recomputed here)."""
    from app.knowledge_engine.curriculum_scope import not_assessed
    return (run.report or {}).get("curriculum_scope") or not_assessed()


def _confirmed(g):
    """A confirmed gap: partial or missing coverage, supported demand, no unresolved disagreement in the evidence
    (same rule as intelligence_stage.is_confirmed_gap)."""
    return (g.get("classification_v2") in ("PARTIAL", "MISSING") and g.get("support_state") in SUPPORTED_DEMAND
            and g.get("evidence_status") != "REVIEW_REQUIRED")


def _findings(run, gaps_v2, demand_by, recs, sups, pops, peers, occ, drift, sem_mode):
    """Key findings stated only from GOLD values of this run (never invented). Each finding names the evidence it rests
    on and the screen that shows it."""
    out = []
    scope = curriculum_scope(run)
    scope_limited = [g for g in gaps_v2 if g.get("scope_limited")]
    if scope.get("status") == "INCOMPLETE":
        out.append({"kind": "SCOPE", "tone": "warning", "value": len(scope_limited),
                    "title": "The supplied curriculum covers only part of the programme",
                    "statement": scope.get("note") or scope.get("reason"), "target": "skillGaps"})
    supported = [g for g in gaps_v2 if _confirmed(g)]
    partial = [g for g in gaps_v2 if g.get("classification_v2") == "PARTIAL"]
    missing = [g for g in gaps_v2 if g.get("classification_v2") == "MISSING"]
    thin = [g for g in partial + missing if g.get("support_state") not in SUPPORTED_DEMAND]
    posting_counts = [demand_by.get(g["skill_key"], {}).get("posting_count") or 0 for g in thin]
    if supported:
        out.append({"kind": "GAPS", "tone": "warning", "value": len(supported),
                    "title": f"{len(supported)} evidence-supported curriculum gap{'s' if len(supported) != 1 else ''}",
                    "statement": "Skills with supported industry demand whose target-curriculum coverage is partial or missing.",
                    "target": "skillGaps"})
    elif scope_limited:
        out.append({"kind": "GAPS", "tone": "neutral", "value": 0,
                    "title": "No confirmed gaps: the curriculum supplied is incomplete",
                    "statement": (f"{len(scope_limited)} skill{'s' if len(scope_limited) != 1 else ''} with industry "
                                  "demand show partial or missing coverage in the supplied semesters. They are marked for "
                                  "review, not confirmed, because the missing semesters may teach them."),
                    "target": "skillGaps"})
    else:
        shown = [f"{len(partial)} skill{'s' if len(partial) != 1 else ''} show{'' if len(partial) != 1 else 's'} partial curriculum coverage"]
        if missing:
            shown.append(f"{len(missing)} {'are' if len(missing) != 1 else 'is'} not covered")
        out.append({"kind": "GAPS", "tone": "neutral", "value": 0,
                    "title": "No evidence-supported skill gaps identified",
                    "statement": (" and ".join(shown) + ", but the available industry signal is too limited to confirm a "
                                  "curriculum gap"
                                  + (f" ({min(posting_counts)}–{max(posting_counts)} postings each)" if posting_counts else "")
                                  + ".") if partial or missing else
                                 "No skill with industry demand lacks curriculum coverage in this analysis.",
                    "target": "skillGaps"})
    withheld = [s for s in sups if any(r.get("code") in WITHHELD_CODES for r in s.get("reasons", []))]
    scope_withheld = [s for s in withheld if any(r.get("code") == "CURRICULUM_SCOPE_REVIEW_REQUIRED"
                                                 for r in s.get("reasons", []))]
    withheld = [s for s in withheld if s not in scope_withheld]
    out.append({"kind": "RECOMMENDATIONS", "tone": "warning" if withheld or scope_withheld else "neutral", "value": len(recs),
                "title": (f"{len(recs)} recommendation{'s' if len(recs) != 1 else ''} issued" if recs else "No recommendation issued"),
                "statement": ("; ".join(filter(None, [
                    f"{len(withheld)} withheld for review because the breadth and depth coverage measures disagree "
                    f"({', '.join(s['skill_label'] for s in withheld)})" if withheld else None,
                    f"{len(scope_withheld)} withheld for review because the supplied curriculum lacks semesters of the "
                    "programme" if scope_withheld else None,
                    f"{len(sups) - len(withheld) - len(scope_withheld)} suppressed with coded reasons (mostly thin demand)"])) + "."),
                "target": "recommendations"})
    for p in pops.get("populations", []):
        if p.get("trend_status") != "COMPUTED":
            have = (p.get("missing") or {}).get("have") or {}
            out.append({"kind": "TEMPORAL", "tone": "neutral", "value": have.get("qualifying_periods"),
                        "title": "Not enough time periods for a trend",
                        "statement": (f"All {p.get('eligible_postings')} postings of {p.get('population_id')} fall in one "
                                      f"{have.get('granularity') or 'period'}; trends need at least two comparable periods."),
                        "target": "trends"})
    if peers:
        out.append({"kind": "PEERS", "tone": "neutral", "value": len(peers.get("available", [])),
                    "title": {"PEER_DATA_PARTIAL": "Peer comparison is partial", "PEER_DATA_AVAILABLE": "Peer comparison available",
                              "PEER_DATA_NOT_AVAILABLE": "No peer curriculum yet"}.get(peers.get("status"), peers.get("status")),
                    "statement": (f"{len(peers.get('available', []))} official peer curricula decoded "
                                  f"({', '.join(a.get('institution', '') for a in peers.get('available', []))}); "
                                  f"{len(peers.get('missing', []))} requested peers are not available."),
                    "target": "peers"})
    if drift:
        out.append({"kind": "DRIFT", "tone": "neutral", "value": sum(drift.values()),
                    "title": "The curriculum changed between versions",
                    "statement": ", ".join(f"{v} {k.lower().replace('_', ' ')}" for k, v in sorted(drift.items(), key=lambda kv: -kv[1]))
                                 + " (courses, previous → target version).",
                    "target": "courseDrift"})
    if occ:
        out.append({"kind": "OCCUPATIONS", "tone": "neutral", "value": occ.get("established"),
                    "title": f"{occ.get('established')} of {sum((occ.get('by_state') or {}).values())} postings have an established occupation",
                    "statement": "The rest are candidates, ambiguous, unmapped or lack evidence; a title is never mapped against its own skills.",
                    "target": "occupations"})
    out.append({"kind": "TRUST", "tone": "neutral", "value": None,
                "title": "AI interpretation is advisory" if sem_mode == "SAFE_MODE" else "Validated AI decisions are applied",
                "statement": ("AI-assisted semantic interpretation is advisory. Authoritative results rely on deterministic "
                              "evidence while independent semantic validation is pending." if sem_mode == "SAFE_MODE"
                              else "Only validated classes of AI decisions affect results."),
                "target": "aiEvaluation"})
    return out


def _withheld_statement(w, demand, trace):
    """Plain-language reading of a withheld candidate, from its recorded evidence only."""
    g2 = w.get("gap_v2") or {}
    courses = ((trace or {}).get("curriculum") or {}).get("target_courses_with_skill")
    parts = []
    if demand.get("posting_count") is not None:
        parts.append(f"{demand.get('posting_count')} of {demand.get('eligible_postings')} postings ask for it"
                     + (" (supported demand)" if demand.get("support_state") in SUPPORTED_DEMAND else ""))
    title_conflict = next((r for r in w.get("reasons") or [] if r.get("code") == "COURSE_TITLE_CONFLICT_REVIEW_REQUIRED"), None)
    scope_review = next((r for r in w.get("reasons") or [] if r.get("code") == "CURRICULUM_SCOPE_REVIEW_REQUIRED"), None)
    if scope_review:
        parts.append(f"it is {(g2.get('coverage_level') or 'not').lower()} in the supplied semesters, but the curriculum "
                     "supplied does not include the whole programme")
        text = "; ".join(parts)
        return text[:1].upper() + text[1:] + ". Analyse the full curriculum before acting on this."
    if title_conflict:
        parts.append("a target course is named after it, but its topics show only "
                     f"{(g2.get('coverage_level') or 'limited').lower()} coverage")
    elif g2.get("classification") == "COVERED":
        parts.append(f"the curriculum covers it in depth ({(g2.get('reason') or '').lower()})"
                     + (f", but only {courses} courses name it" if courses is not None else ""))
    text = "; ".join(parts)
    return (text[:1].upper() + text[1:] + ". " if text else "") + \
        "Current evidence supports reviewing existing coverage rather than creating a new course."


def overview(run):
    rep = run.report
    docs = rep.get("documents", []) if isinstance(rep.get("documents"), list) else []
    target = next((d for d in docs if d.get("role") == "TARGET"), None)
    t_courses = [c for c in run.courses.values() if target and c["doc_id"] == target["doc_id"]]
    t_topics = [t for t in run.topics.values() if target and t["doc_id"] == target["doc_id"] and t["noise_label"] == "TOPIC"]
    t_concepts = [c for c in run.concepts.values() if "TARGET" in c["source_roles"]]
    ind = run.industry or {}
    scope = ind.get("scope") or {}
    skills = ind.get("skills") or {}
    demand = ind.get("demand") or []
    demand_by = {d["skill_key"]: d for d in demand}
    gaps_v2 = _jsonl(run.dir / "intelligence" / "skill_gaps_v2.jsonl")
    ev = (_json(run.dir / "intelligence" / "evidence_status.json") or {}).get("requirements", [])
    peers = _json(run.dir / "peers" / "peer_status.json")
    pops = _v2(run, "temporal_populations.json") or {}
    occ = _v2(run, "occupation_summary.json") or {}
    sem = (rep.get("intelligence") or {}).get("semantic_adjudication") or {}
    drift = rep.get("course_drift") or {}
    recs = ind.get("recommendations") or []
    sups = ind.get("suppressions") or []
    eligible = [s for s in skills.values() if s.get("eligible_for_analytics")]
    gap_counts = Counter(g.get("classification_v2") for g in gaps_v2)
    supported_gaps = [g for g in gaps_v2 if _confirmed(g)]
    sem_mode = "SAFE_MODE" if not ((sem.get("gate") or {}).get("passed")) else "PROMOTED"
    inst = f"{target.get('institution')} {target.get('curriculum_version')}" if target else None
    # every metric says which population it counts (scope labels come from the GOLD definitions)
    kpis = [
        {"key": "courses", "value": len(t_courses), "label": "Target-curriculum courses",
         "context": f"every course extracted from {inst}" if inst else None, "source": "GOLD courses (TARGET document)"},
        {"key": "topics", "value": len(t_topics), "label": "Target-curriculum topics",
         "context": "clean topics with page provenance (noise excluded)", "source": "GOLD topics (TARGET, noise_label TOPIC)"},
        {"key": "concepts", "value": len(t_concepts), "label": "Target-curriculum concepts",
         "context": f"concept clusters containing a target topic ({len(run.concepts)} across all curricula)",
         "source": "GOLD concepts (source_roles include TARGET)"},
        {"key": "postings", "value": scope.get("eligible_postings"), "label": "Industry postings",
         "context": "distinct eligible postings, " + ", ".join(f"{k} {v}" for k, v in (scope.get("geographic_scope") or {}).items()),
         "source": "GOLD population scope"},
        {"key": "skills", "value": len(eligible), "label": "Normalized industry skills eligible for analysis",
         "context": (f"{len(demand)} demand-assessed (skill role in >= 1 posting); "
                     f"{sum(1 for s in eligible if s.get('esco_uri'))} mapped to ESCO; {len(skills)} normalized in total"),
         "source": "GOLD skills (eligible_for_analytics) / industry_demand"},
        {"key": "gaps", "value": len(supported_gaps), "label": "Evidence-supported gaps",
         "context": (f"PARTIAL or MISSING with SUPPORTED demand; of {len(gaps_v2)} demand skills: "
                     f"{gap_counts.get('COVERED', 0)} covered, {gap_counts.get('PARTIAL', 0)} partial, "
                     f"{gap_counts.get('MISSING', 0)} missing, {gap_counts.get('INSUFFICIENT_EVIDENCE', 0)} not enough evidence"),
         "source": "GOLD skill_gaps_v2"},
        {"key": "recommendations", "value": len(recs), "label": "Recommendations issued",
         "context": f"{len(sups)} withheld or suppressed with coded reasons", "source": "GOLD recommendations"},
    ]
    attention = []
    for g in gaps_v2:
        if g.get("classification_v2") in ("PARTIAL", "MISSING"):
            d = demand_by.get(g["skill_key"], {})
            attention.append({"skill_key": g["skill_key"], "skill_label": g.get("skill_label"),
                              "classification": g.get("classification_v2"), "coverage_level": g.get("coverage_level"),
                              "coverage_reason": g.get("reason_v2"), "demand_support": g.get("support_state"),
                              "posting_count": d.get("posting_count"), "eligible_postings": d.get("eligible_postings"),
                              "posting_prevalence_pct": d.get("posting_prevalence_pct"),
                              "evidence_supported": _confirmed(g),
                              "needs_review": (g.get("review") or {}).get("detail")})
    attention.sort(key=lambda a: (not a["evidence_supported"], -(a["posting_count"] or 0), a["skill_label"] or ""))
    withheld = [x for x in sups if any((r or {}).get("code") in WITHHELD_CODES
                                       for r in x.get("reasons") or [])]
    support = Counter(d["support_state"] for d in demand)
    flow = [
        {"step": "industry", "stage": "Industry", "label": "Industry postings", "value": scope.get("eligible_postings"),
         "headline": f"{scope.get('eligible_postings')} postings",
         "detail": f"{len({p for d in demand for p in d.get('posting_uids', [])})} contain an analysable skill",
         "evidence": [f"{v} postings from {k}" for k, v in (scope.get("geographic_scope") or {}).items()]
                     + [f"dated {(scope.get('date_range') or {}).get('earliest')} to {(scope.get('date_range') or {}).get('latest')}"]
                     + [f"{scope.get('distinct_companies')} companies"]},
        {"step": "skills", "stage": "Skills", "label": "Skills with demand", "value": len(demand),
         "headline": f"{len(demand)} assessed", "detail": dict(support),
         "evidence": [f"{support.get('SUPPORTED', 0) + support.get('HIGH_SUPPORT', 0)} with supported demand",
                      f"{support.get('OBSERVED', 0)} observed in a few postings",
                      f"{support.get('INSUFFICIENT_EVIDENCE', 0)} with too few postings to judge"]},
        {"step": "coverage", "stage": "Curriculum", "label": "Assessed against the curriculum", "value": len(gaps_v2),
         "headline": f"{gap_counts.get('PARTIAL', 0)} partial · {gap_counts.get('COVERED', 0)} covered",
         "detail": dict(gap_counts),
         "evidence": [f"{gap_counts.get('COVERED', 0)} covered in depth", f"{gap_counts.get('PARTIAL', 0)} partially covered",
                      f"{gap_counts.get('MISSING', 0)} not covered",
                      f"{gap_counts.get('INSUFFICIENT_EVIDENCE', 0)} with too little evidence to classify"]},
        {"step": "gaps", "stage": "Gaps", "label": "Evidence-supported gaps", "value": len(supported_gaps),
         "headline": f"{len(supported_gaps)} confirmed", "detail": None,
         "evidence": ([g.get("skill_label") for g in supported_gaps] or
                      ["a gap needs partial or missing coverage AND supported industry demand; no skill meets both"])},
        {"step": "recommendations", "stage": "Actions", "label": "Recommendations issued", "value": len(recs),
         "headline": f"{len(recs)} issued · {len(withheld)} withheld for review",
         "detail": f"{len(sups)} withheld/suppressed",
         "evidence": ([f"{r.get('skill_label')}: {r.get('action_type')}" for r in recs]
                      + [f"{w.get('skill_label')}: withheld — the coverage measures disagree" for w in withheld]
                      + [f"{len(sups) - len(withheld)} not recommended, each with a coded reason"])},
    ]
    # existing-course-first reasoning (experimental): the least disruptive intervention the curriculum evidence
    # supports, next to the rule engine's action; absent for runs produced before it existed
    reasoning = {r["skill_key"]: r for r in _jsonl(run.dir / "intelligence" / "recommendation_reasoning.jsonl")}
    actions = {
        "issued": [{"skill_key": r.get("skill_key"), "skill_label": r.get("skill_label"), "action_type": r.get("action_type"),
                    "rule_reasons": r.get("rule_reasons"),
                    "reasoning": reasoning.get(r.get("skill_key"))} for r in recs],
        "withheld": [{"skill_key": w.get("skill_key"), "skill_label": w.get("skill_label"),
                      "reason": next((r.get("detail") for r in w.get("reasons") or []
                                      if r.get("code") in WITHHELD_CODES), None),
                      "withheld_action": (w.get("withheld_recommendation") or {}).get("action_type"),
                      "gap_v2": w.get("gap_v2"),
                      "posting_count": demand_by.get(w.get("skill_key"), {}).get("posting_count"),
                      "support_state": demand_by.get(w.get("skill_key"), {}).get("support_state"),
                      "curriculum_courses": (((ind.get("traces") or {}).get(w.get("skill_key")) or {}).get("curriculum") or {})
                      .get("target_courses_with_skill"),
                      "statement": _withheld_statement(w, demand_by.get(w.get("skill_key"), {}),
                                                       (ind.get("traces") or {}).get(w.get("skill_key")))} for w in withheld],
        "not_recommended": len(sups) - len(withheld),
        "not_recommended_by_reason": dict(Counter((x.get("reasons") or [{}])[0].get("code") for x in sups if x not in withheld)),
    }
    return _ok(run, {
        "run": {k: rep.get(k) for k in ("run_id", "generated_at", "content_digest", "pipeline_version", "code_fingerprint")},
        "target": target, "kpis": kpis,
        "findings": _findings(run, gaps_v2, demand_by, recs, sups, pops, peers, occ, drift, sem_mode),
        "attention": attention[:12], "flow": flow, "actions": actions,
        "curriculum_scope": curriculum_scope(run),
        "gap_line": {"confirmed": len(supported_gaps), "partial": gap_counts.get("PARTIAL", 0),
                     "review_required": sum(1 for g in gaps_v2 if g.get("evidence_status") == "REVIEW_REQUIRED"),
                     "scope_limited": sum(1 for g in gaps_v2 if g.get("scope_limited")),
                     "missing": gap_counts.get("MISSING", 0), "covered": gap_counts.get("COVERED", 0),
                     "insufficient": gap_counts.get("INSUFFICIENT_EVIDENCE", 0)},
        "data_scope": {"industry": {"population_ids": [p.get("population_id") for p in pops.get("populations", [])],
                                    "eligible_postings": scope.get("eligible_postings"), "date_range": scope.get("date_range"),
                                    "geographic_scope": scope.get("geographic_scope"),
                                    "representativeness_warning": scope.get("representativeness_warning")},
                       "curriculum": [{k: d.get(k) for k in ("doc_id", "role", "institution", "curriculum_version", "academic_year")}
                                      for d in docs]},
        "gap_summary": dict(gap_counts),
        "gap_demand_support": {f"{a}|{b}": n for (a, b), n in
                               Counter((g.get("classification_v2"), g.get("support_state")) for g in gaps_v2).items()},
        "drift_summary": drift,
        "trend_status": {p.get("population_id"): {"status": p.get("trend_status"), "missing": (p.get("missing") or {}).get("have")}
                         for p in pops.get("populations", [])},
        "peer_status": (peers or {}).get("status", "NOT_PRODUCED"),
        "peers_available": [p.get("institution") for p in (peers or {}).get("available", [])],
        "occupations": {k: occ.get(k) for k in ("established", "established_share", "by_state")},
        "evidence_status": {e["requirement_id"]: e["status"] for e in ev},
        "semantic": {"mode": sem_mode,
                     "mode_label": ("AI interpretation is advisory" if sem_mode == "SAFE_MODE" else "Validated AI decisions applied"),
                     "decisions": sum((sem.get("decisions_by_state") or {}).values()),
                     "effects_blocked": sem.get("effects_blocked"),
                     "independent_evaluation": (_json(EVALUATION_FILE) or {}).get("status", "PENDING_INDEPENDENT_LABELS")},
    })


# ------------------------------------------------------------------ search

SEARCH_TYPES = ("COURSE", "TOPIC", "CONCEPT", "SKILL", "ESCO", "OCCUPATION", "COMPANY", "JOB")


_SEARCH_CACHE = {}


def _search_index(run):
    key = str(run.dir)
    if key in _SEARCH_CACHE:
        return _SEARCH_CACHE[key]
    idx = []
    for c in run.courses.values():
        idx.append(("COURSE", c["course_uid"], f"{c['course_code']} {c['title']}", c["doc_id"], {"course_uid": c["course_uid"]}))
    for t in run.topics.values():
        if t["noise_label"] == "TOPIC":
            idx.append(("TOPIC", t["topic_uid"], t["clean_text"], f"{t['doc_id']} · {t.get('course_code')} · p.{t.get('page_number')}",
                        {"topic_uid": t["topic_uid"]}))
    for c in run.concepts.values():
        idx.append(("CONCEPT", c["concept_uid"], c["name"], f"{c['support']} topics · {'+'.join(c['source_roles'])}",
                    {"concept_uid": c["concept_uid"]}))
    for s in (run.industry or {}).get("skills", {}).values():
        if s.get("eligible_for_analytics"):
            idx.append(("SKILL", s["skill_key"], s["label"], s.get("esco_status"), {"skill_key": s["skill_key"]}))
    seen = set()
    for m in (run.industry or {}).get("mappings", []):
        if m.get("esco_uri") and m["esco_uri"] not in seen:
            seen.add(m["esco_uri"])
            idx.append(("ESCO", m["esco_uri"], m.get("esco_pref_label") or m["normalized_label"], "ESCO v1.2.1 skill",
                        {"skill_key": m.get("skill_key")}))
    for r in _jsonl(run.dir / "industry_v2" / "occupation_resolution.jsonl"):
        if r.get("established") and r["occupation_uri"] not in seen:
            seen.add(r["occupation_uri"])
            idx.append(("OCCUPATION", r["occupation_uri"], r["occupation_label"], r.get("occupation_group"),
                        {"occupation_uri": r["occupation_uri"]}))
    postings = _jsonl(run.dir / "industry" / "postings.jsonl")
    for comp in sorted({p.get("company_name") for p in postings if p.get("company_name")}):
        idx.append(("COMPANY", comp, comp, f"{sum(1 for p in postings if p.get('company_name') == comp)} posting(s)", {"company": comp}))
    for p in postings:
        idx.append(("JOB", p["posting_uid"], p.get("job_title") or "", f"{p.get('company_name')} · {p.get('location')}",
                    {"posting_uid": p["posting_uid"]}))
    out = [(typ, k, label, sub, target, (label or "").lower()) for typ, k, label, sub, target in idx]
    if len(_SEARCH_CACHE) > 4:
        _SEARCH_CACHE.clear()
    _SEARCH_CACHE[key] = out
    return out


def search(run, q, types=None, limit=30):
    q = (q or "").strip()
    if len(q) < 2:
        return _ok(run, {"query": q, "items": [], "total": 0, "reason": "type at least 2 characters"})
    ql = q.lower()
    words = re.findall(r"\w+", ql)
    want = {t.upper() for t in types} if types else set(SEARCH_TYPES)
    hits = []
    for typ, key, label, sub, target, low in _search_index(run):
        if typ not in want:
            continue
        if low == ql:
            rank = 0
        elif low.startswith(ql):
            rank = 1
        elif ql in low:
            rank = 2
        elif words and all(w in low for w in words):
            rank = 3
        else:
            continue
        hits.append((rank, SEARCH_TYPES.index(typ), len(label), label, {"type": typ, "id": key, "label": label,
                                                                      "subtitle": sub, "target": target}))
    hits.sort(key=lambda h: h[:4])
    return _ok(run, {"query": q, "total": len(hits), "by_type": dict(Counter(h[4]["type"] for h in hits)),
                     "items": [h[4] for h in hits[:limit]]})


# ------------------------------------------------------------------ lineage

def run_lineage(run):
    rec = _json(LINEAGE_DIR / f"{run.run_id}.json")
    if rec is None:
        return {"evidence_state": "NOT_PRODUCED", "scope": _scope(run), "items": [],
                "reason": "no recomputation lineage was recorded for this run (it was not produced by scripts/acquisition/recompute.py)"}
    return _ok(run, {"lineage": rec, "items": []})


# ------------------------------------------------------------------ readiness (product abstraction of the run's state)

READINESS_HUMAN = {
    "READY": "Ready", "NOT_READY": "Not ready",
    "AVAILABLE": "Available", "AVAILABLE_WITH_LIMITATIONS": "Available with limitations", "INSUFFICIENT": "Insufficient",
    "PARTIAL": "Partial", "NOT_ESTABLISHED": "Not established", "ESTABLISHED": "Established", "NOT_AVAILABLE": "Not available",
    "ADVISORY": "Advisory", "VALIDATED": "Validated",
    "COMPLETE": "Complete", "INCOMPLETE": "Incomplete",
}


def _state(key, label, state, statement, **extra):
    return {"key": key, "label": label, "state": state, "human": READINESS_HUMAN.get(state, state.title()),
            "statement": statement, **extra}


def readiness(run):
    """Is the analysis usable, what evidence supports it, what is limited, is AI advisory, can results be traced?

    Every state is DERIVED from this run's GOLD (health gates, evidence requirements, population scopes, peer status,
    occupation summary, semantic gate, graph checks); nothing here is a new measurement. Implementation details are
    returned separately under `technical`, for the collapsed technical section of the UI."""
    rep = run.report
    docs = rep.get("documents", []) if isinstance(rep.get("documents"), list) else []
    target = next((d for d in docs if d.get("role") == "TARGET"), None)
    t_courses = [c for c in run.courses.values() if target and c["doc_id"] == target["doc_id"]]
    t_topics = [t for t in run.topics.values() if target and t["doc_id"] == target["doc_id"] and t["noise_label"] == "TOPIC"]
    ind = run.industry or {}
    scope = ind.get("scope") or {}
    skills = ind.get("skills") or {}
    demand = ind.get("demand") or []
    gates = (run.health or {}).get("analytics_gates") or {}
    blocked_gates = sorted(k for k, g in gates.items() if (g or {}).get("status") != "ALLOWED")
    ev = {e["requirement_id"]: e for e in (_json(run.dir / "intelligence" / "evidence_status.json") or {}).get("requirements", [])}
    peers = _json(run.dir / "peers" / "peer_status.json") or {}
    pops = (_v2(run, "temporal_populations.json") or {}).get("populations", [])
    occ = _v2(run, "occupation_summary.json") or {}
    sem = (rep.get("intelligence") or {}).get("semantic_adjudication") or {}
    gate = sem.get("gate") or {}
    graph = (_json(run.dir / "intelligence" / "graph_consistency.json") or {}).get("checks") or {}
    sups = ind.get("suppressions") or []

    # ---- evidence coverage, one row per evidence area
    esco_mapped = sum(1 for s in skills.values() if s.get("eligible_for_analytics") and s.get("esco_uri"))
    n_post = scope.get("eligible_postings") or 0
    avail_peers = peers.get("available") or []
    missing_peers = peers.get("missing") or []
    computed = [p for p in pops if p.get("trend_status") == "COMPUTED"]
    have = ((pops[0].get("missing") or {}).get("have") or {}) if pops and not computed else {}
    established = occ.get("established") or 0
    occ_total = sum((occ.get("by_state") or {}).values())
    coverage = [
        _state("curriculum", "Curriculum", "AVAILABLE" if t_courses and t_topics else "INSUFFICIENT",
               f"{len(t_courses)} courses and {len(t_topics)} topics of the target curriculum"
               + (f" ({target.get('institution')} {target.get('curriculum_version')})" if target else "")),
        _state("industry", "Industry", "AVAILABLE" if n_post else "INSUFFICIENT",
               f"{n_post} job postings"
               + (f", {(scope.get('date_range') or {}).get('earliest')} to {(scope.get('date_range') or {}).get('latest')}"
                  if (scope.get('date_range') or {}).get('earliest') else "")),
        _state("taxonomy", "Skill taxonomy", "AVAILABLE" if esco_mapped else "INSUFFICIENT",
               f"{esco_mapped} industry skills mapped to the ESCO skills taxonomy"),
        _state("peers", "Peer curricula", "AVAILABLE" if avail_peers and not missing_peers else
               "PARTIAL" if avail_peers else "NOT_AVAILABLE",
               f"{len(avail_peers)} official peer curricula compared"
               + (f"; {len(missing_peers)} requested peers not acquired" if missing_peers else ""),
               missing=("official curricula of " + ", ".join(m.get("name", "") for m in missing_peers)) if missing_peers else None,
               why_it_matters="a peer comparison shows how other institutions cover the same areas",
               resolve=("acquire the official curriculum of each missing peer (Add evidence, Peer); a peer whose "
                        "official curriculum has no topic content stays unavailable") if missing_peers else None),
        _state("trends", "Industry trends", "ESTABLISHED" if computed else "NOT_ESTABLISHED",
               (f"trends computed for {len(computed)} job-posting population(s)" if computed else
                f"current job evidence covers {have.get('qualifying_periods', 0)} qualifying time period"
                f"{'' if have.get('qualifying_periods') == 1 else 's'}; a trend requires at least "
                f"{((pops[0].get('gate') or {}).get('min_periods_for_trend') if pops else None) or 2}"),
               missing=None if computed else "job postings from additional dated periods of the same population",
               why_it_matters="a trend compares the same population at two or more points in time",
               resolve=None if computed else "add dated job postings from further periods (for snapshots: repeat the "
                                             "acquisition on later dates)"),
        _state("occupations", "Occupation mapping",
               "AVAILABLE" if occ_total and established == occ_total else "PARTIAL" if established else "NOT_AVAILABLE",
               f"{established} of {occ_total} postings resolved to an occupation",
               missing=None if occ_total and established == occ_total else
               "a confident occupation for the remaining postings (titles that are ambiguous, unmapped or lack context)",
               why_it_matters="occupation-level demand needs most postings mapped to an occupation",
               resolve=("a reviewer resolving the ambiguous and unmapped titles, or an additional occupation "
                        "taxonomy kept as a separate scope") if established != occ_total else None),
    ]
    core_ok = all(c["state"] == "AVAILABLE" for c in coverage[:3])
    limited = [c for c in coverage[3:] if c["state"] not in ("AVAILABLE", "ESTABLISHED")]
    evidence_state = ("INSUFFICIENT" if not core_ok else "AVAILABLE_WITH_LIMITATIONS" if limited else "AVAILABLE")

    # ---- AI interpretation
    promoted = bool(gate.get("passed"))
    ai_state = "VALIDATED" if promoted else "ADVISORY"
    ai = {
        "state": ai_state, "human": READINESS_HUMAN[ai_state],
        "explanation": ("AI is used to interpret relationships between curriculum concepts and reference knowledge. "
                        + ("These interpretations passed the declared validation gate and are applied as an additional, "
                           "labelled evidence layer." if promoted else
                           "These interpretations are currently advisory and do not alter authoritative analysis without "
                           "independent validation.")),
        "why": None if promoted else "Independent validation of the frozen semantic benchmark is pending.",
        "affects": "AI-suggested semantic relationships only.",
        "authoritative": "Validated curriculum, industry, taxonomy and evidence-derived analytics.",
    }

    # ---- traceability: every published result back to source evidence, processing and the run
    checks = {
        "source_documents_hash_verified": all(d.get("sha256") for d in docs) and bool(docs),
        "postings_with_source_file_and_row": all(p.get("source_file") and p.get("row_number") and p.get("source_sha256")
                                                 for p in _jsonl(run.dir / "industry" / "postings.jsonl")),
        "source_files_hash_verified": all(c.get("status") == "PASS" for c in ((run.health or {}).get("industry") or {})
                                          .get("checks", []) if c.get("check") == "source_hashes_verified"),
        "demand_rows_with_postings": all(d.get("posting_uids") for d in demand),
        "withheld_and_suppressed_with_reasons": all(s.get("reasons") for s in sups),
        "graph_edges_with_provenance": graph.get("edges_without_provenance", 0) == 0,
        "graph_without_dangling_edges": graph.get("dangling_edges", 0) == 0,
        "run_content_digest": bool(rep.get("content_digest")),
    }
    trace_state = "COMPLETE" if all(checks.values()) else "INCOMPLETE"

    analysis_state = "READY" if (run.dir / "intelligence" / "intelligence_report.json").exists() and not blocked_gates and t_courses else "NOT_READY"
    primary = [
        _state("analysis", "Analysis", analysis_state,
               "The current analysis is available." if analysis_state == "READY" else
               "The analysis is not usable yet: " + (", ".join(blocked_gates) or "no target curriculum")),
        _state("evidence", "Evidence", evidence_state,
               {"AVAILABLE": "Every evidence dimension is covered.",
                "AVAILABLE_WITH_LIMITATIONS": "Core evidence is available; " + ", ".join(c["label"].lower() for c in limited)
                + " " + ("is" if len(limited) == 1 else "are") + " limited.",
                "INSUFFICIENT": "Core evidence is missing."}[evidence_state]),
        _state("ai", "AI interpretation", ai_state,
               "AI interpretation is advisory." if ai_state == "ADVISORY" else "Validated AI interpretation is applied."),
        _state("traceability", "Traceability", trace_state,
               "Every published analytical result can be traced to source evidence, processing and the analysis run."
               if trace_state == "COMPLETE" else "Some results cannot be traced: "
               + ", ".join(k.replace("_", " ") for k, v in checks.items() if not v)),
    ]
    know = [("Core curriculum analysis is available." if core_ok else "Core evidence is incomplete; the analysis is not "
             "usable until it is supplied.")]
    part = [c["label"].lower() for c in coverage if c["key"] in ("peers", "occupations") and c["state"] != "AVAILABLE"]
    if part:
        know.append(f"Some {' and '.join(p.replace(' curricula', '').replace(' mapping', '') for p in part)} evidence is incomplete.")
    if not computed:
        know.append(f"Industry trends are not established because only {have.get('qualifying_periods', 0)} qualifying "
                    f"period{'' if have.get('qualifying_periods') == 1 else 's'} {'is' if have.get('qualifying_periods') == 1 else 'are'} available.")
    ready = analysis_state == "READY"
    return _ok(run, {
        "headline": "Curriculum intelligence is ready" if ready else "Curriculum intelligence is not ready",
        "summary": ("The current analysis is available and traceable. Some evidence dimensions have limited coverage "
                    "and are clearly marked where relevant." if ready and limited and trace_state == "COMPLETE" else
                    "The current analysis is available and traceable." if ready and trace_state == "COMPLETE" else
                    primary[0]["statement"]),
        "primary": primary, "coverage": coverage, "what_to_know": know[:3], "ai_interpretation": ai,
        "traceability": {"state": trace_state, "checks": checks},
        "secondary": {
            "last_successful_analysis": rep.get("generated_at"),
            "industry_evidence_dates": scope.get("date_range"),
            "curriculum_version": f"{target.get('institution')} {target.get('curriculum_version')}" if target else None,
            "evidence_requirements": {k: v.get("status") for k, v in ev.items()},
            "analytics_gates_blocked": blocked_gates,
        },
        "technical": {
            "run_id": rep.get("run_id"), "pipeline_version": rep.get("pipeline_version"),
            "code_fingerprint": rep.get("code_fingerprint"), "config_hash": rep.get("config_hash"),
            "content_digest": rep.get("content_digest"),
            "semantic_mode": "SAFE_MODE" if not promoted else "PROMOTED",
            "semantic_gate_passed": promoted,
            "semantic_gate_checks": {k: v.get("pass") for k, v in (gate.get("checks") or {}).items()},
            "semantic_decisions": sum((sem.get("decisions_by_state") or {}).values()),
            "semantic_effects_blocked": sem.get("effects_blocked"),
            "semantic_cache": sem.get("cache_file"),
            "independent_evaluation": (_json(EVALUATION_FILE) or {}).get("status", "PENDING_INDEPENDENT_LABELS"),
            "evidence_requirements": {k: v.get("status") for k, v in ev.items()},
            "analytics_gates": {k: (g or {}).get("status") for k, g in gates.items()},
            "graph_checks": graph,
        },
    })
