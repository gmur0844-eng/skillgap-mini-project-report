#!/usr/bin/env python3
"""
Automatic recomputation after new evidence.

  python3 scripts/acquisition/recompute.py [--parent <run_id>] [--publish --dsn ...] [--dry-run]

Compares the sources registered NOW (data/metadata/curriculum_sources.json) with the sources the parent run used
(default: the latest run), plans the affected analytics, reruns the pipeline when anything changed (a new run id;
the parent run directory is never modified), then records the lineage -- parent run, source changes, planned
recomputation, changed outputs -- in data/gold/knowledge/lineage/<new_run>.json.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.knowledge_engine import pipeline, recompute  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--dsn")
    ap.add_argument("--new-run", help="record lineage for a run that was already produced from the current sources "
                                      "and code (its fingerprint must match) instead of running the pipeline again")
    a = ap.parse_args()
    gold = ROOT / "data/gold/knowledge"
    parent = a.parent or json.loads((gold / "latest_run.json").read_text())["run_id"]
    parent_inv, parent_fp, parent_cfg = recompute.inventory_from_run(gold / parent)
    manifest = json.loads((ROOT / "data/metadata/curriculum_sources.json").read_text())
    now_inv = recompute.source_inventory(manifest)
    changes = recompute.source_changes(parent_inv, now_inv)
    code_fp = pipeline.code_fingerprint()
    planned = recompute.plan(changes, code_fp != parent_fp)
    print(json.dumps({"parent": parent, "source_changes": {k: len(v) for k, v in changes.items()},
                      "code_changed": code_fp != parent_fp, "plan": planned}, indent=1))
    if a.dry_run or not planned["recompute"]:
        print("nothing to recompute" if not planned["recompute"] else "dry run: not recomputing")
        return
    if a.new_run:
        new_inv, new_fp, _ = recompute.inventory_from_run(gold / a.new_run)
        if new_fp != code_fp or recompute.source_changes(new_inv, now_inv) != {"added": [], "removed": [], "changed": []}:
            sys.exit(f"run {a.new_run} was not produced from the current code and sources; rerun without --new-run")
        new, new_code_fp = a.new_run, new_fp
    else:
        report = pipeline.run(publish=a.publish, dsn=a.dsn)
        new, new_code_fp = report["run_id"], report["code_fingerprint"]
    diff = recompute.diff_runs(gold / parent, gold / new)
    rec = recompute.lineage_record(parent, new, changes, planned, diff, parent_fp, new_code_fp)
    path = recompute.write_lineage(ROOT, rec)
    print(json.dumps({"new_run": new, "changed_outputs": diff["counts"], "lineage": str(path)}, indent=1))


if __name__ == "__main__":
    main()
