"""
One reproducible end-to-end workflow: RAW -> BRONZE -> SILVER -> HEALTH GATE -> GOLD (-> PUBLISH).

Reproducibility / idempotency
  * run_id = hash(pipeline version, parser fingerprint, config hash, backend,
    semantic identity (mode, model key, replayed recording), every document's
    SHA-256, review-decisions hash). A protected release
    (data/metadata/protected_runs.json) is never regenerated in place. Same inputs -> same
    run_id -> same GOLD directory; the run writes a content digest that must
    match on rerun.
  * BRONZE page text is cached per document SHA-256 AND parser fingerprint:
    an unchanged PDF is not re-extracted; any change to the extraction code
    invalidates the cache automatically.
  * GOLD run directories are never overwritten by a DIFFERENT run: a new
    run_id gets a new directory, so historical results stay reproducible.

Fail-safe
  * Documents failing the health gate are excluded from GOLD analytics;
    analytics whose inputs are missing are written as BLOCKED records with
    reasons -- never as numbers.
"""
import hashlib
import json
import shutil
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.analytics.core_knowledge_mapping import (
    MATCH_STATUS_COMPOUND, MATCH_STATUS_MATCHED, load_scoped_vocabulary, match_text_to_core_topics,
)
from app.knowledge_engine import PIPELINE_VERSION
from app.knowledge_engine.concepts import concept_edges, course_families, discover_concepts
from app.knowledge_engine.config import config_hash, load_config
from app.knowledge_engine.contracts import enforce
from app.knowledge_engine.drift import comparable_semesters, concept_drift, course_drift
from app.knowledge_engine.evaluation import (
    confidence_distribution, evaluate_golden_pages, evaluate_industry_sample, evaluate_semantic_benchmark,
    evaluate_topic_sample,
)
from app.knowledge_engine.exports import content_digest, file_sha256, write_csv, write_json, write_jsonl
from app.knowledge_engine import curriculum_scope as curriculum_scope_mod
from app.knowledge_engine import discipline_profiles
from app.knowledge_engine import identity, industry_intel, industry_stage, intelligence_stage, occupation_resolution, peer_stage
from app.knowledge_engine.intelligence import outcomes_by_course as intel_outcomes
from app.knowledge_engine.evidence_guard import require_source_path
from app.knowledge_engine.health import FAIL, analytics_gates, document_health, industry_health
from app.knowledge_engine.mapping import concept_reference_status, course_correspondence, map_topics
from app.knowledge_engine.observability import RunObserver
from app.knowledge_engine.prerequisites import resolve_prerequisites
from app.knowledge_engine.quarantine import Quarantine
from app.knowledge_engine.review import apply_decisions, assign_priority, build_review_queue, load_decisions, update_registry
from app.knowledge_engine.semantic_backend import available_backends, get_backend
from app.knowledge_engine.silver import build_silver
from app.knowledge_engine.skills import build_skill_layer
from app.pipelines.preprocessing import curriculum_structuring, layout_aware_extraction
from app.pipelines.preprocessing.curriculum_structuring import structure_curriculum_pages

REPO = Path(__file__).resolve().parents[3]


# Optional capabilities an analysis can be asked to leave out (manifest "analysis_scope": {"peers": false,
# "industry": false}), and the gates each one owns. Industry evidence feeds relevance, skill intelligence, gap
# reasoning and recommendations, so leaving it out leaves the curriculum's own analysis (and reference mapping).
# The skill taxonomy (ESCO) is loaded together with the job postings, so it is left out with them.
NOT_REQUESTED_GATES = {"peers": ("peer_benchmark",),
                       "industry": ("industry_gap", "industry_demand", "recommendations", "skill_taxonomy")}
NOT_REQUESTED_REASONS = {
    "peers": "peer comparison was not requested for this analysis",
    "industry": "industry evidence was not requested for this analysis (curriculum-only analysis)",
}


def parser_fingerprint():
    h = hashlib.sha256()
    for module in (curriculum_structuring, layout_aware_extraction):
        h.update(Path(module.__file__).read_bytes())
    h.update(Path(REPO / "backend/app/reference_data/non_course_identifiers.json").read_bytes())
    return h.hexdigest()[:16]


def code_fingerprint():
    """Hash of the analytical code (engine package + the project analytics and
    skill modules it calls), so a code change always yields a new run_id."""
    h = hashlib.sha256()
    roots = [REPO / "backend/app/knowledge_engine", REPO / "backend/app/analytics"]
    files = sorted(f for r in roots for f in r.glob("*.py"))
    files += [REPO / "backend/app/pipelines/preprocessing" / n for n in
              ("skill_extraction.py", "skill_normalization.py", "text_cleaning.py", "validation.py", "deduplication.py")]
    for f in files:
        h.update(f.relative_to(REPO).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def _pdftotext_pages(path):
    raw = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=True).stdout
    pages = raw.split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


