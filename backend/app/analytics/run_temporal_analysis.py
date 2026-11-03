"""
Temporal / drift analysis orchestration (DB-dependent). Wires the pure logic
in temporal.py / historical_demand.py / trend_analysis.py / curriculum_drift.py
to real JobPosting / ExtractedSkill / CurriculumVersion / Course data.

Versioned-snapshot semantics (see app.analytics.run_selection) apply here
exactly as in run_analysis.py: every successful call creates a new
AnalysisRun and fresh GOLD rows; nothing is overwritten across runs.
"""
import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.jobs import JobPosting, ExtractedSkill, SkillDemand
from app.models.curriculum import Course, CurriculumTopic, CourseLearningOutcome, Module, CurriculumVersion
from app.models.analysis import AnalysisRun, CurriculumSkillDrift
from app.models.data_source import DataQualityMetric
from app.analytics.temporal import bucket_date, period_bounds
from app.analytics.historical_demand import compute_historical_skill_demand
from app.analytics.trend_analysis import assess_trend_sufficiency, compute_relative_change, compute_trend_label
from app.analytics.curriculum_coverage import compute_curriculum_coverage
from app.analytics.curriculum_drift import compare_curriculum_versions, compare_courses, compare_course_skills
from app.analytics.skill_set_alignment import resolve_evidence_value, classify_demand_coverage
from app.analytics.data_quality import (
    compute_temporal_industry_quality_metrics,
    compute_temporal_curriculum_quality_metrics,
    compute_drift_quality_metrics,
    metrics_to_rows,
)
from app.pipelines.preprocessing.artifact_writer import write_jsonl_records
from app.core.config import get_settings


