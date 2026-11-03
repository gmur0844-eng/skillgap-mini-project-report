#!/usr/bin/env python3
"""
Topic → concept mapping audit (read-only; changes nothing in the run).

  python3 scripts/audit/topic_concept_mapping_audit.py [--run <run_id>] [--out data/evaluation/topic_concept_mapping_audit.json]

Keeps the three mapping problems apart:
  A  TOPIC → CONCEPT               clustering membership (topic belongs to a discovered concept)
  B  CURRICULUM → REFERENCE         target topic → reference topic relationship (topic_mappings.jsonl)
  C  INDUSTRY SKILL → TAXONOMY      normalized skill → ESCO concept (esco_mappings / mention sense)
(the peer comparison is a fourth, audited by the peer stage's own rules and in FULL_CONSISTENCY_AUDIT)

Every flag is produced by a stated deterministic check. Proposed classifications carry their basis:
  DETERMINISTIC_RULE       follows mechanically from the check
  ASSISTANT_ADJUDICATION   the assistant read the texts and courses (NOT human validation)
  REQUIRES_HUMAN_REVIEW    no safe automatic decision
The old result is always kept next to the proposal.
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine.peer_stage import _specific  # noqa: E402
from app.knowledge_engine.semantic_backend import TfidfBackend  # noqa: E402
from app.services import knowledge_service as ks  # noqa: E402

# structural / generic wording that never identifies a concept on its own (language-level, not discipline-level)
GENERIC = {"introduction", "applications", "application", "concepts", "concept", "basics", "overview", "types", "properties",
           "techniques", "methods", "process", "processes", "structures", "structure", "definition", "defining", "paths",
           "initialization", "examples", "problems", "advantages", "features", "models", "systems", "analysis", "design",
           "principles", "fundamentals", "operations", "matching", "trees", "index", "security", "network", "networks",
           "communication", "plan", "planning", "management", "tools", "case", "study", "case study"}

# assistant readings of the specific pairs flagged below (texts + both courses read); NOT human validation
def _same_course(a, b):
    """Course titles match case-insensitively; a title truncated in a report ('Problem Solving and Programming usi…')
    matches its full form by prefix."""
    a, b = (a or "").strip().rstrip("…").lower(), (b or "").strip().rstrip("…").lower()
    return bool(a) and bool(b) and (a == b or a.startswith(b) or b.startswith(a))


def assistant_reading(topic, source_course, reference_course):
    for (t, sc, rc), v in ASSISTANT.items():
        if t == topic and _same_course(sc, source_course) and _same_course(rc, reference_course):
            return v
    return None


ASSISTANT = {
    ("Concepts", "ENGINEERING ECONOMICS AND ACCOUNTANCY", "Advanced Programming"): ("UNRELATED", "generic word; economics vs programming course"),
    ("techniques", "Network Security", "Complier Design"): ("UNRELATED", "generic word; security vs compiler techniques"),
    ("Properties", "WEB PROGRAMMING WITH JAVASCRIPT", "Engineering Graphics & Design"): ("UNRELATED", "CSS/JS properties vs geometric properties"),
    ("Initialization", "Problem Solving and Programming", "Machine Learning"): ("UNRELATED", "variable initialization vs weight initialization"),
    ("Paths", "SOFTWARE TESTING METHODOLOGY", "Discrete Mathematics"): ("RELATED", "path testing uses graph paths; not the same concept"),
    ("Applications", "BASIC ELECTRICAL ENGINEERING", "Basic Electrical Engineering"): ("AMBIGUOUS", "generic heading; which applications is unknown"),
    ("Defining", "Employability Skills", "English"): ("AMBIGUOUS", "fragment; no standalone concept"),
    ("Process", "Operating Systems", "Operating Systems"): ("SAME_CONCEPT", "OS process in both OS courses"),
    ("Structures", "Problem Solving and Programming", "Programming for Problem Solving"): ("SAME_CONCEPT", "C structures in both programming courses"),
    ("Trees", "Discrete Structures", "Discrete Mathematics"): ("SAME_CONCEPT", "graph-theoretic trees in both discrete-math courses"),
    ("Matching", "Discrete Structures", "Discrete Mathematics"): ("SAME_CONCEPT", "graph matching in both discrete-math courses"),
    ("Iterator", "FUNDAMENTALS OF JAVA PROGRAMMING", "Advanced Programming"): ("SAME_CONCEPT", "Java iterator"),
    ("Interfaces", "Java Programming", "Advanced Programming"): ("SAME_CONCEPT", "Java interfaces"),
    ("Prepositions", "Employability Skills", "English"): ("SAME_CONCEPT", "grammar topic in both language courses"),
    ("Articles", "Employability Skills", "English"): ("SAME_CONCEPT", "grammar topic"),
    ("articles", "TECHNICAL WRITING SKILLS", "English"): ("SAME_CONCEPT", "grammar topic"),
    ("Synonyms", "Employability Skills", "English"): ("SAME_CONCEPT", "vocabulary topic"),
    ("Antonyms", "Employability Skills", "English"): ("SAME_CONCEPT", "vocabulary topic"),
    ("Antonyms", "English", "English"): ("SAME_CONCEPT", "vocabulary topic"),
    ("Recursion", "Problem Solving and Programming", "Programming for Problem Solving"): ("SAME_CONCEPT", "recursion in programming"),
    ("Pointers", "Problem Solving and Programming", "Programming for Problem Solving"): ("SAME_CONCEPT", "C pointers"),
    ("Regression", "Artificial Intelligence and Machine Learning", "Machine Learning"): ("SAME_CONCEPT", "ML regression"),
    ("Gradient", "Linear Algebra and Calculus", "Mathematics-I"): ("SAME_CONCEPT", "vector calculus gradient"),
    ("Divergence", "Linear Algebra and Calculus", "Mathematics-I"): ("SAME_CONCEPT", "vector calculus divergence"),
    ("derivatives", "English", "English"): ("SAME_CONCEPT", "word derivatives (vocabulary), same course type"),
    ("segmentation", "Operating Systems", "Operating Systems"): ("SAME_CONCEPT", "memory segmentation"),
    ("swapping", "Operating Systems", "Operating Systems"): ("SAME_CONCEPT", "memory swapping"),
    ("wait", "Operating Systems", "Operating Systems"): ("SAME_CONCEPT", "wait() system call"),
    ("exec", "Operating Systems", "Operating Systems"): ("SAME_CONCEPT", "exec() system call"),
    ("getpid", "Operating Systems", "Operating Systems"): ("SAME_CONCEPT", "getpid() system call"),
    ("sbrk", "Operating Systems", "Operating Systems"): ("SAME_CONCEPT", "sbrk() system call"),
    ("munmap", "Operating Systems", "Operating Systems"): ("SAME_CONCEPT", "munmap() system call"),
}

PROBES = {  # known failure patterns to look for (search terms only; the audit reports what it finds)
    "stack": r"\bstacks?\b", "data types": r"\bdata\s*types?\b", "network vs neural network": r"\bnetworks?\b",
    "angular": r"\bangular\b", "communication": r"\bcommunication\b", "plan": r"\bplan(ning)?\b",
    "network security vs computer networks": r"\bnetwork security\b|\bcomputer networks?\b",
}


def jl(p):
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()] if Path(p).exists() else []


def content_words(text):
    return [w for w in re.findall(r"[a-z0-9+#]+", (text or "").lower()) if len(w) > 2 and w not in {"and", "the", "for", "with", "its"}]


def course_context(courses, topics_by_course):
    uids = sorted(u for u in courses if topics_by_course.get(u))
    texts = [" ; ".join(topics_by_course[u]) for u in uids]
    be = TfidfBackend()
    be.fit(texts)
    sims = be.similarity(be.embed(texts), be.embed(texts))
    pos = {u: i for i, u in enumerate(uids)}
    return lambda a, b: float(sims[pos[a], pos[b]]) if a in pos and b in pos else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None)
    ap.add_argument("--out", default=str(ROOT / "data/evaluation/topic_concept_mapping_audit.json"))
    a = ap.parse_args()
    run = ks.load_run(a.run)
    D = run.dir
    cfg = json.loads((ROOT / "backend/app/knowledge_engine/engine_config.json").read_text())
    ctx_min = cfg["peers"]["course_context_min_similarity"]
    courses = run.courses
    topics = run.topics
    clean = {u: t for u, t in topics.items() if t["noise_label"] == "TOPIC"}
    by_course = defaultdict(list)
    for t in clean.values():
        by_course[t["course_uid"]].append(t["clean_text"])
    cctx = course_context(courses, by_course)
    title = lambda cu: courses.get(cu, {}).get("title", "?")  # noqa: E731

    # ------------------------------------------------------------------ A  topic → concept membership
    concepts = run.concepts
    member_of = {}
    for c in concepts.values():
        for u in c["member_topic_uids"]:
            member_of[u] = c["concept_uid"]
    a_flags = []
    for c in concepts.values():
        name = c["name"]
        words = content_words(name)
        members = [clean[u] for u in c["member_topic_uids"] if u in clean]
        m_courses = sorted({m["course_uid"] for m in members})
        coh = c.get("mean_member_similarity_to_centroid")
        pair_ctx = [cctx(x, y) for i, x in enumerate(m_courses) for y in m_courses[i + 1:]]
        pair_ctx = [p for p in pair_ctx if p is not None]
        flags = []
        if not words or all(w in GENERIC for w in words):
            flags.append("GENERIC_CONCEPT_NAME")
        if coh is not None and coh < 0.35 and len(members) > 1:
            flags.append("LOW_MEMBER_COHERENCE")
        if pair_ctx and min(pair_ctx) < ctx_min and len(m_courses) > 1:
            flags.append("MEMBERS_FROM_UNRELATED_COURSES")
        if flags:
            a_flags.append({"concept_uid": c["concept_uid"], "name": name, "support": c["support"], "flags": flags,
                            "member_similarity_to_centroid": coh, "courses": [title(u) for u in m_courses][:6],
                            "min_course_context": round(min(pair_ctx), 3) if pair_ctx else None,
                            "members": [m["clean_text"] for m in members][:6],
                            "proposal": "REVIEW_REQUIRED (concept may merge different senses)"
                            if "MEMBERS_FROM_UNRELATED_COURSES" in flags else "REVIEW_REQUIRED (generic or loosely coherent cluster)",
                            "proposal_basis": "REQUIRES_HUMAN_REVIEW"})
    probes = {}
    for label, rx in PROBES.items():
        rxc = re.compile(rx, re.I)
        hits = [t for t in clean.values() if rxc.search(t["clean_text"])]
        by_concept = defaultdict(list)
        for t in hits:
            by_concept[member_of.get(t["topic_uid"], "NOT_IN_A_CONCEPT")].append(t)
        probes[label] = {
            "topics": len(hits), "concepts": len([k for k in by_concept if k != "NOT_IN_A_CONCEPT"]),
            "not_in_a_concept": len(by_concept.get("NOT_IN_A_CONCEPT", [])),
            "by_concept": [{"concept": concepts[k]["name"] if k in concepts else k,
                            "courses": sorted({title(t["course_uid"]) for t in v})[:5],
                            "examples": sorted({t["clean_text"][:70] for t in v})[:4], "topics": len(v)}
                           for k, v in sorted(by_concept.items(), key=lambda kv: -len(kv[1]))[:12]]}

    # ------------------------------------------------------------------ B  curriculum → reference
    tm = jl(D / "topic_mappings.jsonl")
    b_rows = []
    for m in tm:
        if not m.get("target_uid"):
            continue
        e = m.get("evidence") or {}
        src, ref = m["source_text"], e.get("reference_text", "")
        ref_course = m.get("reference_course_uid")
        cc = cctx(m["source_course_uid"], ref_course)
        rel = m["relationship"]
        flags = []
        sw, rw = content_words(src), content_words(ref)
        if rel == "SAME_CONCEPT" and not _specific(src):
            flags.append("GENERIC_OR_SINGLE_WORD_IDENTITY")
        if rel in ("CHILD", "PARENT"):
            contained = rw if rel == "CHILD" else sw
            if len(contained) <= 1:
                flags.append("CONTAINMENT_OF_SINGLE_WORD")
            if " and " in f" {src.lower()} " or " and " in f" {ref.lower()} ":
                flags.append("CONJUNCTION_DIRECTION_RISK")
        if rel in ("RELATED", "PARTIAL_OVERLAP") and cc is not None and cc < ctx_min:
            flags.append("SIMILARITY_WITHOUT_COURSE_CONTEXT")
        if len(sw) <= 1 and src[:1].islower() and rel != "SAME_CONCEPT":
            flags.append("FRAGMENT_SOURCE")
        if cc is not None and cc < ctx_min and rel in ("SAME_CONCEPT", "CHILD", "PARENT"):
            flags.append("LOW_COURSE_CONTEXT")
        row = {"mapping_uid": m["mapping_uid"], "source_topic": src, "source_course": title(m["source_course_uid"]),
               "source_page": e.get("target_page"), "reference_topic": ref, "reference_course": e.get("reference_course"),
               "reference_page": e.get("reference_page"), "relationship": rel, "method": m["method"],
               "evidence_status": m["evidence_status"], "lexical_similarity": m.get("similarity_score"),
               "unit_context_similarity": (m.get("signals") or {}).get("context_similarity"),
               "course_context": round(cc, 4) if cc is not None else None,
               "deterministic": m["method"] == "normalized_text_identity", "flags": flags}
        hit = assistant_reading(src, title(m["source_course_uid"]), e.get("reference_course"))
        if hit:
            lab, why = hit
            row.update(proposed=lab, proposal_basis="ASSISTANT_ADJUDICATION", proposal_reason=why)
        elif "GENERIC_OR_SINGLE_WORD_IDENTITY" in flags and "LOW_COURSE_CONTEXT" in flags:
            row.update(proposed="SAME_CONCEPT (REVIEW_REQUIRED)", proposal_basis="DETERMINISTIC_RULE",
                       proposal_reason=f"single-word identity with course context < {ctx_min}: shared words are not enough")
        elif "CONTAINMENT_OF_SINGLE_WORD" in flags or "LOW_COURSE_CONTEXT" in flags:
            row.update(proposed="AMBIGUOUS (REVIEW_REQUIRED)", proposal_basis="REQUIRES_HUMAN_REVIEW",
                       proposal_reason="containment of a single word or no comparable course context; direction/sense unverified")
        elif flags:
            row.update(proposed=None, proposal_basis="REQUIRES_HUMAN_REVIEW", proposal_reason="flagged; keep MODEL_SUGGESTED")
        b_rows.append(row)
    b_sum = {"linked_mappings": len(b_rows), "by_relationship": dict(Counter(r["relationship"] for r in b_rows)),
             "flag_counts": dict(Counter(f for r in b_rows for f in r["flags"])),
             "flagged": sum(1 for r in b_rows if r["flags"]),
             "unmapped": dict(Counter(m["relationship"] for m in tm if not m.get("target_uid")))}

    # historical 45-pair benchmark vs the current pipeline links
    bench = json.loads((ROOT / "data/evaluation/semantic_benchmark.json").read_text())
    cur = {(m["source_text"].lower(), (m.get("evidence") or {}).get("reference_text", "").lower()): m["relationship"]
           for m in tm if m.get("target_uid")}
    hist = []
    for p in bench["pairs"]:
        now = cur.get((p["target_text"].lower(), p["reference_text"].lower()))
        hist.append({"pair_id": p["pair_id"], "source": p.get("source"), "assistant_label": p["label"],
                     "current_pipeline_relationship": now})
    still = [h for h in hist if h["source"] == "pipeline_link" and h["current_pipeline_relationship"]]
    eval_now = json.loads((D / "evaluation.json").read_text()).get("semantic_relationships", {})

    # ------------------------------------------------------------------ C  industry skill → taxonomy
    em = jl(D / "industry/esco_mappings.jsonl")
    skills = {s["skill_key"]: s for s in jl(D / "industry/skills.jsonl")}
    mentions = jl(D / "industry/skill_mentions.jsonl")
    demand = {d["skill_key"]: d for d in jl(D / "industry/industry_demand.jsonl")}
    alias = []
    for x in em:
        s = skills.get(x["skill_key"], {})
        if x.get("esco_uri") and s.get("eligible_for_analytics") and "Label_full_taxonomy" in (x.get("mapping_method") or "") \
                and x["normalized_label"].lower() != (x.get("esco_pref_label") or "").lower():
            broader = not (set(content_words(x["normalized_label"])) & set(content_words(x.get("esco_pref_label"))))
            alias.append({"skill": x["normalized_label"], "esco_concept": x.get("esco_pref_label"), "method": x["mapping_method"],
                          "demand_postings": demand.get(x["skill_key"], {}).get("posting_count"),
                          "flag": "ALIAS_TO_DIFFERENTLY_NAMED_CONCEPT" if broader else "MORPHOLOGICAL_OR_WORDING_VARIANT",
                          "proposal_basis": "REQUIRES_HUMAN_REVIEW" if broader else "DETERMINISTIC_RULE"})
    c_sum = {"mappings": len(em), "by_status": dict(Counter(x.get("status") for x in em)),
             "mention_taxonomy_relationship": dict(Counter(m.get("taxonomy_relationship") for m in mentions)),
             "alias_mentions_by_sense_state": dict(Counter(m["sense_state"] for m in mentions
                                                          if m.get("taxonomy_relationship") == "TAXONOMY_ALIAS_MATCH")),
             "eligible_alias_mappings": len(alias),
             "alias_to_differently_named_concept": sum(1 for x in alias if x["flag"] == "ALIAS_TO_DIFFERENTLY_NAMED_CONCEPT")}

    out = {"run_id": run.run_id, "course_context_min_similarity": ctx_min,
           "problems_kept_separate": {"A": "topic → concept (clustering membership)", "B": "curriculum topic → reference topic",
                                       "C": "industry skill → ESCO taxonomy concept", "peer": "see peers/peer_relations.jsonl"},
           "A_topic_concept": {"concepts": len(concepts), "clean_topics": len(clean), "topics_in_concepts": len(member_of),
                               "flagged_concepts": len(a_flags), "flag_counts": dict(Counter(f for x in a_flags for f in x["flags"])),
                               "flagged": a_flags, "known_pattern_probes": probes},
           "B_curriculum_reference": {"summary": b_sum, "rows": b_rows},
           "historical_benchmark": {"file": "data/evaluation/semantic_benchmark.json", "labelled_by": bench.get("labelled_by"),
                                    "pairs": len(bench["pairs"]),
                                    "pair_rule_result_this_run": {k: eval_now.get(k, {}).get("accuracy") for k in ("relationship_level", "linked_vs_unrelated")},
                                    "historical_pipeline_links_still_produced": len(still),
                                    "still_produced_agreeing_with_label": sum(1 for h in still if h["current_pipeline_relationship"] == h["assistant_label"]),
                                    "rows": hist},
           "C_skill_taxonomy": {"summary": c_sum, "alias_rows": alias}}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps({"A": out["A_topic_concept"]["flag_counts"], "B": b_sum, "C": c_sum,
                      "hist": {k: v for k, v in out["historical_benchmark"].items() if k != "rows"}}, indent=1))


if __name__ == "__main__":
    main()
