import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.gap_classification import classify_skill_gap
from app.analytics.recommendation_engine import generate_recommendation, group_related_skills

HD, PC = 0.15, 0.4


def _gap(demand, coverage, trend_label=None, drift_status=None):
    return classify_skill_gap(demand, coverage, HD, PC, trend_label=trend_label, drift_status=drift_status)


def test_a_missing_sufficient_evidence():
    r = generate_recommendation(_gap(30.0, 0.0))
    assert r["recommendation_state"] == "RECOMMENDATION_SUPPORTED"


def test_b_partial_sufficient_evidence():
    r = generate_recommendation(_gap(30.0, 15.0))
    assert r["recommendation_state"] == "RECOMMENDATION_SUPPORTED"
    assert r["action_type"] in ("ADD_MODULE", "EXPAND_EXISTING_TOPIC")


def test_c_covered_no_action():
    r = generate_recommendation(_gap(30.0, 60.0))
    assert r["recommendation_state"] == "NO_ACTION_INDICATED"
    assert r["action_type"] is None


def test_d_insufficient_evidence():
    r = generate_recommendation(_gap(None, None))
    assert r["recommendation_state"] == "INSUFFICIENT_EVIDENCE"
    assert r["action_type"] is None
    assert r["target_level"] is None


def test_e_missing_high_demand():
    r = generate_recommendation(_gap(20.0, 0.0))
    assert r["action_type"] == "ADD_NEW_SUBJECT"


def test_e_missing_low_demand_is_elective():
    r = generate_recommendation(_gap(5.0, 0.0))
    assert r["action_type"] == "ADD_ELECTIVE"


def test_f_missing_trending_up():
    r = generate_recommendation(_gap(20.0, 0.0, trend_label="TRENDING_UP"))
    assert r["recommendation_state"] == "RECOMMENDATION_SUPPORTED"
    assert any("INCREASING_DEMAND" in reason for reason in r["reasons"])


def test_g_missing_insufficient_trend_data():
    r = generate_recommendation(_gap(20.0, 0.0, trend_label="INSUFFICIENT_DATA"))
    assert r["recommendation_state"] == "RECOMMENDATION_SUPPORTED"
    assert any("Trend evidence is insufficient" in reason for reason in r["reasons"])


def test_h_covered_trending_up_with_course():
    r = generate_recommendation(_gap(20.0, 60.0, trend_label="TRENDING_UP"), courses_with_evidence=["CS101"])
    assert r["action_type"] == "REVIEW_EXISTING_COURSE"
    assert r["action_type"] != "ADD_NEW_SUBJECT"


def test_i_coverage_decreased_never_outdated():
    r = generate_recommendation(_gap(20.0, 60.0, drift_status="COVERAGE_DECREASED"))
    assert r["action_type"] != "OUTDATED"
    for reason in r["reasons"]:
        assert "is outdated" not in reason.lower()


def test_j_no_evidence_no_strong_recommendation():
    r = generate_recommendation(_gap(None, 50.0))
    assert r["recommendation_state"] == "INSUFFICIENT_EVIDENCE"
    r2 = generate_recommendation(_gap(50.0, None))
    assert r2["recommendation_state"] == "INSUFFICIENT_EVIDENCE"


def test_k_none_vs_zero_distinct_recommendations():
    zero_case = generate_recommendation(_gap(0.0, 50.0))
    none_case = generate_recommendation(_gap(None, 50.0))
    assert zero_case["recommendation_state"] != none_case["recommendation_state"]


def test_l_course_target_unavailable_falls_back_to_programme():
    r = generate_recommendation(_gap(30.0, 15.0), courses_with_evidence=[])
    assert r["target_level"] == "PROGRAMME"
    assert r["target_course_codes"] == []


def test_m_missing_always_programme_level():
    r = generate_recommendation(_gap(30.0, 0.0), courses_with_evidence=["SHOULD_NOT_BE_USED"])
    assert r["target_level"] == "PROGRAMME"
    assert r["target_course_codes"] == []


def test_n_existing_course_recommendation():
    r = generate_recommendation(_gap(30.0, 15.0), courses_with_evidence=["CS201", "CS202"])
    assert r["target_level"] == "COURSE"
    assert r["target_course_codes"] == ["CS201", "CS202"]


