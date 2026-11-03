"""
Core curriculum document ingestion logic (DB-dependent).

Uses pdfplumber for PDF text extraction. The original phase-1 spec suggested
PyMuPDF; PyMuPDF is not installable in this environment, and pdfplumber is a
functionally equivalent, actively maintained alternative already used
elsewhere in this codebase's toolchain — this substitution is noted here
rather than silently made.

Flow: RAW file -> per-page text extraction -> VALIDATION (did we get usable
text at all?) -> heuristic STRUCTURING (course/module/topic/outcome) ->
persistence as Institution/Programme/CurriculumVersion/Document/Course/Module/
CurriculumTopic, all linked back to a DataSource and an AnalysisRun.

Low-confidence extractions are flagged (Document.flagged_for_review = 1)
instead of silently trusted, per spec.
"""
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.curriculum import (
    Institution,
    Discipline,
    Department,
    Programme,
    CurriculumVersion,
    Document,
    Course,
    Module,
    CurriculumTopic,
    CourseLearningOutcome,
)
from app.models.analysis import AnalysisRun
from app.models.data_source import DataQualityMetric
from app.pipelines.preprocessing.curriculum_structuring import (
    structure_curriculum_pages,
    extraction_confidence,
    resolve_extraction_method,
)
from app.pipelines.preprocessing.validation import validate_curriculum_document
from app.pipelines.preprocessing.artifact_writer import write_raw_copy, write_jsonl_records
from app.pipelines.ingestion.common import file_hash, get_or_create_data_source
from app.pipelines.ingestion.outcome import curriculum_outcome
from app.analytics.data_quality import compute_curriculum_quality_metrics, metrics_to_rows

LOW_CONFIDENCE_THRESHOLD = 0.3  # below this fraction of pages contributing structure, flag for manual review


def _page_text(page) -> str:
    return page.extract_text() or ""


def _extract_pages_from_pdf(path: Path) -> list[str]:
    # pages are read on several cores (identical output; see preprocessing/parallel_pages.py)
    from app.pipelines.preprocessing.parallel_pages import map_pages
    return map_pages(path, "app.pipelines.ingestion.curriculum:_page_text")


