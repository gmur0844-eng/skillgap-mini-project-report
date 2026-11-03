"""
Report what the engine does with the semantic hard cases (data/evaluation/semantic_hard_cases_v2.json).

For each pair (LEFT, RIGHT) it records, using only production mechanisms:
  * the ESCO mapping of each side (full classification, same mapper as the pipeline)
  * whether the label evidence rule holds the side back (context-dependent single word)
  * the coverage relation LEFT would get inside the text RIGHT (DIRECT / PARTIAL / RELATED / INCIDENTAL)
  * CONFLATED = both sides map to the same ESCO concept while the expected relationship is not SAME_CONCEPT
The 'expected' values are transcribed from the specification, not human labels: the output states
behaviour, not accuracy.

Usage: python3 scripts/evaluation/hard_case_report.py [--out data/evaluation/results/hard_cases_v2.json]
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine import esco_full as ef  # noqa: E402
from app.knowledge_engine import industry as ind  # noqa: E402
from app.knowledge_engine import intelligence as intel  # noqa: E402
from app.knowledge_engine.config import load_config  # noqa: E402
from app.knowledge_engine.semantic_backend import get_backend  # noqa: E402
from app.pipelines.preprocessing.skill_normalization import normalize_skill_text as norm  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data/evaluation/results/hard_cases_v2.json"))
    args = ap.parse_args()
    cfg = load_config()
    manifest = json.loads((ROOT / "data/metadata/curriculum_sources.json").read_text())
    full = next(t for t in manifest["taxonomy_sources"] if t["kind"] == "esco_full")
    tables, members = ef.read_classification(ROOT / full["path"])
    store, _ = ef.build_store(tables, members)
    vocab, _ = ef.skill_vocabulary(store)
    _, label_index = ind.build_vocabulary(vocab)
    cases = json.loads((ROOT / "data/evaluation/semantic_hard_cases_v2.json").read_text())["cases"]
    surfaces = [{"normalized_text": norm(x), "raw_mention": x, "method": "exact_label"} for c in cases for x in (c["left"], c["right"])]
    maps = ind.map_skills(surfaces, vocab, label_index, lambda: get_backend(cfg["semantic_backend"])[0], cfg["industry"])
    rows = []
    for c in cases:
        l, r = maps[norm(c["left"])], maps[norm(c["right"])]
        m = re.search(r"(?<![A-Za-z0-9])" + re.escape(c["left"]) + r"(?![A-Za-z0-9])", c["right"], re.IGNORECASE)
        relation = intel.mention_relation(c["right"], m.span(), cfg["intelligence"]["coverage"]["max_item_words"]) if m else None
        conflated = bool(l["esco_uri"] and l["esco_uri"] == r["esco_uri"] and c["expected"] != "SAME_CONCEPT")
        rows.append({**c, "left_esco": {k: l[k] for k in ("status", "esco_pref_label", "mapping_method", "reason")},
                     "right_esco": {k: r[k] for k in ("status", "esco_pref_label", "mapping_method", "reason")},
                     "left_inside_right_relation": relation, "conflated_by_taxonomy": conflated,
                     "same_esco_concept": bool(l["esco_uri"] and l["esco_uri"] == r["esco_uri"])})
    out = {"label_source": "SPECIFICATION_TRANSCRIBED_BY_ASSISTANT (not human labels)", "cases": rows,
           "summary": {"cases": len(rows), "conflated_by_taxonomy": sum(r["conflated_by_taxonomy"] for r in rows),
                       "left_held_back_by_label_evidence_rule": sum(r["left_esco"]["status"] == "INSUFFICIENT_EVIDENCE" for r in rows),
                       "left_inside_right_relation": {k: sum(1 for r in rows if r["left_inside_right_relation"] == k)
                                                      for k in ("DIRECT", "PARTIAL", "RELATED", "INCIDENTAL", None)}}}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out["summary"], indent=1))
    for r in rows:
        print(f"{r['left']:>8} | {r['right']:<30} exp={r['expected']:<13} L={r['left_esco']['status']:<22} "
              f"R={r['right_esco']['status']:<22} rel={r['left_inside_right_relation']} conflated={r['conflated_by_taxonomy']}")


if __name__ == "__main__":
    main()
