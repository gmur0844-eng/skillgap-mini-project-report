import json
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.analysis import AnalysisRun, CurriculumSkillCoverage, SkillAlignment, AlignmentResult, CurriculumSkillDrift, SkillGap, Recommendation
from app.models.jobs import SkillDemand
from app.models.skills import Skill
from app.analytics.run_selection import select_latest_successful_run

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


def _latest_run(session: Session, dataset_name: str, population_scope: str | None = None):
    """
    Fetches every AnalysisRun for this dataset_name and delegates the actual
    "which one is authoritative" decision to the pure, unit-tested
    select_latest_successful_run() -- see app.analytics.run_selection for why
    GOLD results are versioned-snapshot rather than skip/replace-on-rerun.

    population_scope: if given, only runs with that EXACT population_scope
    are considered (e.g. "global", or "programme:5"). This matters now that
    programme/discipline-scoped runs can coexist with global ones for the
    SAME dataset_name (spec Phase 5/10) -- without this filter, a
    discipline-scoped industry-demand run could silently become "the
    latest" run the global /industry-demand endpoint returns, which would
    be exactly the kind of incompatible-evidence-combination the earlier
    hardening phase was built to prevent. Endpoints that only ever mean one
    scope (e.g. curriculum-drift, which is always programme-scoped) pass
    population_scope=None and are unaffected by this filter.
    """
    runs = session.query(AnalysisRun).filter(AnalysisRun.dataset_name == dataset_name).all()
    if population_scope is not None:
        runs = [r for r in runs if r.population_scope == population_scope]
    run_dicts = [{"id": r.id, "dataset_name": r.dataset_name, "status": r.status, "started_at": r.started_at} for r in runs]
    selected = select_latest_successful_run(run_dicts, dataset_name)
    if not selected:
        return None
    return session.query(AnalysisRun).filter(AnalysisRun.id == selected["id"]).one()


def _pending_response(dataset_name: str) -> dict:
    return {
        "status": "pending",
        "note": f"No successful '{dataset_name}' analysis run exists yet. "
        f"Run scripts/analysis/run_analytics.py to populate this.",
        "items": [],
    }


@router.get("/industry-demand")
def get_industry_demand(
    skill_id: int | None = Query(None),
    discipline_id: int | None = Query(None, description="If given, returns the latest run scoped to this discipline instead of the global population"),
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
):
    scope = "global" if discipline_id is None else f"discipline:{discipline_id}"
    run = _latest_run(db, "industry_demand", population_scope=scope)
    if not run:
        return _pending_response("industry_demand")

    q = db.query(SkillDemand).filter(SkillDemand.analysis_run_id == run.id)
    if skill_id:
        q = q.filter(SkillDemand.skill_id == skill_id)
    rows = q.order_by(SkillDemand.demand_percentage.desc()).limit(limit).all()

    return {
        "status": "ok",
        "analysis_run_id": run.id,
        "computed_at": run.finished_at.isoformat() if run.finished_at else None,
        "methodology": "demand_percentage = distinct postings mentioning the skill / eligible job postings * 100. "
        "Eligible population = non-duplicate job postings at time of run. See docs/analytics_methodology.md.",
        "items": [
            {
                "skill_id": r.skill_id,
                "posting_count": r.posting_count,
                "total_relevant_postings": r.total_relevant_postings,
                "demand_percentage": r.demand_percentage,
            }
            for r in rows
        ],
    }


