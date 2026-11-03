"""
Independent semantic evaluation (improvement release).

The frozen 88-case benchmark (semantic_benchmark_v1, SHA-256 checked) becomes an independent evaluation set:

  1. model-blind reviewer sheets (no model prediction, confidence, internal decision or development label)
  2. one immutable label file per independent human reviewer (the assistant or a model is refused as reviewer)
  3. agreement: Cohen's kappa for two reviewers, Fleiss' kappa for three or more; every disagreement listed
  4. predefined adjudication: unanimous cases become gold directly; disagreements go to a named human
     adjudicator who chooses among the reviewers' labels (or AMBIGUOUS); the model answer is never used
  5. semantic_gold_v1: frozen gold labels (case, gold relationship, evidence, adjudication status, reviewers)
  6. evaluation of every system on ALL cases: accuracy, macro precision/recall/F1, per-class metrics,
     confusion matrix, critical semantic errors, critical-error rate, baseline-vs-model 2x2 table
  7. promotion gate v2 (declared in data/evaluation/semantic_gate_v2.json BEFORE any independent label existed):
     Qwen stays in SAFE_MODE unless the gate passes, and then only the relationship classes that pass their own
     precision criterion may be promoted.

Until independent labels exist, every result is PENDING_INDEPENDENT_LABELS. An INTERNAL development preview
against the assistant's development labels can be computed; it is always flagged as not independent.
"""
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

LABELS = ("SAME_CONCEPT", "PARENT", "CHILD", "RELATED", "PARTIAL_OVERLAP", "UNRELATED", "AMBIGUOUS",
          "INSUFFICIENT_EVIDENCE")
DEFINITE = ("SAME_CONCEPT", "PARENT", "CHILD", "RELATED", "PARTIAL_OVERLAP", "UNRELATED")
NOT_INDEPENDENT = re.compile(r"(?i)\b(assistant|claude|model|qwen|gpt|llm|auto|bot)\b")
HALLUCINATION_FINDINGS = ("QUOTE_NOT_IN_ITEM", "METADATA_CITED")
SYSTEMS = {"DETERMINISTIC_BASELINE": "BASELINE", "QWEN_RAW": "V3_RAW", "QWEN_VALIDATED": "V3_VALIDATED"}


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def check_reviewer(name):
    if not name or not name.strip() or NOT_INDEPENDENT.search(name):
        raise ValueError("a named independent human reviewer is required (the assistant or a model cannot be one)")
    return name.strip()


# ------------------------------------------------------------------ agreement

def cohen_kappa(a, b):
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return None if pe == 1 else round((po - pe) / (1 - pe), 4)


def fleiss_kappa(table):
    """table: list of per-case Counters of labels (every case rated by the same number of raters)."""
    if not table:
        return None
    n = sum(table[0].values())
    if n < 2 or any(sum(t.values()) != n for t in table):
        return None
    N = len(table)
    cats = sorted({k for t in table for k in t})
    p_j = {c: sum(t.get(c, 0) for t in table) / (N * n) for c in cats}
    P_i = [(sum(v * v for v in t.values()) - n) / (n * (n - 1)) for t in table]
    P_bar = sum(P_i) / N
    P_e = sum(v * v for v in p_j.values())
    return None if P_e == 1 else round((P_bar - P_e) / (1 - P_e), 4)


def agreement(label_sets):
    """label_sets: [{"reviewer", "labels": {case: label}}]. Only cases labelled by every reviewer are compared."""
    reviewers = [s["reviewer"] for s in label_sets]
    common = sorted(set.intersection(*(set(s["labels"]) for s in label_sets))) if label_sets else []
    out = {"reviewers": reviewers, "cases_labelled_by_all": len(common), "measure": None, "kappa": None,
           "pairwise": [], "disagreements": []}
    if len(label_sets) < 2:
        out["measure"] = "NOT_APPLICABLE (one reviewer)"
        return out
    for i in range(len(label_sets)):
        for j in range(i + 1, len(label_sets)):
            a, b = label_sets[i], label_sets[j]
            out["pairwise"].append({"a": a["reviewer"], "b": b["reviewer"],
                                    "cohen_kappa": cohen_kappa([a["labels"][c] for c in common], [b["labels"][c] for c in common]),
                                    "raw_agreement": round(sum(a["labels"][c] == b["labels"][c] for c in common) / len(common), 4)
                                    if common else None})
    if len(label_sets) == 2:
        out["measure"], out["kappa"] = "COHEN_KAPPA", out["pairwise"][0]["cohen_kappa"]
    else:
        out["measure"] = "FLEISS_KAPPA"
        out["kappa"] = fleiss_kappa([Counter(s["labels"][c] for s in label_sets) for c in common])
    out["disagreements"] = [{"case": c, "labels": {s["reviewer"]: s["labels"][c] for s in label_sets}}
                            for c in common if len({s["labels"][c] for s in label_sets}) > 1]
    return out


