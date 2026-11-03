"""
Curriculum knowledge API: read-only views of the latest GOLD knowledge run
(or ?run_id=...). All logic lives in app.services.knowledge_service; these
routes only translate query parameters and 404s.

Fail-safe behaviour is preserved end to end: an analytics gate that the
pipeline BLOCKED is returned as {"status": "BLOCKED", "gate": {...reasons}}
with no items, never as numbers.
"""
from fastapi import APIRouter, HTTPException, Query

from app.services import knowledge_service as ks

router = APIRouter(prefix="/api/v1/curriculum", tags=["curriculum-knowledge"])


def _run(run_id):
    try:
        return ks.load_run(run_id)
    except ks.InvalidRunId as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_RUN_ID", "message": str(exc)}) from exc
    except ks.RunNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": ks.not_found_code(exc), "message": str(exc)}) from exc


@router.get("/knowledge-runs/latest")
def latest_run(run_id: str | None = Query(None)):
    return ks.run_summary(_run(run_id))


@router.get("/knowledge-health")
def knowledge_health(run_id: str | None = Query(None)):
    return ks.health(_run(run_id))


@router.get("/blocked-analytics")
def blocked_analytics(run_id: str | None = Query(None)):
    return ks.blocked_analytics(_run(run_id))


@router.get("/topics")
def topics(doc_id: str | None = None, course_code: str | None = None, include_noise: bool = False,
           q: str | None = None, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
           run_id: str | None = None):
    return ks.list_topics(_run(run_id), doc_id, course_code, include_noise, q, limit, offset)


@router.get("/concepts")
def concepts(discipline: str | None = None, family_uid: str | None = None, evidence_status: str | None = None,
             review_priority: str | None = None, q: str | None = None,
             limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), run_id: str | None = None):
    return ks.list_concepts(_run(run_id), discipline, family_uid, evidence_status, review_priority, q, limit, offset)


@router.get("/concepts/{concept_uid}")
def concept(concept_uid: str, run_id: str | None = None):
    result = ks.get_concept(_run(run_id), concept_uid)
    if result is None:
        raise HTTPException(status_code=404, detail="concept not found in this run")
    return result


@router.get("/concepts/{concept_uid}/related")
def concept_related(concept_uid: str, run_id: str | None = None):
    result = ks.related_concepts(_run(run_id), concept_uid)
    if result is None:
        raise HTTPException(status_code=404, detail="concept not found in this run")
    return result


@router.get("/concepts/{concept_uid}/evidence")
def concept_evidence(concept_uid: str, run_id: str | None = None):
    result = ks.concept_evidence(_run(run_id), concept_uid)
    if result is None:
        raise HTTPException(status_code=404, detail="concept not found in this run")
    return result


@router.get("/concept-mappings")
def concept_mappings(relationship: str | None = None, course_code: str | None = None,
                     limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), run_id: str | None = None):
    return ks.concept_mappings(_run(run_id), relationship, course_code, limit, offset)


@router.get("/knowledge-graph")
def knowledge_graph(discipline: str | None = None, family_uid: str | None = None,
                    max_nodes: int = Query(500, ge=1, le=5000), run_id: str | None = None):
    return ks.knowledge_graph(_run(run_id), discipline, family_uid, max_nodes)


@router.get("/review-queue")
def review_queue(priority: str | None = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                 run_id: str | None = None):
    return ks.review_queue(_run(run_id), priority, limit, offset)


@router.get("/skill-candidates")
def skill_candidates(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), run_id: str | None = None):
    return ks.skill_candidates(_run(run_id), limit, offset)


# ---------------- industry / ESCO layer ----------------
# skill_key is an ESCO URI or "surface:<text>", so it is passed as a query
# parameter rather than a path segment. Every industry response carries the
# population scope and the representativeness warning.
industry_router = APIRouter(prefix="/api/v1/industry", tags=["industry-knowledge"])


def _not_found(result, what):
    if result is None:
        raise HTTPException(status_code=404, detail=f"{what} not found in this run")
    return result


@industry_router.get("/scope")
def industry_scope(run_id: str | None = None):
    return ks.industry_scope(_run(run_id))


@industry_router.get("/health")
def industry_health(run_id: str | None = None):
    return ks.industry_health(_run(run_id))


@industry_router.get("/esco-audit")
def esco_audit(run_id: str | None = None):
    return ks.esco_audit(_run(run_id))


@industry_router.get("/demand")
def industry_demand(support_state: str | None = None, esco_status: str | None = None,
                    limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), run_id: str | None = None):
    return ks.industry_demand(_run(run_id), support_state, esco_status, limit, offset)


@industry_router.get("/skills")
def industry_skills(esco_status: str | None = None, limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
                    run_id: str | None = None):
    return ks.industry_skills(_run(run_id), esco_status, limit, offset)


@industry_router.get("/segments")
def industry_segments(run_id: str | None = None):
    return ks.industry_segments(_run(run_id))


@industry_router.get("/gaps")
def skill_gaps(classification: str | None = None, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
               run_id: str | None = None):
    return ks.skill_gaps(_run(run_id), classification, limit, offset)


@industry_router.get("/recommendations")
def recommendations(include_suppressed: bool = False, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
                    run_id: str | None = None):
    return ks.recommendations(_run(run_id), include_suppressed, limit, offset)


@industry_router.get("/why-no-recommendation")
def why_no_recommendation(skill_key: str, run_id: str | None = None):
    return _not_found(ks.why_no_recommendation(_run(run_id), skill_key), "industry layer")


@industry_router.get("/evidence-trace")
def evidence_trace(skill_key: str, run_id: str | None = None):
    return _not_found(ks.evidence_trace(_run(run_id), skill_key), "evidence trace")


@industry_router.get("/review-queue")
def industry_review_queue(kind: str | None = None, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
                          run_id: str | None = None):
    return ks.industry_review_queue(_run(run_id), kind, limit, offset)