def run_historical_industry_demand(session: Session, granularity: str = "month") -> dict:
    """
    Buckets all non-duplicate JobPostings by their REAL posted_date (never
    ingestion date) into periods, computes per-period demand for every
    canonical skill, and additionally computes a trend (relative change +
    sufficiency-gated label) between each skill's two most recent periods,
    writing growth_rate/trend_label onto that skill's LATEST period's
    SkillDemand row -- reusing the existing columns rather than a new model.
    """
    settings = get_settings()
    run = AnalysisRun(
        run_type="analysis", dataset_name="industry_skill_trends", status="running",
        started_at=datetime.utcnow(), pipeline_version="0.1.0", population_scope="global",
    )
    session.add(run)
    session.flush()

    try:
        posting_rows = (
            session.query(JobPosting.id, JobPosting.posted_date).filter(JobPosting.is_duplicate == 0).all()
        )
        postings = [{"job_posting_id": pid, "posted_date": pdate} for pid, pdate in posting_rows]

        mention_rows = (
            session.query(ExtractedSkill.job_posting_id, ExtractedSkill.normalized_skill_id)
            .filter(ExtractedSkill.job_posting_id.isnot(None), ExtractedSkill.mapping_status == "mapped")
            .all()
        )
        mentions = [{"job_posting_id": pid, "normalized_skill_id": sid} for pid, sid in mention_rows]

        result = compute_historical_skill_demand(postings, mentions, granularity)
        periods = result["periods"]

        period_eligible_counts = {}
        for p in postings:
            bucket = bucket_date(p["posted_date"], granularity)
            if bucket is not None:
                period_eligible_counts[bucket] = period_eligible_counts.get(bucket, 0) + 1

        sorted_periods = sorted(periods.keys())

        skill_period_series = {}
        for period in sorted_periods:
            for skill_id, stats in periods[period].items():
                skill_period_series.setdefault(skill_id, []).append((period, stats))

        rows_by_skill_and_period = {}
        for period in sorted_periods:
            start, end = period_bounds(period, granularity)
            for skill_id, stats in periods[period].items():
                row = SkillDemand(
                    skill_id=skill_id,
                    time_bucket=period,
                    period_start=start,
                    period_end=end,
                    posting_count=stats["posting_count"],
                    total_relevant_postings=stats["total_relevant_postings"],
                    demand_percentage=stats["demand_percentage"],
                    analysis_run_id=run.id,
                )
                session.add(row)
                rows_by_skill_and_period[(skill_id, period)] = row

        skills_sufficient, skills_insufficient = 0, 0
        for skill_id, series in skill_period_series.items():
            eligible_list = [period_eligible_counts.get(p, 0) for p, _ in series]
            skill_total = sum(s["posting_count"] for _, s in series)
            sufficient = assess_trend_sufficiency(
                len(series), eligible_list, skill_total,
                settings.min_periods_for_trend, settings.min_eligible_postings_per_period,
                settings.min_skill_postings_for_trend,
            )
            if sufficient:
                skills_sufficient += 1
            else:
                skills_insufficient += 1

            if len(series) >= 2:
                (_, prev_stats), (latest_period, latest_stats) = series[-2], series[-1]
                growth_rate = compute_relative_change(prev_stats["demand_percentage"], latest_stats["demand_percentage"])
                trend_label = compute_trend_label(prev_stats["demand_percentage"], latest_stats["demand_percentage"], sufficient)
                latest_row = rows_by_skill_and_period[(skill_id, latest_period)]
                latest_row.growth_rate = growth_rate
                latest_row.trend_label = trend_label
            else:
                only_period = series[0][0]
                rows_by_skill_and_period[(skill_id, only_period)].trend_label = "INSUFFICIENT_DATA"

        quality_metrics = compute_temporal_industry_quality_metrics(
            total_postings=len(postings),
            dated_postings=len(result["dated_posting_ids"]),
            postings_per_period=period_eligible_counts,
            skills_with_sufficient_evidence=skills_sufficient,
            skills_with_insufficient_evidence=skills_insufficient,
        )
        for row_dict in metrics_to_rows(quality_metrics, run.id, None):
            session.add(DataQualityMetric(**row_dict))

        write_jsonl_records(
            "gold", "industry_skill_trends", run.id,
            [
                {"skill_id": sid, "period": period, **stats}
                for period, skill_stats in periods.items()
                for sid, stats in skill_stats.items()
            ],
        )

        run.status = "succeeded"
        run.records_processed = sum(len(v) for v in periods.values())
        run.record_counts_json = json.dumps({"eligible_job_postings": len(postings), "periods": len(sorted_periods)})
        run.finished_at = datetime.utcnow()
        session.commit()

        return {
            "analysis_run_id": run.id,
            "periods_computed": sorted_periods,
            "granularity": granularity,
            "quality_metrics": quality_metrics,
        }
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_log = str(exc)
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        raise


def _resolve_course_id_for_mention(m, topic_to_course, outcome_to_course):
    if m.course_id is not None:
        return m.course_id
    if m.curriculum_topic_id is not None:
        return topic_to_course.get(m.curriculum_topic_id)
    if m.course_learning_outcome_id is not None:
        return outcome_to_course.get(m.course_learning_outcome_id)
    return None


def _coverage_for_curriculum_version(session: Session, curriculum_version_id: int) -> dict:
    """
    Coverage scoped to ONE curriculum version's own courses only (unlike
    run_curriculum_coverage_analysis's level="overall", which covers every
    course in the DB). Returns (coverage_by_skill: {skill_id: pct}, course_count).
    """
    course_ids = {cid for (cid,) in session.query(Course.id).filter(Course.curriculum_version_id == curriculum_version_id).all()}
    if not course_ids:
        return {}, 0

    topic_to_course = {}
    for topic_id, module_id in session.query(CurriculumTopic.id, CurriculumTopic.module_id).all():
        module = session.query(Module).filter(Module.id == module_id).one_or_none()
        if module and module.course_id in course_ids:
            topic_to_course[topic_id] = module.course_id

    outcome_to_course = {
        oid: cid
        for oid, cid in session.query(CourseLearningOutcome.id, CourseLearningOutcome.course_id).all()
        if cid in course_ids
    }

    mention_rows = (
        session.query(ExtractedSkill)
        .filter(ExtractedSkill.mapping_status == "mapped")
        .filter(
            (ExtractedSkill.course_id.in_(course_ids))
            | (ExtractedSkill.curriculum_topic_id.in_(topic_to_course.keys()) if topic_to_course else False)
            | (ExtractedSkill.course_learning_outcome_id.in_(outcome_to_course.keys()) if outcome_to_course else False)
        )
        .all()
    )

    mentions = []
    for m in mention_rows:
        course_id = _resolve_course_id_for_mention(m, topic_to_course, outcome_to_course)
        if course_id is not None:
            mentions.append({"course_id": course_id, "normalized_skill_id": m.normalized_skill_id})

    coverage = compute_curriculum_coverage(mentions, course_ids)
    coverage_pct_by_skill = {skill_id: stats["coverage_percentage"] for skill_id, stats in coverage.items()}
    return coverage_pct_by_skill, len(course_ids)


