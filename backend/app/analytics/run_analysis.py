"""
GOLD-layer analysis orchestration (DB-dependent). Wires the pure logic in
industry_demand.py / curriculum_coverage.py / skill_set_alignment.py /
tfidf_alignment.py to real ExtractedSkill evidence, and populates
SkillDemand / CurriculumSkillCoverage / SkillAlignment / AlignmentResult.

Every function here creates its own AnalysisRun so "when was this calculated,
against which population, with which config" is always answerable (spec
Section 10).
"""
from datetime import datetime
import json

from sqlalchemy.orm import Session

from app.models.jobs import JobPosting, ExtractedSkill, SkillDemand, JobDiscipline
from app.models.curriculum import Course, CurriculumTopic, CourseLearningOutcome, Module
from app.models.analysis import AnalysisRun, AlignmentResult, CurriculumSkillCoverage, SkillAlignment
from app.models.data_source import DataQualityMetric
from app.analytics.industry_demand import compute_skill_demand
from app.analytics.curriculum_coverage import compute_curriculum_coverage
from app.analytics.skill_set_alignment import compute_skill_set_alignment, classify_demand_coverage, resolve_evidence_value
from app.analytics.tfidf_alignment import compute_tfidf_alignment
from app.pipelines.preprocessing.artifact_writer import write_jsonl_records
from app.analytics.data_quality import (
    compute_industry_analysis_quality_metrics,
    compute_curriculum_analysis_quality_metrics,
    compute_cross_coverage_quality_metrics,
    metrics_to_rows,
)
from app.core.config import get_settings


def run_industry_demand_analysis(session: Session, discipline_id: int | None = None) -> dict:
    """
    discipline_id=None (default): eligible population = all non-duplicate
    job postings currently in the DB -- UNCHANGED behavior from before
    discipline-scoping was added.

    discipline_id=<id>: eligible population = only postings linked to that
    Discipline via JobDiscipline (spec Phase 5). Since JobDiscipline is not
    populated by any current ingestion pipeline (see that model's
    docstring -- no fabricated classifications), passing a real
    discipline_id today will correctly yield zero eligible postings rather
    than silently falling back to the global population; this is honest,
    not a bug. The formula and the pure compute_skill_demand() function are
    UNCHANGED regardless of scope.

    Uses only MAPPED ExtractedSkill rows (job_posting_id is not null,
    mapping_status="mapped") -- unmapped mentions carry no canonical skill to
    attribute demand to.
    """
    run = AnalysisRun(
        run_type="analysis", dataset_name="industry_demand", status="running",
        started_at=datetime.utcnow(), pipeline_version="0.1.0",
        population_scope="global" if discipline_id is None else f"discipline:{discipline_id}",
    )
    session.add(run)
    session.flush()

    try:
        posting_query = session.query(JobPosting.id).filter(JobPosting.is_duplicate == 0)
        if discipline_id is not None:
            posting_query = posting_query.join(
                JobDiscipline, JobDiscipline.job_posting_id == JobPosting.id
            ).filter(JobDiscipline.discipline_id == discipline_id)
        eligible_posting_ids = {pid for (pid,) in posting_query.all()}

        mention_rows = (
            session.query(ExtractedSkill.job_posting_id, ExtractedSkill.normalized_skill_id)
            .filter(ExtractedSkill.job_posting_id.isnot(None), ExtractedSkill.mapping_status == "mapped")
            .all()
        )
        mentions = [{"job_posting_id": pid, "normalized_skill_id": sid} for pid, sid in mention_rows]

        demand = compute_skill_demand(mentions, eligible_posting_ids)

        for skill_id, stats in demand.items():
            session.add(
                SkillDemand(
                    skill_id=skill_id,
                    time_bucket="overall",  # no time-segmentation this phase -- see spec Section 3
                    posting_count=stats["posting_count"],
                    total_relevant_postings=stats["total_relevant_postings"],
                    demand_percentage=stats["demand_percentage"],
                    analysis_run_id=run.id,
                )
            )

        postings_with_skills = {m["job_posting_id"] for m in mentions}
        all_mention_rows = (
            session.query(ExtractedSkill.mapping_status)
            .filter(ExtractedSkill.job_posting_id.isnot(None))
            .all()
        )
        mapped_count = sum(1 for (s,) in all_mention_rows if s == "mapped")
        unmapped_count = sum(1 for (s,) in all_mention_rows if s == "unmapped")

        quality_metrics = compute_industry_analysis_quality_metrics(
            eligible_job_postings=len(eligible_posting_ids),
            postings_with_extracted_skills=len(postings_with_skills & eligible_posting_ids),
            unique_canonical_skills=len(demand),
            mapped_mentions_count=mapped_count,
            unmapped_mentions_count=unmapped_count,
        )
        for row_dict in metrics_to_rows(quality_metrics, run.id, None):
            session.add(DataQualityMetric(**row_dict))

        write_jsonl_records(
            "gold", "industry_demand", run.id,
            [{"skill_id": sid, **stats} for sid, stats in demand.items()],
        )

        run.status = "succeeded"
        run.records_processed = len(demand)
        run.record_counts_json = json.dumps({"eligible_job_postings": len(eligible_posting_ids)})
        run.finished_at = datetime.utcnow()
        session.commit()

        return {
            "analysis_run_id": run.id, "skills_with_demand": len(demand),
            "discipline_id": discipline_id, "quality_metrics": quality_metrics,
        }
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_log = str(exc)
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        raise


