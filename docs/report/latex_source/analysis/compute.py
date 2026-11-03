"""Recompute every figure used in the report from the staged project files (read-only)."""
import json, sys, itertools, re, copy
from collections import Counter, defaultdict
from pathlib import Path
EV = Path(sys.argv[1]); OUT = Path(sys.argv[2])
sys.path.insert(0, str(EV / "backend")); sys.path.insert(0, str(EV / "scripts/semantic"))
from app.knowledge_engine import semantic_responses as sr, semantic_v3 as v3
import score_against_reviewers as sar

PKG = EV / "data/evaluation/semantic_gold/computer-science-and-engineering/v1"
jl = lambda p: [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
bench = json.loads((EV / "data/evaluation/semantic_benchmark_v1/benchmark.json").read_text())
bmap = {b["benchmark_id"]: b for b in bench}
cid_of = {b["benchmark_id"]: b["candidate_id"] for b in bench}
cands = {c["candidate_id"]: c for c in json.loads((EV / "data/semantic_runs/qwen-270-v3/candidates.json").read_text())}
subset = json.loads((PKG / "subset.json").read_text())["case_ids"]
records, files = sr.load(PKG)
preds = {p["benchmark_id"]: p for p in jl(EV / "data/semantic_runs/qwen-270-v3/analysis/benchmark_predictions.jsonl")}
dec3 = {d["candidate_id"]: d for d in jl(EV / "data/semantic_runs/qwen-270-v3/out/decisions.jsonl")}
dec4 = {d["candidate_id"]: d for d in jl(EV / "data/semantic_runs/qwen-270-v4/out/decisions.jsonl")}
R = {}
R["files"] = [{k: f.get(k) for k in ("reviewer_id", "reviewer_source", "counts_as_independent_label")} for f in files]
R["subset_size"] = len(subset); R["benchmark_size"] = len(bench)
# reviewer labels per reviewer
lab = defaultdict(dict); status = Counter()
for r in records:
    status[(r["reviewer_id"], r["status"])] += 1
    if r["status"] == "COMPLETED":
        lab[r["reviewer_id"]][r["question_id"]] = r["relationship"]["code"]
R["status_counts"] = {f"{a}|{b}": n for (a, b), n in sorted(status.items())}
R["completed_per_reviewer"] = {k: len(v) for k, v in sorted(lab.items())}
R["label_dist"] = {k: dict(Counter(v.values())) for k, v in sorted(lab.items())}
def kappa(a, b, ids):
    ids = [i for i in ids if i in a and i in b]
    n = len(ids); 
    if not n: return None
    po = sum(a[i] == b[i] for i in ids) / n
    ca, cb = Counter(a[i] for i in ids), Counter(b[i] for i in ids)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n / n
    return {"n": n, "agree": sum(a[i] == b[i] for i in ids), "po": round(po, 4), "pe": round(pe, 4),
            "kappa": round((po - pe) / (1 - pe), 4) if pe < 1 else None}
R["pairwise"] = {f"{x}-{y}": kappa(lab[x], lab[y], subset) for x, y in itertools.combinations(sorted(lab), 2)}
agreed = {q: lab["R02"][q] for q in subset if q in lab["R02"] and q in lab["R03"] and lab["R02"][q] == lab["R03"][q]}
R["agreed_n"] = len(agreed); R["agreed_dist"] = dict(Counter(agreed.values()))
R["disagreements_R02_R03"] = [{"q": q, "R02": lab["R02"].get(q), "R03": lab["R03"].get(q), "left": bmap[q]["left_text"], "right": bmap[q]["right_concept"]} for q in subset if lab["R02"].get(q) != lab["R03"].get(q)]
# compare with the pkg code's comparison
rows = sr.compare(records, subset, "R02", "R03"); R["pkg_compare"] = dict(Counter(r["comparison"] for r in rows))
# dev labels (assistant) vs reviewers
R["assistant_vs_agreed"] = sum(bmap[q]["label"] == g for q, g in agreed.items())
ABST = ("AMBIGUOUS", "INSUFFICIENT_EVIDENCE")
systems = {}
for q, g in agreed.items():
    c = cid_of[q]
    v3v, f3 = sar.validated(dec3.get(c), cands[c]); v4v, f4 = sar.validated(dec4.get(c), cands[c])
    systems[q] = {"gold": g, "BASELINE": preds[q]["BASELINE"], "V3_RAW": dec3[c]["relationship"], "V3_VAL": v3v,
                  "V4_RAW": dec4[c]["relationship"], "V4_VAL": v4v, "f3": [x.split(':')[0] for x in f3], "f4": [x.split(':')[0] for x in f4],
                  "kind": bmap[q]["kind"], "left": bmap[q]["left_text"], "right": bmap[q]["right_concept"], "tags": bmap[q]["tags"],
                  "pred_file_v3_validated": preds[q]["V3_VALIDATED"]}
# v4 diagnostic: strip brackets from cited refs
def strip(d):
    d = copy.deepcopy(d)
    def fix(o):
        if isinstance(o, dict): return {k: (re.sub(r"^\[(.*)\]$", r"\1", v) if k == "ref" and isinstance(v, str) else fix(v)) for k, v in o.items()}
        if isinstance(o, list): return [fix(x) for x in o]
        return o
    return fix(d)
for q, s in systems.items():
    c = cid_of[q]; s["V4_VAL_STRIP"] = sar.validated(strip(dec4[c]), cands[c])[0]
R["consistency_pred_file"] = sum(s["V3_VAL"] == s["pred_file_v3_validated"] for s in systems.values())
def metrics(key):
    n = len(systems); ok = sum(s[key] == s["gold"] for s in systems.values())
    com = [s for s in systems.values() if s[key] not in ABST]
    cok = sum(s[key] == s["gold"] for s in com)
    return {"n": n, "correct": ok, "acc": round(ok / n, 4), "commits": len(com), "coverage": round(len(com) / n, 4),
            "abstain": n - len(com), "correct_when_committed": cok, "cond_acc": round(cok / len(com), 4) if com else None,
            "correct_abstentions": sum(s[key] == s["gold"] for s in systems.values() if s[key] in ABST),
            "dist": dict(Counter(s[key] for s in systems.values()))}
R["metrics"] = {k: metrics(k) for k in ("BASELINE", "V3_RAW", "V3_VAL", "V4_RAW", "V4_VAL", "V4_VAL_STRIP")}
classes = ["SAME_CONCEPT", "PARENT", "CHILD", "PARTIAL_OVERLAP", "RELATED", "UNRELATED", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE"]
def prf(key):
    out = {}
    for c in classes:
        tp = sum(s[key] == c and s["gold"] == c for s in systems.values())
        fp = sum(s[key] == c and s["gold"] != c for s in systems.values())
        fn = sum(s[key] != c and s["gold"] == c for s in systems.values())
        p = tp / (tp + fp) if tp + fp else None; r = tp / (tp + fn) if tp + fn else None
        f = 2 * p * r / (p + r) if p and r else (0.0 if (p is not None and r is not None) else None)
        out[c] = {"support": tp + fn, "pred": tp + fp, "tp": tp, "p": p and round(p, 3), "r": r and round(r, 3), "f1": f if f is None else round(f, 3)}
    present = [c for c in classes if out[c]["support"]]
    out["_macro_f1_over_reference_classes"] = round(sum((out[c]["f1"] or 0) for c in present) / len(present), 3)
    return out
R["prf"] = {k: prf(k) for k in ("V3_RAW", "V3_VAL")}
def confusion(key):
    return {f"{g}->{p}": n for (g, p), n in Counter((s["gold"], s[key]) for s in systems.values()).most_common()}
R["confusion"] = {k: confusion(k) for k in ("V3_RAW", "V3_VAL", "V4_RAW", "BASELINE")}
R["findings_cases_v3"] = dict(Counter(f for s in systems.values() for f in set(s["f3"])))
R["no_concept_right_raw"] = sum("NO_CONCEPT_EVIDENCE" in s["f3"] and s["V3_RAW"] == s["gold"] for s in systems.values())
R["raw_right_val_wrong_v3"] = [q for q, s in systems.items() if s["V3_RAW"] == s["gold"] and s["V3_VAL"] != s["gold"]]
R["raw_wrong_val_right_v3"] = [q for q, s in systems.items() if s["V3_RAW"] != s["gold"] and s["V3_VAL"] == s["gold"]]
R["kind_v3"] = {k: {"n": sum(s["kind"] == k for s in systems.values()), "raw": sum(s["kind"] == k and s["V3_RAW"] == s["gold"] for s in systems.values()),
                    "val": sum(s["kind"] == k and s["V3_VAL"] == s["gold"] for s in systems.values())} for k in sorted({s["kind"] for s in systems.values()})}
R["error_cases"] = {cat: [(q, s["left"], s["right"]) for q, s in systems.items() if (s["gold"], s["V3_RAW"]) == pair]
                    for cat, pair in (("narrower_as_same", ("CHILD", "SAME_CONCEPT")), ("overlap_as_same", ("PARTIAL_OVERLAP", "SAME_CONCEPT")), ("broader_as_related", ("PARENT", "RELATED")))}
R["v3_raw_same_concept_count"] = sum(s["V3_RAW"] == "SAME_CONCEPT" for s in systems.values())
R["v4_raw_same_concept_count"] = sum(s["V4_RAW"] == "SAME_CONCEPT" for s in systems.values())
R["systems"] = systems
OUT.write_text(json.dumps(R, indent=1, default=str))
