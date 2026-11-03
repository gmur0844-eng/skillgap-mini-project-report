"""
Core job-postings ingestion logic (DB-dependent).

Pipeline stages, in order:
  RAW (byte-for-byte file preserved to data/raw/jobs/<run_id>/)
  -> VALIDATION (app.pipelines.preprocessing.validation)
  -> IDEMPOTENCY CHECK (skip rows whose external_posting_id already exists for this source)
  -> BRONZE (validated + standardized records written to data/bronze/jobs/<run_id>/records.jsonl)
  -> PREPROCESSING / cleaning (app.pipelines.preprocessing.text_cleaning)
  -> DEDUPLICATION: within-batch near-dup (Jaccard) + cross-run exact-dup (hash lookup)
  -> SILVER (cleaned + deduplicated records written to data/silver/jobs/<run_id>/records.jsonl)
  -> DATA QUALITY METRICS (app.analytics.data_quality)
with an AnalysisRun and per-record IngestionRejection rows so every dropped
or skipped record is explainable.

IDEMPOTENCY (Phase-1 hardening item 1): re-running this function against the
same file is safe. The input file's hash is used to reuse the same DataSource
row across runs (see app.pipelines.ingestion.common.get_or_create_data_source)
so that "have I seen this external_posting_id for this source before" is a
question that can actually be answered across runs, not just within one. Rows
whose external_posting_id already exists for that source are skipped and
counted as "already_ingested" rather than re-inserted. The DB-level
UniqueConstraint on JobPosting(source_id, external_posting_id) is the backstop
in case the application-level check is ever bypassed or wrong.

CROSS-RUN DUPLICATE HANDLING (item 2): near-duplicate detection
(find_near_duplicates) is batch-local only -- see its docstring. Separately,
each new row's clean_description is hashed and checked against
JobPosting.clean_description_hash (indexed) for an EXACT match anywhere in the
table, including rows from earlier runs/sources. This is a cheap indexed
lookup, not global semantic deduplication, which is explicitly out of scope
for Phase 1.
"""
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.models.jobs import JobPosting
from app.models.analysis import AnalysisRun, IngestionRejection
from app.models.data_source import DataQualityMetric
from app.pipelines.preprocessing.text_cleaning import clean_job_description
from app.pipelines.preprocessing.deduplication import (
    find_near_duplicates,
    partition_already_ingested,
    text_hash,
)
from app.pipelines.preprocessing.validation import validate_job_posting_row
from app.pipelines.preprocessing.artifact_writer import write_raw_copy, write_jsonl_records
from app.pipelines.ingestion.common import file_hash, get_or_create_data_source
from app.pipelines.ingestion.outcome import job_postings_outcome
from app.analytics.data_quality import compute_job_posting_quality_metrics, metrics_to_rows
from app.core.config import get_settings

COLUMN_MAP_PRESETS = {
    "naukri": {
        "job_title": "job title",
        "company_name": "company",
        "location": "joblocation_address",
        "posted_date": "postdate",
        "salary_raw": "pay rate",
        "raw_description": "job description",
        "external_posting_id": "jobid",
        "skills_tag": "skills",  # Naukri's structured comma-separated skills column
    },
    "linkedin": {
        "job_title": "title",
        "company_name": "company_name",
        "location": "location",
        "posted_date": "original_listed_time",
        "salary_raw": "med_salary",
        "raw_description": "description",
        "external_posting_id": "job_id",
        # no equivalent structured skills column in this dataset
    },
    "fixture": {
        "job_title": "job title",
        "company_name": "company",
        "location": "joblocation_address",
        "posted_date": "postdate",
        "salary_raw": "pay rate",
        "raw_description": "job description",
        "external_posting_id": "jobid",
        "skills_tag": "skills",
    },
}

DEFAULT_COLUMN_MAP = COLUMN_MAP_PRESETS["naukri"]


