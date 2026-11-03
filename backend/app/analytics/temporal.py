"""
Pure temporal bucketing utility (spec Section 3). No dependence on the
current date/time, no timezone conversion (operates on whatever naive
datetime is stored -- this project never mixes timezone-aware and naive
datetimes, so there is nothing to convert; if that ever changes, conversion
must happen before calling this, not inside it).
"""
from datetime import datetime, timedelta

GRANULARITIES = ("month", "quarter", "year")


def bucket_date(dt, granularity: str):
    """
    2026-01-15, "month"   -> "2026-01"
    2026-02-15, "quarter" -> "2026-Q1"
    2026-02-15, "year"    -> "2026"
    None (missing date) -> None. NEVER substitutes today's date or any other
    fallback -- a missing date must be reported as missing, not silently
    defaulted (spec Section 5).
    """
    if granularity not in GRANULARITIES:
        raise ValueError(f"Unknown granularity '{granularity}'. Must be one of {GRANULARITIES}.")
    if dt is None:
        return None

    if granularity == "month":
        return f"{dt.year:04d}-{dt.month:02d}"
    if granularity == "quarter":
        q = (dt.month - 1) // 3 + 1
        return f"{dt.year:04d}-Q{q}"
    return f"{dt.year:04d}"


def period_bounds(bucket_label: str, granularity: str) -> tuple:
    """
    Inverse of bucket_date: given a bucket label, returns (period_start,
    period_end) as exact datetimes, for storage on SkillDemand.period_start/
    period_end. period_end is the last microsecond of the period (inclusive).
    Raises ValueError for a malformed label rather than guessing.
    """
    if granularity not in GRANULARITIES:
        raise ValueError(f"Unknown granularity '{granularity}'. Must be one of {GRANULARITIES}.")

    if granularity == "month":
        year_str, month_str = bucket_label.split("-")
        year, month = int(year_str), int(month_str)
        start = datetime(year, month, 1)
        end = (datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)) - timedelta(microseconds=1)
        return start, end

    if granularity == "quarter":
        year_str, q_str = bucket_label.split("-Q")
        year, q = int(year_str), int(q_str)
        if q < 1 or q > 4:
            raise ValueError(f"Invalid quarter in bucket label '{bucket_label}'")
        start_month = (q - 1) * 3 + 1
        start = datetime(year, start_month, 1)
        end_month = start_month + 3
        if end_month > 12:
            end = datetime(year + 1, end_month - 12, 1) - timedelta(microseconds=1)
        else:
            end = datetime(year, end_month, 1) - timedelta(microseconds=1)
        return start, end

    year = int(bucket_label)
    start = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1) - timedelta(microseconds=1)
    return start, end
