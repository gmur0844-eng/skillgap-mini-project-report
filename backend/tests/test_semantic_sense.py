"""
Alias-sense / acronym-sense validation, semantic hard negatives, embedding
backend plumbing. Everything here goes through generic mechanisms; the
fixture strings reproduce real shapes but no code path names them.

A. an altLabel is a valid taxonomy alias          E. valid aliases work when context is sufficient
B. a different prefLabel does not establish        F. no subject-specific conditional (static audit)
   meaning in arbitrary text                      G. recommendations cannot consume REVIEW_REQUIRED mappings
C. ambiguous alias meanings are excluded from     H. recommendations cannot become evidence
   demand
D. exact preferred-label matches still work
"""
import csv
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine import industry as ind
from app.knowledge_engine import industry_stage
from app.knowledge_engine.config import load_config
from app.knowledge_engine.esco_delta import EXPECTED_COLUMNS, build_skill_vocabulary, read_delta_rows
from app.knowledge_engine.evidence_guard import CircularEvidenceError, require_source_records
from app.knowledge_engine.mapping import _relationship, map_topics
from app.knowledge_engine.semantic_backend import (
    EmbeddingBackend, TfidfBackend, available_backends, contextual_input, get_backend,
)

CFG = load_config()
U = "http://data.europa.eu/esco/skill/"
VB, SQLC, CTRL, WORDC, SQLSRV = (U + f"{i:08d}-1111-1111-1111-111111111111" for i in range(5))
SETTINGS = {"high_demand_threshold": 0.15, "partial_coverage_threshold": 0.4, "min_periods_for_trend": 2,
            "min_eligible_postings_per_period": 30, "min_skill_postings_for_trend": 5, "near_duplicate_similarity_threshold": 0.75}


def _vocab():
    rows = [[VB, "Visual Basic", "altLabel", "None", ".NET", "Added", "en"],
            [SQLC, "SQL", "description", "a", "b", "Updated", "en"],
            [SQLSRV, "SQL Server", "altLabel", "None", "MSSQL", "Added", "en"],
            [SQLSRV, "SQL Server", "altLabel", "None", "SQL Servr", "Added", "en"],
            [CTRL, "control systems", "description", "a", "b", "Updated", "en"],
            [WORDC, "Angular", "description", "a", "b", "Updated", "en"]]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPECTED_COLUMNS)
    w.writerows(rows)
    path = Path(tempfile.mkdtemp()) / "d.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("delta.csv", buf.getvalue())
    return build_skill_vocabulary(read_delta_rows(path))[0]


def _posting(i, text, title="Engineer", company=None):
    return {"posting_uid": f"posting:{i:016x}", "job_title": title, "clean_description": text,
            "company_key": company or f"c{i}", "company_name": company or f"C{i}", "posted_date": "2026-09-22",
            "evidence_status": "EXTRACTED", "url": f"https://jobs.example.org/{i}", "source_file": "f.xlsx",
            "row_number": i + 1, "country_code": "XX"}


def _extract(postings, topics=()):
    return industry_stage.extract_and_map(postings, list(topics), _vocab(), CFG, TfidfBackend)


def _states(extraction, surface):
    return [m["sense_state"] for m in extraction["posting_mentions"] if m["normalized_text"] == surface]


# ---------------- A-E: alias sense ----------------

def test_A_alias_is_kept_as_taxonomy_fact_and_B_does_not_establish_meaning():
    ex = _extract([_posting(1, "Strong C#, .NET Core and Web API experience.")])
    mapping = ex["mappings"][".net"]
    assert mapping["esco_uri"] == VB and mapping["mapping_method"] == "altLabel_active_after_delta"   # A: ESCO fact kept
    assert _states(ex, ".net") == ["ALIAS_SENSE_REVIEW_REQUIRED"]                                  # B
    skill = ex["skills"][VB]
    assert skill["esco_status"] == "ALIAS_SENSE_REVIEW_REQUIRED" and skill["esco_uri"] is None
    assert skill["taxonomy_candidate_uri"] == VB and skill["taxonomy_relationship"] == "TAXONOMY_ALIAS_MATCH"
    assert skill["evidence_status"] == "REVIEW_REQUIRED" and skill["eligible_for_analytics"] is False


