import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.run_selection import select_latest_successful_run


def _run(id_, dataset_name, status, started_at):
    return {"id": id_, "dataset_name": dataset_name, "status": status, "started_at": started_at}


def test_run1_then_run2_identical_dataset_picks_the_newer():
    t0 = datetime(2026, 1, 1)
    t1 = datetime(2026, 6, 1)
    runs = [
        _run(1, "industry_demand", "succeeded", t0),
        _run(2, "industry_demand", "succeeded", t1),
    ]
    selected = select_latest_successful_run(runs, "industry_demand")
    assert selected["id"] == 2


def test_failed_rerun_does_not_shadow_prior_success():
    t0 = datetime(2026, 1, 1)
    t1 = datetime(2026, 6, 1)
    runs = [
        _run(1, "industry_demand", "succeeded", t0),
        _run(2, "industry_demand", "failed", t1),
    ]
    selected = select_latest_successful_run(runs, "industry_demand")
    assert selected["id"] == 1


def test_no_runs_returns_none():
    assert select_latest_successful_run([], "industry_demand") is None


def test_only_other_dataset_runs_returns_none():
    runs = [_run(1, "curriculum_coverage", "succeeded", datetime(2026, 1, 1))]
    assert select_latest_successful_run(runs, "industry_demand") is None


def test_deterministic_regardless_of_list_order():
    t0 = datetime(2026, 1, 1)
    t1 = datetime(2026, 6, 1)
    forward = [_run(1, "x", "succeeded", t0), _run(2, "x", "succeeded", t1)]
    backward = list(reversed(forward))
    assert select_latest_successful_run(forward, "x")["id"] == select_latest_successful_run(backward, "x")["id"] == 2


def test_three_runs_only_latest_succeeded_wins():
    runs = [
        _run(1, "x", "succeeded", datetime(2026, 1, 1)),
        _run(2, "x", "succeeded", datetime(2026, 3, 1)),
        _run(3, "x", "running", datetime(2026, 6, 1)),
    ]
    selected = select_latest_successful_run(runs, "x")
    assert selected["id"] == 2


def test_temporal_snapshot_three_runs_failed_third_does_not_shadow():
    """
    Spec's exact SNAPSHOT scenario for temporal datasets: successful run 1,
    successful run 2, failed run 3 -> current result must remain run 2.
    """
    runs = [
        _run(101, "industry_skill_trends", "succeeded", datetime(2026, 1, 1)),
        _run(102, "industry_skill_trends", "succeeded", datetime(2026, 2, 1)),
        _run(103, "industry_skill_trends", "failed", datetime(2026, 3, 1)),
    ]
    selected = select_latest_successful_run(runs, "industry_skill_trends")
    assert selected["id"] == 102


def _scope_filter(runs, population_scope):
    """
    Mirrors exactly the filter-then-select pattern now used by
    app.api.v1.analytics._latest_run and
    app.analytics.run_gap_classification._find_latest_run_id (Phase 4/5
    scope-safety hardening): population_scope is applied BEFORE latest-run
    selection, never after. Tested here as a pure function since neither of
    those two call sites can be exercised without a live database in this
    environment.
    """
    if population_scope is None:
        return runs
    return [r for r in runs if r.get("population_scope") == population_scope]


def test_global_and_scoped_runs_coexist_scoped_selection_picks_correct_one():
    """
    Regression test for the exact bug fixed this phase: a global
    industry_demand run and a discipline-scoped one for the SAME
    dataset_name must never be conflated by "latest wins" alone.
    """
    runs = [
        _run(1, "industry_demand", "succeeded", datetime(2026, 1, 1)),
        {**_run(2, "industry_demand", "succeeded", datetime(2026, 6, 1)), "population_scope": "discipline:7"},
    ]
    runs[0]["population_scope"] = "global"

    global_pick = select_latest_successful_run(_scope_filter(runs, "global"), "industry_demand")
    scoped_pick = select_latest_successful_run(_scope_filter(runs, "discipline:7"), "industry_demand")

    assert global_pick["id"] == 1
    assert scoped_pick["id"] == 2
    # Without scope filtering, "latest wins" would have wrongly picked run 2
    # (started later) for a caller that actually wanted the global population.
    naive_latest = select_latest_successful_run(runs, "industry_demand")
    assert naive_latest["id"] == 2  # demonstrates why the filter step is required, not optional


def test_programme_scoped_runs_never_mixed_across_programmes():
    runs = [
        {**_run(1, "curriculum_drift", "succeeded", datetime(2026, 1, 1)), "population_scope": "programme:1"},
        {**_run(2, "curriculum_drift", "succeeded", datetime(2026, 2, 1)), "population_scope": "programme:2"},
    ]
    prog1 = select_latest_successful_run(_scope_filter(runs, "programme:1"), "curriculum_drift")
    prog2 = select_latest_successful_run(_scope_filter(runs, "programme:2"), "curriculum_drift")
    assert prog1["id"] == 1
    assert prog2["id"] == 2


def test_discipline_scoped_runs_never_mixed_across_disciplines():
    """ECE must never silently consume a CSE-only population, and vice versa."""
    runs = [
        {**_run(1, "industry_demand", "succeeded", datetime(2026, 1, 1)), "population_scope": "discipline:ece"},
        {**_run(2, "industry_demand", "succeeded", datetime(2026, 1, 2)), "population_scope": "discipline:cse"},
    ]
    ece = select_latest_successful_run(_scope_filter(runs, "discipline:ece"), "industry_demand")
    cse = select_latest_successful_run(_scope_filter(runs, "discipline:cse"), "industry_demand")
    assert ece["id"] == 1
    assert cse["id"] == 2


def test_no_scope_requested_when_only_scoped_runs_exist_returns_none():
    """A caller that requires 'global' evidence must get nothing (-> INSUFFICIENT_EVIDENCE
    upstream) rather than silently receiving a programme-scoped substitute."""
    runs = [{**_run(1, "skill_gap_classification", "succeeded", datetime(2026, 1, 1)), "population_scope": "programme:9"}]
    result = select_latest_successful_run(_scope_filter(runs, "global"), "skill_gap_classification")
    assert result is None


def test_mechanical_never_consumes_unrestricted_global_population_silently():
    """Phase 5's explicit example: a caller requesting a Mechanical-scoped
    result must not silently receive a global (unrestricted) run's data."""
    runs = [{**_run(1, "curriculum_coverage", "succeeded", datetime(2026, 1, 1)), "population_scope": "global"}]
    mechanical_result = select_latest_successful_run(_scope_filter(runs, "programme:mechanical"), "curriculum_coverage")
    assert mechanical_result is None  # correctly nothing -- not the global run
