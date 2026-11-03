"""
Curriculum-intelligence layer (engine 2.0) -- additive analyses on top of the existing GOLD outputs.

  topic_hierarchy        subtopics from explicit list structure ("Head: a, b, c"), never blind comma splits
  occupation_analysis    job title -> ESCO occupation (labels only) -> ISCO groups; posting skills vs the
                         occupation's ESCO essential/optional skill profile
  skill_taxonomy_context ESCO skill type, reuse level, skill-group ancestors, collections for each skill
  coverage_depth         per skill and curriculum: coverage RELATION of each mention (DIRECT / PARTIAL /
                         RELATED / INCIDENTAL) and coverage LEVEL (ABSENT / MENTION / INTRODUCTORY /
                         SUBSTANTIAL / ADVANCED / INSUFFICIENT_EVIDENCE) from topics, units, courses,
                         outcomes and prerequisite progression
  industry_trends        EMERGING / GROWING / STABLE / DECLINING / REPLACED / INSUFFICIENT_EVIDENCE
  curriculum_industry_lag INDUSTRY_FIRST / CURRICULUM_FIRST / ALIGNED / INSUFFICIENT_EVIDENCE
  prerequisite_recommendations  INTRODUCE_PREREQUISITE from ESCO skill-skill relations + absent coverage
  knowledge_graph + graph_consistency  typed, evidenced nodes/edges and automated consistency checks
  adjudication_candidates  pairs the rules could not settle, for the SemanticModelProvider

No function names a university, programme, discipline, skill or subject.
"""
import re
from collections import Counter, defaultdict

from app.knowledge_engine import esco_full
from app.knowledge_engine.silver import uid
from app.pipelines.preprocessing.skill_normalization import normalize_skill_text as norm

# ------------------------------------------------------------------ topic hierarchy

_HEAD_RE = re.compile(r"^\s*(?P<head>[^:;.]{2,90}?)\s*:\s*(?P<rest>.+)$")
_ITEM_SPLIT_RE = re.compile(r"\s*[,;]\s*")


def topic_hierarchy(topics, cfg):
    """
    Parent/child topic records from EXPLICIT list structure only:
      a line "Head: item, item, item" (head <= max_head_words, every item <= max_item_words, >= 2 items),
      where the head is not a structural label (a head seen in >= structural_head_min_courses courses)
    The head becomes the parent topic; items become subtopics. A line without a colon head is never
    split into a hierarchy (commas alone do not imply sub-topics).
    """
    max_head, max_item = cfg["max_head_words"], cfg["max_item_words"]
    by_line = defaultdict(list)
    for t in topics:
        by_line[(t["course_uid"], t.get("unit_label"), t.get("source_line") or t["clean_text"])].append(t)
    # a head used in many different courses ("Module II:", "Topics:") is a structural label of the
    # document layout, not a parent topic (corpus frequency, no word list)
    head_courses = defaultdict(set)
    for (course_uid, _, line) in by_line:
        m = _HEAD_RE.match(line or "")
        if m:
            head_courses[norm(m.group("head"))].add(course_uid)
    structural = {h for h, cs in head_courses.items() if len(cs) >= cfg["structural_head_min_courses"]}
    rows, stats = [], Counter()
    for (course_uid, unit, line), members in sorted(by_line.items(), key=lambda kv: (kv[0][0], str(kv[0][1]), kv[0][2])):
        m = _HEAD_RE.match(line or "")
        if not m:
            stats["lines_without_head"] += 1
            continue
        head = m.group("head").strip(" -–")
        if norm(m.group("head")) in structural:
            stats["head_is_structural_label"] += 1
            continue
        items = [i.strip(" .-–") for i in _ITEM_SPLIT_RE.split(m.group("rest")) if i.strip(" .-–")]
        if not (1 <= len(head.split()) <= max_head) or len(items) < 2 or any(len(i.split()) > max_item for i in items):
            stats["head_rejected_by_shape"] += 1
            continue
        stats["lines_with_hierarchy"] += 1
        parent_uid = uid("topicnode", course_uid, unit, head)
        member_uids = sorted(t["topic_uid"] for t in members)
        for pos, item in enumerate(items):
            child_topic = next((t["topic_uid"] for t in members if norm(item) and norm(item) in norm(t["clean_text"])), None)
            rows.append({"hierarchy_uid": uid("subtopic", parent_uid, pos, item), "parent_node_uid": parent_uid,
                         "parent_text": head, "child_text": item, "position": pos, "course_uid": course_uid,
                         "unit_label": unit, "doc_id": members[0]["doc_id"], "page_number": members[0].get("page_number"),
                         "child_topic_uid": child_topic, "source_topic_uids": member_uids, "source_line": line,
                         "relationship": "CHILD_OF", "method": "colon_head_list_structure",
                         "evidence_status": "EXTRACTED"})
            stats["subtopics"] += 1
    return rows, dict(stats)


# ------------------------------------------------------------------ occupations

