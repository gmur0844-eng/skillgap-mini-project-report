"""
/live   the process answers (always 200 while the server runs)
/ready  200 when the service can answer with data (GOLD run present, and the database when the app needs one);
        503 with the reasons otherwise
/health every component separately: API, DATABASE, MODEL, SEMANTIC (safe mode), DATA, PIPELINE
The app sets app.state.db_check (callable or None) and app.state.db_required.
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core import health as h
from app.knowledge_engine.config import load_config

router = APIRouter(tags=["health"])


def report(request: Request, probe_model=True):
    st = request.app.state
    check = getattr(st, "db_check", None)
    latest, _ = h.latest_run_dir()
    bound = (lambda: check(latest.name if latest else None)) if check else None
    return h.health_report(cfg=load_config(), db_check=bound, db_required=getattr(st, "db_required", False),
                           probe_model=probe_model)


@router.get("/live")
def live():
    return {"status": "ALIVE"}


@router.get("/ready")
def ready(request: Request):
    r = report(request, probe_model=False)
    body = {"status": r["status"], "not_ready_reasons": r["not_ready_reasons"],
            "components": {k: v["status"] for k, v in r["components"].items()}}
    return JSONResponse(body, status_code=200 if r["ready"] else 503)


@router.get("/health")
def health(request: Request):
    return report(request)
