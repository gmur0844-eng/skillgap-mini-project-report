"""
Independent, model-blind labelling of the frozen semantic benchmark.

  export   writes a labelling sheet with ONLY the case texts (no model output, no development-gold label, no rationale):
           data/evaluation/semantic_benchmark_v1/independent_labels/labelling_sheet.csv
  ingest   --file <filled sheet> --reviewer "<name>" --label-version v1
           validates every label, refuses the assistant or a blank reviewer, stores an immutable
           labels_<reviewer>_<version>.json (never overwritten) with timestamps and the benchmark hash
  compare  --labels <labels json> : per-system agreement and per-class precision/recall against the INDEPENDENT labels,
           and agreement (Cohen's kappa) between the independent reviewer and the assistant's development gold
  agreement            Cohen's kappa (2 reviewers) / Fleiss' kappa (3+), every disagreement listed
  adjudication-sheet   disagreements for a named human adjudicator (choose a reviewer's label or AMBIGUOUS)
  adjudicate           --file <sheet> --adjudicator "<name>": immutable adjudication record
  gold                 freeze semantic_gold_v1 (UNANIMOUS / ADJUDICATED; UNRESOLVED and UNLABELLED excluded, listed)
  evaluate [--internal-preview]  all systems on all cases + promotion gate v2; PENDING_INDEPENDENT_LABELS without gold

The frozen benchmark itself is never modified (its SHA-256 is checked on every command).
"""
import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "data/evaluation/semantic_benchmark_v1/benchmark.json"
OUT = ROOT / "data/evaluation/semantic_benchmark_v1/independent_labels"
FROZEN_SHA = "94b4e79c49bc2c7a0c5bce0234298f9ebada568c1e767ee8651aac19ac3722b7"
LABELS = ("SAME_CONCEPT", "PARENT", "CHILD", "RELATED", "PARTIAL_OVERLAP", "UNRELATED", "AMBIGUOUS",
          "INSUFFICIENT_EVIDENCE")
NOT_INDEPENDENT = re.compile(r"(?i)\b(assistant|claude|model|qwen|gpt|llm|auto)\b")


def load_bench():
    raw = BENCH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_SHA:
        raise SystemExit("benchmark hash mismatch: the frozen benchmark was modified")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _ctx(items):
    return " | ".join(f"[{i.get('source_type')}] {i.get('text')}" for i in items or [])


def export(_args):
    bench, sha = load_bench()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "labelling_sheet.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["benchmark_id", "question", "left_expression", "left_context", "right_concept",
                    "right_description", "label", "note"])
        for c in bench:
            w.writerow([c["benchmark_id"], "Does the LEFT expression mean, represent, teach or require the RIGHT concept "
                        "in this context?", c["left_text"], _ctx(c["left_context"]), c["right_concept"],
                        c.get("right_description") or _ctx(c.get("right_context")), "", ""])
    (OUT / "LABELLING_GUIDE.md").write_text(
        "# Independent labelling guide\n\nFill the `label` column with one of: " + ", ".join(LABELS) + ".\n\n"
        "- Judge the meaning in the given context only. A shared word or one string inside another is not a hierarchy.\n"
        "- PARENT: LEFT is broader than RIGHT. CHILD: LEFT is narrower than RIGHT.\n"
        "- Use AMBIGUOUS when the context allows more than one reading, INSUFFICIENT_EVIDENCE when it decides nothing.\n"
        "- Do not look at any model output or at the development gold while labelling.\n", encoding="utf-8")
    print(f"sheet: {path} ({len(bench)} cases, benchmark sha {sha[:12]}); guide: {OUT / 'LABELLING_GUIDE.md'}")


def ingest(a):
    bench, sha = load_bench()
    if not a.reviewer.strip() or NOT_INDEPENDENT.search(a.reviewer):
        raise SystemExit("a named independent human reviewer is required (the assistant or a model cannot be one)")
    ids = {c["benchmark_id"] for c in bench}
    rows, errors = [], []
    with open(a.file, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            bid, label = r.get("benchmark_id", "").strip(), (r.get("label") or "").strip().upper()
            if bid not in ids:
                errors.append(f"unknown benchmark_id {bid!r}")
                continue
            if label and label not in LABELS:
                errors.append(f"{bid}: invalid label {label!r}")
                continue
            rows.append({"benchmark_id": bid, "label": label or None, "note": (r.get("note") or "").strip() or None})
    if errors:
        raise SystemExit("rejected:\n  " + "\n  ".join(errors[:50]))
    slug = re.sub(r"[^a-z0-9]+", "-", a.reviewer.lower()).strip("-")
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"labels_{slug}_{a.label_version}.json"
    if out.exists():
        raise SystemExit(f"{out.name} exists; label sets are immutable -- use a new --label-version")
    doc = {"benchmark": "semantic_benchmark_v1", "benchmark_sha256": sha, "reviewer": a.reviewer,
           "label_version": a.label_version, "independent": True, "model_blind": True,
           "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "source_sheet_sha256": hashlib.sha256(Path(a.file).read_bytes()).hexdigest(),
           "labels": rows, "labelled": sum(1 for r in rows if r["label"])}
    out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"stored {out} ({doc['labelled']} labelled of {len(ids)})")