def test_C_unestablished_alias_mentions_are_excluded_from_demand():
    ex = _extract([_posting(i, "Strong C#, .NET Core and Web API experience.") for i in range(6)])
    assert ex["summary"]["mentions_sense_review_required"] == 6
    pairs = {(m["skill_key"], m["source_uid"]) for m in ex["posting_mentions"] if m["sense_established"]}
    assert not any(k == VB for k, _ in pairs)


def test_D_exact_preferred_label_still_works():
    ex = _extract([_posting(1, "Write SQL queries daily.")])
    assert ex["mappings"]["sql"]["status"] == "EXACT" and _states(ex, "sql") == ["ESTABLISHED"]
    assert ex["skills"][SQLC]["eligible_for_analytics"] is True


def test_E_alias_established_when_the_same_text_names_the_concept():
    ex = _extract([_posting(1, "Maintain Visual Basic 6 and .NET applications.")])
    assert _states(ex, ".net") == ["ESTABLISHED_BY_CONTEXT"]
    m = next(m for m in ex["posting_mentions"] if m["normalized_text"] == ".net")
    assert m["sense_evidence"]["other_labels_of_concept_in_text"] == ["visual basic"]
    # the skill takes the strongest status of its surfaces (the prefLabel mention is EXACT)
    assert ex["skills"][VB]["esco_status"] == "EXACT" and ex["skills"][VB]["eligible_for_analytics"]
    assert ex["skills"][VB]["established_mentions"] == 2


def test_alias_decision_is_per_mention_not_per_label():
    ex = _extract([_posting(1, "Strong C#, .NET Core."), _posting(2, "Visual Basic and .NET.")])
    assert sorted(_states(ex, ".net")) == ["ALIAS_SENSE_REVIEW_REQUIRED", "ESTABLISHED_BY_CONTEXT"]
    assert ex["skills"][VB]["established_mentions"] == 2  # the .NET in posting 2 + the Visual Basic prefLabel mention


def test_acronym_tokens_need_technical_context():
    ex = _extract([_posting(1, "Monitor trials per GCP principles and ICH guidelines."),
                   _posting(2, "Deploy services on AWS, GCP and Docker.")])
    states = {m["source_uid"]: m["sense_state"] for m in ex["posting_mentions"] if m["normalized_text"] == "gcp"}
    assert states["posting:0000000000000001"] == "ACRONYM_SENSE_REVIEW_REQUIRED"
    assert states["posting:0000000000000002"] == "ESTABLISHED_BY_CONTEXT"


# ---------------- F: no subject-specific conditional ----------------

