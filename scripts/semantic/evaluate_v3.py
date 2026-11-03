"""
Evaluate BASELINE / V2 / V3 on the frozen development benchmark and compute the pre-declared promotion gate.
Written before V3 outputs existed; nothing here is tuned on them.

Usage: python3 scripts/semantic/evaluate_v3.py --v3 data/semantic_runs/qwen-270-v3 --v2 data/semantic_runs/qwen-270-v1

The benchmark is a DEVELOPMENT GOLD SET labelled by the assistant (not independent humans): every metric is a
development estimate and is reported as such.

Systems compared (8 relationship classes):
  BASELINE      deterministic rules: AMBIGUOUS for every candidate (they exist because the rules could not decide)
  V2_RAW        qwen-270-v1 model relationship (pool cases only; V2 never saw the diagnostic contexts)
  V3_RAW        V3 model relationship before validation
  V3_VALIDATED  what downstream may read: relationship if MODEL_SUPPORTED; MODEL_SUGGESTED keeps AMBIGUOUS /
                INSUFFICIENT_EVIDENCE; validator downgrade -> INSUFFICIENT_EVIDENCE; REVIEW_REQUIRED/MODEL_FAILURE -> AMBIGUOUS
"""
import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine import semantic_v3 as v3  # noqa: E402
from app.knowledge_engine.semantic_provider import RELATIONSHIPS  # noqa: E402

CLASSES = list(RELATIONSHIPS)


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()] if Path(p).exists() else []


def effective(d, cand):
    if d is None:
        return None
    if d["decision_state"] != "MODEL_SUGGESTED":
        return "AMBIGUOUS"
    state, _ = v3.validate_decision({k: d.get(k) for k in ("relationship", "reason", "evidence", "direction_justification",
                                                           "alternatives", "uncertainty")}, cand)
    if state == "MODEL_SUPPORTED":
        return d["relationship"]
    if state == "MODEL_SUGGESTED":
        return d["relationship"]
    return "INSUFFICIENT_EVIDENCE" if state == "INSUFFICIENT_EVIDENCE" else "AMBIGUOUS"


def metrics(pairs):
    """pairs: [(gold, pred)] with pred possibly None (excluded)."""
    pairs = [(g, p) for g, p in pairs if p is not None]
    n = len(pairs)
    conf = {g: {p: 0 for p in CLASSES} for g in CLASSES}
    for g, p in pairs:
        conf[g][p] += 1
    per = {}
    for c in CLASSES:
        tp = conf[c][c]
        pred = sum(conf[g][c] for g in CLASSES)
        gold = sum(conf[c].values())
        prec = tp / pred if pred else None
        rec = tp / gold if gold else None
        f1 = (2 * prec * rec / (prec + rec)) if prec and rec else (0.0 if (pred and gold) else None)
        per[c] = {"support_gold": gold, "predicted": pred, "precision": r(prec), "recall": r(rec), "f1": r(f1)}
    acc = sum(conf[c][c] for c in CLASSES) / n if n else None
    return {"n": n, "agreement_with_dev_gold": r(acc), "per_class": per, "confusion": conf}


