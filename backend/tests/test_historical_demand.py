import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.historical_demand import compute_historical_skill_demand


def test_repeated_skill_within_posting_counts_once_per_period():
    postings = [{"job_posting_id": 1, "posted_date": datetime(2026, 1, 5)}]
    mentions = [{"job_posting_id": 1, "normalized_skill_id": 10}] * 5
    result = compute_historical_skill_demand(postings, mentions, "month")
    assert result["periods"]["2026-01"][10]["posting_count"] == 1


def test_skill_across_multiple_periods_tracked_separately():
    postings = [
        {"job_posting_id": 1, "posted_date": datetime(2026, 1, 5)},
        {"job_posting_id": 2, "posted_date": datetime(2026, 2, 5)},
    ]
    mentions = [
        {"job_posting_id": 1, "normalized_skill_id": 10},
        {"job_posting_id": 2, "normalized_skill_id": 10},
    ]
    result = compute_historical_skill_demand(postings, mentions, "month")
    assert result["periods"]["2026-01"][10]["posting_count"] == 1
    assert result["periods"]["2026-02"][10]["posting_count"] == 1


def test_multiple_skills_independent_per_period():
    postings = [{"job_posting_id": 1, "posted_date": datetime(2026, 1, 5)}]
    mentions = [
        {"job_posting_id": 1, "normalized_skill_id": 10},
        {"job_posting_id": 1, "normalized_skill_id": 20},
    ]
    result = compute_historical_skill_demand(postings, mentions, "month")
    assert result["periods"]["2026-01"][10]["posting_count"] == 1
    assert result["periods"]["2026-01"][20]["posting_count"] == 1


def test_zero_demand_skill_not_fabricated_into_a_period_with_no_eligible_postings():
    postings = []
    mentions = []
    result = compute_historical_skill_demand(postings, mentions, "month")
    assert result["periods"] == {}
    assert result["dated_posting_ids"] == set()
    assert result["undated_posting_ids"] == set()


def test_missing_date_tracked_not_silently_excluded():
    postings = [
        {"job_posting_id": 1, "posted_date": datetime(2026, 1, 5)},
        {"job_posting_id": 2, "posted_date": None},
        {"job_posting_id": 3, "posted_date": None},
    ]
    mentions = [{"job_posting_id": 2, "normalized_skill_id": 10}]
    result = compute_historical_skill_demand(postings, mentions, "month")
    assert result["dated_posting_ids"] == {1}
    assert result["undated_posting_ids"] == {2, 3}
    assert 10 not in result["periods"].get("2026-01", {})


def test_denominator_is_per_period_not_global():
    postings = [
        {"job_posting_id": 1, "posted_date": datetime(2026, 1, 1)},
        {"job_posting_id": 2, "posted_date": datetime(2026, 1, 2)},
        {"job_posting_id": 3, "posted_date": datetime(2026, 2, 1)},
    ]
    mentions = [{"job_posting_id": 1, "normalized_skill_id": 10}]
    result = compute_historical_skill_demand(postings, mentions, "month")
    assert result["periods"]["2026-01"][10]["total_relevant_postings"] == 2
    assert result["periods"]["2026-01"][10]["demand_percentage"] == 50.0


def test_deterministic_repeated_calculation():
    postings = [{"job_posting_id": i, "posted_date": datetime(2026, 1, i % 28 + 1)} for i in range(10)]
    mentions = [{"job_posting_id": i, "normalized_skill_id": 10} for i in range(5)]
    r1 = compute_historical_skill_demand(postings, mentions, "month")
    r2 = compute_historical_skill_demand(postings, mentions, "month")
    assert r1["periods"] == r2["periods"]