def test_F_static_generalization_audit_finds_no_conditional():
    out = subprocess.run([sys.executable, str(ROOT / "scripts/evaluation/static_generalization_audit.py")],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout[-2000:]
    assert "CONDITIONAL (forbidden): 0" in out.stdout


# ---------------- G, H: recommendations ----------------

def _gold(postings, topics):
    ex = _extract(postings, topics)
    courses = {f"course:{i:016x}": {"course_uid": f"course:{i:016x}", "doc_id": "t", "course_code": f"T{i}",
                                    "title": f"Course {i}"} for i in range(1, 5)}  # 1 of 4 courses names SQL -> 25 % -> PARTIAL
    ctx = {"topics_by_uid": {t["topic_uid"]: t for t in topics}, "courses_by_uid": courses, "roles": {"t": "TARGET"},
           "topic_to_concept": {}, "target_doc": "t", "reference_doc": None, "previous_doc": None}
    return ex, industry_stage.gold(postings, [{"path": "f.xlsx"}], ex, ctx, CFG, SETTINGS, "run", TfidfBackend)


def test_G_recommendations_cannot_consume_review_required_mappings():
    postings = [_posting(i, "Strong C#, .NET Core and Web API.") for i in range(8)] + \
               [_posting(100 + i, "Write SQL queries and tune SQL.") for i in range(8)]
    topics = [{"topic_uid": "topic:0000000000000001", "doc_id": "t", "course_uid": "course:0000000000000001", "course_code": "T1",
               "unit_label": "Unit 1", "clean_text": "Basic SQL queries", "page_number": 3, "evidence_status": "EXTRACTED",
               "noise_label": "TOPIC"}]
    ex, g = _gold(postings, topics)
    assert all(d["skill_key"] != VB for d in g["demand"])
    assert all(x["skill_key"] != VB for x in g["gaps"] + g["recommendations"] + g["suppressions"])
    assert any(r["skill_key"] == SQLC for r in g["recommendations"])          # exact SQL path unaffected
    review = [i for i in g["review_queue"] if i["kind"] == "ALIAS_SENSE_CHECK"]
    assert review and review[0]["detail"]["esco_candidate"] == "Visual Basic"
    assert review[0]["detail"]["postings"] == 8 and review[0]["detail"]["contexts"]


def test_H_recommendations_cannot_become_evidence():
    postings = [_posting(100 + i, "Write SQL queries.") for i in range(8)]
    topics = [{"topic_uid": "topic:0000000000000001", "doc_id": "t", "course_uid": "course:0000000000000001", "course_code": "T1",
               "unit_label": "Unit 1", "clean_text": "Basic SQL queries", "page_number": 3, "evidence_status": "EXTRACTED",
               "noise_label": "TOPIC"}]
    _, g = _gold(postings, topics)
    try:
        require_source_records(g["recommendations"], "curriculum topic")
        raise AssertionError("recommendations accepted as evidence")
    except CircularEvidenceError:
        pass


# ---------------- hard negatives (data/evaluation/semantic_hard_negatives.json) ----------------

def _case(cid):
    data = json.loads((ROOT / "data/evaluation/semantic_hard_negatives.json").read_text())
    return next(c for c in data["cases"] if c["id"] == cid)


def test_hard_negatives_pinned():
    ex = _extract([_posting(1, "Conservation of Angular momentum"), _posting(2, "Strong C#, .NET Core."),
                   _posting(3, "Maintain Visual Basic 6 and .NET applications."),
                   _posting(4, "monitor trials per GCP principles and ICH guidelines"), _posting(5, "deploy on AWS, GCP and Docker"),
                   _posting(6, "familiarity with version control systems")])
    by_post = {(m["source_uid"], m["normalized_text"]): m for m in ex["posting_mentions"]}
    assert ex["mappings"]["angular"]["status"] == _case("hn01")["expected"]
    assert by_post[("posting:0000000000000002", ".net")]["sense_state"] == _case("hn02")["expected"]
    assert by_post[("posting:0000000000000003", ".net")]["sense_state"] == _case("hn03")["expected"]
    assert by_post[("posting:0000000000000004", "gcp")]["sense_state"] == _case("hn04")["expected"]
    assert by_post[("posting:0000000000000005", "gcp")]["sense_state"] == _case("hn05")["expected"]
    # KNOWN_FAILURE pinned: the head noun of "version control systems" still matches
    assert by_post[("posting:0000000000000006", "control systems")]["sense_state"] == _case("hn06")["expected_current_outcome"]
    assert _relationship("database management", "management", 0.6)[0] == _case("hn07")["expected"]
    assert _relationship("test", "testing", 0.6)[0] == _case("hn08")["expected"]


def test_stack_across_course_families_is_not_mapped():
    backend = TfidfBackend()
    targets = [{"topic_uid": "topic:a", "course_uid": "c1", "clean_text": "Stack", "page_number": 1, "unit_label": "Unit 1"}]
    refs = [{"topic_uid": "topic:b", "course_uid": "c2", "clean_text": "Stack", "page_number": 2, "unit_label": "Module 1"}]
    backend.fit(["Stack", "stack emissions", "linked list"])
    courses = {"c1": {"title": "Data Structures"}, "c2": {"title": "Air Pollution Control"}}
    rec = map_topics(targets, refs, {"c1": "family:a", "c2": "family:b"}, {}, {}, backend, CFG["mapping"], courses)[0]
    assert rec["target_uid"] is None and rec["explanation"]["reason"] == "NO_REFERENCE_TOPICS_IN_SCOPE"
    assert rec["explanation"]["best_out_of_scope_candidate"]["reference_text"] == "Stack"


def test_mapping_records_separate_signals_and_provenance():
    backend = TfidfBackend()
    t = {"topic_uid": "topic:a", "course_uid": "c1", "clean_text": "binary search trees", "page_number": 1, "unit_label": "Unit 2"}
    r = {"topic_uid": "topic:b", "course_uid": "c2", "clean_text": "binary search trees and heaps", "page_number": 5, "unit_label": "Module 3"}
    backend.fit([t["clean_text"], r["clean_text"], "Data Structures", "Algorithms"])
    courses = {"c1": {"title": "Data Structures"}, "c2": {"title": "Algorithms"}}
    rec = map_topics([t], [r], {"c1": "f", "c2": "f"}, {}, {}, backend, CFG["mapping"], courses)[0]
    sig = rec["signals"]
    assert sig["semantic_similarity"] is None and sig["semantic_similarity_status"] == "EMBEDDING_BACKEND_UNAVAILABLE"
    assert sig["composite_score"] is None and 0 <= sig["context_similarity"] <= 1
    assert sig["provenance"]["backend"] == "tfidf" and sig["provenance"]["score_is_calibrated"] is False
    assert len(sig["provenance"]["source_text_sha256"]) == 64


# ---------------- embedding backend plumbing ----------------

def test_embedding_backends_report_unavailability_instead_of_faking():
    status = available_backends()
    for name in ("sentence_transformer", "onnx_embedding", "api_embedding"):
        assert status[name].startswith("UNAVAILABLE:") or status[name] == "AVAILABLE"
    _, resolution = get_backend("onnx_embedding", fallback="tfidf")
    assert resolution["used"] == "tfidf" and resolution["fallback_reason"]


def test_contextual_input_keeps_context_without_subject_assumptions():
    text = contextual_input("Stack", {"document": "Doc", "course": "Course X", "unit": "Unit 2",
                                      "neighbours": ["Queues", "Stack", "Linked lists"]})
    assert text == "Doc | Course X | Unit 2 | Stack | neighbours: Queues; Linked lists"
    assert contextual_input("Stack") == "Stack"


def test_embedding_cache_reuses_vectors_deterministically():
    calls = []

    def encoder(texts):  # deterministic test double -- only used here, never registered as a backend
        calls.append(list(texts))
        return np.array([[len(t), t.count("a") + 1.0] for t in texts], dtype=np.float32)
    root = tempfile.mkdtemp()
    b1 = EmbeddingBackend(encoder, "test-encoder", "0", {"pooling": "none"}, cache_root=root)
    v1 = b1.embed(["alpha", "beta", "alpha"])
    size = b1.cache.save()
    b2 = EmbeddingBackend(encoder, "test-encoder", "0", {"pooling": "none"}, cache_root=root)
    v2 = b2.embed(["beta", "alpha"])
    assert len(calls) == 1 and sorted(calls[0]) == ["alpha", "beta"] and size > 0
    assert np.allclose(v1[1], v2[0]) and b2.cache.misses == 0 and b2.cache.hits == 2
    b3 = EmbeddingBackend(encoder, "test-encoder", "0", {"pooling": "mean"}, cache_root=root)  # new config -> new cache
    b3.embed(["alpha"])
    assert len(calls) == 2
    assert b1.describe()["semantic_capability"].startswith("embedding-based semantic similarity (uncalibrated")


def test_orthographic_variant_alias_keeps_identity():
    ex = _extract([_posting(1, "Admin for SQL Servr clusters."), _posting(2, "We run MSSQL in production.")])
    assert _states(ex, "sql servr") == ["ESTABLISHED"]           # spelling variant of the prefLabel
    assert _states(ex, "mssql") == ["ALIAS_SENSE_REVIEW_REQUIRED"]  # different string: meaning needs context


def test_title_case_and_all_caps_labels_are_not_technical_evidence():
    assert not ind._distinctive("Risk Management") and not ind._distinctive("GDPR")
    assert ind._distinctive("C++") and ind._distinctive("JavaScript") and ind._distinctive("SA8000")