def r(x):
    return None if x is None else round(x, 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v3", required=True)
    ap.add_argument("--v2", required=True)
    ap.add_argument("--benchmark", default=str(ROOT / "data/evaluation/semantic_benchmark_v1/benchmark.json"))
    a = ap.parse_args()
    cfg = json.loads((ROOT / "backend/app/knowledge_engine/engine_config.json").read_text())
    gate_cfg = cfg["semantic_ai"]["promotion"]
    bm_text = Path(a.benchmark).read_text(encoding="utf-8")
    bm_sha = hashlib.sha256(bm_text.encode("utf-8")).hexdigest()
    if bm_sha != gate_cfg["benchmark_sha256"]:
        sys.exit(f"REFUSED: benchmark hash {bm_sha} differs from the declared {gate_cfg['benchmark_sha256']}")
    bench = json.loads(bm_text)
    v3dir, v2dir = Path(a.v3), Path(a.v2)
    cands = {c["candidate_id"]: c for c in json.loads((v3dir / "candidates.json").read_text())}
    dec3 = {d["candidate_id"]: d for d in jl(v3dir / "out/decisions.jsonl")}
    v2src = v2dir / "out/archive/run-01/decisions.jsonl"
    dec2 = {d["candidate_id"]: d for d in jl(v2src if v2src.exists() else v2dir / "out/decisions.jsonl")}
    meta3 = json.loads((v3dir / "out/run_meta.json").read_text()) if (v3dir / "out/run_meta.json").exists() else {}

    systems = defaultdict(list)
    rows = []
    for b in bench:
        cid, g = b["candidate_id"], b["label"]
        c, d3, d2 = cands[cid], dec3.get(cid), dec2.get(cid)
        pred = {"BASELINE": "AMBIGUOUS" if b["kind"] != "DIAGNOSTIC" else None,
                "V2_RAW": d2["relationship"] if d2 and b["kind"] != "DIAGNOSTIC" else None,
                "V3_RAW": d3["relationship"] if d3 else None,
                "V3_VALIDATED": effective(d3, c)}
        for s, p in pred.items():
            systems[s].append((g, p))
        rows.append({"benchmark_id": b["benchmark_id"], "candidate_id": cid, "kind": b["kind"], "tags": b["tags"],
                     "left": b["left_text"], "right": b["right_concept"], "gold": g, **pred,
                     "v3_validated_state": (v3.validate_decision({k: d3.get(k) for k in ("relationship", "reason", "evidence",
                                            "direction_justification", "alternatives", "uncertainty")}, c)
                                            if d3 and d3["decision_state"] == "MODEL_SUGGESTED" else (d3 or {}).get("decision_state"))})
    res = {"benchmark": {"path": a.benchmark, "sha256": bm_sha, "cases": len(bench),
                         "label_source": "DEVELOPMENT GOLD (assistant-labelled); not independent human labels"},
           "overall": {s: metrics(p) for s, p in systems.items()},
           "by_kind": {k: {s: metrics([(g, p) for (g, p), row in zip(systems[s], rows) if row["kind"] == k]) for s in systems}
                       for k in sorted({b["kind"] for b in bench})}}

    # ---- specific measures
    def subset(pred_key, cond):
        return [(row["gold"], row[pred_key]) for row in rows if cond(row) and row[pred_key] is not None]
    special = {}
    for s in ("V2_RAW", "V3_RAW", "V3_VALIDATED"):
        coll = subset(s, lambda x: "lexical_collision" in x["tags"] and x["gold"] == "UNRELATED")
        alias = subset(s, lambda x: x["kind"] == "ALIAS_SENSE")
        hier = [(g, p) for g, p in subset(s, lambda x: x["gold"] in ("PARENT", "CHILD")) if p in ("PARENT", "CHILD")]
        same_alias = [(g, p) for g, p in alias if p == "SAME_CONCEPT"]
        unrel_alias = [(g, p) for g, p in alias if p == "UNRELATED"]
        special[s] = {
            "lexical_collision_rejection_rate": r(sum(p == "UNRELATED" for _, p in coll) / len(coll)) if coll else None,
            "lexical_collisions_n": len(coll),
            "lexical_collisions_called_same_concept": sum(p == "SAME_CONCEPT" for _, p in coll),
            "alias_sense_agreement": r(sum(g == p for g, p in alias) / len(alias)) if alias else None, "alias_n": len(alias),
            "alias_same_concept_predicted": len(same_alias),
            "alias_same_concept_precision": r(sum(g == "SAME_CONCEPT" for g, _ in same_alias) / len(same_alias)) if same_alias else None,
            "alias_unrelated_predicted": len(unrel_alias),
            "alias_unrelated_precision": r(sum(g == "UNRELATED" for g, _ in unrel_alias) / len(unrel_alias)) if unrel_alias else None,
            "hierarchy_predictions_on_hierarchy_gold": len(hier),
            "hierarchy_direction_correct": sum(g == p for g, p in hier), "hierarchy_direction_reversed": sum(g != p for g, p in hier),
        }
    res["special"] = special

    # ---- evidence measures over ALL V3 decisions (no labels needed)
    allv = []
    for cid, d in dec3.items():
        c = cands.get(cid)
        if c is None:
            continue
        st, f = (v3.validate_decision({k: d.get(k) for k in ("relationship", "reason", "evidence", "direction_justification",
                                                              "alternatives", "uncertainty")}, c)
                 if d["decision_state"] == "MODEL_SUGGESTED" else (d["decision_state"], []))
        allv.append((d, c, st, f))
    definite = [(d, c, st, f) for d, c, st, f in allv if d["relationship"] in v3.DEFINITE and d["decision_state"] == "MODEL_SUGGESTED"]
    res["population"] = {
        "decisions": len(allv), "frozen_candidates": len(cands), "missing": sorted(set(cands) - set(dec3))[:10],
        "model_states": dict(Counter(d["decision_state"] for d, *_ in allv)),
        "raw_relationships": dict(Counter(d["relationship"] for d, *_ in allv)),
        "validated_states": dict(Counter(st for *_, st, _ in allv)),
        "validated_states_by_kind": {k: dict(Counter(st for d, c, st, _ in allv if c["kind"] == k)) for k in sorted({c["kind"] for _, c, *_ in allv})},
        "findings": dict(Counter(x.split(":")[0] for *_, f in allv for x in f)),
        "definite_decisions": len(definite),
        "evidence_grounding_rate": r(sum(not any(x.startswith(("UNKNOWN_REF", "QUOTE_NOT_IN_ITEM", "EMPTY_QUOTE")) for x in f)
                                         for *_, f in definite) / len(definite)) if definite else None,
        "source_evidence_rate": r(sum("NO_SOURCE_EVIDENCE" not in f for *_, f in definite) / len(definite)) if definite else None,
        "metadata_cited_rate": r(sum(any(x.startswith("METADATA_CITED") for x in f) for *_, f in definite) / len(definite)) if definite else None,
        "metadata_only_supported": sum(1 for d, c, st, f in definite if st == "MODEL_SUPPORTED"
                                       and all(e.get("ref", "").startswith("M") for e in d.get("evidence", []))),
        "schema_valid_rate": r(sum(d["decision_state"] == "MODEL_SUGGESTED" for d, *_ in allv) / len(allv)) if allv else None,
    }
    lat = sorted((d.get("latency_s") or 0) for d, *_ in allv)
    res["run"] = {"model": (meta3.get("provider") or {}).get("model"), "model_details": meta3.get("model_details"),
                  "runtime_version": meta3.get("runtime_version"), "prompt_version": meta3.get("prompt_version"),
                  "schema_version": meta3.get("schema_version"), "total_runtime_s": meta3.get("total_runtime_s"),
                  "adjudicator_stats": meta3.get("adjudicator_stats"), "tokens": meta3.get("tokens"),
                  "consistency": meta3.get("consistency"), "started": meta3.get("started"), "finished": meta3.get("finished"),
                  "latency_s": {"mean": r(statistics.mean(lat)), "median": r(statistics.median(lat)),
                                "p95": lat[max(0, int(round(0.95 * len(lat))) - 1)], "min": lat[0], "max": lat[-1]} if lat else None}

    # ---- V2 -> V3 transitions on the shared 270 pool
    trans = Counter()
    for cid, d in dec3.items():
        if cid in dec2:
            c = cands[cid]
            trans[(c["kind"], dec2[cid]["relationship"], effective(d, c))] += 1
    res["transitions_v2_raw_to_v3_validated"] = [{"kind": k, "v2": a2, "v3_validated": b3, "n": n} for (k, a2, b3), n in sorted(trans.items())]

    # ---- pre-declared promotion gate
    g = gate_cfg["gate"]
    sv = special["V3_VALIDATED"]
    coll_all = sum(1 for row in rows if "lexical_collision" in row["tags"] and row["V3_VALIDATED"] == "SAME_CONCEPT")
    checks = {
        "min_supported_same_concept_alias_predictions": (sv["alias_same_concept_predicted"], g["min_supported_same_concept_alias_predictions"],
                                                         sv["alias_same_concept_predicted"] >= g["min_supported_same_concept_alias_predictions"]),
        "min_precision_same_concept_alias": (sv["alias_same_concept_precision"], g["min_precision_same_concept_alias"],
                                             (sv["alias_same_concept_precision"] or 0) >= g["min_precision_same_concept_alias"]),
        "max_lexical_collisions_supported_as_same_concept": (coll_all, g["max_lexical_collisions_supported_as_same_concept"],
                                                             coll_all <= g["max_lexical_collisions_supported_as_same_concept"]),
        "min_unrelated_precision_alias": (sv["alias_unrelated_precision"], g["min_unrelated_precision_alias"],
                                          (sv["alias_unrelated_precision"] or 0) >= g["min_unrelated_precision_alias"]),
        "min_schema_valid_rate": (res["population"]["schema_valid_rate"], g["min_schema_valid_rate"],
                                  (res["population"]["schema_valid_rate"] or 0) >= g["min_schema_valid_rate"]),
        "max_metadata_only_supported": (res["population"]["metadata_only_supported"], g["max_metadata_only_supported"],
                                        res["population"]["metadata_only_supported"] <= g["max_metadata_only_supported"]),
    }
    gate = {"run": v3dir.name, "benchmark_sha256": bm_sha, "declared_in": "engine_config.json semantic_ai.promotion (before V3 outputs)",
            "checks": {k: {"value": v, "threshold": t, "pass": ok} for k, (v, t, ok) in checks.items()},
            "passed": all(ok for *_, ok in checks.values()),
            "effects_if_passed": gate_cfg["effects"], "label_source": res["benchmark"]["label_source"]}
    out = v3dir / "analysis"
    out.mkdir(exist_ok=True)
    (out / "evaluation_v3.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    (out / "benchmark_predictions.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n")
    (out / "promotion_gate.json").write_text(json.dumps(gate, indent=1))
    print(json.dumps({"overall": {s: {"n": m["n"], "agreement_with_dev_gold": m["agreement_with_dev_gold"]} for s, m in res["overall"].items()},
                      "special": special, "population": {k: v for k, v in res["population"].items() if k != "missing"},
                      "gate": gate["checks"], "gate_passed": gate["passed"]}, indent=1))


if __name__ == "__main__":
    main()
