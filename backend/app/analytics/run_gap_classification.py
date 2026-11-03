"""
Skill-gap classification orchestration (DB-dependent). Combines the outputs
of already-existing analysis runs (industry demand, curriculum coverage,
optionally historical trends and curriculum drift) into SkillGap rows via
the pure app.analytics.gap_classification.classify_skill_gap.

This function does NOT recompute demand/coverage/trend/drift itself -- it
reads already-persisted GOLD rows from the runs identified (explicitly, or
via select_latest_successful_run) and classifies on top of them.

COURSE-LEVEL SCOPE (documented, not fabricated): this project's industry
demand is programme/dataset-level, not course-level -- there is no
per-course industry evidence to classify against. So course-level output
here is a lighter-weight, honest data point: "which specific courses (if
any) currently contain evidence of this skill", not a full per-course
classification. See docs/gap_classification_methodology.md.
"""
import json
from datetime import datetime

from app.models.jobs import SkillDemand, ExtractedSkill
from app.models.curriculum import Course, CurriculumTopic, CourseLearningOutcome, Module
from app.models.analysis import AnalysisRun, CurriculumSkillCoverage, CurriculumSkillDrift, SkillGap
from app.models.data_source import DataQualityMetric
from app.analytics.run_selection import select_latest_successful_run
from app.analytics.run_compatibility import check_run_compatibility, COMPATIBLE
from app.analytics.skill_set_alignment import resolve_evidence_value
from app.analytics.gap_classification import classify_skill_gap, aggregate_gap_counts
from app.analytics.data_quality import metrics_to_rows
from app.pipelines.preprocessing.artifact_writer import write_jsonl_records
from app.core.config import get_settings


def _find_latest_run_id(session, dataset_name, population_scope=None):
    """
    population_scope: if given, only runs with that EXACT population_scope
    are considered -- e.g. "global". Without this, once programme/discipline
    -scoped runs can coexist with global ones for the same dataset_name
    (spec Phase 5 generalization), the "latest" run picked here could
    silently be a narrowly-scoped one even when the caller expected the
    global population, defeating the whole point of run-compatibility
    hardening. Gap classification currently only ever auto-selects "global"
    demand/coverage runs by default (see run_skill_gap_classification's
    default call below) -- explicit programme-scoped gap classification is
    not yet wired end-to-end and is documented as a known limitation.
    """
    runs = session.query(AnalysisRun).filter(AnalysisRun.dataset_name == dataset_name).all()
    if population_scope is not None:
        runs = [r for r in runs if r.population_scope == population_scope]
    run_dicts = [{"id": r.id, "dataset_name": r.dataset_name, "status": r.status, "started_at": r.started_at} for r in runs]
    selected = select_latest_successful_run(run_dicts, dataset_name)
    return selected["id"] if selected else None


def _population_from_run(session, run_id, key):
    if run_id is None:
        return 0
    run = session.query(AnalysisRun).filter(AnalysisRun.id == run_id).one_or_none()
    if run is None or not run.record_counts_json:
        return 0
    return json.loads(run.record_counts_json).get(key, 0)


def _courses_containing_skill(session, skill_id):
    mentions = (
        session.query(ExtractedSkill)
        .filter(ExtractedSkill.normalized_skill_id == skill_id, ExtractedSkill.mapping_status == "mapped")
        .filter(
            (ExtractedSkill.course_id.isnot(None))
            | (ExtractedSkill.curriculum_topic_id.isnot(None))
            | (ExtractedSkill.course_learning_outcome_id.isnot(None))
        )
        .all()
    )
    if not mentions:
        return []

    course_ids = set()
    for m in mentions:
        if m.course_id is not None:
            course_ids.add(m.course_id)
        elif m.curriculum_topic_id is not None:
            topic = session.query(CurriculumTopic).filter(CurriculumTopic.id == m.curriculum_topic_id).one_or_none()
            if topic:
                module = session.query(Module).filter(Module.id == topic.module_id).one_or_none()
                if module:
                    course_ids.add(module.course_id)
        elif m.course_learning_outcome_id is not None:
            outcome = (
                session.query(CourseLearningOutcome)
                .filter(CourseLearningOutcome.id == m.course_learning_outcome_id)
                .one_or_none()
            )
            if outcome:
                course_ids.add(outcome.course_id)

    codes = [
        c.course_code
        for c in session.query(Course).filter(Course.id.in_(course_ids)).all()
        if c.course_code
    ]
    return sorted(codes)


