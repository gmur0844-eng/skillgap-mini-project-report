"""
Semantic relationship validation: the reviewer responses of a validation package (app.services.semantic_validation_service).

  GET  /api/v1/semantic-validation/packages                      packages, imported reviewers, label schema
  GET  /api/v1/semantic-validation/questions?package=            the 48 questions with their evidence (+ ai_reference)
  GET  /api/v1/semantic-validation/assessments?reviewer=&label=&status=&question_id=
  GET  /api/v1/semantic-validation/assessments/{question_id}/{reviewer_id}
  GET  /api/v1/semantic-validation/missing?reviewers=R02,R03      questions not COMPLETED per reviewer
  GET  /api/v1/semantic-validation/compare?a=R02&b=R03&outcome=   per question, with metrics
  GET  /api/v1/semantic-validation/metrics?a=R02&b=R03            metrics, each with its definition
  GET  /api/v1/semantic-validation/export.csv?reviewers=R02,R03   verbatim records with their source location
  POST /api/v1/semantic-validation/import                         form responses (.xlsx/.csv) + how they were produced
`package` defaults to the only (first) package. Errors use the project's structured shape {code, message}.
"""
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse

from app.core.config import get_settings
from app.services import semantic_validation_service as svc

router = APIRouter(prefix="/api/v1/semantic-validation", tags=["semantic validation"])
PACKAGE = Query(None, max_length=100, description="<discipline>/<version>; default: the first package")


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.InvalidRequest as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEST", "message": str(exc)}) from exc
    except svc.PackageNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc


def _list(value):
    return [x.strip() for x in value.split(",") if x.strip()] if value else None


@router.get("/packages")
def packages():
    return _call(svc.packages)


@router.get("/questions")
def questions(package: str | None = PACKAGE):
    return _call(svc.questions, package)


@router.get("/assessments")
def assessments(package: str | None = PACKAGE, reviewer: str | None = Query(None, max_length=40),
                label: str | None = Query(None, max_length=40), status: str | None = Query(None, max_length=20),
                question_id: str | None = Query(None, max_length=40)):
    return _call(svc.assessments, package, reviewer, label, status, question_id)


@router.get("/assessments/{question_id}/{reviewer_id}")
def assessment(question_id: str, reviewer_id: str, package: str | None = PACKAGE):
    return _call(svc.assessment, package, question_id, reviewer_id)


@router.get("/missing")
def missing(package: str | None = PACKAGE, reviewers: str = Query("R02,R03", max_length=200)):
    return _call(svc.missing, package, _list(reviewers))


@router.get("/compare")
def compare(package: str | None = PACKAGE, a: str = Query("R02", max_length=40), b: str = Query("R03", max_length=40),
            outcome: str | None = Query(None, max_length=20)):
    return _call(svc.compare, package, a, b, outcome)


@router.get("/metrics")
def metrics(package: str | None = PACKAGE, a: str = Query("R02", max_length=40), b: str = Query("R03", max_length=40)):
    return _call(svc.metrics, package, a, b)


@router.get("/export.csv", response_class=PlainTextResponse)
def export(package: str | None = PACKAGE, reviewers: str | None = Query(None, max_length=200)):
    body = _call(svc.export_csv, package, _list(reviewers))
    return PlainTextResponse(body, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="semantic_validation_responses.csv"'})


@router.post("/import")
async def import_responses(file: UploadFile = File(...),
                           source: str = Form(..., description="HUMAN_UNASSISTED, HUMAN_AI_ASSISTED or NOT_STATED"),
                           reviewers: str | None = Form(None), note: str | None = Form(None, max_length=2000),
                           package: str | None = Form(None)):
    limit = get_settings().max_upload_size_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status_code=413, detail={"code": "FILE_TOO_LARGE",
                                                     "message": f"the file is larger than {limit // (1024 * 1024)} MB"})
    out = _call(svc.import_upload, package, file.filename, content, source, _list(reviewers), note)
    if "CONFLICT" in out["stored"].values():
        raise HTTPException(status_code=409, detail={"code": "RESPONSES_EXIST", "message":
                            "these reviewers already have different stored responses; nothing was overwritten",
                            "details": out["stored"]})
    return out