def occupation_analysis(postings, posting_mentions, skills, store, cfg):
    index = esco_full.occupation_index(store)
    established_keys = {k for k, s in skills.items() if s["eligible_for_analytics"] and s.get("esco_uri")}
    skills_by_posting = defaultdict(set)
    for m in posting_mentions:
        if m["skill_key"] in established_keys and m["mention_role"] == "SKILL" and m["sense_established"]:
            skills_by_posting[m["source_uid"]].add(skills[m["skill_key"]]["esco_uri"])
    rows = []
    for p in sorted(postings, key=lambda x: x["posting_uid"]):
        r = esco_full.match_occupation(p.get("job_title"), index)
        occ_uri = r.get("occupation_uri")
        row = {"posting_uid": p["posting_uid"], "job_title": p.get("job_title"), "status": r["status"],
               "established": r["status"] in esco_full.OCCUPATION_ESTABLISHED, "matched_label": r.get("matched_label"),
               "occupation_uri": occ_uri, "occupation_label": store["occupations"][occ_uri]["pref_label"] if occ_uri else None,
               "uncovered_title_words": r.get("uncovered_title_words"), "candidates": r.get("candidates") or r.get("other_candidates") or [],
               "reason": r.get("reason"), "method": "esco_occupation_label_match"}
        if occ_uri:
            path = esco_full.isco_path(store, occ_uri)
            row["isco_groups"] = path
            row["isco_major_group"] = next((g for g in path if len(g["code"]) == 1), None)
            occ = store["occupations"][occ_uri]
            ess, opt = set(occ["essential_skills"]), set(occ["optional_skills"])
            found = skills_by_posting.get(p["posting_uid"], set())
            row["posting_skills_vs_esco_profile"] = {
                "essential": sorted(found & ess), "optional": sorted(found & opt),
                "not_in_profile": sorted(found - ess - opt),
                "esco_profile_size": {"essential": len(ess), "optional": len(opt)}}
        rows.append(row)
    est = [r for r in rows if r["established"]]
    groups = defaultdict(list)
    for r in est:
        g = r.get("isco_major_group")
        groups[(g["code"], g["label"]) if g else ("?", "unknown")].append(r["posting_uid"])
    in_profile = sum(len(r["posting_skills_vs_esco_profile"]["essential"]) + len(r["posting_skills_vs_esco_profile"]["optional"])
                     for r in est)
    outside = sum(len(r["posting_skills_vs_esco_profile"]["not_in_profile"]) for r in est)
    summary = {
        "postings": len(rows), "by_status": dict(Counter(r["status"] for r in rows)),
        "established_postings": len(est), "distinct_established_occupations": len({r["occupation_uri"] for r in est}),
        "postings_by_isco_major_group": {f"{c} {l}": len(v) for (c, l), v in sorted(groups.items())},
        "established_skill_occurrences_in_esco_profile": in_profile,
        "established_skill_occurrences_outside_esco_profile": outside,
        "min_postings_per_occupation_group_for_comparison": cfg["min_postings_per_group"],
        "comparable_groups": sorted(f"{c} {l}" for (c, l), v in groups.items() if len(v) >= cfg["min_postings_per_group"]),
        "note": ("Only EXACT/VARIANT title matches are established. CANDIDATE matches (a label inside a longer title) "
                 "are kept for review and not used. Demand is compared only within an occupation group that has at "
                 "least min_postings_per_group established postings; smaller groups are INSUFFICIENT_EVIDENCE."),
    }
    return rows, summary


# ------------------------------------------------------------------ taxonomy context

def skill_taxonomy_context(skills, store):
    out = []
    for key, s in sorted(skills.items()):
        uri = s.get("esco_uri") or s.get("taxonomy_candidate_uri")
        if not uri or uri not in store["skills"]:
            continue
        node = store["skills"][uri]
        groups = esco_full.skill_group_path(store, uri)
        out.append({"skill_key": key, "esco_uri": uri, "label": node["pref_label"], "skill_type": node["skill_type"],
                    "reuse_level": node["reuse_level"], "collections": sorted(set(node.get("collections", []))),
                    "description": node["description"],
                    "broader": [{"uri": g["uri"], "label": g["label"], "kind": g["kind"], "code": g["code"]}
                                for g in groups if g["depth"] == 1],
                    "top_skill_groups": sorted({g["label"] for g in groups if g["kind"] == "skill_group" and g.get("code")
                                                and len(g["code"]) <= 2}),
                    "ancestors": len(groups),
                    "used_by_occupations": sum(1 for o in store["occupations"].values()
                                               if uri in o["essential_skills"] or uri in o["optional_skills"]),
                    "evidence_status": "REFERENCE_TAXONOMY_FACT"})
    return out


# ------------------------------------------------------------------ coverage depth

COVERAGE_RELATIONS = ("DIRECT", "PARTIAL", "RELATED", "INCIDENTAL")
COVERAGE_LEVELS = ("ABSENT", "MENTION", "INTRODUCTORY", "SUBSTANTIAL", "ADVANCED", "INSUFFICIENT_EVIDENCE")
_TOKEN = re.compile(r"[A-Za-z0-9+#.]+")


