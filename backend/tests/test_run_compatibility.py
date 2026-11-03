import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.run_compatibility import (
    check_dimension_compatibility,
    check_run_compatibility,
    COMPATIBLE,
    INCOMPATIBLE_SCOPE,
    UNKNOWN_SCOPE,
    NO_RUN,
)


def test_compatible_runs_same_scope():
    assert check_dimension_compatibility("global", "global", True) == COMPATIBLE


def test_incompatible_runs_different_scope():
    assert check_dimension_compatibility("global", "programme:3", True) == INCOMPATIBLE_SCOPE


def test_missing_dimension_scope_metadata():
    assert check_dimension_compatibility("global", None, True) == UNKNOWN_SCOPE


def test_missing_reference_scope_metadata():
    assert check_dimension_compatibility(None, "global", True) == UNKNOWN_SCOPE


def test_both_scopes_none_is_unknown_not_compatible():
    assert check_dimension_compatibility(None, None, True) == UNKNOWN_SCOPE


def test_multiple_dimensions_checked_together():
    result = check_run_compatibility(
        "global",
        {
            "trend": {"scope": "global", "exists": True},
            "drift": {"scope": "programme:3", "exists": True},
            "alignment": {"scope": None, "exists": True},
        },
    )
    assert result["trend"] == COMPATIBLE
    assert result["drift"] == INCOMPATIBLE_SCOPE
    assert result["alignment"] == UNKNOWN_SCOPE


def test_no_run_available():
    assert check_dimension_compatibility("global", "global", False) == NO_RUN
    assert check_dimension_compatibility("global", "programme:1", False) == NO_RUN


def test_repeated_calls_with_same_inputs_deterministic():
    r1 = check_dimension_compatibility("global", "global", True)
    r2 = check_dimension_compatibility("global", "global", True)
    assert r1 == r2 == COMPATIBLE


def test_check_run_compatibility_deterministic_and_order_independent():
    dims_a = {
        "trend": {"scope": "global", "exists": True},
        "drift": {"scope": "programme:5", "exists": True},
    }
    dims_b = {
        "drift": {"scope": "programme:5", "exists": True},
        "trend": {"scope": "global", "exists": True},
    }
    assert check_run_compatibility("global", dims_a) == check_run_compatibility("global", dims_b)


def test_empty_dimensions_returns_empty():
    assert check_run_compatibility("global", {}) == {}


def test_programme_scoped_reference_against_matching_programme():
    assert check_dimension_compatibility("programme:5", "programme:5", True) == COMPATIBLE


def test_programme_scoped_reference_against_different_programme():
    assert check_dimension_compatibility("programme:5", "programme:9", True) == INCOMPATIBLE_SCOPE