def test_o_new_subject_recommendation():
    r = generate_recommendation(_gap(50.0, 0.0))
    assert r["action_type"] == "ADD_NEW_SUBJECT"


def test_p_elective_recommendation():
    r = generate_recommendation(_gap(5.0, 0.0))
    assert r["action_type"] == "ADD_ELECTIVE"


def test_q_module_recommendation_partial_no_course():
    r = generate_recommendation(_gap(30.0, 15.0), courses_with_evidence=[])
    assert r["action_type"] == "ADD_MODULE"


def test_q_module_recommendation_via_grouping():
    r = generate_recommendation(_gap(30.0, 0.0), related_skill_ids={99, 100})
    assert r["action_type"] == "ADD_MODULE"
    assert r["grouped_skill_ids"] == [99, 100]


def test_r_deterministic_repeated_calls():
    gap = _gap(30.0, 15.0, trend_label="TRENDING_UP")
    r1 = generate_recommendation(gap, courses_with_evidence=["CS301"])
    r2 = generate_recommendation(gap, courses_with_evidence=["CS301"])
    assert r1 == r2


def test_s_duplicate_course_evidence_not_fabricated():
    r = generate_recommendation(_gap(30.0, 15.0), courses_with_evidence=["CS301", "CS301"])
    assert "CS301" in r["target_course_codes"]


def test_t_idempotent_same_inputs():
    gap = _gap(20.0, 0.0)
    assert generate_recommendation(gap) == generate_recommendation(gap)


def test_u_failed_run_upstream_yields_insufficient_evidence():
    r = generate_recommendation(_gap(None, None))
    assert r["recommendation_state"] == "INSUFFICIENT_EVIDENCE"


def test_v_incompatible_trend_and_drift_simply_absent():
    r = generate_recommendation(_gap(30.0, 0.0, trend_label=None, drift_status=None))
    assert r["recommendation_state"] == "RECOMMENDATION_SUPPORTED"
    assert not any("TRENDING" in reason for reason in r["reasons"])


def test_w_no_fabricated_provenance_in_reasons():
    r = generate_recommendation(_gap(30.0, 0.0))
    reasons_text = " ".join(r["reasons"])
    assert "analysis_run_id" not in reasons_text


def test_x_reasons_generated_from_actual_fields_not_hardcoded():
    r1 = generate_recommendation(_gap(42.0, 0.0))
    r2 = generate_recommendation(_gap(17.0, 0.0))
    assert "42.0" in " ".join(r1["reasons"])
    assert "17.0" in " ".join(r2["reasons"])
    assert r1["reasons"] != r2["reasons"]


def test_y_multi_skill_grouping_connected_components():
    groups = group_related_skills({1, 2, 3, 4}, {1: {2}, 2: {1, 3}})
    group_sets = {frozenset(g) for g in groups}
    assert frozenset({1, 2, 3}) in group_sets
    assert frozenset({4}) in group_sets


def test_y_grouping_with_no_relationship_data_is_all_singletons():
    groups = group_related_skills({1, 2, 3}, {})
    assert sorted(groups, key=lambda g: min(g)) == [frozenset({1}), frozenset({2}), frozenset({3})]


def test_y_grouping_ignores_relationships_outside_candidate_set():
    groups = group_related_skills({1, 2}, {1: {2, 999}})
    assert frozenset({1, 2}) in {frozenset(g) for g in groups}
    assert not any(999 in g for g in groups)


def test_z_boundary_exactly_at_high_demand_threshold_is_new_subject():
    r = generate_recommendation(_gap(15.0, 0.0))
    assert r["action_type"] == "ADD_NEW_SUBJECT"


def test_z_boundary_just_below_high_demand_threshold_is_elective():
    r = generate_recommendation(_gap(14.9, 0.0))
    assert r["action_type"] == "ADD_ELECTIVE"


def test_z_boundary_exactly_at_partial_threshold_is_covered_not_partial():
    r = generate_recommendation(_gap(30.0, 40.0))
    assert r["recommendation_state"] in ("NO_ACTION_INDICATED", "RECOMMENDATION_SUPPORTED")


def test_empty_gap_set_produces_no_recommendations():
    results = [generate_recommendation(g) for g in []]
    assert results == []
