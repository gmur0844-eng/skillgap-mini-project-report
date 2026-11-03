"""
Improvement-release API (read-only, backward compatible: new paths only, existing responses unchanged).

  /api/v1/overview                         KPI snapshot, data scope, statuses (GOLD only)
  /api/v1/search?q=&types=                 typed search (COURSE, TOPIC, CONCEPT, SKILL, ESCO, OCCUPATION, COMPANY, JOB)
  /api/v1/peers/status|benchmark|differences|relations|skills
  /api/v1/industry/intelligence|temporal-trends|dimensions|clusters
  /api/v1/occupations/resolution|analysis
  /api/v1/evaluation/semantic              independent semantic evaluation status (PENDING until independent labels)
  /api/v1/lineage/recompute                recomputation lineage of a run
Every response carries evidence_state; errors use the structured error shape of app.core.errors.
"""
from fastapi import APIRouter, HTTPException, Query

from app.services import improvement_service as svc
from app.services import knowledge_service as ks

router = APIRouter(prefix="/api/v1", tags=["improvement"])


def _run(run_id):
    try:
        return ks.load_run(run_id)
    except ks.InvalidRunId as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_RUN_ID", "message": str(exc)}) from exc
    except ks.RunNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": ks.not_found_code(exc), "message": str(exc)}) from exc


@router.get("/overview")
def overview(run_id: str | None = None):
    return svc.overview(_run(run_id))


@router.get("/readiness")
def readiness(run_id: str | None = None):
    """Is the analysis usable, what evidence supports it, what is limited, is AI advisory, can results be traced."""
    return svc.readiness(_run(run_id))


@router.get("/search")
def search(q: str = Query("", max_length=120), types: str | None = Query(None, max_length=120),
           limit: int = Query(30, ge=1, le=200), run_id: str | None = None):
    wanted = [t.strip() for t in types.split(",") if t.strip()] if types else None
    unknown = [t for t in (wanted or []) if t.upper() not in svc.SEARCH_TYPES]
    if unknown:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR",
                                                     "message": f"unknown search type(s) {unknown}; allowed {list(svc.SEARCH_TYPES)}"})
    return svc.search(_run(run_id), q, wanted, limit)


@router.get("/peers/status")
def peers_status(run_id: str | None = None):
    return svc.peer_status(_run(run_id))


@router.get("/peers/benchmark")
def peers_benchmark(comparison_doc_id: str | None = Query(None, max_length=120), run_id: str | None = None):
    return svc.peer_benchmark(_run(run_id), comparison_doc_id)


@router.get("/peers/differences")
def peers_differences(comparison_doc_id: str = Query(..., max_length=120), kind: str | None = Query(None, max_length=80),
                      limit: int = Query(40, ge=1, le=500), offset: int = Query(0, ge=0), run_id: str | None = None):
    return svc.peer_differences(_run(run_id), comparison_doc_id, kind, limit, offset)


@router.get("/peers/relations")
def peers_relations(comparison_doc_id: str | None = Query(None, max_length=120), relationship: str | None = Query(None, max_length=40),
                    evidence_state: str | None = Query(None, max_length=40), q: str | None = Query(None, max_length=120),
                    limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), run_id: str | None = None):
    return svc.peer_relations(_run(run_id), comparison_doc_id, relationship, evidence_state, q, limit, offset)


@router.get("/peers/skills")
def peers_skills(comparison_doc_id: str = Query(..., max_length=120), difference: str | None = Query(None, max_length=40),
                 limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0), run_id: str | None = None):
    return svc.peer_skills(_run(run_id), comparison_doc_id, difference, limit, offset)


@router.get("/industry/intelligence")
def industry_intelligence(run_id: str | None = None):
    return svc.industry_intelligence(_run(run_id))


@router.get("/industry/temporal-trends")
def industry_trends(state: str | None = Query(None, max_length=40), population_id: str | None = Query(None, max_length=120),
                    limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0), run_id: str | None = None):
    if state and state not in svc.TREND_STATES:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR",
                                                     "message": f"state must be one of {list(svc.TREND_STATES)}"})
    return svc.industry_trends(_run(run_id), state, population_id, limit, offset)


@router.get("/industry/dimensions")
def industry_dimensions(dimension: str | None = Query(None, max_length=40), run_id: str | None = None):
    return svc.industry_dimensions(_run(run_id), dimension)


@router.get("/industry/clusters")
def industry_clusters(run_id: str | None = None):
    return svc.industry_clusters(_run(run_id))


@router.get("/occupations/resolution")
def occupations_resolution(state: str | None = Query(None, max_length=40), limit: int = Query(100, ge=1, le=1000),
                           offset: int = Query(0, ge=0), run_id: str | None = None):
    return svc.occupation_resolution(_run(run_id), state, limit, offset)


@router.get("/occupations/analysis")
def occupations_analysis(level: str = Query("occupation", pattern="^(occupation|occupation_group)$"), run_id: str | None = None):
    return svc.occupation_analysis(_run(run_id), level)


@router.get("/evaluation/semantic")
def evaluation_semantic(include_cases: bool = False):
    return svc.semantic_evaluation(include_cases)


@router.get("/lineage/recompute")
def lineage(run_id: str | None = None):
    return svc.run_lineage(_run(run_id))