def ingest_job_postings_file(
    session: Session,
    csv_path: Path,
    column_map: dict | None = None,
    source_name: str = "Real job postings dataset (unspecified)",
    source_url: str | None = None,
    dataset_label: str = "jobs",
    limit: int | None = None,
) -> dict:
    column_map = column_map or DEFAULT_COLUMN_MAP

    run = AnalysisRun(
        run_type="ingestion",
        dataset_name="job_postings",
        status="running",
        started_at=datetime.utcnow(),
        pipeline_version="0.1.0",
    )
    session.add(run)
    session.flush()

    try:
        write_raw_copy(dataset_label, run.id, csv_path)

        df = pd.read_csv(csv_path, nrows=limit)
        total_input_records = len(df)
        missing_cols = [c for c in column_map.values() if c not in df.columns]

        source, source_reused = get_or_create_data_source(
            session,
            source_name=source_name,
            source_type="labour_market",
            file_hash_value=file_hash(csv_path),
            source_url=source_url,
            license_text="See dataset page — verify redistribution terms before commercial use",
            notes=(
                f"Column mapping warning: expected columns not found: {missing_cols}. "
                f"Available: {list(df.columns)}" if missing_cols else None
            ),
        )
        run.source_id = source.id

        mapped_rows = []
        for idx, row in df.iterrows():
            skills_tag_col = column_map.get("skills_tag")
            mapped_rows.append(
                {
                    "_row_idx": idx,
                    "job_title": _safe_str(row.get(column_map["job_title"])),
                    "company_name": _safe_str(row.get(column_map["company_name"])),
                    "location": _safe_str(row.get(column_map["location"])),
                    "raw_description": _safe_str(row.get(column_map["raw_description"])),
                    "salary_raw": _safe_str(row.get(column_map["salary_raw"])),
                    "external_posting_id": _safe_str(row.get(column_map["external_posting_id"])),
                    "skills_raw": _safe_str(row.get(skills_tag_col)) if skills_tag_col else None,
                    "_posted_date_raw": row.get(column_map["posted_date"]),
                }
            )

        valid_rows, rejected_rows = [], []
        for mapped in mapped_rows:
            validation = validate_job_posting_row(mapped)
            if validation.is_valid:
                valid_rows.append(mapped)
            else:
                rejected_rows.append({"reason": validation.reason, "row": mapped})
                session.add(
                    IngestionRejection(
                        analysis_run_id=run.id,
                        dataset_name="job_postings",
                        record_identifier=mapped["external_posting_id"] or str(mapped["_row_idx"]),
                        reason=validation.reason,
                        detail=validation.detail,
                        raw_snippet=(mapped["raw_description"] or "")[:200],
                    )
                )

        write_jsonl_records(
            "bronze",
            dataset_label,
            run.id,
            [
                {**{k: v for k, v in r.items() if not k.startswith("_")}, "valid": True}
                for r in valid_rows
            ]
            + [
                {**{k: v for k, v in r["row"].items() if not k.startswith("_")}, "valid": False, "rejection_reason": r["reason"]}
                for r in rejected_rows
            ],
        )

        existing_external_ids = {
            eid
            for (eid,) in session.query(JobPosting.external_posting_id)
            .filter(JobPosting.source_id == source.id, JobPosting.external_posting_id.isnot(None))
            .all()
        }
        new_rows, already_ingested_rows = partition_already_ingested(valid_rows, existing_external_ids)
        for row in already_ingested_rows:
            session.add(
                IngestionRejection(
                    analysis_run_id=run.id,
                    dataset_name="job_postings",
                    record_identifier=row["external_posting_id"],
                    reason="already_ingested",
                    detail=f"source_id={source.id} (source reused: {source_reused})",
                    raw_snippet=(row["raw_description"] or "")[:200],
                )
            )

        inserted_postings = []
        accepted_rows_for_metrics = []
        cross_run_duplicate_count = 0
        for mapped in new_rows:
            posted_date = _parse_date(mapped["_posted_date_raw"])
            clean_desc = clean_job_description(mapped["raw_description"])
            clean_hash = text_hash(clean_desc) if clean_desc else None

            cross_run_original = None
            if clean_hash:
                cross_run_original = (
                    session.query(JobPosting)
                    .filter(JobPosting.clean_description_hash == clean_hash)
                    .first()
                )

            posting = JobPosting(
                source_id=source.id,
                external_posting_id=mapped["external_posting_id"],
                job_title=mapped["job_title"],
                company_name=mapped["company_name"],
                location=mapped["location"],
                posted_date=posted_date,
                salary_raw=mapped["salary_raw"],
                raw_description=mapped["raw_description"],
                clean_description=clean_desc,
                clean_description_hash=clean_hash,
                skills_raw=mapped["skills_raw"],
            )
            if cross_run_original:
                posting.is_duplicate = 1
                posting.duplicate_of_id = cross_run_original.id
                posting.duplicate_scope = "cross_run"
                cross_run_duplicate_count += 1

            session.add(posting)
            inserted_postings.append(posting)
            accepted_rows_for_metrics.append({"clean_description": clean_desc})

        session.flush()

        dedup_input = [
            {
                "id": p.id,
                "job_title": p.job_title,
                "company_name": p.company_name,
                "clean_description": p.clean_description,
            }
            for p in inserted_postings
            if not p.is_duplicate
        ]
        duplicate_map = find_near_duplicates(
            dedup_input, similarity_threshold=get_settings().near_duplicate_similarity_threshold
        )
        exact_duplicate_count = 0
        near_duplicate_count = 0
        by_id = {p.id: p for p in inserted_postings}

        for dup_id, original_id in duplicate_map.items():
            by_id[dup_id].is_duplicate = 1
            by_id[dup_id].duplicate_of_id = original_id
            by_id[dup_id].duplicate_scope = "within_batch"
            if (by_id[dup_id].clean_description or "") == (by_id[original_id].clean_description or ""):
                exact_duplicate_count += 1
            else:
                near_duplicate_count += 1

        write_jsonl_records(
            "silver",
            dataset_label,
            run.id,
            [
                {
                    "id": p.id,
                    "external_posting_id": p.external_posting_id,
                    "job_title": p.job_title,
                    "company_name": p.company_name,
                    "clean_description": p.clean_description,
                    "skills_raw": p.skills_raw,
                    "is_duplicate": bool(p.is_duplicate),
                    "duplicate_of_id": p.duplicate_of_id,
                    "duplicate_scope": p.duplicate_scope,
                }
                for p in inserted_postings
            ],
        )

        quality_metrics = compute_job_posting_quality_metrics(
            total_input_records=total_input_records,
            accepted_records=accepted_rows_for_metrics,
            rejected_records=[{"reason": r["reason"]} for r in rejected_rows],
            duplicate_count=exact_duplicate_count + cross_run_duplicate_count,
            near_duplicate_count=near_duplicate_count,
            already_ingested_count=len(already_ingested_rows),
        )
        for row_dict in metrics_to_rows(quality_metrics, run.id, source.id):
            session.add(DataQualityMetric(**row_dict))

        run.status = "succeeded"
        run.records_processed = len(inserted_postings)
        run.records_failed = len(rejected_rows)
        run.finished_at = datetime.utcnow()
        session.commit()

        result = {
            "analysis_run_id": run.id,
            "source_id": source.id,
            "status": "succeeded",
            "source_reused": source_reused,
            "records_input": total_input_records,
            "records_accepted": len(inserted_postings),
            "records_rejected": len(rejected_rows),
            "duplicates_flagged": exact_duplicate_count + near_duplicate_count + cross_run_duplicate_count,
            "already_ingested_skipped": len(already_ingested_rows),
            "cross_run_duplicates_flagged": cross_run_duplicate_count,
            "quality_metrics": quality_metrics,
        }
        result["outcome"] = job_postings_outcome(result)
        return result
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_log = str(exc)
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        raise


def _safe_str(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    s = str(value).strip()
    return s or None


def _parse_date(raw_value):
    if raw_value is None or (isinstance(raw_value, float) and pd.isna(raw_value)):
        return None
    try:
        dt = pd.to_datetime(raw_value, unit="ms", errors="coerce")
        if pd.isna(dt):
            dt = pd.to_datetime(raw_value, errors="coerce")
        if pd.isna(dt):
            return None
        return dt.to_pydatetime()
    except Exception:
        return None