def kappa(a, b):
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return None if pe == 1 else round((po - pe) / (1 - pe), 4)


def compare(a):
    bench, _ = load_bench()
    doc = json.loads(Path(a.labels).read_text())
    if not (doc.get("independent") and doc.get("model_blind")):
        raise SystemExit("not an independent, model-blind label set")
    gold = {r["benchmark_id"]: r["label"] for r in doc["labels"] if r["label"]}
    dev = {c["benchmark_id"]: c["label"] for c in bench}
    preds = [json.loads(x) for x in (ROOT / "data/semantic_runs/qwen-270-v3/analysis/benchmark_predictions.jsonl")
             .read_text().splitlines() if x.strip()]
    ids = sorted(gold)
    res = {"labels": len(ids), "reviewer": doc["reviewer"], "label_version": doc["label_version"],
           "kappa_independent_vs_dev_gold": kappa([gold[i] for i in ids], [dev[i] for i in ids]), "systems": {}}
    for system in ("V2_RAW", "V3_RAW", "V3_VALIDATED"):
        pairs = [(gold[p["benchmark_id"]], p[system]) for p in preds if p["benchmark_id"] in gold and p.get(system)]
        per = {}
        for cls in LABELS:
            tp = sum(1 for g, y in pairs if g == cls and y == cls)
            pp = sum(1 for _, y in pairs if y == cls)
            gp = sum(1 for g, _ in pairs if g == cls)
            per[cls] = {"precision": round(tp / pp, 4) if pp else None, "recall": round(tp / gp, 4) if gp else None,
                        "support": gp}
        res["systems"][system] = {"n": len(pairs), "agreement": round(sum(g == y for g, y in pairs) / len(pairs), 4)
                                  if pairs else None, "per_class": per}
    out = Path(a.labels).with_name(Path(a.labels).stem + "_comparison.json")
    out.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1)[:3000])


# ---------------------------------------------------------------- improvement release: gold + evaluation
sys.path.insert(0, str(ROOT / "backend"))
from app.knowledge_engine import semantic_eval as se  # noqa: E402

RESULTS = ROOT / "data/evaluation/semantic_benchmark_v1/results"
GOLD = ROOT / "data/evaluation/semantic_benchmark_v1/semantic_gold_v1.json"
GATE = ROOT / "data/evaluation/semantic_gate_v2.json"
PREDICTIONS = ROOT / "data/semantic_runs/qwen-270-v3/analysis/benchmark_predictions.jsonl"


def _gate():
    cfg = json.loads((ROOT / "backend/app/knowledge_engine/engine_config.json").read_text())
    raw = GATE.read_bytes()
    want = cfg["semantic_promotion_v2"]["gate_sha256"]
    if se.sha256_bytes(raw) != want:
        raise SystemExit("gate v2 file does not match the SHA-256 recorded in engine_config (it was modified)")
    return json.loads(raw), want


def agreement_cmd(_a):
    bench, sha = load_bench()
    sets = se.load_label_sets(OUT, sha)
    res = se.agreement(sets)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "agreement.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("reviewers", "cases_labelled_by_all", "measure", "kappa")}, indent=1))
    print(f"{len(res['disagreements'])} disagreement(s) -> {RESULTS / 'agreement.json'}")


def adjudication_sheet(_a):
    bench, sha = load_bench()
    res = se.agreement(se.load_label_sets(OUT, sha))
    by_id = {c["benchmark_id"]: c for c in bench}
    path = OUT / "adjudication_sheet.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["benchmark_id", "left_expression", "left_context", "right_concept", "reviewer_labels", "decision", "note"])
        for d in res["disagreements"]:
            c = by_id[d["case"]]
            w.writerow([d["case"], c["left_text"], _ctx(c["left_context"]), c["right_concept"],
                        "; ".join(f"{k}={v}" for k, v in sorted(d["labels"].items())), "", ""])
    print(f"{len(res['disagreements'])} case(s) to adjudicate -> {path} (choose one of the reviewers' labels or AMBIGUOUS)")