def _course_skill_sets(session: Session, course_rows: list) -> dict:
    """
    Builds {course_code: set(skill_id)} for the given Course rows -- resolves
    mentions from the course title itself, its topics, and its learning
    outcomes, same resolution logic as _coverage_for_curriculum_version.
    Courses with no course_code are skipped (nothing to key them by).
    """
    course_ids = {c.id for c in course_rows}
    course_id_to_code = {c.id: c.course_code for c in course_rows if c.course_code}
    if not course_ids:
        return {}

    topic_to_course = {}
    for topic_id, module_id in session.query(CurriculumTopic.id, CurriculumTopic.module_id).all():
        module = session.query(Module).filter(Module.id == module_id).one_or_none()
        if module and module.course_id in course_ids:
            topic_to_course[topic_id] = module.course_id

    outcome_to_course = {
        oid: cid
        for oid, cid in session.query(CourseLearningOutcome.id, CourseLearningOutcome.course_id).all()
        if cid in course_ids
    }

    mention_rows = (
        session.query(ExtractedSkill)
        .filter(ExtractedSkill.mapping_status == "mapped")
        .filter(
            (ExtractedSkill.course_id.in_(course_ids))
            | (ExtractedSkill.curriculum_topic_id.in_(topic_to_course.keys()) if topic_to_course else False)
            | (ExtractedSkill.course_learning_outcome_id.in_(outcome_to_course.keys()) if outcome_to_course else False)
        )
        .all()
    )

    result = {}
    for m in mention_rows:
        course_id = _resolve_course_id_for_mention(m, topic_to_course, outcome_to_course)
        code = course_id_to_code.get(course_id)
        if code is not None and m.normalized_skill_id is not None:
            result.setdefault(code, set()).add(m.normalized_skill_id)
    return result