def mention_relation(topic_text, span, max_item_words):
    """
    Where the skill label sits in its list item decides what the topic says about it:
      DIRECT      the item IS the label                      ("X")
      PARTIAL     the label is the item's head (last words)  ("advanced X", "Introduction to X")
      RELATED     the label modifies another head            ("X injection" is about injection, not X)
      INCIDENTAL  the label is buried in a long item (> max_item_words words)
    Items are the pieces between list punctuation (, ; : . and dashes).
    """
    start, end = span
    left = re.split(r"[,;:.–—]|\s-\s", topic_text[:start])[-1]
    right = re.split(r"[,;:.–—]|\s-\s", topic_text[end:])[0]
    before, after = _TOKEN.findall(left), _TOKEN.findall(right)
    item_len = len(before) + len(after) + len(_TOKEN.findall(topic_text[start:end]))
    if item_len > max_item_words:
        return "INCIDENTAL"
    if not before and not after:
        return "DIRECT"
    if not after:
        return "PARTIAL"
    return "RELATED"


def coverage_depth(curriculum_mentions, topics_by_uid, courses_by_uid, doc_id, skills, outcome_mentions,
                   prereq_edges, cfg):
    """Per skill_key: coverage relation + level for one curriculum document (evidence listed)."""
    by_skill = defaultdict(list)
    for m in curriculum_mentions:
        t = topics_by_uid.get(m["source_uid"])
        if t is None or t["doc_id"] != doc_id or not m.get("sense_established") or m["skill_key"] not in skills:
            continue
        rel = mention_relation(t["clean_text"], m["span"], cfg["max_item_words"])
        by_skill[m["skill_key"]].append({"topic_uid": t["topic_uid"], "course_uid": t["course_uid"],
                                         "course_code": courses_by_uid[t["course_uid"]]["course_code"],
                                         "unit_label": t.get("unit_label"), "page": t.get("page_number"),
                                         "text": t["clean_text"], "raw_mention": m["raw_mention"], "relation": rel})
    outcomes_by_skill = defaultdict(list)
    for m in outcome_mentions:
        if m.get("doc_id") == doc_id:
            outcomes_by_skill[m["skill_key"]].append(m)
    prereq_pairs = {(e["source_uid"], e["target_uid"]) for e in prereq_edges}
    rows = []
    for key in sorted(skills):
        ev = by_skill.get(key, [])
        strong = [e for e in ev if e["relation"] in ("DIRECT", "PARTIAL")]
        rel_counts = Counter(e["relation"] for e in ev)
        best_rel = next((r for r in COVERAGE_RELATIONS if rel_counts.get(r)), None)
        strong_courses = sorted({e["course_uid"] for e in strong})
        strong_units = sorted({(e["course_uid"], e["unit_label"]) for e in strong}, key=str)
        progression = sorted({(a, b) for a in strong_courses for b in strong_courses if (a, b) in prereq_pairs})
        outcome_ev = outcomes_by_skill.get(key, [])
        if not ev:
            level, why = "ABSENT", "no topic of this curriculum contains an established mention of the skill"
        elif not strong:
            level, why = "MENTION", "only RELATED/INCIDENTAL mentions (the skill qualifies another subject)"
        elif progression:
            level, why = "ADVANCED", "covered in a course AND in a course it lists as prerequisite (progression evidence)"
        elif len(strong) >= cfg["substantial_min_topics"] or len(strong_units) >= cfg["substantial_min_units"]:
            level, why = "SUBSTANTIAL", (f"{len(strong)} DIRECT/PARTIAL topics in {len(strong_units)} unit(s)")
        else:
            level, why = "INTRODUCTORY", f"{len(strong)} DIRECT/PARTIAL topic(s) in {len(strong_units)} unit(s)"
        rows.append({"skill_key": key, "skill_label": skills[key]["label"], "doc_id": doc_id, "coverage_level": level,
                     "coverage_relation": best_rel or "NONE", "level_reason": why,
                     "relation_counts": dict(rel_counts), "courses_direct_or_partial": len(strong_courses),
                     "units_direct_or_partial": len(strong_units), "prerequisite_progression_pairs": len(progression),
                     "outcome_mentions": len(outcome_ev),
                     "outcome_examples": [o["text"][:160] for o in outcome_ev[:3]],
                     "evidence": ev[:12], "method": "label_position_in_list_item + counts (heuristic, uncalibrated)",
                     "evidence_status": "INFERRED_FROM_TEXT" if ev else "INSUFFICIENT_EVIDENCE" if level == "INSUFFICIENT_EVIDENCE" else "NO_TEXT_EVIDENCE"})
    return rows


# ------------------------------------------------------------------ trends and lag

