"""
The five analysis agents: what each one is responsible for, which code implements it, what it reads and writes, and
whether its output exists for the selected run. Read-only; nothing is recomputed.

An "agent" here is a pipeline component with a defined responsibility, inputs and outputs -- not an LLM wrapper. The
agents run in a fixed order, each consuming the previous one's stored outputs:

  1 Curriculum Understanding -> 2 Discipline-to-Industry Relevance -> 3 Skill Intelligence -> 4 Skill-Gap Reasoning
  -> 5 Curriculum Recommendation

Every agent has an AUTHORITATIVE layer (the deterministic release pipeline, whose outputs the screens show) and,
where one exists, an EXPERIMENTAL layer (deterministic, evaluated, not yet promoted: shown only where labelled
experimental). The semantic model (Qwen) stays advisory under Safe Mode in every agent.
"""
from app.services import knowledge_service as ks
from app.services.knowledge_service import _json, _jsonl

EXPERIMENTS = ks.REPO / "data" / "experiments"

AGENTS = [
    {"id": "curriculum_understanding", "order": 1, "name": "Curriculum Understanding",
     "responsibility": "Reads each curriculum into programmes, courses, units, topics and outcomes; measures how deeply "
                       "each skill is taught; records compulsory or elective status, course type, lab pairing and "
                       "whether a document is complete.",
     "authoritative": {"code": ["knowledge_engine/silver.py", "pipelines/preprocessing/curriculum_structuring.py",
                                "knowledge_engine/intelligence.py (coverage_depth)"],
                       "outputs": ["courses.jsonl", "intelligence/coverage_depth.jsonl", "intelligence/topic_hierarchy.jsonl"]},
     "experimental": {"code": ["knowledge_engine/curriculum_understanding.py"], "layer": "gap_reasoning",
                      "outputs": ["curriculum_profiles.json", "skill_coverage.jsonl"]},
     "reads": ["curriculum PDFs (BRONZE page text, SILVER records)"],
     "writes_for": ["Skill Intelligence", "Skill-Gap Reasoning"]},
    {"id": "discipline_relevance", "order": 2, "name": "Discipline-to-Industry Relevance",
     "responsibility": "Decides which job postings and skills are relevant to the programme's discipline: relevant, "
                       "likely, adjacent, uncertain or not relevant, and which posting text is employer boilerplate.",
     "authoritative": {"code": ["knowledge_engine/occupation_resolution.py", "knowledge_engine/industry.py (discipline relevance override)"],
                       "outputs": ["industry_v2/occupation_resolution.jsonl", "industry/population_scope.json"]},
     "experimental": {"code": ["knowledge_engine/relevance.py"], "layer": "relevance",
                      "outputs": ["job_relevance.jsonl", "skill_relevance.jsonl", "summary.json"]},
     "reads": ["job postings (SILVER)", "programme profile from Curriculum Understanding"],
     "writes_for": ["Skill Intelligence"]},
    {"id": "skill_intelligence", "order": 3, "name": "Skill Intelligence",
     "responsibility": "Extracts skill mentions with their original wording and position, qualifies each occurrence "
                       "from its context, normalises it to ESCO only when the context confirms the concept, and counts "
                       "demand. A taxonomy match alone is never proof that a skill is required.",
     "authoritative": {"code": ["knowledge_engine/industry_stage.py", "knowledge_engine/industry.py"],
                       "outputs": ["industry/skill_mentions.jsonl", "industry/esco_mappings.jsonl", "industry/industry_demand.jsonl"]},
     "experimental": {"code": ["knowledge_engine/skill_evidence.py", "knowledge_engine/skill_intelligence.py"],
                      "layer": "skill_evidence", "outputs": ["mention_evidence.jsonl", "skill_evidence.jsonl", "scorecard.json"]},
     "reads": ["job postings", "ESCO v1.2.1", "relevance from Discipline-to-Industry Relevance"],
     "writes_for": ["Skill-Gap Reasoning"]},
    {"id": "gap_reasoning", "order": 4, "name": "Skill-Gap Reasoning",
     "responsibility": "Combines qualified demand, curriculum coverage, programme context, evidence sufficiency, "
                       "trend evidence and curriculum versions into a gap state; says there is not enough evidence "
                       "rather than inventing a gap.",
     "authoritative": {"code": ["knowledge_engine/intelligence_stage.py (gap_v2)", "analytics/gap_classification.py"],
                       "outputs": ["industry/skill_gaps.jsonl", "intelligence/skill_gaps_v2.jsonl"]},
     "experimental": {"code": ["knowledge_engine/gap_reasoning.py"], "layer": "gap_reasoning",
                      "outputs": ["skill_stages.jsonl", "gap_states.jsonl", "scorecard.json"]},
     "reads": ["coverage from Curriculum Understanding", "demand from Skill Intelligence"],
     "writes_for": ["Curriculum Recommendation"]},
    {"id": "recommendation", "order": 5, "name": "Curriculum Recommendation",
     "responsibility": "Turns established gaps into practical changes, preferring to expand or strengthen an existing "
                       "course over adding a subject, and explains the rationale, alternatives, evidence and limits.",
     "authoritative": {"code": ["analytics/recommendation_engine.py", "knowledge_engine/intelligence_stage.py (reconcile)",
                                "knowledge_engine/recommendation_reasoning.py"],
                       "outputs": ["industry/recommendations.jsonl", "industry/recommendation_suppressions.jsonl",
                                   "intelligence/recommendation_reasoning.jsonl"]},
     "experimental": None,
     "reads": ["gaps from Skill-Gap Reasoning", "course coverage from Curriculum Understanding"],
     "writes_for": []},
]


