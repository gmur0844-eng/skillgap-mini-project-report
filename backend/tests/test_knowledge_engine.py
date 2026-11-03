"""
Unit tests for the knowledge engine's hardening layer: stage contracts,
quarantine, noise labels, replaceable semantic backend, SILVER validity,
health gate (including simulated extraction degradation), drift, review /
versioning, exports and observability. Fixtures reproduce the SHAPE of real
records; nothing here depends on an institution, discipline or subject name.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine.config import config_hash, load_config
from app.knowledge_engine.contracts import enforce
from app.knowledge_engine.drift import comparable_semesters, course_drift
from app.knowledge_engine.evaluation import classification_report, evaluate_golden_pages
from app.knowledge_engine.exports import content_digest, write_csv, write_jsonl
from app.knowledge_engine.health import analytics_gates, document_health
from app.knowledge_engine.noise import TOPIC, classify_topic
from app.knowledge_engine.observability import RunObserver
from app.knowledge_engine.quarantine import Quarantine
from app.knowledge_engine.review import apply_decisions, assign_priority, update_registry
from app.knowledge_engine.semantic_backend import BackendUnavailable, get_backend
from app.knowledge_engine.silver import build_silver, clean_course_title, uid
from app.knowledge_engine.skills import build_skill_layer, tool_candidates
from app.pipelines.preprocessing.curriculum_structuring import structure_curriculum_pages

CFG = load_config()


# ---------------- contracts + quarantine ----------------

def _topic(**over):
    base = {"topic_uid": uid("topic", "x"), "doc_id": "d", "course_uid": uid("course", "c"), "course_code": "AB101",
            "unit_label": "Unit 1", "raw_text": "Binary trees", "clean_text": "Binary trees", "page_number": 3,
            "extraction_method": "pdftotext_layout", "noise_label": "TOPIC", "evidence_status": "EXTRACTED"}
    base.update(over)
    return base


def test_contract_passes_valid_record_and_keeps_extra_fields():
    out = enforce([_topic(source_line="Binary trees, heaps")], "topic")
    assert len(out) == 1 and out[0]["source_line"] == "Binary trees, heaps"


def test_contract_violation_is_quarantined_not_raised():
    q = Quarantine()
    bad = [_topic(page_number=0), _topic(topic_uid="not-a-uid"), _topic(evidence_status="GUESSED")]
    out = enforce(bad + [_topic()], "topic", q, "silver.contract")
    assert len(out) == 1
    assert q.count() == 3
    assert all(item["reason"].startswith("CONTRACT_VIOLATION(topic)") for item in q.items)


def test_mapping_contract_rejects_calibrated_score_claim():
    q = Quarantine()
    rec = {"mapping_uid": uid("map", "a"), "source_uid": uid("topic", "a"), "target_uid": None,
           "relationship": "INSUFFICIENT_EVIDENCE", "similarity_score": None, "score_is_calibrated": True,
           "method": "tfidf", "evidence_status": "INSUFFICIENT_EVIDENCE"}
    assert enforce([rec], "mapping", q) == [] and q.count() == 1
    rec["score_is_calibrated"] = False
    assert len(enforce([rec], "mapping", q)) == 1


def test_mapping_contract_keeps_none_distinct_from_zero():
    rec = {"mapping_uid": uid("map", "b"), "source_uid": uid("topic", "b"), "relationship": "INSUFFICIENT_EVIDENCE",
           "similarity_score": None, "method": "tfidf", "evidence_status": "INSUFFICIENT_EVIDENCE"}
    assert enforce([rec], "mapping")[0]["similarity_score"] is None


def test_uid_is_deterministic_and_well_formed():
    assert uid("topic", "a", 1) == uid("topic", "a", 1)
    assert uid("topic", "a", 1) != uid("topic", "a", 2)
    assert len(uid("concept", "x").split(":")[1]) == 16


# ---------------- noise labels ----------------

def test_noise_labels_real_shapes():
    assert classify_topic("Linked Lists")[0] == TOPIC
    assert classify_topic("Process Control Block (PCB)")[0] == TOPIC
    assert classify_topic("https://nptel.ac.in/courses/106")[0] == "NOISE_URL"
    assert classify_topic("..")[0] == "NOISE_EMPTY"
    line = "2. Erwin Kreyszig, Advanced Engineering Mathematics, 9th Edition, John Wiley & Sons, 2006"
    assert classify_topic("Erwin Kreyszig", source_line=line)[0] == "NOISE_BIBLIOGRAPHY"


# ---------------- replaceable semantic backend ----------------

def test_tfidf_backend_available_and_symmetric():
    backend, resolution = get_backend("tfidf")
    assert resolution == {"requested": "tfidf", "used": "tfidf", "fallback_reason": None}
    backend.fit(["binary search trees", "hash tables and hashing", "process scheduling"])
    m = backend.embed(["binary search trees", "hashing"])
    sim = backend.similarity(m, m)
    assert abs(sim[0][1] - sim[1][0]) < 1e-9


def test_unavailable_backend_is_recorded_not_faked():
    backend, resolution = get_backend("sentence_transformer", fallback="tfidf")
    if resolution["used"] == "sentence_transformer":
        return  # the library is genuinely installed in this environment
    assert resolution["used"] == "tfidf" and resolution["fallback_reason"]
    try:
        get_backend("sentence_transformer", fallback=None)
        raise AssertionError("expected BackendUnavailable")
    except BackendUnavailable:
        pass


def test_unknown_backend_name_is_reported():
    _, resolution = get_backend("no_such_backend")
    assert "unknown backend" in resolution["fallback_reason"]


# ---------------- SILVER ----------------

def test_title_cut_at_second_course_code_in_two_column_table():
    assert clean_course_title("Software Testing   22CSE16N Software Testing Lab") == "Software Testing"
    assert clean_course_title("Image Processing  22ECO05") == "Image Processing"
    assert clean_course_title("Data Structures 3L:0T:0P 3") == "Data Structures"


def _doc():
    return {"doc_id": "doc-x", "sha256": "0" * 64, "_page_methods": {}}


def test_orphan_topics_are_quarantined_with_provenance():
    pages = ["SEMESTER I\nAB101 Discrete Structures\nUNIT-I\nSets, Relations, Functions\n"
             "Appendix - 2\nMathematics option\nUNIT-I\nEvolutes and involutes, Beta and Gamma functions"]
    structure = structure_curriculum_pages(pages)
    q = Quarantine()
    silver = build_silver(_doc(), structure, q, CFG["topics"])
    kept = {t["clean_text"] for t in silver["topics"]}
    assert "Sets" in kept
    assert not any("Evolutes" in t for t in kept)
    orphans = [i for i in q.items if i["reason"].startswith("ORPHAN_ATTRIBUTION")]
    assert orphans and all(i["record"]["page_number"] == 1 for i in orphans)


def test_single_unanchored_code_mention_is_not_a_course():
    pages = ["PO10 Project Management and finance\nSEMESTER I\nAB101 Discrete Structures\nUNIT-I\nSets, Relations",
             "AB101 Discrete Structures\nUNIT-II\nGraphs"]
    q = Quarantine()
    silver = build_silver(_doc(), structure_curriculum_pages(pages), q, CFG["topics"])
    assert [c["course_code"] for c in silver["courses"]] == ["AB101"]
    assert any(i["reason"].startswith("NO_STRUCTURAL_EVIDENCE") for i in q.items)


def test_unit_heading_with_en_dash_is_detected():
    pages = ["SEMESTER I\nAB101 Discrete Structures\nUNIT-I\nSets, Relations\nUNIT–II\nGraphs, Trees"]
    structure = structure_curriculum_pages(pages)
    labels = {t.topic_text: t.module_heading_label for t in structure.topics}
    assert labels.get("Graphs") is not None and labels["Graphs"] != labels["Sets"]


# ---------------- health gate ----------------

def _summary(**over):
    base = {"doc_id": "d", "sha256": "a" * 64, "expected_sha256": "a" * 64, "page_count": 100,
            "text_layer_pages": 95, "blank_pages": 5, "ocr_required_pages": 0, "valid_courses": 40,
            "unresolved_title_courses": 0, "noise_topics": 100, "all_topics": 1000, "contract_violations": 0,
            "contract_checked": 1500, "topics_with_provenance": 1000, "units": 349, "clean_topics": 900, "outcomes": 200}
    base.update(over)
    return base


BASELINE = {"valid_courses": 40, "units": 349, "clean_topics": 900, "outcomes": 200,
            "recorded_at": "t", "pipeline_version": "v"}


def test_healthy_document_passes_with_baseline():
    assert document_health(_summary(), CFG, BASELINE)["status"] == "PASS"


def test_simulated_unit_collapse_fails_baseline_regression():
    # the real failure mode this gate exists for: a parser change dropped 349 units to 31
    h = document_health(_summary(units=31), CFG, BASELINE)
    check = next(c for c in h["checks"] if c["check"] == "baseline_regression")
    assert h["status"] == "FAIL" and check["status"] == "FAIL"


def test_hash_mismatch_fails():
    assert document_health(_summary(sha256="b" * 64), CFG, BASELINE)["status"] == "FAIL"


def test_scanned_document_fails_ocr_check():
    h = document_health(_summary(text_layer_pages=10, ocr_required_pages=90), CFG, BASELINE)
    assert h["status"] == "FAIL"


def test_noise_and_provenance_thresholds_fail():
    assert document_health(_summary(noise_topics=800), CFG, BASELINE)["status"] == "FAIL"
    assert document_health(_summary(topics_with_provenance=990), CFG, BASELINE)["status"] == "FAIL"


def test_missing_baseline_is_warn_not_pass():
    assert document_health(_summary(), CFG, None)["status"] == "WARN"


def test_gates_block_analytics_when_reference_fails():
    health = {"t": {"status": "PASS"}, "p": {"status": "PASS"}, "r": {"status": "FAIL"}}
    roles = {"t": "TARGET", "p": "PREVIOUS_VERSION", "r": "REFERENCE"}
    gates = analytics_gates(health, roles, ["I"], False, None, CFG)
    assert gates["reference_mapping"]["status"] == "BLOCKED"
    assert gates["concept_drift"]["status"] == "ALLOWED"
    assert gates["concept_discovery"]["excluded_documents"] == ["r"]
    assert gates["industry_gap"]["status"] == "BLOCKED" and gates["recommendations"]["status"] == "BLOCKED"


def test_gates_need_enough_real_postings():
    health = {"t": {"status": "PASS"}}
    few = analytics_gates(health, {"t": "TARGET"}, [], False, 5, CFG)
    enough = analytics_gates(health, {"t": "TARGET"}, [], False, CFG["health"]["min_industry_postings"], CFG)
    assert few["industry_gap"]["status"] == "BLOCKED" and enough["industry_gap"]["status"] == "ALLOWED"
    assert few["concept_drift"]["status"] == "BLOCKED"


# ---------------- drift ----------------

def _course(code, title, sem, doc="p"):
    return {"course_uid": uid("course", doc, code), "course_code": code, "title": title, "semester": sem}


def test_course_drift_statuses_and_exclusions():
    prev = [_course("A1", "Data Structures", "III"), _course("A2", "Old Course", "III"), _course("A9", "X Course", None)]
    target = [_course("B1", "Data Structures", "III", "t"), _course("A3", "New Course", "III", "t"),
              _course("B7", "Later Course", "VII", "t")]
    sems = comparable_semesters(prev, target)
    rows, counts, excluded = course_drift(prev, target, sems)
    assert sems == ["III"]
    assert counts == {"ADDED": 1, "REMOVED": 1, "RETAINED_RECODED": 1}
    assert excluded == {"previous_without_semester": 1, "target_without_semester": 0, "target_outside_comparable_semesters": 1}


# ---------------- skills ----------------

def test_tool_candidates_are_suggestions_without_taxonomy():
    found = tool_candidates("Version control tools - GIT and GitHub, programming in C++ and Node.js")
    assert "GitHub" in found and "C++" in found
    topics = [{"topic_uid": uid("topic", 1), "course_uid": uid("course", 1), "doc_id": "d",
               "clean_text": "Version control using GitHub"}]
    candidates, links, status = build_skill_layer(topics, {})
    assert status.startswith("TAXONOMY_UNAVAILABLE")
    assert all(c["taxonomy_mapping"] is None for c in candidates)
    assert all(c["evidence_status"] in ("MODEL_SUGGESTED", "REVIEW_REQUIRED") for c in candidates)


# ---------------- review + versioning ----------------

def _concept(name, support, roles, courses):
    return {"concept_uid": uid("concept", name), "name": name, "support": support, "source_roles": roles,
            "course_uids": courses, "discipline": "d", "evidence_status": "DISCOVERED"}


def test_review_priority_and_generic_names():
    cs = assign_priority([_concept("Page Replacement Algorithms", 6, ["TARGET", "REFERENCE"], ["a", "b"]),
                          _concept("Forms", 9, ["TARGET"], ["a"])], CFG)
    assert cs[0]["review_priority"] == "HIGH"
    assert cs[1]["review_priority"] == "LOW" and any("GENERIC_NAME" in f for f in cs[1]["review_flags"])


def test_no_decisions_means_no_validation():
    cs = [_concept("Hashing", 3, ["TARGET"], ["a"])]
    kept, applied = apply_decisions(cs, {})
    assert applied == [] and kept[0]["evidence_status"] == "DISCOVERED"


def test_decisions_accept_reject_rename():
    a, r, n = (_concept(x, 3, ["TARGET"], ["a"]) for x in ("Hashing", "Forms", "Trees Graphs"))
    decisions = {a["concept_uid"]: {"review_decision": "ACCEPT", "reviewer": "x"},
                 r["concept_uid"]: {"review_decision": "REJECT"},
                 n["concept_uid"]: {"review_decision": "RENAME", "new_name": "Non-linear Data Structures"}}
    kept, applied = apply_decisions([a, r, n], decisions)
    assert [c["name"] for c in kept] == ["Hashing", "Non-linear Data Structures"]
    assert all(c["evidence_status"] == "HUMAN_VALIDATED" for c in kept) and len(applied) == 3
    assert kept[1]["discovered_name"] == "Trees Graphs"


def test_registry_marks_absent_concepts_instead_of_deleting(tmp_path=None):
    import tempfile
    path = Path(tempfile.mkdtemp()) / "registry.json"
    c1, c2 = _concept("A concept", 2, ["TARGET"], ["a"]), _concept("B concept", 2, ["TARGET"], ["a"])
    update_registry(path, "run1", [c1, c2])
    stats = update_registry(path, "run2", [c1])
    reg = json.loads(path.read_text())["concepts"]
    assert stats["total_known"] == 2 and reg[c2["concept_uid"]]["absent_since_run"] == "run2"
    assert reg[c1["concept_uid"]]["first_seen_run"] == "run1"


# ---------------- exports, observability, config, evaluation ----------------

def test_content_digest_deterministic_and_ignores_timing_files():
    import tempfile
    d = Path(tempfile.mkdtemp())
    write_jsonl(d / "a.jsonl", [{"b": 1, "a": 2}])
    first = content_digest(d)
    (d / "observability.json").write_text('{"duration_s": 1.23}')
    assert content_digest(d) == first
    write_jsonl(d / "a.jsonl", [{"b": 1, "a": 3}])
    assert content_digest(d) != first


def test_database_csv_keeps_null_distinct_from_empty():
    import tempfile
    p = Path(tempfile.mkdtemp()) / "t.csv"
    write_csv(p, [{"a": None, "b": ""}], ["a", "b"], null_marker="\\N")
    assert p.read_text().splitlines()[1] == "\\N,"
    write_csv(p, [{"a": None, "b": ""}], ["a", "b"])
    assert p.read_text().splitlines()[1] == ","


def test_observer_records_time_memory_and_funnel():
    obs = RunObserver()
    with obs.stage("s", doc_id="d") as st:
        st["pages"] = 2
        _ = [0] * 10000
    obs.count("pages", 2)
    report = obs.report()
    stage = report["stages"][0]
    assert stage["duration_s"] >= 0 and stage["peak_python_heap_mb"] >= 0 and stage["pages"] == 2
    assert report["funnel"]["pages"] == 2


def test_config_override_changes_hash():
    base = load_config()
    changed = load_config(overrides={"concepts": {"distance_threshold": 0.4}})
    assert changed["concepts"]["distance_threshold"] == 0.4
    assert config_hash(base) != config_hash(changed)


def test_classification_report_none_when_undefined():
    r = classification_report(["A", "A"], ["A", "A"], ["A", "B"])
    assert r["per_class"]["B"]["precision"] is None and r["per_class"]["A"]["f1"] == 1.0


def test_golden_evaluation_counts_misattribution():
    golden = {"pages": [{"doc_id": "d", "page": 5, "course_code": "AB101", "expected_topics": ["Hashing", "Trees"]}]}
    topics = [{"doc_id": "d", "page_number": 5, "course_code": "AB101", "clean_text": "Hashing", "noise_label": "TOPIC"},
              {"doc_id": "d", "page_number": 5, "course_code": "ZZ999", "clean_text": "Trees", "noise_label": "TOPIC"}]
    page = evaluate_golden_pages(golden, topics)["pages"][0]
    assert page["recall"] == 0.5 and page["topics_on_pages_attributed_to_other_courses"] == 1
    assert page["missed"] == ["Trees"]
