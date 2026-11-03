"""
Skill-set alignment (intersection/union) and demand/coverage classification.

CALCULATED METRIC vs METHODOLOGICAL THRESHOLD: the Jaccard score itself is a
calculated metric; HIGH/LOW demand and coverage are methodological
classifications that depend on a threshold the caller supplies (never
hardcoded here) -- see backend/app/core/config.py
(high_demand_threshold / high_coverage_threshold).

Per spec Section 18: this module deliberately does NOT combine skill-set
alignment with TF-IDF alignment (see tfidf_alignment.py) into any single
weighted score. They are reported side by side, never merged.
"""


def compute_skill_set_alignment(industry_skill_ids: set, curriculum_skill_ids: set) -> dict:
    """
    Jaccard similarity: |intersection| / |union|. Documented, transparent,
    not a black box -- every count in the result is independently checkable.
    """
    intersection = industry_skill_ids & curriculum_skill_ids
    union = industry_skill_ids | curriculum_skill_ids
    industry_only = industry_skill_ids - curriculum_skill_ids
    curriculum_only = curriculum_skill_ids - industry_skill_ids

    return {
        "method": "jaccard_intersection_over_union",
        "industry_skill_count": len(industry_skill_ids),
        "curriculum_skill_count": len(curriculum_skill_ids),
        "intersection_count": len(intersection),
        "union_count": len(union),
        "industry_only_count": len(industry_only),
        "curriculum_only_count": len(curriculum_only),
        "jaccard_alignment_score": round(len(intersection) / len(union), 4) if union else None,
    }


def classify_demand_coverage(
    demand_percentage,
    coverage_percentage,
    high_demand_threshold: float,
    high_coverage_threshold: float,
) -> str:
    """
    Transparent, threshold-based classification -- NOT a recommendation.
    Thresholds are supplied by the caller (from app.core.config), never
    hardcoded here.

    CRITICAL: None and 0.0 are NOT the same thing and must never be conflated.
    - demand_percentage / coverage_percentage = None means NO EVIDENCE exists
      for that side of the comparison (e.g. no industry population was
      available at all, or the skill was never considered for that side).
    - demand_percentage / coverage_percentage = 0.0 means evidence WAS
      collected and the measured value is genuinely zero (e.g. a real
      job-posting population existed and zero postings mentioned the skill).
    Silently doing `value = value or 0.0` would destroy this distinction --
    every "no evidence" case would be misreported as "measured 0%, hence
    LOW_DEMAND/LOW_COVERAGE", which is a false analytical claim. Callers
    (see app.analytics.run_analysis.run_skill_alignment_analysis) are
    responsible for resolving which case applies BEFORE calling this
    function -- this function only distinguishes None from a real number,
    it never guesses.

    Returns one of:
      INSUFFICIENT_EVIDENCE      -- both sides missing (case 4)
      NO_INDUSTRY_EVIDENCE       -- industry side missing, curriculum side present (case 3)
      NO_CURRICULUM_EVIDENCE     -- curriculum side missing, industry side present (case 2)
      HIGH_DEMAND_LOW_COVERAGE / HIGH_DEMAND_HIGH_COVERAGE /
      LOW_DEMAND_HIGH_COVERAGE / LOW_DEMAND_LOW_COVERAGE
                                  -- both sides present (cases 1, 5, 6); a
                                     genuinely-measured 0% on either side is
                                     compared against its threshold normally,
                                     just like any other real percentage.
    """
    if demand_percentage is None and coverage_percentage is None:
        return "INSUFFICIENT_EVIDENCE"
    if demand_percentage is None:
        return "NO_INDUSTRY_EVIDENCE"
    if coverage_percentage is None:
        return "NO_CURRICULUM_EVIDENCE"

    demand_threshold_pct = high_demand_threshold * 100
    coverage_threshold_pct = high_coverage_threshold * 100

    high_demand = demand_percentage >= demand_threshold_pct
    high_coverage = coverage_percentage >= coverage_threshold_pct

    if high_demand and not high_coverage:
        return "HIGH_DEMAND_LOW_COVERAGE"
    if high_demand and high_coverage:
        return "HIGH_DEMAND_HIGH_COVERAGE"
    if not high_demand and high_coverage:
        return "LOW_DEMAND_HIGH_COVERAGE"
    return "LOW_DEMAND_LOW_COVERAGE"


def resolve_evidence_value(measured_value, has_measurement, population_size):
    """
    The actual None-vs-zero resolution decision, extracted as a pure function
    so it's testable without a database. Given:
      - measured_value: the value from an actual GOLD row if one exists (e.g.
        SkillDemand.demand_percentage), or None if no such row exists.
      - has_measurement: whether a GOLD row actually exists for this skill.
      - population_size: the eligible population size for this side of the
        comparison (e.g. eligible_job_postings), used ONLY when
        has_measurement is False, to decide between "measured zero" and
        "no evidence at all".

    Returns the resolved value:
      - measured_value, if has_measurement is True (a real row exists)
      - 0.0, if there is no row but population_size > 0 (population existed,
        this skill simply had zero occurrences -- a genuine measurement)
      - None, if there is no row and population_size <= 0 (no population at
        all -- genuinely missing evidence)
    """
    if has_measurement:
        return measured_value
    if population_size and population_size > 0:
        return 0.0
    return None
