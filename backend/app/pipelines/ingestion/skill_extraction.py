"""
Skill-mention extraction orchestration (DB-dependent).

Wires the pure logic in app.pipelines.preprocessing.skill_extraction to the
real ingested data: JobPosting (structured skills_raw tag field + free-text
clean_description) and curriculum Course/CurriculumTopic/CourseLearningOutcome
text. Persists results as ExtractedSkill rows (the SKILL MENTION entity --
see that model's docstring for why this is deliberately not the same concept
as Skill).

There is no RAW file to copy here (unlike esco/onet/job_postings/curriculum
ingestion) -- the "raw" input to this stage is already-ingested database rows,
not an external file. BRONZE = every candidate mention found, before
deduplication/idempotency filtering. SILVER = the final, deduplicated,
mapped-or-honestly-unmapped mention set that actually gets persisted.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.jobs import JobPosting, ExtractedSkill
from app.models.curriculum import Course, CurriculumTopic, CourseLearningOutcome
from app.models.skills import Skill, SkillAlias
from app.models.analysis import AnalysisRun
from app.models.data_source import DataQualityMetric
from app.pipelines.preprocessing.skill_extraction import (
    build_vocabulary_index,
    extract_mentions_from_text,
    extract_mentions_from_tag_field,
    deduplicate_mentions,
    partition_new_mentions,
)
from app.pipelines.preprocessing.artifact_writer import write_jsonl_records
from app.analytics.data_quality import compute_skill_mention_quality_metrics, metrics_to_rows


def build_vocabulary_index_from_db(session: Session) -> list:
    """Queries Skill + SkillAlias and converts to the plain-dict shape the
    pure build_vocabulary_index() expects -- keeps that function DB-free."""
    skill_rows = [
        {"id": s.id, "external_id": s.external_id, "preferred_label": s.preferred_label}
        for s in session.query(Skill).all()
    ]
    alias_rows = [
        {"skill_id": a.skill_id, "external_id": None, "alias_label": a.alias_label}
        for a in session.query(SkillAlias).all()
    ]
    return build_vocabulary_index(skill_rows, alias_rows)


def _persist_mentions(
    session: Session,
    run_id: int,
    source_type: str,
    source_id: int,
    mentions: list,
    existing_hashes: set,
    fk_field: str,
    context_snippet,
) -> tuple:
    """
    Returns (inserted_count, skipped_already_ingested_count). The idempotency
    decision itself lives in the pure partition_new_mentions() -- this
    function's only DB-specific job is turning "new_with_hash" into actual
    ExtractedSkill rows and updating existing_hashes so later calls in the
    same run (or a later run) see them too.
    """
    new_with_hash, skipped = partition_new_mentions(mentions, source_type, source_id, existing_hashes)
    for m, h in new_with_hash:
        existing_hashes.add(h)
        row = ExtractedSkill(
            original_text_span=m.original_text,
            normalized_text_span=m.normalized_text,
            normalized_skill_id=m.skill_id,
            mapping_status=m.mapping_status,
            extraction_method=m.method,
            confidence=m.confidence,
            context_snippet=context_snippet,
            mention_hash=h,
            analysis_run_id=run_id,
        )
        setattr(row, fk_field, source_id)
        session.add(row)
    return len(new_with_hash), len(skipped)


def extract_skills_from_job_postings(session: Session, limit: int | None = None) -> dict:
    """
    Extracts mentions from JobPosting.skills_raw (structured tag field, method
    "structured_tag") and JobPosting.clean_description (free-text scan).
    Skips postings already flagged as duplicates (is_duplicate=1) -- no point
    extracting skills from a posting we've already identified as a repost of
    another one already processed.
    """
    run = AnalysisRun(
        run_type="extraction", dataset_name="skill_mentions_jobs", status="running",
        started_at=datetime.utcnow(), pipeline_version="0.1.0",
    )
    session.add(run)
    session.flush()

    try:
        vocabulary = build_vocabulary_index_from_db(session)
        existing_hashes = {
            h for (h,) in session.query(ExtractedSkill.mention_hash)
            .filter(ExtractedSkill.mention_hash.isnot(None)).all()
        }

        query = session.query(JobPosting).filter(JobPosting.is_duplicate == 0)
        if limit:
            query = query.limit(limit)
        postings = query.all()

        bronze_records, silver_records = [], []
        total_mentions_found = 0
        total_inserted = 0
        total_already_ingested = 0
        postings_processed = 0
        postings_with_no_mentions = 0

        for posting in postings:
            postings_processed += 1
            candidate_mentions = []
            if posting.skills_raw:
                candidate_mentions.extend(extract_mentions_from_tag_field(posting.skills_raw, vocabulary))
            if posting.clean_description:
                candidate_mentions.extend(extract_mentions_from_text(posting.clean_description, vocabulary))

            bronze_records.extend(
                {
                    "job_posting_id": posting.id,
                    "original_text": m.original_text,
                    "normalized_text": m.normalized_text,
                    "method": m.method,
                    "mapping_status": m.mapping_status,
                }
                for m in candidate_mentions
            )
            total_mentions_found += len(candidate_mentions)

            deduped = deduplicate_mentions(candidate_mentions)
            if not deduped:
                postings_with_no_mentions += 1

            inserted, skipped = _persist_mentions(
                session, run.id, "job_posting", posting.id, deduped, existing_hashes,
                fk_field="job_posting_id",
                context_snippet=(posting.clean_description or "")[:200],
            )
            total_inserted += inserted
            total_already_ingested += skipped
            silver_records.extend(
                {
                    "job_posting_id": posting.id,
                    "normalized_text": m.normalized_text,
                    "method": m.method,
                    "mapping_status": m.mapping_status,
                    "skill_id": m.skill_id,
                }
                for m in deduped
            )

        write_jsonl_records("bronze", "skill_mentions_jobs", run.id, bronze_records)
        write_jsonl_records("silver", "skill_mentions_jobs", run.id, silver_records)

        quality_metrics = compute_skill_mention_quality_metrics(
            source_records_processed=postings_processed,
            total_mentions=total_mentions_found,
            persisted_mentions=silver_records,
            already_ingested_count=total_already_ingested,
            records_with_no_mentions=postings_with_no_mentions,
        )
        for row_dict in metrics_to_rows(quality_metrics, run.id, None):
            session.add(DataQualityMetric(**row_dict))

        run.status = "succeeded"
        run.records_processed = total_inserted
        run.records_failed = 0
        run.finished_at = datetime.utcnow()
        session.commit()

        return {
            "analysis_run_id": run.id,
            "postings_processed": postings_processed,
            "mentions_found": total_mentions_found,
            "mentions_inserted": total_inserted,
            "already_ingested_skipped": total_already_ingested,
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


def extract_skills_from_curriculum(session: Session, limit: int | None = None) -> dict:
    """
    Extracts mentions from Course.name (title-level), CurriculumTopic.topic_text
    (syllabus topics), and CourseLearningOutcome.outcome_text (outcomes) --
    the three text sources this project's curriculum structuring actually
    produces (see docs/testing.md for what curriculum ingestion does and does
    not extract).
    """
    run = AnalysisRun(
        run_type="extraction", dataset_name="skill_mentions_curriculum", status="running",
        started_at=datetime.utcnow(), pipeline_version="0.1.0",
    )
    session.add(run)
    session.flush()

    try:
        vocabulary = build_vocabulary_index_from_db(session)
        existing_hashes = {
            h for (h,) in session.query(ExtractedSkill.mention_hash)
            .filter(ExtractedSkill.mention_hash.isnot(None)).all()
        }

        bronze_records, silver_records = [], []
        total_mentions_found = 0
        total_inserted = 0
        total_already_ingested = 0
        source_records_processed = 0

        course_q = session.query(Course)
        topic_q = session.query(CurriculumTopic)
        outcome_q = session.query(CourseLearningOutcome)
        if limit:
            course_q, topic_q, outcome_q = course_q.limit(limit), topic_q.limit(limit), outcome_q.limit(limit)

        sources = [
            ("course", course_q.all(), lambda c: c.name),
            ("curriculum_topic", topic_q.all(), lambda t: t.topic_text),
            ("course_learning_outcome", outcome_q.all(), lambda o: o.outcome_text),
        ]
        fk_field_map = {
            "course": "course_id",
            "curriculum_topic": "curriculum_topic_id",
            "course_learning_outcome": "course_learning_outcome_id",
        }

        for source_type, rows, text_getter in sources:
            for row in rows:
                source_records_processed += 1
                text = text_getter(row)
                mentions = extract_mentions_from_text(text, vocabulary) if text else []
                bronze_records.extend(
                    {
                        "source_type": source_type,
                        "source_id": row.id,
                        "original_text": m.original_text,
                        "normalized_text": m.normalized_text,
                        "method": m.method,
                        "mapping_status": m.mapping_status,
                    }
                    for m in mentions
                )
                total_mentions_found += len(mentions)
                deduped = deduplicate_mentions(mentions)

                inserted, skipped = _persist_mentions(
                    session, run.id, source_type, row.id, deduped, existing_hashes,
                    fk_field=fk_field_map[source_type],
                    context_snippet=(text or "")[:200],
                )
                total_inserted += inserted
                total_already_ingested += skipped
                silver_records.extend(
                    {
                        "source_type": source_type,
                        "source_id": row.id,
                        "normalized_text": m.normalized_text,
                        "method": m.method,
                        "mapping_status": m.mapping_status,
                        "skill_id": m.skill_id,
                    }
                    for m in deduped
                )

        write_jsonl_records("bronze", "skill_mentions_curriculum", run.id, bronze_records)
        write_jsonl_records("silver", "skill_mentions_curriculum", run.id, silver_records)

        quality_metrics = compute_skill_mention_quality_metrics(
            source_records_processed=source_records_processed,
            total_mentions=total_mentions_found,
            persisted_mentions=silver_records,
            already_ingested_count=total_already_ingested,
            records_with_no_mentions=None,
        )
        for row_dict in metrics_to_rows(quality_metrics, run.id, None):
            session.add(DataQualityMetric(**row_dict))

        run.status = "succeeded"
        run.records_processed = total_inserted
        run.records_failed = 0
        run.finished_at = datetime.utcnow()
        session.commit()

        return {
            "analysis_run_id": run.id,
            "source_records_processed": source_records_processed,
            "mentions_found": total_mentions_found,
            "mentions_inserted": total_inserted,
            "already_ingested_skipped": total_already_ingested,
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