def _extract_pages_from_txt(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [text]  # a plain text file is treated as one "page"


def ingest_curriculum_document(
    session: Session,
    file_path: Path,
    institution_name: str | None,
    programme_name: str | None,
    curriculum_version_label: str = "v1",
    source_url: str | None = None,
    department_name: str | None = None,
    discipline_name: str | None = None,
    programme_code: str | None = None,
    degree_level: str | None = None,
    academic_year: str | None = None,
    specialization: str | None = None,
    document_role: str | None = None,
) -> dict:
    """
    Generalized for ANY engineering discipline/programme (spec: "the same
    pipeline must ingest CBIT AI&DS, CBIT CSE, CBIT ECE, ... and curricula
    from other universities" -- there is no branch-specific logic here,
    every field is caller-supplied data). department_name/discipline_name/
    programme_code/degree_level/academic_year are all optional and
    additive: omitting them preserves the exact prior behavior (Unknown
    Institution/Programme, NULL degree/code, NULL effective_period).
    """
    run = AnalysisRun(
        run_type="ingestion",
        dataset_name="curriculum",
        status="running",
        started_at=datetime.utcnow(),
        pipeline_version="0.1.0",
    )
    session.add(run)
    session.flush()

    try:
        # --- RAW: preserve the exact original file, run-scoped, never overwritten ---
        raw_artifact_path = write_raw_copy("curricula", run.id, file_path)

        suffix = file_path.suffix.lower()
        extraction_method = resolve_extraction_method(suffix)  # raises ValueError for unsupported types, incl. .csv
        if extraction_method == "pdfplumber":
            pages = _extract_pages_from_pdf(file_path)
        else:
            pages = _extract_pages_from_txt(file_path)

        total_text_len = sum(len(p) for p in pages)
        validation = validate_curriculum_document(str(file_path), len(pages), total_text_len)

        source, _source_reused = get_or_create_data_source(
            session,
            source_name=f"University curriculum document: {file_path.name}",
            source_type="curriculum",
            file_hash_value=file_hash(file_path),
            source_url=source_url,
            institution=institution_name,
            programme=programme_name,
        )
        run.source_id = source.id

        # --- BRONZE: validated, standardized per-page records (pre-structuring) ---
        bronze_artifact_path = write_jsonl_records(
            "bronze",
            "curricula",
            run.id,
            [
                {
                    "page_number": i + 1,
                    "text_length": len(page_text or ""),
                    "extraction_method": extraction_method,
                }
                for i, page_text in enumerate(pages)
            ],
        )

        if not validation.is_valid:
            run.status = "failed"
            run.error_log = f"{validation.reason}: {validation.detail}"
            run.finished_at = datetime.utcnow()
            session.commit()
            failed = {
                "analysis_run_id": run.id,
                "source_id": source.id,
                "status": "failed",
                "reason": validation.reason,
                "detail": validation.detail,
                "raw_artifact_path": str(raw_artifact_path),
                "bronze_artifact_path": str(bronze_artifact_path),
                "document_role": document_role,
            }
            failed["outcome"] = curriculum_outcome(failed, LOW_CONFIDENCE_THRESHOLD)
            return failed

        structure = structure_curriculum_pages(pages)
        confidence = extraction_confidence(structure, len(pages))
        flagged = confidence < LOW_CONFIDENCE_THRESHOLD or structure.is_empty

        institution = _get_or_create_institution(session, institution_name)
        department = _get_or_create_department(session, institution, department_name, discipline_name)
        programme = _get_or_create_programme(session, institution, programme_name, department, programme_code, degree_level)

        document = Document(
            file_name=file_path.name,
            file_type=suffix.lstrip("."),
            raw_path=str(file_path),
            page_count=len(pages),
            extraction_method=extraction_method,
            extraction_confidence=confidence,
            flagged_for_review=1 if flagged else 0,
            document_role=document_role,
            source_id=source.id,
        )
        session.add(document)
        session.flush()

        curriculum_version = (
            session.query(CurriculumVersion)
            .filter(CurriculumVersion.programme_id == programme.id, CurriculumVersion.version_label == curriculum_version_label)
            .one_or_none()
        )
        if curriculum_version is None:
            curriculum_version = CurriculumVersion(
                programme_id=programme.id,
                version_label=curriculum_version_label,
                effective_period=academic_year,
                document_id=document.id,
                source_id=source.id,
            )
            session.add(curriculum_version)
            session.flush()
        else:
            # Re-ingestion of the SAME (programme, version_label): this is the
            # same curriculum version, not a new one -- point it at the
            # latest document/source rather than creating a duplicate row.
            # NOTE (documented limitation): this does not yet deduplicate the
            # Course/Module/Topic rows a re-ingestion would create under this
            # version -- full course-level re-ingestion idempotency is a
            # separate concern from version identity and is not fixed here.
            curriculum_version.document_id = document.id
            curriculum_version.source_id = source.id
            if academic_year:
                curriculum_version.effective_period = academic_year

        # Build Course -> Module -> Topic tree from the flat structure lists.
        course_by_code: dict[str, Course] = {}
        for extracted in structure.courses:
            code = extracted.course_code or f"UNKNOWN-{extracted.page_number}"
            if code not in course_by_code:
                course = Course(
                    programme_id=programme.id,
                    curriculum_version_id=curriculum_version.id,
                    course_code=extracted.course_code,
                    name=extracted.course_name or "Unknown (not reliably extracted)",
                )
                session.add(course)
                session.flush()
                course_by_code[code] = course

        module_by_key: dict[tuple, Module] = {}
        for extracted in structure.modules:
            code = extracted.course_code or "UNASSIGNED"
            course = course_by_code.get(code)
            if course is None:
                # A module was found before any course code on the page — attach
                # to a placeholder course rather than silently dropping it.
                course = course_by_code.setdefault(
                    code,
                    Course(
                        programme_id=programme.id,
                        curriculum_version_id=curriculum_version.id,
                        course_code=None,
                        name="Unassigned (module found without preceding course code)",
                    ),
                )
                session.add(course)
                session.flush()
            key = (code, extracted.heading_label)
            if key not in module_by_key:
                module = Module(course_id=course.id, name=f"{extracted.heading_label}: {extracted.title or ''}".strip(": "))
                session.add(module)
                session.flush()
                module_by_key[key] = module

        # Attach topics to their module using the EXACT (course_code, heading_label)
        # key -- not heading_label alone. PHASE-1 HARDENING FIX: the previous version
        # scanned module_by_key.items() and overwrote `module` on every label match,
        # so with two courses that both have a "Unit 1", topics ended up attached to
        # whichever course's "Unit 1" was iterated last, silently merging Course A's
        # and Course B's topics. A dict lookup on the same composite key used to
        # build module_by_key makes the collision structurally impossible.
        for topic in structure.topics:
            code = topic.course_code or "UNASSIGNED"
            module = module_by_key.get((code, topic.module_heading_label))
            if module is None:
                continue  # cannot attribute topic to any module -> do not fabricate a home for it
            session.add(
                CurriculumTopic(
                    module_id=module.id,
                    topic_text=topic.topic_text,
                    source_page=topic.page_number,
                    extraction_confidence=confidence,
                )
            )

        # Persist learning outcomes (previously extracted by curriculum_structuring
        # but never written to the database -- Phase-1 hardening item E). Attributed
        # to the course via the same course_by_code map used for courses/modules, so
        # an outcome under Course A never lands on Course B's row.
        outcomes_persisted = 0
        for outcome in structure.outcomes:
            code = outcome.course_code or "UNASSIGNED"
            course = course_by_code.get(code)
            if course is None:
                continue  # cannot attribute outcome to any course -> do not fabricate a home for it
            session.add(
                CourseLearningOutcome(
                    course_id=course.id,
                    outcome_label=outcome.label,
                    outcome_text=outcome.text,
                    source_page=outcome.page_number,
                    extraction_confidence=confidence,
                )
            )
            outcomes_persisted += 1

        # --- SILVER: cleaned + structured records (post course/module/topic/outcome attribution) ---
        silver_artifact_path = write_jsonl_records(
            "silver",
            "curricula",
            run.id,
            [
                {
                    "course_code": c.course_code,
                    "course_name": c.name,
                    "modules": [
                        {
                            "name": m.name,
                            "topics": [
                                t.topic_text
                                for t in structure.topics
                                if (t.course_code or "UNASSIGNED") == code
                                and module_by_key.get((code, t.module_heading_label)) is m
                            ],
                        }
                        for (mcode, _label), m in module_by_key.items()
                        if mcode == code
                    ],
                    "outcomes": [o.text for o in structure.outcomes if (o.course_code or "UNASSIGNED") == code],
                }
                for code, c in course_by_code.items()
            ],
        )

        quality_metrics = compute_curriculum_quality_metrics(
            [
                {
                    "page_count": len(pages),
                    "extraction_confidence": confidence,
                    "flagged_for_review": bool(flagged),
                    "courses_found": structure.courses_found,
                }
            ]
        )
        for row_dict in metrics_to_rows(quality_metrics, run.id, source.id):
            session.add(DataQualityMetric(**row_dict))

        run.status = "succeeded"
        run.records_processed = structure.courses_found
        run.records_failed = 0
        run.finished_at = datetime.utcnow()
        session.commit()

        if specialization and not programme.specialization:
            programme.specialization = specialization
        result = {
            "analysis_run_id": run.id,
            "source_id": source.id,
            "document_id": document.id,
            "status": "succeeded",
            "extraction_confidence": confidence,
            "flagged_for_review": flagged,
            "courses_found": structure.courses_found,
            "modules_found": len(structure.modules),
            "topics_found": len(structure.topics),
            "topics_unattributed": sum(1 for t in structure.topics if not t.course_code),
            "analysis_readiness": _analysis_readiness(structure, file_path),
            "outcomes_found": len(structure.outcomes),
            "outcomes_persisted": outcomes_persisted,
            "raw_artifact_path": str(raw_artifact_path),
            "bronze_artifact_path": str(bronze_artifact_path),
            "silver_artifact_path": str(silver_artifact_path),
            "raw_sha256": file_hash(file_path),
            "document_role": document_role,
        }
        # one canonical interpretation (execution / extraction / quality / review) returned with the numbers
        result["outcome"] = curriculum_outcome(result, LOW_CONFIDENCE_THRESHOLD)
        return result
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_log = str(exc)
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        raise


def _analysis_readiness(structure, file_path):
    """The analysis's own course checks on this upload (knowledge_engine.readiness); None when they cannot run."""
    if structure.is_empty:
        return None
    try:
        from app.knowledge_engine.readiness import curriculum_readiness
        sha = file_hash(file_path)
        return curriculum_readiness(structure, f"upl-{sha[:12]}", sha)
    except Exception as exc:  # noqa: BLE001 -- the check never breaks ingestion; its absence is reported
        return {"status": "NOT_CHECKED", "reasons": [f"the analysis readiness check could not run ({type(exc).__name__})"]}


def _get_or_create_institution(session: Session, name: str | None) -> Institution:
    name = name or "Unknown Institution"
    existing = session.query(Institution).filter(Institution.name == name).one_or_none()
    if existing:
        return existing
    inst = Institution(name=name)
    session.add(inst)
    session.flush()
    return inst


def _get_or_create_discipline(session: Session, name: str | None):
    """Discipline is a data-driven reference table (see app.models.curriculum.Discipline
    docstring) -- get-or-create by name, never a hardcoded set."""
    if not name:
        return None
    existing = session.query(Discipline).filter(Discipline.name == name).one_or_none()
    if existing:
        return existing
    disc = Discipline(name=name)
    session.add(disc)
    session.flush()
    return disc


def _get_or_create_department(session: Session, institution: Institution, name: str | None, discipline_name: str | None = None):
    if not name:
        return None
    existing = (
        session.query(Department)
        .filter(Department.institution_id == institution.id, Department.name == name)
        .one_or_none()
    )
    if existing:
        return existing
    discipline = _get_or_create_discipline(session, discipline_name)
    dept = Department(institution_id=institution.id, name=name, discipline_id=discipline.id if discipline else None)
    session.add(dept)
    session.flush()
    return dept


def _get_or_create_programme(
    session: Session,
    institution: Institution,
    name: str | None,
    department=None,
    programme_code: str | None = None,
    degree_level: str | None = None,
) -> Programme:
    name = name or "Unknown Programme"
    existing = (
        session.query(Programme)
        .filter(Programme.institution_id == institution.id, Programme.name == name)
        .one_or_none()
    )
    if existing:
        return existing
    prog = Programme(
        institution_id=institution.id,
        name=name,
        department_id=department.id if department else None,
        programme_code=programme_code,
        degree_level=degree_level,
    )
    session.add(prog)
    session.flush()
    return prog