def run_skill_gap_classification(
    session,
    demand_run_id=None,
    coverage_run_id=None,
    trend_run_id=None,
    drift_run_id=None,
    include_course_evidence=True,
):
    """
    If demand_run_id/coverage_run_id are not given, the latest successful
    "industry_demand"/"curriculum_coverage" runs are used. trend_run_id/
    drift_run_id are OPTIONAL: if omitted, this function looks for a latest
    successful "industry_skill_trends"/"curriculum_drift" run and uses it if
    found; if none exists, trend_label/drift_status stay None for every
    skill (not an error).
    """
    settings = get_settings()
    run = AnalysisRun(
        run_type="analysis", dataset_name="skill_gap_classification", status="running",
        started_at=datetime.utcnow(), pipeline_version="0.1.0",
    )
    session.add(run)
    session.flush()

    try:
        demand_run_id = demand_run_id or _find_latest_run_id(session, "industry_demand", population_scope="global")
        coverage_run_id = coverage_run_id or _find_latest_run_id(session, "curriculum_coverage", population_scope="global")
        trend_run_id = trend_run_id or _find_latest_run_id(session, "industry_skill_trends", population_scope="global")
        drift_run_id = drift_run_id or _find_latest_run_id(session, "curriculum_drift")

        demand_by_skill = {}
        if demand_run_id:
            demand_by_skill = {
                d.skill_id: d
                for d in session.query(SkillDemand)
                .filter(SkillDemand.analysis_run_id == demand_run_id, SkillDemand.time_bucket == "overall")
                .all()
            }
        coverage_by_skill = {}
        if coverage_run_id:
            coverage_by_skill = {
                c.skill_id: c
                for c in session.query(CurriculumSkillCoverage)
                .filter(CurriculumSkillCoverage.analysis_run_id == coverage_run_id, CurriculumSkillCoverage.level == "overall")
                .all()
            }

        eligible_job_postings = _population_from_run(session, demand_run_id, "eligible_job_postings")
        eligible_courses = _population_from_run(session, coverage_run_id, "eligible_courses")

        demand_scope = None
        if demand_run_id:
            demand_run = session.query(AnalysisRun).filter(AnalysisRun.id == demand_run_id).one_or_none()
            demand_scope = demand_run.population_scope if demand_run else None

        trend_scope = None
        if trend_run_id:
            trend_run = session.query(AnalysisRun).filter(AnalysisRun.id == trend_run_id).one_or_none()
            trend_scope = trend_run.population_scope if trend_run else None
        drift_scope = None
        if drift_run_id:
            drift_run = session.query(AnalysisRun).filter(AnalysisRun.id == drift_run_id).one_or_none()
            drift_scope = drift_run.population_scope if drift_run else None

        compatibility = check_run_compatibility(
            demand_scope,
            {
                "trend": {"scope": trend_scope, "exists": trend_run_id is not None},
                "drift": {"scope": drift_scope, "exists": drift_run_id is not None},
            },
        )
        # HARDENING (spec: "never silently combine incompatible snapshots"):
        # only feed trend_label/drift_status into classify_skill_gap (where
        # they influence the human-readable `reasons`) when the run they came
        # from is verified COMPATIBLE with the demand/coverage population
        # this gap classification is built on. Otherwise the raw value is
        # still recorded on the SkillGap row (see below) alongside its
        # compatibility verdict -- visible, never hidden, but not presented
        # as validated evidence for THIS classification.
        trend_usable = compatibility["trend"] == COMPATIBLE
        drift_usable = compatibility["drift"] == COMPATIBLE

        trend_by_skill = {}
        if trend_run_id:
            trend_rows = session.query(SkillDemand).filter(SkillDemand.analysis_run_id == trend_run_id).all()
            latest_by_skill = {}
            for row in trend_rows:
                existing = latest_by_skill.get(row.skill_id)
                if existing is None or (row.period_start and (existing.period_start is None or row.period_start > existing.period_start)):
                    latest_by_skill[row.skill_id] = row
            trend_by_skill = {sid: row.trend_label for sid, row in latest_by_skill.items()}

        drift_by_skill = {}
        if drift_run_id:
            drift_rows = session.query(CurriculumSkillDrift).filter(CurriculumSkillDrift.analysis_run_id == drift_run_id).all()
            drift_by_skill = {d.skill_id: d.status for d in drift_rows}

        all_skill_ids = set(demand_by_skill) | set(coverage_by_skill)
        thresholds_json = json.dumps(
            {"high_demand_threshold": settings.high_demand_threshold, "partial_coverage_threshold": settings.partial_coverage_threshold}
        )

        gap_records_for_aggregation = []
        artifact_records = []

        for skill_id in all_skill_ids:
            d = demand_by_skill.get(skill_id)
            c = coverage_by_skill.get(skill_id)

            demand_pct = resolve_evidence_value(d.demand_percentage if d else None, d is not None, eligible_job_postings)
            coverage_pct = resolve_evidence_value(c.coverage_percentage if c else None, c is not None, eligible_courses)

            raw_trend_label = trend_by_skill.get(skill_id)
            raw_drift_status = drift_by_skill.get(skill_id)

            result = classify_skill_gap(
                demand_pct, coverage_pct,
                settings.high_demand_threshold, settings.partial_coverage_threshold,
                trend_label=raw_trend_label if trend_usable else None,
                drift_status=raw_drift_status if drift_usable else None,
            )
            gap_records_for_aggregation.append(result)

            if not trend_usable and raw_trend_label is not None:
                result["reasons"].append(
                    f"Trend evidence exists (trend_label={raw_trend_label}) but was NOT used: its source run's "
                    f"population scope ({trend_scope}) is {compatibility['trend']} relative to this classification's "
                    f"scope ({demand_scope}). See trend_compatibility on this record."
                )
            if not drift_usable and raw_drift_status is not None:
                result["reasons"].append(
                    f"Curriculum drift evidence exists (drift_status={raw_drift_status}) but was NOT used: its "
                    f"source run's population scope ({drift_scope}) is {compatibility['drift']} relative to this "
                    f"classification's scope ({demand_scope}). See drift_compatibility on this record."
                )

            courses_with_evidence = _courses_containing_skill(session, skill_id) if include_course_evidence else None

            session.add(
                SkillGap(
                    analysis_run_id=run.id,
                    skill_id=skill_id,
                    industry_demand=result["industry_demand_percentage"],
                    curriculum_coverage=result["curriculum_coverage_percentage"],
                    high_demand=(1 if result["high_demand"] else (0 if result["high_demand"] is False else None)),
                    trend_label=raw_trend_label,
                    drift_status=raw_drift_status,
                    trend_compatibility=compatibility["trend"],
                    drift_compatibility=compatibility["drift"],
                    classification=result["classification"],
                    evidence_state=result["evidence_state"],
                    reasons_json=json.dumps(result["reasons"]),
                    thresholds_used_json=thresholds_json,
                    source_demand_run_id=demand_run_id,
                    source_coverage_run_id=coverage_run_id,
                    source_trend_run_id=trend_run_id,
                    source_drift_run_id=drift_run_id,
                )
            )

            artifact_records.append(
                {
                    "skill_id": skill_id,
                    **result,
                    "raw_trend_label": raw_trend_label,
                    "raw_drift_status": raw_drift_status,
                    "trend_compatibility": compatibility["trend"],
                    "drift_compatibility": compatibility["drift"],
                    "courses_with_evidence": courses_with_evidence,
                }
            )

        programme_counts = aggregate_gap_counts(gap_records_for_aggregation)

        write_jsonl_records("gold", "skill_gap_classification", run.id, artifact_records)

        for row_dict in metrics_to_rows(programme_counts, run.id, None):
            session.add(DataQualityMetric(**row_dict))

        run.status = "succeeded"
        run.records_processed = len(all_skill_ids)
        run.population_scope = demand_scope
        # ^ This gap-classification run's own scope IS the scope of the demand
        #   evidence it was built from (coverage is checked for compatibility
        #   with it above) -- recording this, rather than leaving it NULL,
        #   is what lets the API filter by scope instead of blindly trusting
        #   "latest run" (Phase 4/5 hardening: an evidence result must never
        #   silently appear for a population it was not computed for).
        run.record_counts_json = json.dumps(
            {
                "demand_run_id": demand_run_id, "coverage_run_id": coverage_run_id,
                "trend_run_id": trend_run_id, "drift_run_id": drift_run_id,
                "eligible_job_postings": eligible_job_postings, "eligible_courses": eligible_courses,
            }
        )
        run.finished_at = datetime.utcnow()
        session.commit()

        return {
            "analysis_run_id": run.id,
            "skills_classified": len(all_skill_ids),
            "source_runs": {
                "demand_run_id": demand_run_id, "coverage_run_id": coverage_run_id,
                "trend_run_id": trend_run_id, "drift_run_id": drift_run_id,
            },
            "counts": programme_counts,
        }
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_log = str(exc)
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        raise
