import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.data_quality import (
    compute_temporal_industry_quality_metrics,
    compute_temporal_curriculum_quality_metrics,
    compute_drift_quality_metrics,
    compute_job_posting_quality_metrics,
    compute_curriculum_quality_metrics,
    compute_skill_mention_quality_metrics,
    compute_curriculum_ingestion_quality_gates,
    metrics_to_rows,
)


def test_quality_metrics_basic_counts():
    accepted = [{"clean_description": "a" * 30}, {"clean_description": "b" * 50}]
    rejected = [{"reason": "empty_description"}, {"reason": "empty_description"}, {"reason": "description_too_short"}]
    metrics = compute_job_posting_quality_metrics(
        total_input_records=10,
        accepted_records=accepted,
        rejected_records=rejected,
        duplicate_count=1,
        near_duplicate_count=2,
        already_ingested_count=3,
    )
    assert metrics["total_records"] == 10
    assert metrics["valid_records"] == 2
    assert metrics["invalid_records"] == 3
    assert metrics["already_ingested_records"] == 3
    assert metrics["exact_duplicates"] == 1
    assert metrics["near_duplicates"] == 2
    assert metrics["min_text_length"] == 30
    assert metrics["max_text_length"] == 50
    assert metrics["removed_reasons"] == {"empty_description": 2, "description_too_short": 1}


def test_quality_metrics_already_ingested_defaults_to_zero():
    """Backward compatibility: callers that don't pass already_ingested_count
    (e.g. a fresh ingest with nothing pre-existing) still get a valid metric."""
    metrics = compute_job_posting_quality_metrics(
        total_input_records=1,
        accepted_records=[{"clean_description": "x" * 25}],
        rejected_records=[],
        duplicate_count=0,
        near_duplicate_count=0,
    )
    assert metrics["already_ingested_records"] == 0


def test_quality_metrics_empty_dataset():
    metrics = compute_job_posting_quality_metrics(
        total_input_records=0,
        accepted_records=[],
        rejected_records=[],
        duplicate_count=0,
        near_duplicate_count=0,
    )
    assert metrics["avg_text_length"] is None
    assert metrics["min_text_length"] is None
    assert metrics["max_text_length"] is None


def test_metrics_to_rows_flattens_nested_dict():
    metrics = {"total_records": 5, "removed_reasons": {"empty_description": 2, "too_short": 1}}
    rows = metrics_to_rows(metrics, analysis_run_id=1, source_id=2)
    names = {r["metric_name"] for r in rows}
    assert "total_records" in names
    assert "removed_reasons:empty_description" in names
    assert "removed_reasons:too_short" in names
    for r in rows:
        assert r["analysis_run_id"] == 1
        assert r["source_id"] == 2


def test_curriculum_quality_metrics():
    docs = [
        {"page_count": 3, "extraction_confidence": 0.8, "flagged_for_review": False, "courses_found": 2},
        {"page_count": 5, "extraction_confidence": 0.1, "flagged_for_review": True, "courses_found": 0},
    ]
    metrics = compute_curriculum_quality_metrics(docs)
    assert metrics["total_documents"] == 2
    assert metrics["flagged_for_review"] == 1
    assert metrics["total_courses_extracted"] == 2
    assert metrics["documents_with_zero_courses"] == 1


def test_skill_mention_quality_metrics_basic():
    persisted = [
        {"mapping_status": "mapped", "method": "exact_label", "normalized_text": "python"},
        {"mapping_status": "mapped", "method": "alias", "normalized_text": "ml"},
        {"mapping_status": "unmapped", "method": "technical_token", "normalized_text": "tensorflow"},
    ]
    metrics = compute_skill_mention_quality_metrics(
        source_records_processed=10,
        total_mentions=5,
        persisted_mentions=persisted,
        already_ingested_count=1,
        records_with_no_mentions=2,
    )
    assert metrics["source_records_processed"] == 10
    assert metrics["mentions_persisted"] == 3
    assert metrics["mapped_to_esco"] == 2
    assert metrics["unmapped"] == 1
    assert metrics["mapping_rate"] == round(2 / 3, 4)
    assert metrics["already_ingested_records"] == 1
    assert metrics["duplicate_mentions_removed"] == 1  # 5 found - 3 persisted - 1 already_ingested
    assert metrics["records_with_no_mentions"] == 2
    assert metrics["extraction_method_counts"] == {"exact_label": 1, "alias": 1, "technical_token": 1}


def test_skill_mention_quality_metrics_empty():
    metrics = compute_skill_mention_quality_metrics(
        source_records_processed=0, total_mentions=0, persisted_mentions=[],
    )
    assert metrics["mapping_rate"] is None
    assert metrics["mentions_persisted"] == 0


