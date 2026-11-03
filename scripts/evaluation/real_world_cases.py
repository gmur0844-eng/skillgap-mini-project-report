"""
Ten real-world demonstrations, each selected from a GOLD run by a fixed, generic rule (no hand-picking by
name). Output: data/evaluation/results/real_world_cases.md (+ .json).

Usage: python3 scripts/evaluation/real_world_cases.py [--run-id ID]
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import knowledge_service as ks  # noqa: E402


def jl(p):
    return ks._jsonl(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id")
    args = ap.parse_args()
    run = ks.KnowledgeRun(args.run_id)
    ind, intel = run.dir / "industry", run.dir / "intelligence"
    topics = run.topics
    courses = run.courses
    cases = []

    def add(n, title, rule, evidence_class, body):
        cases.append({"case": n, "title": title, "selection_rule": rule, "evidence_class": evidence_class, **body})

    # 1 same concept, different wording
    import re
    words = lambda t: set(re.findall(r"[a-z0-9]+", (t or "").lower()))
    same = sorted((m for m in run.mappings if m["relationship"] == "SAME_CONCEPT"
                   and words(m["source_text"]) != words((m.get("evidence") or {}).get("reference_text"))),
                  key=lambda m: (-(m["similarity_score"] or 0), m["mapping_uid"]))
    if same:
        m = same[0]
        add(1, "Same concept with different wording", "SAME_CONCEPT topic mappings whose word sets differ; highest similarity",
            "MODEL_SUGGESTED (TF-IDF, uncalibrated)", {"target_topic": m["source_text"], "reference_topic": m["evidence"]["reference_text"],
                                                       "similarity_score": m["similarity_score"], "method": m["method"]})
    else:
        pm_all = jl(ind / "skill_mentions.jsonl")
        alias = sorted((m for m in pm_all if m["sense_state"] in ("ESTABLISHED", "ESTABLISHED_BY_CONTEXT")
                        and m.get("taxonomy_relationship") == "TAXONOMY_ALIAS_MATCH"),
                       key=lambda m: (m["normalized_text"], m["mention_uid"]))
        if alias:
            m = alias[0]
            sk = run.industry["skills"][m["skill_key"]]
            add(1, "Same concept with different wording",
                "no SAME_CONCEPT topic mapping differs in words; first established ESCO alias match in postings instead",
                "NORMALIZED (taxonomy alias, sense established)",
                {"text": m["raw_mention"], "esco_concept": sk.get("esco_pref_label") or sk["label"],
                 "sense_state": m["sense_state"], "sense_evidence": m.get("sense_evidence"),
                 "note": "all 53 SAME_CONCEPT curriculum mappings have identical word sets (spacing/quote differences only)"})
    # 2 parent / child
    h = jl(intel / "topic_hierarchy.jsonl")
    par = next((m for m in sorted(run.mappings, key=lambda m: m["mapping_uid"]) if m["relationship"] == "PARENT"), None)
    add(2, "Parent / child", "first explicit 'Head: items' subtopic group; first PARENT reference mapping", "EXTRACTED + MODEL_SUGGESTED",
        {"explicit_hierarchy": [{"parent": r["parent_text"], "child": r["child_text"], "page": r["page_number"],
                                 "source_line": r["source_line"]} for r in h if r["parent_node_uid"] == h[0]["parent_node_uid"]] if h else [],
         "reference_mapping_parent": par and {"target_topic": par["source_text"],
                                              "reference_topic": (par.get("evidence") or {}).get("reference_text"),
                                              "relationship": "PARENT (target broader than reference)"}})
    # 3 context-dependent word
    maps = jl(ind / "esco_mappings.jsonl")
    pm = jl(ind / "skill_mentions.jsonl")
    cnt = Counter(m["normalized_text"] for m in pm)
    dep = sorted((m for m in maps if (m.get("reason") or "").startswith("LABEL_CONTEXT_DEPENDENT")), key=lambda m: (-cnt[m["normalized_label"]], m["normalized_label"]))
    if dep:
        m = dep[0]
        ex = [x for x in pm if x["normalized_text"] == m["normalized_label"]][:3]
        add(3, "Context-dependent word", "most frequent posting surface held back by the label evidence rule", "INSUFFICIENT_EVIDENCE",
            {"surface": m["normalized_label"], "postings_with_text": cnt[m["normalized_label"]], "status": m["status"], "reason": m["reason"],
             "contexts": [x["context"].strip() for x in ex], "esco_candidates": [c.get("label") for c in m.get("candidates", [])][:3]})
    # 4 ESCO alias ambiguity
    al = Counter(m["normalized_text"] for m in pm if m["sense_state"] == "ALIAS_SENSE_REVIEW_REQUIRED")
    decisions = jl(intel / "semantic_decisions.jsonl")
    if al:
        surf = sorted(al.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        x = next(m for m in pm if m["normalized_text"] == surf and m["sense_state"] == "ALIAS_SENSE_REVIEW_REQUIRED")
        dec = next((dd for dd in decisions if dd["source_entity"] == x["mention_uid"]), None)
        add(4, "ESCO alias ambiguity", "surface with the most ALIAS_SENSE_REVIEW_REQUIRED posting mentions", "REVIEW_REQUIRED",
            {"surface": x["raw_mention"], "mentions_under_review": al[surf], "taxonomy_fact": x["sense_evidence"]["esco_evidence"],
             "context": x["context"].strip(), "question": x["sense_evidence"]["question"],
             "adjudication": dec and {k: dec[k] for k in ("relationship", "decision_state", "provider", "uncertainty")}})
    # 5 academic concept without ESCO match
    esco_topics = {m["source_uid"] for m in jl(ind / "curriculum_skill_mentions.jsonl") if m["esco_status"] in ("EXACT", "NORMALIZED")}
    no_esco = sorted((c for c in run.concepts.values() if not set(c["member_topic_uids"]) & esco_topics),
                     key=lambda c: (-c["support"], c["concept_uid"]))
    if no_esco:
        c = no_esco[0]
        add(5, "Academic concept without ESCO match", "highest-support concept none of whose topics has an ESCO-mapped mention",
            "DISCOVERED (concept) + ESCO_UNMAPPED", {"concept": c["name"], "support": c["support"],
                                                   "courses": sorted({courses[u]["course_code"] for u in c["course_uids"] if u in courses}),
                                                   "example_topics": [topics[t]["clean_text"] for t in c["member_topic_uids"][:4] if t in topics]})
    # 6/7 industry skill with / without ESCO match
    demand = jl(ind / "industry_demand.jsonl")
    skills = run.industry["skills"]
    for n, want, title in ((6, lambda s: s["esco_status"] == "EXACT", "Industry skill with ESCO match"),
                           (7, lambda s: s["esco_status"] == "UNMAPPED", "Industry skill without ESCO match")):
        rows = sorted((r for r in demand if want(skills[r["skill_key"]])), key=lambda r: (-r["posting_count"], r["skill_label"]))
        if rows:
            r = rows[0]
            s = skills[r["skill_key"]]
            mp = next((m for m in maps if m["skill_key"] == r["skill_key"]), {})
            add(n, title, "highest posting count among demand rows with that ESCO status", "FACT (counts) + REFERENCE_MAPPED / NORMALIZED",
                {"skill": s["label"], "esco_status": s["esco_status"], "esco_uri": s["esco_uri"], "posting_count": r["posting_count"],
                 "company_count": r["company_count"], "support_state": r["support_state"], "mapping_reason": mp.get("reason"),
                 "closest_esco_candidates": [(c.get("label"), c.get("similarity_score"), c.get("lexical_relation")) for c in mp.get("candidates", [])][:3],
                 "scope_warning": run.industry["scope"]["representativeness_warning"]})
    # 8 partial coverage
    cov = [r for r in jl(intel / "coverage_depth.jsonl") if r["role"] == "TARGET"]
    part = sorted((r for r in cov if r["coverage_level"] in ("MENTION", "INTRODUCTORY")),
                  key=lambda r: (r["coverage_level"] != "MENTION", r["skill_label"]))
    if part:
        r = part[0]
        add(8, "Curriculum topic with partial coverage", "target coverage MENTION first, else INTRODUCTORY", "INFERRED_FROM_TEXT",
            {"skill": r["skill_label"], "coverage_level": r["coverage_level"], "relation_counts": r["relation_counts"],
             "reason": r["level_reason"], "evidence": [{k: e[k] for k in ("course_code", "page", "text", "relation")} for e in r["evidence"][:4]]})
    # 9 concept across multiple courses
    multi = sorted(run.concepts.values(), key=lambda c: (-len(c["course_uids"]), c["concept_uid"]))[0]
    add(9, "Concept across multiple courses", "concept with the most distinct courses", "DISCOVERED (TF-IDF clustering)",
        {"concept": multi["name"], "courses": sorted({courses[u]["course_code"] + " " + courses[u]["title"] for u in multi["course_uids"] if u in courses}),
         "support": multi["support"]})
    # 10 emerging over time
    tr = jl(intel / "industry_trends.jsonl")
    add(10, "Industry concept emerging over time", "trend states of all demand skills", "INSUFFICIENT_EVIDENCE",
        {"trend_states": dict(Counter(t["trend_state"] for t in tr)), "reason": tr[0]["reason"] if tr else None,
         "note": "no EMERGING claim is made: the supplied postings cover a single month"})

    out_dir = ROOT / "data/evaluation/results"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "real_world_cases.json").write_text(json.dumps({"run_id": run.run_id, "cases": cases}, indent=1, ensure_ascii=False))
    lines = [f"# Ten real-world cases (run `{run.run_id}`)", "",
             "Each case is selected by the stated rule from GOLD outputs; nothing is hand-picked by name.", ""]
    for c in cases:
        lines += [f"## {c['case']}. {c['title']}", f"*Selection:* {c['selection_rule']} · *Evidence class:* **{c['evidence_class']}**", ""]
        lines += ["```json", json.dumps({k: v for k, v in c.items() if k not in ("case", "title", "selection_rule", "evidence_class")},
                                        indent=1, ensure_ascii=False), "```", ""]
    (out_dir / "real_world_cases.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines)[:6000])


if __name__ == "__main__":
    main()
