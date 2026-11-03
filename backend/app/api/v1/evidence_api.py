"""
Evidence workflow API: Add evidence -> Validate -> Extract -> Review -> Publish -> Analyse.

Read-only metadata (mounted in the full app and in the file-only Knowledge API):
  GET  /api/v1/metadata/document-roles      role policy (required / recommended metadata per document role)
  GET  /api/v1/metadata/disciplines         disciplines seen so far (a typing aid; any discipline is accepted)
  GET  /api/v1/metadata/sources             Source Registry: type, scope, access method, licence, configuration
  GET  /api/v1/metadata/upload-formats      job-posting file formats (file layouts, never platform access)
  GET  /api/v1/settings/appearance         the web app's design (v1 | v2), mode (dark | light) and finalised design
  POST /api/v1/settings/appearance         {"version"?, "theme"?, "finalise"?: true, "clear_final"?: true}
  GET  /api/v1/metadata/discipline-profiles discipline profiles with the support each actually has, computed from the
                                            evidence present (industry postings, reference and peer curricula)
Analysis jobs (full app only; they start the knowledge pipeline):
  GET  /api/v1/uploads/{upload_id}          a staged upload with its metadata and ingestion outcome
  GET  /api/v1/analysis/comparison-targets?upload_id=|discipline=   peer curricula available for comparison, with
                                            whether each is comparable with the upload's (or the typed) discipline (a client chooses; nothing
                                            is substituted)
  POST /api/v1/analysis/jobs                {"upload_id", "reviewed_by"?, "options"?: {"peers": bool, "industry": bool,
                                            "peer_ids"?: [doc_id]}} (a repeated submission while the same job runs
                                            returns that job, with duplicate_submission: true)
                                            -> a new analysis run in the background (options leave optional
                                            capabilities out: a curriculum-only analysis of a new institution)
  GET  /api/v1/analysis/run-comparison?a=&b=   what differs between two stored runs: curriculum, industry evidence
                                            or method (b defaults to the published run)
  GET  /api/v1/analysis/jobs                recent jobs
  GET  /api/v1/analysis/jobs/active         the job running now (null when none): reconnect after a page reload
  GET  /api/v1/analysis/jobs/{job_id}       ANALYSIS_PENDING | ANALYSIS_READY (run_id) | ANALYSIS_FAILED | NEEDS_REVIEW,
                                            with live "phases" (the pipeline's real stage events) and "current"
  GET  /api/v1/analysis/jobs/{job_id}/events   Server-Sent Events: the full job record on connect and on every
                                            progress change, until the job ends. Reconnecting simply resumes: each
                                            event carries the complete current state (id = progress_seq).
  POST /api/v1/analysis/jobs/{job_id}/retry start the same upload again with the same options and reviewer
"""
import asyncio
import json

from fastapi import APIRouter, Body, Query
from fastapi.responses import StreamingResponse

from app.core.errors import ApiError
from app.services import analysis_jobs, evidence_metadata

metadata_router = APIRouter(prefix="/api/v1/metadata", tags=["evidence"])
settings_router = APIRouter(prefix="/api/v1/settings", tags=["settings"])
analysis_router = APIRouter(prefix="/api/v1", tags=["evidence"])


@metadata_router.get("/document-roles")
def document_roles():
    return {"evidence_state": "AVAILABLE", **evidence_metadata.document_roles()}


@metadata_router.get("/disciplines")
def disciplines():
    items = evidence_metadata.disciplines()
    return {"evidence_state": "AVAILABLE", "items": items, "total": len(items),
            "note": "suggestions only: any discipline is accepted and new disciplines need no code change"}


@metadata_router.get("/sources")
def sources():
    return {"evidence_state": "AVAILABLE", **evidence_metadata.sources()}


@metadata_router.get("/upload-formats")
def upload_formats():
    return {"evidence_state": "AVAILABLE", **evidence_metadata.upload_formats()}


@settings_router.get("/appearance")
def get_appearance():
    from app.services import ui_preferences
    return {"evidence_state": "AVAILABLE", **ui_preferences.read()}


@settings_router.post("/appearance")
def set_appearance(payload: dict = Body(...)):
    from app.services import ui_preferences
    rec, err = ui_preferences.update(payload)
    if err:
        raise ApiError(422, "INVALID_APPEARANCE", err)
    return {"evidence_state": "AVAILABLE", **rec}


@metadata_router.get("/discipline-profiles")
def discipline_profile_summary():
    from app.knowledge_engine import discipline_profiles
    base = analysis_jobs._read(analysis_jobs.MANIFEST, {}) or {}
    # registered references of other disciplines count as available: an upload of that discipline is compared with them
    with_refs = {**base, "documents": list(base.get("documents") or []) + analysis_jobs.discipline_references()}
    return {"evidence_state": "AVAILABLE", **discipline_profiles.summary(with_refs)}


def _public(job, technical=False):
    if job is None:
        return None
    return {k: v for k, v in job.items() if technical or k != "error_detail"}


@analysis_router.get("/uploads/{upload_id}")
def get_upload(upload_id: str):
    up = analysis_jobs.upload(upload_id)
    if up is None:
        raise ApiError(404, "NOT_FOUND", f"no staged upload {upload_id!r}")
    return {"evidence_state": "AVAILABLE", **up}


