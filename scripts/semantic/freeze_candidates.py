"""
Freeze the semantic-adjudication candidates of one GOLD run so a model run can be compared with the
deterministic baseline on EXACTLY the same inputs.

Candidates are regenerated with the production function (intelligence.adjudication_candidates) from the
run's own GOLD/SILVER files; every candidate's input_hash and context_hash must equal the ones recorded in
that run's intelligence/semantic_decisions.jsonl, otherwise the freeze is refused.

Usage: python3 scripts/semantic/freeze_candidates.py --run-id 438ec2c0d5182dd4 --out data/semantic_runs/qwen-270-v1
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine import intelligence as intel  # noqa: E402
from app.knowledge_engine import semantic_provider as sp  # noqa: E402
from app.knowledge_engine.config import load_config  # noqa: E402
from app.services import knowledge_service as ks  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    run = ks.KnowledgeRun(a.run_id)
    ind, it = run.dir / "industry", run.dir / "intelligence"
    posting_mentions = ks._jsonl(ind / "skill_mentions.jsonl")
    mappings = {m["normalized_label"]: m for m in ks._jsonl(ind / "esco_mappings.jsonl")}
    postings = {p["posting_uid"]: p for p in ks._jsonl(ind / "postings.jsonl")}
    cfg = load_config()
    cands = intel.adjudication_candidates(posting_mentions, mappings, run.mappings, run.topics, postings,
                                          cfg["intelligence"]["adjudication_limit"])
    recorded = ks._jsonl(it / "semantic_decisions.jsonl")
    rec_keys = {(d["input_hash"], d["context_hash"]) for d in recorded}
    frozen, unmatched = [], []
    for c in cands:
        ih = sp.sha({k: c.get(k) for k in ("left", "right", "question")})
        ch = sp.sha({k: c.get(k) for k in ("left_context", "right_context", "rule_relationship", "rule_reason", "rule_evidence")})
        if (ih, ch) not in rec_keys:
            unmatched.append(c)
        cid = "cand:" + sp.sha([c["kind"], c.get("source_entity"), c.get("candidate_entity"), ih, ch])[:16]
        frozen.append({**c, "candidate_id": cid, "input_hash": ih, "context_hash": ch,
                       "baseline": {"rule_relationship": c.get("rule_relationship"),
                                    "baseline_decision_state": "RULE_VERDICT_NO_MODEL",
                                    "baseline_source": f"run {a.run_id} intelligence/semantic_decisions.jsonl"}})
    if unmatched or len(frozen) != len(recorded):
        sys.exit(f"REFUSED: {len(unmatched)} regenerated candidates do not match the recorded decisions "
                 f"(regenerated {len(frozen)}, recorded {len(recorded)})")
    ids = [f["candidate_id"] for f in frozen]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    body = json.dumps(frozen, indent=1, ensure_ascii=False, sort_keys=True)
    (out / "candidates.json").write_text(body, encoding="utf-8")
    manifest = {
        "source_run_id": a.run_id, "source_content_digest": run.report.get("content_digest"),
        "source_code_fingerprint": run.report.get("code_fingerprint"), "source_config_hash": run.report.get("config_hash"),
        "candidates": len(frozen), "distinct_candidate_ids": len(set(ids)),
        "by_kind": {k: sum(1 for f in frozen if f["kind"] == k) for k in sorted({f["kind"] for f in frozen})},
        "candidates_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "generator": "app.knowledge_engine.intelligence.adjudication_candidates (unchanged)",
        "verification": "every regenerated (input_hash, context_hash) equals a recorded decision of the source run",
        "prompt_version": sp.PROMPT_VERSION, "schema_version": sp.SCHEMA_VERSION,
    }
    (out / "freeze_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