def run_curriculum_version_comparison(session: Session, previous_version_id: int, current_version_id: int) -> dict:
    """
    Compares two CurriculumVersion rows of (expected to be) the SAME
    programme. Computes skill-level drift (persisted to CurriculumSkillDrift)
    and course-level drift (GOLD artifact only -- see CurriculumSkillDrift's
    docstring for why no separate course-drift table was added).
    """
    run = AnalysisRun(
        run_type="analysis", dataset_name="curriculum_drift", status="running",
        started_at=datetime.utcnow(), pipeline_version="0.1.0",
    )
    session.add(run)
    session.flush()

    try:
        prev_version = session.query(CurriculumVersion).filter(CurriculumVersion.id == previous_version_id).one_or_none()
        curr_version = session.query(CurriculumVersion).filter(CurriculumVersion.id == current_version_id).one_or_none()
        if prev_version is None or curr_version is None:
            raise ValueError(
                f"CurriculumVersion not found (previous_version_id={previous_version_id}, "
                f"current_version_id={current_version_id})."
            )
        if prev_version.programme_id != curr_version.programme_id:
            # This is a genuine data-integrity problem, not something to
            # silently paper over: "curriculum drift" is only meaningful
            # between two versions of the SAME programme.
            raise ValueError(
                f"Cannot compute curriculum drift across different programmes "
                f"(previous_version programme_id={prev_version.programme_id}, "
                f"current_version programme_id={curr_version.programme_id})."
            )
        run.population_scope = f"programme:{prev_version.programme_id}"

        prev_coverage_raw, prev_course_count = _coverage_for_curriculum_version(session, previous_version_id)
        curr_coverage_raw, curr_course_count = _coverage_for_curriculum_version(session, current_version_id)

        all_skill_ids = set(prev_coverage_raw) | set(curr_coverage_raw)
        prev_resolved = {
            sid: resolve_evidence_value(prev_coverage_raw.get(sid), sid in prev_coverage_raw, prev_course_count)
            for sid in all_skill_ids
        }
        curr_resolved = {
            sid: resolve_evidence_value(curr_coverage_raw.get(sid), sid in curr_coverage_raw, curr_course_count)
            for sid in all_skill_ids
        }

        drift = compare_curriculum_versions(prev_resolved, curr_resolved)

        for skill_id, d in drift.items():
            session.add(
                CurriculumSkillDrift(
                    analysis_run_id=run.id,
                    previous_curriculum_version_id=previous_version_id,
                    current_curriculum_version_id=current_version_id,
                    skill_id=skill_id,
                    previous_coverage_percentage=d["previous_coverage"],
                    current_coverage_percentage=d["current_coverage"],
                    absolute_change=d["absolute_change"],
                    status=d["status"],
                )
            )

        # Course-level drift: which courses changed, and for courses present
        # in BOTH versions, which skills were added/removed within them.
        prev_course_rows = session.query(Course).filter(Course.curriculum_version_id == previous_version_id).all()
        curr_course_rows = session.query(Course).filter(Course.curriculum_version_id == current_version_id).all()
        prev_courses = {c.course_code for c in prev_course_rows if c.course_code}
        curr_courses = {c.course_code for c in curr_course_rows if c.course_code}
        course_changes = compare_courses(prev_courses, curr_courses)

        prev_course_skills = _course_skill_sets(session, prev_course_rows)
        curr_course_skills = _course_skill_sets(session, curr_course_rows)
        course_skill_changes = compare_course_skills(prev_course_skills, curr_course_skills)

        write_jsonl_records(
            "gold", "curriculum_drift", run.id,
            [{"skill_id": sid, **d} for sid, d in drift.items()],
        )
        write_jsonl_records(
            "gold", "curriculum_drift_courses", run.id,
            [
                {
                    "added_courses": sorted(course_changes["added"]),
                    "removed_courses": sorted(course_changes["removed"]),
                    "unchanged_courses": sorted(course_changes["unchanged"]),
                    "course_skill_changes": {
                        code: {"added": sorted(c["added"]), "removed": sorted(c["removed"])}
                        for code, c in course_skill_changes.items()
                    },
                }
            ],
        )

        drift_quality_metrics = compute_drift_quality_metrics(list(drift.values()))
        total_versions = session.query(CurriculumVersion).count()
        versions_missing_period = (
            session.query(CurriculumVersion)
            .filter((CurriculumVersion.effective_period.is_(None)) | (CurriculumVersion.effective_period == ""))
            .count()
        )
        curriculum_quality_metrics = compute_temporal_curriculum_quality_metrics(
            curriculum_versions=total_versions,
            comparable_version_pairs=1,  # this one call compares exactly one pair
            courses_per_version={str(previous_version_id): prev_course_count, str(current_version_id): curr_course_count},
            versions_with_missing_temporal_metadata=versions_missing_period,
        )
        for row_dict in metrics_to_rows(drift_quality_metrics, run.id, None):
            session.add(DataQualityMetric(**row_dict))
        for row_dict in metrics_to_rows(curriculum_quality_metrics, run.id, None):
            session.add(DataQualityMetric(**row_dict))

        run.status = "succeeded"
        run.records_processed = len(drift)
        run.record_counts_json = json.dumps(
            {"previous_courses": prev_course_count, "current_courses": curr_course_count}
        )
        run.finished_at = datetime.utcnow()
        session.commit()

        return {
            "analysis_run_id": run.id,
            "skills_compared": len(drift),
            "course_changes": {k: sorted(v) for k, v in course_changes.items()},
            "quality_metrics": drift_quality_metrics,
        }
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_log = str(exc)
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        raise


