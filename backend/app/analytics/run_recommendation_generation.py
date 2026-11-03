"""
Recommendation generation orchestration (DB-dependent). Reads already-
persisted SkillGap rows (from run_skill_gap_classification) and produces
Recommendation rows via the pure app.analytics.recommendation_engine --
this function does NOT recompute demand/coverage/trend/drift/gap
classification itself, it is a thin, traceable layer on top.

Multi-skill grouping uses real SkillRelationship rows if any exist; since no
current ingestion pipeline populates that table, grouping currently
degenerates to singletons for every skill -- documented, not a bug.
"""
import json
from datetime import datetime

from app.models.skills import SkillRelationship
from app.models.analysis import AnalysisRun, SkillGap, Recommendation
from app.models.data_source import DataQualityMetric
from app.analytics.recommendation_engine import generate_recommendation, group_related_skills
from app.analytics.data_quality import compute_recommendation_quality_metrics, metrics_to_rows
from app.pipelines.preprocessing.artifact_writer import write_jsonl_records
from app.analytics.run_gap_classification import _courses_containing_skill, _find_latest_run_id


def run_recommendation_generation(session, gap_classification_run_id=None):
    """
    If gap_classification_run_id is not given, the latest successful
    "skill_gap_classification" run is used (via select_latest_successful_run,
    reused through app.analytics.run_gap_classification._find_latest_run_id
    rather than re-implemented).
    """
    run = AnalysisRun(
        run_type="analysis", dataset_name="curriculum_recommendations", status="running",
        started_at=datetime.utcnow(), pipeline_version="0.1.0",
    )
    session.add(run)
    session.flush()

    try:
        gap_classification_run_id = gap_classification_run_id or _find_latest_run_id(
            session, "skill_gap_classification", population_scope="global"
        )
        if gap_classification_run_id is None:
            run.status = "succeeded"
            run.records_processed = 0
            run.finished_at = datetime.utcnow()
            session.commit()
            return {
                "analysis_run_id": run.id,
                "recommendations_created": 0,
                "note": "No successful global-scoped skill_gap_classification run exists yet.",
            }

        gap_run = session.query(AnalysisRun).filter(AnalysisRun.id == gap_classification_run_id).one()
        run.population_scope = gap_run.population_scope
        # ^ Transitively inherits the gap-classification run's scope, rather
        #   than being left NULL -- a recommendation set is only ever as
        #   scope-safe as the gap evidence it was built from (Phase 4/5
        #   hardening: never let a result silently outlive/outgrow the
        #   population it was actually computed for).

        gap_rows = session.query(SkillGap).filter(SkillGap.analysis_run_id == gap_classification_run_id).all()

        relationship_rows = session.query(SkillRelationship).all()
        relationship_lookup = {}
        for rel in relationship_rows:
            relationship_lookup.setdefault(rel.source_skill_id, set()).add(rel.target_skill_id)
            relationship_lookup.setdefault(rel.target_skill_id, set()).add(rel.source_skill_id)

        missing_skill_ids = {g.skill_id for g in gap_rows if g.classification == "MISSING"}
        groups = group_related_skills(missing_skill_ids, relationship_lookup) if missing_skill_ids else []
        group_of_skill = {}
        for group in groups:
            if len(group) > 1:
                for sid in group:
                    group_of_skill[sid] = group - {sid}

        recommendation_dicts = []

        for g in gap_rows:
            gap_record = {
                "classification": g.classification,
                "evidence_state": g.evidence_state,
                "industry_demand_percentage": g.industry_demand,
                "curriculum_coverage_percentage": g.curriculum_coverage,
                "high_demand": bool(g.high_demand) if g.high_demand is not None else None,
                "demand_trend_signal": _trend_label_to_signal(g.trend_label),
                "trend_label": g.trend_label,
                "drift_status": g.drift_status,
            }
            courses_with_evidence = _courses_containing_skill(session, g.skill_id)
            related = group_of_skill.get(g.skill_id)

            result = generate_recommendation(gap_record, courses_with_evidence=courses_with_evidence, related_skill_ids=related)
            result.update(
                {
                    "skill_id": g.skill_id,
                    "source_demand_run_id": g.source_demand_run_id,
                    "source_coverage_run_id": g.source_coverage_run_id,
                }
            )
            recommendation_dicts.append(result)

            primary_course_id = None
            if courses_with_evidence:
                from app.models.curriculum import Course

                first_course = session.query(Course).filter(Course.course_code == courses_with_evidence[0]).first()
                primary_course_id = first_course.id if first_course else None

            session.add(
                Recommendation(
                    analysis_run_id=run.id,
                    skill_id=g.skill_id,
                    course_id=primary_course_id,
                    current_coverage=g.curriculum_coverage,
                    industry_demand=g.industry_demand,
                    trend_label=g.trend_label,
                    drift_status=g.drift_status,
                    recommendation_state=result["recommendation_state"],
                    action_type=result["action_type"],
                    target_level=result["target_level"],
                    target_course_codes_json=json.dumps(result["target_course_codes"]),
                    grouped_skill_ids_json=json.dumps(result["grouped_skill_ids"]),
                    evidence_json=json.dumps(gap_record),
                    reasons_json=json.dumps(result["reasons"]),
                    source_gap_classification_run_id=gap_classification_run_id,
                )
            )

        quality_metrics = compute_recommendation_quality_metrics(recommendation_dicts)
        for row_dict in metrics_to_rows(quality_metrics, run.id, None):
            session.add(DataQualityMetric(**row_dict))

        write_jsonl_records("gold", "curriculum_recommendations", run.id, recommendation_dicts)

        run.status = "succeeded"
        run.records_processed = len(recommendation_dicts)
        run.record_counts_json = json.dumps({"gap_classification_run_id": gap_classification_run_id})
        run.finished_at = datetime.utcnow()
        session.commit()

        return {
            "analysis_run_id": run.id,
            "recommendations_created": len(recommendation_dicts),
            "source_gap_classification_run_id": gap_classification_run_id,
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


def _trend_label_to_signal(trend_label):
    return {
        "TRENDING_UP": "INCREASING_DEMAND",
        "TRENDING_DOWN": "DECREASING_DEMAND",
        "STABLE": "STABLE_DEMAND",
        "INSUFFICIENT_DATA": "INSUFFICIENT_TREND_DATA",
    }.get(trend_label, "INSUFFICIENT_TREND_DATA")
