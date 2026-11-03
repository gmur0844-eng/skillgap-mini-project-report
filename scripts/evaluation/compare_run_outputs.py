#!/usr/bin/env python3
"""Do two analysis runs hold the same results? For checking that a change to the code (a speed-up, a refactor)
changes nothing in the outputs.

    python3 scripts/evaluation/compare_run_outputs.py <run_a> <run_b> [--gold data/gold/knowledge]

Every GOLD file of the two runs is compared byte for byte, except observability.json and run_report.* (timings).
Two kinds of difference are expected whenever the code changes, and are neutralised before comparing:
  * the run id, and the ids hashed from it (scope, gap, recommendation, peer relation, trace, suppression, graph
    edge): masked;
  * the order of rows and list items sorted by those ids: compared in any order (only for files that still differ).
Anything else that differs is listed, and the exit code is 1.
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.knowledge_engine.silver import uid  # noqa: E402

SKIP = {"observability.json", "run_report.json", "run_report.md"}
RUN_DERIVED = re.compile(rb"\b(rec|kg|peerrel|gap|rec2|trace|norec):[0-9a-f]{16}\b")


def files(root):
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p.name not in SKIP}


def normalised(gold, run, f):
    data = (gold / run / f).read_bytes().replace(run.encode(), b"RUN")
    data = data.replace(uid("scope", run, "ALL_POSTINGS").encode(), b"SCOPE")
    return RUN_DERIVED.sub(rb"\1:ID", data)


def canon(o):
    if isinstance(o, dict):
        return {k: canon(v) for k, v in o.items()}
    if isinstance(o, list):
        return sorted((canon(v) for v in o), key=lambda v: json.dumps(v, sort_keys=True))
    return o


def compare(gold, a, b):
    fa, fb = files(gold / a), files(gold / b)
    different = []
    for f in sorted(fa & fb):
        x, y = normalised(gold, a, f), normalised(gold, b, f)
        if x == y:
            continue
        if f.endswith(".jsonl"):
            same = sorted(x.splitlines()) == sorted(y.splitlines())
        elif f.endswith(".json"):
            same = canon(json.loads(x)) == canon(json.loads(y))
        else:
            same = False
        if not same:
            different.append(f)
    return {"compared": len(fa & fb), "only_in_a": sorted(fa - fb), "only_in_b": sorted(fb - fa),
            "different": different}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_a")
    ap.add_argument("run_b")
    ap.add_argument("--gold", default=str(REPO / "data/gold/knowledge"))
    args = ap.parse_args()
    r = compare(Path(args.gold), args.run_a, args.run_b)
    same = not (r["only_in_a"] or r["only_in_b"] or r["different"])
    print(f"{r['compared']} files compared: " + ("all identical (run-derived ids masked, order of id-sorted rows "
                                                  "ignored)" if same else "DIFFERENT"))
    for k in ("only_in_a", "only_in_b", "different"):
        if r[k]:
            print(f"  {k}: {r[k]}")
    sys.exit(0 if same else 1)


if __name__ == "__main__":
    main()