@router.get("/curriculum-coverage")
def get_curriculum_coverage(
    skill_id: int | None = Query(None),
    programme_id: int | None = Query(None, description="If given, returns the latest run scoped to this programme instead of the global (all-courses) population"),
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
):
    scope = "global" if programme_id is None else f"programme:{programme_id}"
    effective_level = "overall" if programme_id is None else "programme"
    run = _latest_run(db, "curriculum_coverage", population_scope=scope)
    if not run:
        return _pending_response("curriculum_coverage")

    q = db.query(CurriculumSkillCoverage).filter(
        CurriculumSkillCoverage.analysis_run_id == run.id, CurriculumSkillCoverage.level == effective_level
    )
    if skill_id:
        q = q.filter(CurriculumSkillCoverage.skill_id == skill_id)
    rows = q.order_by(CurriculumSkillCoverage.coverage_percentage.desc()).limit(limit).all()

    return {
        "status": "ok",
        "analysis_run_id": run.id,
        "computed_at": run.finished_at.isoformat() if run.finished_at else None,
        "methodology": "coverage_percentage = distinct courses mentioning the skill / eligible courses * 100 "
        f"(level='{effective_level}', programme_id={programme_id}). See docs/analytics_methodology.md.",
        "items": [
            {
                "skill_id": r.skill_id,
                "courses_with_skill": r.courses_with_skill,
                "eligible_courses": r.eligible_courses,
                "coverage_percentage": r.coverage_percentage,
                "topics_with_skill": r.topics_with_skill,
                "outcomes_with_skill": r.outcomes_with_skill,
            }
            for r in rows
        ],
    }


@router.get("/skill-alignment")
def get_skill_alignment(
    classification: str | None = Query(None, description="HIGH_DEMAND_LOW_COVERAGE | HIGH_DEMAND_HIGH_COVERAGE | LOW_DEMAND_HIGH_COVERAGE | LOW_DEMAND_LOW_COVERAGE"),
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
):
    run = _latest_run(db, "skill_alignment")
    if not run:
        return _pending_response("skill_alignment")

    q = db.query(SkillAlignment).filter(SkillAlignment.analysis_run_id == run.id)
    if classification:
        q = q.filter(SkillAlignment.classification == classification.upper())
    rows = q.order_by(SkillAlignment.demand_rank.asc().nullslast()).limit(limit).all()

    skill_labels = {s.id: s.preferred_label for s in db.query(Skill).all()}

    overall_alignment = (
        db.query(AlignmentResult)
        .filter(AlignmentResult.analysis_run_id == run.id, AlignmentResult.level == "overall")
        .first()
    )

    return {
        "status": "ok",
        "analysis_run_id": run.id,
        "computed_at": run.finished_at.isoformat() if run.finished_at else None,
        "overall_skill_set_alignment": overall_alignment.skill_set_alignment if overall_alignment else None,
        "methodology": "Per-skill comparison of the latest industry-demand and curriculum-coverage runs. "
        "Classification is a transparent threshold rule, NOT a recommendation. "
        "TF-IDF text alignment (per-course) and skill-set Jaccard alignment are reported separately "
        "and never combined into one composite score. See docs/analytics_methodology.md.",
        "items": [
            {
                "skill_id": r.skill_id,
                "preferred_label": skill_labels.get(r.skill_id),
                "industry_posting_count": r.industry_posting_count,
                "industry_demand_percentage": r.industry_demand_percentage,
                "curriculum_course_count": r.curriculum_course_count,
                "curriculum_coverage_percentage": r.curriculum_coverage_percentage,
                "demand_rank": r.demand_rank,
                "coverage_rank": r.coverage_rank,
                "classification": r.classification,
            }
            for r in rows
        ],
    }


@router.get("/text-alignment")
def get_text_alignment(
    level: str = Query("course"),
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
):
    run = _latest_run(db, "tfidf_alignment")
    if not run:
        return _pending_response("tfidf_alignment")

    rows = (
        db.query(AlignmentResult)
        .filter(AlignmentResult.analysis_run_id == run.id, AlignmentResult.level == level)
        .order_by(AlignmentResult.tfidf_alignment.desc())
        .limit(limit)
        .all()
    )

    return {
        "status": "ok",
        "analysis_run_id": run.id,
        "computed_at": run.finished_at.isoformat() if run.finished_at else None,
        "methodology": "TF-IDF cosine similarity (text_alignment_score) between each course's topic/outcome "
        "text and an aggregate corpus of all non-duplicate job postings. A calculated text-similarity metric, "
        "not a causal or quality measure. See docs/analytics_methodology.md.",
        "items": [
            {
                "entity_id": r.entity_id,
                "text_alignment_score": r.tfidf_alignment,
                "vocabulary_size": r.vocabulary_size,
            }
            for r in rows
        ],
    }