def bronze_pages(doc, fingerprint, force=False):
    """Per-page text for one document, cached by (sha256, parser fingerprint)."""
    cache = REPO / "data" / "bronze" / "curricula" / doc["sha256"][:16] / f"pages.{fingerprint}.json"
    if cache.exists() and not force:
        return json.loads(cache.read_text(encoding="utf-8")), "CACHE_HIT"
    fallback = _pdftotext_pages(REPO / doc["path"])
    geometry_dir = REPO / "data" / "bronze" / "curricula"
    geometry_state = ("HIT" if layout_aware_extraction.geometry_cache_path(geometry_dir, REPO / doc["path"]).exists()
                      else "STORED")
    pages, used = layout_aware_extraction.extract_document_pages_as_text(str(REPO / doc["path"]), fallback_pages=fallback,
                                                                         geometry_cache_dir=geometry_dir)
    methods = ["pdfplumber_table_topics_column" if u else "pdftotext_layout" for u in used]
    listing = subprocess.run(["pdfimages", "-list", str(REPO / doc["path"])], capture_output=True, text=True).stdout.splitlines()[2:]
    image_pages = sorted({int(line.split()[0]) for line in listing if line.strip()})
    raw_alpha = [sum(ch.isalpha() for ch in p) for p in fallback]
    cache.parent.mkdir(parents=True, exist_ok=True)
    data = {"doc_id": doc["doc_id"], "sha256": doc["sha256"], "parser_fingerprint": fingerprint,
            "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "pages": pages, "methods": methods, "raw_alpha_per_page": raw_alpha, "image_pages": image_pages}
    write_json(cache, data)
    return data, f"EXTRACTED (page geometry {geometry_state})"


class ProtectedRunError(RuntimeError):
    pass


def numeric_environment():
    """The interpreter, numeric libraries and BLAS that computed this run. Clustering and nearest-neighbour peer
    comparison are floating-point computations whose near-ties can resolve differently on another BLAS (OpenBLAS vs
    Apple Accelerate) or library version, so a reproducibility comparison needs to know what produced each run.
    Recorded in run_report.json only (outside the content digest): it describes the machine, not the evidence."""
    import platform
    import sys
    out = {"python": platform.python_version(), "implementation": platform.python_implementation(),
           "platform": f"{sys.platform}-{platform.machine()}"}
    for mod in ("numpy", "scipy", "sklearn", "threadpoolctl"):
        try:
            out[mod] = __import__(mod).__version__
        except Exception as exc:  # recorded, never fatal
            out[mod] = f"unavailable: {type(exc).__name__}"
    try:
        from threadpoolctl import threadpool_info
        out["blas"] = [{k: lib.get(k) for k in ("user_api", "internal_api", "version", "prefix", "threading_layer",
                                                 "architecture", "num_threads")}
                       for lib in threadpool_info()]
    except Exception as exc:
        out["blas"] = f"unavailable: {type(exc).__name__}"
    try:
        import numpy
        out["numpy_blas_build"] = {k: v for k, v in ((numpy.show_config(mode="dicts") or {}).get("Build Dependencies")
                                                      or {}).get("blas", {}).items() if k in ("name", "version")}
    except Exception as exc:
        out["numpy_blas_build"] = f"unavailable: {type(exc).__name__}"
    return out


def protected_runs():
    """Release run ids that must never be regenerated in place."""
    p = REPO / "data/metadata/protected_runs.json"
    return set(json.loads(p.read_text(encoding="utf-8")).get("protected_runs", [])) if p.exists() else set()


def existing_settings():
    """The project's established thresholds (app.core.config), hashed into the run."""
    from app.core.config import get_settings
    st = get_settings()
    return {k: getattr(st, k) for k in ("high_demand_threshold", "partial_coverage_threshold", "high_coverage_threshold",
                                        "min_periods_for_trend", "min_eligible_postings_per_period",
                                        "min_skill_postings_for_trend", "near_duplicate_similarity_threshold",
                                        "taxonomy_version")}


def _load_json(path, default=None):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def run(manifest_path=None, config_path=None, force_extract=False, publish=False, dsn=None,
        record_baseline=False, gold_root=None, config_overrides=None, set_latest=True, semantic_mode=None, progress=None):
    """set_latest=False leaves data/gold/knowledge/latest_run.json (the run the API serves by default) untouched: an
    uploaded curriculum's analysis is opened through its own run id and never replaces the published default run.
    semantic_mode="replay" never calls a live model (see intelligence_stage.semantic_setup); None keeps the default.
    progress(event, stage_record) receives each stage's start and end (RunObserver listener); it never affects results."""
    manifest_path = Path(manifest_path or REPO / "data/metadata/curriculum_sources.json")
    manifest = _load_json(manifest_path)
    cfg = load_config(config_path, overrides=config_overrides)
    cfg["existing_settings"] = existing_settings()
    cfg_hash = config_hash(cfg)
    observer = RunObserver(listener=progress)
    quarantine = Quarantine()
    decisions_path = REPO / "data/metadata/review_decisions.json"
    baselines_path = REPO / "data/metadata/pipeline_baselines.json"
    baselines = _load_json(baselines_path, {"documents": {}})
    fingerprint = parser_fingerprint()
    backend, backend_resolution = get_backend(cfg["semantic_backend"])

    # ---------------- RAW ----------------
    with observer.stage("raw.verify") as st:
        documents = []
        for entry in manifest["documents"]:
            require_source_path(entry["path"], REPO)
            path = REPO / entry["path"]
            if not path.exists():
                quarantine.add("raw", entry, f"MISSING_FILE: {entry['path']}")
                continue
            sha = file_sha256(path)
            info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True).stdout
            pages = int(next((l.split()[-1] for l in info.splitlines() if l.startswith("Pages:")), "0"))
            documents.append({**entry, "sha256": sha, "page_count": pages, "bytes": path.stat().st_size})
        documents = enforce(documents, "document", quarantine, "raw")
        job_sources, taxonomy_sources = industry_stage.verify_sources(manifest, REPO, quarantine)
        st["documents"] = len(documents)
        st["job_files"] = len(job_sources)
        st["taxonomy_files"] = len(taxonomy_sources)
    roles = {d["doc_id"]: d["role"] for d in documents}
    # ---- discipline profile (discipline_profiles.py): evidence is used only when it belongs to the analysed
    # curriculum's discipline. Job postings of other populations are left out before anything reads them, so the run
    # id reflects the evidence actually used; a discipline with no relevant postings is analysed on its curriculum.
    target_profile, job_sources, industry_exclusion = discipline_profiles.scope_industry(documents, job_sources)
    observer.count("documents", len(documents))
    observer.count("pages", sum(d["page_count"] for d in documents))

    code_fp = code_fingerprint()
    # the semantic layer is set up before the run id: its identity (mode, model key, replayed recording) is an input
    adjudicator, semantic_info = intelligence_stage.semantic_setup(cfg, REPO, mode=semantic_mode)
    semantic_id = intelligence_stage.semantic_identity(adjudicator, semantic_info)
    run_id = hashlib.sha256("|".join([PIPELINE_VERSION, fingerprint, code_fp, cfg_hash, backend_resolution["used"],
                                      semantic_id,
                                      *sorted(d["sha256"] for d in documents),
                                      *sorted(j["sha256"] for j in job_sources + taxonomy_sources),
                                      file_sha256(decisions_path) if decisions_path.exists() else "-",
                                      # only an explicit scope enters the id: runs without one keep their ids
                                      *([json.dumps(manifest["analysis_scope"], sort_keys=True)]
                                        if manifest.get("analysis_scope") else []),
                                      # a model-based backend enters with its model identity (repo, revision, file
                                      # hashes); TF-IDF runs keep their ids
                                      *([json.dumps(backend.describe(), sort_keys=True, default=str)]
                                        if backend_resolution["used"] != "tfidf" else [])]).encode()).hexdigest()[:16]
    gold_dir = Path(gold_root or REPO / "data/gold/knowledge") / run_id
    if gold_dir.exists():
        if run_id in protected_runs():
            raise ProtectedRunError(f"run {run_id} is a protected release; it is never regenerated in place "
                                    "(data/metadata/protected_runs.json)")
        shutil.rmtree(gold_dir)  # same run_id == identical inputs: regenerate the same content in place
    gold_dir.mkdir(parents=True)

    # ---------------- BRONZE + SILVER ----------------
    silver, doc_summaries = {}, {}
    for doc in documents:
        with observer.stage("bronze.extract", doc_id=doc["doc_id"]) as st:
            bronze, cache_state = bronze_pages(doc, fingerprint, force_extract)
            pages, methods = bronze["pages"], bronze["methods"]
            st["cache"] = cache_state
            st["pages"] = len(pages)
            st["table_topic_pages"] = methods.count("pdfplumber_table_topics_column")
        with observer.stage("silver.structure", doc_id=doc["doc_id"]) as st:
            structure = structure_curriculum_pages(pages)
            doc_ctx = {**doc, "_page_methods": {i + 1: m for i, m in enumerate(methods)}}
            records = build_silver(doc_ctx, structure, quarantine, cfg["topics"])
            checked = len(records["courses"]) + len(records["units"]) + len(records["topics"])
            before = quarantine.count()
            records["courses"] = enforce(records["courses"], "course", quarantine, "silver.contract")
            records["units"] = enforce(records["units"], "unit", quarantine, "silver.contract")
            records["topics"] = enforce(records["topics"], "topic", quarantine, "silver.contract")
            violations = quarantine.count() - before
            for t in records["topics"]:
                t["role"] = doc["role"]
            silver[doc["doc_id"]] = records
            unresolved = sum(1 for q in quarantine.items if q["stage"] == "silver.course" and q["record"].get("doc_id") == doc["doc_id"]
                             and q["reason"].startswith("UNRESOLVED_TITLE"))
            topics = records["topics"]
            doc_summaries[doc["doc_id"]] = {
                "doc_id": doc["doc_id"], "sha256": doc["sha256"], "expected_sha256": doc.get("expected_sha256"),
                "page_count": doc["page_count"],
                "text_layer_pages": sum(1 for a in bronze["raw_alpha_per_page"] if a >= 20),
                "blank_pages": sum(1 for i, a in enumerate(bronze["raw_alpha_per_page"]) if a < 20 and (i + 1) not in bronze["image_pages"]),
                "ocr_required_pages": sum(1 for i, a in enumerate(bronze["raw_alpha_per_page"]) if a < 20 and (i + 1) in bronze["image_pages"]),
                "valid_courses": len(records["courses"]), "unresolved_title_courses": unresolved,
                "units": len(records["units"]), "all_topics": len(topics),
                "clean_topics": sum(1 for t in topics if t["noise_label"] == "TOPIC"),
                "noise_topics": sum(1 for t in topics if t["noise_label"] != "TOPIC"),
                "outcomes": len(records["outcomes"]), "prerequisites": len(records["prerequisites"]),
                "contract_checked": checked, "contract_violations": violations,
                "topics_with_provenance": sum(1 for t in topics if t["doc_id"] and t["course_uid"] and t["page_number"]),
                "noise_breakdown": dict(Counter(t["noise_label"] for t in topics)),
                "courses_with_semester": sum(1 for c in records["courses"] if c.get("semester")),
            }
            st.update({k: doc_summaries[doc["doc_id"]][k] for k in ("valid_courses", "units", "clean_topics", "noise_topics")})
        write_jsonl(REPO / "data/silver/curricula" / doc["doc_id"] / doc["sha256"][:16] / "courses.jsonl", records["courses"],
                    sort_key=lambda r: r["course_uid"])
        write_jsonl(REPO / "data/silver/curricula" / doc["doc_id"] / doc["sha256"][:16] / "topics.jsonl", records["topics"],
                    sort_key=lambda r: r["topic_uid"])
        write_jsonl(REPO / "data/silver/curricula" / doc["doc_id"] / doc["sha256"][:16] / "outcomes.jsonl", records["outcomes"],
                    sort_key=lambda r: r["outcome_uid"])

    # ---------------- INDUSTRY: RAW -> SILVER, extraction, ESCO ----------------
    industry_ingest, extraction, esco_vocab, esco_audit, ind_health = None, None, None, None, None
    if job_sources:
        with observer.stage("industry.esco") as st:
            esco_vocab, esco_audit = industry_stage.load_esco(taxonomy_sources,
                                                              cfg["industry"].get("esco_taxonomy_mode", "full_with_delta"))
            st["skill_concepts"] = len(esco_vocab["concepts"]) if esco_vocab else 0
        with observer.stage("industry.silver") as st:
            industry_ingest = industry_stage.ingest(job_sources, REPO, cfg["existing_settings"],
                                                    cfg["industry"].get("employer_boilerplate"))
            st.update(industry_ingest["summary"]["status_counts"])
        observer.count("job_postings_read", industry_ingest["summary"]["records_read"])
        observer.count("job_postings_eligible", len(industry_ingest["postings"]))
        if esco_vocab:
            with observer.stage("industry.extract") as st:
                # peers never alter the run's mappings, and neither do curricula of another discipline (the guard
                # below sets them aside, so their topics would have no coverage to belong to)
                set_aside = discipline_profiles.not_comparable_documents(documents)
                core_documents = [d for d in documents if d["role"] != "PEER" and d not in set_aside]
                source_topics = [t for d in core_documents for t in silver[d["doc_id"]]["topics"] if t["noise_label"] == "TOPIC"]
                resolver = None
                if esco_vocab.get("_store"):
                    all_silver_topics = {t["topic_uid"]: t for d in core_documents for t in silver[d["doc_id"]]["topics"]}
                    silver_courses = {c["course_uid"]: c for d in core_documents for c in silver[d["doc_id"]]["courses"]}
                    resolver = intelligence_stage.industry_sense_resolver(
                        cfg, adjudicator, semantic_info, esco_vocab["_store"], all_silver_topics, silver_courses,
                        intel_outcomes([o for d in core_documents for o in silver[d["doc_id"]]["outcomes"]]))
                ext_cache = industry_stage.ExtractionCache(REPO / "data/cache/industry_extraction", {
                    "code": code_fp, "config": cfg_hash, "backend": backend_resolution["used"],
                    "taxonomy": sorted(j["sha256"] for j in taxonomy_sources),
                    "esco_mode": cfg["industry"].get("esco_taxonomy_mode", "full_with_delta"),
                    "numeric": {k: v for k, v in numeric_environment().items() if k in ("python", "numpy", "scipy", "sklearn")}})
                extraction = industry_stage.extract_and_map(industry_ingest["postings"], source_topics, esco_vocab, cfg,
                                                            lambda: get_backend(cfg["semantic_backend"])[0],
                                                            sense_resolver=resolver, cache=ext_cache)
                st.update(extraction["summary"])
                st["cache"] = extraction["cache"]["status"]  # observability only: outputs never depend on it
            observer.count("skill_mentions", extraction["summary"]["mentions_all"])
            observer.count("normalized_skills", extraction["summary"]["unique_normalized_skills"])
            observer.count("esco_mapped_skills", extraction["summary"]["esco_mapped_skills"])
            ind_summary = industry_stage.health_summary(job_sources, industry_ingest, extraction, esco_vocab)
            industry_key = hashlib.sha256("|".join(sorted(j["sha256"] for j in job_sources + taxonomy_sources)).encode()).hexdigest()[:16]
            ind_health = industry_health(ind_summary, cfg, baselines.get("industry", {}).get(industry_key))
            ind_health["summary"] = ind_summary
            ind_health["inputs_key"] = industry_key

    # ---------------- HEALTH GATE ----------------
    with observer.stage("health.gate") as st:
        health = {d: document_health(s, cfg, baselines["documents"].get(s["sha256"])) for d, s in doc_summaries.items()}
        usable_all = [d for d in documents if health[d["doc_id"]]["status"] != FAIL]
        # PEER curricula are decoded and health-checked like every document but kept out of every
        # TARGET / PREVIOUS_VERSION / REFERENCE analytic; they are only read by the peer stage
        # peer and reference curricula of another discipline are not comparable with the analysed curriculum
        not_comparable = [d for d in discipline_profiles.not_comparable_documents(documents) if d in usable_all]
        usable_all = [d for d in usable_all if d not in not_comparable]
        usable_docs = [d for d in usable_all if d["role"] != "PEER"]
        usable_peers = [d for d in usable_all if d["role"] == "PEER"]
        by_role = defaultdict(list)
        for d in usable_docs:
            by_role[d["role"]].append(d)
        prev_doc = by_role.get("PREVIOUS_VERSION", [None])[0]
        target_doc = by_role.get("TARGET", [None])[0]
        # does the target cover the whole programme? (span derived from the other curricula; curriculum_scope.py)
        curriculum_scope = curriculum_scope_mod.assess(
            target_doc, usable_all, {d["doc_id"]: silver[d["doc_id"]]["courses"] for d in usable_all},
            cfg.get("curriculum_scope"))
        st.update(curriculum_scope=curriculum_scope["status"])
        # one identity rule (identity.py): versions of the same programme are compared as curriculum changes; another
        # programme of the same institution only as a cross-programme comparison; other institutions only as peers
        curriculum_relation = identity.relation(prev_doc, target_doc) if prev_doc and target_doc else None
        rel_kind = curriculum_relation["relation"] if curriculum_relation else None
        same_programme = rel_kind == identity.SAME_PROGRAMME
        cross_programme = rel_kind == identity.SAME_INSTITUTION_OTHER_PROGRAMME
        semesters = (comparable_semesters(silver[prev_doc["doc_id"]]["courses"], silver[target_doc["doc_id"]]["courses"])
                     if same_programme or cross_programme else [])
        industry_postings = len(industry_ingest["postings"]) if industry_ingest else None
        gates = analytics_gates(health, {d["doc_id"]: d["role"] for d in documents
                                         if d["role"] != "PEER" and d not in not_comparable}, semesters,
                                taxonomy_loaded=esco_vocab is not None, industry_postings=industry_postings, cfg=cfg,
                                industry_health_status=ind_health["status"] if ind_health else (FAIL if industry_ingest else None),
                                taxonomy_scope=esco_audit.get("reconstruction_scope") if esco_audit else None)
        if gates["reference_mapping"]["status"] != "ALLOWED" or not by_role.get("TARGET"):
            gates["industry_gap"] = {"status": "BLOCKED", "reasons": ["gap classification needs a healthy TARGET curriculum"
                                                                      " and reference mapping"]}
        gates["recommendations"] = ({"status": "ALLOWED", "reasons": []} if gates["industry_gap"]["status"] == "ALLOWED"
                                    else {"status": "BLOCKED", "reasons": ["recommendations require an industry-evidenced gap classification, which is blocked"]})
        gates["peer_benchmark"] = ({"status": "ALLOWED", "reasons": [], "peers": [d["doc_id"] for d in usable_peers]}
                                   if target_doc and usable_peers else
                                   {"status": "BLOCKED", "reasons": ["needs a healthy TARGET and at least one healthy PEER curriculum"
                                                                     if target_doc else "needs a healthy TARGET curriculum"],
                                    "peers": [d["doc_id"] for d in usable_peers]})
        if target_doc and not same_programme:
            # curriculum changes are only defined between versions of one programme: without such a version the
            # analysis is not applicable (not a failed requirement), and the reason says which comparison applies
            gates["concept_drift"] = {"status": "NOT_APPLICABLE", "reasons": [
                ("the earlier curriculum is a different programme of the same institution ("
                 + "; ".join(curriculum_relation["reasons"]) + "); it is compared as a cross-programme comparison")
                if cross_programme else
                ("the earlier curriculum is from another institution; institutions are compared only as peers")
                if rel_kind == identity.DIFFERENT_INSTITUTION else
                "no earlier curriculum of the same programme is available"]}
        gates["programme_comparison"] = (
            {"status": "ALLOWED", "reasons": []} if cross_programme and semesters else
            {"status": "BLOCKED", "reasons": ["the two programmes share no comparable semester"]} if cross_programme else
            {"status": "NOT_APPLICABLE", "reasons": ["only for two programmes of the same institution"]})
        # analyses whose evidence does not belong to the curriculum's discipline: NOT_APPLICABLE, with the reason
        discipline_profiles.apply_gates(gates, not_comparable,
                                        {"PEER": usable_peers, "REFERENCE": by_role.get("REFERENCE") or []},
                                        industry_exclusion, job_sources)
        # capabilities the analysis was asked to leave out (an upload's standalone analysis): reported as
        # NOT_REQUESTED -- not BLOCKED, which would mean the evidence was wanted and is missing or unusable
        for capability, gate_names in NOT_REQUESTED_GATES.items():
            if (manifest.get("analysis_scope") or {}).get(capability) is False:
                for name in gate_names:
                    gates[name] = {"status": "NOT_REQUESTED", "reasons": [NOT_REQUESTED_REASONS[capability]]}
        st["documents"] = {d: h["status"] for d, h in health.items()}
        st["gates"] = {g: v["status"] for g, v in gates.items()}

    # ---------------- GOLD ----------------
    courses = [c for d in usable_docs for c in silver[d["doc_id"]]["courses"]]
    courses_by_uid = {c["course_uid"]: c for c in courses}
    all_topics = [t for d in usable_docs for t in silver[d["doc_id"]]["topics"]]
    clean_topics = [t for t in all_topics if t["noise_label"] == "TOPIC"]
    topics_by_uid = {t["topic_uid"]: t for t in all_topics}
    observer.count("courses_valid", len(courses))
    observer.count("units", sum(len(silver[d["doc_id"]]["units"]) for d in usable_docs))
    observer.count("topics_extracted", len(all_topics))
    observer.count("topics_clean", len(clean_topics))

    families, concepts, edges, mappings, drift_rows, course_drift_rows = [], [], [], [], [], []
    concept_ref_status, correspondence, prereq_edges, unresolved_prereqs = [], [], [], []
    course_reference_matches, skill_candidates, skill_links = [], [], []
    applied_decisions, family_selection, drift_counts, course_drift_counts, course_drift_excluded = [], {}, {}, {}, {}
    topic_to_concept, taxonomy_status = {}, None

    if gates["concept_discovery"]["status"] == "ALLOWED":
        with observer.stage("gold.concepts") as st:
            for discipline in sorted({d["discipline"] for d in usable_docs}):
                d_ids = {d["doc_id"] for d in usable_docs if d["discipline"] == discipline}
                d_courses = [c for c in courses if c["doc_id"] in d_ids]
                d_topics = [t for t in clean_topics if t["doc_id"] in d_ids]
                backend.fit([t["clean_text"] for t in d_topics] + [c["title"] for c in d_courses])
                by_course = defaultdict(list)
                for t in d_topics:
                    by_course[t["course_uid"]].append(t)
                fams, c2f, selection = course_families(discipline, d_courses, by_course, backend, cfg["families"])
                family_selection[discipline] = selection
                families += fams
                for fam in fams:
                    fam_topics = [t for t in d_topics if c2f[t["course_uid"]] == fam["family_uid"]]
                    found, t2c = discover_concepts(discipline, fam, fam_topics, backend, cfg["concepts"], roles)
                    concepts += found
                    topic_to_concept.update(t2c)
                # mapping needs the discipline-fitted backend, so it runs inside the discipline loop
                if gates["reference_mapping"]["status"] == "ALLOWED":
                    targets = [t for t in d_topics if roles[t["doc_id"]] == "TARGET"]
                    refs = [t for t in d_topics if roles[t["doc_id"]] == "REFERENCE"]
                    concept_roles = {c["concept_uid"]: c["source_roles"] for c in concepts}
                    mappings += map_topics(targets, refs, c2f, topic_to_concept, concept_roles, backend,
                                           {**cfg["mapping"], "course_context_min_similarity":
                                            cfg["peers"]["course_context_min_similarity"]}, courses_by_uid)
                for c in d_courses:
                    c["family_uid"] = c2f.get(c["course_uid"])
            concepts, applied_decisions = apply_decisions(concepts, load_decisions(decisions_path))
            assign_priority(concepts, cfg)
            concepts = enforce(concepts, "concept", quarantine, "gold.contract")
            edges = enforce(concept_edges(concepts, topics_by_uid), "edge", quarantine, "gold.contract")
            st.update({"families": len(families), "concepts": len(concepts), "edges": len(edges)})
        observer.count("concepts", len(concepts))
        observer.count("topics_in_concepts", sum(c["support"] for c in concepts))

    if gates["reference_mapping"]["status"] == "ALLOWED":
        with observer.stage("gold.reference_mapping") as st:
            mappings = enforce(mappings, "mapping", quarantine, "gold.contract")
            concept_ref_status = concept_reference_status(concepts, topics_by_uid, courses_by_uid)
            target_courses = [c for c in courses if roles[c["doc_id"]] == "TARGET"]
            correspondence = course_correspondence(mappings, target_courses, courses_by_uid)
            # the derived core topics belong to one discipline; another discipline's courses are not matched to them
            core_ref = manifest.get("core_reference")
            core = (_load_json(REPO / core_ref["path"]) if core_ref and target_doc is not None
                    and discipline_profiles.comparable(core_ref.get("applies_to_discipline"),
                                                       target_doc.get("discipline")) else None)
            if core:
                abbr, syn, vocab_sources = load_scoped_vocabulary(manifest["core_reference"]["applies_to_discipline"])
                candidates = [{"id": t["id"], "name": t["canonical_term"]} for t in core["core_topics"]]
                by_id = {t["id"]: t for t in core["core_topics"]}
                for c in target_courses:
                    result = match_text_to_core_topics(c["title"], candidates, abbr, syn)
                    hits = []
                    if result["status"] == MATCH_STATUS_MATCHED:
                        hits = [(result["core_topic_id"], result["method"])]
                    elif result["status"] == MATCH_STATUS_COMPOUND:
                        hits = [(x["core_topic_id"], x["method"]) for x in result["components"] if x.get("core_topic_id")]
                    course_reference_matches.append({
                        "course_uid": c["course_uid"], "course_code": c["course_code"], "title": c["title"],
                        "status": result["status"], "vocabulary_applied": vocab_sources,
                        "core_topics": [{"core_topic": by_id[i]["canonical_term"], "aicte_code": by_id[i]["code"],
                                         "domain": by_id[i]["domain"], "page": by_id[i]["page"], "method": m} for i, m in hits],
                        "evidence_status": "REFERENCE_MAPPED" if hits else "INSUFFICIENT_EVIDENCE"})
            st.update({"topic_mappings": len(mappings),
                       "by_relationship": dict(Counter(m["relationship"] for m in mappings))})
        observer.count("topic_mappings", len(mappings))
        observer.count("topic_mappings_linked", sum(1 for m in mappings if m["target_uid"]))

    with observer.stage("gold.prerequisites") as st:
        prereqs = [dict(p, doc_id=courses_by_uid[p["course_uid"]]["doc_id"]) for d in usable_docs
                   for p in silver[d["doc_id"]]["prerequisites"]]
        courses_by_doc = defaultdict(list)
        for c in courses:
            courses_by_doc[c["doc_id"]].append(c)
        abbr, syn, _ = load_scoped_vocabulary(usable_docs[0]["discipline"]) if usable_docs else ({}, [], [])
        prereq_edges, unresolved_prereqs = resolve_prerequisites(prereqs, courses_by_doc, (abbr, syn))
        prereq_edges = enforce(prereq_edges, "edge", quarantine, "gold.contract")
        st.update({"statements": len(prereqs), "explicit_none": sum(1 for p in prereqs if p["is_explicit_none"]),
                   "resolved_edges": len(prereq_edges), "unresolved": len(unresolved_prereqs)})

    with observer.stage("gold.skills") as st:
        target_topics = [t for t in clean_topics if roles[t["doc_id"]] == "TARGET"]
        skill_candidates, skill_links, taxonomy_status = build_skill_layer(target_topics, topic_to_concept, esco_vocab)
        if esco_vocab:
            taxonomy_status = (f"TAXONOMY_LOADED: ESCO v1.2.1 ({esco_vocab.get('scope')}); curriculum tool/acronym "
                               "candidates are kept as before, ESCO mapping of skills is in industry/esco_mappings.jsonl")
        st.update({"candidates": len(skill_candidates), "taxonomy_status": taxonomy_status})
    observer.count("skill_candidates", len(skill_candidates))
    observer.count("taxonomy_skills", extraction["summary"]["esco_mapped_skills"] if extraction else 0)

    if gates["concept_drift"]["status"] == "ALLOWED":
        with observer.stage("gold.drift") as st:
            drift_rows, drift_counts = concept_drift(concepts, topics_by_uid, courses_by_uid, prev_doc["doc_id"],
                                                     target_doc["doc_id"], semesters, cfg["drift"])
            course_topics = defaultdict(list)
            for t in clean_topics:
                course_topics[t["course_uid"]].append(t["clean_text"])
            course_drift_rows, course_drift_counts, course_drift_excluded = course_drift(
                silver[prev_doc["doc_id"]]["courses"], silver[target_doc["doc_id"]]["courses"], semesters,
                course_topics, cfg["drift"].get("lineage"),
                lambda a, b: backend.similarity(backend.embed(a), backend.embed(b)))
            st.update({"concepts_compared": len(drift_rows), "concept_status": drift_counts, "course_status": course_drift_counts})

    programme_comparison = {"status": gates["programme_comparison"]["status"], "relation": curriculum_relation}
    programme_concept_rows, programme_course_rows = [], []
    if gates["programme_comparison"]["status"] == "ALLOWED":
        with observer.stage("gold.programme_comparison") as st:
            programme_concept_rows, pc_counts = concept_drift(concepts, topics_by_uid, courses_by_uid, prev_doc["doc_id"],
                                                              target_doc["doc_id"], semesters, cfg["drift"])
            pc_topics = defaultdict(list)
            for t in clean_topics:
                pc_topics[t["course_uid"]].append(t["clean_text"])
            programme_course_rows, pc_course_counts, pc_excluded = course_drift(
                silver[prev_doc["doc_id"]]["courses"], silver[target_doc["doc_id"]]["courses"], semesters,
                pc_topics, cfg["drift"].get("lineage"),
                lambda a, b: backend.similarity(backend.embed(a), backend.embed(b)))
            meta = lambda d: {k: d.get(k) for k in ("doc_id", "institution", "programme", "discipline", "specialization",
                                                    "curriculum_version", "academic_year")}
            programme_comparison.update(
                comparison=meta(prev_doc), current=meta(target_doc), comparable_semesters=semesters,
                concept_status=pc_counts, course_status=pc_course_counts, course_excluded=pc_excluded,
                note="two different programmes of one institution, compared on the semesters both documents cover; "
                     "differences are between programmes, not changes over time")
            st.update({"concepts_compared": len(programme_concept_rows), "course_status": pc_course_counts})

    industry_gold = None
    if extraction and gates["industry_demand"]["status"] == "ALLOWED":
        with observer.stage("industry.gold") as st:
            curriculum_ctx = {"topics_by_uid": {t["topic_uid"]: t for t in clean_topics}, "courses_by_uid": courses_by_uid,
                              "roles": roles, "topic_to_concept": topic_to_concept,
                              "target_doc": target_doc["doc_id"] if target_doc else None,
                              "reference_doc": (by_role.get("REFERENCE") or [{}])[0].get("doc_id"),
                              "previous_doc": prev_doc["doc_id"] if prev_doc else None}
            industry_gold = industry_stage.gold(industry_ingest["postings"], [j for j in job_sources if j["hash_verified"]],
                                                extraction, curriculum_ctx, cfg, cfg["existing_settings"], run_id,
                                                lambda: get_backend(cfg["semantic_backend"])[0])
            if gates["industry_gap"]["status"] != "ALLOWED":
                industry_gold.update(gaps=[], recommendations=[], suppressions=[], traces=[])
            st.update({"demand_rows": len(industry_gold["demand"]), "gaps": Counter(g["classification"] for g in industry_gold["gaps"]),
                       "recommendations": len(industry_gold["recommendations"]), "suppressed": len(industry_gold["suppressions"])})
        observer.count("industry_demand_skills", len(industry_gold["demand"]))
        observer.count("skill_gaps", len(industry_gold["gaps"]))
        observer.count("recommendations", len(industry_gold["recommendations"]))

    intelligence_out = None
    if extraction and esco_vocab and esco_vocab.get("_store") and industry_gold:
        with observer.stage("intelligence") as st:
            intelligence_out = intelligence_stage.run(
                store=esco_vocab["_store"], cfg=cfg, run_id=run_id, repo=REPO, documents=usable_docs,
                courses=courses, clean_topics=clean_topics, topics_by_uid=topics_by_uid, courses_by_uid=courses_by_uid,
                concepts=concepts, topic_to_concept=topic_to_concept, topic_mappings=mappings, prereq_edges=prereq_edges,
                drift_rows=drift_rows, outcomes=[o for d in usable_docs for o in silver[d["doc_id"]]["outcomes"]],
                extraction=extraction, industry_gold=industry_gold, postings=industry_ingest["postings"],
                # the earlier-version comparisons (coverage then vs now, curriculum-industry lag) need a version of
                # the same programme; another programme of the institution is not one
                target_doc=target_doc, prev_doc=prev_doc if same_programme else None,
                reference_doc=(by_role.get("REFERENCE") or [None])[0],
                adjudicator=adjudicator, semantic_info=semantic_info,
                peer_requests=manifest.get("requested_peer_sources", []), manifest=manifest,
                institution_doc=prev_doc if (same_programme or cross_programme) else None,
                curriculum_scope=curriculum_scope)
            st.update(intelligence_out["summary_counts"])

    peers_out = None
    if intelligence_out and target_doc is not None:
        with observer.stage("peers.semantic_benchmark") as st:
            comparison_docs = (by_role.get("REFERENCE") or []) + usable_peers
            peers_out = peer_stage.run(
                target_doc=target_doc, comparison_docs=comparison_docs,
                requested_peers=manifest.get("requested_peer_sources", []), health={d: h["status"] for d, h in health.items()},
                silver=silver, target_concepts=concepts, target_topics_by_uid={t["topic_uid"]: t for t in clean_topics},
                courses_by_uid=courses_by_uid, extraction=extraction, esco_vocab=esco_vocab, store=esco_vocab["_store"],
                demand=industry_gold["demand"], cfg=cfg, backend_factory=lambda: get_backend(cfg["semantic_backend"])[0],
                run_id=run_id, outcomes_by_doc=None, target_prereq_edges=prereq_edges,
                target_mentions=extraction["curriculum_mentions"])
            st.update({"peer_status": peers_out["status"]["status"], "comparisons": len(peers_out["comparisons"]),
                       "relations": len(peers_out["relations"])})
        if intelligence_out.get("benchmark") is not None:
            intelligence_out["benchmark"].update(peer_status=peers_out["status"]["status"],
                                                 peer_status_reason="see peers/peer_status.json and peers/peer_benchmark.json "
                                                                    "for the semantic peer benchmark; this block compares the "
                                                                    "REFERENCE document by skill depth only")

    industry_v2 = None
    if intelligence_out:
        with observer.stage("industry.v2") as st:
            store = esco_vocab["_store"]
            occ_rows, occ_summary = occupation_resolution.resolve(industry_ingest["postings"], extraction["posting_mentions"],
                                                                  extraction["skills"], store, cfg)
            sources_by_id = {j["source_id"]: j for j in job_sources}
            industry_v2 = industry_intel.run(industry_ingest["postings"], extraction, sources_by_id, cfg["existing_settings"],
                                             cfg, occupation_resolution.occupation_lookup(occ_rows), run_id)
            target_topics = {t["topic_uid"]: t for t in clean_topics if target_doc and t["doc_id"] == target_doc["doc_id"]}
            target_skill_uris = {u for rels in peer_stage._skill_subjects(extraction["curriculum_mentions"], target_topics,
                                                                           cfg["intelligence"]["coverage"]["max_item_words"]).values()
                                 for u, rel in rels.items() if rel in ("DIRECT", "PARTIAL")}
            eligible_keys = {k for k, sk in extraction["skills"].items() if sk["eligible_for_analytics"]}
            pairs = sorted({(m["skill_key"], m["source_uid"]) for m in extraction["posting_mentions"]
                            if m["skill_key"] in eligible_keys and m["mention_role"] == "SKILL" and m["sense_established"]})
            industry_v2["occupations"] = {
                "rows": occ_rows, "summary": occ_summary,
                "analysis": occupation_resolution.occupation_analysis(
                    occ_rows, pairs, extraction["skills"], store, target_skill_uris,
                    {r["skill_key"]: r for r in intelligence_out["depth"].get("TARGET", [])}, intelligence_out["gaps_v2"], cfg)}
            st.update({"populations": len(industry_v2["populations"]), "occupations_established": occ_summary["established"],
                       "trend_status": [p["trend_status"] for p in industry_v2["temporal"]["populations"]],
                       "clusters": len(industry_v2["clusters"]["clusters"])})

    if intelligence_out:
        # evidence status re-evaluated with the facts of the improvement stages (peer documents, occupation
        # resolution v2, the finest temporal granularity evaluated) -- offline, deterministic
        from app.knowledge_engine import acquisition as acq
        v2_pop = (industry_v2 or {}).get("temporal", {}).get("populations") or []
        evaluation_g = v2_pop[0]["granularity_evaluation"] if v2_pop else {}
        best_g = (max(evaluation_g, key=lambda g: (len(evaluation_g[g]["qualifying_periods"]), -["week", "month", "quarter"].index(g)))
                  if evaluation_g else "month")
        occ_sum = (industry_v2 or {}).get("occupations", {}).get("summary") or {}
        ev = acq.evaluate(REPO, {
            "postings_by_period": (evaluation_g.get(best_g) or {}).get("postings_by_period")
                                  or (industry_gold.get("temporal") or {}).get("postings_by_period"),
            "period_granularity": best_g,
            "peer_documents": len(usable_peers), "peer_doc_ids": [d["doc_id"] for d in usable_peers],
            "requested_peers_missing": [r["name"] for r in manifest.get("requested_peer_sources", []) if r.get("status") != "SUPPLIED"],
            "reference_documents": [d["doc_id"] for d in by_role.get("REFERENCE", [])],
            "postings": occ_sum.get("postings"), "established_postings": occ_sum.get("established"),
            "independent_labels": acq.count_independent_labels(REPO)}, cfg["existing_settings"], manifest)
        intelligence_out["evidence_status"] = ev
        intelligence_out["report"]["evidence_status"] = {e["requirement_id"]: e["status"] for e in ev}

    with observer.stage("gold.review_and_versioning") as st:
        families_by_uid = {f["family_uid"]: f for f in families}
        ref_status_by_concept = {r["concept_uid"]: r for r in concept_ref_status}
        review_queue = build_review_queue(concepts, families_by_uid, topics_by_uid, courses_by_uid, edges, ref_status_by_concept)
        registry = update_registry(REPO / "data/gold/knowledge/concept_registry.json", run_id, concepts)
        st.update({"review_items": Counter(i["priority"] for i in review_queue), "registry": registry})

    # ---------------- EVALUATION ----------------
    evaluation = {}
    with observer.stage("evaluation") as st:
        eval_dir = REPO / "data/evaluation"
        bench = _load_json(eval_dir / "semantic_benchmark.json")
        sample = _load_json(eval_dir / "topic_extraction_sample.json")
        golden = _load_json(eval_dir / "golden_pages.json")
        if bench and gates["concept_discovery"]["status"] == "ALLOWED":
            evaluation["semantic_relationships"] = evaluate_semantic_benchmark(bench, backend, cfg["mapping"]["min_similarity"])
        if sample:
            evaluation["topic_noise_filter"] = evaluate_topic_sample(sample, topics_by_uid)
        if golden:
            evaluation["golden_pages"] = evaluate_golden_pages(golden, all_topics)
        evaluation["similarity_score_distribution"] = confidence_distribution(mappings)
        ind_sample = _load_json(eval_dir / "industry_mention_sample.json")
        if ind_sample and extraction:
            evaluation["industry_skill_mentions"] = evaluate_industry_sample(
                ind_sample, {m["mention_uid"]: m for m in extraction["posting_mentions"]}, extraction["skills"])
        evaluation["industry_esco_benchmark"] = {
            "status": "NO_HUMAN_LABELLED_BENCHMARK",
            "note": "no human-labelled ESCO mapping benchmark exists; the assistant-labelled mention sample above is the only industry evaluation"}
        st["evaluated"] = sorted(evaluation)

    # ---------------- WRITE GOLD ----------------
    with observer.stage("gold.write") as st:
        g = gold_dir
        blocked = {name: v for name, v in gates.items() if v["status"] == "BLOCKED"}
        write_json(g / "health.json", {"documents": health, "industry": ind_health, "analytics_gates": gates})
        write_jsonl(g / "courses.jsonl", courses, sort_key=lambda r: r["course_uid"])
        write_jsonl(g / "concept_families.jsonl", families, sort_key=lambda r: r["family_uid"])
        write_jsonl(g / "concepts.jsonl", concepts, sort_key=lambda r: r["concept_uid"])
        write_jsonl(g / "concept_edges.jsonl", edges + prereq_edges, sort_key=lambda r: r["edge_uid"])
        write_jsonl(g / "topic_mappings.jsonl", mappings, sort_key=lambda r: r["mapping_uid"])
        write_jsonl(g / "concept_reference_status.jsonl", concept_ref_status, sort_key=lambda r: r["concept_uid"])
        write_jsonl(g / "course_correspondence.jsonl", correspondence, sort_key=lambda r: r["course_uid"])
        write_jsonl(g / "course_reference_matches.jsonl", course_reference_matches, sort_key=lambda r: r["course_uid"])
        write_jsonl(g / "prerequisites_unresolved.jsonl", unresolved_prereqs, sort_key=lambda r: r["prerequisite_uid"])
        write_jsonl(g / "skill_candidates.jsonl", skill_candidates, sort_key=lambda r: r["skill_candidate_uid"])
        write_jsonl(g / "concept_skill_links.jsonl", skill_links, sort_key=lambda r: r["edge_uid"])
        write_jsonl(g / "concept_drift.jsonl", drift_rows)
        write_jsonl(g / "course_drift.jsonl", course_drift_rows)
        if programme_comparison["status"] == "ALLOWED":
            write_jsonl(g / "programme_comparison" / "concept_differences.jsonl", programme_concept_rows)
            write_jsonl(g / "programme_comparison" / "course_differences.jsonl", programme_course_rows)
        write_jsonl(g / "review_queue.jsonl", review_queue)
        write_json(g / "review_queue_high_priority.json", [i for i in review_queue if i["priority"] == "HIGH"])
        write_jsonl(g / "quarantine.jsonl", quarantine.items)
        write_json(g / "evaluation.json", evaluation)
        for name, v in blocked.items():
            write_json(g / "blocked" / f"{name}.json", {"output": name, "status": "BLOCKED", "reasons": v["reasons"],
                                                        "note": "no numbers are produced for a blocked output"})
        if industry_ingest:
            write_industry_gold(g / "industry", industry_ingest, extraction, esco_audit, ind_health, industry_gold)
        if intelligence_out:
            intelligence_stage.write(g / "intelligence", intelligence_out)
        if peers_out:
            write_peers_gold(g / "peers", peers_out)
        if industry_v2:
            write_industry_v2_gold(g / "industry_v2", industry_v2)
        write_csv(g / "exports/concepts.csv", sorted(concepts, key=lambda c: c["concept_uid"]), ["concept_uid", "name", "discipline", "family_uid", "support",
                  "source_roles", "evidence_status", "review_priority"])
        write_csv(g / "exports/topic_mappings.csv",
                  [{**m, "target_text": (m.get("evidence") or {}).get("reference_text")} for m in mappings],
                  ["mapping_uid", "source_text", "relationship", "similarity_score", "target_text", "method", "evidence_status"])
        write_csv(g / "exports/concept_drift.csv", drift_rows, ["concept", "status", "previous_support", "target_support"])
        write_csv(g / "exports/course_drift.csv", course_drift_rows, ["status", "previous_code", "target_code", "title",
                  "previous_semester", "target_semester"])
        st["files"] = sum(1 for _ in g.rglob("*") if _.is_file())
    digest = content_digest(gold_dir)

    summary = {
        "run_id": run_id, "pipeline_version": PIPELINE_VERSION, "parser_fingerprint": fingerprint,
        "code_fingerprint": code_fp, "semantic_identity": semantic_id,
        "config_hash": cfg_hash, "config": cfg, "semantic_backend": backend.describe(),
        "backend_resolution": backend_resolution, "backends_available": available_backends(),
        "numeric_environment": numeric_environment(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "documents": [{k: d[k] for k in ("doc_id", "role", "institution", "programme", "discipline", "curriculum_version",
                                           "academic_year", "path", "sha256", "page_count", "bytes", "source_url")}
                      | {k: d.get(k) for k in ("specialization", "degree_level") if d.get(k)} for d in documents],
        "document_summaries": doc_summaries, "health": {d: h["status"] for d, h in health.items()},
        "analytics_gates": gates, "comparable_semesters_for_drift": semesters if same_programme else [],
        **({"analysis_scope": manifest["analysis_scope"]} if manifest.get("analysis_scope") else {}),
        "discipline_profile": discipline_profiles.profile_ref(target_profile),
        **({"industry_exclusion": industry_exclusion} if industry_exclusion else {}),
        **({"not_comparable_documents": [d["doc_id"] for d in not_comparable]} if not_comparable else {}),
        "programme_comparison": programme_comparison, "curriculum_scope": curriculum_scope,
        "family_selection": family_selection, "families": len(families), "concepts": len(concepts),
        "concepts_by_priority": dict(Counter(c["review_priority"] for c in concepts)),
        "concepts_by_roles": dict(Counter("+".join(c["source_roles"]) for c in concepts)),
        "concept_reference_status": dict(Counter(r["status"] for r in concept_ref_status)),
        "edges_by_relationship": dict(Counter(e["relationship"] for e in edges + prereq_edges)),
        "topic_mappings_by_relationship": dict(Counter(m["relationship"] for m in mappings)),
        "topic_mappings_by_evidence_status": dict(Counter(m["evidence_status"] for m in mappings)),
        "course_reference_matches": dict(Counter(r["status"] for r in course_reference_matches)),
        "prerequisites": {"resolved_edges": len(prereq_edges), "unresolved": len(unresolved_prereqs)},
        "skills": {"taxonomy_status": taxonomy_status, "candidates": dict(Counter(s["candidate_type"] for s in skill_candidates))},
        "concept_drift": drift_counts, "course_drift": course_drift_counts, "course_drift_excluded": course_drift_excluded,
        "review_decisions_applied": len(applied_decisions), "quarantine": quarantine.summary(),
        "industry": industry_report(industry_ingest, extraction, esco_audit, ind_health, industry_gold),
        "intelligence": intelligence_out["report"] if intelligence_out else {"status": "NOT_RUN"},
        "industry_v2": ({"populations": industry_v2["populations"],
                         "trend_status": {p["population_id"]: p["trend_status"] for p in industry_v2["temporal"]["populations"]},
                         "occupations": {k: industry_v2["occupations"]["summary"][k] for k in
                                         ("by_state", "established", "established_by_title", "established_by_context",
                                          "title_contradicted_by_context", "established_share", "established_share_title_only")},
                         "clusters": len(industry_v2["clusters"]["clusters"])} if industry_v2 else {"status": "NOT_RUN"}),
        "peers": ({"status": peers_out["status"]["status"],
                   "comparisons": {c["comparison_doc_id"]: {"role": c["comparison_role"], "scope": c["scope"],
                                                            "coverage_levels": {k: (v.get("pct") if isinstance(v, dict) and "pct" in v else v)
                                                                                for k, v in c["coverage_levels"].items()}}
                                   for c in peers_out["comparisons"]}} if peers_out else {"status": "NOT_RUN"}),
        "content_digest": digest,
    }
    report = {**summary, "observability": observer.report()}
    write_json(gold_dir / "run_report.json", report)
    (gold_dir / "run_report.md").write_text(render_markdown(report), encoding="utf-8")
    # pointer read by the API service layer; outside the run directory so it
    # never affects the run's content digest
    if set_latest:
        write_json(gold_dir.parent / "latest_run.json", {"run_id": run_id, "generated_at": summary["generated_at"],
                                                         "content_digest": digest})

    if record_baseline:
        for s in doc_summaries.values():
            if health[s["doc_id"]]["status"] != FAIL:
                baselines["documents"][s["sha256"]] = {
                    "doc_id": s["doc_id"], **{k: s[k] for k in ("valid_courses", "units", "clean_topics", "outcomes")},
                    "recorded_at": summary["generated_at"], "pipeline_version": PIPELINE_VERSION,
                    "parser_fingerprint": fingerprint, "recorded_from_run": run_id}
        if ind_health and ind_health["status"] != FAIL:
            baselines.setdefault("industry", {})[ind_health["inputs_key"]] = {
                **{k: ind_health["summary"][k] for k in ("eligible_postings", "mentions", "unique_skills_eligible", "esco_mapped_skills")},
                "recorded_at": summary["generated_at"], "pipeline_version": PIPELINE_VERSION, "recorded_from_run": run_id}
        write_json(baselines_path, baselines)

    if publish:
        from app.knowledge_engine.db_publish import publish as do_publish
        bundle = gold_bundle(run_id, summary, documents, courses, silver, usable_docs, families, concepts, edges + prereq_edges,
                             mappings, drift_rows, review_queue)
        bundle.update(industry_bundle(run_id, industry_ingest, extraction, esco_vocab, industry_gold))
        if intelligence_out:
            bundle.update(intelligence_stage.bundle(run_id, intelligence_out, extraction["skills"], esco_vocab["_store"]))
        extra = improvement_bundle(run_id, documents, peers_out, industry_v2, extraction["skills"] if extraction else {},
                                   esco_vocab["_store"] if esco_vocab and esco_vocab.get("_store") else None, cfg)
        occ_rows = {r["occupation_uri"]: r for r in bundle.get("esco_occupation", []) + extra.pop("esco_occupation", [])}
        bundle["esco_occupation"] = [occ_rows[u] for u in sorted(occ_rows)]
        bundle.update(extra)
        with observer.stage("publish.postgres") as st:
            db_report = do_publish(bundle, REPO / "data/gold/knowledge" / "_publish_staging" / run_id, dsn=dsn, local=dsn is None)
            st["status"] = db_report["status"]
        report["publish"] = db_report
        report["observability"] = observer.report()
        write_json(gold_dir / "observability.json", report["observability"])
        write_json(gold_dir / "publish_report.json", db_report)
    else:
        write_json(gold_dir / "observability.json", report["observability"])
    return report


def improvement_bundle(run_id, documents, peers_out, industry_v2, skills, store, cfg):
    """Rows for the improvement-release tables (peer benchmark, temporal trends, occupation resolution)."""
    out = {}
    sha = {d["doc_id"]: d["sha256"] for d in documents}
    if peers_out:
        out["peer_comparison"] = [{
            "run_id": run_id, "comparison_doc_sha256": sha[c["comparison_doc_id"]], "comparison_role": c["comparison_role"],
            "peer_status": peers_out["status"]["status"],
            "exact_lexical_pct": c["coverage_levels"]["exact_lexical"]["pct"], "normalized_pct": c["coverage_levels"]["normalized"]["pct"],
            "semantic_concept_pct": c["coverage_levels"]["semantic_concept"]["pct"],
            "semantic_related_pct": c["coverage_levels"]["semantic_related"]["pct"],
            "target_concepts": c["scope"]["target_concepts"], "comparison_concepts": c["scope"]["concepts"],
            "course_context_min": cfg["peers"]["course_context_min_similarity"]} for c in peers_out["comparisons"]]
        out["peer_relation"] = [{
            "relation_uid": r["relation_uid"], "run_id": run_id, "comparison_doc_sha256": sha[r["comparison_doc_id"]],
            "target_concept_uid": r["target"]["concept_uid"], "comparison_unit_uid": r["comparison"]["concept_uid"],
            "target_concept": r["target"]["concept"], "comparison_concept": r["comparison"]["concept"],
            "relationship": r["relationship"], "evidence_state": r["evidence_state"],
            "similarity": r["evidence"]["similarity"], "course_context": r["evidence"]["course_context"],
            "model_consulted": r["semantic_decision"]["model_consulted"]} for r in peers_out["relations"]]
    if industry_v2:
        pops = industry_v2["temporal"]["populations"]
        out["temporal_population"] = [{"run_id": run_id, "population_id": p["population_id"], "eligible_postings": p["eligible_postings"],
                                       "granularity": p["granularity"], "trend_status": p["trend_status"],
                                       "date_earliest": p["date_range"]["earliest"], "date_latest": p["date_range"]["latest"]}
                                      for p in pops]
        out["skill_trend"] = [{"run_id": run_id, "population_id": r["population_id"], "segment": r["segment"],
                               "skill_uid": skills[r["skill_key"]]["skill_uid"], "trend_state": r["trend_state"],
                               "periods": r["periods"], "pp_change": r.get("pp_change"), "relative_change": r.get("relative_change"),
                               "total_postings": r["total_postings_with_skill"]} for r in industry_v2["temporal"]["rows"]]
        occ = industry_v2["occupations"]["rows"]
        out["occupation_resolution"] = [{"run_id": run_id, "posting_uid": r["posting_uid"], "state": r["state"],
                                         "established": r["established"], "established_by": r["established_by"],
                                         "occupation_uri": r["occupation_uri"], "context_support": r["context_support"],
                                         "posting_context_skills": r["posting_context_skills"]} for r in occ]
        if store is not None:
            out["esco_occupation"] = [{"occupation_uri": u, "pref_label": store["occupations"][u]["pref_label"],
                                       "isco_code": store["occupations"][u]["isco_code"]}
                                      for u in sorted({r["occupation_uri"] for r in occ if r["occupation_uri"]})]
    return out


def gold_bundle(run_id, summary, documents, courses, silver, usable_docs, families, concepts, edges, mappings, drift_rows, review_queue):
    sha_by_doc = {d["doc_id"]: d["sha256"] for d in documents}
    units = [u for d in usable_docs for u in silver[d["doc_id"]]["units"]]
    topics = [t for d in usable_docs for t in silver[d["doc_id"]]["topics"]]
    return {
        "pipeline_run": [{"run_id": run_id, "pipeline_version": summary["pipeline_version"], "config_hash": summary["config_hash"],
                          "semantic_backend": summary["semantic_backend"]["name"], "content_digest": summary["content_digest"]}],
        "document": [{"sha256": d["sha256"], "doc_id": d["doc_id"], "role": d["role"], "institution": d["institution"],
                      "programme": d["programme"], "discipline": d["discipline"], "curriculum_version": d["curriculum_version"],
                      "page_count": d["page_count"]} for d in documents],
        "course": [{**c, "doc_sha256": sha_by_doc[c["doc_id"]]} for c in courses],
        "unit": units, "topic": topics,
        "concept_family": families, "concept": concepts,
        "concept_member": [{"concept_uid": c["concept_uid"], "topic_uid": u} for c in concepts for u in c["member_topic_uids"]],
        "concept_run": [{"run_id": run_id, "concept_uid": c["concept_uid"]} for c in concepts],
        "edge": [e for e in edges if e["relationship"] in ("BELONGS_TO_FAMILY", "PARENT", "CO_OCCURS_IN_UNIT", "PREREQUISITE_OF")],
        "topic_mapping": [{**m, "source_topic_uid": m["source_uid"], "target_topic_uid": m["target_uid"]} for m in mappings],
        "concept_drift": [{"run_id": run_id, "concept_uid": r["concept_uid"], "status": r["status"],
                           "previous_support": r["previous_support"], "target_support": r["target_support"]} for r in drift_rows],
        "review_item": [{"review_item_uid": i["review_item_uid"], "priority": i["priority"], "review_decision": i["review_decision"],
                         "reviewer": i["reviewer"], "decided_at": i["decided_at"]} for i in review_queue],
    }


def write_industry_v2_gold(d, v2):
    write_json(d / "temporal_populations.json", {"populations": v2["temporal"]["populations"], "denominator": v2["denominator"]})
    write_jsonl(d / "skill_trends.jsonl", v2["temporal"]["rows"], sort_key=lambda r: (r["population_id"], r["segment"], r["skill_key"]))
    write_jsonl(d / "segment_trend_scopes.jsonl", v2["temporal"]["segments"], sort_key=lambda r: (r["population_id"], r["segment"]))
    write_json(d / "dimension_demand.json", v2["dimensions"])
    write_json(d / "distributions.json", v2["distributions"])
    write_jsonl(d / "mentions_vs_postings.jsonl", v2["mentions_vs_postings"], sort_key=lambda r: r["skill_key"])
    write_json(d / "skill_clusters.json", v2["clusters"])
    write_jsonl(d / "occupation_resolution.jsonl", v2["occupations"]["rows"], sort_key=lambda r: r["posting_uid"])
    write_json(d / "occupation_summary.json", v2["occupations"]["summary"])
    write_json(d / "occupation_analysis.json", v2["occupations"]["analysis"])


def write_peers_gold(d, out):
    write_json(d / "peer_status.json", out["status"])
    write_json(d / "peer_benchmark.json", {"status": out["status"]["status"], "method": out["method"], "config": out["config"],
                                           "comparisons": out["comparisons"]})
    write_jsonl(d / "peer_relations.jsonl", out["relations"], sort_key=lambda r: r["relation_uid"])
    write_jsonl(d / "peer_review_candidates.jsonl", out["pending_review"], sort_key=lambda r: r["relation_uid"])


def write_industry_gold(d, ingest_result, extraction, esco_audit, ind_health, ig):
    esco_audit = esco_audit or {"status": "NOT_LOADED"}
    write_json(d / "esco_audit.json", esco_audit)
    # kept for readers of earlier runs: the delta part of the audit (the whole audit when only the delta was used)
    write_json(d / "esco_delta_audit.json", esco_audit.get("delta_change_information") or esco_audit)
    write_json(d / "industry_health.json", ind_health)
    write_json(d / "ingestion_summary.json", ingest_result["summary"])
    write_jsonl(d / "posting_records.jsonl", ingest_result["records"], sort_key=lambda r: (r["source_file"], r["row_number"]))
    write_jsonl(d / "postings.jsonl", [{k: v for k, v in p.items() if k not in ("raw_description", "clean_description")}
                                       for p in ingest_result["postings"]], sort_key=lambda r: r["posting_uid"])
    if extraction:
        write_jsonl(d / "skill_mentions.jsonl", extraction["posting_mentions"], sort_key=lambda r: r["mention_uid"])
        write_jsonl(d / "curriculum_skill_mentions.jsonl", extraction["curriculum_mentions"], sort_key=lambda r: r["mention_uid"])
        write_jsonl(d / "esco_mappings.jsonl", list(extraction["mappings"].values()), sort_key=lambda r: r["normalized_label"])
        write_jsonl(d / "skills.jsonl", list(extraction["skills"].values()), sort_key=lambda r: r["skill_key"])
    if ig is None:
        write_json(d / "blocked.json", {"status": "BLOCKED", "note": "industry GOLD analytics were not produced; see health.json gates"})
        return
    write_json(d / "population_scope.json", ig["scope"])
    write_json(d / "temporal_scope.json", ig["temporal"])
    write_json(d / "segments.json", ig["segments"])
    write_jsonl(d / "industry_demand.jsonl", ig["demand"], sort_key=lambda r: r["skill_key"])
    write_jsonl(d / "qualification_mentions.jsonl", ig["qualification_mentions"], sort_key=lambda r: r["skill_key"])
    write_jsonl(d / "segment_demand.jsonl", ig["segment_demand"], sort_key=lambda r: (r["segment"], r["skill_key"]))
    write_jsonl(d / "curriculum_skill_coverage.jsonl", ig["coverage"], sort_key=lambda r: (r["role"], r["skill_key"]))
    write_jsonl(d / "skill_gaps.jsonl", ig["gaps"], sort_key=lambda r: r["skill_key"])
    write_jsonl(d / "recommendations.jsonl", ig["recommendations"], sort_key=lambda r: r["recommendation_uid"])
    write_jsonl(d / "recommendation_suppressions.jsonl", ig["suppressions"], sort_key=lambda r: r["skill_key"])
    write_jsonl(d / "evidence_traces.jsonl", ig["traces"], sort_key=lambda r: r["skill_key"])
    write_jsonl(d / "industry_review_queue.jsonl", ig["review_queue"])
    warning = ig["scope"]["representativeness_warning"]
    write_csv(d / "exports/industry_demand.csv", [{**r, "scope_warning": warning} for r in ig["demand"]],
              ["skill_key", "skill_label", "esco_status", "posting_count", "eligible_postings", "posting_prevalence_pct",
               "company_count", "eligible_companies", "company_prevalence_pct", "support_state", "scope_warning"])
    write_csv(d / "exports/skill_gaps.csv", [{**r, "scope_warning": warning} for r in ig["gaps"]],
              ["skill_key", "skill_label", "classification", "evidence_state", "industry_count", "industry_population",
               "industry_prevalence_pct", "curriculum_count", "curriculum_population", "curriculum_coverage_pct",
               "support_state", "esco_status", "scope_warning"])
    # suppressions are held in suppression_uid order, which derives from the run id: export them by skill key so the
    # file does not reorder with every new run id
    write_csv(d / "exports/recommendations.csv", sorted(ig["recommendations"], key=lambda r: r["skill_key"])
              + sorted(ig["suppressions"], key=lambda r: r["skill_key"]),
              ["skill_key", "skill_label", "recommendation_state", "action_type", "target_level", "target_course_codes",
               "classification", "support_state", "reasons", "uncertainty"])


def industry_report(ingest_result, extraction, esco_audit, ind_health, ig):
    if ingest_result is None:
        return {"status": "NO_INDUSTRY_SOURCES"}
    out = {"ingestion": ingest_result["summary"], "health": ind_health["status"] if ind_health else None,
           "esco_reconstruction_scope": (esco_audit or {}).get("reconstruction_scope"),
           "esco_skill_concepts": (esco_audit or {}).get("skill_concepts_reconstructed"),
           "esco_taxonomy_mode": (esco_audit or {}).get("taxonomy_mode"),
           "extraction": extraction["summary"] if extraction else None}
    if ig:
        out.update({
            "population_scope": {k: ig["scope"][k] for k in ("eligible_postings", "source_files", "geographic_scope", "date_range",
                                                            "distinct_companies", "distinct_job_titles", "representativeness_warning")},
            "demand_skills": len(ig["demand"]),
            "demand_by_support_state": dict(Counter(d["support_state"] for d in ig["demand"])),
            "temporal": ig["temporal"]["trend_status"],
            "segments": {"k": ig["segments"]["selection"]["chosen"], "sizes": [s["size"] for s in ig["segments"]["segments"]]},
            "coverage_populations": ig["coverage_populations"],
            "gaps_by_classification": dict(Counter(g["classification"] for g in ig["gaps"])),
            "gaps_by_evidence_state": dict(Counter(g["evidence_state"] for g in ig["gaps"])),
            "recommendations": len(ig["recommendations"]),
            "recommendations_by_action": dict(Counter(r["action_type"] for r in ig["recommendations"])),
            "suppressions": len(ig["suppressions"]),
            "suppressions_by_reason": dict(Counter(w["code"] for s in ig["suppressions"] for w in s["reasons"])),
            "industry_review_items": dict(Counter(i["kind"] for i in ig["review_queue"])),
        })
    return out


def industry_bundle(run_id, ingest_result, extraction, esco_vocab, ig):
    if not ingest_result or not extraction or not ig:
        return {}
    skills = extraction["skills"]
    used_uris = {s["esco_uri"] for s in skills.values() if s["esco_uri"]}
    used_uris |= {s["taxonomy_candidate_uri"] for s in skills.values() if s.get("taxonomy_candidate_uri")}
    used_uris |= {c["uri"] for m in extraction["mappings"].values() for c in m.get("candidates", []) if c.get("uri") in esco_vocab["concepts"]}
    scope = ig["scope"]
    return {
        "population_scope": [{"scope_uid": scope["scope_uid"], "run_id": run_id, "segment": "ALL_POSTINGS",
                              "eligible_postings": scope["eligible_postings"], "distinct_companies": scope["distinct_companies"],
                              "date_earliest": scope["date_range"]["earliest"], "date_latest": scope["date_range"]["latest"],
                              "geographic_scope": scope["geographic_scope"], "source_files": scope["source_files"],
                              "representativeness_warning": scope["representativeness_warning"]}],
        "job_posting": [{k: p[k] for k in ("posting_uid", "identity", "platform", "external_id", "url", "source_id", "source_file",
                                           "source_sha256", "row_number", "job_title", "company_name", "company_key",
                                           "location", "country_code", "posted_date", "raw_description_sha256", "evidence_status")}
                        for p in ingest_result["postings"]],
        "esco_concept": [{"esco_uri": u, "pref_label": esco_vocab["concepts"][u]["pref_label"],
                          "taxonomy_scope": esco_vocab.get("scope", "PARTIAL_DELTA_SUBSET")} for u in sorted(used_uris)],
        "skill": [{"skill_uid": s["skill_uid"], "skill_key": s["skill_key"], "label": s["label"], "esco_status": s["esco_status"],
                   "esco_uri": s["esco_uri"], "mapping_method": s["mapping_method"], "skill_category": s["skill_category"],
                   "taxonomy_candidate_uri": s.get("taxonomy_candidate_uri")}
                  for s in skills.values()],
        "skill_run": [{"run_id": run_id, "skill_uid": s["skill_uid"], "esco_status": s["esco_status"], "esco_uri": s["esco_uri"],
                       "mapping_method": s["mapping_method"], "skill_category": s["skill_category"],
                       "taxonomy_candidate_uri": s.get("taxonomy_candidate_uri")} for s in skills.values()],
        "skill_mention_run": [{"run_id": run_id, "mention_uid": m["mention_uid"], "posting_uid": m["source_uid"],
                               "skill_uid": skills[m["skill_key"]]["skill_uid"], "mention_role": m["mention_role"],
                               "sense_state": m["sense_state"]} for m in extraction["posting_mentions"]],
        "skill_mention": [{"mention_uid": m["mention_uid"], "posting_uid": m["source_uid"], "skill_uid": skills[m["skill_key"]]["skill_uid"],
                           "raw_mention": m["raw_mention"], "span_start": m["span"][0], "span_end": m["span"][1],
                           "extraction_method": m["method"], "run_id": run_id, "mention_role": m["mention_role"],
                           "sense_state": m["sense_state"]} for m in extraction["posting_mentions"]],
        "industry_demand": [{"run_id": run_id, "scope_uid": d["population_scope_ref"], "skill_uid": skills[d["skill_key"]]["skill_uid"],
                             "posting_count": d["posting_count"], "eligible_postings": d["eligible_postings"],
                             "posting_prevalence_pct": d["posting_prevalence_pct"], "company_count": d["company_count"],
                             "eligible_companies": d["eligible_companies"], "company_prevalence_pct": d["company_prevalence_pct"],
                             "support_state": d["support_state"]} for d in ig["demand"]],
        "skill_gap": [{"gap_uid": g["gap_uid"], "run_id": run_id, "scope_uid": g["population_scope_ref"],
                       "skill_uid": skills[g["skill_key"]]["skill_uid"], "classification": g["classification"],
                       "evidence_state": g["evidence_state"], "industry_count": g["industry_count"],
                       "industry_population": g["industry_population"], "industry_prevalence_pct": g["industry_prevalence_pct"],
                       "curriculum_count": g["curriculum_count"], "curriculum_population": g["curriculum_population"],
                       "curriculum_coverage_pct": g["curriculum_coverage_pct"], "support_state": g["support_state"]}
                      for g in ig["gaps"]],
        "recommendation": [{"recommendation_uid": r["recommendation_uid"], "gap_uid": r["gap_uid"], "run_id": run_id,
                            "state": r["recommendation_state"], "action_type": r["action_type"],
                            "target_course_codes": r["target_course_codes"], "evidence_status": r["evidence_status"],
                            "is_source_evidence": False} for r in ig["recommendations"]]
                          + [{"recommendation_uid": s["suppression_uid"], "gap_uid": s["gap_uid"], "run_id": run_id,
                              "state": "SUPPRESSED", "action_type": None, "target_course_codes": [],
                              "evidence_status": s["evidence_status"], "is_source_evidence": False} for s in ig["suppressions"]],
    }


def render_markdown(r):
    lines = [f"# Knowledge-engine run `{r['run_id']}`", "",
             f"Pipeline `{r['pipeline_version']}` · parser `{r['parser_fingerprint']}` · config `{r['config_hash'][:12]}` · "
             f"backend `{r['semantic_backend']['name']}` ({r['semantic_backend']['semantic_capability']}) · "
             f"content digest `{r['content_digest'][:16]}`", "", "## Documents", "",
             "| doc | role | version | pages | SHA-256 | health |", "|---|---|---|---|---|---|"]
    for d in r["documents"]:
        lines.append(f"| {d['doc_id']} | {d['role']} | {d['curriculum_version']} | {d['page_count']} | `{d['sha256'][:12]}…` | {r['health'][d['doc_id']]} |")
    lines += ["", "## Funnel", "", "| stage | count |", "|---|---|"]
    for k, v in r["observability"]["funnel"].items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Analytics gates", "", "| output | status | reason |", "|---|---|---|"]
    for name, g in r["analytics_gates"].items():
        lines.append(f"| {name} | {g['status']} | {'; '.join(g['reasons'])} |")
    lines += ["", "## Stages", "", "| stage | doc | seconds | peak heap MB | RSS MB | status |", "|---|---|---|---|---|---|"]
    for s in r["observability"]["stages"]:
        lines.append(f"| {s['stage']} | {s.get('doc_id', '')} | {s['duration_s']} | {s['peak_python_heap_mb']} | {s['rss_mb']} | {s.get('status')} |")
    lines += ["", "## Results", "", "```json", json.dumps({k: r[k] for k in (
        "families", "concepts", "concepts_by_priority", "concept_reference_status", "topic_mappings_by_relationship",
        "course_reference_matches", "prerequisites", "skills", "concept_drift", "course_drift", "quarantine")}, indent=2), "```", ""]
    return "\n".join(lines)
