from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.session import get_db
from app.models.jobs import JobPosting
from app.models.curriculum import Course, Programme, Institution

router = APIRouter(prefix="/api/v1", tags=["data-quality"])

# Below this many real job postings, alignment/gap/trend numbers are not
# statistically meaningful enough to present as findings (spec Section 9:
# "clearly tell the user if the dataset is too poor for reliable analysis").
MIN_POSTINGS_FOR_RELIABLE_ANALYSIS = 500


@router.get("/data-quality")
def data_quality_overview(db: Session = Depends(get_db)):
    total_postings = db.query(func.count(JobPosting.id)).scalar() or 0
    missing_desc = (
        db.query(func.count(JobPosting.id)).filter(JobPosting.clean_description.is_(None)).scalar() or 0
    )
    duplicate_postings = db.query(func.count(JobPosting.id)).filter(JobPosting.is_duplicate == 1).scalar() or 0
    total_institutions = db.query(func.count(Institution.id)).scalar() or 0
    total_programmes = db.query(func.count(Programme.id)).scalar() or 0
    total_courses = db.query(func.count(Course.id)).scalar() or 0

    return {
        "job_postings": {
            "total": total_postings,
            "missing_clean_description": missing_desc,
            "missing_pct": round(missing_desc / total_postings * 100, 2) if total_postings else None,
            "duplicate_count": duplicate_postings,
            "duplicate_pct": round(duplicate_postings / total_postings * 100, 2) if total_postings else None,
        },
        "curriculum": {
            "institutions": total_institutions,
            "programmes": total_programmes,
            "courses": total_courses,
        },
        "reliable_for_analysis": total_postings >= MIN_POSTINGS_FOR_RELIABLE_ANALYSIS
        and total_courses > 0,
        "note": (
            None
            if total_postings >= MIN_POSTINGS_FOR_RELIABLE_ANALYSIS and total_courses > 0
            else "Insufficient real data loaded yet — run the ingestion scripts in "
            "scripts/ingestion/ before trusting any alignment/gap/trend numbers."
        ),
    }
