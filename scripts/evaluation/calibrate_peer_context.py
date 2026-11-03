#!/usr/bin/env python3
"""
Calibrate peers.course_context_min_similarity (peer_stage.py) on course pairs whose identity is known
WITHOUT using the peer benchmark itself:
  positive = a target course and a comparison course with EQUAL titles after normalisation
  negative = a target course and a comparison course whose titles share no content word
Course context = cosine of the two courses' TOPIC text (titles excluded, so a positive is not scored on the
title that labelled it). Declared rule (precision first): the LOWEST threshold whose false-positive rate on
the negatives is <= max_fpr. Youden's J optimum is reported next to it. Writes
artifacts/calibration/peer_course_context.json. Reads SILVER only; changes nothing.
"""
import argparse
import collections
import json
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
import numpy as np  # noqa: E402
from app.knowledge_engine.concepts import _content_words  # noqa: E402
from app.knowledge_engine.semantic_backend import get_backend  # noqa: E402
from app.pipelines.preprocessing.skill_normalization import normalize_skill_text as norm  # noqa: E402


def load(doc_id, sha):
    d = REPO / "data/silver/curricula" / doc_id / sha[:16]
    cs = {c["course_uid"]: c for c in map(json.loads, open(d / "courses.jsonl"))}
    ts = [t for t in map(json.loads, open(d / "topics.jsonl")) if t["noise_label"] == "TOPIC" and t["course_uid"] in cs]
    return cs, ts


def course_texts(cs, ts):
    g = collections.defaultdict(list)
    for t in ts:
        g[t["course_uid"]].append(t["clean_text"])
    u = sorted(g)
    return u, [" ; ".join(g[x]) for x in u]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-fpr", type=float, default=0.001)
    ap.add_argument("--out", default=str(REPO / "artifacts/calibration/peer_course_context.json"))
    a = ap.parse_args()
    man = json.load(open(REPO / "data/metadata/curriculum_sources.json"))
    target = next(d for d in man["documents"] if d["role"] == "TARGET")
    tc, tt = load(target["doc_id"], target["expected_sha256"])
    pairs = []
    for d in man["documents"]:
        if d["role"] not in ("REFERENCE", "PEER"):
            continue
        oc, ot = load(d["doc_id"], d["expected_sha256"])
        ua, ta = course_texts(tc, tt)
        ub, tb = course_texts(oc, ot)
        b = get_backend("tfidf")[0]
        b.fit(ta + tb)
        S = b.similarity(b.embed(ta), b.embed(tb))
        for i, x in enumerate(ua):
            for j, y in enumerate(ub):
                na, nb = norm(tc[x]["title"]), norm(oc[y]["title"])
                wa = {w.lower() for w in _content_words(tc[x]["title"])}
                wb = {w.lower() for w in _content_words(oc[y]["title"])}
                label = 1 if na and na == nb else (0 if not (wa & wb) else None)
                if label is not None:
                    pairs.append({"comparison_doc_id": d["doc_id"], "label": label, "similarity": round(float(S[i, j]), 4),
                                  "target_title": tc[x]["title"], "comparison_title": oc[y]["title"]})
    pos = [p for p in pairs if p["label"] == 1]
    neg = [p for p in pairs if p["label"] == 0]
    grid = []
    for th in np.round(np.arange(0.01, 0.61, 0.01), 2):
        tpr = sum(p["similarity"] >= th for p in pos) / len(pos)
        fpr = sum(p["similarity"] >= th for p in neg) / len(neg)
        grid.append({"threshold": float(th), "tpr": round(tpr, 4), "fpr": round(fpr, 5), "youden_j": round(tpr - fpr, 4)})
    chosen = next(g for g in grid if g["fpr"] <= a.max_fpr)
    youden = max(grid, key=lambda g: (g["youden_j"], -g["threshold"]))
    out = {"purpose": "calibrate peers.course_context_min_similarity on course pairs of known identity",
           "rule": f"lowest threshold with false-positive rate <= {a.max_fpr} (precision first)",
           "positives": len(pos), "negatives": len(neg), "chosen": chosen, "youden_optimum": youden,
           "grid": grid, "positive_pairs": pos,
           "limitations": "positives are only courses with equal titles (31 pairs); negatives only title-disjoint pairs; "
                          "the context measure is lexical (TF-IDF) over topic text"}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("positives", "negatives", "chosen", "youden_optimum")}))


if __name__ == "__main__":
    main()
