"""Experimental skill-qualification audit of an existing run (default: the published release).

Builds on scripts/analysis/relevance_audit.py (boilerplate + job relevance) and qualifies every skill mention the
release extracted from job postings. Writes only to data/experiments/skill_qualification/<run_id>/; the run, its
demand, gaps and recommendations are not touched.

    python3 scripts/analysis/skill_qualification_audit.py [--run c066b227857f9eaf]
    python3 scripts/analysis/skill_qualification_audit.py --freeze-benchmark   # (re)build the benchmark sample
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts/analysis"))

import relevance_audit as ra  # noqa: E402
from app.knowledge_engine import industry  # noqa: E402
from app.knowledge_engine import relevance as rel  # noqa: E402
from app.knowledge_engine import skill_qualification as sq  # noqa: E402

TRACE = ("make decisions", "reproductive health", "social media management", "help customers", "financial statements",
         "machine learning", "SQL", "docker", "kubernetes", "cloud technologies", "lead others", "communication",
         "Python (computer programming)", "Java (computer programming)")
BENCH_DIR = REPO / "data/evaluation/skill_qualification_benchmark_v1"
HARD = ("make decisions", "decision making", "reproductive health", "help customers", "financial statements",
        "linkedin", "machine learning", "sql", "docker", "kubernetes", "aws", "leadership", "communication",
        "python", "java", "lead a team", "customer service", "meet deadlines", "project management", "instagram")


def qualify_run(d, a):
    store_skills = d["store"]["skills"]
    by = {p["posting_uid"]: p for p in d["postings"]}
    maps = {}
    for line in (d["run"] / "industry/esco_mappings.jsonl").read_text().splitlines():
        if line.strip():
            m = json.loads(line)
            maps[m["normalized_label"]] = m
    jobs = [m for m in d["skill_mentions"] if m.get("source_type") == "job_posting" and m["source_uid"] in by]
    # per sentence: the concepts (release key or single candidate) of every mention, for sibling evidence
    sent = defaultdict(set)
    for m in jobs:
        text = by[m["source_uid"]]["clean_description"]
        s = sq.sentence_of(text, tuple(ra.lit(m["span"])))
        cands = ra.lit((maps.get(m["normalized_text"]) or {}).get("candidates")) or []
        uri = m["skill_key"] if m["skill_key"].startswith("http") else (cands[0]["uri"] if len(cands) == 1 else None)
        sent[(m["source_uid"], s)].add(uri)
    near = a["near"]
    out = []
    for m in sorted(jobs, key=lambda x: (x["source_uid"], x["mention_uid"])):
        text = by[m["source_uid"]]["clean_description"]
        span = tuple(ra.lit(m["span"]))
        kind = rel.segment_state(a["boiler"][m["source_uid"]], span)
        s = sq.sentence_of(text, span)
        q = sq.qualify(m, maps.get(m["normalized_text"]), store_skills, text, kind, a["profile"], near,
                       sent[(m["source_uid"], s)])
        q["job_relevance"] = a["jobs"][m["source_uid"]]["relevance"]
        q["posting_eligible"] = m["source_uid"] in a["eligible"]
        q["job_title"] = by[m["source_uid"]].get("job_title")
        q["company"] = by[m["source_uid"]].get("company_name")
        out.append(q)
    return out


def skills_table(d, a, quals):
    company = {p["posting_uid"]: p.get("company_key") for p in d["postings"]}
    state = {u: j["relevance"] for u, j in a["jobs"].items()}
    reuse = {u: s.get("reuse_level") for u, s in d["store"]["skills"].items()}
    by_skill = defaultdict(list)
    for q in quals:
        k = q["concept"] or q["release_concept"]
        by_skill[k].append(q)
    rows = {}
    keys = set(by_skill) | set(d["demand"])
    for k in keys:
        qs = by_skill.get(k, [])
        cur = set(ra.lit((d["demand"].get(k) or {}).get("posting_uids")) or [])
        job_text = {q["posting_uid"] for q in qs if q["decision"] in sq.DEMAND_ELIGIBLE}
        new = {u for u in job_text if u in a["eligible"]}
        skill_rel = rel.skill_relevance(k, a["profile"], reuse, job_text, state)
        decision = sq.skill_decision([q["decision"] for q in qs], skill_rel)
        label = ((d["demand"].get(k) or {}).get("skill_label") or (d["store"]["skills"].get(k) or {}).get("pref_label")
                 or (qs[0]["normalized_phrase"] if qs else k))
        rows[k] = {
            "skill_key": k, "skill_label": label, "skill_decision": decision,
            "decisions": dict(Counter(q["decision"] for q in qs)),
            "in_release_demand": k in d["demand"],
            "release": {"postings": len(cur), "companies": len({company[u] for u in cur}),
                        "support_state": (d["demand"].get(k) or {}).get("support_state", "NOT_IN_DEMAND")},
            "new": {"postings": len(new), "companies": len({company[u] for u in new}),
                    "support_state": industry.support_state(len(new), len({company[u] for u in new}), d["cfg"])},
            "gap_eligible": decision in sq.GAP_ELIGIBLE,
            "release_gap": (d["gaps"].get(k) or {}).get("classification"),
            "release_gap_v2": (d["gaps_v2"].get(k) or {}).get("classification_v2"),
        }
    return rows


def gap_change(r):
    g = r["release_gap"]
    if r["in_release_demand"] and not r["gap_eligible"]:
        return f"{g} -> NOT_A_GAP_CANDIDATE ({r['skill_decision']})"
    if not r["in_release_demand"] and r["new"]["support_state"] in ("SUPPORTED", "HIGH_SUPPORT") and r["gap_eligible"]:
        return "NEW_DEMAND -> needs curriculum coverage measurement before a gap can be classified"
    if r["in_release_demand"] and r["new"]["support_state"] != r["release"]["support_state"]:
        return f"{g} (support {r['release']['support_state']} -> {r['new']['support_state']}; re-classification pending)"
    return "unchanged"


def _kind(change):
    if "NOT_A_GAP_CANDIDATE" in change:
        return "release skill no longer a gap candidate"
    if change.startswith("NEW_DEMAND"):
        return "new supported skill, coverage to be measured"
    return "support state changed, gap re-classification pending"


# ------------------------------------------------------------------------------------------------ benchmark

def freeze_benchmark(quals, seed=20261008, n_random=120):
    """A frozen, stratified sample of real extracted mentions: every hard-case phrase (up to 6 each, from different
    postings), plus a random sample. Stored WITHOUT system decisions so labels can be written blind."""
    rng = random.Random(seed)
    pool = [q for q in quals]
    chosen, seen = [], set()
    by_phrase = defaultdict(list)
    for q in pool:
        by_phrase[(q["normalized_phrase"] or "").lower()].append(q)
    for h in HARD:
        items = sorted(by_phrase.get(h, []), key=lambda q: q["mention_uid"])
        rng.shuffle(items)
        posts = set()
        for q in items:
            if q["posting_uid"] in posts:
                continue
            posts.add(q["posting_uid"])
            chosen.append(q)
            seen.add(q["mention_uid"])
            if len(posts) == 6:
                break
    rest = sorted((q for q in pool if q["mention_uid"] not in seen), key=lambda q: q["mention_uid"])
    chosen += rng.sample(rest, n_random)
    items = [{"item_id": f"sq{i:03d}", "mention_uid": q["mention_uid"], "posting_uid": q["posting_uid"],
              "job_title": q["job_title"], "company": q["company"], "phrase": q["raw_phrase"],
              "normalized_phrase": q["normalized_phrase"], "sentence": q["sentence"],
              "stratum": "hard_case" if (q["normalized_phrase"] or "").lower() in HARD else "random"}
             for i, q in enumerate(chosen)]
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(x, sort_keys=True) + "\n" for x in items)
    (BENCH_DIR / "benchmark.jsonl").write_text(body)
    manifest = {"name": "skill_qualification_benchmark_v1", "items": len(items), "seed": seed,
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
                "label_set": ["DEMAND_EVIDENCE", "NOT_DEMAND_EVIDENCE"],
                "label_question": "Does this phrase, in this sentence, state a skill or knowledge the job requires "
                                  "(evidence of industry demand)? Employer text, activities described without a "
                                  "requirement, and words not used as a skill are NOT_DEMAND_EVIDENCE.",
                "label_files": {"human": "labels_human.csv (empty until independent reviewers fill it)",
                                "assistant": "labels_assistant.jsonl (model-generated by the assistant that wrote "
                                             "the method; NOT independent, NOT human)"}}
    (BENCH_DIR / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    with open(BENCH_DIR / "labels_human.csv", "w") as fh:
        fh.write("item_id,reviewer,label,type,notes\n")
        for x in items:
            fh.write(f"{x['item_id']},,,,\n")
    return items


def evaluate(quals, label_file, source):
    labels = {}
    for line in Path(label_file).read_text().splitlines():
        if line.strip():
            x = json.loads(line)
            labels[x["item_id"]] = x
    items = [json.loads(l) for l in (BENCH_DIR / "benchmark.jsonl").read_text().splitlines() if l.strip()]
    by = {q["mention_uid"]: q for q in quals}
    tp = fp = fn = tn = 0
    per_stratum = defaultdict(Counter)
    confusion = Counter()
    rows = []
    for it in items:
        lab = labels.get(it["item_id"])
        if not lab:
            continue
        gold = lab["label"] == "DEMAND_EVIDENCE"
        q = by[it["mention_uid"]]
        pred = q["eligible_for_demand"]
        tp += gold and pred
        fp += (not gold) and pred
        fn += gold and not pred
        tn += (not gold) and not pred
        per_stratum[it["stratum"]][("TP" if gold and pred else "FP" if pred else "FN" if gold else "TN")] += 1
        confusion[(lab["label"], q["decision"])] += 1
        if gold != pred:
            rows.append({"item_id": it["item_id"], "phrase": it["phrase"], "sentence": it["sentence"][:200],
                         "label": lab["label"], "decision": q["decision"], "reason": q["reason"]})
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else None
    return {"label_source": source, "labelled_items": tp + fp + fn + tn,
            "positive_class": "DEMAND_EVIDENCE", "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(p, 3) if p is not None else None, "recall": round(r, 3) if r is not None else None,
            "f1": round(f, 3) if f is not None else None,
            "accuracy": round((tp + tn) / max(1, tp + fp + fn + tn), 3),
            "per_stratum": {k: dict(v) for k, v in per_stratum.items()},
            "decision_by_label": {f"{k[0]} | {k[1]}": v for k, v in sorted(confusion.items())},
            "disagreements": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=json.loads((REPO / "data/gold/knowledge/latest_run.json").read_text())["run_id"])
    ap.add_argument("--freeze-benchmark", action="store_true")
    args = ap.parse_args()
    d = ra.load(args.run)
    a = ra.audit(d)
    quals = qualify_run(d, a)
    if args.freeze_benchmark:
        items = freeze_benchmark(quals)
        print("benchmark frozen:", len(items), "items")
        return
    skills = skills_table(d, a, quals)
    out = REPO / "data/experiments/skill_qualification" / args.run
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "mention_qualification.jsonl", "w") as fh:
        for q in quals:
            fh.write(json.dumps(q, sort_keys=True) + "\n")
    with open(out / "skill_qualification.jsonl", "w") as fh:
        for k in sorted(skills):
            fh.write(json.dumps({**skills[k], "gap_change": gap_change(skills[k])}, sort_keys=True) + "\n")
    dem_rows = [r for r in skills.values() if r["in_release_demand"]]
    recs = []
    for rec in d["recommendations"]:
        r = skills.get(rec["skill_key"])
        if r:
            recs.append({"skill": r["skill_label"], "action": rec.get("action_type"), "skill_decision": r["skill_decision"],
                         "release_support": r["release"]["support_state"], "new_support": r["new"]["support_state"],
                         "still_a_basis": r["gap_eligible"] and r["new"]["support_state"] in ("SUPPORTED", "HIGH_SUPPORT")})
    sup = lambda rows, f: dict(Counter(f(r) for r in rows))
    summary = {
        "run_id": args.run, "method": sq.METHOD, "relevance_method": rel.METHOD,
        "mentions": len(quals), "mention_decisions": dict(Counter(q["decision"] for q in quals)),
        "mention_types": dict(Counter(q["type"] for q in quals)),
        "mention_confidence": dict(Counter(q["confidence"] for q in quals)),
        "resolved_by_context": sum(1 for q in quals if q["resolved_by"]),
        "skills_in_release_demand": len(dem_rows),
        "release_demand_skill_decisions": sup(dem_rows, lambda r: r["skill_decision"]),
        "release_support": sup(dem_rows, lambda r: r["release"]["support_state"]),
        "new_support_release_skills": sup(dem_rows, lambda r: r["new"]["support_state"]),
        "new_skills_entering_demand": sorted(
            (r["skill_label"], r["new"]["postings"], r["new"]["support_state"]) for r in skills.values()
            if not r["in_release_demand"] and r["new"]["support_state"] in ("SUPPORTED", "HIGH_SUPPORT")),
        "skills_leaving_supported": sorted(
            r["skill_label"] for r in dem_rows if r["release"]["support_state"] in ("SUPPORTED", "HIGH_SUPPORT")
            and r["new"]["support_state"] not in ("SUPPORTED", "HIGH_SUPPORT")),
        "gap_changes": dict(Counter(_kind(gap_change(r)) for r in skills.values() if gap_change(r) != "unchanged")),
        "release_gaps_no_longer_candidates": sorted(
            (r["skill_label"], r["release_gap"], r["skill_decision"]) for r in dem_rows
            if r["release_gap"] in ("MISSING", "PARTIAL", "GAP") and not r["gap_eligible"]),
        "recommendations": recs,
    }
    traces = {}
    for name in TRACE:
        k = next((k for k, r in sorted(skills.items(), key=lambda x: not x[0].startswith("http"))
                  if r["skill_label"].lower() == name.lower()), None)
        if k is None:
            continue
        qs = [q for q in quals if (q["concept"] or q["release_concept"]) == k]
        traces[name] = {**skills[k], "gap_change": gap_change(skills[k]),
                        "examples": [{x: q[x] for x in ("company", "job_title", "raw_phrase", "sentence", "text_kind",
                                                         "requirement_framing", "decision", "confidence", "reason",
                                                         "resolved_by", "job_relevance")}
                                     for q in sorted(qs, key=lambda q: q["mention_uid"])[:6]]}
    evals = {}
    for src, f in (("assistant (model-generated, not independent, not human)", BENCH_DIR / "labels_assistant.jsonl"),
                   ("human (independent reviewers)", BENCH_DIR / "labels_human.jsonl")):
        if f.exists():
            evals[src] = evaluate(quals, f, src)
    summary["evaluation"] = {k: {x: v[x] for x in v if x != "disagreements"} for k, v in evals.items()}
    summary["evaluation_note"] = ("No independent human labels exist yet; labels_human.csv is the empty template."
                                  if not (BENCH_DIR / "labels_human.jsonl").exists() else "")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    (out / "traces.json").write_text(json.dumps(traces, indent=2, sort_keys=True))
    (out / "evaluation.json").write_text(json.dumps(evals, indent=2, sort_keys=True))
    print(json.dumps({k: summary[k] for k in ("mentions", "mention_decisions", "release_demand_skill_decisions",
                                               "release_support", "new_support_release_skills",
                                               "new_skills_entering_demand", "skills_leaving_supported")}, indent=1))
    for k, v in summary["evaluation"].items():
        print(k, {x: v[x] for x in ("labelled_items", "precision", "recall", "f1", "accuracy")})
    print("written", out)


if __name__ == "__main__":
    main()
