"""
Core Discipline Knowledge Layer import orchestration (DB-dependent).

Format-agnostic by design: `ingest_core_knowledge_records()` takes
already-parsed plain-dict records, so CSV/JSON today and PDF/JSONL/ODS/XML
later (spec Phase 8) all funnel through ONE ingestion function -- no
per-branch, per-university, or per-format-specific business logic lives
here. Adding a new format means adding a new loader that produces the same
record shape, not touching this function.

Idempotent: get-or-create at every level (Discipline, CoreKnowledgeDomain,
CoreTopic, CoreSubtopic) via the UniqueConstraints already defined on those
models -- re-running the same import file twice does not duplicate rows.
"""
import json
from datetime import datetime

from app.models.curriculum import Discipline
from app.models.core_knowledge import CoreKnowledgeDomain, CoreTopic, CoreSubtopic
from app.models.analysis import AnalysisRun
from app.models.data_source import DataQualityMetric
from app.pipelines.ingestion.common import file_hash, get_or_create_data_source
from app.pipelines.preprocessing.artifact_writer import write_raw_copy, write_jsonl_records
from app.pipelines.preprocessing.core_knowledge_loaders import (  # noqa: F401 -- re-exported for CLI convenience
    load_records_from_csv,
    load_records_from_json,
    validate_records,
    records_fingerprint,
)
from app.analytics.data_quality import compute_core_knowledge_quality_metrics, metrics_to_rows


def _get_or_create_discipline(session, name):
    existing = session.query(Discipline).filter(Discipline.name == name).one_or_none()
    if existing:
        return existing
    disc = Discipline(name=name)
    session.add(disc)
    session.flush()
    return disc


