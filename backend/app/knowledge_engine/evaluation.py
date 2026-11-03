"""
Evaluation against labelled samples drawn from the REAL documents.

The labelled files live in data/evaluation/. Each declares who labelled it.
Labels written by the assistant are marked `labelled_by: "assistant"`,
`human_validated: false`: they are an independent reading of the source
text, NOT ground truth, and every metric computed from them is reported with
that caveat and its sample size. No metric is produced without a labelled
file.
"""
from collections import Counter, defaultdict

from app.knowledge_engine.mapping import _norm, _relationship


def classification_report(gold, pred, labels=None):
    labels = labels or sorted(set(gold) | set(pred))
    confusion = {g: {p: 0 for p in labels} for g in labels}
    for g, p in zip(gold, pred):
        confusion.setdefault(g, {q: 0 for q in labels})
        confusion[g][p] = confusion[g].get(p, 0) + 1
    per_class = {}
    for label in labels:
        tp = confusion.get(label, {}).get(label, 0)
        fp = sum(confusion[g].get(label, 0) for g in confusion if g != label)
        fn = sum(v for p, v in confusion.get(label, {}).items() if p != label)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (2 * precision * recall / (precision + recall)) if precision and recall else (0.0 if (precision == 0 or recall == 0) else None)
        per_class[label] = {"precision": _r(precision), "recall": _r(recall), "f1": _r(f1), "support": tp + fn}
    scored = [v["f1"] for v in per_class.values() if v["f1"] is not None and v["support"]]
    return {"n": len(gold), "accuracy": _r(sum(g == p for g, p in zip(gold, pred)) / len(gold)) if gold else None,
            "macro_f1": _r(sum(scored) / len(scored)) if scored else None, "per_class": per_class, "confusion": confusion}


def _r(x):
    return round(x, 4) if isinstance(x, float) else x


def predict_pair(target_text, reference_text, backend, min_similarity):
    a, b = backend.embed([target_text]), backend.embed([reference_text])
    sim = float(backend.similarity(a, b)[0][0])
    if _norm(target_text) == _norm(reference_text):
        return "SAME_CONCEPT", sim
    if sim < min_similarity:
        return "UNRELATED", sim
    return _relationship(target_text, reference_text, sim)[0], sim


def evaluate_semantic_benchmark(benchmark, backend, min_similarity):
    pairs = benchmark["pairs"]
    gold, pred, rows = [], [], []
    for pair in pairs:
        label, sim = predict_pair(pair["target_text"], pair["reference_text"], backend, min_similarity)
        gold.append(pair["label"])
        pred.append(label)
        rows.append({**pair, "predicted": label, "similarity_score": round(sim, 4), "correct": label == pair["label"]})
    binary_gold = ["LINKED" if g != "UNRELATED" else "UNRELATED" for g in gold]
    binary_pred = ["LINKED" if p != "UNRELATED" else "UNRELATED" for p in pred]
    return {"labelled_by": benchmark.get("labelled_by"), "human_validated": benchmark.get("human_validated", False),
            "sample_size": len(pairs), "relationship_level": classification_report(gold, pred),
            "linked_vs_unrelated": classification_report(binary_gold, binary_pred, ["LINKED", "UNRELATED"]),
            "rows": rows, "caveat": benchmark.get("caveat")}


def evaluate_topic_sample(sample, topics_by_uid):
    """sample items: {"topic_uid", "label": "TOPIC" | "NOISE"} labelled from the raw text."""
    gold, pred, missing = [], [], 0
    for item in sample["items"]:
        topic = topics_by_uid.get(item["topic_uid"])
        if topic is None:
            missing += 1
            continue
        gold.append(item["label"])
        pred.append("TOPIC" if topic["noise_label"] == "TOPIC" else "NOISE")
    report = classification_report(gold, pred, ["TOPIC", "NOISE"])
    kept = [g for g, p in zip(gold, pred) if p == "TOPIC"]
    return {"labelled_by": sample.get("labelled_by"), "human_validated": sample.get("human_validated", False),
            "sample_size": len(gold), "items_not_found_in_this_run": missing, "report": report,
            "noise_leakage_in_kept_topics": _r(kept.count("NOISE") / len(kept)) if kept else None,
            "caveat": sample.get("caveat")}


