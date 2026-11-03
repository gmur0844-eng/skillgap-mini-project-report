"""
Tests for the read-only knowledge service behind /api/v1/curriculum/*.
A tiny GOLD/SILVER run is written to a temp directory in the exact file
layout the pipeline produces. Checks: BLOCKED gates return no numbers,
None stays None, provenance is attached, 404 paths return None.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import knowledge_service as ks

SHA = "ab" * 32


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _make_run(mapping_gate="ALLOWED"):
    root = Path(tempfile.mkdtemp())
    gold, silver = root / "gold", root / "silver"
    run = gold / "run1"
    course = {"course_uid": "course:0000000000000001", "doc_id": "doc-t", "course_code": "AB101", "title": "Data Structures",
              "semester": "III", "source_sha256": SHA, "family_uid": "family:0000000000000001"}
    topics = [
        {"topic_uid": "topic:0000000000000001", "doc_id": "doc-t", "course_uid": course["course_uid"], "course_code": "AB101",
         "unit_label": "UNIT-I", "raw_text": "Binary trees", "clean_text": "Binary trees", "page_number": 7,
         "extraction_method": "pdftotext_layout", "noise_label": "TOPIC", "evidence_status": "EXTRACTED"},
        {"topic_uid": "topic:0000000000000002", "doc_id": "doc-t", "course_uid": course["course_uid"], "course_code": "AB101",
         "unit_label": "UNIT-I", "raw_text": "60 Marks", "clean_text": "Marks", "page_number": 7,
         "extraction_method": "pdftotext_layout", "noise_label": "NOISE_ADMINISTRATIVE", "evidence_status": "INSUFFICIENT_EVIDENCE"},
        {"topic_uid": "topic:0000000000000003", "doc_id": "doc-t", "course_uid": course["course_uid"], "course_code": "AB101",
         "unit_label": "UNIT-II", "raw_text": "Binary search trees", "clean_text": "Binary search trees", "page_number": 8,
         "extraction_method": "pdftotext_layout", "noise_label": "TOPIC", "evidence_status": "EXTRACTED"},
    ]
    _write(silver / "doc-t" / SHA[:16] / "topics.jsonl", topics)
    concepts = [
        {"concept_uid": "concept:0000000000000001", "name": "Binary Trees", "discipline": "D", "family_uid": "family:0000000000000001",
         "support": 2, "member_topic_uids": ["topic:0000000000000001", "topic:0000000000000003"], "course_uids": [course["course_uid"]],
         "source_roles": ["TARGET"], "source_documents": ["doc-t"], "evidence_status": "DISCOVERED", "review_priority": "MEDIUM",
         "mean_member_similarity_to_centroid": 0.8},
        {"concept_uid": "concept:0000000000000002", "name": "Binary Search Trees", "discipline": "D", "family_uid": "family:0000000000000001",
         "support": 1, "member_topic_uids": ["topic:0000000000000003"], "course_uids": [course["course_uid"]],
         "source_roles": ["TARGET"], "source_documents": ["doc-t"], "evidence_status": "DISCOVERED", "review_priority": "LOW",
         "mean_member_similarity_to_centroid": 1.0},
    ]
    _write(run / "courses.jsonl", [course])
    _write(run / "concepts.jsonl", concepts)
    _write(run / "concept_families.jsonl", [{"family_uid": "family:0000000000000001", "name": "trees", "evidence_status": "DISCOVERED"}])
    _write(run / "concept_edges.jsonl", [
        {"edge_uid": "edge:0000000000000001", "source_uid": "concept:0000000000000001", "target_uid": "concept:0000000000000002",
         "relationship": "PARENT", "method": "name containment", "evidence_status": "DISCOVERED"},
        {"edge_uid": "edge:0000000000000002", "source_uid": "concept:0000000000000001", "target_uid": "family:0000000000000001",
         "relationship": "BELONGS_TO_FAMILY", "method": "family", "evidence_status": "DISCOVERED"}])
    _write(run / "topic_mappings.jsonl", [
        {"mapping_uid": "map:0000000000000001", "source_uid": "topic:0000000000000001", "target_uid": None,
         "relationship": "INSUFFICIENT_EVIDENCE", "similarity_score": None, "score_is_calibrated": False,
         "method": "tfidf_cosine_scoped", "evidence_status": "INSUFFICIENT_EVIDENCE"}])
    for name in ("concept_reference_status", "concept_drift", "review_queue", "skill_candidates", "concept_skill_links"):
        _write(run / f"{name}.jsonl", [])
    gates = {"concept_discovery": {"status": "ALLOWED", "reasons": []},
             "reference_mapping": {"status": mapping_gate, "reasons": [] if mapping_gate == "ALLOWED" else ["reference FAIL"]},
             "industry_gap": {"status": "BLOCKED", "reasons": ["no postings"]}}
    (run / "health.json").write_text(json.dumps({"documents": {"doc-t": {"status": "PASS"}}, "analytics_gates": gates}))
    (run / "run_report.json").write_text(json.dumps({"run_id": "run1", "content_digest": "x"}))
    (gold / "latest_run.json").write_text(json.dumps({"run_id": "run1"}))
    return ks.KnowledgeRun(None, gold_root=gold, silver_root=silver)


def test_latest_pointer_and_summary():
    run = _make_run()
    assert run.run_id == "run1"
    s = ks.run_summary(run)
    assert s["document_health"] == {"doc-t": "PASS"}


def test_topics_exclude_noise_by_default_and_carry_provenance():
    run = _make_run()
    page = ks.list_topics(run)
    assert page["total"] == 2
    item = page["items"][0]
    assert item["provenance"]["page"] == 7 and item["provenance"]["source_sha256"] == SHA
    assert ks.list_topics(run, include_noise=True)["total"] == 3


def test_concept_evidence_and_related():
    run = _make_run()
    ev = ks.concept_evidence(run, "concept:0000000000000001")
    assert len(ev["directly_extracted_topics"]) == 2 and ev["missing_member_topics"] == 0
    rel = ks.related_concepts(run, "concept:0000000000000001")["related"]
    assert [r["relationship"] for r in rel] == ["PARENT"]  # family membership is not a concept relation
    assert ks.get_concept(run, "concept:ffffffffffffffff") is None
    assert ks.get_concept(run, "concept:0000000000000001")["similarity_is_calibrated_confidence"] is False


def test_unmapped_similarity_stays_none():
    run = _make_run()
    m = ks.concept_mappings(run)["items"][0]
    assert m["similarity_score"] is None and m["reference"] is None


def test_blocked_gate_returns_no_items():
    run = _make_run(mapping_gate="BLOCKED")
    out = ks.concept_mappings(run)
    assert out["status"] == "BLOCKED" and out["items"] == [] and out["gate"]["reasons"]
    assert set(ks.blocked_analytics(run)) == {"reference_mapping", "industry_gap"}


def test_graph_truncation_reports_true_total():
    run = _make_run()
    g = ks.knowledge_graph(run, max_nodes=1)
    assert g["truncated"] and g["total_concepts_matching"] == 2
    assert sum(1 for n in g["nodes"] if n["type"] == "concept") == 1


def test_missing_run_raises():
    try:
        ks.KnowledgeRun("nope", gold_root=Path(tempfile.mkdtemp()))
        raise AssertionError("expected RunNotFound")
    except ks.RunNotFound:
        pass


# ---------------- industry layer ----------------

def _with_industry(gate_status="ALLOWED"):
    run = _make_run()
    ind = run.dir / "industry"
    ind.mkdir()
    warning = "These results describe the supplied job-posting dataset and are not necessarily representative of the entire labour market."
    (ind / "population_scope.json").write_text(json.dumps({
        "eligible_postings": 10, "source_files": ["a.xlsx"], "geographic_scope": {"IN": 10},
        "date_range": {"earliest": "2026-09-22", "latest": "2026-09-22"}, "distinct_companies": 9,
        "distinct_job_titles": 10, "representativeness_warning": warning}))
    (ind / "industry_health.json").write_text(json.dumps({"status": "PASS", "checks": []}))
    _write(ind / "industry_demand.jsonl", [{"skill_key": "k1", "skill_label": "SQL", "posting_count": 3, "posting_uids": ["p1", "p2", "p3"],
                                            "support_state": "OBSERVED", "esco_status": "EXACT"}])
    _write(ind / "skill_gaps.jsonl", [{"skill_key": "k1", "skill_label": "SQL", "classification": "MISSING", "industry_count": 3}])
    _write(ind / "recommendations.jsonl", [])
    _write(ind / "recommendation_suppressions.jsonl", [{"skill_key": "k1", "reasons": [{"code": "INDUSTRY_SUPPORT_BELOW_THRESHOLD"}]}])
    for name in ("skills", "esco_mappings", "evidence_traces", "industry_review_queue", "curriculum_skill_coverage", "qualification_mentions"):
        _write(ind / f"{name}.jsonl", [])
    health = json.loads((run.dir / "health.json").read_text())
    for g in ("industry_demand", "industry_gap", "recommendations"):
        health["analytics_gates"][g] = {"status": gate_status, "reasons": [] if gate_status == "ALLOWED" else ["industry health FAIL"]}
    (run.dir / "health.json").write_text(json.dumps(health))
    return ks.KnowledgeRun(None, gold_root=run.gold_root, silver_root=run.silver_root)


def test_industry_results_always_carry_scope_and_warning():
    run = _with_industry()
    out = ks.industry_demand(run)
    assert out["status"] == "ALLOWED" and "not necessarily representative" in out["population_scope"]["representativeness_warning"]
    assert out["items"][0]["posting_uid_count"] == 3 and "posting_uids" not in out["items"][0]
    assert ks.skill_gaps(run)["population_scope"]["eligible_postings"] == 10


def test_industry_blocked_gate_returns_no_numbers():
    run = _with_industry("BLOCKED")
    for out in (ks.industry_demand(run), ks.skill_gaps(run), ks.recommendations(run)):
        assert out["status"] == "BLOCKED" and out["items"] == []


def test_why_no_recommendation_is_structured():
    run = _with_industry()
    why = ks.why_no_recommendation(run, "k1")
    assert why["recommendation_exists"] is False and why["reasons"][0]["code"] == "INDUSTRY_SUPPORT_BELOW_THRESHOLD"
    assert ks.why_no_recommendation(run, "unknown")["reasons"][0]["code"] == "NO_INDUSTRY_DEMAND_ROW"
