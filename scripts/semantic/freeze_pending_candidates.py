"""
Freeze the replay-miss candidates of a GOLD run as a NEW semantic run (never touching earlier runs):

  python3 scripts/semantic/freeze_pending_candidates.py --run <run_id> --name qwen-v3-replay-misses-1

Reads <gold>/<run>/intelligence/semantic_pending_candidates.jsonl (the exact V3 candidates the pipeline could not
replay), re-verifies each candidate's input/context hash with the production V3 protocol, and writes
data/semantic_runs/<name>/candidates.json + freeze_manifest.json for scripts/semantic/run_frozen_adjudication.py.
Refuses if the target directory already exists.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine import semantic_provider as sp  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--name", required=True)
    a = ap.parse_args()
    src = ROOT / "data/gold/knowledge" / a.run / "intelligence/semantic_pending_candidates.jsonl"
    rows = [json.loads(x) for x in src.read_text().splitlines() if x.strip()]
    protocol = sp.v3_protocol()
    for c in rows:
        body = {k: v for k, v in c.items() if k not in ("input_hash", "context_hash")}
        if protocol.hashes(body) != (c["input_hash"], c["context_hash"]):
            sys.exit(f"REFUSED: {c['candidate_id']} hash mismatch")
    out = ROOT / "data/semantic_runs" / a.name
    if out.exists():
        sys.exit(f"REFUSED: {out} exists (experiments are never overwritten)")
    out.mkdir(parents=True)
    body = json.dumps(sorted(rows, key=lambda c: c["candidate_id"]), indent=1, ensure_ascii=False)
    (out / "candidates.json").write_text(body, encoding="utf-8")
    manifest = {"source_run_id": a.run, "source_file": str(src.relative_to(ROOT)), "total": len(rows),
                "distinct_ids": len({c["candidate_id"] for c in rows}),
                "by_kind": {k: sum(1 for c in rows if c["kind"] == k) for k in sorted({c["kind"] for c in rows})},
                "candidates_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "prompt_version": protocol.prompt_version, "schema_version": protocol.schema_version,
                "reason": "replay misses: these inputs changed after qwen-270-v3 was frozen (silver attribution fix), so "
                          "no recorded decision exists; decided fresh by the same model and protocol"}
    (out / "freeze_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