def industry_trends(demand_rows, temporal):
    """States require >= 2 comparable periods; the temporal stage already decides whether trends exist."""
    allowed = temporal.get("trend_status") not in (None, "INSUFFICIENT_EVIDENCE")
    out = []
    for d in demand_rows:
        if not allowed:
            out.append({"skill_key": d["skill_key"], "skill_label": d.get("skill_label"), "trend_state": "INSUFFICIENT_EVIDENCE",
                        "reason": temporal.get("reason"), "posting_count": d["posting_count"]})
            continue
        series = (temporal.get("skill_series") or {}).get(d["skill_key"])
        out.append({"skill_key": d["skill_key"], "skill_label": d.get("skill_label"),
                    "trend_state": (series or {}).get("state", "INSUFFICIENT_EVIDENCE"),
                    "reason": (series or {}).get("reason", "no per-period series for this skill"),
                    "posting_count": d["posting_count"]})
    return out


def curriculum_industry_lag(skills, target_depth, previous_depth, trends, versions):
    """
    Which moved first. Needs dated curriculum versions AND an industry trend:
      INDUSTRY_FIRST    industry EMERGING/GROWING before the curriculum version that added the skill
      CURRICULUM_FIRST  the curriculum covered the skill in the previous version before industry growth
      ALIGNED           both present across the compared periods
      INSUFFICIENT_EVIDENCE  otherwise (reason stated)
    """
    trend = {t["skill_key"]: t for t in trends}
    prev = {r["skill_key"]: r for r in previous_depth}
    tgt = {r["skill_key"]: r for r in target_depth}
    out = []
    for key in sorted(trend):
        t = trend[key]
        p_level = prev.get(key, {}).get("coverage_level")
        t_level = tgt.get(key, {}).get("coverage_level")
        reasons = []
        if t["trend_state"] == "INSUFFICIENT_EVIDENCE":
            reasons.append(f"industry trend unavailable: {t['reason']}")
        if not (versions.get("previous_date") and versions.get("target_date")):
            reasons.append("curriculum versions carry no effective dates in the source manifest")
        state = "INSUFFICIENT_EVIDENCE"
        if not reasons:
            prev_has = p_level not in (None, "ABSENT", "MENTION")
            tgt_has = t_level not in (None, "ABSENT", "MENTION")
            if tgt_has and not prev_has and t["trend_state"] in ("EMERGING", "GROWING"):
                state = "INDUSTRY_FIRST"
            elif prev_has and t["trend_state"] in ("EMERGING", "GROWING"):
                state = "CURRICULUM_FIRST"
            elif prev_has and tgt_has:
                state = "ALIGNED"
            else:
                reasons.append("the pattern of coverage and trend does not match a defined lag state")
        out.append({"skill_key": key, "skill_label": skills[key]["label"] if key in skills else t.get("skill_label"),
                    "lag_state": state, "previous_coverage_level": p_level, "target_coverage_level": t_level,
                    "industry_trend_state": t["trend_state"], "reasons": reasons})
    return out


# ------------------------------------------------------------------ prerequisite recommendations

def prerequisite_recommendations(recommendations, skills, target_depth, store, run_id):
    """For every recommended skill, ESCO 'essential' skill-skill relations whose related skill has
    ABSENT coverage in the target curriculum -> INTRODUCE_PREREQUISITE (taxonomy fact + coverage)."""
    depth_by_uri = {skills[r["skill_key"]].get("esco_uri"): r for r in target_depth if r["skill_key"] in skills}
    related = defaultdict(list)
    for rel in store["skill_skill"]:
        if rel["relation"] == "essential":
            related[rel["skill_uri"]].append(rel["related_skill_uri"])
    out, checked = [], []
    for rec in recommendations:
        uri = skills.get(rec["skill_key"], {}).get("esco_uri")
        for rel_uri in related.get(uri, []):
            d = depth_by_uri.get(rel_uri)
            level = d["coverage_level"] if d else "NOT_ASSESSED"
            checked.append({"skill_key": rec["skill_key"], "related_uri": rel_uri, "coverage_level": level})
            if level == "ABSENT":
                out.append({"recommendation_uid": uid("rec2", run_id, rec["skill_key"], rel_uri),
                            "action_type": "INTRODUCE_PREREQUISITE", "skill_key": rec["skill_key"],
                            "prerequisite_esco_uri": rel_uri,
                            "prerequisite_label": store["skills"][rel_uri]["pref_label"],
                            "what": f"introduce '{store['skills'][rel_uri]['pref_label']}' before/with '{rec['skill_label']}'",
                            "where": rec.get("target_course_codes"),
                            "why": ["ESCO lists it as an essential related skill (taxonomy fact)",
                                    "no established mention in the target curriculum (coverage ABSENT)"],
                            "evidence_status": "INFERRED", "is_source_evidence": False,
                            "uncertainty": "ESCO relations are generic, not programme-specific; ABSENT means no label "
                                           "match in topic text, not proof the content is missing"})
    return out, {"relations_checked": len(checked), "not_assessed": sum(1 for c in checked if c["coverage_level"] == "NOT_ASSESSED"),
                 "rules": {"INTRODUCE_PREREQUISITE": "ESCO essential skill-skill relation + target coverage ABSENT",
                           "INTRODUCE_LAB": "NOT_IMPLEMENTED: practical/lab hours are not parsed from the supplied curricula",
                           "INTRODUCE_PROJECT": "NOT_IMPLEMENTED: no project evidence is extracted",
                           "REDUCE_OUTDATED_CONTENT": "requires industry trend DECLINING/REPLACED; trends are INSUFFICIENT_EVIDENCE "
                                                      "for a single-period posting set"}}


