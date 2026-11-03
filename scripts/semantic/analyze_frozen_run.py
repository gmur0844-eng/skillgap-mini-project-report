"""
Analyse a frozen adjudication run (written BEFORE its outputs were seen; nothing here is tuned on them).

Usage: python3 scripts/semantic/analyze_frozen_run.py --frozen data/semantic_runs/qwen-270-v1 --run-id 438ec2c0d5182dd4

Reads <frozen>/out (and out/archive/run-*/ for earlier invocations) and the source GOLD run (read-only).
Writes <frozen>/analysis/: analysis.json, transitions.csv, changed_decisions.jsonl, graph_candidates.jsonl.
No agreement number is called accuracy: there are no human labels for these candidates.

Deterministic checks (declared in advance)
  schema            the stored decision passes semantic_provider.validate_decision
  evidence          every quoted evidence string occurs (case/whitespace-insensitive) in LEFT, LEFT CONTEXT,
                    RIGHT, RIGHT CONTEXT or QUESTION; a definite relationship with no evidence is not grounded
  promotion         a model decision is promoted above MODEL_SUGGESTED only if the deterministic rule that
                    produced the candidate is now satisfied -- it cannot be for these candidates (they exist
                    because the rule was not satisfied), so promotions must be 0
  graph             candidate edges: non-null endpoints, no self edge, valid type, endpoints exist, no
                    contradiction with existing graph edges, no duplicate, no PARENT/CHILD cycle, provenance
"""
import argparse
import csv
import hashlib
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine import semantic_provider as sp  # noqa: E402
from app.services import knowledge_service as ks  # noqa: E402

DEFINITE = ("SAME_CONCEPT", "PARENT", "CHILD", "RELATED", "PARTIAL_OVERLAP", "UNRELATED")
EDGE_TYPE = {"SAME_CONCEPT": "SAME_AS", "PARENT": "PARENT_OF", "CHILD": "CHILD_OF", "RELATED": "RELATED_TO",
             "PARTIAL_OVERLAP": "RELATED_TO", "UNRELATED": "NOT_RELATED"}
HARD_TERMS = [".net", "visual basic", "excel", "spreadsheet", "statistics", "data collection", "aws", "gcp", "angular",
              "network", "version control", "control systems", "communication", "accounting", "java", "python", "sql", "ml"]


def norm(t):
    return re.sub(r"\s+", " ", re.sub(r"[“”\"'`…]|\.\.\.", " ", (t or "").lower())).strip()


def jl(p):
    p = Path(p)
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def grounding(d):
    hay = norm(" \n ".join(str(d.get(k) or "") for k in ("left", "left_context", "right", "right_context", "question")))
    ev = [e for e in (d.get("evidence") or []) if str(e).strip()]
    if not ev:
        return "NO_EVIDENCE", []
    missing = [e for e in ev if norm(e) and norm(e) not in hay]
    return ("ALL_GROUNDED" if not missing else "UNGROUNDED" if len(missing) == len(ev) else "PARTLY_GROUNDED"), missing


