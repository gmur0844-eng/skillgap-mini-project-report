from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.analysis import AnalysisRun, IngestionRejection

router = APIRouter(prefix="/api/v1", tags=["pipeline-runs"])


def _run_to_dict(r: AnalysisRun) -> dict:
    return {
        "id": r.id,
        "run_type": r.run_type,
        "dataset_name": r.dataset_name,
        "source_id": r.source_id,
        "status": r.status,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "records_processed": r.records_processed,
        "records_failed": r.records_failed,
        "pipeline_version": r.pipeline_version,
        "error_log": r.error_log,
    }


@router.get("/pipeline-runs")
def list_pipeline_runs(db: Session = Depends(get_db)):
    runs = db.query(AnalysisRun).order_by(AnalysisRun.started_at.desc()).all()
    return [_run_to_dict(r) for r in runs]


@router.get("/pipeline-runs/{run_id}")
def get_pipeline_run(run_id: int, db: Session = Depends(get_db)):
    run = db.query(AnalysisRun).filter(AnalysisRun.id == run_id).one_or_none()
    if not run:
        raise HTTPException(404, "Pipeline run not found")
    rejections = (
        db.query(IngestionRejection).filter(IngestionRejection.analysis_run_id == run_id).limit(200).all()
    )
    result = _run_to_dict(run)
    result["rejections"] = [
        {
            "record_identifier": rej.record_identifier,
            "reason": rej.reason,
            "detail": rej.detail,
            "raw_snippet": rej.raw_snippet,
        }
        for rej in rejections
    ]
    return result