@router.get("/industry-trends")
def get_industry_trends(
    skill_id: int | None = Query(None),
    period: str | None = Query(None, description="e.g. '2026-01' -- filter to one specific period"),
    limit: int = Query(200, le=2000),
    db: Session = Depends(get_db),
):
    """
    Historical, per-period industry demand -- from app.analytics.run_temporal_analysis.run_historical_industry_demand.
    Returns an honest pending state if that has never been run.
    """
    # Only "global" historical-demand runs exist today (discipline-scoped
    # temporal analytics is a documented future extension, not yet built) --
    # filtering explicitly here still matters: it prevents this endpoint
    # from silently returning a scoped run's data once one exists.
    run = _latest_run(db, "industry_skill_trends", population_scope="global")
    if not run:
        return _pending_response("industry_skill_trends")

    q = db.query(SkillDemand).filter(SkillDemand.analysis_run_id == run.id)
    if skill_id:
        q = q.filter(SkillDemand.skill_id == skill_id)
    if period:
        q = q.filter(SkillDemand.time_bucket == period)
    rows = q.order_by(SkillDemand.time_bucket.asc()).limit(limit).all()

    return {
        "status": "ok",
        "analysis_run_id": run.id,
        "computed_at": run.finished_at.isoformat() if run.finished_at else None,
        "methodology": "Per-period demand_percentage = distinct postings mentioning the skill in that period / "
        "eligible dated postings in that period * 100. trend_label is only ever TRENDING_UP/TRENDING_DOWN when "
        "the configured minimum-evidence rules are met; otherwise INSUFFICIENT_DATA. Never a causal claim. "
        "See docs/temporal_methodology.md.",
        "items": [
            {
                "skill_id": r.skill_id,
                "period": r.time_bucket,
                "period_start": r.period_start.isoformat() if r.period_start else None,
                "period_end": r.period_end.isoformat() if r.period_end else None,
                "posting_count": r.posting_count,
                "total_relevant_postings": r.total_relevant_postings,
                "demand_percentage": r.demand_percentage,
                "growth_rate": r.growth_rate,
                "trend_label": r.trend_label,
            }
            for r in rows
        ],
    }


@router.get("/curriculum-drift")
def get_curriculum_drift(
    programme_id: int = Query(..., description="REQUIRED: curriculum drift is always scoped to one programme; without this, results from different programmes could be silently mixed across calls."),
    status: str | None = Query(None, description="SKILL_ADDED | SKILL_REMOVED | COVERAGE_INCREASED | COVERAGE_DECREASED | UNCHANGED | INSUFFICIENT_DATA"),
    limit: int = Query(200, le=2000),
    db: Session = Depends(get_db),
):
    run = _latest_run(db, "curriculum_drift", population_scope=f"programme:{programme_id}")
    if not run:
        return _pending_response("curriculum_drift")

    q = db.query(CurriculumSkillDrift).filter(CurriculumSkillDrift.analysis_run_id == run.id)
    if status:
        q = q.filter(CurriculumSkillDrift.status == status.upper())
    rows = q.limit(limit).all()

    skill_labels = {s.id: s.preferred_label for s in db.query(Skill).all()}

    return {
        "status": "ok",
        "analysis_run_id": run.id,
        "computed_at": run.finished_at.isoformat() if run.finished_at else None,
        "methodology": "Per-skill coverage compared between two CurriculumVersion snapshots of the same "
        "programme. status is a DESCRIPTIVE classification only -- never an interpretation of quality, and a "
        "decrease is never labeled 'outdated'. See docs/temporal_methodology.md.",
        "items": [
            {
                "skill_id": r.skill_id,
                "preferred_label": skill_labels.get(r.skill_id),
                "previous_curriculum_version_id": r.previous_curriculum_version_id,
                "current_curriculum_version_id": r.current_curriculum_version_id,
                "previous_coverage_percentage": r.previous_coverage_percentage,
                "current_coverage_percentage": r.current_coverage_percentage,
                "absolute_change": r.absolute_change,
                "status": r.status,
            }
            for r in rows
        ],
    }


