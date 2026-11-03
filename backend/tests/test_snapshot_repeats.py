"""Open-posting snapshots collected on several dates: a posting still open on a later date is one posting (not a
duplicate in the data), counted in every snapshot it was open on; trends compare only the boards collected on every
date. Synthetic fixtures; no real company or posting."""
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import industry_intel as ii
from app.knowledge_engine.config import load_config
from app.knowledge_engine.health import FAIL, PASS, industry_health
from app.knowledge_engine.jobs import ingest_postings

DESC = "Build data pipelines with SQL and Python for reporting teams across several regions of the company."
POP = "BOARDS_TEST"


def _source(tmp, name, rows, collected_on, board="https://boards.example.com/one"):
    path = tmp / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["job_title", "url", "posted_date", "job_description", "company_name"])
        w.writeheader()
        w.writerows(rows)
    return {"source_id": name, "path": str(path), "abs_path": str(path), "sha256": (name * 64)[:64].ljust(64, "0"),
            "population_id": POP, "provenance": {"collected_on": collected_on, "date_semantics": "OPEN_POSTINGS_SNAPSHOT",
                                                 "population_id": POP, "source_url": board}}


def _row(n, title="Data Engineer"):
    return {"job_title": f"{title} {n}", "url": f"https://boards.example.com/one/jobs/{n}", "posted_date": "2026-09-20",
            "job_description": f"{DESC} Team {n} variant {n * 7}.", "company_name": "Example Co"}


def _ingest(sources):
    tmp = Path(tempfile.mkdtemp())
    return ingest_postings(sources, tmp / "bronze", tmp / "silver", 0.99)


def test_a_posting_still_open_later_is_a_snapshot_repeat_not_a_data_duplicate():
    tmp = Path(tempfile.mkdtemp())
    first = _source(tmp, "a_2026-10-01", [_row(1), _row(2)], "2026-10-01")
    later = _source(tmp, "a_2026-10-21", [_row(1), _row(3), _row(3)], "2026-10-21")  # 1 still open; 3 listed twice
    result = _ingest([later, first])
    kinds = sorted(r.get("duplicate_kind") for r in result["records"] if r["status"] == "DUPLICATE")
    assert kinds == ["SAME_IDENTITY", "SNAPSHOT_REPEAT"]
    assert len(result["postings"]) == 3  # 1, 2, 3: each posting kept once
    kept = {p["identity"].rsplit("/", 1)[-1]: p for p in result["postings"]}
    assert kept["1"]["open_on_snapshots"] == ["2026-10-01", "2026-10-21"]
    assert "open_on_snapshots" not in kept["2"] and "open_on_snapshots" not in kept["3"]
    s = result["summary"]
    assert (s["records_read"], s["status_counts"]["DUPLICATE"], s["snapshot_repeats"]) == (5, 2, 1)
    assert s["duplicate_rate"] == 0.4  # unchanged meaning: all duplicates / all records
    assert s["duplicate_rate_excluding_snapshot_repeats"] == 0.25  # 1 real duplicate / 4 distinct records


def test_datasets_without_snapshot_dates_are_unchanged():
    tmp = Path(tempfile.mkdtemp())
    src = _source(tmp, "plain", [_row(1), _row(1)], None)
    src["provenance"] = {}
    result = _ingest([src])
    dup = [r for r in result["records"] if r["status"] == "DUPLICATE"]
    assert [r["duplicate_kind"] for r in dup] == ["SAME_IDENTITY"]
    assert dup[0]["reason"].startswith("same posting identity as ")
    assert result["summary"]["snapshot_repeats"] == 0


def _summary(**over):
    base = {"files_expected": 4, "files_verified": 4, "records_read": 1000, "duplicates": 0, "missing_description": 0,
            "eligible_postings": 700, "postings_with_skill": 500, "unique_normalized_skills": 130,
            "unique_skills_eligible": 100, "esco_mapped_skills": 90, "ambiguous_skills": 1,
            "postings_with_provenance": 700, "esco_skill_concepts": 9000, "mentions": 1800}
    base.update(over)
    return base


def _dup_check(summary):
    cfg = load_config()
    return next(c for c in industry_health(summary, cfg)["checks"] if c["check"] == "duplicate_rate")


