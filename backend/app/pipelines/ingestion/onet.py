"""
Core O*NET ingestion logic (DB-dependent). Mirrors app/pipelines/ingestion/esco.py.
"""
import csv
import hashlib
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.skills import Skill
from app.models.jobs import Occupation
from app.models.analysis import AnalysisRun
from app.pipelines.ingestion.common import get_or_create_data_source


def _ingest_occupations(path: Path, session: Session) -> int:
    count = 0
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            code = (row.get("O*NET-SOC Code") or "").strip()
            title = (row.get("Title") or "").strip()
            if not code or not title:
                continue
            existing = (
                session.query(Occupation)
                .filter(Occupation.taxonomy == "ONET", Occupation.external_id == code)
                .one_or_none()
            )
            if existing:
                continue
            session.add(
                Occupation(
                    taxonomy="ONET",
                    external_id=code,
                    title=title,
                    description=(row.get("Description") or "").strip() or None,
                )
            )
            count += 1
    return count


def _ingest_technology_skills(path: Path, session: Session) -> int:
    count = 0
    seen = set()
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if "Example" not in (reader.fieldnames or []):
            raise ValueError(
                f"{path.name}: expected an 'Example' column, found {reader.fieldnames}."
            )
        for row in reader:
            example = (row.get("Example") or "").strip()
            if not example or example in seen:
                continue
            seen.add(example)
            existing = (
                session.query(Skill)
                .filter(Skill.taxonomy == "ONET", Skill.external_id == example)
                .one_or_none()
            )
            if existing:
                continue
            session.add(
                Skill(
                    taxonomy="ONET",
                    external_id=example,
                    preferred_label=example,
                    skill_group=(row.get("Commodity Title") or "").strip() or None,
                )
            )
            count += 1
    return count


def ingest_onet_files(
    session: Session,
    occupations_path: Path | None,
    tech_skills_path: Path | None,
    version: str = "unspecified",
) -> dict:
    run = AnalysisRun(
        run_type="ingestion",
        dataset_name="onet",
        status="running",
        started_at=datetime.utcnow(),
        pipeline_version="0.1.0",
        taxonomy_version=f"ONET-{version}",
    )
    session.add(run)
    session.flush()

    try:
        combined_hash = hashlib.sha256()
        for p in (occupations_path, tech_skills_path):
            if p is not None:
                combined_hash.update(p.read_bytes())

        source, _source_reused = get_or_create_data_source(
            session,
            source_name="O*NET Database",
            source_type="taxonomy",
            file_hash_value=combined_hash.hexdigest(),
            source_url="https://www.onetcenter.org/database.html",
            license_text="Creative Commons (O*NET)",
            version=version,
        )
        run.source_id = source.id

        occupations_ingested = _ingest_occupations(occupations_path, session) if occupations_path else 0
        tech_skills_ingested = _ingest_technology_skills(tech_skills_path, session) if tech_skills_path else 0

        run.status = "succeeded"
        run.records_processed = occupations_ingested + tech_skills_ingested
        run.records_failed = 0
        run.finished_at = datetime.utcnow()
        session.commit()

        return {
            "analysis_run_id": run.id,
            "source_id": source.id,
            "occupations_ingested": occupations_ingested,
            "technology_skills_ingested": tech_skills_ingested,
        }
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_log = str(exc)
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        raise