def run_temporal_industry_curriculum_comparison(
    session: Session,
    historical_demand_run_id: int,
    time_bucket: str,
    curriculum_version_id: int,
) -> dict:
    """
    Combines ONE industry period (a specific time_bucket from a
    run_historical_industry_demand run) with ONE curriculum version's
    coverage into a per-skill comparison. GOLD-artifact only (no dedicated DB
    table) -- see spec Section 12: this must not become a new composite
    score, and the existing SkillAlignment/AlignmentResult tables are scoped
    to "overall" comparisons, not a specific (period, version) pair; adding a
    third near-duplicate table for this was judged unnecessary over-modeling.
    """
    settings = get_settings()
    run = AnalysisRun(
        run_type="analysis", dataset_name="temporal_skill_comparison", status="running",
        started_at=datetime.utcnow(), pipeline_version="0.1.0",
    )
    session.add(run)
    session.flush()

    try:
        curriculum_version = session.query(CurriculumVersion).filter(CurriculumVersion.id == curriculum_version_id).one_or_none()
        if curriculum_version is None:
            raise ValueError(f"CurriculumVersion not found (curriculum_version_id={curriculum_version_id}).")
        run.population_scope = f"programme:{curriculum_version.programme_id}"

        demand_rows = (
            session.query(SkillDemand)
            .filter(SkillDemand.analysis_run_id == historical_demand_run_id, SkillDemand.time_bucket == time_bucket)
            .all()
        )
        demand_by_skill = {d.skill_id: d for d in demand_rows}
        eligible_postings_this_period = demand_rows[0].total_relevant_postings if demand_rows else 0

        coverage_raw, course_count = _coverage_for_curriculum_version(session, curriculum_version_id)

        all_skill_ids = set(demand_by_skill) | set(coverage_raw)
        thresholds_json = json.dumps(
            {"high_demand_threshold": settings.high_demand_threshold, "high_coverage_threshold": settings.high_coverage_threshold}
        )

        comparison_records = []
        for skill_id in all_skill_ids:
            d = demand_by_skill.get(skill_id)
            demand_pct = resolve_evidence_value(
                d.demand_percentage if d else None, d is not None, eligible_postings_this_period
            )
            coverage_pct = resolve_evidence_value(
                coverage_raw.get(skill_id), skill_id in coverage_raw, course_count
            )
            classification = classify_demand_coverage(
                demand_pct, coverage_pct, settings.high_demand_threshold, settings.high_coverage_threshold
            )
            comparison_records.append(
                {
                    "skill_id": skill_id,
                    "industry_period": time_bucket,
                    "industry_demand_percentage": demand_pct,
                    "industry_posting_count": d.posting_count if d else (0 if eligible_postings_this_period > 0 else None),
                    "curriculum_version_id": curriculum_version_id,
                    "curriculum_coverage_percentage": coverage_pct,
                    "classification": classification,
                }
            )

        write_jsonl_records("gold", "temporal_skill_comparison", run.id, comparison_records)

        run.status = "succeeded"
        run.records_processed = len(comparison_records)
        run.record_counts_json = json.dumps(
            {"eligible_job_postings": eligible_postings_this_period, "eligible_courses": course_count}
        )
        run.finished_at = datetime.utcnow()
        session.commit()

        return {
            "analysis_run_id": run.id,
            "time_bucket": time_bucket,
            "curriculum_version_id": curriculum_version_id,
            "skills_compared": len(comparison_records),
            "thresholds_used": json.loads(thresholds_json),
        }
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_log = str(exc)
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        raise
