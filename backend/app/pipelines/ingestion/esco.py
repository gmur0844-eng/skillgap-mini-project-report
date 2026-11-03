"""
Core ESCO ingestion logic (DB-dependent). Both scripts/ingestion/ingest_esco.py
(CLI) and app.api.v1.ingestion (API upload endpoint) call `ingest_esco_file`
so there is exactly one implementation to maintain.
"""
import csv
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.skills import Skill, SkillAlias
from app.models.analysis import AnalysisRun
from app.pipelines.ingestion.common import file_hash, get_or_create_data_source

REQUIRED_COLUMNS = {"conceptUri", "preferredLabel"}


def ingest_esco_file(session: Session, csv_path: Path, version: str = "unspecified", source_url: str | None = None) -> dict:
    """
    Returns a summary dict: {analysis_run_id, source_id, skills_ingested,
    skills_skipped, skip_reasons}. Creates an AnalysisRun and reuses/creates a
    DataSource row keyed by file hash (see app.pipelines.ingestion.common), so
    re-running against the same ESCO export doesn't create a duplicate source
    record. Per-skill idempotency is handled separately below via the
    existing-external_id check ("already_exists" in skip_reasons).
    """
    run = AnalysisRun(
        run_type="ingestion",
        dataset_name="esco",
        status="running",
        started_at=datetime.utcnow(),
        pipeline_version="0.1.0",
        taxonomy_version=f"ESCO-{version}",
    )
    session.add(run)
    session.flush()

    try:
        source, _source_reused = get_or_create_data_source(
            session,
            source_name="ESCO",
            source_type="taxonomy",
            file_hash_value=file_hash(csv_path),
            source_url=source_url or "https://esco.ec.europa.eu/en/use-esco/download",
            license_text="ESCO open reuse (see portal for exact terms of the downloaded version)",
            version=version,
        )
        run.source_id = source.id

        skills_ingested = 0
        skills_skipped = 0
        skip_reasons: dict[str, int] = {}

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise ValueError(
                    f"{csv_path.name} is missing expected ESCO columns {missing}. "
                    f"Found columns: {reader.fieldnames}."
                )

            for row in reader:
                uri = (row.get("conceptUri") or "").strip()
                label = (row.get("preferredLabel") or "").strip()
                if not uri or not label:
                    skills_skipped += 1
                    skip_reasons["missing_uri_or_label"] = skip_reasons.get("missing_uri_or_label", 0) + 1
                    continue

                existing = (
                    session.query(Skill)
                    .filter(Skill.taxonomy == "ESCO", Skill.external_id == uri)
                    .one_or_none()
                )
                if existing:
                    skills_skipped += 1
                    skip_reasons["already_exists"] = skip_reasons.get("already_exists", 0) + 1
                    continue

                skill = Skill(
                    taxonomy="ESCO",
                    external_id=uri,
                    preferred_label=label,
                    description=(row.get("description") or "").strip() or None,
                    skill_group=row.get("skillType") or row.get("conceptType") or None,
                )
                session.add(skill)
                session.flush()

                alt_labels = (row.get("altLabels") or "").strip()
                if alt_labels:
                    for alias in [a.strip() for a in alt_labels.replace("\r", "").split("\n") if a.strip()]:
                        session.add(SkillAlias(skill_id=skill.id, alias_label=alias))

                skills_ingested += 1

        run.status = "succeeded"
        run.records_processed = skills_ingested
        run.records_failed = skills_skipped
        run.finished_at = datetime.utcnow()
        session.commit()

        return {
            "analysis_run_id": run.id,
            "source_id": source.id,
            "skills_ingested": skills_ingested,
            "skills_skipped": skills_skipped,
            "skip_reasons": skip_reasons,
        }
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_log = str(exc)
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        raise
