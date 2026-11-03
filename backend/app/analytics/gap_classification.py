"""
Evidence-based curriculum gap classification. Pure, no DB, no side effects.

FOUR STATES, deterministically derived from resolved (None-vs-zero already
decided by the caller, per app.analytics.skill_set_alignment.resolve_evidence_value)
industry demand and curriculum coverage percentages:

    MISSING               industry demand is real and non-zero; curriculum coverage is genuinely zero.
    PARTIAL               curriculum coverage is real but below the configured partial-coverage threshold.
    COVERED               either (a) curriculum coverage meets/exceeds the threshold, or
                           (b) industry demand is genuinely zero -- no unmet demand means no
                           meaningful gap, regardless of curriculum coverage (spec: "a skill
                           absent from the curriculum is not automatically a meaningful gap
                           unless there is sufficient industry evidence").
    INSUFFICIENT_EVIDENCE either side's population/evidence was unavailable (None).

trend_label and drift_status are separate EVIDENCE DIMENSIONS passed through
unchanged -- NEVER folded into classification. A MISSING skill with
TRENDING_DOWN demand is still MISSING; a COVERED skill with
COVERAGE_DECREASED drift is still COVERED and is NEVER relabeled "outdated".
"""

CLASSIFICATION_MISSING = "MISSING"
CLASSIFICATION_PARTIAL = "PARTIAL"
CLASSIFICATION_COVERED = "COVERED"
CLASSIFICATION_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

EVIDENCE_BOTH_MEASURED = "BOTH_MEASURED"
EVIDENCE_NO_INDUSTRY = "NO_INDUSTRY_EVIDENCE"
EVIDENCE_NO_CURRICULUM = "NO_CURRICULUM_EVIDENCE"
EVIDENCE_NONE = "NO_EVIDENCE"

_TREND_TO_SIGNAL = {
    "TRENDING_UP": "INCREASING_DEMAND",
    "TRENDING_DOWN": "DECREASING_DEMAND",
    "STABLE": "STABLE_DEMAND",
    "INSUFFICIENT_DATA": "INSUFFICIENT_TREND_DATA",
}


