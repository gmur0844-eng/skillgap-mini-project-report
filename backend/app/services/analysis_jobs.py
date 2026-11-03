"""
Analysis jobs: turn an uploaded, usable curriculum into a NEW analysis run, without touching earlier runs.

  stage_upload(...)     keep a hash-addressed copy of the uploaded file + its metadata + its ingestion outcome
                        (data/raw/curricula/uploads/<sha12>/, data/metadata/staged_uploads/<upload_id>.json)
  start_job(upload_id)  build a DERIVED source manifest (the project manifest is never edited): the current manifest plus
                        the upload in its declared role. A new TARGET replaces the analysed curriculum (and the previous
                        version, which belonged to the old target); PEER / REFERENCE are added. Then the knowledge pipeline
                        runs in a background thread and produces a new run id; lineage (parent run -> new run) is recorded.
  job(job_id)           ANALYSIS_PENDING -> ANALYSIS_READY (run_id) | ANALYSIS_FAILED (reason) | NEEDS_REVIEW (the
                        run exists but the analysed curriculum failed its document checks, or a requested
                        capability was blocked, with the reasons)
  options               {"peers": bool, "industry": bool, "peer_ids"?: [doc_id]}: optional capabilities. A new institution's curriculum can be
                        analysed on its own: leaving peers or industry out removes those sources from the analysis
                        context and their outputs are reported NOT_REQUESTED (never BLOCKED, never another
                        institution's results). Default: both included when their evidence exists. peer_ids chooses
                        the peers explicitly: only those are compared; an unknown peer or one of another discipline is
                        refused (INVALID_PEER_SELECTION), never replaced by another.
  duplicate submissions the same upload with the same options while its job is still running returns that job.
  progress              rec["phases"]: live phase/step states built from the pipeline's own stage events
                        (analysis_progress.py), persisted with the job so a client can reconnect at any time.
  interrupted jobs      a job still PENDING that no thread of this process runs (the server stopped mid-run) is
                        reported ANALYSIS_FAILED with an explicit reason, never left pending forever.

An upload whose ingestion outcome is not usable is refused (EXECUTION_SUCCEEDED_BUT_NO_USABLE_CONTENT never; a
NEEDS_REVIEW upload only with an explicit reviewer name, which is recorded). One job runs at a time.
"""
import hashlib
import json
import re
import shutil
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.knowledge_engine import discipline_profiles, identity

REPO = Path(__file__).resolve().parents[3]
UPLOAD_DIR = REPO / "data/raw/curricula/uploads"
STAGED_DIR = REPO / "data/metadata/staged_uploads"
CONTEXT_DIR = REPO / "data/metadata/analysis_contexts"
JOB_DIR = REPO / "data/gold/knowledge/analysis_jobs"
MANIFEST = REPO / "data/metadata/curriculum_sources.json"
DISCIPLINE_REFERENCES = REPO / "data/metadata/discipline_references.json"
_MANIFEST_FIELDS = ("doc_id", "role", "institution", "programme", "discipline", "curriculum_version", "academic_year",
                    "path", "expected_sha256", "source_url", "acquisition", "retrieved_at")
GOLD = REPO / "data/gold/knowledge"

PENDING, READY, FAILED, REVIEW = "ANALYSIS_PENDING", "ANALYSIS_READY", "ANALYSIS_FAILED", "NEEDS_REVIEW"
_lock = threading.Lock()
_running = {"job_id": None}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def stage_upload(path, role, values, outcome, ingestion_run_id=None):
    path = Path(path)
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", path.name)[:120] or "upload"
    dest = UPLOAD_DIR / sha[:12] / safe
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copyfile(path, dest)
    upload_id = f"upl-{sha[:12]}"
    record = {"upload_id": upload_id, "sha256": sha, "path": str(dest.relative_to(REPO)), "file_name": path.name,
              "document_role": role, "metadata": {k: v for k, v in (values or {}).items() if v},
              "outcome": outcome, "ingestion_run_id": ingestion_run_id, "staged_at": _now()}
    _write(STAGED_DIR / f"{upload_id}.json", record)
    return record