def per_class_agreement(label_sets):
    """For each label: how many cases at least one reviewer gave it, and on how many of those all reviewers agreed
    (specific agreement). Only cases labelled by every reviewer count."""
    if len(label_sets) < 2:
        return {}
    common = sorted(set.intersection(*(set(s["labels"]) for s in label_sets)))
    out = {}
    for cls in LABELS:
        used = [c for c in common if any(s["labels"][c] == cls for s in label_sets)]
        agreed = [c for c in used if all(s["labels"][c] == cls for s in label_sets)]
        if used:
            out[cls] = {"cases_with_label": len(used), "all_agreed": len(agreed),
                        "specific_agreement": round(len(agreed) / len(used), 4)}
    return out


def disagreement_matrix(label_sets):
    """Pairwise label-by-label counts between the first two reviewers (rows = reviewer A, columns = reviewer B)."""
    if len(label_sets) < 2:
        return None
    a, b = label_sets[0], label_sets[1]
    common = sorted(set(a["labels"]) & set(b["labels"]))
    m = {x: {y: 0 for y in LABELS} for x in LABELS}
    for c in common:
        m[a["labels"][c]][b["labels"][c]] += 1
    return {"rows": a["reviewer"], "columns": b["reviewer"],
            "matrix": {x: {y: n for y, n in row.items() if n} for x, row in m.items() if any(row.values())}}


# ------------------------------------------------------------------ adjudication + gold

def build_gold(bench, label_sets, adjudication=None):
    """
    Predefined adjudication process:
      UNANIMOUS    every reviewer who labelled the case gave the same label
      ADJUDICATED  reviewers disagreed and a named human adjudicator chose one of THEIR labels (or AMBIGUOUS)
      UNRESOLVED   reviewers disagreed and no valid adjudication exists -> excluded from gold (listed)
      UNLABELLED   no reviewer labelled the case -> excluded (listed)
    """
    adjudication = adjudication or {"adjudicator": None, "decisions": {}}
    rows = []
    for c in bench:
        cid = c["benchmark_id"]
        given = {s["reviewer"]: s["labels"][cid] for s in label_sets if s["labels"].get(cid)}
        evidence = c.get("evidence_span")
        if not given:
            rows.append({"case_id": cid, "gold": None, "adjudication_status": "UNLABELLED", "reviewer_labels": {}, "evidence": evidence})
            continue
        if len(set(given.values())) == 1:
            rows.append({"case_id": cid, "gold": next(iter(given.values())), "adjudication_status": "UNANIMOUS",
                         "reviewer_labels": given, "evidence": evidence})
            continue
        choice = adjudication["decisions"].get(cid)
        if choice and (choice in given.values() or choice == "AMBIGUOUS"):
            rows.append({"case_id": cid, "gold": choice, "adjudication_status": "ADJUDICATED", "reviewer_labels": given,
                         "adjudicator": adjudication["adjudicator"], "evidence": evidence})
        else:
            rows.append({"case_id": cid, "gold": None, "adjudication_status": "UNRESOLVED", "reviewer_labels": given,
                         "adjudicator_choice_rejected": choice, "evidence": evidence})
    return rows


# ------------------------------------------------------------------ metrics

def _prf(tp, pp, gp):
    p = tp / pp if pp else None
    r = tp / gp if gp else None
    f = (2 * p * r / (p + r)) if p and r else (0.0 if (p is not None and r is not None) else None)
    return p, r, f