@router.get("/temporal-comparison")
def get_temporal_comparison(
    programme_id: int = Query(..., description="REQUIRED: temporal_skill_comparison runs are always scoped to one curriculum version's programme; without this, results from different programmes could be silently mixed across calls (same fix as /curriculum-drift)."),
    limit: int = Query(200, le=2000),
    db: Session = Depends(get_db),
):
    """
    A specific (industry period, curriculum version) pair's per-skill
    comparison -- GOLD-artifact-only (see run_temporal_industry_curriculum_comparison's
    docstring for why no dedicated DB table exists for this yet), so this
    endpoint reads the most recent successful run's metadata but points to
    the artifact for the actual records rather than re-deriving them from a
    table that doesn't exist.
    """
    run = _latest_run(db, "temporal_skill_comparison", population_scope=f"programme:{programme_id}")
    if not run:
        return _pending_response("temporal_skill_comparison")

    return {
        "status": "ok",
        "analysis_run_id": run.id,
        "computed_at": run.finished_at.isoformat() if run.finished_at else None,
        "note": "Records for this comparison are written to the GOLD artifact "
        f"(data/gold/temporal_skill_comparison/{run.id}/records.jsonl) rather than a queryable table -- "
        "see docs/temporal_methodology.md for why.",
        "population": json.loads(run.record_counts_json) if run.record_counts_json else None,
    }


@router.get("/skill-gaps")
def get_skill_gaps(
    classification: str | None = Query(None, description="MISSING | PARTIAL | COVERED | INSUFFICIENT_EVIDENCE"),
    high_demand: bool | None = Query(None),
    skill_id: int | None = Query(None),
    limit: int = Query(200, le=2000),
    db: Session = Depends(get_db),
):
    """
    Evidence-based curriculum gap classification -- see
    docs/gap_classification_methodology.md. Never returns a numeric "gap
    score" (the project deliberately does not compute one this phase).
    """
    # skill_gap_classification runs now record population_scope (Phase 4/5
    # hardening); default to "global" -- the only scope the orchestration
    # auto-selects today -- so a future explicitly-programme-scoped run
    # never silently becomes this endpoint's answer.
    run = _latest_run(db, "skill_gap_classification", population_scope="global")
    if not run:
        return _pending_response("skill_gap_classification")

    q = db.query(SkillGap).filter(SkillGap.analysis_run_id == run.id)
    if classification:
        q = q.filter(SkillGap.classification == classification.upper())
    if high_demand is not None:
        q = q.filter(SkillGap.high_demand == (1 if high_demand else 0))
    if skill_id:
        q = q.filter(SkillGap.skill_id == skill_id)
    rows = q.limit(limit).all()

    skill_labels = {s.id: s.preferred_label for s in db.query(Skill).all()}
    source_runs = json.loads(run.record_counts_json) if run.record_counts_json else {}

    return {
        "status": "ok",
        "analysis_run_id": run.id,
        "computed_at": run.finished_at.isoformat() if run.finished_at else None,
        "source_runs": source_runs,
        "methodology": "MISSING = real, non-zero industry demand with genuinely zero curriculum coverage. "
        "PARTIAL = curriculum coverage below the configured partial_coverage_threshold. COVERED = coverage "
        "meets that threshold, OR industry demand is genuinely zero (no unmet demand = no meaningful gap). "
        "INSUFFICIENT_EVIDENCE = either side's population was unavailable. trend_label/drift_status are "
        "separate evidence dimensions, never folded into the classification -- a decrease is never labeled "
        "'outdated'. No numeric gap score is computed. See docs/gap_classification_methodology.md.",
        "items": [
            {
                "skill_id": r.skill_id,
                "preferred_label": skill_labels.get(r.skill_id),
                "classification": r.classification,
                "evidence_state": r.evidence_state,
                "industry_demand_percentage": r.industry_demand,
                "curriculum_coverage_percentage": r.curriculum_coverage,
                "high_demand": bool(r.high_demand) if r.high_demand is not None else None,
                "trend_label": r.trend_label,
                "drift_status": r.drift_status,
                "trend_compatibility": r.trend_compatibility,
                "drift_compatibility": r.drift_compatibility,
                "reasons": json.loads(r.reasons_json) if r.reasons_json else [],
            }
            for r in rows
        ],
    }


