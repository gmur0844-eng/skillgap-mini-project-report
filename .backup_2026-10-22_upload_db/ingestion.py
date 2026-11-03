"""
Ingestion trigger endpoints. Each wraps the same pipeline function the CLI
scripts use (app.pipelines.ingestion.*) — uploading a file here and running
the equivalent scripts/ingestion/*.py command are equivalent operations.
"""
import logging
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.config import get_settings
from app.core.errors import ApiError
from app.pipelines.ingestion.esco import ingest_esco_file
from app.pipelines.ingestion.onet import ingest_onet_files
from app.pipelines.ingestion.job_postings import ingest_job_postings_file, COLUMN_MAP_PRESETS
from app.pipelines.ingestion.curriculum import ingest_curriculum_document

router = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion"])


CHUNK = 1024 * 1024


def _save_upload_to_tmp(upload: UploadFile, allowed_extensions: list[str]) -> Path:
    """
    allowed_extensions is caller-specified per endpoint rather than a single
    global list — curriculum uploads must NOT accept .csv (no real per-column
    CSV parser exists for curricula; see app.pipelines.ingestion.curriculum),
    while job-postings/ESCO/O*NET genuinely parse delimited files.

    Safety: the client's file name is never used as a path (only its extension is read), the file is streamed in
    chunks and rejected as soon as it exceeds MAX_UPLOAD_SIZE_MB, and it lives in a private temporary directory that
    is removed after ingestion (_cleanup).
    """
    settings = get_settings()
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in allowed_extensions:
        raise ApiError(415, "UNSUPPORTED_FILE_TYPE", f"file type {suffix or '(none)'!r} is not accepted here",
                       {"allowed": allowed_extensions})
    limit = settings.max_upload_size_mb * 1024 * 1024
    tmp_dir = Path(tempfile.mkdtemp(prefix="skillgap_upload_"))
    # provenance keeps a sanitised form of the client's file name; it can never contain a path component
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(upload.filename or "upload").stem)[:100].lstrip(".") or "upload"
    dest = tmp_dir / f"{stem}{suffix}"
    written = 0
    with dest.open("wb") as f:
        while chunk := upload.file.read(CHUNK):
            written += len(chunk)
            if written > limit:
                f.close()
                _cleanup(dest)
                raise ApiError(413, "FILE_TOO_LARGE", f"file exceeds {settings.max_upload_size_mb} MB",
                               {"limit_mb": settings.max_upload_size_mb})
            f.write(chunk)
    if written == 0:
        _cleanup(dest)
        raise ApiError(400, "EMPTY_FILE", "the uploaded file is empty")
    return dest


def _cleanup(path):
    if path:
        shutil.rmtree(Path(path).parent, ignore_errors=True)


def _ingestion_failed(exc):
    logging.getLogger("skillgap.ingestion").error("ingestion failed: %s", type(exc).__name__)
    return ApiError(422, "INGESTION_FAILED", "the file could not be ingested; the ingestion run record (/api/v1/pipeline-runs) shows its status",
                    {"exception": type(exc).__name__})


@router.post("/jobs")
def trigger_job_postings_ingestion(
    file: UploadFile = File(...),
    dataset: str = Form("naukri"),
    source_name: str | None = Form(None),
    source_url: str | None = Form(None),
    licence_note: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """`dataset` names the COLUMN FORMAT of the CSV you supply (GET /api/v1/metadata/upload-formats); the application
    reads the uploaded file only and never connects to the platform the export came from."""
    if dataset not in COLUMN_MAP_PRESETS:
        raise HTTPException(400, f"Unknown dataset preset '{dataset}'. Options: {list(COLUMN_MAP_PRESETS.keys())}")
    path = _save_upload_to_tmp(file, allowed_extensions=[".csv"])
    try:
        result = ingest_job_postings_file(
            db, path, column_map=COLUMN_MAP_PRESETS[dataset], source_name=source_name or f"Uploaded file ({dataset} column format)",
            source_url=source_url,
        )
        result["provenance"] = {"file_format": dataset, "source_name": source_name, "source_url": source_url,
                                "licence_note": licence_note,
                                "licence_declared": bool((licence_note or "").strip())}
        if not result["provenance"]["licence_declared"] and result.get("outcome", {}).get("outcome") == "SUCCESSFUL_AND_USABLE":
            # usable content, but provenance is incomplete: it needs a person's decision before analysis
            result["outcome"] = {**result["outcome"], "outcome": "NEEDS_REVIEW", "review_status": "NEEDS_REVIEW",
                                 "usable_for_analysis": False,
                                 "headline": "Postings imported, but no licence or terms were stated — review required",
                                 "reasons": result["outcome"].get("reasons", []) + ["no licence / terms of use stated"],
                                 "next_action": "State the licence or terms of use of the file"}
        return result
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 -- converted to a structured error without internal details
        raise _ingestion_failed(exc) from exc
    finally:
        _cleanup(path)


@router.post("/curriculum/inspect")
def inspect_curriculum(file: UploadFile = File(...)):
    """
    Metadata suggestions read from the document's first pages (institution, programme, discipline, regulation,
    academic year, degree level), each with the page and line it was read from (services/metadata_inference.py).
    Nothing is stored and nothing is ingested: the suggestions only pre-fill the form for the person to check.
    """
    from app.services import evidence_metadata as em
    from app.services.metadata_inference import FRONT_PAGES, infer_metadata
    path = _save_upload_to_tmp(file, allowed_extensions=get_settings().allowed_curriculum_extensions_list)
    try:
        if path.suffix.lower() == ".pdf":
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages[:FRONT_PAGES]]
        else:
            pages = [path.read_text(encoding="utf-8", errors="replace")]
        known = [d["name"] for d in em.disciplines()]
        return {"evidence_state": "AVAILABLE", **infer_metadata(pages, known)}
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 -- an unreadable file yields no suggestions, never a crash
        logging.getLogger("skillgap.ingestion").warning("inspect failed: %s", type(exc).__name__)
        return {"evidence_state": "AVAILABLE", "suggestions": {}, "pages_read": 0,
                "note": "no suggestions: the document's first pages could not be read"}
    finally:
        _cleanup(path)


