import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.trend_analysis import (
    compute_absolute_change,
    compute_percentage_point_change,
    compute_relative_change,
    assess_trend_sufficiency,
    compute_trend_label,
)


def test_percentage_point_vs_relative_change_are_different():
    pp = compute_percentage_point_change(5, 8)
    rel = compute_relative_change(5, 8)
    assert pp == 3
    assert rel == 60.0
    assert pp != rel


def test_absolute_change_basic():
    assert compute_absolute_change(5, 8) == 3
    assert compute_absolute_change(8, 5) == -3
    assert compute_absolute_change(5, 5) == 0


def test_relative_change_zero_to_positive_returns_none():
    assert compute_relative_change(0, 5) is None


def test_relative_change_positive_to_zero_is_negative_100():
    assert compute_relative_change(5, 0) == -100.0


def test_relative_change_equal_values_is_zero():
    assert compute_relative_change(5, 5) == 0.0


def test_missing_values_return_none_not_zero():
    assert compute_absolute_change(None, 5) is None
    assert compute_absolute_change(5, None) is None
    assert compute_percentage_point_change(None, None) is None
    assert compute_relative_change(None, 5) is None
    assert compute_relative_change(5, None) is None


def test_sufficiency_enough_periods_and_postings():
    assert assess_trend_sufficiency(3, [50, 60, 70], 10, 2, 30, 5) is True


def test_sufficiency_insufficient_periods():
    assert assess_trend_sufficiency(1, [50], 10, 2, 30, 5) is False


def test_sufficiency_insufficient_eligible_population():
    assert assess_trend_sufficiency(2, [50, 5], 10, 2, 30, 5) is False


def test_sufficiency_insufficient_skill_observations():
    assert assess_trend_sufficiency(2, [50, 60], 2, 2, 30, 5) is False


def test_trend_label_up_down_stable():
    assert compute_trend_label(5, 8, True) == "TRENDING_UP"
    assert compute_trend_label(8, 5, True) == "TRENDING_DOWN"
    assert compute_trend_label(5, 5, True) == "STABLE"


def test_trend_label_insufficient_never_forces_up_or_down():
    assert compute_trend_label(5, 8, False) == "INSUFFICIENT_DATA"
    assert compute_trend_label(None, 8, True) == "INSUFFICIENT_DATA"
    assert compute_trend_label(5, None, True) == "INSUFFICIENT_DATA"
    assert compute_trend_label(None, None, False) == "INSUFFICIENT_DATA"


def test_deterministic_repeated_calls():
    assert compute_relative_change(5, 8) == compute_relative_change(5, 8)
    assert compute_trend_label(5, 8, True) == compute_trend_label(5, 8, True)