def _status(paths):
    present = [p for p in paths if p.exists()]
    if len(present) == len(paths):
        return "AVAILABLE"
    return "PARTIAL" if present else "NOT_PRODUCED"


def agents(run):
    rows = []
    for a in AGENTS:
        auth = [run.dir / f for f in a["authoritative"]["outputs"]]
        row = {k: a[k] for k in ("id", "order", "name", "responsibility", "reads", "writes_for")}
        row["authoritative"] = {**a["authoritative"], "status": _status(auth),
                                "missing": [str(p.relative_to(run.dir)) for p in auth if not p.exists()]}
        if a["experimental"]:
            d = EXPERIMENTS / a["experimental"]["layer"] / run.run_id
            exp = [d / f for f in a["experimental"]["outputs"]]
            row["experimental"] = {**a["experimental"], "status": _status(exp),
                                   "note": "deterministic and evaluated, not yet promoted; shown only where labelled "
                                           "experimental"}
        else:
            row["experimental"] = None
        row["status"] = row["authoritative"]["status"]
        row["experimental_status"] = (row["experimental"] or {}).get("status", "NONE")
        rows.append(row)
    return {"run_id": run.run_id, "items": rows,
            "coordination": " -> ".join(a["name"] for a in AGENTS),
            "semantic_model": "advisory under Safe Mode in every agent: model decisions are recorded, never applied "
                              "unless a pre-declared promotion gate passes",
            "note": "Agents are pipeline components with defined inputs and outputs, run in this order; each reads the "
                    "previous agents' stored outputs."}


def gap_review(run, state=None, eligible_only=True, limit=200, offset=0):
    """The Skill-Gap Reasoning agent's experimental states beside the authoritative classification."""
    d = EXPERIMENTS / "gap_reasoning" / run.run_id
    if not (d / "gap_states.jsonl").exists():
        return {"evidence_state": "NOT_PRODUCED", "run_id": run.run_id, "items": [],
                "reason": "The experimental gap review has not been produced for this analysis.",
                "how_to_produce": "python3 scripts/analysis/gap_reasoning_audit.py --run " + run.run_id}
    stages = {r["skill_key"]: r for r in _jsonl(d / "skill_stages.jsonl")}
    v2 = {g["skill_key"]: g for g in _jsonl(run.dir / "intelligence" / "skill_gaps_v2.jsonl")}
    rows = []
    for g in _jsonl(d / "gap_states.jsonl"):
        st = stages.get(g["skill_key"], {})
        if eligible_only and not st.get("eligible"):
            continue
        if state and g["gap_state"] != state:
            continue
        a = v2.get(g["skill_key"])
        rows.append({"skill_key": g["skill_key"], "skill_label": g["skill_label"], "gap_state": g["gap_state"],
                     "authoritative_classification": a["classification_v2"] if a else "NOT_IN_RELEASE_GAPS",
                     "coverage_level": g["coverage_level"], "access": g["access"], "practice": g["practice"],
                     "courses": g["carrying_courses"], "reason": "; ".join(g["reasons"]),
                     "other_curricula": "; ".join(f"{role.replace('_', ' ').lower()}: {txt}" for role, txt in
                                                  sorted(((g.get("corroboration") or {}).get("summary") or {}).items())),
                     "support_state": g.get("support_state"), "skill_stage": g.get("skill_stage")})
    order = {s: i for i, s in enumerate(("STRUCTURAL_GAP", "DEPTH_GAP", "LIMITED_COVERAGE", "REVIEW_REQUIRED",
                                         "OUTDATED_COVERAGE", "INSUFFICIENT_EVIDENCE", "NO_GAP"))}
    rows.sort(key=lambda r: (order.get(r["gap_state"], 9), (r["skill_label"] or "").lower()))
    score = _json(d / "scorecard.json", {})
    states = {}
    for r in rows:
        states[r["gap_state"]] = states.get(r["gap_state"], 0) + 1
    return {"evidence_state": "AVAILABLE", "authority": "EXPERIMENTAL", "run_id": run.run_id,
            "label": "Experimental gap review: deterministic and tested, awaiting human review before it replaces the "
                     "authoritative skill gaps",
            "states": states, "eligible_skills": len(rows) if eligible_only else None,
            "label_source": score.get("label_source"),
            "note": "Other curricula are shown as context and never decide a state. A document that is incomplete "
                    "can show what is taught, never what is missing.",
            **ks._page(rows, limit, offset)}
