"""
Read-only service over a GOLD knowledge run (data/gold/knowledge/<run_id>).

The API layer calls these functions; they return exactly what the pipeline
wrote -- nothing is recomputed, estimated or filled in here. Rules kept
from the pipeline:
  - a BLOCKED analytics gate is returned as BLOCKED with its reasons, never
    as numbers;
  - None stays None (e.g. an unmapped topic has similarity_score None, not 0);
  - every concept/topic carries its provenance (document, course, page).

Topics live in SILVER (data/silver/curricula/<doc_id>/<sha16>/topics.jsonl);
the run's courses name the document hash, so the service reads exactly the
SILVER files the run was built from.
"""
import json
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GOLD_ROOT = REPO / "data" / "gold" / "knowledge"
SILVER_ROOT = REPO / "data" / "silver" / "curricula"


class RunNotFound(LookupError):
    pass


class NoAnalysisYet(RunNotFound):
    """No analysis exists on this machine yet (a fresh clone): not an error in a request. The API answers 404 with
    code NO_ANALYSIS_YET so the app can say how to start."""


class InvalidRunId(RunNotFound):
    """A malformed run id cannot name any run (subclass of RunNotFound; the API answers 400 for it)."""


def not_found_code(exc):
    return "NO_ANALYSIS_YET" if isinstance(exc, NoAnalysisYet) else "RUN_NOT_FOUND"


RUN_ID_RE = __import__("re").compile(r"^[0-9a-f]{16}$")


def check_run_id(run_id):
    """A run id is 16 lowercase hex characters; anything else (e.g. a path) is rejected before any file access."""
    if run_id is not None and not RUN_ID_RE.match(run_id):
        raise InvalidRunId("run_id must be 16 lowercase hexadecimal characters")
    return run_id


