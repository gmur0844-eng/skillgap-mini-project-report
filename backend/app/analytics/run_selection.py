"""
GOLD re-run / versioning behavior (spec Section 9).

DESIGN DECISION (documented, not accidental): re-running an analysis function
(run_industry_demand_analysis, etc.) always creates a NEW AnalysisRun and a
fresh set of GOLD rows tagged with that run's id -- it does NOT check for or
skip/replace a prior run's rows. This is deliberate "versioned snapshot"
behavior, analogous to how a data warehouse keeps dated fact-table snapshots:
- Old runs' GOLD rows are retained for audit/history (e.g. "how did Python's
  demand percentage change between the March run and the June run?").
- This is safe to re-run repeatedly: nothing is corrupted or silently
  overwritten, and disk/DB growth is bounded by how often analysis is run,
  not by ingestion volume.
- The ambiguity risk this section warns against ("silently creating duplicate
  GOLD records") is avoided by NEVER reading GOLD tables directly -- every
  consumer (the API layer, this function) must go through
  select_latest_successful_run() to get one unambiguous, current answer.

This is a different idempotency model from ingestion/extraction (which use
content-hash-based skip-if-exists, because re-ingesting the same raw record
would be a genuine, unwanted duplicate of PRIMARY data). GOLD analytical
results are derived, not primary, so "latest wins" is the correct semantics.
"""


def select_latest_successful_run(runs: list[dict], dataset_name: str) -> dict | None:
    """
    runs: [{"id": int, "dataset_name": str, "status": str, "started_at": <comparable, e.g. ISO string or datetime>}, ...]
    Returns the run dict with the latest started_at among those matching
    dataset_name with status == "succeeded", or None if there isn't one.
    Pure and deterministic: the same input list always yields the same
    selection, independent of dict/list ordering.
    """
    candidates = [r for r in runs if r.get("dataset_name") == dataset_name and r.get("status") == "succeeded"]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["started_at"])