def critical_errors(case, gold, pred, findings):
    tags = set(case.get("tags") or [])
    left = (case.get("left") or "")
    errs = []
    if pred == "SAME_CONCEPT" and gold != "SAME_CONCEPT":
        errs.append("FALSE_SAME_CONCEPT")
    if pred == "PARENT" and gold != "PARENT":
        errs.append("FALSE_PARENT")
    if pred == "CHILD" and gold != "CHILD":
        errs.append("FALSE_CHILD")
    if pred == "RELATED" and gold not in ("RELATED", "PARTIAL_OVERLAP"):
        errs.append("FALSE_RELATED")
    if gold == "SAME_CONCEPT" and pred != "SAME_CONCEPT":
        errs.append("MISSED_SAME_CONCEPT")
    if {gold, pred} == {"PARENT", "CHILD"}:
        errs.append("WRONG_HIERARCHY_DIRECTION")
    wrong = pred != gold and pred in DEFINITE  # errors of commission only; an abstention is not a sense error
    if wrong and "lexical_collision" in tags and pred in ("SAME_CONCEPT", "PARENT", "CHILD"):
        errs.append("LEXICAL_COLLISION")
    if wrong and case.get("kind") == "ALIAS_SENSE":
        errs.append("ALIAS_SENSE_ERROR")
    if wrong and ("acronym" in tags or "abbreviation" in tags or (left.isupper() and 1 < len(left) <= 6)):
        errs.append("ACRONYM_SENSE_ERROR")
    if gold in ("AMBIGUOUS", "INSUFFICIENT_EVIDENCE") and pred in DEFINITE:
        errs.append("INSUFFICIENT_CONTEXT_ERROR")
    if pred in DEFINITE and any(f.split(":")[0] in HALLUCINATION_FINDINGS for f in (findings or [])):
        errs.append("UNSUPPORTED_TAXONOMY_EVIDENCE")
    return errs


SEVERE = ("FALSE_SAME_CONCEPT", "WRONG_HIERARCHY_DIRECTION", "UNSUPPORTED_TAXONOMY_EVIDENCE", "FALSE_PARENT", "FALSE_CHILD")


def evaluate_system(cases, gold, preds, findings=None):
    """cases: benchmark cases; gold: {case: label}; preds: {case: label or None (no prediction = abstain)}."""
    ids = [c["benchmark_id"] for c in cases if gold.get(c["benchmark_id"])]
    by_id = {c["benchmark_id"]: c for c in cases}
    pairs = [(gold[i], preds.get(i)) for i in ids]
    n = len(pairs)
    confusion = {g: {p: 0 for p in LABELS + ("NO_PREDICTION",)} for g in LABELS}
    for g, p in pairs:
        confusion[g][p or "NO_PREDICTION"] += 1
    per = {}
    for cls in LABELS:
        tp = sum(1 for g, p in pairs if g == cls and p == cls)
        pp = sum(1 for _, p in pairs if p == cls)
        gp = sum(1 for g, _ in pairs if g == cls)
        p, r, f = _prf(tp, pp, gp)
        per[cls] = {"precision": None if p is None else round(p, 4), "recall": None if r is None else round(r, 4),
                    "f1": None if f is None else round(f, 4), "support": gp, "predicted": pp}
    present = [c for c in LABELS if per[c]["support"] > 0]
    def macro(k):
        vals = [per[c][k] if per[c][k] is not None else 0.0 for c in present]
        return round(sum(vals) / len(vals), 4) if vals else None
    errors = Counter()
    per_case = []
    for i in ids:
        g, p = gold[i], preds.get(i)
        errs = critical_errors(by_id[i], g, p, (findings or {}).get(i))
        errors.update(errs)
        per_case.append({"case_id": i, "kind": by_id[i].get("kind"), "left": by_id[i].get("left"),
                         "right": by_id[i].get("right"), "gold": g, "prediction": p, "correct": g == p, "critical_errors": errs})
    severe_cases = sum(1 for r in per_case if any(e in SEVERE for e in r["critical_errors"]))
    definite = [(g, p) for g, p in pairs if p in DEFINITE]
    return {"cases": n, "predicted": sum(1 for _, p in pairs if p), "abstained": sum(1 for _, p in pairs if not p),
            "definite_predictions": len(definite),
            "non_definite_predictions": sum(1 for _, p in pairs if p and p not in DEFINITE),
            "precision_on_definite": round(sum(g == p for g, p in definite) / len(definite), 4) if definite else None,
            "accuracy": round(sum(g == p for g, p in pairs) / n, 4) if n else None,
            "macro_precision": macro("precision"), "macro_recall": macro("recall"), "macro_f1": macro("f1"),
            "per_class": per, "confusion_matrix": confusion, "critical_errors": dict(errors),
            "critical_error_rate": round(severe_cases / n, 4) if n else None, "per_case": per_case}


def contingency(per_case_a, per_case_b):
    a = {r["case_id"]: r["correct"] for r in per_case_a}
    b = {r["case_id"]: r["correct"] for r in per_case_b}
    common = sorted(set(a) & set(b))
    t = Counter((a[i], b[i]) for i in common)
    return {"both_correct": t[(True, True)], "baseline_correct_model_incorrect": t[(True, False)],
            "baseline_incorrect_model_correct": t[(False, True)], "both_incorrect": t[(False, False)],
            "cases_baseline_correct_model_incorrect": [i for i in common if a[i] and not b[i]],
            "cases_baseline_incorrect_model_correct": [i for i in common if not a[i] and b[i]]}


