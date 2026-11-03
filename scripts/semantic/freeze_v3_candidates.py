"""
Freeze Semantic Engine V3 candidates:
  * the SAME 270 pool candidates as qwen-270-v1 (same candidate_id), rebuilt with V3 context by the production
    builder intelligence.v3_from_pool from the pool's source run (GOLD) and SILVER texts;
  * the hard-case diagnostics of data/evaluation/semantic_v3_diagnostic_specs.json (real texts, real ESCO concepts).
Usage: python3 scripts/semantic/freeze_v3_candidates.py --pool data/semantic_runs/qwen-270-v1 --run-id 438ec2c0d5182dd4 --out data/semantic_runs/qwen-270-v3
"""
import argparse
import glob
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine import esco_full as ef  # noqa: E402
from app.knowledge_engine import intelligence as intel  # noqa: E402
from app.knowledge_engine import semantic_provider as sp  # noqa: E402
from app.knowledge_engine import semantic_v3 as v3  # noqa: E402
from app.services import knowledge_service as ks  # noqa: E402


def load_context(run_id):
    run = ks.KnowledgeRun(run_id)
    manifest = json.loads((ROOT / "data/metadata/curriculum_sources.json").read_text())
    full = next(t for t in manifest["taxonomy_sources"] if t["kind"] == "esco_full")
    store, _ = ef.build_store(*ef.read_classification(ROOT / full["path"]))
    postings = {}
    for f in sorted(glob.glob(str(ROOT / "data/silver/jobs/*/postings.jsonl"))):
        for p in ks._jsonl(Path(f)):
            postings[p["posting_uid"]] = p
    wanted = {p["posting_uid"] for p in ks._jsonl(run.dir / "industry/postings.jsonl")}
    postings = {k: v for k, v in postings.items() if k in wanted}
    outcomes = intel.outcomes_by_course([o for doc_id, sha in sorted({(c["doc_id"], c["source_sha256"]) for c in run.courses.values()})
                                         for o in ks._jsonl(ROOT / "data/silver/curricula" / doc_id / sha[:16] / "outcomes.jsonl")])
    ctx = intel.V3Context(store, postings, ks._jsonl(run.dir / "industry/skill_mentions.jsonl"),
                          ks._jsonl(run.dir / "industry/esco_mappings.jsonl"), run.mappings, run.topics, run.courses,
                          outcomes, ks._jsonl(run.dir / "industry/curriculum_skill_mentions.jsonl"))
    return run, ctx


def diagnostics(ctx, specs):
    by_label = {s["pref_label"]: u for u, s in ctx.store["skills"].items()}
    topics = sorted((t for t in ctx.topics.values() if t.get("noise_label") == "TOPIC"), key=lambda t: t["topic_uid"])
    out, skipped = [], []
    for d in specs["cases"]:
        rx = re.compile(d["source_regex"], re.IGNORECASE)
        uri = by_label.get(d["esco_pref_label"])
        if d["source"] == "topic":
            t = next((t for t in topics if rx.search(t["clean_text"])), None)
            if not t or not uri:
                skipped.append({**d, "reason": "source text or ESCO concept not found"})
                continue
            course = ctx.courses.get(t["course_uid"], {})
            left = v3._ids([{"source_type": "SOURCE_TEXT", "text": t["clean_text"]},
                            {"source_type": "COURSE_TITLE", "text": course.get("title")},
                            {"source_type": "UNIT_TITLE", "text": t.get("unit_label")}]
                           + [{"source_type": "SOURCE_TEXT", "text": s} for s in ctx.siblings(t)[:4]]
                           + [{"source_type": "LEARNING_OUTCOME", "text": o["text"]} for o in ctx.outcomes.get(t["course_uid"], [])[:2]], "L")
            left_text, src = t["clean_text"], {"topic_uid": t["topic_uid"], "course_code": course.get("course_code"), "page": t.get("page_number")}
        else:
            p = next((p for _, p in sorted(ctx.postings.items()) if rx.search(p.get("clean_description") or "")), None)
            if not p or not uri:
                skipped.append({**d, "reason": "source text or ESCO concept not found"})
                continue
            m = rx.search(p["clean_description"])
            cur, prev, nxt = v3.sentence_at(p["clean_description"], m.start(), m.end())
            left = v3._ids([{"source_type": "SOURCE_TEXT", "text": cur}, {"source_type": "SOURCE_TEXT", "text": prev},
                            {"source_type": "SOURCE_TEXT", "text": nxt}, {"source_type": "JOB_TITLE", "text": p.get("job_title")}], "L")
            left_text, src = m.group(0), {"posting_uid": p["posting_uid"], "span": [m.start(), m.end()]}
        right, concept = v3.esco_concept_items(ctx.store, uri)
        c = {"kind": "DIAGNOSTIC", "left": left_text, "left_items": left, "right": concept["label"], "right_concept": concept,
             "right_items": right, "metadata_items": v3._ids([{"source_type": "NORMALIZATION_METADATA",
                                                               "text": "evaluation pair from the hard-case specification"}], "M"),
             "question": "Does the LEFT expression, in THIS source context, mean, represent, teach or require the RIGHT concept?",
             "diag_id": d["diag_id"], "hard_case": d["hard_case"], "source_ref": src, "candidate_entity": uri}
        out.append(c)
    return out, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    pool = json.loads((Path(a.pool) / "candidates.json").read_text())
    run, ctx = load_context(a.run_id)
    frozen, missing = [], []
    for c in pool:
        c3 = intel.v3_from_pool(c, ctx)
        if c3 is None:
            missing.append(c["candidate_id"])
            continue
        c3.update(candidate_id=c["candidate_id"], source_entity=c.get("source_entity"),
                  candidate_entity=c.get("candidate_entity"), v2_input_hash=c["input_hash"], v2_context_hash=c["context_hash"],
                  baseline=c["baseline"])
        frozen.append(c3)
    specs = json.loads((ROOT / "data/evaluation/semantic_v3_diagnostic_specs.json").read_text())
    diags, skipped = diagnostics(ctx, specs)
    for c in diags:
        c["candidate_id"] = "diag:" + c["diag_id"]
        c["baseline"] = {"rule_relationship": None, "baseline_decision_state": "NO_BASELINE (evaluation pair)"}
    allc = frozen + diags
    for c in allc:
        c["input_hash"], c["context_hash"] = v3.candidate_hashes(c, sp.sha)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    body = json.dumps(allc, indent=1, ensure_ascii=False, sort_keys=True)
    (out / "candidates.json").write_text(body, encoding="utf-8")
    manifest = {"pool": str(a.pool), "pool_candidates": len(pool), "pool_rebuilt": len(frozen), "pool_missing": missing,
                "diagnostics": len(diags), "diagnostics_skipped": skipped, "diagnostics_not_available": specs["not_available"],
                "source_run_id": a.run_id, "total": len(allc), "distinct_ids": len({c["candidate_id"] for c in allc}),
                "candidates_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "prompt_version": v3.PROMPT_VERSION, "schema_version": v3.SCHEMA_VERSION,
                "builder": "app.knowledge_engine.intelligence.v3_from_pool + semantic_v3 (production code)",
                "metadata_never_evidence": "taxonomy/normalization facts are shown only as M-items; the validator rejects them as evidence"}
    (out / "freeze_manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in manifest.items() if k != "pool_missing"}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