# ------------------------------------------------------------------ knowledge graph

INVERSE = {"PARENT_OF": "CHILD_OF", "CHILD_OF": "PARENT_OF"}


def knowledge_graph(ctx):
    """Nodes/edges from the GOLD records in ctx. Every edge: type, source, target, method, evidence, status."""
    nodes, edges = {}, []

    def node(nid, ntype, label, **extra):
        nodes.setdefault(nid, {"node_id": nid, "node_type": ntype, "label": label, **extra})

    seen = {}

    def edge(src, rel, dst, method, status, evidence=None, uncertainty=None, kind=None):
        key = (src, rel, dst)
        if key in seen:  # the same fact derived twice is one edge; further derivations are listed on it
            seen[key][1] += 1
            if method not in seen[key][0]["methods"]:
                seen[key][0]["methods"].append(method)
            return
        edges.append({"edge_id": uid("kg", src, rel, dst), "source": src, "relationship": rel, "target": dst,
                      "method": method, "methods": [method], "evidence_status": status, "evidence": evidence or {},
                      "uncertainty": uncertainty, "mapping_kind": kind})
        seen[key] = [edges[-1], 1]

    for d in ctx["documents"]:
        node(f"doc:{d['doc_id']}", "CURRICULUM_VERSION", d["doc_id"], institution=d.get("institution"),
             programme=d.get("programme"), role=d.get("role"))
    for c in ctx["courses"]:
        node(c["course_uid"], "COURSE", c["title"], course_code=c["course_code"], doc_id=c["doc_id"])
        edge(f"doc:{c['doc_id']}", "CONTAINS", c["course_uid"], "document_structure", "EXTRACTED", {"page": c.get("first_page")},
             kind="DOCUMENT_STRUCTURE")
    for t in ctx["topics"]:
        node(t["topic_uid"], "TOPIC", t["clean_text"], doc_id=t["doc_id"])
        edge(t["course_uid"], "CONTAINS", t["topic_uid"], "document_structure", "EXTRACTED",
             {"page": t.get("page_number"), "unit": t.get("unit_label")}, kind="DOCUMENT_STRUCTURE")
    for h in ctx["hierarchy"]:
        node(h["parent_node_uid"], "TOPIC", h["parent_text"], doc_id=h["doc_id"], derived="subtopic_head")
        child = h["child_topic_uid"] or h["hierarchy_uid"]
        if not h["child_topic_uid"]:
            node(child, "SUBTOPIC", h["child_text"], doc_id=h["doc_id"])
        edge(h["parent_node_uid"], "PARENT_OF", child, h["method"], "EXTRACTED", {"source_line": h["source_line"]},
             kind="TOPIC_HIERARCHY")
        edge(child, "CHILD_OF", h["parent_node_uid"], h["method"], "EXTRACTED", {"source_line": h["source_line"]},
             kind="TOPIC_HIERARCHY")
    for c in ctx["concepts"]:
        node(c["concept_uid"], "CONCEPT", c["name"], family_uid=c.get("family_uid"))
    for tid, cid in ctx["topic_to_concept"].items():
        if tid in nodes and cid in nodes:
            edge(tid, "MAPS_TO", cid, "tfidf_concept_clustering", "MODEL_SUGGESTED", kind="TOPIC_TO_CONCEPT")
    rel_map = {"SAME_CONCEPT": "SAME_AS", "PARENT": "PARENT_OF", "CHILD": "CHILD_OF", "RELATED": "RELATED_TO",
               "PARTIAL_OVERLAP": "RELATED_TO"}
    for m in ctx["mappings"]:
        rel = rel_map.get(m.get("relationship"))
        tgt = m.get("target_uid")
        if rel and tgt and m["source_uid"] in nodes and tgt in nodes:
            edge(m["source_uid"], rel, tgt, m.get("method") or "reference_mapping", m.get("evidence_status"),
                 {"similarity_score": m.get("similarity_score"), "score_is_calibrated": False,
                  "course_context": (m.get("signals") or {}).get("course_context"),
                  "context_gate": (m.get("signals") or {}).get("context_gate")}, kind="CURRICULUM_TO_REFERENCE")
    for e in ctx["prereq_edges"]:
        edge(e["source_uid"], "PREREQUISITE_OF", e["target_uid"], e.get("method") or "explicit_prerequisite_statement",
             e.get("evidence_status") or "EXTRACTED", e.get("evidence"), kind="PREREQUISITE")
    for s in ctx["skills"].values():
        node(s["skill_uid"], "SKILL", s["label"], esco_status=s["esco_status"])
        if s.get("esco_uri"):
            node(s["esco_uri"], "ESCO_SKILL", s.get("esco_pref_label") or s["label"])
            edge(s["skill_uid"], "MAPS_TO", s["esco_uri"], s.get("mapping_method") or "label_match",
                 "REFERENCE_MAPPED" if s["esco_status"] == "EXACT" else "NORMALIZED", kind="SKILL_TO_TAXONOMY")
    for d in ctx["demand"]:
        s = ctx["skills"][d["skill_key"]]
        edge(s["skill_uid"], "DEMANDED_BY", ctx["scope_uid"], "posting_prevalence", "OBSERVED" if d["posting_count"] else "NONE",
             {"posting_count": d["posting_count"], "support_state": d["support_state"]}, kind="INDUSTRY_DEMAND")
    node(ctx["scope_uid"], "INDUSTRY_POPULATION", "supplied job postings")
    for m in ctx["curriculum_mentions"]:
        if m.get("sense_established") and m["skill_key"] in ctx["skills"] and m["source_uid"] in nodes:
            edge(m["source_uid"], "MENTIONS", ctx["skills"][m["skill_key"]]["skill_uid"], m["method"], "EXTRACTED",
                 {"span": m["span"]}, kind="CURRICULUM_SKILL_MENTION")
    for r in ctx["occupations"]:
        if r["established"]:
            node(r["occupation_uri"], "OCCUPATION", r["occupation_label"])
            node(r["posting_uid"], "JOB_POSTING", r["job_title"])
            edge(r["posting_uid"], "APPEARS_IN", r["occupation_uri"], r["method"], "NORMALIZED", {"matched_label": r["matched_label"]},
                 kind="OCCUPATION")
    for tx in ctx["taxonomy"]:
        for b in tx["broader"]:
            node(b["uri"], "ESCO_SKILL_GROUP" if b["kind"] == "skill_group" else "ESCO_SKILL", b["label"])
            if tx["esco_uri"] in nodes:
                edge(b["uri"], "PARENT_OF", tx["esco_uri"], "esco_broader_relation", "REFERENCE_TAXONOMY_FACT",
                     kind="TAXONOMY_HIERARCHY")
                edge(tx["esco_uri"], "CHILD_OF", b["uri"], "esco_broader_relation", "REFERENCE_TAXONOMY_FACT",
                     kind="TAXONOMY_HIERARCHY")
    for se in ctx.get("semantic_edges", []):  # MODEL_SUPPORTED semantic decisions (evidence validator v2 passed)
        if se["source"] in nodes:
            node(se["target"], "ESCO_SKILL" if str(se["target"]).startswith("http") else "TOPIC", se.get("target_label"))
            edge(se["source"], se["relationship"], se["target"], f"semantic_v3:{se['model']}", "MODEL_SUPPORTED",
                 {"decision_id": se["decision_id"], "prompt_version": se["prompt_version"]}, kind="SEMANTIC_DECISION")
    ctx["_merged_duplicate_edges"] = sum(v[1] - 1 for v in seen.values())
    for drow in ctx["drift"]:
        if drow["concept_uid"] in nodes and drow.get("status") in ("ADDED", "REMOVED", "EXPANDED", "REDUCED"):
            nodes[drow["concept_uid"]].setdefault("drift_status", drow["status"])
    return list(nodes.values()), edges