@router.get("/recommendations")
def get_recommendations(
    action_type: str | None = Query(None, description="ADD_NEW_SUBJECT | ADD_ELECTIVE | ADD_MODULE | UPDATE_EXISTING_TOPIC | EXPAND_EXISTING_TOPIC | REVIEW_EXISTING_COURSE"),
    recommendation_state: str | None = Query(None, description="RECOMMENDATION_SUPPORTED | INSUFFICIENT_EVIDENCE | NO_ACTION_INDICATED"),
    skill_id: int | None = Query(None),
    course_id: int | None = Query(None),
    limit: int = Query(200, le=2000),
    db: Session = Depends(get_db),
):
    """
    Deterministic, evidence-based curriculum recommendations -- see
    docs/recommendation_methodology.md. No LLM, no numeric priority score.
    """
    # curriculum_recommendations runs inherit their scope from the gap
    # classification run they were built on (Phase 4/5 hardening); default
    # to "global" for the same reason as /skill-gaps above.
    run = _latest_run(db, "curriculum_recommendations", population_scope="global")
    if not run:
        return _pending_response("curriculum_recommendations")

    q = db.query(Recommendation).filter(Recommendation.analysis_run_id == run.id)
    if action_type:
        q = q.filter(Recommendation.action_type == action_type.upper())
    if recommendation_state:
        q = q.filter(Recommendation.recommendation_state == recommendation_state.upper())
    if skill_id:
        q = q.filter(Recommendation.skill_id == skill_id)
    if course_id:
        q = q.filter(Recommendation.course_id == course_id)
    rows = q.limit(limit).all()

    skill_labels = {s.id: s.preferred_label for s in db.query(Skill).all()}

    return {
        "status": "ok",
        "analysis_run_id": run.id,
        "computed_at": run.finished_at.isoformat() if run.finished_at else None,
        "methodology": "Deterministic rule engine built on top of skill-gap classification evidence. "
        "recommendation_state distinguishes RECOMMENDATION_SUPPORTED from INSUFFICIENT_EVIDENCE and "
        "NO_ACTION_INDICATED -- weak/insufficient evidence never produces a strong action. No numeric "
        "priority/score is computed. Course targeting only uses courses with real ExtractedSkill evidence, "
        "never invented titles. See docs/recommendation_methodology.md.",
        "items": [
            {
                "skill_id": r.skill_id,
                "preferred_label": skill_labels.get(r.skill_id),
                "recommendation_state": r.recommendation_state,
                "action_type": r.action_type,
                "target_level": r.target_level,
                "target_course_codes": json.loads(r.target_course_codes_json) if r.target_course_codes_json else [],
                "grouped_skill_ids": json.loads(r.grouped_skill_ids_json) if r.grouped_skill_ids_json else [],
                "industry_demand": r.industry_demand,
                "current_coverage": r.current_coverage,
                "trend_label": r.trend_label,
                "drift_status": r.drift_status,
                "reasons": json.loads(r.reasons_json) if r.reasons_json else [],
            }
            for r in rows
        ],
    }