def test_health_check_leaves_snapshot_repeats_out_of_the_duplicate_rate():
    # 300 duplicates of 1,000 records fails (30 % > 20 %) ...
    assert _dup_check(_summary(duplicates=300))["status"] == FAIL
    # ... but when 260 of them are the same postings still open in a later snapshot: 40 / 740 = 5.4 %
    check = _dup_check(_summary(duplicates=300, snapshot_repeats=260))
    assert check["status"] == PASS and check["value"] == round(40 / 740, 4)
    assert "260 postings still open in a later snapshot" in check["detail"]
    # real duplicates still fail with repeats present
    assert _dup_check(_summary(duplicates=500, snapshot_repeats=100))["status"] == FAIL


SETTINGS = {"min_periods_for_trend": 2, "min_eligible_postings_per_period": 3, "min_skill_postings_for_trend": 2}
TCFG = {"min_pp_change": 5.0, "min_relative_change": 0.25, "persistent_min_pct": 10.0, "require_monotonic": True}


def _posting(uid, source_id, dates):
    p = {"posting_uid": uid, "source_id": source_id, "source_file": f"{source_id}.csv", "country_code": "IN",
         "temporal_date": dates[0], "date_semantics": "OPEN_POSTINGS_SNAPSHOT"}
    if len(dates) > 1:
        p["open_on_snapshots"] = dates
    return p


def _src(source_id, when, board):
    return {"source_id": source_id, "population_id": POP,
            "provenance": {"collected_on": when, "date_semantics": "OPEN_POSTINGS_SNAPSHOT", "source_url": board}}


def test_a_posting_open_on_two_snapshots_counts_in_both_periods():
    sources = {"x1": _src("x1", "2026-10-01", "b1"), "x2": _src("x2", "2026-10-21", "b1")}
    ps = [_posting(f"o{i}", "x1", ["2026-10-01", "2026-10-21"]) for i in range(3)]  # open on both dates
    ps += [_posting(f"n{i}", "x2", ["2026-10-21"]) for i in range(3)]               # new on the later date
    pairs = [("a", "o0"), ("a", "o1"), ("a", "n0")]
    scope, rows = ii.population_trends(POP, ps, pairs, {"a": {"label": "A"}}, sources, SETTINGS, TCFG)
    assert scope["trend_status"] == "COMPUTED" and "board_panel" not in scope
    by = scope["granularity_evaluation"]["week"]["postings_by_period"]
    assert list(by.values()) == [3, 6]  # the three still-open postings are members of the later snapshot too
    periods = rows[0]["periods"]
    assert [(p["posting_count"], p["eligible_postings"]) for p in periods] == [(2, 3), (3, 6)]
    assert scope["date_range"] == {"earliest": "2026-10-01", "latest": "2026-10-21"}


def test_boards_collected_on_only_some_dates_are_left_out_of_trends():
    sources = {"x1": _src("x1", "2026-10-01", "b1"), "x2": _src("x2", "2026-10-21", "b1"),
               "y2": _src("y2", "2026-10-21", "b2")}  # board b2 was first collected on the later date
    ps = [_posting(f"o{i}", "x1", ["2026-10-01"]) for i in range(3)]
    ps += [_posting(f"n{i}", "x2", ["2026-10-21"]) for i in range(3)]
    ps += [_posting(f"m{i}", "y2", ["2026-10-21"]) for i in range(5)]
    scope, _ = ii.population_trends(POP, ps, [], {}, sources, SETTINGS, TCFG)
    panel = scope["board_panel"]
    assert panel["boards_left_out"] == ["b2"] and panel["postings_left_out"] == 5 and panel["trend_postings"] == 6
    assert scope["eligible_postings"] == 11  # the population itself is unchanged
    assert list(scope["granularity_evaluation"]["week"]["postings_by_period"].values()) == [3, 3]


def test_no_panel_without_snapshot_provenance():
    ps = [_posting(f"o{i}", "s", ["2026-09-01"]) for i in range(3)]
    assert ii.board_panel(POP, ps, {}) is None
    assert ii.board_panel(POP, ps, {"s": {"source_id": "s", "population_id": POP}}) is None
