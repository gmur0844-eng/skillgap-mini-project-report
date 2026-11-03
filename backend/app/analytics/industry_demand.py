"""
Industry demand: OBSERVED DATA from real job postings' ExtractedSkill
evidence, never from ESCO itself (ESCO is the normalization taxonomy, not a
demand source -- see docs/analytics_methodology.md).

demand_percentage = postings_with_skill / eligible_job_postings * 100

Per spec: a skill mentioned 8 times in one posting counts that posting ONCE.
This module is pure (no DB) so the dedup and percentage math is independently
verifiable without a live database.
"""


def compute_skill_demand(
    mentions: list[dict],
    eligible_posting_ids: set,
) -> dict:
    """
    mentions: [{"job_posting_id": int, "normalized_skill_id": int}, ...] --
        pass only MAPPED mentions (normalized_skill_id is not None); unmapped
        mentions have no canonical skill to attribute demand to.
    eligible_posting_ids: the exact denominator population (e.g. all
        non-duplicate job postings considered for this analysis run). Callers
        must define and pass this explicitly -- this function never invents
        a population.

    Returns {skill_id: {"posting_count": int, "total_relevant_postings": int,
                         "demand_percentage": float}}
    """
    total = len(eligible_posting_ids)

    # distinct (job_posting_id, skill_id) pairs -- this is what makes 8
    # mentions of Python in one posting count as 1, not 8.
    distinct_pairs = {
        (m["job_posting_id"], m["normalized_skill_id"])
        for m in mentions
        if m.get("normalized_skill_id") is not None and m.get("job_posting_id") in eligible_posting_ids
    }

    posting_counts: dict = {}
    for _posting_id, skill_id in distinct_pairs:
        posting_counts[skill_id] = posting_counts.get(skill_id, 0) + 1

    result = {}
    for skill_id, count in posting_counts.items():
        result[skill_id] = {
            "posting_count": count,
            "total_relevant_postings": total,
            "demand_percentage": round(count / total * 100, 2) if total else None,
        }
    return result