@router.post("/curriculum")
def trigger_curriculum_ingestion(
    file: UploadFile = File(...),
    institution: str | None = Form(None),
    programme: str | None = Form(None),
    curriculum_version_label: str | None = Form(None),
    document_role: str | None = Form(None),
    discipline: str | None = Form(None),
    specialization: str | None = Form(None),
    degree_level: str | None = Form(None),
    academic_year: str | None = Form(None),
    department: str | None = Form(None),
    programme_code: str | None = Form(None),
    source_url: str | None = Form(None),
    licence_note: str | None = Form(None),
    title: str | None = Form(None),
    publisher: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """
    Upload a curriculum (or a general reference document). `document_role` selects the metadata policy in
    data/metadata/document_roles.json; required fields are enforced per role (an institution-independent reference
    curriculum does not need an institution). Without `document_role` the legacy behaviour is kept (no policy), and
    the response lists which metadata is missing. The response carries `outcome`: one interpretation of execution,
    extraction, quality and review status, so no zero-content extraction can read as a usable curriculum.
    """
    from app.services import evidence_metadata as em
    values = {"institution": institution, "programme": programme, "discipline": discipline,
              "curriculum_version": curriculum_version_label,
              "academic_year": academic_year, "source_url": source_url, "licence_note": licence_note,
              "specialization": specialization, "degree_level": degree_level, "title": title, "publisher": publisher}
    if document_role is not None:
        document_role = document_role.strip().upper()
        missing = em.validate_metadata(document_role, values)
        if missing:
            raise ApiError(422, "METADATA_INCOMPLETE", f"{document_role}: required metadata missing: {', '.join(missing)}",
                           {"document_role": document_role, "missing": missing,
                            "policy": "GET /api/v1/metadata/document-roles"})
    policy = em.role_policy(document_role) if document_role else None
    path = _save_upload_to_tmp(file, allowed_extensions=get_settings().allowed_curriculum_extensions_list)
    try:
        if policy is not None and not policy.get("analysed_by_curriculum_pipeline", True):
            from app.pipelines.ingestion.outcome import reference_outcome
            from app.pipelines.ingestion.common import file_hash
            staged = _stage_upload(path, document_role, values, None)
            return {"status": "succeeded", "document_role": document_role, "raw_sha256": file_hash(path),
                    "upload_id": staged["upload_id"], "outcome": reference_outcome(), "metadata": _metadata_view(values, policy)}
        result = ingest_curriculum_document(
            db, path, institution_name=institution, programme_name=programme,
            curriculum_version_label=curriculum_version_label or "v1", source_url=source_url, department_name=department,
            discipline_name=discipline, programme_code=programme_code, degree_level=degree_level,
            academic_year=academic_year, specialization=specialization, document_role=document_role,
        )
        result["metadata"] = _metadata_view(values, policy)
        if result.get("status") == "succeeded":
            staged = _stage_upload(path, document_role, values, result)
            result["upload_id"] = staged["upload_id"]
        return result
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 -- converted to a structured error without internal details
        raise _ingestion_failed(exc) from exc
    finally:
        _cleanup(path)


def _metadata_view(values, policy):
    required = policy["required"] if policy else []
    recommended = policy["recommended"] if policy else ["institution", "programme", "discipline", "curriculum_version"]
    return {"values": {k: v for k, v in values.items() if v},
            "policy": policy["role"] if policy else None,
            "missing_recommended": [f for f in recommended if not str(values.get(f) or "").strip()],
            "missing_required": [f for f in required if not str(values.get(f) or "").strip()]}


def _stage_upload(path, role, values, result):
    """Keep a hash-addressed copy of an uploaded document plus its metadata and outcome, so the analysis job can add it
    to a derived source manifest (the project manifest is never edited by an upload)."""
    from app.services import analysis_jobs
    return analysis_jobs.stage_upload(path, role, values, (result or {}).get("outcome"),
                                      ingestion_run_id=(result or {}).get("analysis_run_id"))


@router.post("/esco")
def trigger_esco_ingestion(
    file: UploadFile = File(...),
    version: str = Form("unspecified"),
    db: Session = Depends(get_db),
):
    path = _save_upload_to_tmp(file, allowed_extensions=[".csv"])
    try:
        result = ingest_esco_file(db, path, version=version)
        return result
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 -- converted to a structured error without internal details
        raise _ingestion_failed(exc) from exc
    finally:
        _cleanup(path)


@router.post("/onet")
def trigger_onet_ingestion(
    occupations_file: UploadFile | None = File(None),
    technology_skills_file: UploadFile | None = File(None),
    version: str = Form("unspecified"),
    db: Session = Depends(get_db),
):
    if not occupations_file and not technology_skills_file:
        raise HTTPException(400, "Provide at least one of occupations_file or technology_skills_file.")
    occ_path = _save_upload_to_tmp(occupations_file, allowed_extensions=[".txt", ".csv"]) if occupations_file else None
    tech_path = _save_upload_to_tmp(technology_skills_file, allowed_extensions=[".txt", ".csv"]) if technology_skills_file else None
    try:
        result = ingest_onet_files(db, occ_path, tech_path, version=version)
        return result
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 -- converted to a structured error without internal details
        raise _ingestion_failed(exc) from exc
    finally:
        _cleanup(occ_path)
        _cleanup(tech_path)
