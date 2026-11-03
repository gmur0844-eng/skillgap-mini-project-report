#!/usr/bin/env python3
"""Score model runs on the frozen candidates against reviewer judgments of the human-validation subset.

    python3 scripts/semantic/score_against_reviewers.py \\
        --run v3=data/semantic_runs/qwen-270-v3/out --run v4=data/semantic_runs/qwen-270-v4/out \\
        [--package data/evaluation/semantic_gold/computer-science-and-engineering/v1] [--a R02 --b R03] [--out <json>]

Two references, never mixed:
  DEVELOPMENT   the cases on which two reviewers' stored responses (<package>/responses/) agree. These responses are
                not independent labels (see their reviewer_source); the prompt was designed with them in view, so a
                score here is a development estimate and can never pass the promotion gate.
  INDEPENDENT   the frozen gold (<package>/semantic_gold_v1.json) when it exists, else PENDING. Only this reference
                can show whether a prompt generalises; the gate itself is applied by semantic_validation.py evaluate.

For every run and reference: the model's own answer (raw) and what downstream would read after the unchanged evidence
validator (validated: the relationship only when the validator supports it); how often the validated system commits
to a definite relationship, and how often it is right when it does; the most frequent confusions; the validator's
findings. Nothing is written except --out.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine import semantic_responses as sr  # noqa: E402
from app.knowledge_engine import semantic_v3 as v3  # noqa: E402

PKG = ROOT / "data/evaluation/semantic_gold/computer-science-and-engineering/v1"
BENCH = ROOT / "data/evaluation/semantic_benchmark_v1/benchmark.json"
CANDIDATES = ROOT / "data/semantic_runs/qwen-270-v3/candidates.json"
ABSTAIN = ("AMBIGUOUS", "INSUFFICIENT_EVIDENCE")


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def validated(d, cand):
    """What downstream may read (same rule as scripts/semantic/evaluate_v3.py `effective`)."""
    if d is None:
        return None, ["NO_DECISION"]
    if d.get("decision_state") not in ("MODEL_SUGGESTED", "MODEL_SUPPORTED", "INSUFFICIENT_EVIDENCE", "REVIEW_REQUIRED"):
        return "AMBIGUOUS", [f"DECISION_STATE:{d.get('decision_state')}"]
    out = {k: d.get(k) for k in ("relationship", "reason", "evidence", "direction_justification", "alternatives",
                                 "uncertainty")}
    state, findings = v3.validate_decision(out, cand)
    if state in ("MODEL_SUPPORTED", "MODEL_SUGGESTED"):
        return d["relationship"], findings
    return ("INSUFFICIENT_EVIDENCE" if state == "INSUFFICIENT_EVIDENCE" else "AMBIGUOUS"), findings


def references(pkg, a, b):
    subset = json.loads((pkg / "subset.json").read_text())["case_ids"]
    records, files = sr.load(pkg)
    rows = sr.compare(records, subset, a, b)
    sources = sorted({f["reviewer_source"] for f in files if f["reviewer_id"] in (a, b)})
    dev = {r["question_id"]: r[a]["label"] for r in rows if r["comparison"] == "AGREE"}
    gold_path = pkg / "semantic_gold_v1.json"
    indep = None
    if gold_path.exists():
        indep = {r["case_id"]: r["gold"] for r in json.loads(gold_path.read_text())["cases"] if r.get("gold")}
    return {"DEVELOPMENT": {"labels": dev, "what": f"cases on which {a} and {b} agree; their stated source: {sources}; "
                                                 "not independent labels"},
            "INDEPENDENT": {"labels": indep, "what": "frozen gold semantic_gold_v1" if indep is not None else
                            "PENDING: no independent label set has been frozen"}}


def score(labels, decisions, cands, cid_of):
    pairs, raw_ok, val_ok, committed, committed_ok = [], 0, 0, 0, 0
    confusion, findings, missing = Counter(), Counter(), []
    for case, gold in sorted(labels.items()):
        cid = cid_of.get(case)
        d = decisions.get(cid)
        if d is None:
            missing.append(case)
            continue
        raw = d.get("relationship")
        val, f = validated(d, cands[cid])
        findings.update(x.split(":")[0] for x in f)
        raw_ok += raw == gold
        val_ok += val == gold
        if val not in ABSTAIN:
            committed += 1
            committed_ok += val == gold
        if raw != gold:
            confusion[f"{gold} -> {raw}"] += 1
        pairs.append({"case": case, "reference": gold, "raw": raw, "validated": val})
    n = len(pairs)
    pct = (lambda x, d: round(x / d, 4) if d else None)  # noqa: E731
    return {"cases_scored": n, "cases_without_decision": missing,
            "raw_correct": raw_ok, "raw_accuracy": pct(raw_ok, n),
            "validated_correct": val_ok, "validated_accuracy": pct(val_ok, n),
            "validated_commits": committed, "validated_commit_rate": pct(committed, n),
            "validated_precision_when_committed": pct(committed_ok, committed),
            "top_raw_confusions": confusion.most_common(8), "validator_findings": findings.most_common(),
            "cases": pairs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, help="name=<folder with decisions.jsonl>")
    ap.add_argument("--package", default=str(PKG))
    ap.add_argument("--a", default="R02")
    ap.add_argument("--b", default="R03")
    ap.add_argument("--out")
    args = ap.parse_args()
    bench = json.loads(BENCH.read_text(encoding="utf-8"))
    bench = bench.get("cases", bench) if isinstance(bench, dict) else bench
    cid_of = {b["benchmark_id"]: b["candidate_id"] for b in bench}
    cands = {c["candidate_id"]: c for c in json.loads(CANDIDATES.read_text(encoding="utf-8"))}
    refs = references(Path(args.package), args.a, args.b)
    report = {"references": {k: {"what": v["what"], "cases": None if v["labels"] is None else len(v["labels"])}
                             for k, v in refs.items()}, "runs": {}}
    for spec in args.run:
        name, folder = spec.split("=", 1)
        decisions = {d["candidate_id"]: d for d in jl(Path(folder) / "decisions.jsonl")}
        meta = json.loads((Path(folder) / "run_meta.json").read_text()) if (Path(folder) / "run_meta.json").exists() else {}
        report["runs"][name] = {"folder": folder, "prompt_version": meta.get("prompt_version"),
                                **{ref: (score(v["labels"], decisions, cands, cid_of) if v["labels"] is not None
                                         else {"status": "PENDING_INDEPENDENT_LABELS"}) for ref, v in refs.items()}}
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    for name, r in report["runs"].items():
        for ref in ("DEVELOPMENT", "INDEPENDENT"):
            s = r[ref]
            if "status" in s:
                print(f"{name:4} {ref:12} {s['status']}")
                continue
            print(f"{name:4} {ref:12} raw {s['raw_correct']}/{s['cases_scored']}  validated {s['validated_correct']}/"
                  f"{s['cases_scored']}  commits {s['validated_commits']}  right when committing "
                  f"{s['validated_precision_when_committed']}  ({r['prompt_version']})")
    print("DEVELOPMENT is not an independent evaluation:", report["references"]["DEVELOPMENT"]["what"])


if __name__ == "__main__":
    main()