GRAPH_RELATIONSHIPS = ("PARENT_OF", "CHILD_OF", "RELATED_TO", "SAME_AS", "MAPS_TO", "CONTAINS", "MENTIONS",
                       "DEMANDED_BY", "APPEARS_IN", "PREREQUISITE_OF")


def graph_consistency(nodes, edges):
    """Automated structural checks. Contradictions are reported, never silently resolved."""
    ids = {n["node_id"] for n in nodes}
    by_pair = defaultdict(set)
    seen, duplicates, dangling, self_parent = set(), 0, 0, []
    for e in edges:
        k = (e["source"], e["relationship"], e["target"])
        if k in seen:
            duplicates += 1
        seen.add(k)
        if e["source"] not in ids or e["target"] not in ids:
            dangling += 1
        by_pair[(e["source"], e["target"])].add(e["relationship"])
        if e["relationship"] in ("PARENT_OF", "CHILD_OF", "PREREQUISITE_OF") and e["source"] == e["target"]:
            self_parent.append(k)
    same_as = {(s, t) for (s, t), rels in by_pair.items() if "SAME_AS" in rels}
    asym_same = sorted((s, t) for s, t in same_as if (t, s) not in same_as)
    missing_inverse = sorted((s, r, t) for (s, t), rels in by_pair.items() for r in rels
                             if r in INVERSE and INVERSE[r] not in by_pair.get((t, s), set()))
    contradictions = []
    for (s, t), rels in by_pair.items():
        if "SAME_AS" in rels and ("UNRELATED" in rels or "PARENT_OF" in rels or "CHILD_OF" in rels):
            contradictions.append({"source": s, "target": t, "relationships": sorted(rels), "kind": "SAME_AS_WITH_HIERARCHY_OR_UNRELATED"})
        if "PARENT_OF" in rels and "PARENT_OF" in by_pair.get((t, s), set()):
            contradictions.append({"source": s, "target": t, "relationships": ["PARENT_OF", "PARENT_OF(reverse)"], "kind": "MUTUAL_PARENT"})
    cycles = {}
    for rel in ("PARENT_OF", "PREREQUISITE_OF"):
        adj = defaultdict(list)
        for e in edges:
            if e["relationship"] == rel and e["source"] != e["target"]:
                adj[e["source"]].append(e["target"])
        cycles[rel] = _cycles(adj)
    return {
        "nodes": len(nodes), "edges": len(edges),
        "nodes_by_type": dict(Counter(n["node_type"] for n in nodes)),
        "edges_by_relationship": dict(Counter(e["relationship"] for e in edges)),
        "edges_by_evidence_status": dict(Counter(str(e["evidence_status"]) for e in edges)),
        "checks": {
            "duplicate_edges": duplicates, "dangling_edges": dangling, "self_parent_or_self_prerequisite": len(self_parent),
            "same_as_not_symmetric": len(asym_same), "parent_child_missing_inverse": len(missing_inverse),
            "contradictions": len(contradictions),
            "parent_of_cycles": len(cycles["PARENT_OF"]), "prerequisite_cycles": len(cycles["PREREQUISITE_OF"]),
            "self_edges": sum(1 for e in edges if e["source"] == e["target"]),
            "invalid_relationship_types": sum(1 for e in edges if e["relationship"] not in GRAPH_RELATIONSHIPS),
            "edges_without_provenance": sum(1 for e in edges if not e.get("method") or not e.get("evidence_status")),
        },
        "examples": {"same_as_not_symmetric": asym_same[:5], "parent_child_missing_inverse": missing_inverse[:5],
                     "prerequisite_cycles": cycles["PREREQUISITE_OF"][:3], "parent_of_cycles": cycles["PARENT_OF"][:3]},
        "contradictions": contradictions[:200],
        "note": ("SAME_AS edges come from one-directional reference mappings (target topic -> reference topic); "
                 "asymmetry is reported, not repaired. Automated validation, not human validation."),
    }


