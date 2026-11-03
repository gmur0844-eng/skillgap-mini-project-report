"""
Trend calculations (spec Section 6/7). Pure, no DB, no current-date
dependency. Percentage-point change and relative change are DIFFERENT
numbers and must never be confused (5% -> 8% is +3 percentage points AND
+60% relative change -- both true, describing different things).
"""


def compute_absolute_change(previous, current):
    """current - previous. None if either side is missing."""
    if previous is None or current is None:
        return None
    return round(current - previous, 4)


def compute_percentage_point_change(previous_percentage, current_percentage):
    """
    Same arithmetic as compute_absolute_change but named separately per spec
    for percentage-point (pp) values specifically. 5% -> 8% = +3 pp.
    """
    return compute_absolute_change(previous_percentage, current_percentage)


def compute_relative_change(previous, current):
    """
    (current - previous) / previous * 100. 5% -> 8% = +60% relative change.
    Returns None (not infinity, not a fabricated number) when previous == 0
    -- relative change from a zero base is mathematically undefined.
    Also None if either input is missing.
    """
    if previous is None or current is None:
        return None
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 4)


def assess_trend_sufficiency(
    num_periods,
    eligible_postings_per_period,
    skill_posting_count_total,
    min_periods_for_trend,
    min_eligible_postings_per_period,
    min_skill_postings_for_trend,
):
    """
    Configurable minimum-evidence rule (spec Section 7). All thresholds are
    supplied by the caller (from app.core.config), never hardcoded here.
    """
    if num_periods < min_periods_for_trend:
        return False
    if any(p < min_eligible_postings_per_period for p in eligible_postings_per_period):
        return False
    if skill_posting_count_total < min_skill_postings_for_trend:
        return False
    return True


def compute_trend_label(previous_percentage, current_percentage, is_sufficient):
    """
    Returns "INSUFFICIENT_DATA" whenever is_sufficient is False or either
    percentage is missing -- NEVER forces TRENDING_UP/TRENDING_DOWN from
    inadequate evidence.
    """
    if not is_sufficient or previous_percentage is None or current_percentage is None:
        return "INSUFFICIENT_DATA"
    if current_percentage > previous_percentage:
        return "TRENDING_UP"
    if current_percentage < previous_percentage:
        return "TRENDING_DOWN"
    return "STABLE"
