"""
Core Discipline Knowledge Layer read API. Returns only what is actually
stored -- the tables are empty until real authoritative sources are
imported, so every list endpoint honestly returns an empty list today.

Leakage safeguards:
- /topics REQUIRES discipline_id (no accidental cross-discipline listing).
- Records whose DataSource has is_test_data=1 are EXCLUDED by default;
  pass include_test_data=true explicitly to see fixtures.
- Records with no source_id are returned with source=null (missing
  provenance is visible, never hidden or back-filled).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.data_source import DataSource
from app.models.curriculum import Discipline
from app.models.core_knowledge import CoreKnowledgeDomain, CoreTopic, CoreSubtopic, CoreKnowledgeSkillMapping

router = APIRouter(prefix="/api/v1/core-knowledge", tags=["core-knowledge"])


def _source_dict(source):
    if source is None:
        return None
    return {
        "id": source.id, "source_name": source.source_name, "source_type": source.source_type,
        "source_url": source.source_url, "version": source.version,
        "retrieval_date": source.retrieval_date.isoformat() if source.retrieval_date else None,
        "is_test_data": bool(source.is_test_data),
    }


def _sources_by_id(db):
    return {s.id: s for s in db.query(DataSource).all()}


def _visible(source_id, sources, include_test_data):
    if source_id is None:
        return True  # missing provenance is shown (source=null), not hidden
    src = sources.get(source_id)
    return include_test_data or src is None or not src.is_test_data


@router.get("/sources")
def list_core_knowledge_sources(
    source_type: str | None = Query(None),
    include_test_data: bool = Query(False),
    db: Session = Depends(get_db),
):
    used_ids = {sid for (sid,) in db.query(CoreKnowledgeDomain.source_id).distinct() if sid is not None}
    used_ids |= {sid for (sid,) in db.query(CoreTopic.source_id).distinct() if sid is not None}
    q = db.query(DataSource).filter(DataSource.id.in_(used_ids)) if used_ids else None
    rows = q.all() if q is not None else []
    if source_type:
        rows = [r for r in rows if r.source_type == source_type]
    if not include_test_data:
        rows = [r for r in rows if not r.is_test_data]
    return {"items": [_source_dict(r) for r in rows]}


@router.get("/disciplines/{discipline_id}")
def get_discipline_core_knowledge(discipline_id: int, include_test_data: bool = Query(False), db: Session = Depends(get_db)):
    discipline = db.query(Discipline).filter(Discipline.id == discipline_id).one_or_none()
    if not discipline:
        raise HTTPException(404, "Discipline not found")
    sources = _sources_by_id(db)
    domains = [
        d for d in db.query(CoreKnowledgeDomain).filter(CoreKnowledgeDomain.discipline_id == discipline_id).all()
        if _visible(d.source_id, sources, include_test_data)
    ]
    return {
        "discipline": {"id": discipline.id, "name": discipline.name},
        "domains": [
            {
                "id": d.id, "name": d.name, "is_active": bool(d.is_active), "confidence": d.confidence,
                "topic_count": db.query(CoreTopic).filter(CoreTopic.domain_id == d.id).count(),
                "source": _source_dict(sources.get(d.source_id)),
            }
            for d in domains
        ],
    }


@router.get("/topics")
def list_core_topics(
    discipline_id: int = Query(..., description="REQUIRED -- prevents cross-discipline listing"),
    include_inactive: bool = Query(False, description="Inactive (retracted/superseded) topics are excluded unless true"),
    include_test_data: bool = Query(False),
    db: Session = Depends(get_db),
):
    sources = _sources_by_id(db)
    q = (
        db.query(CoreTopic, CoreKnowledgeDomain)
        .join(CoreKnowledgeDomain, CoreTopic.domain_id == CoreKnowledgeDomain.id)
        .filter(CoreKnowledgeDomain.discipline_id == discipline_id)
    )
    if not include_inactive:
        q = q.filter(CoreTopic.is_active == 1, CoreKnowledgeDomain.is_active == 1)
    items = []
    for t, d in q.all():
        if not _visible(t.source_id, sources, include_test_data):
            continue
        items.append({
            "id": t.id, "name": t.name, "domain_id": d.id, "domain_name": d.name,
            "is_active": bool(t.is_active), "confidence": t.confidence,
            "source": _source_dict(sources.get(t.source_id)),
        })
    return {"discipline_id": discipline_id, "items": items}


@router.get("/topics/{topic_id}")
def get_core_topic(topic_id: int, db: Session = Depends(get_db)):
    topic = db.query(CoreTopic).filter(CoreTopic.id == topic_id).one_or_none()
    if not topic:
        raise HTTPException(404, "Core topic not found")
    sources = _sources_by_id(db)
    domain = db.query(CoreKnowledgeDomain).filter(CoreKnowledgeDomain.id == topic.domain_id).one()
    subtopics = db.query(CoreSubtopic).filter(CoreSubtopic.topic_id == topic.id).all()
    mappings = db.query(CoreKnowledgeSkillMapping).filter(CoreKnowledgeSkillMapping.core_topic_id == topic.id).all()
    return {
        "id": topic.id, "name": topic.name, "description": topic.description,
        "domain": {"id": domain.id, "name": domain.name, "discipline_id": domain.discipline_id},
        "is_active": bool(topic.is_active), "confidence": topic.confidence,
        "source": _source_dict(sources.get(topic.source_id)),
        "subtopics": [
            {"id": s.id, "name": s.name, "is_active": bool(s.is_active), "source": _source_dict(sources.get(s.source_id))}
            for s in subtopics
        ],
        "skill_mappings": [
            {"skill_id": m.skill_id, "method": m.method, "confidence": m.confidence,
             "source": _source_dict(sources.get(m.source_id))}
            for m in mappings
        ],
    }


@router.get("/mappings")
def list_core_skill_mappings(
    core_topic_id: int | None = Query(None),
    skill_id: int | None = Query(None),
    method: str | None = Query(None),
    db: Session = Depends(get_db),
):
    if core_topic_id is None and skill_id is None:
        raise HTTPException(400, "Provide core_topic_id or skill_id (unscoped global listing is not offered).")
    q = db.query(CoreKnowledgeSkillMapping)
    if core_topic_id is not None:
        q = q.filter(CoreKnowledgeSkillMapping.core_topic_id == core_topic_id)
    if skill_id is not None:
        q = q.filter(CoreKnowledgeSkillMapping.skill_id == skill_id)
    if method:
        q = q.filter(CoreKnowledgeSkillMapping.method == method)
    sources = _sources_by_id(db)
    return {
        "items": [
            {"id": m.id, "core_topic_id": m.core_topic_id, "core_subtopic_id": m.core_subtopic_id,
             "skill_id": m.skill_id, "method": m.method, "confidence": m.confidence,
             "source": _source_dict(sources.get(m.source_id))}
            for m in q.all()
        ]
    }
