"""
Accept a REVIEWED change in a document's extraction counts as its new baseline.

The health gate FAILs a document whose counts fall more than
max_baseline_drop_ratio below the recorded baseline for the same document
hash, and analytics that depend on it are BLOCKED. When a person has
inspected the change and confirmed it is an improvement (e.g. spurious
records removed by a parser fix), this command records the run's counts as
the new baseline -- with the reason, the reviewer and the previous baseline
kept for audit. It refuses when any OTHER health check is not PASS, so it
cannot be used to wave through a genuinely unhealthy document.

Usage:
  python scripts/pipeline/accept_baseline_change.py --doc-id aicte-ug-cse-model \
      --reviewer "name" --reason "what was checked and why the change is correct" [--run-id <run>]
Then re-run the pipeline (BRONZE is cached, so this is fast).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc-id", required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--reviewer", required=True)
    ap.add_argument("--run-id")
    ap.add_argument("--gold-root", default=str(REPO / "data/gold/knowledge"))
    ap.add_argument("--baselines", default=str(REPO / "data/metadata/pipeline_baselines.json"))
    args = ap.parse_args(argv)

    gold = Path(args.gold_root)
    run_id = args.run_id or json.loads((gold / "latest_run.json").read_text())["run_id"]
    report = json.loads((gold / run_id / "run_report.json").read_text())
    health = json.loads((gold / run_id / "health.json").read_text())["documents"][args.doc_id]
    blocking = [c for c in health["checks"] if c["status"] != "PASS" and c["check"] != "baseline_regression"]
    if blocking:
        sys.exit(f"refused: {args.doc_id} has other non-PASS checks: {[c['check'] for c in blocking]}")
    summary = report["document_summaries"][args.doc_id] if isinstance(report["document_summaries"], dict) else \
        next(s for s in report["document_summaries"] if s["doc_id"] == args.doc_id)
    path = Path(args.baselines)
    baselines = json.loads(path.read_text()) if path.exists() else {"documents": {}}
    previous = baselines["documents"].get(summary["sha256"])
    baselines["documents"][summary["sha256"]] = {
        "doc_id": args.doc_id, **{k: summary[k] for k in ("valid_courses", "units", "clean_topics", "outcomes")},
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pipeline_version": report["pipeline_version"], "parser_fingerprint": report["parser_fingerprint"],
        "recorded_from_run": run_id,
        "accepted_change": {"reason": args.reason, "reviewer": args.reviewer, "previous_baseline": previous,
                            "baseline_regression_check": next(c for c in health["checks"] if c["check"] == "baseline_regression")},
    }
    path.write_text(json.dumps(baselines, indent=2, sort_keys=True), encoding="utf-8")
    print(f"baseline for {args.doc_id} updated from run {run_id}")


if __name__ == "__main__":
    main()
