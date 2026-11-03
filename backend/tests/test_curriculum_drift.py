import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.curriculum_drift import compare_curriculum_versions, compare_courses, compare_course_skills


def test_skill_added():
    result = compare_curriculum_versions({}, {1: 20.0})
    assert result[1]["status"] == "SKILL_ADDED"
    assert result[1]["previous_coverage"] is None
    assert result[1]["current_coverage"] == 20.0


def test_skill_removed():
    result = compare_curriculum_versions({1: 20.0}, {})
    assert result[1]["status"] == "SKILL_REMOVED"
    assert result[1]["current_coverage"] is None


def test_coverage_increased():
    result = compare_curriculum_versions({1: 20.0}, {1: 35.0})
    assert result[1]["status"] == "COVERAGE_INCREASED"
    assert result[1]["absolute_change"] == 15.0


def test_coverage_decreased():
    result = compare_curriculum_versions({1: 35.0}, {1: 20.0})
    assert result[1]["status"] == "COVERAGE_DECREASED"
    assert result[1]["absolute_change"] == -15.0


def test_unchanged():
    result = compare_curriculum_versions({1: 20.0}, {1: 20.0})
    assert result[1]["status"] == "UNCHANGED"
    assert result[1]["absolute_change"] == 0.0


def test_genuine_zero_coverage_is_not_missing_previous_version():
    result = compare_curriculum_versions({1: 0.0}, {1: 25.0})
    assert result[1]["status"] == "COVERAGE_INCREASED"
    assert result[1]["previous_coverage"] == 0.0


def test_missing_previous_version_entirely():
    result = compare_curriculum_versions({1: None}, {1: None})
    assert result[1]["status"] == "INSUFFICIENT_DATA"


def test_missing_current_version_entirely():
    result = compare_curriculum_versions({1: 20.0}, {1: None})
    assert result[1]["status"] == "SKILL_REMOVED"


def test_never_labels_decreased_as_outdated():
    result = compare_curriculum_versions({1: 50.0}, {1: 10.0})
    assert "outdated" not in result[1]["status"].lower()
    assert result[1]["status"] == "COVERAGE_DECREASED"


def test_courses_added_removed_unchanged():
    result = compare_courses({"CS101", "CS201"}, {"CS101", "CS301"})
    assert result["added"] == {"CS301"}
    assert result["removed"] == {"CS201"}
    assert result["unchanged"] == {"CS101"}


def test_course_skills_added_removed_only_for_common_courses():
    previous = {"CS101": {1, 2}, "CS999": {5}}
    current = {"CS101": {2, 3}, "CS201": {7}}
    result = compare_course_skills(previous, current)
    assert set(result.keys()) == {"CS101"}
    assert result["CS101"]["added"] == {3}
    assert result["CS101"]["removed"] == {1}


def test_deterministic_repeated_calculation():
    previous = {1: 20.0, 2: 30.0}
    current = {1: 25.0, 3: 10.0}
    r1 = compare_curriculum_versions(previous, current)
    r2 = compare_curriculum_versions(previous, current)
    assert r1 == r2
