import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.curriculum_coverage import compute_curriculum_coverage


def test_multiple_mentions_in_one_course_count_once():
    mentions = [
        {"course_id": 1, "normalized_skill_id": 10, "mention_source": "curriculum_topic", "source_record_id": 100},
        {"course_id": 1, "normalized_skill_id": 10, "mention_source": "curriculum_topic", "source_record_id": 101},
        {"course_id": 2, "normalized_skill_id": 10, "mention_source": "course_title", "source_record_id": None},
    ]
    result = compute_curriculum_coverage(mentions, eligible_course_ids={1, 2, 3})
    assert result[10]["courses_with_skill"] == 2
    assert result[10]["eligible_courses"] == 3
    assert result[10]["coverage_percentage"] == round(2 / 3 * 100, 2)


def test_topic_and_outcome_counts_deduped_by_record_id():
    mentions = [
        {"course_id": 1, "normalized_skill_id": 10, "mention_source": "curriculum_topic", "source_record_id": 100},
        {"course_id": 1, "normalized_skill_id": 10, "mention_source": "curriculum_topic", "source_record_id": 100},
        {"course_id": 1, "normalized_skill_id": 10, "mention_source": "course_learning_outcome", "source_record_id": 500},
    ]
    result = compute_curriculum_coverage(mentions, eligible_course_ids={1})
    assert result[10]["topics_with_skill"] == 1
    assert result[10]["outcomes_with_skill"] == 1


def test_unmapped_mentions_excluded():
    mentions = [{"course_id": 1, "normalized_skill_id": None, "mention_source": "course_title", "source_record_id": None}]
    result = compute_curriculum_coverage(mentions, eligible_course_ids={1})
    assert result == {}


def test_courses_outside_eligible_set_excluded():
    mentions = [{"course_id": 99, "normalized_skill_id": 10, "mention_source": "course_title", "source_record_id": None}]
    result = compute_curriculum_coverage(mentions, eligible_course_ids={1, 2})
    assert result == {}


def test_empty_eligible_population_no_division_by_zero():
    mentions = [{"course_id": 1, "normalized_skill_id": 10, "mention_source": "course_title", "source_record_id": None}]
    result = compute_curriculum_coverage(mentions, eligible_course_ids=set())
    assert result == {}


def test_deterministic_repeated_calculation():
    mentions = [
        {"course_id": i, "normalized_skill_id": 10, "mention_source": "course_title", "source_record_id": None}
        for i in range(3)
    ]
    eligible = {0, 1, 2, 3, 4}
    r1 = compute_curriculum_coverage(mentions, eligible)
    r2 = compute_curriculum_coverage(mentions, eligible)
    assert r1 == r2
