from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.jobs import ExtractedSkill

router = APIRouter(prefix="/api/v1", tags=["skill-mentions"])


def _mention_to_dict(m: ExtractedSkill) -> dict:
    return {
        "id": m.id,
        "job_posting_id": m.job_posting_id,
        "course_id": m.course_id,
        "curriculum_topic_id": m.curriculum_topic_id,
        "course_learning_outcome_id": m.course_learning_outcome_id,
        "original_text_span": m.original_text_span,
        "normalized_text_span": m.normalized_text_span,
        "normalized_skill_id": m.normalized_skill_id,
        "mapping_status": m.mapping_status,
        "extraction_method": m.extraction_method,
        "confidence": m.confidence,
        "context_snippet": m.context_snippet,
        "mention_hash": m.mention_hash,
        "analysis_run_id": m.analysis_run_id,
    }


@router.get("/skill-mentions")
def list_skill_mentions(
    mapping_status: str | None = Query(None, description="mapped | unmapped"),
    extraction_method: str | None = Query(None),
    source_type: str | None = Query(None, description="job_posting | course | curriculum_topic | course_learning_outcome"),
    job_posting_id: int | None = Query(None),
    course_id: int | None = Query(None),
    normalized_skill_id: int | None = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(ExtractedSkill)
    if mapping_status:
        q = q.filter(ExtractedSkill.mapping_status == mapping_status)
    if extraction_method:
        q = q.filter(ExtractedSkill.extraction_method == extraction_method)
    if job_posting_id:
        q = q.filter(ExtractedSkill.job_posting_id == job_posting_id)
    if course_id:
        q = q.filter(ExtractedSkill.course_id == course_id)
    if normalized_skill_id:
        q = q.filter(ExtractedSkill.normalized_skill_id == normalized_skill_id)
    if source_type == "job_posting":
        q = q.filter(ExtractedSkill.job_posting_id.isnot(None))
    elif source_type == "course":
        q = q.filter(ExtractedSkill.course_id.isnot(None))
    elif source_type == "curriculum_topic":
        q = q.filter(ExtractedSkill.curriculum_topic_id.isnot(None))
    elif source_type == "course_learning_outcome":
        q = q.filter(ExtractedSkill.course_learning_outcome_id.isnot(None))

    total = q.count()
    rows = q.order_by(ExtractedSkill.id).offset(offset).limit(limit).all()
    return {"total": total, "items": [_mention_to_dict(m) for m in rows]}


@router.get("/skill-mentions/{mention_id}")
def get_skill_mention(mention_id: int, db: Session = Depends(get_db)):
    m = db.query(ExtractedSkill).filter(ExtractedSkill.id == mention_id).one_or_none()
    if not m:
        raise HTTPException(404, "Skill mention not found")
    return _mention_to_dict(m)