def evaluate_golden_pages(golden, topics):
    """golden pages: {"doc_id", "page", "extra_pages"?, "course_code"?, "expected_topics": [...]}.
    A topic counts only if it is on one of the listed pages AND (when the page
    names a course_code) is attributed to that course -- so misattribution is
    measured, not just presence. Matching is normalized containment in either
    direction."""
    results = []
    by_page = defaultdict(list)
    for t in topics:
        if t["noise_label"] == "TOPIC":
            by_page[(t["doc_id"], t["page_number"])].append(t)
    for page in golden["pages"]:
        page_numbers = [page["page"], *page.get("extra_pages", [])]
        on_pages = [t for p in page_numbers for t in by_page.get((page["doc_id"], p), [])]
        code = page.get("course_code")
        extracted = [t["clean_text"] for t in on_pages if code is None or t.get("course_code") == code]
        misattributed = sum(1 for t in on_pages if code is not None and t.get("course_code") != code)
        norm_extracted = [_norm(x) for x in extracted]
        expected = [_norm(x) for x in page["expected_topics"]]

        def found(e):
            return any(e in x or x in e for x in norm_extracted if x)  # noqa: B023 -- called within this iteration
        hit = sum(1 for e in expected if found(e))
        matched_extracted = sum(1 for x in norm_extracted if any(e in x or x in e for e in expected))
        results.append({"fixture_id": page.get("fixture_id"), "doc_id": page["doc_id"], "pages": page_numbers,
                        "course_code": code, "expected": len(expected), "extracted_topics": len(extracted),
                        "topics_on_pages_attributed_to_other_courses": misattributed,
                        "recall": _r(hit / len(expected)) if expected else None,
                        "matched_fraction_of_extracted_lower_bound": _r(matched_extracted / len(extracted)) if extracted else None,
                        "missed": [page["expected_topics"][i] for i, e in enumerate(expected) if not found(e)]})
    return {"labelled_by": golden.get("labelled_by"), "human_validated": golden.get("human_validated", False),
            "pages": results, "caveat": golden.get("caveat")}


def confidence_distribution(mappings):
    buckets = Counter()
    for m in mappings:
        s = m.get("similarity_score")
        if s is None:
            buckets["none"] += 1
        else:
            lo = min(int(s * 10), 9) / 10
            buckets[f"{lo:.1f}-{lo + 0.1:.1f}"] += 1
    return dict(sorted(buckets.items()))


def evaluate_industry_sample(sample, mentions_by_uid, skills):
    """
    sample items: {"mention_uid", "is_skill_requirement": bool, "mapped_sense_correct": bool | None}.
    'counted' = the mention enters skill demand (analytics-eligible skill AND mention_role SKILL).
    Reports precision / recall / F1 of 'counted' against is_skill_requirement, how many
    genuine skill mentions the rules excluded (and why), and the sense accuracy of the
    ESCO concept / curated token for counted mentions.
    """
    gold, pred, missing, excluded_true = [], [], 0, Counter()
    sense = []
    for item in sample["items"]:
        m = mentions_by_uid.get(item["mention_uid"])
        if m is None:
            missing += 1
            continue
        eligible = skills.get(m["skill_key"], {}).get("eligible_for_analytics", False)
        counted = bool(eligible and m["mention_role"] == "SKILL")
        gold.append("SKILL" if item["is_skill_requirement"] else "NOT_SKILL")
        pred.append("SKILL" if counted else "NOT_SKILL")
        if item["is_skill_requirement"] and not counted:
            excluded_true["QUALIFICATION_CONTEXT" if m["mention_role"] != "SKILL" else f"ESCO_STATUS_{m['esco_status']}"] += 1
        if counted and item.get("mapped_sense_correct") is not None:
            sense.append(item["mapped_sense_correct"])
    report = classification_report(gold, pred, ["SKILL", "NOT_SKILL"])
    return {"labelled_by": sample.get("labelled_by"), "human_validated": sample.get("human_validated", False),
            "sample_size": len(gold), "items_not_found_in_this_run": missing, "counted_as_demand_vs_label": report,
            "genuine_skill_mentions_excluded_by_rule": dict(excluded_true),
            "mapped_sense_accuracy_of_counted_mentions": {"n": len(sense), "correct": sum(sense),
                                                          "accuracy": _r(sum(sense) / len(sense)) if sense else None},
            "caveat": sample.get("caveat")}