def _cycles(adj, limit=50):
    colour, out = defaultdict(int), []
    for root in list(adj):
        if colour[root]:
            continue
        stack, path = [(root, iter(adj[root]))], [root]
        colour[root] = 1
        while stack and len(out) < limit:
            n, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                colour[n] = 2
                stack.pop()
                path.pop()
            elif colour[nxt] == 1:
                out.append(path[path.index(nxt):] + [nxt])
            elif colour[nxt] == 0:
                colour[nxt] = 1
                stack.append((nxt, iter(adj.get(nxt, ()))))
                path.append(nxt)
    return out


# ------------------------------------------------------------------ adjudication candidates

def adjudication_candidates(posting_mentions, mappings, topic_mappings, topics_by_uid, postings_by_uid, limit):
    """Pairs the deterministic layers left open. Candidate generation happens here, not in the model."""
    out = []
    for m in posting_mentions:
        if m["sense_state"] == "ALIAS_SENSE_REVIEW_REQUIRED":
            ev = m.get("sense_evidence") or {}
            p = postings_by_uid.get(m["source_uid"], {})
            out.append({"kind": "ALIAS_SENSE", "source_entity": m["mention_uid"], "candidate_entity": ev.get("esco_uri"),
                        "left": m["raw_mention"], "left_context": (m.get("context") or "")[:400],
                        "right": ev.get("esco_candidate"), "right_context": ev.get("esco_evidence"),
                        "question": ev.get("question"), "rule_relationship": "AMBIGUOUS",
                        "rule_reason": "alias sense not established by the text (rule layer)",
                        "rule_evidence": [f"posting {p.get('job_title')}"]})
    for surface, mp in sorted(mappings.items()):
        if mp["status"] == "AMBIGUOUS":
            for c in mp.get("candidates", [])[:3]:
                out.append({"kind": "AMBIGUOUS_TAXONOMY_LABEL", "source_entity": mp["mapping_uid"], "candidate_entity": c.get("uri"),
                            "left": surface, "left_context": "; ".join(mp.get("raw_mentions", [])[:3]),
                            "right": c.get("label"), "right_context": f"ESCO label kinds {c.get('label_kinds')}",
                            "question": f"Does '{surface}' denote the ESCO concept '{c.get('label')}'?",
                            "rule_relationship": "AMBIGUOUS", "rule_reason": "label shared by several ESCO concepts"})
    for tm in topic_mappings:
        if tm.get("relationship") == "AMBIGUOUS":
            src = topics_by_uid.get(tm["source_uid"], {})
            for c in (tm.get("evidence") or tm.get("explanation") or {}).get("candidates_considered", [])[:2]:
                out.append({"kind": "AMBIGUOUS_TOPIC_MAPPING", "source_entity": tm["mapping_uid"],
                            "candidate_entity": c.get("reference_topic_uid"), "left": src.get("clean_text") or tm.get("source_text"),
                            "left_context": src.get("unit_label"), "right": c.get("reference_text"), "right_context": None,
                            "rule_relationship": "AMBIGUOUS", "rule_reason": "two reference candidates too close"})
    return out[:limit]


