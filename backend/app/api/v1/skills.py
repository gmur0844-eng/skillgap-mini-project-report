from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.skills import Skill, SkillAlias

router = APIRouter(prefix="/api/v1", tags=["skills"])


@router.get("/skills")
def list_skills(
    taxonomy: str | None = Query(None, description="ESCO | ONET"),
    search: str | None = Query(None, description="Substring match on preferred_label"),
    limit: int = Query(100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Skill)
    if taxonomy:
        q = q.filter(Skill.taxonomy == taxonomy.upper())
    if search:
        q = q.filter(Skill.preferred_label.ilike(f"%{search}%"))
    total = q.count()
    rows = q.order_by(Skill.preferred_label).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": s.id,
                "taxonomy": s.taxonomy,
                "external_id": s.external_id,
                "preferred_label": s.preferred_label,
                "skill_group": s.skill_group,
            }
            for s in rows
        ],
    }


@router.get("/skills/{skill_id}")
def get_skill_detail(skill_id: int, db: Session = Depends(get_db)):
    """
    Canonical skill detail, including its aliases -- the "alias system" view
    (spec Section 7): preferred label -> alternative labels -> normalized
    forms, all traceable to this one canonical skill.
    """
    skill = db.query(Skill).filter(Skill.id == skill_id).one_or_none()
    if not skill:
        raise HTTPException(404, "Skill not found")
    aliases = db.query(SkillAlias).filter(SkillAlias.skill_id == skill.id).all()
    return {
        "id": skill.id,
        "taxonomy": skill.taxonomy,
        "external_id": skill.external_id,
        "preferred_label": skill.preferred_label,
        "description": skill.description,
        "skill_group": skill.skill_group,
        "aliases": [a.alias_label for a in aliases],
    }