def test_temporal_industry_quality_metrics():
    metrics = compute_temporal_industry_quality_metrics(
        total_postings=100, dated_postings=80,
        postings_per_period={"2026-01": 40, "2026-02": 40},
        skills_with_sufficient_evidence=5, skills_with_insufficient_evidence=3,
    )
    assert metrics["undated_postings"] == 20
    assert metrics["periods_observed"] == 2
    assert metrics["skills_with_sufficient_evidence"] == 5


def test_temporal_curriculum_quality_metrics():
    metrics = compute_temporal_curriculum_quality_metrics(
        curriculum_versions=3, comparable_version_pairs=2,
        courses_per_version={"v1": 10, "v2": 12}, versions_with_missing_temporal_metadata=1,
    )
    assert metrics["curriculum_versions"] == 3
    assert metrics["comparable_version_pairs"] == 2


def test_drift_quality_metrics():
    drift_results = [
        {"status": "SKILL_ADDED"}, {"status": "SKILL_ADDED"},
        {"status": "COVERAGE_INCREASED"}, {"status": "UNCHANGED"},
        {"status": "INSUFFICIENT_DATA"},
    ]
    metrics = compute_drift_quality_metrics(drift_results)
    assert metrics["added_skills"] == 2
    assert metrics["increased_coverage"] == 1
    assert metrics["unchanged"] == 1
    assert metrics["insufficient_evidence"] == 1
    assert metrics["removed_skills"] == 0


def test_curriculum_quality_gates_all_pass():
    summary = {
        "course_count": 8, "topic_count": 40, "outcome_count": 20, "page_count": 30,
        "course_codes": ["CS101", "CS102", "CS103", "CS104", "CS105", "CS106", "CS107", "CS108"],
        "courses_with_zero_topics": [], "empty_topic_texts": 0, "malformed_course_codes": [],
        "has_semester_info": True, "expected_outcomes": True,
    }
    result = compute_curriculum_ingestion_quality_gates(summary)
    assert result["overall"] == "PASS"
    assert result["fail_count"] == 0


def test_curriculum_quality_gates_zero_courses_fails():
    summary = {
        "course_count": 0, "topic_count": 0, "outcome_count": 0, "page_count": 10,
        "course_codes": [], "courses_with_zero_topics": [], "empty_topic_texts": 0,
        "malformed_course_codes": [], "has_semester_info": False, "expected_outcomes": False,
    }
    result = compute_curriculum_ingestion_quality_gates(summary)
    assert result["overall"] == "FAIL"
    assert result["checks"]["course_count"][0] == "FAIL"


def test_curriculum_quality_gates_detects_duplicate_courses():
    summary = {
        "course_count": 5, "topic_count": 10, "outcome_count": 5, "page_count": 10,
        "course_codes": ["CS101", "CS101", "CS102", "CS103", "CS104"],
        "courses_with_zero_topics": [], "empty_topic_texts": 0, "malformed_course_codes": [],
        "has_semester_info": True, "expected_outcomes": True,
    }
    result = compute_curriculum_ingestion_quality_gates(summary)
    assert result["checks"]["duplicate_courses"][0] == "WARN"
    assert "CS101" in result["checks"]["duplicate_courses"][1]


def test_curriculum_quality_gates_low_extraction_volume_warns():
    summary = {
        "course_count": 1, "topic_count": 1, "outcome_count": 0, "page_count": 50,
        "course_codes": ["CS101"], "courses_with_zero_topics": [], "empty_topic_texts": 0,
        "malformed_course_codes": [], "has_semester_info": False, "expected_outcomes": False,
    }
    result = compute_curriculum_ingestion_quality_gates(summary)
    assert result["checks"]["extraction_volume"][0] == "WARN"


def test_curriculum_quality_gates_missing_outcomes_when_expected_warns():
    summary = {
        "course_count": 5, "topic_count": 10, "outcome_count": 0, "page_count": 10,
        "course_codes": ["CS101", "CS102", "CS103", "CS104", "CS105"],
        "courses_with_zero_topics": [], "empty_topic_texts": 0, "malformed_course_codes": [],
        "has_semester_info": True, "expected_outcomes": True,
    }
    result = compute_curriculum_ingestion_quality_gates(summary)
    assert result["checks"]["learning_outcomes"][0] == "WARN"


def test_curriculum_quality_gates_deterministic():
    summary = {
        "course_count": 3, "topic_count": 6, "outcome_count": 3, "page_count": 10,
        "course_codes": ["A1", "A2", "A3"], "courses_with_zero_topics": [], "empty_topic_texts": 0,
        "malformed_course_codes": [], "has_semester_info": True, "expected_outcomes": True,
    }
    r1 = compute_curriculum_ingestion_quality_gates(summary)
    r2 = compute_curriculum_ingestion_quality_gates(summary)
    assert r1 == r2