def adjudicate(a):
    bench, sha = load_bench()
    name = se.check_reviewer(a.adjudicator)
    decisions, errors = {}, []
    with open(a.file, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = (r.get("decision") or "").strip().upper()
            if d and d not in LABELS:
                errors.append(f"{r.get('benchmark_id')}: invalid decision {d!r}")
            elif d:
                decisions[r["benchmark_id"].strip()] = d
    if errors:
        raise SystemExit("rejected:\n  " + "\n  ".join(errors))
    out = OUT / f"adjudication_{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}.json"
    if out.exists():
        raise SystemExit(f"{out.name} exists; adjudications are immutable")
    out.write_text(json.dumps({"benchmark_sha256": sha, "adjudicator": name, "adjudicated_at": se.now(),
                               "process": "choose among the reviewers' labels or AMBIGUOUS; the model answer is never used",
                               "decisions": decisions}, indent=1), encoding="utf-8")
    print(f"stored {out} ({len(decisions)} decisions)")


def gold_cmd(_a):
    bench, sha = load_bench()
    if GOLD.exists():
        raise SystemExit(f"{GOLD.name} is frozen; a revision must be released as semantic_gold_v2")
    sets = se.load_label_sets(OUT, sha)
    if not sets:
        raise SystemExit("no independent label set exists; gold cannot be frozen (status stays PENDING_INDEPENDENT_LABELS)")
    adj_files = sorted(OUT.glob("adjudication_*.json"))
    adjudication = json.loads(adj_files[-1].read_text()) if adj_files else None
    rows = se.build_gold(bench, sets, adjudication)
    doc = {"gold": "semantic_gold_v1", "frozen_at": se.now(), "benchmark_sha256": sha,
           "reviewers": [s["reviewer"] for s in sets], "adjudicator": (adjudication or {}).get("adjudicator"),
           "agreement": {k: v for k, v in se.agreement(sets).items() if k != "disagreements"},
           "status_counts": dict(Counter(r["adjudication_status"] for r in rows)), "cases": rows}
    GOLD.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"frozen {GOLD}: {doc['status_counts']}")


def evaluate_cmd(a):
    bench, sha = load_bench()
    gate, gate_sha = _gate()
    preds = [json.loads(x) for x in PREDICTIONS.read_text().splitlines() if x.strip()]
    findings = se.group_findings(preds)
    sets = se.load_label_sets(OUT, sha)
    cases = [{**c, "left": p["left"], "right": p["right"], "tags": p["tags"], "kind": p["kind"]}
             for c, p in zip(sorted(bench, key=lambda c: c["benchmark_id"]), sorted(preds, key=lambda p: p["benchmark_id"]))]

    def run(gold):
        systems = {name: se.evaluate_system(cases, gold, {p["benchmark_id"]: p.get(col) for p in preds},
                                            findings if name != "DETERMINISTIC_BASELINE" else None)
                   for name, col in se.SYSTEMS.items()}
        for s in systems.values():
            s["by_kind"] = se.by_kind(s["per_case"])
        comp = {m: se.contingency(systems["DETERMINISTIC_BASELINE"]["per_case"], systems[m]["per_case"])
                for m in ("QWEN_RAW", "QWEN_VALIDATED")}
        return systems, comp
    out = {"benchmark": "semantic_benchmark_v1", "benchmark_sha256": sha, "gate": gate["version"], "gate_sha256": gate_sha,
           "evaluated_at": se.now(), "cases_in_benchmark": len(bench), "reviewers": [s["reviewer"] for s in sets]}
    if GOLD.exists():
        gdoc = json.loads(GOLD.read_text())
        gold = {r["case_id"]: r["gold"] for r in gdoc["cases"] if r["gold"]}
        systems, comp = run(gold)
        agreement = gdoc["agreement"]
        out.update(status="INDEPENDENTLY_EVALUATED", gold="semantic_gold_v1", gold_cases=len(gold),
                   gold_distribution=dict(Counter(gold.values())), agreement=agreement, systems=systems, baseline_vs_model=comp,
                   gate_result=se.apply_gate(gate, gdoc["cases"], agreement, systems[gate["evaluated_system"]], sets))
    else:
        out.update(se.pending_status(sha, gate, sets))
    if a.internal_preview:
        dev = {c["benchmark_id"]: c["label"] for c in bench}
        systems, comp = run(dev)
        out["internal_development_preview"] = {
            "label_source": "DEVELOPMENT GOLD labelled by the assistant -- NOT independent, NOT human-validated; "
                            "for development diagnostics only; never used by the promotion gate",
            "gold_distribution": dict(Counter(dev.values())), "systems": systems, "baseline_vs_model": comp}
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / "semantic_ai_evaluation.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: out.get(k) for k in ("status", "reviewers", "gold_cases", "mode")}, indent=1))
    print(f"-> {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export")
    i = sub.add_parser("ingest")
    i.add_argument("--file", required=True)
    i.add_argument("--reviewer", required=True)
    i.add_argument("--label-version", default="v1")
    c = sub.add_parser("compare")
    c.add_argument("--labels", required=True)
    sub.add_parser("agreement")
    sub.add_parser("adjudication-sheet")
    j = sub.add_parser("adjudicate")
    j.add_argument("--file", required=True)
    j.add_argument("--adjudicator", required=True)
    sub.add_parser("gold")
    e = sub.add_parser("evaluate")
    e.add_argument("--internal-preview", action="store_true",
                   help="also compute metrics against the assistant's DEVELOPMENT labels (flagged, never used by the gate)")
    a = ap.parse_args()
    {"export": export, "ingest": ingest, "compare": compare, "agreement": agreement_cmd,
     "adjudication-sheet": adjudication_sheet, "adjudicate": adjudicate, "gold": gold_cmd,
     "evaluate": evaluate_cmd}[a.cmd](a)