@analysis_router.get("/analysis/comparison-targets")
def comparison_targets(upload_id: str | None = None, discipline: str | None = None):
    if upload_id and analysis_jobs.upload(upload_id) is None:
        raise ApiError(404, "NOT_FOUND", f"no staged upload {upload_id!r}")
    return {"evidence_state": "AVAILABLE", **analysis_jobs.comparison_targets(upload_id, discipline=discipline)}


@analysis_router.get("/analysis/run-comparison")
def run_comparison(a: str, b: str | None = None):
    from app.services import run_comparison as rc
    if not b:
        b = str((analysis_jobs._read(analysis_jobs.GOLD / "latest_run.json", {}) or {}).get("run_id") or "")
    result, err = rc.compare(a, b, gold=analysis_jobs.GOLD)
    if err:
        raise ApiError(404, "NOT_FOUND", f"no stored analysis run {err[1]!r}")
    return {"evidence_state": "AVAILABLE", **result}


@analysis_router.post("/analysis/jobs")
def start_analysis(payload: dict = Body(...)):
    upload_id = str(payload.get("upload_id") or "")
    options = payload.get("options") if isinstance(payload.get("options"), dict) else None
    job, err = analysis_jobs.start_job(upload_id, reviewed_by=payload.get("reviewed_by"), options=options)
    if err == "UPLOAD_NOT_FOUND":
        raise ApiError(404, "NOT_FOUND", f"no staged upload {upload_id!r}")
    if err == "INVALID_PEER_SELECTION":
        problems = analysis_jobs.peer_selection_problems(upload_id, analysis_jobs.normalise_options(options).get("peer_ids"))
        raise ApiError(422, "INVALID_PEER_SELECTION", "the selected peers cannot be compared with this curriculum: "
                       + "; ".join(f"{d}: {why}" for d, why in problems)
                       + ". Choose from the comparison targets; no other peer is used in their place.")
    if err == "NOT_ANALYSABLE":
        raise ApiError(409, "NOT_ANALYSABLE", "this upload has no usable curriculum content; review the extraction first")
    if err == "REVIEW_REQUIRED":
        raise ApiError(409, "REVIEW_REQUIRED", "the extraction needs review; start the analysis with reviewed_by to "
                                               "record who accepted it")
    if err == "JOB_RUNNING":
        raise ApiError(409, "JOB_RUNNING", "another analysis is running; try again when it has finished")
    return {"evidence_state": "AVAILABLE", **_public(job)}


@analysis_router.get("/analysis/jobs")
def list_jobs(limit: int = Query(20, ge=1, le=100)):
    items = [_public(j) for j in analysis_jobs.jobs(limit) if j]
    return {"evidence_state": "AVAILABLE", "items": items, "total": len(items)}


@analysis_router.get("/analysis/jobs/active")
def get_active_job():
    job = analysis_jobs.active_job()
    return {"evidence_state": "AVAILABLE", "job": _public(job)}


@analysis_router.get("/analysis/jobs/{job_id}")
def get_job(job_id: str, technical: bool = False):
    job = analysis_jobs.job(job_id)
    if job is None:
        raise ApiError(404, "NOT_FOUND", f"no analysis job {job_id!r}")
    return {"evidence_state": "AVAILABLE", **_public(job, technical)}


@analysis_router.post("/analysis/jobs/{job_id}/retry")
def retry_analysis(job_id: str):
    job, err = analysis_jobs.retry_job(job_id)
    if err == "JOB_NOT_FOUND":
        raise ApiError(404, "NOT_FOUND", f"no analysis job {job_id!r}")
    if err == "UPLOAD_NOT_FOUND":
        raise ApiError(404, "NOT_FOUND", "the job's upload no longer exists; upload the document again")
    if err == "JOB_RUNNING":
        raise ApiError(409, "JOB_RUNNING", "an analysis is running; try again when it has finished")
    if err in ("NOT_ANALYSABLE", "REVIEW_REQUIRED"):
        raise ApiError(409, err, "this upload cannot be analysed as it stands; review the extraction first")
    return {"evidence_state": "AVAILABLE", **_public(job)}


EVENT_POLL_S = 0.5
EVENT_HEARTBEAT_S = 15.0
FINAL = (analysis_jobs.READY, analysis_jobs.FAILED, analysis_jobs.REVIEW)


def _sse(job):
    return f"id: {job.get('progress_seq', 0)}\nevent: job\ndata: {json.dumps(_public(job), ensure_ascii=False)}\n\n"


@analysis_router.get("/analysis/jobs/{job_id}/events")
async def job_events(job_id: str):
    first = analysis_jobs.job(job_id)
    if first is None:
        raise ApiError(404, "NOT_FOUND", f"no analysis job {job_id!r}")

    async def stream():
        job, last_key, quiet = first, None, 0.0
        while True:
            key = (job.get("progress_seq"), job.get("status"))
            if key != last_key:
                last_key, quiet = key, 0.0
                yield _sse(job)
                if job.get("status") in FINAL:
                    return
            elif quiet >= EVENT_HEARTBEAT_S:
                quiet = 0.0
                yield ": keep-alive\n\n"
            await asyncio.sleep(EVENT_POLL_S)
            quiet += EVENT_POLL_S
            job = analysis_jobs.job(job_id) or job

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