def upload(upload_id):
    if not re.fullmatch(r"upl-[0-9a-f]{12}", upload_id or ""):
        return None
    return _read(STAGED_DIR / f"{upload_id}.json")


def _settle_interrupted(rec):
    """A PENDING job that no thread of this process is running was interrupted (the server stopped mid-run)."""
    if rec and rec.get("status") == PENDING and _running["job_id"] != rec.get("job_id"):
        # the job's thread writes its final record before it clears _running: a record read just before that write
        # is stale, not interrupted. Read it again before settling it.
        fresh = _read(JOB_DIR / f"{rec['job_id']}.json", None)
        if isinstance(fresh, dict) and fresh.get("status") != PENDING:
            return fresh
        from app.services import analysis_progress
        rec["status"] = FAILED
        rec["reason"] = "the analysis was interrupted (the server stopped while it was running); start it again"
        rec["interrupted"] = True
        rec["finished_at"] = rec.get("finished_at") or _now()
        rec["stage"] = "finished"
        analysis_progress.finish(rec, failed=True)
        _write(JOB_DIR / f"{rec['job_id']}.json", rec)
    return rec


def job(job_id):
    if not re.fullmatch(r"job-[0-9a-f]{12}", job_id or ""):
        return None
    return _settle_interrupted(_read(JOB_DIR / f"{job_id}.json"))