def _resolve_course_id_for_mention(m: ExtractedSkill, topic_to_course: dict, outcome_to_course: dict) -> tuple:
    """Returns (course_id, mention_source, source_record_id) for one ExtractedSkill row."""
    if m.course_id is not None:
        return m.course_id, "course_title", None
    if m.curriculum_topic_id is not None:
        return topic_to_course.get(m.curriculum_topic_id), "curriculum_topic", m.curriculum_topic_id
    if m.course_learning_outcome_id is not None:
        return outcome_to_course.get(m.course_learning_outcome_id), "course_learning_outcome", m.course_learning_outcome_id
    return None, None, None


def run_curriculum_coverage_analysis(session: Session, level: str = "overall", programme_id: int | None = None) -> dict:
    """
    level="overall", programme_id=None (default): eligible population =
    every Course currently in the DB -- UNCHANGED behavior from before
    programme-scoping was added, so existing callers/tests are unaffected.

    programme_id=<id>: eligible population = only Courses belonging to that
    Programme (spec Phase 5 -- "the eligible population must be scoped to
    the relevant programme"). The underlying formula and the pure
    compute_curriculum_coverage() function are UNCHANGED; only which
    Course rows are queried into eligible_course_ids differs. level and
    entity_id are set to make the scope explicit and queryable
    (CurriculumSkillCoverage.entity_id was added for exactly this purpose
    but never wired up before this phase).
    """
    run = AnalysisRun(
        run_type="analysis", dataset_name="curriculum_coverage", status="running",
        started_at=datetime.utcnow(), pipeline_version="0.1.0",
        population_scope="global" if programme_id is None else f"programme:{programme_id}",
    )
    session.add(run)
    session.flush()

    try:
        course_query = session.query(Course.id)
        if programme_id is not None:
            course_query = course_query.filter(Course.programme_id == programme_id)
        eligible_course_ids = {cid for (cid,) in course_query.all()}

        effective_level = "programme" if programme_id is not None else level
        effective_entity_id = programme_id

        topic_to_course = {}
        for topic_id, module_id in session.query(CurriculumTopic.id, CurriculumTopic.module_id).all():
            module = session.query(Module).filter(Module.id == module_id).one_or_none()
            if module:
                topic_to_course[topic_id] = module.course_id

        outcome_to_course = {
            oid: cid for oid, cid in session.query(CourseLearningOutcome.id, CourseLearningOutcome.course_id).all()
        }

        mention_rows = (
            session.query(ExtractedSkill)
            .filter(
                ExtractedSkill.mapping_status == "mapped",
            )
            .filter(
                (ExtractedSkill.course_id.isnot(None))
                | (ExtractedSkill.curriculum_topic_id.isnot(None))
                | (ExtractedSkill.course_learning_outcome_id.isnot(None))
            )
            .all()
        )

        mentions = []
        for m in mention_rows:
            course_id, source, record_id = _resolve_course_id_for_mention(m, topic_to_course, outcome_to_course)
            if course_id is not None:
                mentions.append(
                    {
                        "course_id": course_id,
                        "normalized_skill_id": m.normalized_skill_id,
                        "mention_source": source,
                        "source_record_id": record_id,
                    }
                )

        coverage = compute_curriculum_coverage(mentions, eligible_course_ids)

        for skill_id, stats in coverage.items():
            session.add(
                CurriculumSkillCoverage(
                    analysis_run_id=run.id,
                    skill_id=skill_id,
                    level=effective_level,
                    entity_id=effective_entity_id,
                    courses_with_skill=stats["courses_with_skill"],
                    eligible_courses=stats["eligible_courses"],
                    coverage_percentage=stats["coverage_percentage"],
                    topics_with_skill=stats["topics_with_skill"],
                    outcomes_with_skill=stats["outcomes_with_skill"],
                )
            )

        courses_with_skills = {m["course_id"] for m in mentions}
        quality_metrics = compute_curriculum_analysis_quality_metrics(
            eligible_courses=len(eligible_course_ids),
            courses_with_extracted_skills=len(courses_with_skills & eligible_course_ids),
            unique_canonical_skills=len(coverage),
        )
        for row_dict in metrics_to_rows(quality_metrics, run.id, None):
            session.add(DataQualityMetric(**row_dict))

        write_jsonl_records(
            "gold", "curriculum_coverage", run.id,
            [{"skill_id": sid, "level": effective_level, "entity_id": effective_entity_id, **stats} for sid, stats in coverage.items()],
        )

        run.status = "succeeded"
        run.records_processed = len(coverage)
        run.record_counts_json = json.dumps({"eligible_courses": len(eligible_course_ids)})
        run.finished_at = datetime.utcnow()
        session.commit()

        return {
            "analysis_run_id": run.id, "skills_with_coverage": len(coverage),
            "programme_id": programme_id, "quality_metrics": quality_metrics,
        }
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_log = str(exc)
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        raise


