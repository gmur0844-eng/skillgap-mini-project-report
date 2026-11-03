import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.industry_demand import compute_skill_demand


def test_multiple_mentions_in_one_posting_count_once():
    mentions = [{"job_posting_id": 1, "normalized_skill_id": 10}] * 8
    mentions.append({"job_posting_id": 2, "normalized_skill_id": 10})
    result = compute_skill_demand(mentions, eligible_posting_ids={1, 2, 3, 4})
    assert result[10]["posting_count"] == 2
    assert result[10]["total_relevant_postings"] == 4
    assert result[10]["demand_percentage"] == 50.0


def test_unmapped_mentions_excluded():
    mentions = [
        {"job_posting_id": 1, "normalized_skill_id": None},
        {"job_posting_id": 2, "normalized_skill_id": 10},
    ]
    result = compute_skill_demand(mentions, eligible_posting_ids={1, 2})
    assert 10 in result
    assert result[10]["posting_count"] == 1
    assert None not in result


def test_postings_outside_eligible_set_excluded():
    mentions = [{"job_posting_id": 99, "normalized_skill_id": 10}]
    result = compute_skill_demand(mentions, eligible_posting_ids={1, 2, 3})
    assert result == {}


def test_empty_mentions():
    result = compute_skill_demand([], eligible_posting_ids={1, 2, 3})
    assert result == {}


def test_empty_eligible_population_no_division_by_zero():
    mentions = [{"job_posting_id": 1, "normalized_skill_id": 10}]
    result = compute_skill_demand(mentions, eligible_posting_ids=set())
    assert result == {}


def test_deterministic_repeated_calculation():
    mentions = [{"job_posting_id": i, "normalized_skill_id": 10} for i in range(5)]
    eligible = set(range(10))
    r1 = compute_skill_demand(mentions, eligible)
    r2 = compute_skill_demand(mentions, eligible)
    assert r1 == r2


def test_multiple_skills_independent():
    mentions = [
        {"job_posting_id": 1, "normalized_skill_id": 10},
        {"job_posting_id": 1, "normalized_skill_id": 20},
        {"job_posting_id": 2, "normalized_skill_id": 10},
    ]
    result = compute_skill_demand(mentions, eligible_posting_ids={1, 2})
    assert result[10]["posting_count"] == 2
    assert result[20]["posting_count"] == 1
    assert result[10]["demand_percentage"] == 100.0
    assert result[20]["demand_percentage"] == 50.0
