"""
Historical (per-period) industry demand (spec Section 4/5). Reuses
compute_skill_demand from industry_demand.py per bucket rather than
duplicating the dedup/percentage logic.
"""
from app.analytics.temporal import bucket_date
from app.analytics.industry_demand import compute_skill_demand


def compute_historical_skill_demand(
    postings: list,
    mentions: list,
    granularity: str,
) -> dict:
    """
    postings: [{"job_posting_id": int, "posted_date": datetime|None}, ...] --
        the full eligible population (before any date filtering).
    mentions: [{"job_posting_id": int, "normalized_skill_id": int}, ...] --
        MAPPED mentions only, same contract as compute_skill_demand.
    granularity: "month" | "quarter" | "year"

    Returns:
        {
          "periods": {bucket_label: {skill_id: {posting_count, total_relevant_postings, demand_percentage}}},
          "dated_posting_ids": set,      # postings with a usable posted_date
          "undated_posting_ids": set,    # postings with posted_date=None -- excluded from every period, but counted, never silently dropped
        }
    """
    dated_posting_ids = set()
    undated_posting_ids = set()
    posting_id_to_bucket = {}

    for p in postings:
        bucket = bucket_date(p.get("posted_date"), granularity)
        if bucket is None:
            undated_posting_ids.add(p["job_posting_id"])
        else:
            dated_posting_ids.add(p["job_posting_id"])
            posting_id_to_bucket[p["job_posting_id"]] = bucket

    eligible_ids_by_period = {}
    for posting_id, bucket in posting_id_to_bucket.items():
        eligible_ids_by_period.setdefault(bucket, set()).add(posting_id)

    mentions_by_period = {}
    for m in mentions:
        bucket = posting_id_to_bucket.get(m["job_posting_id"])
        if bucket is not None:
            mentions_by_period.setdefault(bucket, []).append(m)

    periods = {}
    for bucket, eligible_ids in eligible_ids_by_period.items():
        periods[bucket] = compute_skill_demand(mentions_by_period.get(bucket, []), eligible_ids)

    return {
        "periods": periods,
        "dated_posting_ids": dated_posting_ids,
        "undated_posting_ids": undated_posting_ids,
    }
