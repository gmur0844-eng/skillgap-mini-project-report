"""
Shared helpers used by every ingestion module (esco/onet/job_postings/curriculum).
Pulled out here specifically to fix a Phase-1 hardening bug: every ingestion
run used to create a brand-new DataSource row even when re-ingesting the exact
same file, which made a (source_id, external_posting_id) uniqueness check
meaningless -- source_id was never stable across runs of "the same dataset".
"""
import hashlib
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.data_source import DataSource


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def get_or_create_data_source(
    session: Session,
    *,
    source_name: str,
    source_type: str,
    file_hash_value: str,
    source_url: str | None = None,
    license_text: str | None = None,
    version: str | None = None,
    institution: str | None = None,
    programme: str | None = None,
    notes: str | None = None,
    is_test_data: bool = False,
) -> tuple[DataSource, bool]:
    """
    Returns (data_source, was_created). Re-ingesting a byte-identical file
    (same file_hash + source_type) reuses the existing DataSource row instead
    of creating a new one, which is what makes source_id-scoped idempotency
    checks (see app.pipelines.ingestion.job_postings) actually work across
    repeated runs rather than just within one run.
    """
    existing = (
        session.query(DataSource)
        .filter(DataSource.source_type == source_type, DataSource.file_hash == file_hash_value)
        .one_or_none()
    )
    if existing:
        return existing, False

    source = DataSource(
        source_name=source_name,
        source_url=source_url,
        source_type=source_type,
        retrieval_date=datetime.utcnow(),
        license=license_text,
        version=version,
        institution=institution,
        programme=programme,
        file_hash=file_hash_value,
        notes=notes,
        is_test_data=1 if is_test_data else 0,
    )
    session.add(source)
    session.flush()
    return source, True
