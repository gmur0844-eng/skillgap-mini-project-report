from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.jobs import JobPosting, ExtractedSkill

router = APIRouter(prefix="/api/v1", tags=["jobs"])


@router.get("/jobs")
def list_jobs(
    limit: int = Query(50, le=500),
    offset: int = 0,
    only_duplicates: bool | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(JobPosting)
    if only_duplicates is True:
        q = q.filter(JobPosting.is_duplicate == 1)
    elif only_duplicates is False:
        q = q.filter(JobPosting.is_duplicate == 0)
    total = q.count()
    rows = q.order_by(JobPosting.id).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "job_title": r.job_title,
                "company_name": r.company_name,
                "location": r.location,
                "posted_date": r.posted_date.isoformat() if r.posted_date else None,
                "is_duplicate": bool(r.is_duplicate),
                "duplicate_of_id": r.duplicate_of_id,
            }
            for r in rows
        ],
    }


@router.get("/jobs/{job_id}/preview")
def preview_job(job_id: int, db: Session = Depends(get_db)):
    """
    Powers the Flutter "Preprocessing Preview" screen: RAW TEXT -> CLEANED TEXT
    -> STRUCTURED RECORD for one specific job posting, per the spec's explicit
    demonstration requirement. Skill extraction fields will be added once that
    phase exists — until then this only shows what's genuinely implemented.
    """
    posting = db.query(JobPosting).filter(JobPosting.id == job_id).one_or_none()
    if not posting:
        raise HTTPException(404, "Job posting not found")

    mentions = db.query(ExtractedSkill).filter(ExtractedSkill.job_posting_id == job_id).all()

    return {
        "raw_text": posting.raw_description,
        "clean_text": posting.clean_description,
        "structured_record": {
            "id": posting.id,
            "job_title": posting.job_title,
            "company_name": posting.company_name,
            "location": posting.location,
            "posted_date": posting.posted_date.isoformat() if posting.posted_date else None,
            "salary_raw": posting.salary_raw,
            "skills_raw": posting.skills_raw,
            "is_duplicate": bool(posting.is_duplicate),
            "duplicate_of_id": posting.duplicate_of_id,
            "source_id": posting.source_id,
        },
        "extracted_skills": (
            [
                {
                    "original_text": m.original_text_span,
                    "normalized_text": m.normalized_text_span,
                    "extraction_method": m.extraction_method,
                    "mapping_status": m.mapping_status,
                    "normalized_skill_id": m.normalized_skill_id,
                    "confidence": m.confidence,
                }
                for m in mentions
            ]
            if mentions
            else None  # None (not []) explicitly signals "extraction hasn't been run for this posting yet"
        ),
    }