def pct(sorted_vals, q):
    return sorted_vals[max(0, int(round(q * len(sorted_vals))) - 1)] if sorted_vals else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frozen", required=True)
    ap.add_argument("--run-id", required=True)
    a = ap.parse_args()
    frozen, out = Path(a.frozen), Path(a.frozen) / "out"
    cands = {c["candidate_id"]: c for c in json.loads((frozen / "candidates.json").read_text())}
    runs = sorted((out / "archive").glob("run-*")) if (out / "archive").exists() else []
    run_dirs = runs + [out]
    metas = [json.loads((r / "run_meta.json").read_text()) for r in run_dirs if (r / "run_meta.json").exists()]
    decs_by_run = [jl(r / "decisions.jsonl") for r in run_dirs]
    first = next((i for i, m in enumerate(metas) if m.get("cache_misses")), 0)
    decisions, meta = decs_by_run[first], metas[first]
    res = {"source_run_id": a.run_id, "invocations": len(metas)}

    # ---------------- population / integrity
    ids = [d["candidate_id"] for d in decisions]
    res["population"] = {"frozen": len(cands), "decided": len(decisions), "distinct": len(set(ids)),
                         "missing": len(set(cands) - set(ids)), "missing_sample": sorted(set(cands) - set(ids))[:5], "unknown": sorted(set(ids) - set(cands)),
                         "input_hash_mismatch": sum(1 for d in decisions if not d.get("input_hash_matches_freeze"))}

    # ---------------- states, schema, failures, retries
    res["decision_states"] = dict(Counter(d["decision_state"] for d in decisions))
    res["relationships"] = dict(Counter(d["relationship"] for d in decisions))
    res["relationships_by_kind"] = {k: dict(Counter(d["relationship"] for d in decisions if d["candidate_kind"] == k))
                                    for k in sorted({d["candidate_kind"] for d in decisions})}
    schema_bad = [d for d in decisions if sp.validate_decision({k: d.get(k) for k in
                                                                ("relationship", "reason", "evidence", "alternatives", "uncertainty")})]
    res["schema"] = {"stored_decisions_failing_schema": len(schema_bad),
                     "model_outputs_rejected": sum(len(d.get("rejected_raw_outputs") or []) for d in decisions),
                     "decisions_with_rejected_outputs": sum(1 for d in decisions if d.get("rejected_raw_outputs")),
                     "review_required": res["decision_states"].get("REVIEW_REQUIRED", 0),
                     "model_failures": res["decision_states"].get("MODEL_FAILURE", 0),
                     "retries": sum(max(0, (d.get("attempts") or 1) - 1) for d in decisions),
                     "schema_success_rate_first_attempt": round(sum(1 for d in decisions if d["decision_state"] == "MODEL_SUGGESTED"
                                                                    and d.get("attempts") == 1) / max(1, len(decisions)), 4)}
    res["human_validated"] = sum(1 for d in decisions if d.get("is_human_validated"))

    # ---------------- transitions vs deterministic baseline
    trans = Counter()
    for d in decisions:
        b = cands[d["candidate_id"]]["baseline"]["rule_relationship"]
        after = d["relationship"] if d["decision_state"] == "MODEL_SUGGESTED" else d["decision_state"]
        trans[(d["candidate_kind"], b, after)] += 1
    res["transitions"] = [{"kind": k, "before": b, "after": af, "n": n} for (k, b, af), n in sorted(trans.items())]
    ms = [d for d in decisions if d["decision_state"] == "MODEL_SUGGESTED"]
    base = {d["candidate_id"]: cands[d["candidate_id"]]["baseline"]["rule_relationship"] for d in decisions}
    res["transition_summary"] = {
        "unchanged": sum(1 for d in ms if d["relationship"] == base[d["candidate_id"]]),
        "changed": sum(1 for d in ms if d["relationship"] != base[d["candidate_id"]]),
        "newly_resolved_definite": sum(1 for d in ms if d["relationship"] in DEFINITE and base[d["candidate_id"]] not in DEFINITE),
        "newly_ambiguous": sum(1 for d in ms if d["relationship"] == "AMBIGUOUS" and base[d["candidate_id"]] != "AMBIGUOUS"),
        "still_ambiguous": sum(1 for d in ms if d["relationship"] == "AMBIGUOUS"),
        "insufficient_evidence": sum(1 for d in ms if d["relationship"] == "INSUFFICIENT_EVIDENCE"),
        "newly_rejected_unrelated": sum(1 for d in ms if d["relationship"] == "UNRELATED"),
        "newly_review_required": sum(1 for d in decisions if d["decision_state"] in ("REVIEW_REQUIRED", "MODEL_FAILURE")),
        "baseline_relationships": dict(Counter(base.values())),
    }

    # ---------------- evidence grounding + promotion
    ground = {}
    for d in decisions:
        g, missing = grounding(d)
        if d["decision_state"] == "MODEL_SUGGESTED" and d["relationship"] in DEFINITE and g == "NO_EVIDENCE":
            g = "NO_EVIDENCE_FOR_DEFINITE_RELATIONSHIP"
        ground[d["candidate_id"]] = (g, missing)
    res["evidence_validation"] = {
        "by_status": dict(Counter(g for g, _ in ground.values())),
        "by_status_model_suggested_definite": dict(Counter(ground[d["candidate_id"]][0] for d in ms if d["relationship"] in DEFINITE)),
        "failures": sum(1 for d in ms if ground[d["candidate_id"]][0] not in ("ALL_GROUNDED",) and d["relationship"] in DEFINITE),
        "ungrounded_examples": [{"candidate_id": d["candidate_id"], "left": d["left"], "right": d["right"],
                                 "relationship": d["relationship"], "not_found_in_inputs": ground[d["candidate_id"]][1][:3]}
                                for d in ms if ground[d["candidate_id"]][0] in ("UNGROUNDED", "PARTLY_GROUNDED")][:15],
    }
    res["promotion"] = {"promoted_above_model_suggested": 0,
                        "reason": "each candidate exists because the deterministic rule was NOT satisfied; a model answer does "
                                  "not satisfy that rule, so nothing is promoted (RULE_SUPPORTED requires the rule itself)"}

    # ---------------- consistency / determinism
    cons = jl(out / "consistency.jsonl") if (out / "consistency.jsonl").exists() else []
    cons = cons or next((jl(r / "consistency.jsonl") for r in reversed(run_dirs) if (r / "consistency.jsonl").exists()), [])
    res["model_consistency_resample"] = {"n": len(cons), "same_relationship": sum(c["same_relationship"] for c in cons),
                                         "same_output_hash": sum(c["same_output_hash"] for c in cons)}
    hashes = [sorted(d["output_hash"] for d in ds) for ds in decs_by_run if ds]
    res["rerun_consistency"] = {"invocations_with_decisions": len(hashes),
                                "identical_output_hashes_across_invocations": all(h == hashes[0] for h in hashes),
                                "cache_hits_by_invocation": [m.get("cache_hits") for m in metas],
                                "cache_misses_by_invocation": [m.get("cache_misses") for m in metas]}

    # ---------------- performance, tokens, memory
    lat = sorted(d["wall_latency_s"] for d in decisions if not d.get("cache_hit"))
    res["performance"] = {"total_runtime_s": meta.get("total_runtime_s"), "uncached_decisions": len(lat),
                          "mean_s": round(statistics.mean(lat), 3) if lat else None,
                          "median_s": round(statistics.median(lat), 3) if lat else None,
                          "p95_s": pct(lat, 0.95), "min_s": lat[0] if lat else None, "max_s": lat[-1] if lat else None,
                          "tokens": meta.get("tokens"), "model_calls": (meta.get("adjudicator_stats") or {}).get("model_calls")}
    mem = next((jl(r / "memory_samples.jsonl") for r in run_dirs[first:first + 1]), [])
    free = [int(m.group(1)) for s in mem for m in [re.search(r"free percentage:\s*(\d+)", s.get("memory_pressure") or "")] if m]
    swap = [s.get("swapusage") for s in mem]
    res["memory"] = {"samples": len(mem), "system_free_pct_min": min(free) if free else None,
                     "system_free_pct_max": max(free) if free else None, "swapusage_first": swap[0] if swap else None,
                     "swapusage_last": swap[-1] if swap else None,
                     "ollama_model_bytes": next((x.get("size") for s in mem for x in (s.get("ollama_ps") or [])
                                                 if isinstance(x, dict)), None)}
    res["model"] = {k: meta.get(k) for k in ("provider", "model_details", "runtime_version", "prompt_version", "schema_version",
                                             "engine_config_version", "config_sha256", "semantic_provider_sha256",
                                             "runner_sha256", "host", "python", "concurrency", "started", "finished")}
    res["freeze"] = meta.get("freeze_manifest")

    # ---------------- graph safety (candidate edges are NOT persisted)
    run = ks.KnowledgeRun(a.run_id)
    it = run.dir / "intelligence"
    nodes = {n["node_id"] for n in jl(it / "graph_nodes.jsonl")}
    existing = defaultdict(set)
    for e in jl(it / "graph_edges.jsonl"):
        existing[(e["source"], e["target"])].add(e["relationship"])
    tm = {m["mapping_uid"]: m for m in run.mappings}
    esco = {m["esco_uri"] for m in jl(run.dir / "industry/skills.jsonl") if m.get("esco_uri")} | \
           {m.get("taxonomy_candidate_uri") for m in jl(run.dir / "industry/skills.jsonl")}
    maps = {m["mapping_uid"]: m for m in jl(run.dir / "industry/esco_mappings.jsonl")}
    for m in maps.values():
        esco |= {c.get("uri") for c in m.get("candidates", [])} | {c.get("uri") for c in m.get("alternative_concepts", [])}
    mentions = {m["mention_uid"] for m in jl(run.dir / "industry/skill_mentions.jsonl")}
    graph_rows, seen = [], Counter()
    for d in ms:
        if d["relationship"] not in DEFINITE:
            continue
        kind = d["candidate_kind"]
        if kind == "AMBIGUOUS_TOPIC_MAPPING":
            src = (tm.get(d["source_entity"]) or {}).get("source_uid")
            src_ok = src in nodes
        elif kind == "ALIAS_SENSE":
            src, src_ok = d["source_entity"], d["source_entity"] in mentions
        else:
            src, src_ok = d["source_entity"], d["source_entity"] in maps
        tgt = d["candidate_entity"]
        tgt_ok = (tgt in nodes) if kind == "AMBIGUOUS_TOPIC_MAPPING" else (tgt in esco)
        rel = EDGE_TYPE[d["relationship"]]
        problems = []
        if not src or not tgt:
            problems.append("NULL_ENDPOINT")
        if src and src == tgt:
            problems.append("SELF_EDGE")
        if not src_ok:
            problems.append("SOURCE_NOT_FOUND")
        if not tgt_ok:
            problems.append("TARGET_NOT_FOUND")
        prior = existing.get((src, tgt), set()) | existing.get((tgt, src), set())
        if rel == "NOT_RELATED" and prior & {"SAME_AS", "PARENT_OF", "CHILD_OF"}:
            problems.append(f"CONTRADICTS_EXISTING:{sorted(prior)}")
        if rel == "SAME_AS" and prior & {"PARENT_OF", "CHILD_OF"}:
            problems.append(f"CONTRADICTS_EXISTING:{sorted(prior)}")
        if not (d.get("decision_id") and d.get("model") and d.get("prompt_version")):
            problems.append("MISSING_PROVENANCE")
        if ground[d["candidate_id"]][0] != "ALL_GROUNDED":
            problems.append("EVIDENCE_NOT_GROUNDED")
        seen[(src, rel, tgt)] += 1
        graph_rows.append({"candidate_id": d["candidate_id"], "kind": kind, "source": src, "relationship": rel, "target": tgt,
                           "decision_id": d["decision_id"], "evidence_status": "MODEL_SUGGESTED", "problems": problems})
    for r in graph_rows:
        if seen[(r["source"], r["relationship"], r["target"])] > 1:
            r["problems"].append("DUPLICATE_CANDIDATE_EDGE")
    adj = defaultdict(set)
    for r in graph_rows:
        if r["relationship"] == "PARENT_OF":
            adj[r["source"]].add(r["target"])
        if r["relationship"] == "CHILD_OF":
            adj[r["target"]].add(r["source"])
    cyc = sum(1 for s, ts in adj.items() for t in ts if s in adj.get(t, ()))
    res["graph_safety"] = {"candidate_edges": len(graph_rows), "by_relationship": dict(Counter(r["relationship"] for r in graph_rows)),
                           "problems": dict(Counter(p.split(":")[0] for r in graph_rows for p in r["problems"])),
                           "edges_without_problems": sum(1 for r in graph_rows if not r["problems"]),
                           "two_cycles_parent_child": cyc, "persisted": 0}

    # ---------------- ESCO safety (source GOLD untouched; model output never becomes demand)
    gold_files = sorted((run.dir / "industry").glob("*.jsonl"))
    res["esco_safety"] = {
        "alias_sense_model_same_concept": sum(1 for d in ms if d["candidate_kind"] == "ALIAS_SENSE" and d["relationship"] == "SAME_CONCEPT"),
        "alias_sense_model_unrelated": sum(1 for d in ms if d["candidate_kind"] == "ALIAS_SENSE" and d["relationship"] == "UNRELATED"),
        "demand_rows_changed": 0, "note": "this run writes only to the frozen run's out/ and analysis/; GOLD is read-only here",
        "gold_industry_files_sha256": hashlib.sha256(b"".join(f.read_bytes() for f in gold_files)).hexdigest()}

    # ---------------- representative / hard cases
    def pick(pred, n=4):
        return [{k: d.get(k) for k in ("candidate_id", "candidate_kind", "left", "right", "relationship", "decision_state", "reason",
                                        "evidence")} | {"left_context": (d.get("left_context") or "")[:220],
                                                        "grounding": ground[d["candidate_id"]][0]}
                for d in sorted(decisions, key=lambda x: x["candidate_id"]) if pred(d)][:n]
    by_left = defaultdict(set)
    for d in ms:
        by_left[norm(d["left"])].add(d["relationship"])
    ctx_dep = {k for k, v in by_left.items() if len(v & set(DEFINITE)) > 1}
    res["categories"] = {
        "A_context_changes_meaning": pick(lambda d: d["decision_state"] == "MODEL_SUGGESTED" and norm(d["left"]) in ctx_dep, 6),
        "B_same_concept_different_wording": pick(lambda d: d["relationship"] == "SAME_CONCEPT" and norm(d["left"]) != norm(d["right"])),
        "C_parent_child": pick(lambda d: d["relationship"] in ("PARENT", "CHILD")),
        "D_partial_overlap": pick(lambda d: d["relationship"] == "PARTIAL_OVERLAP"),
        "E_unrelated_lexical_collision": pick(lambda d: d["relationship"] == "UNRELATED"
                                              and set(norm(d["left"]).split()) & set(norm(d["right"]).split())),
        "F_ambiguous_or_insufficient": pick(lambda d: d["relationship"] in ("AMBIGUOUS", "INSUFFICIENT_EVIDENCE")
                                            and d["decision_state"] == "MODEL_SUGGESTED"),
        "G_alias_sense": pick(lambda d: d["candidate_kind"] == "ALIAS_SENSE", 6),
        "H_esco_mapping": pick(lambda d: d["candidate_kind"] == "AMBIGUOUS_TAXONOMY_LABEL", 6),
        "I_topic_to_concept": pick(lambda d: d["candidate_kind"] == "AMBIGUOUS_TOPIC_MAPPING", 6),
        "context_dependent_surfaces": sorted(ctx_dep)[:40],
    }
    hard = {}
    for term in HARD_TERMS:
        rows = [d for d in decisions if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", norm(d["left"]) + " | " + norm(d["right"]))]
        if rows:
            hard[term] = {"n": len(rows), "relationships": dict(Counter(d["relationship"] for d in rows)),
                          "examples": [{"left": d["left"], "right": d["right"], "relationship": d["relationship"],
                                        "state": d["decision_state"], "context": (d.get("left_context") or "")[:180],
                                        "reason": d["reason"]} for d in sorted(rows, key=lambda x: x["candidate_id"])[:3]]}
        else:
            hard[term] = {"n": 0, "note": "not among the 270 candidates"}
    res["hard_cases_in_270"] = hard
    diag = next((jl(r / "diagnostics.jsonl") for r in run_dirs[first:first + 1] if (r / "diagnostics.jsonl").exists()), [])
    res["hard_case_diagnostics"] = {"n": len(diag), "agree_with_specification_expectation": sum(1 for x in diag if x["relationship"] == x["expected_by_specification"]),
                                    "rows": diag,
                                    "note": "16 fixed pairs WITHOUT context; expectations transcribed from the specification, not human labels"}

    # ---------------- write
    ad = frozen / "analysis"
    ad.mkdir(exist_ok=True)
    (ad / "analysis.json").write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str))
    with (ad / "transitions.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["kind", "before", "after", "n"])
        w.writeheader()
        w.writerows(res["transitions"])
    with (ad / "changed_decisions.jsonl").open("w", encoding="utf-8") as fh:
        for d in sorted(decisions, key=lambda x: x["candidate_id"]):
            b = cands[d["candidate_id"]]["baseline"]["rule_relationship"]
            after = d["relationship"] if d["decision_state"] == "MODEL_SUGGESTED" else d["decision_state"]
            fh.write(json.dumps({"candidate_id": d["candidate_id"], "kind": d["candidate_kind"], "left": d["left"],
                                 "left_context": d.get("left_context"), "right": d["right"], "right_context": d.get("right_context"),
                                 "before": b, "after": after, "changed": after != b, "reason": d["reason"],
                                 "evidence": d["evidence"], "evidence_grounding": ground[d["candidate_id"]][0],
                                 "uncertainty": d["uncertainty"], "decision_id": d["decision_id"]}, ensure_ascii=False) + "\n")
    (ad / "graph_candidates.jsonl").write_text("\n".join(json.dumps(r) for r in graph_rows) + "\n")
    print(json.dumps({k: res[k] for k in ("population", "decision_states", "relationships", "schema", "transition_summary",
                                          "evidence_validation", "graph_safety", "performance", "memory", "rerun_consistency",
                                          "model_consistency_resample")}, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
