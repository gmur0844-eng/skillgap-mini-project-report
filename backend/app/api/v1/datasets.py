from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.data_source import DataSource, DataQualityMetric
from app.models.analysis import AnalysisRun

router = APIRouter(prefix="/api/v1", tags=["datasets"])


@router.get("/datasets")
def list_datasets(db: Session = Depends(get_db)):
    """
    One row per DataSource, with the latest pipeline run status/counts and its
    recorded quality metrics attached — the "what real data do we actually
    have loaded, and how good is it" view.
    """
    sources = db.query(DataSource).all()
    results = []
    for s in sources:
        latest_run = (
            db.query(AnalysisRun)
            .filter(AnalysisRun.source_id == s.id)
            .order_by(AnalysisRun.started_at.desc())
            .first()
        )
        metrics = (
            db.query(DataQualityMetric).filter(DataQualityMetric.source_id == s.id).all()
            if latest_run
            else []
        )
        results.append(
            {
                "source_id": s.id,
                "source_name": s.source_name,
                "source_type": s.source_type,
                "license": s.license,
                "version": s.version,
                "retrieval_date": s.retrieval_date.isoformat() if s.retrieval_date else None,
                "latest_run": {
                    "id": latest_run.id,
                    "status": latest_run.status,
                    "records_processed": latest_run.records_processed,
                    "records_failed": latest_run.records_failed,
                }
                if latest_run
                else None,
                "quality_metrics": {m.metric_name: m.metric_value for m in metrics},
            }
        )
    return results
