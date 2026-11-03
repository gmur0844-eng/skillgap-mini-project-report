"""
Engine-2.0 API: /api/v1/semantic/*, /api/v1/intelligence/*, and additions to /api/v1/curriculum/* and
/api/v1/industry/*. Read-only views of GOLD; every response carries `scope` and `evidence_state`.
"""
from fastapi import APIRouter, HTTPException, Query, Request

from app.services import intelligence_service as svc
from app.services import knowledge_service as ks

semantic_router = APIRouter(prefix="/api/v1/semantic", tags=["semantic"])
intelligence_router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])
curriculum_v2_router = APIRouter(prefix="/api/v1/curriculum", tags=["curriculum-knowledge"])
industry_v2_router = APIRouter(prefix="/api/v1/industry", tags=["industry-knowledge"])
agents_router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _ir(run_id):
    try:
        return svc.load(run_id)
    except ks.InvalidRunId as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_RUN_ID", "message": str(exc)}) from exc
    except ks.RunNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": ks.not_found_code(exc), "message": str(exc)}) from exc


@semantic_router.get("/concepts")
def semantic_concepts(q: str | None = None, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), run_id: str | None = None):
    return svc.semantic_concepts(_ir(run_id), q, limit, offset)


@semantic_router.get("/relationships")
def semantic_relationships(relationship: str | None = None, limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
                           run_id: str | None = None):
    return svc.semantic_relationships(_ir(run_id), relationship, limit, offset)


@semantic_router.get("/decisions")
def semantic_decisions(kind: str | None = None, state: str | None = None, limit: int = Query(100, ge=1, le=1000),
                       offset: int = Query(0, ge=0), run_id: str | None = None):
    return svc.semantic_decisions(_ir(run_id), kind, state, limit, offset)


@semantic_router.get("/evidence")
def semantic_evidence(node_id: str, run_id: str | None = None):
    return svc.semantic_evidence(_ir(run_id), node_id)


@semantic_router.get("/contradictions")
def semantic_contradictions(run_id: str | None = None):
    return svc.semantic_contradictions(_ir(run_id))


@semantic_router.get("/review")
def semantic_review(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), run_id: str | None = None):
    return svc.semantic_review(_ir(run_id), limit, offset)


@curriculum_v2_router.get("/topic-hierarchy")
def topic_hierarchy(course_uid: str | None = None, limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
                    run_id: str | None = None):
    return svc.curriculum_topic_hierarchy(_ir(run_id), course_uid, limit, offset)


@curriculum_v2_router.get("/coverage")
def coverage(role: str | None = None, level: str | None = None, limit: int = Query(200, ge=1, le=2000),
             offset: int = Query(0, ge=0), run_id: str | None = None):
    return svc.curriculum_coverage(_ir(run_id), role, level, limit, offset)


@curriculum_v2_router.get("/drift")
def drift(category: str | None = None, limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0), run_id: str | None = None):
    return svc.curriculum_drift(_ir(run_id), category, limit, offset)


@curriculum_v2_router.get("/course-drift")
def course_drift(status: str | None = None, limit: int = Query(200, le=1000), offset: int = 0, run_id: str | None = None):
    return svc.curriculum_course_drift(_ir(run_id), status, limit, offset)


@curriculum_v2_router.get("/programme-comparison")
def programme_comparison(level: str = Query("course", pattern="^(course|concept)$"), status: str | None = None,
                         limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0), run_id: str | None = None):
    return svc.curriculum_programme_comparison(_ir(run_id), level, status, limit, offset)


@curriculum_v2_router.get("/benchmark")
def benchmark(run_id: str | None = None):
    return svc.curriculum_benchmark(_ir(run_id))


@industry_v2_router.get("/occupations")
def occupations(status: str | None = None, limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0), run_id: str | None = None):
    return svc.industry_occupations(_ir(run_id), status, limit, offset)


@industry_v2_router.get("/trends")
def trends(run_id: str | None = None):
    return svc.industry_trends(_ir(run_id))


@industry_v2_router.get("/skill-taxonomy")
def skill_taxonomy(limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0), run_id: str | None = None):
    return svc.industry_skill_taxonomy(_ir(run_id), limit, offset)


@intelligence_router.get("/gaps")
def gaps(classification: str | None = None, limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
         run_id: str | None = None):
    return svc.gaps(_ir(run_id), classification, limit, offset)


@intelligence_router.get("/recommendations")
def recommendations(run_id: str | None = None):
    return svc.recommendations(_ir(run_id))


@intelligence_router.get("/why-not")
def why_not(skill_key: str, run_id: str | None = None):
    return svc.why_not(_ir(run_id), skill_key)


@intelligence_router.get("/evidence-trace")
def evidence_trace(skill_key: str, run_id: str | None = None):
    return svc.evidence_trace(_ir(run_id), skill_key)


@intelligence_router.get("/lineage")
def lineage(run_id: str | None = None):
    return svc.lineage(_ir(run_id))


@intelligence_router.get("/evidence-status")
def evidence_status(run_id: str | None = None):
    return svc.evidence_status(_ir(run_id))


@intelligence_router.get("/system-health")
def system_health(request: Request, run_id: str | None = None):
    from app.api.v1.health_api import report
    return {**svc.system_health(_ir(run_id)), "components": report(request)["components"]}


# ---------------- /agents: the five analysis agents and the experimental gap review ----------------
@agents_router.get("")
def agents(run_id: str | None = None):
    from app.services import agents_service
    return agents_service.agents(_ir(run_id).run)


@agents_router.get("/gap-review")
def gap_review(state: str | None = None, all_skills: bool = False, limit: int = Query(200, ge=1, le=2000),
               offset: int = Query(0, ge=0), run_id: str | None = None):
    from app.services import agents_service
    return agents_service.gap_review(_ir(run_id).run, state, not all_skills, limit, offset)
