from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.curriculum import Institution, Programme, Course, Module, CurriculumTopic, Document

router = APIRouter(prefix="/api/v1", tags=["curricula"])


@router.get("/curricula")
def list_curricula(db: Session = Depends(get_db)):
    institutions = db.query(Institution).all()
    result = []
    for inst in institutions:
        programmes = db.query(Programme).filter(Programme.institution_id == inst.id).all()
        result.append(
            {
                "institution_id": inst.id,
                "institution_name": inst.name,
                "programmes": [
                    {
                        "programme_id": p.id,
                        "programme_name": p.name,
                        "course_count": db.query(Course).filter(Course.programme_id == p.id).count(),
                    }
                    for p in programmes
                ],
            }
        )
    return result


@router.get("/curricula/documents/{document_id}")
def get_document_detail(document_id: int, db: Session = Depends(get_db)):
    """
    Traces Document -> extraction quality -> flagged status, for the
    "inspect problematic records" requirement applied to curriculum ingestion.
    """
    doc = db.query(Document).filter(Document.id == document_id).one_or_none()
    if not doc:
        raise HTTPException(404, "Document not found")
    return {
        "id": doc.id,
        "file_name": doc.file_name,
        "file_type": doc.file_type,
        "page_count": doc.page_count,
        "extraction_method": doc.extraction_method,
        "extraction_confidence": doc.extraction_confidence,
        "flagged_for_review": bool(doc.flagged_for_review),
        "source_id": doc.source_id,
    }


@router.get("/courses/{course_id}")
def get_course_detail(course_id: int, db: Session = Depends(get_db)):
    course = db.query(Course).filter(Course.id == course_id).one_or_none()
    if not course:
        raise HTTPException(404, "Course not found")
    modules = db.query(Module).filter(Module.course_id == course.id).all()
    return {
        "id": course.id,
        "course_code": course.course_code,
        "name": course.name,
        "modules": [
            {
                "id": m.id,
                "name": m.name,
                "topics": [
                    {"id": t.id, "topic_text": t.topic_text, "source_page": t.source_page}
                    for t in db.query(CurriculumTopic).filter(CurriculumTopic.module_id == m.id).all()
                ],
            }
            for m in modules
        ],
    }
