import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.gap_classification import classify_skill_gap, aggregate_gap_counts

HD = 0.15
PC = 0.4


def test_a_industry_evidence_absent():
    r = classify_skill_gap(None, 30.0, HD, PC)
    assert r["classification"] == "INSUFFICIENT_EVIDENCE"
    assert r["evidence_state"] == "NO_INDUSTRY_EVIDENCE"


def test_b_industry_evidence_genuinely_zero():
    r = classify_skill_gap(0.0, 0.0, HD, PC)
    assert r["evidence_state"] == "BOTH_MEASURED"
    assert r["classification"] == "COVERED"


def test_c_curriculum_evidence_absent():
    r = classify_skill_gap(40.0, None, HD, PC)
    assert r["classification"] == "INSUFFICIENT_EVIDENCE"
    assert r["evidence_state"] == "NO_CURRICULUM_EVIDENCE"


def test_d_curriculum_evidence_genuinely_zero():
    r = classify_skill_gap(40.0, 0.0, HD, PC)
    assert r["classification"] == "MISSING"
    assert r["curriculum_coverage_percentage"] == 0.0


def test_e_missing_skill():
    r = classify_skill_gap(50.0, 0.0, HD, PC)
    assert r["classification"] == "MISSING"


def test_f_partial_skill():
    r = classify_skill_gap(50.0, 15.0, HD, PC)
    assert r["classification"] == "PARTIAL"


def test_g_covered_skill():
    r = classify_skill_gap(50.0, 45.0, HD, PC)
    assert r["classification"] == "COVERED"


def test_h_insufficient_evidence_both_missing():
    r = classify_skill_gap(None, None, HD, PC)
    assert r["classification"] == "INSUFFICIENT_EVIDENCE"
    assert r["evidence_state"] == "NO_EVIDENCE"


def test_i_high_demand_missing_skill():
    r = classify_skill_gap(20.0, 0.0, HD, PC)
    assert r["classification"] == "MISSING"
    assert r["high_demand"] is True


def test_j_increasing_demand_missing_skill():
    r = classify_skill_gap(20.0, 0.0, HD, PC, trend_label="TRENDING_UP")
    assert r["classification"] == "MISSING"
    assert r["demand_trend_signal"] == "INCREASING_DEMAND"


def test_k_increasing_demand_partial_skill():
    r = classify_skill_gap(20.0, 15.0, HD, PC, trend_label="TRENDING_UP")
    assert r["classification"] == "PARTIAL"
    assert r["demand_trend_signal"] == "INCREASING_DEMAND"


def test_l_covered_plus_increasing_demand():
    r = classify_skill_gap(20.0, 50.0, HD, PC, trend_label="TRENDING_UP")
    assert r["classification"] == "COVERED"
    assert r["demand_trend_signal"] == "INCREASING_DEMAND"


def test_m_missing_plus_insufficient_trend_data():
    r = classify_skill_gap(20.0, 0.0, HD, PC, trend_label="INSUFFICIENT_DATA")
    assert r["classification"] == "MISSING"
    assert r["demand_trend_signal"] == "INSUFFICIENT_TREND_DATA"
    r2 = classify_skill_gap(20.0, 0.0, HD, PC, trend_label=None)
    assert r2["demand_trend_signal"] == "INSUFFICIENT_TREND_DATA"


def test_n_curriculum_drift_plus_gap_combination():
    r = classify_skill_gap(20.0, 50.0, HD, PC, drift_status="COVERAGE_DECREASED")
    assert r["classification"] == "COVERED"
    assert r["drift_status"] == "COVERAGE_DECREASED"
    assert r["classification"] != "OUTDATED"


def test_o_none_vs_zero_never_conflated():
    zero_case = classify_skill_gap(0.0, 50.0, HD, PC)
    none_case = classify_skill_gap(None, 50.0, HD, PC)
    assert zero_case["classification"] != none_case["classification"]
    assert zero_case["evidence_state"] != none_case["evidence_state"]
    assert zero_case["industry_demand_percentage"] == 0.0
    assert none_case["industry_demand_percentage"] is None


def test_p_boundary_exactly_at_partial_threshold_counts_as_covered():
    r = classify_skill_gap(50.0, 40.0, HD, PC)
    assert r["classification"] == "COVERED"


def test_p_boundary_just_below_partial_threshold_is_partial():
    r = classify_skill_gap(50.0, 39.9, HD, PC)
    assert r["classification"] == "PARTIAL"


def test_p_boundary_exactly_at_high_demand_threshold():
    r = classify_skill_gap(15.0, 50.0, HD, PC)
    assert r["high_demand"] is True


def test_p_different_thresholds_change_result():
    r_default = classify_skill_gap(50.0, 45.0, HD, PC)  # 45% >= 40% default threshold -> COVERED
    r_stricter = classify_skill_gap(50.0, 45.0, HD, 0.5)  # raise partial threshold to 50% -> now PARTIAL
    assert r_default["classification"] == "COVERED"
    assert r_stricter["classification"] == "PARTIAL"


def test_q_deterministic_repeated_calls():
    r1 = classify_skill_gap(50.0, 30.0, HD, PC, trend_label="TRENDING_UP", drift_status="UNCHANGED")
    r2 = classify_skill_gap(50.0, 30.0, HD, PC, trend_label="TRENDING_UP", drift_status="UNCHANGED")
    assert r1 == r2


def test_r_aggregate_empty_dataset():
    counts = aggregate_gap_counts([])
    assert counts["total_skills_classified"] == 0
    assert counts["missing_count"] == 0


def test_s_aggregate_counts_records_as_given():
    r = classify_skill_gap(50.0, 0.0, HD, PC)
    counts = aggregate_gap_counts([r, r, r])
    assert counts["missing_count"] == 3
    assert counts["total_skills_classified"] == 3


def test_aggregate_gap_counts_realistic_mix():
    records = [
        classify_skill_gap(20.0, 0.0, HD, PC),
        classify_skill_gap(50.0, 15.0, HD, PC, trend_label="TRENDING_UP"),
        classify_skill_gap(50.0, 60.0, HD, PC),
        classify_skill_gap(None, None, HD, PC),
    ]
    counts = aggregate_gap_counts(records)
    assert counts["total_skills_classified"] == 4
    assert counts["missing_count"] == 1
    assert counts["partial_count"] == 1
    assert counts["covered_count"] == 1
    assert counts["insufficient_evidence_count"] == 1
    assert counts["high_demand_missing_count"] == 1
    assert counts["increasing_demand_partial_count"] == 1


def test_never_labels_decreased_coverage_as_outdated():
    r = classify_skill_gap(50.0, 60.0, HD, PC, drift_status="COVERAGE_DECREASED")
    assert r["classification"] != "OUTDATED"
    assert r["classification"] == "COVERED"


def test_reasons_always_populated_and_explainable():
    for args in [
        (None, None, HD, PC), (50.0, None, HD, PC), (None, 50.0, HD, PC),
        (0.0, 0.0, HD, PC), (50.0, 0.0, HD, PC), (50.0, 20.0, HD, PC), (50.0, 60.0, HD, PC),
    ]:
        r = classify_skill_gap(*args)
        assert isinstance(r["reasons"], list) and len(r["reasons"]) >= 1