def classify_skill_gap(
    industry_demand_percentage,
    curriculum_coverage_percentage,
    high_demand_threshold,
    partial_coverage_threshold,
    trend_label=None,
    drift_status=None,
):
    """
    industry_demand_percentage / curriculum_coverage_percentage: float (0-100)
        or None. Caller MUST have already resolved None-vs-zero.
    high_demand_threshold / partial_coverage_threshold: fractions (e.g. 0.15,
        0.40) from app.core.config -- never hardcoded here.
    trend_label / drift_status: passed straight through as descriptive
        evidence, never folded into the classification.
    """
    reasons = []

    if industry_demand_percentage is None and curriculum_coverage_percentage is None:
        evidence_state = EVIDENCE_NONE
        classification = CLASSIFICATION_INSUFFICIENT_EVIDENCE
        reasons.append("No industry population and no curriculum population were available for this skill.")
    elif industry_demand_percentage is None:
        evidence_state = EVIDENCE_NO_INDUSTRY
        classification = CLASSIFICATION_INSUFFICIENT_EVIDENCE
        reasons.append("No industry population was available; a curriculum gap cannot be judged meaningful without industry evidence.")
    elif curriculum_coverage_percentage is None:
        evidence_state = EVIDENCE_NO_CURRICULUM
        classification = CLASSIFICATION_INSUFFICIENT_EVIDENCE
        reasons.append("No curriculum population was available for this skill/programme.")
    else:
        evidence_state = EVIDENCE_BOTH_MEASURED
        partial_threshold_pct = partial_coverage_threshold * 100
        if industry_demand_percentage == 0.0:
            classification = CLASSIFICATION_COVERED
            reasons.append(
                "Industry demand is genuinely zero (a real population existed and this skill was "
                "never mentioned); curriculum absence is not treated as a meaningful gap."
            )
        elif curriculum_coverage_percentage == 0.0:
            classification = CLASSIFICATION_MISSING
            reasons.append(
                f"Industry demand is {industry_demand_percentage}% (real, non-zero) but measured "
                f"curriculum coverage is genuinely zero."
            )
        elif curriculum_coverage_percentage < partial_threshold_pct:
            classification = CLASSIFICATION_PARTIAL
            reasons.append(
                f"Curriculum coverage ({curriculum_coverage_percentage}%) is below the configured "
                f"partial-coverage threshold ({partial_threshold_pct:.0f}%)."
            )
        else:
            classification = CLASSIFICATION_COVERED
            reasons.append(
                f"Curriculum coverage ({curriculum_coverage_percentage}%) meets or exceeds the "
                f"configured partial-coverage threshold ({partial_threshold_pct:.0f}%)."
            )

    high_demand = (
        industry_demand_percentage is not None and industry_demand_percentage >= high_demand_threshold * 100
    )
    if industry_demand_percentage is not None and high_demand:
        reasons.append(
            f"Industry demand ({industry_demand_percentage}%) meets or exceeds the high-demand "
            f"threshold ({high_demand_threshold * 100:.0f}%)."
        )

    demand_trend_signal = _TREND_TO_SIGNAL.get(trend_label, "INSUFFICIENT_TREND_DATA")
    if trend_label is not None:
        reasons.append(f"Demand trend signal: {demand_trend_signal} (trend_label={trend_label}).")

    if drift_status is not None:
        reasons.append(
            f"Curriculum drift status for this skill: {drift_status} (descriptive only -- "
            f"never reinterpreted as gap severity or an 'outdated' label)."
        )

    return {
        "classification": classification,
        "evidence_state": evidence_state,
        "industry_demand_percentage": industry_demand_percentage,
        "curriculum_coverage_percentage": curriculum_coverage_percentage,
        "high_demand": high_demand if industry_demand_percentage is not None else None,
        "demand_trend_signal": demand_trend_signal,
        "trend_label": trend_label,
        "drift_status": drift_status,
        "reasons": reasons,
    }


def aggregate_gap_counts(gap_records):
    """
    Transparent, traceable programme/institution-level counts (spec Section
    8) -- NEVER an arbitrary composite "programme score". Every count here
    is directly derivable by filtering the underlying skill-level records.
    """
    counts = {
        "total_skills_classified": len(gap_records),
        "missing_count": 0,
        "partial_count": 0,
        "covered_count": 0,
        "insufficient_evidence_count": 0,
        "high_demand_missing_count": 0,
        "high_demand_partial_count": 0,
        "increasing_demand_missing_count": 0,
        "increasing_demand_partial_count": 0,
        "decreasing_demand_covered_count": 0,
    }
    for r in gap_records:
        classification = r["classification"]
        if classification == CLASSIFICATION_MISSING:
            counts["missing_count"] += 1
        elif classification == CLASSIFICATION_PARTIAL:
            counts["partial_count"] += 1
        elif classification == CLASSIFICATION_COVERED:
            counts["covered_count"] += 1
        elif classification == CLASSIFICATION_INSUFFICIENT_EVIDENCE:
            counts["insufficient_evidence_count"] += 1

        if r.get("high_demand"):
            if classification == CLASSIFICATION_MISSING:
                counts["high_demand_missing_count"] += 1
            elif classification == CLASSIFICATION_PARTIAL:
                counts["high_demand_partial_count"] += 1

        signal = r.get("demand_trend_signal")
        if signal == "INCREASING_DEMAND":
            if classification == CLASSIFICATION_MISSING:
                counts["increasing_demand_missing_count"] += 1
            elif classification == CLASSIFICATION_PARTIAL:
                counts["increasing_demand_partial_count"] += 1
        elif signal == "DECREASING_DEMAND" and classification == CLASSIFICATION_COVERED:
            counts["decreasing_demand_covered_count"] += 1

    return counts
