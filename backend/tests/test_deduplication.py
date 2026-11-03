import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.preprocessing.deduplication import (
    jaccard_similarity,
    shingles,
    find_near_duplicates,
    partition_already_ingested,
)


def test_identical_text_similarity_is_one():
    s1 = shingles("python developer needed with aws and docker experience")
    s2 = shingles("python developer needed with aws and docker experience")
    assert jaccard_similarity(s1, s2) == 1.0


def test_unrelated_text_low_similarity():
    s1 = shingles("python developer needed with aws and docker experience")
    s2 = shingles("we are hiring a marketing manager for our retail team")
    assert jaccard_similarity(s1, s2) < 0.2


def test_find_near_duplicates_flags_reposts():
    postings = [
        {"id": 1, "job_title": "Data Scientist", "company_name": "Acme",
         "clean_description": "We need a data scientist skilled in python sql and machine learning models daily"},
        {"id": 2, "job_title": "Data Scientist", "company_name": "Acme",
         "clean_description": "We need a data scientist skilled in python sql and machine learning models daily."},
        {"id": 3, "job_title": "Backend Engineer", "company_name": "Acme",
         "clean_description": "We are looking for a backend engineer with strong golang and kubernetes skills"},
    ]
    dup_map = find_near_duplicates(postings, similarity_threshold=0.8)
    assert dup_map.get(2) == 1
    assert 3 not in dup_map


def test_partition_already_ingested_splits_correctly():
    """PHASE-1 HARDENING: idempotency partition logic (item 1)."""
    rows = [
        {"external_posting_id": "J1", "job_title": "A"},
        {"external_posting_id": "J2", "job_title": "B"},
        {"external_posting_id": "J3", "job_title": "C"},
    ]
    existing = {"J2"}
    new_rows, already_ingested = partition_already_ingested(rows, existing)
    assert [r["external_posting_id"] for r in new_rows] == ["J1", "J3"]
    assert [r["external_posting_id"] for r in already_ingested] == ["J2"]


def test_partition_already_ingested_repeated_run_skips_everything():
    """Simulates re-running ingestion on an identical file: every row should
    already be in `existing`, so nothing is treated as new the second time."""
    rows = [{"external_posting_id": f"J{i}"} for i in range(5)]
    existing = {f"J{i}" for i in range(5)}
    new_rows, already_ingested = partition_already_ingested(rows, existing)
    assert new_rows == []
    assert len(already_ingested) == 5


def test_partition_already_ingested_rows_without_external_id_always_new():
    """Some real datasets have no external id at all -- those rows can never
    be deduplicated by this mechanism and must always pass through as new."""
    rows = [{"external_posting_id": None, "job_title": "No ID job"}]
    new_rows, already_ingested = partition_already_ingested(rows, {"J1"})
    assert len(new_rows) == 1
    assert already_ingested == []