# ------------------------------------------------------------------ gate v2

def apply_gate(gate, gold_rows, reviewers_agreement, system_result, label_sets):
    """Every check with its value and threshold; promotable classes only when the whole gate passes."""
    gold_cases = sum(1 for r in gold_rows if r["gold"])
    c = gate["criteria"]
    checks = {}

    def check(name, value, ok, threshold):
        checks[name] = {"value": value, "threshold": threshold, "pass": bool(ok)}
    check("independent_reviewers", len(label_sets), len(label_sets) >= c["min_independent_reviewers"], c["min_independent_reviewers"])
    check("gold_cases", gold_cases, gold_cases >= c["min_gold_cases"], c["min_gold_cases"])
    k = reviewers_agreement.get("kappa")
    if len(label_sets) >= 2:
        check("inter_rater_kappa", k, k is not None and k >= c["min_kappa_when_two_or_more_reviewers"],
              c["min_kappa_when_two_or_more_reviewers"])
    s = system_result
    check("accuracy", s["accuracy"], (s["accuracy"] or 0) >= c["min_accuracy"], c["min_accuracy"])
    check("macro_f1", s["macro_f1"], (s["macro_f1"] or 0) >= c["min_macro_f1"], c["min_macro_f1"])
    e = s["critical_errors"]
    check("false_same_concept", e.get("FALSE_SAME_CONCEPT", 0), e.get("FALSE_SAME_CONCEPT", 0) <= c["max_false_same_concept"], c["max_false_same_concept"])
    check("wrong_hierarchy_direction", e.get("WRONG_HIERARCHY_DIRECTION", 0),
          e.get("WRONG_HIERARCHY_DIRECTION", 0) <= c["max_wrong_hierarchy_direction"], c["max_wrong_hierarchy_direction"])
    fh = e.get("FALSE_PARENT", 0) + e.get("FALSE_CHILD", 0)
    check("false_parent_or_child", fh, fh <= c["max_false_parent_or_child"], c["max_false_parent_or_child"])
    check("unsupported_taxonomy_evidence", e.get("UNSUPPORTED_TAXONOMY_EVIDENCE", 0),
          e.get("UNSUPPORTED_TAXONOMY_EVIDENCE", 0) <= c["max_unsupported_taxonomy_evidence"], c["max_unsupported_taxonomy_evidence"])
    check("lexical_collision", e.get("LEXICAL_COLLISION", 0), e.get("LEXICAL_COLLISION", 0) <= c["max_lexical_collision"], c["max_lexical_collision"])
    passed = all(v["pass"] for v in checks.values())
    promotable = []
    if passed:
        for cls in gate["promotable_classes"]:
            pc = s["per_class"][cls]
            if pc["precision"] is not None and pc["predicted"] >= c["min_predictions_per_promoted_class"] \
                    and pc["precision"] >= c["min_precision_per_promoted_class"]:
                promotable.append(cls)
    return {"passed": passed, "checks": checks, "promotable_classes": promotable,
            "mode": "PROMOTE_VALIDATED_CLASSES" if passed and promotable else "SAFE_MODE"}


def pending_status(bench_sha, gate, label_sets):
    return {"status": "PENDING_INDEPENDENT_LABELS", "benchmark_sha256": bench_sha, "independent_reviewers": len(label_sets),
            "gate_version": gate.get("version"), "gate_declared_at": gate.get("declared_at"),
            "mode": "SAFE_MODE",
            "reason": "no independent human labels exist for the frozen benchmark; model accuracy is not claimed",
            "next_action": "an independent reviewer fills labelling_sheet.csv; then benchmark_labelling.py ingest / gold / evaluate"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_label_sets(directory, bench_sha):
    sets = []
    for p in sorted(directory.glob("labels_*.json")):
        if p.name.endswith("_comparison.json"):
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        if not (doc.get("independent") and doc.get("model_blind")) or doc.get("benchmark_sha256") != bench_sha:
            continue
        sets.append({"reviewer": doc["reviewer"], "file": p.name,
                     "labels": {r["benchmark_id"]: r["label"] for r in doc["labels"] if r.get("label")}})
    return sets


def group_findings(preds):
    return {p["benchmark_id"]: (p.get("v3_validated_state") or [None, []])[1] for p in preds}


def by_kind(per_case):
    out = defaultdict(lambda: {"cases": 0, "correct": 0})
    for r in per_case:
        out[r["kind"]]["cases"] += 1
        out[r["kind"]]["correct"] += int(r["correct"])
    return {k: {**v, "accuracy": round(v["correct"] / v["cases"], 4)} for k, v in sorted(out.items())}