def jobs(limit=20):
    files = sorted(JOB_DIR.glob("job-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    return [_settle_interrupted(_read(p)) for p in files]


def active_job():
    """The job this server is running now, or None (a client uses it to reconnect after a reload)."""
    jid = _running["job_id"]
    return _read(JOB_DIR / f"{jid}.json") if jid else None


OPTION_DEFAULTS = {"peers": True, "industry": True}


def normalise_options(options):
    """{"peers": bool, "industry": bool[, "peer_ids": [doc_id, ...]]}; anything not given keeps its default
    (included). peer_ids is kept only when it is a list of strings (sorted, de-duplicated); an empty selection means
    no peer comparison."""
    out = dict(OPTION_DEFAULTS)
    for k in OPTION_DEFAULTS:
        if isinstance((options or {}).get(k), bool):
            out[k] = options[k]
    ids = (options or {}).get("peer_ids")
    if out["peers"] and isinstance(ids, list) and all(isinstance(i, str) for i in ids):
        ids = sorted({i.strip() for i in ids if i.strip()})
        if ids:
            out["peer_ids"] = ids
        else:
            out["peers"] = False
    return out


def comparison_targets(upload_id=None, base=None, discipline=None):
    """The peer curricula an analysis can be compared with, each with its discipline profile and whether it is
    comparable with the analysed curriculum's discipline: the upload's, or `discipline` (text typed in a form before
    anything is uploaded). Nothing is ever substituted: a client chooses from this list."""
    base = base if base is not None else (_read(MANIFEST, {}) or {})
    up = upload(upload_id) if upload_id else None
    given = up is not None or discipline is not None
    target_disc = (up or {}).get("metadata", {}).get("discipline") if up else discipline
    target_profile = discipline_profiles.resolve(target_disc) if given else None
    out = []
    for d in base.get("documents", []):
        if d.get("role") != "PEER":
            continue
        prof = discipline_profiles.resolve(d.get("discipline"))
        item = {"doc_id": d["doc_id"], "institution": d.get("institution"), "programme": d.get("programme"),
                "discipline": d.get("discipline"), "curriculum_version": d.get("curriculum_version"),
                "academic_year": d.get("academic_year"), "discipline_profile": prof["id"] if prof else None}
        if given:
            item["comparable"] = discipline_profiles.comparable(d.get("discipline"), target_disc)
            if not item["comparable"]:
                item["reason"] = ("another discipline" if prof and target_profile else
                                  "the upload's discipline does not match a discipline profile" if prof else
                                  "this curriculum's discipline does not match a discipline profile")
        out.append(item)
    return {"upload_id": upload_id, "upload_discipline": target_disc,
            "upload_discipline_profile": target_profile["id"] if target_profile else None,
            "discipline_profile": discipline_profiles.profile_ref(target_profile), "peers": out}


def peer_selection_problems(upload_id, peer_ids, base=None):
    """[(doc_id, problem)] for selected peers that are unknown or not comparable with the upload."""
    targets = {p["doc_id"]: p for p in comparison_targets(upload_id, base)["peers"]}
    problems = []
    for pid in peer_ids or []:
        if pid not in targets:
            problems.append((pid, "not a known peer curriculum"))
        elif targets[pid].get("comparable") is False:
            problems.append((pid, targets[pid].get("reason") or "not comparable"))
    return problems


same_institution = identity.same_institution  # one identity rule for uploads and the pipeline


def discipline_references(path=None):
    """Registered reference curricula of other disciplines (data/metadata/discipline_references.json), as manifest
    documents; not part of the default analysis."""
    data = _read(Path(path) if path else DISCIPLINE_REFERENCES, {}) or {}
    return [{k: r.get(k) for k in _MANIFEST_FIELDS} for r in data.get("references") or []
            if r.get("role") == "REFERENCE" and r.get("doc_id") and r.get("path")]


def _add_discipline_reference(docs, target_discipline, notes, references=None):
    """Adds the registered reference of the target's discipline when the context has none of that discipline."""
    profile = discipline_profiles.resolve(target_discipline)
    if profile is None:
        return docs
    if any(d.get("role") == "REFERENCE" and discipline_profiles.comparable(d.get("discipline"), target_discipline)
           for d in docs):
        return docs
    ids = {d["doc_id"] for d in docs}
    added = [r for r in (discipline_references() if references is None else references)
             if r["doc_id"] not in ids and discipline_profiles.comparable(r.get("discipline"), target_discipline)]
    if added:
        notes.append(f"{', '.join(r['doc_id'] for r in added)} (the registered {profile['name']} reference curriculum) "
                     "is the reference for this analysis")
    return docs + added


def derived_manifest(base, up, options=None, references=None):
    """The analysis context for an upload: base manifest + the upload in its role (pure; returns (manifest, notes)).
    options (normalise_options) leave optional capabilities out: their sources are removed from the context and the
    manifest's analysis_scope tells the pipeline to report them NOT_REQUESTED."""
    options = normalise_options(options)
    m = json.loads(json.dumps(base))
    md = up["metadata"]
    role = up["document_role"] or "TARGET"
    notes = []
    docs = [d for d in m.get("documents", []) if d.get("expected_sha256") != up["sha256"]]
    if role == "TARGET":
        earlier = next((d for d in docs if d.get("role") == "TARGET"), None)
        upload_doc = {"institution": md.get("institution"), "programme": md.get("programme") or md.get("title"),
                      "discipline": md.get("discipline"), "specialization": md.get("specialization"),
                      "degree_level": md.get("degree_level")}
        rel = identity.relation(earlier, upload_doc) if earlier is not None else None
        if rel and rel["relation"] in (identity.SAME_PROGRAMME, identity.SAME_INSTITUTION_OTHER_PROGRAMME):
            # the institution's current curriculum is the comparison for the upload; the version before it leaves
            # the context
            dropped = [d["doc_id"] for d in docs if d.get("role") == "PREVIOUS_VERSION"]
            docs = [{**d, "role": "PREVIOUS_VERSION"} if d is earlier else d
                    for d in docs if d.get("role") != "PREVIOUS_VERSION"]
            if rel["relation"] == identity.SAME_PROGRAMME:
                notes.append(f"{earlier['doc_id']} (the institution's current curriculum of the same programme) is the "
                             "earlier version of the upload, so curriculum changes are measured against it")
            else:
                notes.append(f"{earlier['doc_id']} is the institution's current curriculum of a different programme "
                             f"({'; '.join(rel['reasons'])}); it is used for a cross-programme comparison, not as an "
                             "earlier version of the upload")
            if dropped:
                notes.append(f"{', '.join(dropped)} (the version before it) is not part of this analysis context")
        else:
            replaced = [d["doc_id"] for d in docs if d.get("role") in ("TARGET", "PREVIOUS_VERSION")]
            docs = [d for d in docs if d.get("role") not in ("TARGET", "PREVIOUS_VERSION")]
            if replaced:
                notes.append(f"the uploaded curriculum is the analysed (TARGET) curriculum; {', '.join(replaced)} "
                             "(another institution's target and its previous version) are not part of this analysis "
                             "context, so curriculum drift needs a previous version of the upload's own programme")
    elif role == "PREVIOUS_VERSION":
        replaced = [d["doc_id"] for d in docs if d.get("role") == "PREVIOUS_VERSION"]
        docs = [d for d in docs if d.get("role") != "PREVIOUS_VERSION"]
        if replaced:
            notes.append(f"the uploaded document replaces the previous version {', '.join(replaced)}")
    entry = {"doc_id": up["upload_id"], "role": role,
             "institution": md.get("institution") or "(not institution-specific)",
             "programme": md.get("programme") or md.get("title") or up["file_name"],
             "discipline": md.get("discipline") or "(unspecified)",
             "curriculum_version": md.get("curriculum_version") or "(unspecified)",
             "academic_year": md.get("academic_year"), "specialization": md.get("specialization"),
             "degree_level": md.get("degree_level"), "path": up["path"], "expected_sha256": up["sha256"],
             "source_url": md.get("source_url"), "licence_note": md.get("licence_note"),
             "retrieved_at": up["staged_at"][:10], "acquisition": "uploaded through the application (Add evidence)"}
    docs.append(entry)
    if role == "TARGET":
        docs = _add_discipline_reference(docs, md.get("discipline"), notes, references)
    if options["peers"] and options.get("peer_ids"):
        chosen = set(options["peer_ids"]) | {up["upload_id"]}  # an uploaded PEER is always part of its own analysis
        left_out = [d["doc_id"] for d in docs if d.get("role") == "PEER" and d["doc_id"] not in chosen]
        docs = [d for d in docs if d.get("role") != "PEER" or d["doc_id"] in chosen]
        notes.append(f"compared with the selected peers only ({', '.join(options['peer_ids'])})"
                     + (f"; {', '.join(left_out)} are not part of this analysis context" if left_out else ""))
    if not options["peers"]:
        left_out = [d["doc_id"] for d in docs if d.get("role") == "PEER"]
        docs = [d for d in docs if d.get("role") != "PEER"]
        m["requested_peer_sources"] = []
        notes.append("peer comparison was not requested" + (f"; {', '.join(left_out)} are not part of this analysis "
                                                            "context" if left_out else ""))
    if not options["industry"]:
        m["industry_sources"], m["taxonomy_sources"] = [], []
        notes.append("industry evidence was not requested: this is a curriculum-only analysis (no demand, skill gaps "
                     "or recommendations)")
    if not (options["peers"] and options["industry"]):
        m["analysis_scope"] = {k: v for k, v in options.items() if v is False}
    m["documents"] = docs
    return m, notes


def start_job(upload_id, reviewed_by=None, runner=None, options=None, retry_of=None):
    """Returns (job, error_code). runner(manifest_path[, progress]) -> report dict; injected in tests."""
    up = upload(upload_id)
    if up is None:
        return None, "UPLOAD_NOT_FOUND"
    oc = (up.get("outcome") or {}).get("outcome")
    if oc in ("EXECUTION_SUCCEEDED_BUT_NO_USABLE_CONTENT", "EXECUTION_FAILED", "REGISTERED_AS_REFERENCE"):
        return None, "NOT_ANALYSABLE"
    if oc == "NEEDS_REVIEW" and not (reviewed_by or "").strip():
        return None, "REVIEW_REQUIRED"
    options = normalise_options(options)
    if options.get("peer_ids") and peer_selection_problems(upload_id, options["peer_ids"]):
        return None, "INVALID_PEER_SELECTION"
    # a repeated submission (double click, a client retrying after a network error) gets the job already running
    current = active_job()
    if current and current.get("status") == PENDING and current.get("upload_id") == upload_id \
            and normalise_options(current.get("options")) == options:
        return {**current, "duplicate_submission": True}, None
    if not _lock.acquire(blocking=False):
        return None, "JOB_RUNNING"
    try:
        base = _read(MANIFEST, {})
        manifest, notes = derived_manifest(base, up, options)
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        ctx_path = CONTEXT_DIR / f"{job_id}.json"
        _write(ctx_path, manifest)
        parent = (_read(GOLD / "latest_run.json", {}) or {}).get("run_id")
        rec = {"job_id": job_id, "upload_id": upload_id, "status": PENDING, "stage": "queued", "created_at": _now(),
               "finished_at": None, "run_id": None, "parent_run": parent, "reason": None, "context_notes": notes,
               "manifest_path": str(ctx_path.relative_to(REPO)), "reviewed_by": (reviewed_by or "").strip() or None,
               "options": options, "retry_of": retry_of, "updated_at": _now(), "current": None,
               "discipline_profile": discipline_profiles.profile_ref(
                   discipline_profiles.resolve(up["metadata"].get("discipline"))),
               "document": {k: up["metadata"].get(k) for k in ("institution", "programme", "discipline", "curriculum_version",
                                                               "academic_year")} | {"role": up["document_role"],
                                                                                    "file_name": up["file_name"]}}
        from app.services import analysis_progress
        rec["phases"] = analysis_progress.initial_phases()
        rec["progress_seq"] = 0
        _running["job_id"] = job_id  # before the record is visible: a PENDING record is never taken as interrupted
        _write(JOB_DIR / f"{job_id}.json", rec)
        t = threading.Thread(target=_run, args=(rec, ctx_path, runner), daemon=True)
        t.start()
        return rec, None
    except Exception:  # noqa: BLE001
        _running["job_id"] = None
        _lock.release()
        raise


def retry_job(job_id):
    """Start the same upload again with the same options and reviewer (a failed or interrupted job)."""
    rec = job(job_id)
    if rec is None:
        return None, "JOB_NOT_FOUND"
    if rec.get("status") == PENDING:
        return None, "JOB_RUNNING"
    return start_job(rec["upload_id"], reviewed_by=rec.get("reviewed_by"), options=rec.get("options"), retry_of=job_id)


def job_semantic_mode():
    """Semantic mode of an upload analysis. Default "replay": the verified recording, never a live model call. In
    LIVE mode no model decision can have an effect (there is no promotion gate), yet each call costs ~10 s on a local
    7B model: R26 (job-569cfd48c93f) spent 768 of its 852 s on 78 such calls. ANALYSIS_SEMANTIC_MODE=live restores
    live advisory decisions for a job (recorded, never applied)."""
    import os
    return None if os.environ.get("ANALYSIS_SEMANTIC_MODE", "").strip().lower() == "live" else "replay"


def _default_runner(manifest_path, progress=None):
    from app.knowledge_engine import pipeline
    # an upload's analysis is opened through its own run id; it never replaces the published default run
    return pipeline.run(manifest_path=manifest_path, set_latest=False, semantic_mode=job_semantic_mode(),
                        progress=progress)


def _call_runner(runner, ctx_path, progress):
    """Injected test runners may take only the manifest path; the default runner also takes the progress listener."""
    if runner is None:
        return _default_runner(ctx_path, progress)
    import inspect
    try:
        takes_progress = len(inspect.signature(runner).parameters) >= 2
    except (TypeError, ValueError):
        takes_progress = False
    return runner(ctx_path, progress) if takes_progress else runner(ctx_path)


def _target_failure(report, rec):
    """The analysed curriculum's own document-check failure, in plain words (None when it passed)."""
    target = rec.get("upload_id")
    if (report.get("health") or {}).get(target) != "FAIL":
        return None
    checks = []
    run_dir = GOLD / str(report.get("run_id"))
    doc_health = ((_read(run_dir / "health.json", {}) or {}).get("documents") or {}).get(target) or {}
    for c in doc_health.get("checks") or []:
        if c.get("status") == "FAIL":
            checks.append(f"{c['check'].replace('_', ' ')} {c.get('value')} (needs {c.get('threshold')})")
    return ("the uploaded curriculum failed the analysis's document checks"
            + (f": {'; '.join(checks)}" if checks else "") + "; review the extraction (Preprocessing preview)")


def _run(rec, ctx_path, runner):
    from app.services import analysis_progress
    save = lambda r: _write(JOB_DIR / f"{r['job_id']}.json", r)  # noqa: E731
    tracker = analysis_progress.ProgressTracker(rec, save)
    gates, target_failed, failed = {}, None, False
    # the outcome is published only in the final write, together with the closed phases: a client never sees a
    # final status while a step (e.g. lineage) is still shown running
    status, reason = FAILED, "the pipeline produced no run"
    try:
        rec.update(stage="analysing", updated_at=_now())
        save(rec)
        report = _call_runner(runner, ctx_path, tracker)
        rec["run_id"] = report.get("run_id")
        gates = report.get("analytics_gates") or (report.get("health") or {}).get("analytics_gates") or {}
        rec["capabilities"] = {k: {"status": v.get("status"), "reasons": v.get("reasons") or []}
                               for k, v in gates.items() if isinstance(v, dict)}
        timings = (report.get("observability") or {}).get("stages") or []
        if timings:
            rec["stage_timings_s"] = {}
            for st in timings:
                rec["stage_timings_s"][st["stage"]] = round(rec["stage_timings_s"].get(st["stage"], 0)
                                                            + float(st.get("duration_s") or 0), 3)
        blocked = {k: v for k, v in gates.items() if isinstance(v, dict) and v.get("status") == "BLOCKED"}
        target_failed = _target_failure(report, rec) if rec["run_id"] else None
        if rec["run_id"] and target_failed:
            # the curriculum itself could not be analysed: that is the reason, not the gates it blocked downstream
            status, reason = REVIEW, target_failed
            rec["review"] = {"code": "TARGET_DOCUMENT_FAILED", "detail": target_failed}
        elif rec["run_id"] and not blocked:
            status, reason = READY, None
        elif rec["run_id"]:
            status = REVIEW
            reason = "analytics gates blocked: " + "; ".join(f"{k}: {', '.join(map(str, v.get('reasons', [])))}"
                                                              for k, v in blocked.items())
        if rec["run_id"] and rec["parent_run"] and rec["parent_run"] != rec["run_id"]:
            try:
                tracker.stage("lineage", lambda: _write_lineage(rec))
            except Exception as exc:  # noqa: BLE001 -- lineage failure never hides the run
                rec["lineage_error"] = type(exc).__name__
    except Exception as exc:  # noqa: BLE001
        failed = True
        status, reason = FAILED, f"{type(exc).__name__}: {str(exc)[:300]}"
        rec["error_detail"] = traceback.format_exc()[-2000:]
    finally:
        rec["status"], rec["reason"] = status, reason
        rec["finished_at"] = _now()
        rec["stage"] = "finished"
        analysis_progress.finish(rec, gates=gates, target_failed=target_failed, failed=failed)
        _write(JOB_DIR / f"{rec['job_id']}.json", rec)
        _running["job_id"] = None
        _lock.release()


def _write_lineage(rec):
    """Lineage parent run -> new run (recompute.py); raises on failure, which the caller records."""
    from app.knowledge_engine import recompute
    diff = recompute.diff_runs(GOLD / rec["parent_run"], GOLD / rec["run_id"])
    pinv, pfp, _ = recompute.inventory_from_run(GOLD / rec["parent_run"])
    ninv, nfp, _ = recompute.inventory_from_run(GOLD / rec["run_id"])
    changes = recompute.source_changes(pinv, ninv)
    lineage = recompute.lineage_record(rec["parent_run"], rec["run_id"], changes,
                                       recompute.plan(changes, pfp != nfp), diff, pfp, nfp)
    lineage["trigger"] = {"kind": "UPLOAD_ANALYSIS_JOB", "job_id": rec["job_id"], "upload_id": rec["upload_id"]}
    recompute.write_lineage(REPO, lineage)
    rec["lineage"] = f"data/gold/knowledge/lineage/{rec['run_id']}.json"