def ingest_core_knowledge_records(
    session,
    records,
    discipline_name,
    source_name,
    source_type,
    raw_file_path=None,
    source_url=None,
    version=None,
    is_test_data=False,
):
    """
    records: [{"domain": str, "topic": str, "subtopic": str|None, "description": str|None}, ...]
    source_type: e.g. "academic_framework" | "university_curriculum" |
        "professional_body" -- free-text, reusing DataSource.source_type.
    raw_file_path: if given, byte-for-byte preserved as the RAW artifact.
    """
    run = AnalysisRun(
        run_type="ingestion", dataset_name="core_knowledge", status="running",
        started_at=datetime.utcnow(), pipeline_version="0.1.0",
    )
    session.add(run)
    session.flush()

    try:
        if raw_file_path is not None:
            write_raw_copy("core_knowledge", run.id, raw_file_path)
            source, _reused = get_or_create_data_source(
                session, source_name=source_name, source_type=source_type,
                file_hash_value=file_hash(raw_file_path), source_url=source_url, version=version,
                is_test_data=is_test_data,
            )
        else:
            # No raw file: fingerprint the record content so re-running the
            # same records reuses the same DataSource (idempotent provenance).
            source, _reused = get_or_create_data_source(
                session, source_name=source_name, source_type=source_type,
                file_hash_value=records_fingerprint(records), source_url=source_url, version=version,
                is_test_data=is_test_data,
            )
        run.source_id = source.id

        discipline = _get_or_create_discipline(session, discipline_name)

        valid_records, invalid_records = validate_records(records)

        write_jsonl_records(
            "bronze", "core_knowledge", run.id,
            [{**r, "valid": True} for r in valid_records] + [{**r, "valid": False} for r in invalid_records],
        )

        domain_cache, topic_cache = {}, {}
        created_domains, created_topics, created_subtopics = [], [], []

        for r in valid_records:
            domain_key = r["domain"]
            if domain_key not in domain_cache:
                existing_domain = (
                    session.query(CoreKnowledgeDomain)
                    .filter(CoreKnowledgeDomain.discipline_id == discipline.id, CoreKnowledgeDomain.name == domain_key)
                    .one_or_none()
                )
                if existing_domain is None:
                    existing_domain = CoreKnowledgeDomain(discipline_id=discipline.id, name=domain_key, source_id=source.id)
                    session.add(existing_domain)
                    session.flush()
                    created_domains.append(existing_domain)
                domain_cache[domain_key] = existing_domain
            domain = domain_cache[domain_key]

            topic_key = (domain.id, r["topic"])
            if topic_key not in topic_cache:
                existing_topic = (
                    session.query(CoreTopic)
                    .filter(CoreTopic.domain_id == domain.id, CoreTopic.name == r["topic"])
                    .one_or_none()
                )
                if existing_topic is None:
                    existing_topic = CoreTopic(
                        domain_id=domain.id, name=r["topic"], description=r.get("description"), source_id=source.id,
                    )
                    session.add(existing_topic)
                    session.flush()
                    created_topics.append(existing_topic)
                topic_cache[topic_key] = existing_topic
            topic = topic_cache[topic_key]

            if r.get("subtopic"):
                existing_subtopic = (
                    session.query(CoreSubtopic)
                    .filter(CoreSubtopic.topic_id == topic.id, CoreSubtopic.name == r["subtopic"])
                    .one_or_none()
                )
                if existing_subtopic is None:
                    existing_subtopic = CoreSubtopic(topic_id=topic.id, name=r["subtopic"], source_id=source.id)
                    session.add(existing_subtopic)
                    session.flush()
                    created_subtopics.append(existing_subtopic)

        write_jsonl_records(
            "silver", "core_knowledge", run.id,
            [
                {"type": "domain", "id": d.id, "name": d.name} for d in created_domains
            ] + [
                {"type": "topic", "id": t.id, "domain_id": t.domain_id, "name": t.name} for t in created_topics
            ] + [
                {"type": "subtopic", "id": s.id, "topic_id": s.topic_id, "name": s.name} for s in created_subtopics
            ],
        )

        quality_metrics = compute_core_knowledge_quality_metrics(
            domains=[{"source_id": d.source_id, "is_active": d.is_active} for d in created_domains],
            topics=[{"source_id": t.source_id, "is_active": t.is_active} for t in created_topics],
            subtopics=[{"source_id": s.source_id, "is_active": s.is_active} for s in created_subtopics],
            skill_mappings=[],
            curriculum_mappings=[],
        )
        quality_metrics["invalid_records"] = len(invalid_records)
        quality_metrics["total_input_records"] = len(records)
        for row_dict in metrics_to_rows(quality_metrics, run.id, source.id):
            session.add(DataQualityMetric(**row_dict))

        run.status = "succeeded"
        run.records_processed = len(created_domains) + len(created_topics) + len(created_subtopics)
        run.records_failed = len(invalid_records)
        run.finished_at = datetime.utcnow()
        session.commit()

        return {
            "analysis_run_id": run.id,
            "source_id": source.id,
            "discipline_id": discipline.id,
            "is_test_data": bool(is_test_data),
            "domains_created": len(created_domains),
            "topics_created": len(created_topics),
            "subtopics_created": len(created_subtopics),
            "invalid_records": len(invalid_records),
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


def map_curriculum_topics_to_core_topics(session, programme_id, discipline_id):
    """
    Links a programme's REAL CurriculumTopic rows to the core topics of ONE
    discipline, using the pure deterministic matcher. Curriculum wording is
    never modified -- only CurriculumTopicCoreTopicMapping rows are written.

    Only MATCHED results are persisted. AMBIGUOUS and NO_MATCH results are
    counted and written to the SILVER artifact for review, never silently
    resolved or turned into a mapping. Discipline isolation is enforced by
    scope_core_topics_to_discipline (data-driven), not by name comparison.
    Idempotent: an existing (curriculum_topic_id, core_topic_id) pair is
    skipped (backed by the UniqueConstraint on the mapping table).
    """
    from app.models.curriculum import Course, Module, CurriculumTopic
    from app.models.core_knowledge import CurriculumTopicCoreTopicMapping
    from app.analytics.core_knowledge_mapping import (
        match_text_to_core_topics, scope_core_topics_to_discipline,
        MATCH_STATUS_MATCHED, MATCH_STATUS_AMBIGUOUS, MATCH_STATUS_COMPOUND,
    )

    run = AnalysisRun(
        run_type="analysis", dataset_name="curriculum_core_topic_mapping", status="running",
        started_at=datetime.utcnow(), pipeline_version="0.1.0",
        population_scope=f"programme:{programme_id}",
    )
    session.add(run)
    session.flush()

    try:
        topic_rows = (
            session.query(CoreTopic, CoreKnowledgeDomain)
            .join(CoreKnowledgeDomain, CoreTopic.domain_id == CoreKnowledgeDomain.id)
            .all()
        )
        candidates = scope_core_topics_to_discipline(
            [
                {"id": t.id, "name": t.name, "discipline_id": d.discipline_id,
                 "is_active": 1 if (t.is_active and d.is_active) else 0}
                for t, d in topic_rows
            ],
            discipline_id,
        )

        curriculum_topics = (
            session.query(CurriculumTopic)
            .join(Module, CurriculumTopic.module_id == Module.id)
            .join(Course, Module.course_id == Course.id)
            .filter(Course.programme_id == programme_id)
            .all()
        )

        existing_pairs = {
            (m.curriculum_topic_id, m.core_topic_id)
            for m in session.query(CurriculumTopicCoreTopicMapping).all()
        }

        def _add_mapping(curriculum_topic_id, core_topic_id, method, confidence):
            """Returns True if a new row was created, False if the
            (curriculum_topic_id, core_topic_id) pair already existed --
            same idempotency key the UniqueConstraint enforces at the DB
            level, checked here first so repeated runs report accurate
            already_present counts rather than relying on a caught
            constraint violation."""
            pair = (curriculum_topic_id, core_topic_id)
            if pair in existing_pairs:
                return False
            session.add(CurriculumTopicCoreTopicMapping(
                curriculum_topic_id=curriculum_topic_id, core_topic_id=core_topic_id,
                method=method, confidence=confidence, analysis_run_id=run.id,
            ))
            existing_pairs.add(pair)
            return True

        created, already_present, ambiguous, unmatched, compound, review_records = 0, 0, 0, 0, 0, []
        for ct in curriculum_topics:
            result = match_text_to_core_topics(ct.topic_text, candidates)

            if result["status"] == MATCH_STATUS_MATCHED:
                if _add_mapping(ct.id, result["core_topic_id"], result["method"], result["confidence"]):
                    created += 1
                else:
                    already_present += 1

            elif result["status"] == MATCH_STATUS_AMBIGUOUS:
                ambiguous += 1
                review_records.append({"curriculum_topic_id": ct.id, "topic_text": ct.topic_text, **result})

            elif result["status"] == MATCH_STATUS_COMPOUND:
                # A compound phrase never becomes ONE mapping to a single
                # core topic (that would fabricate an identity the phrase
                # doesn't actually have) -- one row per genuinely MATCHED
                # component, tagged so the compound origin stays traceable;
                # unmatched components are recorded in the review artifact,
                # never silently dropped.
                compound += 1
                for component in result["components"]:
                    if component["status"] == MATCH_STATUS_MATCHED:
                        method = f"{result['method']}:{component['method']}"
                        if _add_mapping(ct.id, component["core_topic_id"], method, component["confidence"]):
                            created += 1
                        else:
                            already_present += 1
                    else:
                        review_records.append({
                            "curriculum_topic_id": ct.id, "topic_text": ct.topic_text,
                            "compound_component": component["text"], **component,
                        })

            else:
                unmatched += 1
                review_records.append({"curriculum_topic_id": ct.id, "topic_text": ct.topic_text, **result})

        write_jsonl_records("silver", "curriculum_core_topic_mapping_review", run.id, review_records)

        metrics = {
            "curriculum_topics_considered": len(curriculum_topics),
            "candidate_core_topics": len(candidates),
            "mappings_created": created,
            "mappings_already_present": already_present,
            "ambiguous_matches": ambiguous,
            "compound_matches": compound,
            "unmatched_topics": unmatched,
        }
        for row_dict in metrics_to_rows(metrics, run.id, None):
            session.add(DataQualityMetric(**row_dict))

        run.status = "succeeded"
        run.records_processed = created
        run.record_counts_json = json.dumps(metrics)
        run.finished_at = datetime.utcnow()
        session.commit()
        return {"analysis_run_id": run.id, **metrics}
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_log = str(exc)
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        raise