def run_skill_alignment_analysis(
    session: Session,
    demand_run_id: int,
    coverage_run_id: int,
    high_demand_threshold: float | None = None,
    high_coverage_threshold: float | None = None,
) -> dict:
    """
    Combines the results of a specific industry-demand run and a specific
    curriculum-coverage run into the per-skill SkillAlignment comparison
    (spec Section 6) plus the set-based Jaccard alignment (Section 8).
    Thresholds default to app.core.config but can be overridden per call --
    always recorded on the row so results stay interpretable if the config
    changes later.
    """
    settings = get_settings()
    demand_threshold = high_demand_threshold if high_demand_threshold is not None else settings.high_demand_threshold
    coverage_threshold = high_coverage_threshold if high_coverage_threshold is not None else settings.high_coverage_threshold

    run = AnalysisRun(
        run_type="analysis", dataset_name="skill_alignment", status="running",
        started_at=datetime.utcnow(), pipeline_version="0.1.0", population_scope="global",
    )
    session.add(run)
    session.flush()

    try:
        demand_run = session.query(AnalysisRun).filter(AnalysisRun.id == demand_run_id).one()
        coverage_run = session.query(AnalysisRun).filter(AnalysisRun.id == coverage_run_id).one()

        # Population sizes recorded by the runs being combined -- this is what
        # lets us tell "this skill had zero measured demand within a real
        # population" apart from "there was no industry population at all
        # for this run" (see classify_demand_coverage's docstring).
        demand_run_counts = json.loads(demand_run.record_counts_json) if demand_run.record_counts_json else {}
        coverage_run_counts = json.loads(coverage_run.record_counts_json) if coverage_run.record_counts_json else {}
        eligible_job_postings = demand_run_counts.get("eligible_job_postings", 0)
        eligible_courses = coverage_run_counts.get("eligible_courses", 0)

        demand_rows = session.query(SkillDemand).filter(SkillDemand.analysis_run_id == demand_run_id).all()
        coverage_rows = (
            session.query(CurriculumSkillCoverage)
            .filter(CurriculumSkillCoverage.analysis_run_id == coverage_run_id)
            .all()
        )

        demand_by_skill = {d.skill_id: d for d in demand_rows}
        coverage_by_skill = {c.skill_id: c for c in coverage_rows}
        all_skill_ids = set(demand_by_skill) | set(coverage_by_skill)

        # Rank by demand / coverage (1 = highest); a skill absent from one side has no rank on that side.
        demand_ranked = sorted(demand_by_skill.items(), key=lambda kv: kv[1].demand_percentage or 0, reverse=True)
        demand_rank = {skill_id: i + 1 for i, (skill_id, _) in enumerate(demand_ranked)}
        coverage_ranked = sorted(coverage_by_skill.items(), key=lambda kv: kv[1].coverage_percentage or 0, reverse=True)
        coverage_rank = {skill_id: i + 1 for i, (skill_id, _) in enumerate(coverage_ranked)}

        thresholds_json = json.dumps(
            {"high_demand_threshold": demand_threshold, "high_coverage_threshold": coverage_threshold}
        )

        for skill_id in all_skill_ids:
            d = demand_by_skill.get(skill_id)
            c = coverage_by_skill.get(skill_id)

            # Resolve the TRUE value for classification/storage using the
            # pure, unit-tested resolve_evidence_value() -- see
            # app.analytics.skill_set_alignment for the None-vs-zero rules.
            industry_demand_pct = resolve_evidence_value(
                d.demand_percentage if d else None, d is not None, eligible_job_postings
            )
            industry_posting_count = (
                d.posting_count if d is not None else (0 if eligible_job_postings > 0 else None)
            )

            curriculum_coverage_pct = resolve_evidence_value(
                c.coverage_percentage if c else None, c is not None, eligible_courses
            )
            curriculum_course_count = (
                c.courses_with_skill if c is not None else (0 if eligible_courses > 0 else None)
            )

            classification = classify_demand_coverage(
                industry_demand_pct, curriculum_coverage_pct, demand_threshold, coverage_threshold
            )

            session.add(
                SkillAlignment(
                    analysis_run_id=run.id,
                    skill_id=skill_id,
                    industry_posting_count=industry_posting_count,
                    industry_demand_percentage=industry_demand_pct,
                    curriculum_course_count=curriculum_course_count,
                    curriculum_coverage_percentage=curriculum_coverage_pct,
                    demand_rank=demand_rank.get(skill_id),
                    coverage_rank=coverage_rank.get(skill_id),
                    classification=classification,
                    thresholds_used_json=thresholds_json,
                )
            )

        # Set-based Jaccard alignment (Section 8), stored at "overall" level.
        # entity_id is NULL here -- this result isn't scoped to one course/programme.
        set_alignment = compute_skill_set_alignment(set(demand_by_skill), set(coverage_by_skill))
        session.add(
            AlignmentResult(
                analysis_run_id=run.id,
                level="overall",
                entity_id=None,
                skill_set_alignment=set_alignment["jaccard_alignment_score"],
                source_population_size=set_alignment["industry_skill_count"],
                target_population_size=set_alignment["curriculum_skill_count"],
                method_config_json=json.dumps({"method": set_alignment["method"]}),
            )
        )

        cross_metrics = compute_cross_coverage_quality_metrics(set(demand_by_skill), set(coverage_by_skill))
        for row_dict in metrics_to_rows(cross_metrics, run.id, None):
            session.add(DataQualityMetric(**row_dict))

        write_jsonl_records(
            "gold", "skill_alignment", run.id,
            [
                {
                    "skill_id": sid,
                    "industry_demand_percentage": (
                        demand_by_skill[sid].demand_percentage if sid in demand_by_skill
                        else (0.0 if eligible_job_postings > 0 else None)
                    ),
                    "curriculum_coverage_percentage": (
                        coverage_by_skill[sid].coverage_percentage if sid in coverage_by_skill
                        else (0.0 if eligible_courses > 0 else None)
                    ),
                    "demand_rank": demand_rank.get(sid),
                    "coverage_rank": coverage_rank.get(sid),
                }
                for sid in all_skill_ids
            ],
        )

        run.status = "succeeded"
        run.records_processed = len(all_skill_ids)
        run.finished_at = datetime.utcnow()
        session.commit()

        return {
            "analysis_run_id": run.id,
            "skills_compared": len(all_skill_ids),
            "skill_set_alignment": set_alignment,
            "thresholds_used": {"high_demand_threshold": demand_threshold, "high_coverage_threshold": coverage_threshold},
        }
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_log = str(exc)
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        raise