# ------------------------------------------------------------------ semantic V3 candidates

def outcomes_by_course(outcomes):
    """Course outcomes grouped per course in a stable order (page, uid) -- used identically by freeze and pipeline."""
    out = defaultdict(list)
    for o in sorted(outcomes, key=lambda o: (o.get("page_number") or 0, o["outcome_uid"])):
        out[o["course_uid"]].append(o)
    return out


class V3Context:
    """Everything the V3 builder needs, loaded once (from pipeline memory or from a GOLD/SILVER run)."""

    def __init__(self, store, postings, posting_mentions, mappings, topic_mappings, topics_by_uid, courses_by_uid,
                 outcomes_by_course, curriculum_mentions=()):
        self.store, self.postings = store, postings
        self.mentions = {m["mention_uid"]: m for m in posting_mentions}
        self.mentions_by_surface = {}
        for m in sorted(posting_mentions, key=lambda x: x["mention_uid"]):
            self.mentions_by_surface.setdefault(m["normalized_text"], []).append(m)
        self.curriculum_by_surface = {}
        for m in sorted(curriculum_mentions, key=lambda x: x["mention_uid"]):
            self.curriculum_by_surface.setdefault(m["normalized_text"], []).append(m)
        self.mappings_by_uid = {m["mapping_uid"]: m for m in mappings.values()} if isinstance(mappings, dict) else \
            {m["mapping_uid"]: m for m in mappings}
        self.mappings_by_surface = {m["normalized_label"]: m for m in self.mappings_by_uid.values()}
        self.topic_mappings = {m["mapping_uid"]: m for m in topic_mappings}
        self.topics, self.courses, self.outcomes = topics_by_uid, courses_by_uid, outcomes_by_course
        self.unit_members = defaultdict(list)
        for t in sorted(topics_by_uid.values(), key=lambda x: (x.get("page_number") or 0, x["topic_uid"])):
            if t.get("noise_label") == "TOPIC":
                self.unit_members[(t["course_uid"], t.get("unit_label"))].append(t)

    def siblings(self, topic):
        return [t["clean_text"] for t in self.unit_members[(topic["course_uid"], topic.get("unit_label"))]
                if t["topic_uid"] != topic["topic_uid"]]


def v3_from_pool(c, ctx):
    """Rebuild one pool candidate (V2 shape) with V3 context. Returns None when its source is not available."""
    from app.knowledge_engine import semantic_v3 as v3
    if c["kind"] == "ALIAS_SENSE":
        m = ctx.mentions.get(c["source_entity"])
        p = ctx.postings.get(m["source_uid"]) if m else None
        if not m or not p or not c.get("candidate_entity"):
            return None
        mp = ctx.mappings_by_surface.get(m["normalized_text"], {})
        kind = (mp.get("mapping_method") or "alias").split("_")[0]
        note = (f"'{m['raw_mention']}' matched an English ESCO {kind} of '{c['right']}'; the deterministic rules could not "
                "establish from the text that this occurrence means that concept")
        return v3.alias_candidate(m, p.get("clean_description") or "", p.get("job_title") or "", c["candidate_entity"],
                                  ctx.store, note)
    if c["kind"] == "AMBIGUOUS_TAXONOMY_LABEL":
        occ = [(ctx.postings[m["source_uid"]].get("clean_description") or "", m["span"],
                ctx.postings[m["source_uid"]].get("job_title") or "", "JOB_TITLE")
               for m in ctx.mentions_by_surface.get(c["left"], []) if m["source_uid"] in ctx.postings]
        if not occ:  # the surface occurs only in curriculum topics
            for m in ctx.curriculum_by_surface.get(c["left"], []):
                t = ctx.topics.get(m["source_uid"])
                if t:
                    occ.append((t["clean_text"], m["span"], ctx.courses.get(t["course_uid"], {}).get("title") or "", "COURSE_TITLE"))
        note = f"the label '{c['left']}' belongs to several ESCO concepts; this is one of them"
        return v3.taxonomy_label_candidate(c["left"], occ, c["candidate_entity"], ctx.store, note)
    if c["kind"] == "AMBIGUOUS_TOPIC_MAPPING":
        tm = ctx.topic_mappings.get(c["source_entity"])
        t = ctx.topics.get((tm or {}).get("source_uid"))
        r = ctx.topics.get(c.get("candidate_entity"))
        if not t or not r:
            return None
        note = "two reference topics had near-equal lexical (TF-IDF) similarity to the LEFT topic; this is one of them"
        return v3.topic_candidate(t, ctx.courses.get(t["course_uid"], {}), ctx.siblings(t),
                                  [o["text"] for o in ctx.outcomes.get(t["course_uid"], [])],
                                  r, ctx.courses.get(r["course_uid"], {}), ctx.siblings(r), note)
    return None