def _jsonl(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def latest_run_id(gold_root=None):
    root = Path(gold_root or GOLD_ROOT)
    pointer = _json(root / "latest_run.json")
    if pointer and (root / pointer["run_id"] / "run_report.json").exists():
        return pointer["run_id"]
    runs = sorted((p for p in root.iterdir() if (p / "run_report.json").exists()),
                  key=lambda p: (p / "run_report.json").stat().st_mtime) if root.exists() else []
    if not runs:
        raise NoAnalysisYet("no analysis has been run on this machine yet: upload a curriculum in the app (New "
                            "analysis), or run scripts/pipeline/run_knowledge_pipeline.py with your evidence in data/raw")
    return runs[-1].name


class KnowledgeRun:
    def __init__(self, run_id=None, gold_root=None, silver_root=None):
        self.gold_root = Path(gold_root or GOLD_ROOT)
        self.silver_root = Path(silver_root or SILVER_ROOT)
        self.run_id = check_run_id(run_id) or latest_run_id(self.gold_root)
        self.dir = self.gold_root / self.run_id
        if not (self.dir / "run_report.json").exists():
            raise RunNotFound(f"run {self.run_id} not found")
        self.report = _json(self.dir / "run_report.json")
        self.health = _json(self.dir / "health.json", {})
        self.courses = {c["course_uid"]: c for c in _jsonl(self.dir / "courses.jsonl")}
        self.families = {f["family_uid"]: f for f in _jsonl(self.dir / "concept_families.jsonl")}
        self.concepts = {c["concept_uid"]: c for c in _jsonl(self.dir / "concepts.jsonl")}
        self.edges = _jsonl(self.dir / "concept_edges.jsonl")
        self.mappings = _jsonl(self.dir / "topic_mappings.jsonl")
        self.reference_status = {r["concept_uid"]: r for r in _jsonl(self.dir / "concept_reference_status.jsonl")}
        self.drift = {r["concept_uid"]: r for r in _jsonl(self.dir / "concept_drift.jsonl")}
        self.review = _jsonl(self.dir / "review_queue.jsonl")
        self.skill_candidates = _jsonl(self.dir / "skill_candidates.jsonl")
        self.concept_skill_links = _jsonl(self.dir / "concept_skill_links.jsonl")
        ind = self.dir / "industry"
        self.industry = {
            "scope": _json(ind / "population_scope.json"), "health": _json(ind / "industry_health.json"),
            "esco_audit": _json(ind / "esco_audit.json") or _json(ind / "esco_delta_audit.json"), "temporal": _json(ind / "temporal_scope.json"),
            "segments": _json(ind / "segments.json"), "demand": _jsonl(ind / "industry_demand.jsonl"),
            "skills": {s["skill_key"]: s for s in _jsonl(ind / "skills.jsonl")},
            "mappings": _jsonl(ind / "esco_mappings.jsonl"), "gaps": _jsonl(ind / "skill_gaps.jsonl"),
            "recommendations": _jsonl(ind / "recommendations.jsonl"),
            "suppressions": _jsonl(ind / "recommendation_suppressions.jsonl"),
            "traces": {t["skill_key"]: t for t in _jsonl(ind / "evidence_traces.jsonl")},
            "review": _jsonl(ind / "industry_review_queue.jsonl"), "coverage": _jsonl(ind / "curriculum_skill_coverage.jsonl"),
            "qualification": _jsonl(ind / "qualification_mentions.jsonl"),
        } if ind.exists() else None
        self.topics = self._load_topics()
        self.topic_to_concept = {t: c["concept_uid"] for c in self.concepts.values() for t in c["member_topic_uids"]}

    def _load_topics(self):
        topics = {}
        for doc_id, sha in sorted({(c["doc_id"], c["source_sha256"]) for c in self.courses.values()}):
            for t in _jsonl(self.silver_root / doc_id / sha[:16] / "topics.jsonl"):
                if t["course_uid"] in self.courses:
                    topics[t["topic_uid"]] = t
        return topics

    # ---------------- helpers ----------------
    def gate(self, name):
        return (self.health.get("analytics_gates") or {}).get(name, {"status": "UNKNOWN", "reasons": ["gate not recorded"]})

    def _topic_view(self, t):
        course = self.courses.get(t["course_uid"], {})
        return {"topic_uid": t["topic_uid"], "text": t["clean_text"], "raw_text": t["raw_text"],
                "noise_label": t["noise_label"], "evidence_status": t["evidence_status"],
                "concept_uid": self.topic_to_concept.get(t["topic_uid"]),
                "provenance": {"doc_id": t["doc_id"], "course_code": t["course_code"], "course_title": course.get("title"),
                               "semester": course.get("semester"), "unit": t.get("unit_label"), "page": t["page_number"],
                               "extraction_method": t["extraction_method"], "source_sha256": course.get("source_sha256")}}

    def _concept_summary(self, c):
        return {"concept_uid": c["concept_uid"], "name": c["name"], "discipline": c["discipline"],
                "family": self.families.get(c["family_uid"], {}).get("name"), "support": c["support"],
                "source_roles": c["source_roles"], "evidence_status": c["evidence_status"],
                "review_priority": c["review_priority"],
                "reference_status": self.reference_status.get(c["concept_uid"], {}).get("status"),
                "drift_status": self.drift.get(c["concept_uid"], {}).get("status")}


@lru_cache(maxsize=4)
def load_run(run_id=None):
    return KnowledgeRun(run_id)


def _page(items, limit, offset):
    return {"total": len(items), "limit": limit, "offset": offset, "items": items[offset:offset + limit]}


# ---------------- queries used by the API ----------------

def run_summary(run):
    r = run.report
    return {"run_id": run.run_id, "pipeline_version": r.get("pipeline_version"), "generated_at": r.get("generated_at"),
            "content_digest": r.get("content_digest"), "semantic_backend": r.get("backend_resolution"),
            "document_health": {d: v["status"] for d, v in (run.health.get("documents") or {}).items()},
            "analytics_gates": run.health.get("analytics_gates"), "funnel": (r.get("observability") or {}).get("funnel")}


def health(run):
    return run.health


def list_topics(run, doc_id=None, course_code=None, include_noise=False, q=None, limit=100, offset=0):
    items = [t for t in run.topics.values()
             if (include_noise or t["noise_label"] == "TOPIC")
             and (doc_id is None or t["doc_id"] == doc_id)
             and (course_code is None or t["course_code"] == course_code)
             and (q is None or q.lower() in t["clean_text"].lower())]
    items.sort(key=lambda t: (t["doc_id"], t["course_code"], t["page_number"], t["topic_uid"]))
    return _page([run._topic_view(t) for t in items], limit, offset)


def list_concepts(run, discipline=None, family_uid=None, evidence_status=None, review_priority=None, q=None,
                  limit=100, offset=0):
    if run.gate("concept_discovery")["status"] != "ALLOWED":
        return {"status": "BLOCKED", "gate": run.gate("concept_discovery"), "items": []}
    items = [c for c in run.concepts.values()
             if (discipline is None or c["discipline"] == discipline)
             and (family_uid is None or c["family_uid"] == family_uid)
             and (evidence_status is None or c["evidence_status"] == evidence_status)
             and (review_priority is None or c["review_priority"] == review_priority)
             and (q is None or q.lower() in c["name"].lower())]
    items.sort(key=lambda c: (-c["support"], c["name"]))
    return _page([run._concept_summary(c) for c in items], limit, offset)


def get_concept(run, concept_uid):
    c = run.concepts.get(concept_uid)
    if c is None:
        return None
    return {**run._concept_summary(c), "name_method": c.get("name_method"),
            "mean_member_similarity_to_centroid": c.get("mean_member_similarity_to_centroid"),
            "similarity_is_calibrated_confidence": False,
            "validation": c.get("validation"), "course_uids": c["course_uids"],
            "member_count": len(c["member_topic_uids"])}


def concept_evidence(run, concept_uid):
    c = run.concepts.get(concept_uid)
    if c is None:
        return None
    members = [run._topic_view(run.topics[u]) for u in c["member_topic_uids"] if u in run.topics]
    return {"concept_uid": concept_uid, "name": c["name"], "evidence_status": c["evidence_status"],
            "directly_extracted_topics": members,
            "missing_member_topics": len(c["member_topic_uids"]) - len(members),
            "reference_status": run.reference_status.get(concept_uid),
            "drift": run.drift.get(concept_uid),
            "skill_candidates": [l["skill_candidate_uid"] for l in run.concept_skill_links if l["concept_uid"] == concept_uid]}


def related_concepts(run, concept_uid):
    if concept_uid not in run.concepts:
        return None
    out = []
    for e in run.edges:
        if concept_uid in (e["source_uid"], e["target_uid"]) and e["relationship"] != "BELONGS_TO_FAMILY":
            other = e["target_uid"] if e["source_uid"] == concept_uid else e["source_uid"]
            if other in run.concepts:
                direction = "outgoing" if e["source_uid"] == concept_uid else "incoming"
                out.append({"relationship": e["relationship"], "direction": direction, "method": e["method"],
                            "evidence_status": e["evidence_status"], "concept": run._concept_summary(run.concepts[other])})
    return {"concept_uid": concept_uid, "related": sorted(out, key=lambda r: (r["relationship"], r["concept"]["name"]))}


def concept_mappings(run, relationship=None, course_code=None, limit=100, offset=0):
    gate = run.gate("reference_mapping")
    if gate["status"] != "ALLOWED":
        return {"status": "BLOCKED", "gate": gate, "items": []}
    items = []
    for m in run.mappings:
        if relationship and m["relationship"] != relationship:
            continue
        source = run.topics.get(m["source_uid"])
        if course_code and (source is None or source["course_code"] != course_code):
            continue
        target = run.topics.get(m["target_uid"]) if m.get("target_uid") else None
        items.append({**m, "source": run._topic_view(source) if source else None,
                      "reference": run._topic_view(target) if target else None})
    items.sort(key=lambda m: m["mapping_uid"])
    return {"status": "ALLOWED", **_page(items, limit, offset)}


def knowledge_graph(run, discipline=None, family_uid=None, max_nodes=500):
    concepts = [c for c in run.concepts.values()
                if (discipline is None or c["discipline"] == discipline) and (family_uid is None or c["family_uid"] == family_uid)]
    concepts.sort(key=lambda c: (-c["support"], c["name"]))
    total = len(concepts)
    truncated = total > max_nodes
    concepts = concepts[:max_nodes]
    ids = {c["concept_uid"] for c in concepts}
    families = {c["family_uid"] for c in concepts}
    nodes = [{"id": c["concept_uid"], "type": "concept", "label": c["name"], "support": c["support"],
              "evidence_status": c["evidence_status"]} for c in concepts]
    nodes += [{"id": f, "type": "concept_family", "label": run.families[f]["name"],
               "evidence_status": run.families[f]["evidence_status"]} for f in sorted(families) if f in run.families]
    edges = [{"source": e["source_uid"], "target": e["target_uid"], "relationship": e["relationship"],
              "evidence_status": e["evidence_status"]}
             for e in run.edges if e["source_uid"] in ids and (e["target_uid"] in ids or e["target_uid"] in families)]
    return {"nodes": nodes, "edges": edges, "truncated": truncated, "total_concepts_matching": total}


def review_queue(run, priority=None, limit=50, offset=0):
    items = [i for i in run.review if priority is None or i["priority"] == priority]
    return {"note": "review_decision is null until a human records a decision in data/metadata/review_decisions.json",
            **_page(items, limit, offset)}


def skill_candidates(run, limit=100, offset=0):
    gate = run.gate("skill_taxonomy")
    return {"taxonomy_gate": gate, "note": "tokens found in topic text; not taxonomy skills",
            **_page(sorted(run.skill_candidates, key=lambda s: (-s["topic_count"], s["surface"])), limit, offset)}


def blocked_analytics(run):
    return {name: gate for name, gate in (run.health.get("analytics_gates") or {}).items() if gate["status"] == "BLOCKED"}


# ---------------- industry / ESCO layer ----------------
# Every industry response carries the population scope and the
# representativeness warning; a blocked gate returns no numbers.

def _scope_header(run):
    scope = (run.industry or {}).get("scope")
    if not scope:
        return None
    return {k: scope[k] for k in ("eligible_postings", "source_files", "geographic_scope", "date_range",
                                  "distinct_companies", "distinct_job_titles", "representativeness_warning")}


def _industry_gate(run, name):
    if run.industry is None:
        return {"status": "BLOCKED", "reasons": ["no industry sources were processed in this run"]}
    return run.gate(name)


def _industry_response(run, gate_name, payload):
    gate = _industry_gate(run, gate_name)
    if gate["status"] != "ALLOWED":
        return {"status": "BLOCKED", "gate": gate, "population_scope": _scope_header(run), "items": []}
    return {"status": "ALLOWED", "population_scope": _scope_header(run), **payload}


def industry_scope(run):
    return _industry_response(run, "industry_demand", {"scope": run.industry["scope"], "temporal": run.industry["temporal"],
                                                        "health": run.industry["health"]["status"]})


def industry_health(run):
    if run.industry is None:
        return {"status": "BLOCKED", "reasons": ["no industry sources were processed in this run"]}
    return {"industry": run.industry["health"], "gates": {k: v for k, v in (run.health.get("analytics_gates") or {}).items()
                                                          if k in ("skill_taxonomy", "industry_demand", "industry_gap", "recommendations")}}


def esco_audit(run):
    if run.industry is None or run.industry["esco_audit"] is None:
        return {"status": "NOT_LOADED"}
    return run.industry["esco_audit"]


def industry_demand(run, support_state=None, esco_status=None, limit=100, offset=0):
    if run.industry is None:
        return _industry_response(run, "industry_demand", {})
    items = [d for d in run.industry["demand"]
             if (support_state is None or d["support_state"] == support_state)
             and (esco_status is None or d["esco_status"] == esco_status)]
    items.sort(key=lambda d: (-d["posting_count"], d["skill_label"]))
    items = [{k: v for k, v in d.items() if k != "posting_uids"} | {"posting_uid_count": len(d["posting_uids"])} for d in items]
    return _industry_response(run, "industry_demand", {"measure_note": "observed posting prevalence and company prevalence "
                              "(separate measures); not importance", **_page(items, limit, offset)})


def industry_skills(run, esco_status=None, limit=200, offset=0):
    if run.industry is None:
        return _industry_response(run, "industry_demand", {})
    items = sorted((s for s in run.industry["skills"].values() if esco_status is None or s["esco_status"] == esco_status),
                   key=lambda s: s["label"])
    return {"status": "ALLOWED", "population_scope": _scope_header(run),
            "taxonomy_scope": (run.industry["esco_audit"] or {}).get("reconstruction_scope"), **_page(items, limit, offset)}


def industry_segments(run):
    if run.industry is None:
        return _industry_response(run, "industry_demand", {})
    return _industry_response(run, "industry_demand", {"segments": run.industry["segments"]})


def skill_gaps(run, classification=None, limit=100, offset=0):
    if run.industry is None:
        return _industry_response(run, "industry_gap", {})
    items = [g for g in run.industry["gaps"] if classification is None or g["classification"] == classification]
    items.sort(key=lambda g: (-g["industry_count"], g["skill_label"]))
    return _industry_response(run, "industry_gap", _page(items, limit, offset))


def recommendations(run, include_suppressed=False, limit=100, offset=0):
    if run.industry is None:
        return _industry_response(run, "recommendations", {})
    items = list(run.industry["recommendations"]) + (list(run.industry["suppressions"]) if include_suppressed else [])
    return _industry_response(run, "recommendations", {
        "note": "recommendations are derived outputs (is_source_evidence = false) and are never used as evidence",
        **_page(items, limit, offset)})


def why_no_recommendation(run, skill_key):
    if run.industry is None:
        return None
    hit = next((s for s in run.industry["suppressions"] if s["skill_key"] == skill_key), None)
    if hit is None and any(r["skill_key"] == skill_key for r in run.industry["recommendations"]):
        return {"skill_key": skill_key, "recommendation_exists": True}
    if hit is None:
        return {"skill_key": skill_key, "recommendation_exists": False,
                "reasons": [{"code": "NO_INDUSTRY_DEMAND_ROW", "detail": "no eligible supplied posting mentions this skill"}]}
    return {"skill_key": skill_key, "recommendation_exists": False, "reasons": hit["reasons"],
            "population_scope": _scope_header(run)}


def evidence_trace(run, skill_key):
    """Stored trace (recommendations and high-demand gaps) or, for any other skill
    with demand, the same chain assembled from the run's GOLD files."""
    if run.industry is None:
        return None
    stored = run.industry["traces"].get(skill_key)
    if stored is not None:
        return {**stored, "trace_source": "stored"}
    skill = run.industry["skills"].get(skill_key)
    demand = next((d for d in run.industry["demand"] if d["skill_key"] == skill_key), None)
    if skill is None or demand is None:
        return None
    ind = run.dir / "industry"
    postings = {p["posting_uid"]: p for p in _jsonl(ind / "postings.jsonl")}
    mentions = [m for m in _jsonl(ind / "skill_mentions.jsonl") if m["skill_key"] == skill_key and m["mention_role"] == "SKILL"]
    gap = next((g for g in run.industry["gaps"] if g["skill_key"] == skill_key), None)
    coverage = [c for c in run.industry["coverage"] if c["skill_key"] == skill_key]
    rec = next((r for r in run.industry["recommendations"] if r["skill_key"] == skill_key), None)
    return {
        "trace_source": "assembled_from_gold", "skill_key": skill_key,
        "job_postings": [{"posting_uid": m["source_uid"], "url": postings.get(m["source_uid"], {}).get("url"),
                          "source_file": postings.get(m["source_uid"], {}).get("source_file"),
                          "row_number": postings.get(m["source_uid"], {}).get("row_number"),
                          "job_title": postings.get(m["source_uid"], {}).get("job_title"),
                          "company": postings.get(m["source_uid"], {}).get("company_name"),
                          "raw_mention": m["raw_mention"], "span": m["span"], "context": m["context"],
                          "extraction_method": m["method"], "mention_uid": m["mention_uid"]} for m in mentions][:20],
        "normalized_skill": {"skill_uid": skill["skill_uid"], "label": skill["label"], "surfaces": skill["surfaces"],
                             "category": skill["skill_category"]},
        "esco": {"status": skill["esco_status"], "uri": skill["esco_uri"], "pref_label": skill["esco_pref_label"],
                 "mapping_method": skill["mapping_method"],
                             "taxonomy_scope": ((run.industry.get("esco_audit") or {}).get("reconstruction_scope")
                                                or "PARTIAL_DELTA_SUBSET")},
        "industry_demand": {k: v for k, v in demand.items() if k != "posting_uids"},
        "population_scope": _scope_header(run),
        "curriculum_coverage_by_document_role": coverage,
        "gap": gap, "recommendation": rec,
        "no_recommendation": None if rec else why_no_recommendation(run, skill_key),
        "run_id": run.run_id,
    }


def industry_review_queue(run, kind=None, limit=100, offset=0):
    if run.industry is None:
        return {"items": []}
    items = [i for i in run.industry["review"] if kind is None or i["kind"] == kind]
    return {"note": "review_decision is null until a person records a decision; nothing here is human-validated",
            **_page(items, limit, offset)}
