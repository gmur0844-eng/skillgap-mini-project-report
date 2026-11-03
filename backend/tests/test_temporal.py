import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.temporal import bucket_date, period_bounds


def test_month_bucketing():
    assert bucket_date(datetime(2026, 1, 15), "month") == "2026-01"
    assert bucket_date(datetime(2026, 12, 1), "month") == "2026-12"


def test_quarter_bucketing():
    assert bucket_date(datetime(2026, 2, 15), "quarter") == "2026-Q1"
    assert bucket_date(datetime(2026, 4, 1), "quarter") == "2026-Q2"
    assert bucket_date(datetime(2026, 7, 1), "quarter") == "2026-Q3"
    assert bucket_date(datetime(2026, 10, 1), "quarter") == "2026-Q4"


def test_year_bucketing():
    assert bucket_date(datetime(2026, 2, 15), "year") == "2026"


def test_quarter_boundary_dates():
    assert bucket_date(datetime(2026, 3, 31), "quarter") == "2026-Q1"
    assert bucket_date(datetime(2026, 4, 1), "quarter") == "2026-Q2"
    assert bucket_date(datetime(2026, 12, 31), "quarter") == "2026-Q4"


def test_missing_date_returns_none_never_today():
    assert bucket_date(None, "month") is None
    assert bucket_date(None, "quarter") is None
    assert bucket_date(None, "year") is None


def test_invalid_granularity_raises():
    try:
        bucket_date(datetime(2026, 1, 1), "week")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_deterministic_repeated_calls():
    dt = datetime(2026, 6, 15)
    assert bucket_date(dt, "month") == bucket_date(dt, "month")
    assert bucket_date(dt, "quarter") == bucket_date(dt, "quarter")


def test_period_bounds_month():
    start, end = period_bounds("2026-01", "month")
    assert start == datetime(2026, 1, 1)
    assert end.day == 31 and end.month == 1
    start, end = period_bounds("2026-12", "month")
    assert end.year == 2026 and end.month == 12 and end.day == 31


def test_period_bounds_quarter_year_rollover():
    start, end = period_bounds("2026-Q4", "quarter")
    assert start == datetime(2026, 10, 1)
    assert end.year == 2026 and end.month == 12 and end.day == 31


def test_period_bounds_year():
    start, end = period_bounds("2026", "year")
    assert start == datetime(2026, 1, 1)
    assert end.year == 2026 and end.month == 12 and end.day == 31


def test_bucket_date_and_period_bounds_are_consistent():
    dt = datetime(2026, 5, 17, 14, 30)
    bucket = bucket_date(dt, "month")
    start, end = period_bounds(bucket, "month")
    assert start <= dt <= end
