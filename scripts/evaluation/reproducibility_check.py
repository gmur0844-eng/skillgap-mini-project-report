"""
Reproducibility evidence for a GOLD run. A rerun with identical inputs keeps the same run_id and rewrites the
run directory in place, so the first run is snapshotted before the rerun:

  python3 scripts/evaluation/reproducibility_check.py snapshot --out artifacts/repro/run1.json
  (rerun the pipeline)
  python3 scripts/evaluation/reproducibility_check.py snapshot --out artifacts/repro/run2.json
  python3 scripts/evaluation/reproducibility_check.py compare artifacts/repro/run1.json artifacts/repro/run2.json

A snapshot = run_id, content_digest, per-file sha256 of every analytical file (timing/memory reports are excluded,
exactly as content_digest excludes them), and the semantic adjudication counters (cache hits prove replay reuse).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine.exports import content_digest, file_sha256  # noqa: E402

GOLD = ROOT / "data/gold/knowledge"
EXCLUDE = ("run_report.json", "run_report.md", "observability.json", "publish_report.json")


def snapshot(out):
    latest = json.loads((GOLD / "latest_run.json").read_text())
    d = GOLD / latest["run_id"]
    files = {str(p.relative_to(d)): file_sha256(p) for p in sorted(d.rglob("*")) if p.is_file() and p.name not in EXCLUDE}
    intel = json.loads((d / "intelligence/intelligence_report.json").read_text()) if (d / "intelligence/intelligence_report.json").exists() else {}
    adj = intel.get("semantic_adjudication") or {}
    snap = {"run_id": latest["run_id"], "content_digest": content_digest(d), "recorded_digest": latest.get("content_digest"),
            "files": files, "semantic": {k: adj.get(k) for k in ("mode", "status", "candidates", "stats", "replay")}}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(snap, indent=1))
    print(f"run={snap['run_id']} digest={snap['content_digest'][:16]} files={len(files)} semantic={snap['semantic'].get('stats')}")


def compare(a, b):
    A, B = json.loads(Path(a).read_text()), json.loads(Path(b).read_text())
    changed = sorted(k for k in set(A["files"]) | set(B["files"]) if A["files"].get(k) != B["files"].get(k))
    res = {"same_run_id": A["run_id"] == B["run_id"], "same_content_digest": A["content_digest"] == B["content_digest"],
           "files_compared": len(set(A["files"]) | set(B["files"])), "files_differing": changed,
           "semantic_first": A["semantic"], "semantic_second": B["semantic"]}
    print(json.dumps(res, indent=1))
    sys.exit(0 if res["same_run_id"] and res["same_content_digest"] and not changed else 1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--out", required=True)
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    args = ap.parse_args()
    snapshot(args.out) if args.cmd == "snapshot" else compare(args.a, args.b)