def run_course_tfidf_alignment(session: Session) -> dict:
    """
    Course-level TF-IDF text_alignment_score against an aggregate industry
    corpus (all non-duplicate job postings' clean_description, concatenated).
    A course's "text" is its topics + outcomes concatenated -- reuses
    already-ingested text, no re-preprocessing.
    """
    run = AnalysisRun(
        run_type="analysis", dataset_name="tfidf_alignment", status="running",
        started_at=datetime.utcnow(), pipeline_version="0.1.0", population_scope="global",
    )
    session.add(run)
    session.flush()

    try:
        postings = session.query(JobPosting).filter(JobPosting.is_duplicate == 0).all()
        eligible_postings_count = len(postings)  # broader eligible population (Section 4 fix)
        contributing_postings = [p for p in postings if p.clean_description]
        reference_doc = " ".join(p.clean_description for p in contributing_postings)

        courses = session.query(Course).all()
        entity_docs = {}
        for course in courses:
            modules = session.query(Module).filter(Module.course_id == course.id).all()
            module_ids = [m.id for m in modules]
            topics = (
                session.query(CurriculumTopic).filter(CurriculumTopic.module_id.in_(module_ids)).all()
                if module_ids
                else []
            )
            outcomes = session.query(CourseLearningOutcome).filter(CourseLearningOutcome.course_id == course.id).all()
            parts = [course.name or ""] + [t.topic_text for t in topics] + [o.outcome_text for o in outcomes]
            entity_docs[course.id] = " ".join(p for p in parts if p)

        result = compute_tfidf_alignment(entity_docs, reference_doc)

        write_jsonl_records(
            "gold", "tfidf_alignment", run.id,
            [{"course_id": cid, **stats} for cid, stats in result["entities"].items()],
        )

        for course_id, stats in result["entities"].items():
            session.add(
                AlignmentResult(
                    analysis_run_id=run.id,
                    level="course",
                    entity_id=course_id,
                    tfidf_alignment=stats["text_alignment_score"],
                    vocabulary_size=result["vocabulary_size"],
                    reference_doc_length=result["reference_doc_length"],
                    source_population_size=len(contributing_postings),  # postings that ACTUALLY contributed text to the corpus
                    target_population_size=len(result["entities"]),  # courses that actually contributed text (non-skipped)
                    eligible_source_population_size=eligible_postings_count,  # broader eligible population, incl. postings with no usable text
                    method_config_json=json.dumps(result["config"]),
                )
            )

        run.status = "succeeded"
        run.records_processed = len(result["entities"])
        run.finished_at = datetime.utcnow()
        session.commit()

        return {
            "analysis_run_id": run.id,
            "courses_scored": len(result["entities"]),
            "courses_skipped": len(result["skipped_entity_ids"]),
            "vocabulary_size": result["vocabulary_size"],
        }
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_log = str(exc)
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        raise
