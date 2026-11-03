import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.skill_set_alignment import compute_skill_set_alignment, classify_demand_coverage, resolve_evidence_value


def test_jaccard_alignment_basic():
    result = compute_skill_set_alignment({1, 2, 3}, {2, 3, 4})
    assert result["intersection_count"] == 2
    assert result["union_count"] == 4
    assert result["jaccard_alignment_score"] == 0.5
    assert result["industry_only_count"] == 1
    assert result["curriculum_only_count"] == 1


def test_jaccard_identical_sets():
    result = compute_skill_set_alignment({1, 2}, {1, 2})
    assert result["jaccard_alignment_score"] == 1.0
    assert result["industry_only_count"] == 0
    assert result["curriculum_only_count"] == 0


def test_jaccard_disjoint_sets():
    result = compute_skill_set_alignment({1, 2}, {3, 4})
    assert result["jaccard_alignment_score"] == 0.0
    assert result["intersection_count"] == 0


def test_jaccard_both_empty_no_division_by_zero():
    result = compute_skill_set_alignment(set(), set())
    assert result["jaccard_alignment_score"] is None
    assert result["union_count"] == 0


def test_classify_high_demand_low_coverage():
    assert classify_demand_coverage(50.0, 5.0, 0.15, 0.15) == "HIGH_DEMAND_LOW_COVERAGE"


def test_classify_high_demand_high_coverage():
    assert classify_demand_coverage(50.0, 50.0, 0.15, 0.15) == "HIGH_DEMAND_HIGH_COVERAGE"


def test_classify_low_demand_high_coverage():
    assert classify_demand_coverage(5.0, 50.0, 0.15, 0.15) == "LOW_DEMAND_HIGH_COVERAGE"


def test_classify_low_demand_low_coverage():
    assert classify_demand_coverage(5.0, 5.0, 0.15, 0.15) == "LOW_DEMAND_LOW_COVERAGE"


def test_classify_boundary_exactly_at_threshold_counts_as_high():
    assert classify_demand_coverage(15.0, 15.0, 0.15, 0.15) == "HIGH_DEMAND_HIGH_COVERAGE"


def test_classify_both_none_is_insufficient_evidence():
    """Case 4: both sides missing -- must NOT be silently treated as 0%/0%."""
    assert classify_demand_coverage(None, None, 0.15, 0.15) == "INSUFFICIENT_EVIDENCE"


def test_classify_none_industry_present_curriculum_is_no_industry_evidence():
    """Case 3: industry evidence missing, curriculum evidence present."""
    assert classify_demand_coverage(None, 50.0, 0.15, 0.15) == "NO_INDUSTRY_EVIDENCE"


def test_classify_present_industry_none_curriculum_is_no_curriculum_evidence():
    """Case 2: industry evidence present, curriculum evidence missing."""
    assert classify_demand_coverage(50.0, None, 0.15, 0.15) == "NO_CURRICULUM_EVIDENCE"


def test_classify_genuine_zero_demand_is_not_missing_evidence():
    """
    Case A / case 5 from the regression spec: industry population exists,
    skill has zero observed postings -> demand_percentage = 0.0 is a REAL
    measurement, must classify normally (LOW_DEMAND), never as missing
    evidence. This is the core None-vs-zero distinction.
    """
    result = classify_demand_coverage(0.0, 50.0, 0.15, 0.15)
    assert result == "LOW_DEMAND_HIGH_COVERAGE"
    assert result != "NO_INDUSTRY_EVIDENCE"
    assert result != "INSUFFICIENT_EVIDENCE"


def test_classify_genuine_zero_coverage_is_not_missing_evidence():
    """Case 6: curriculum evidence exists, measured coverage is genuinely 0%."""
    result = classify_demand_coverage(50.0, 0.0, 0.15, 0.15)
    assert result == "HIGH_DEMAND_LOW_COVERAGE"
    assert result != "NO_CURRICULUM_EVIDENCE"
    assert result != "INSUFFICIENT_EVIDENCE"


def test_classify_case_a_vs_case_b_produce_different_states():
    """
    Regression spec Case A vs Case B: (demand=0%, coverage=50%) is a
    genuinely-measured low-demand skill; (demand=None, coverage=50%) is
    missing industry evidence entirely. These MUST differ.
    """
    case_a = classify_demand_coverage(0.0, 50.0, 0.15, 0.15)  # measured zero
    case_b = classify_demand_coverage(None, 50.0, 0.15, 0.15)  # missing evidence
    assert case_a != case_b
    assert case_a == "LOW_DEMAND_HIGH_COVERAGE"
    assert case_b == "NO_INDUSTRY_EVIDENCE"


def test_classify_case_c_vs_case_d_produce_different_states():
    """Regression spec Case C vs Case D: the coverage-side mirror of the above."""
    case_c = classify_demand_coverage(50.0, 0.0, 0.15, 0.15)  # measured zero coverage
    case_d = classify_demand_coverage(50.0, None, 0.15, 0.15)  # missing curriculum evidence
    assert case_c != case_d
    assert case_c == "HIGH_DEMAND_LOW_COVERAGE"
    assert case_d == "NO_CURRICULUM_EVIDENCE"


def test_classify_boundary_around_threshold_with_real_zero_values():
    """Boundary behavior: a measured 0% is always LOW relative to any positive threshold."""
    assert classify_demand_coverage(0.0, 0.0, 0.15, 0.15) == "LOW_DEMAND_LOW_COVERAGE"
    # exactly at threshold still counts as HIGH (>=), consistent with the existing boundary test above
    assert classify_demand_coverage(15.0, 0.0, 0.15, 0.15) == "HIGH_DEMAND_LOW_COVERAGE"


def test_classify_different_thresholds_change_result():
    assert classify_demand_coverage(20.0, 5.0, 0.15, 0.15) == "HIGH_DEMAND_LOW_COVERAGE"
    assert classify_demand_coverage(20.0, 5.0, 0.30, 0.15) == "LOW_DEMAND_LOW_COVERAGE"


def test_resolve_evidence_value_has_measurement_wins():
    """A real row always wins, even if the value happens to be 0.0."""
    assert resolve_evidence_value(0.0, True, 100) == 0.0
    assert resolve_evidence_value(42.5, True, 100) == 42.5
    assert resolve_evidence_value(42.5, True, 0) == 42.5  # population size irrelevant when measurement exists


def test_resolve_evidence_value_no_measurement_population_exists_is_zero():
    """No row, but the population existed -> genuine measured zero, not None."""
    assert resolve_evidence_value(None, False, 100) == 0.0


def test_resolve_evidence_value_no_measurement_no_population_is_none():
    """No row AND no population -> genuinely missing evidence."""
    assert resolve_evidence_value(None, False, 0) is None
    assert resolve_evidence_value(None, False, None) is None


def test_resolve_evidence_value_feeds_correctly_into_classification():
    """End-to-end pure simulation of the orchestration's per-skill resolution
    (Cases 1-6), without touching a database."""
    # Case: population existed (100 postings), skill never mentioned -> measured 0%
    demand = resolve_evidence_value(None, False, 100)
    coverage = resolve_evidence_value(None, False, 20)
    assert classify_demand_coverage(demand, coverage, 0.15, 0.15) == "LOW_DEMAND_LOW_COVERAGE"

    # Case: no industry population at all (0 postings) -> missing evidence
    demand2 = resolve_evidence_value(None, False, 0)
    coverage2 = resolve_evidence_value(None, False, 20)
    assert classify_demand_coverage(demand2, coverage2, 0.15, 0.15) == "NO_INDUSTRY_EVIDENCE"
