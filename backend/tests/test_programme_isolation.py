import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.curriculum_coverage import compute_curriculum_coverage
from app.analytics.industry_demand import compute_skill_demand
from app.analytics.curriculum_drift import compare_curriculum_versions


def test_curriculum_coverage_isolates_ai_ds_from_ece():
    ai_ds_course_id, ece_course_id = 101, 201
    python_skill_id, vhdl_skill_id = 1, 2

    all_mentions = [
        {"course_id": ai_ds_course_id, "normalized_skill_id": python_skill_id, "mention_source": "course_title", "source_record_id": None},
        {"course_id": ece_course_id, "normalized_skill_id": vhdl_skill_id, "mention_source": "course_title", "source_record_id": None},
    ]

    ai_ds_coverage = compute_curriculum_coverage(all_mentions, eligible_course_ids={ai_ds_course_id})
    ece_coverage = compute_curriculum_coverage(all_mentions, eligible_course_ids={ece_course_id})

    assert python_skill_id in ai_ds_coverage
    assert vhdl_skill_id not in ai_ds_coverage
    assert vhdl_skill_id in ece_coverage
    assert python_skill_id not in ece_coverage


def test_curriculum_coverage_isolates_mechanical_from_civil_different_institutions():
    mech_course_id, civil_course_id = 301, 401
    autocad_skill_id, surveying_skill_id = 3, 4

    all_mentions = [
        {"course_id": mech_course_id, "normalized_skill_id": autocad_skill_id, "mention_source": "course_title", "source_record_id": None},
        {"course_id": civil_course_id, "normalized_skill_id": surveying_skill_id, "mention_source": "course_title", "source_record_id": None},
    ]

    mech_coverage = compute_curriculum_coverage(all_mentions, eligible_course_ids={mech_course_id})
    civil_coverage = compute_curriculum_coverage(all_mentions, eligible_course_ids={civil_course_id})

    assert autocad_skill_id in mech_coverage
    assert surveying_skill_id not in mech_coverage
    assert surveying_skill_id in civil_coverage
    assert autocad_skill_id not in civil_coverage


def test_industry_demand_isolates_by_discipline_scoped_posting_population():
    computing_posting_id, electronics_posting_id = 1001, 1002
    python_skill_id, vhdl_skill_id = 1, 2

    all_mentions = [
        {"job_posting_id": computing_posting_id, "normalized_skill_id": python_skill_id},
        {"job_posting_id": electronics_posting_id, "normalized_skill_id": vhdl_skill_id},
    ]

    computing_demand = compute_skill_demand(all_mentions, eligible_posting_ids={computing_posting_id})
    electronics_demand = compute_skill_demand(all_mentions, eligible_posting_ids={electronics_posting_id})

    assert python_skill_id in computing_demand
    assert vhdl_skill_id not in computing_demand
    assert vhdl_skill_id in electronics_demand
    assert python_skill_id not in electronics_demand


def test_same_skill_can_appear_in_multiple_programmes_independently():
    ai_ds_course_id, mechatronics_course_id = 101, 501
    python_skill_id = 1

    mentions = [
        {"course_id": ai_ds_course_id, "normalized_skill_id": python_skill_id, "mention_source": "course_title", "source_record_id": None},
        {"course_id": mechatronics_course_id, "normalized_skill_id": python_skill_id, "mention_source": "course_title", "source_record_id": None},
    ]

    ai_ds_coverage = compute_curriculum_coverage(mentions, eligible_course_ids={ai_ds_course_id})
    mechatronics_coverage = compute_curriculum_coverage(mentions, eligible_course_ids={mechatronics_course_id})
    combined_coverage = compute_curriculum_coverage(mentions, eligible_course_ids={ai_ds_course_id, mechatronics_course_id})

    assert ai_ds_coverage[python_skill_id]["courses_with_skill"] == 1
    assert mechatronics_coverage[python_skill_id]["courses_with_skill"] == 1
    assert combined_coverage[python_skill_id]["courses_with_skill"] == 2


def test_curriculum_version_isolation_two_versions_of_same_programme():
    v1_coverage = {1: 20.0, 2: 0.0}
    v2_coverage = {1: 40.0, 2: 0.0}

    drift = compare_curriculum_versions(v1_coverage, v2_coverage)
    assert drift[1]["previous_coverage"] == 20.0
    assert drift[1]["current_coverage"] == 40.0
    assert 90.0 not in [d["previous_coverage"] for d in drift.values()]
    assert 90.0 not in [d["current_coverage"] for d in drift.values()]


def test_cross_version_isolation_three_programmes_never_conflated():
    mech_courses = {301, 302}
    civil_courses = {401, 402}
    mech_postings = {1001, 1002}

    mentions_curriculum = [
        {"course_id": 301, "normalized_skill_id": 3, "mention_source": "course_title", "source_record_id": None},
        {"course_id": 401, "normalized_skill_id": 4, "mention_source": "course_title", "source_record_id": None},
    ]
    mentions_industry = [{"job_posting_id": 1001, "normalized_skill_id": 3}]

    mech_curriculum_result = compute_curriculum_coverage(mentions_curriculum, eligible_course_ids=mech_courses)
    civil_curriculum_result = compute_curriculum_coverage(mentions_curriculum, eligible_course_ids=civil_courses)
    mech_industry_result = compute_skill_demand(mentions_industry, eligible_posting_ids=mech_postings)

    assert 3 in mech_curriculum_result
    assert 4 not in mech_curriculum_result
    assert 4 in civil_curriculum_result
    assert 3 not in civil_curriculum_result
    assert 3 in mech_industry_result
    assert mech_industry_result[3]["total_relevant_postings"] == len(mech_postings)


def test_empty_scope_yields_empty_result_not_a_fallback_to_global():
    mentions = [{"course_id": 101, "normalized_skill_id": 1, "mention_source": "course_title", "source_record_id": None}]
    result = compute_curriculum_coverage(mentions, eligible_course_ids=set())
    assert result == {}
