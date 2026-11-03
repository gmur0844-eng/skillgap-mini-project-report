from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.data_source import DataSource

router = APIRouter(prefix="/api/v1", tags=["data-sources"])


@router.get("/data-sources")
def list_data_sources(db: Session = Depends(get_db)):
    """
    Every real dataset ingested into this system is registered here with its
    source_url, license, version, and retrieval_date. This endpoint is empty
    until ingestion scripts have actually been run against real data — it never
    returns fabricated entries.
    """
    rows = db.query(DataSource).all()
    return [
        {
            "id": r.id,
            "source_name": r.source_name,
            "source_url": r.source_url,
            "source_type": r.source_type,
            "retrieval_date": r.retrieval_date.isoformat() if r.retrieval_date else None,
            "license": r.license,
            "version": r.version,
            "institution": r.institution,
            "programme": r.programme,
        }
        for r in rows
    ]
