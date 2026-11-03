"""
Pipeline stage "intelligence" (engine 2.0). Runs after industry.gold, only when the full ESCO
classification is loaded. Produces GOLD files under intelligence/ and a report section. Additive:
no earlier output is modified (gap classification v2 is written next to v1, with the differences).
"""
import json
import re
from collections import Counter
from pathlib import Path

from app.knowledge_engine import curriculum_scope as scope_mod
from app.knowledge_engine import industry as ind
from app.knowledge_engine import intelligence as intel
from app.knowledge_engine.exports import write_json, write_jsonl
from app.knowledge_engine.silver import uid

SEMANTIC_DRIFT_CATEGORY = {"ADDED": "ADDED", "REMOVED": "REMOVED", "EXPANDED": "EXPANDED", "REDUCED": "REDUCED",
                           "RETAINED": "PERSISTENT", "RETAINED_REWORDED": "REWORDED", "UNCERTAIN": "INSUFFICIENT_EVIDENCE"}
_COURSE_LEVEL = "detected at COURSE level by topic-match lineage (course_drift.jsonl, /api/v1/curriculum/course-drift)"
NOT_DETECTED_DRIFT = {"RENAMED": "INSUFFICIENT_EVIDENCE at concept level (needs a validated same-concept decision across "
                                 "differently named concepts); " + _COURSE_LEVEL,
                      "MERGED": "INSUFFICIENT_EVIDENCE at concept level (needs many-to-one concept correspondence); " + _COURSE_LEVEL,
                      "SPLIT": "INSUFFICIENT_EVIDENCE at concept level (needs one-to-many concept correspondence); " + _COURSE_LEVEL,
                      "EVOLVED": "INSUFFICIENT_EVIDENCE at concept level (needs dated intermediate versions); " + _COURSE_LEVEL}


SUPPORTED_DEMAND = ("SUPPORTED", "HIGH_SUPPORT")


def _title_names(label, titles):
    """Target course titles that contain the skill label as whole words (case-insensitive)."""
    lab = re.sub(r"\s+", " ", (label or "").strip().lower())
    if len(lab) < 2:
        return []
    pat = re.compile(r"(?<![a-z0-9])" + re.escape(lab).replace("\\ ", "\\s+") + r"(?![a-z0-9])")
    return sorted({code for code, title in titles if pat.search((title or "").lower())})


def gap_v2(gaps, depth_by_key, trends_by_key, identity_by_key=None, target_titles=None, discipline=None,
           curriculum_scope=None):
    """
    v2 classification uses coverage DEPTH instead of 'any topic text names the skill':
      MISSING      demand supported, target coverage ABSENT or MENTION only (e.g. the label only qualifies
                   another subject)
      PARTIAL      INTRODUCTORY coverage
      COVERED      SUBSTANTIAL or ADVANCED coverage
      EMERGING     trend EMERGING (needs >= 2 periods; never from one posting)
      OUTDATED     trend DECLINING/REPLACED while coverage is SUBSTANTIAL/ADVANCED
      MISALIGNED   not produced: no detector (stated)
      INSUFFICIENT_EVIDENCE  v1 said so (demand support or discipline relevance not established)
    Every row also states, separately from its classification:
      curriculum_scope  the run's curriculum scope status (COMPLETE / INCOMPLETE / UNDETERMINED; curriculum_scope.py)
      scope_limited     PARTIAL/MISSING in a target that lacks semesters of the programme: absence from the supplied
                        semesters is not a whole-programme deficiency, so the gap is marked for review
                        (review CURRICULUM_SCOPE_INCOMPLETE) -- the classification itself is not changed
      actionable        the confirmed-gap rule (is_confirmed_gap) after every review mark
    """
    out = []
    for g in gaps:
        d = depth_by_key.get(g["skill_key"], {})
        level = d.get("coverage_level", "ABSENT")
        trend = trends_by_key.get(g["skill_key"], {}).get("trend_state", "INSUFFICIENT_EVIDENCE")
        if g["classification"] == "INSUFFICIENT_EVIDENCE":
            v2, why = "INSUFFICIENT_EVIDENCE", "unchanged from v1: " + "; ".join(g.get("reasons", [])[:2])
        elif trend == "EMERGING":
            v2, why = "EMERGING", "industry trend EMERGING"
        elif trend in ("DECLINING", "REPLACED") and level in ("SUBSTANTIAL", "ADVANCED"):
            v2, why = "OUTDATED", f"industry trend {trend} with {level} coverage"
        elif level in ("ABSENT", "MENTION") and g.get("support_state") not in SUPPORTED_DEMAND:
            # a missing-coverage gap is only claimed for demand that is established; thin demand stays insufficient
            v2, why = "INSUFFICIENT_EVIDENCE", (f"target coverage {level}, but industry demand support is "
                                               f"{g.get('support_state')}: a MISSING gap needs {'/'.join(SUPPORTED_DEMAND)} demand")
        elif level in ("ABSENT", "MENTION"):
            v2, why = "MISSING", f"target coverage {level}: {d.get('level_reason', 'no mention')}"
        elif level == "INTRODUCTORY":
            v2, why = "PARTIAL", d["level_reason"]
        else:
            v2, why = "COVERED", d["level_reason"]
        review = None
        if v2 in ("PARTIAL", "MISSING") and discipline and _title_names(g.get("skill_label"), [("discipline", discipline)]):
            # the "skill" is the name of the curriculum's own discipline ("computer science" for a Computer Science
            # and Engineering programme): the whole curriculum is about it, so topic-level coverage cannot measure it
            v2, why = "INSUFFICIENT_EVIDENCE", (f"{why}; but '{g.get('skill_label')}' names the curriculum's own "
                                               f"discipline ({discipline}), which topic coverage cannot measure")
        elif v2 in ("PARTIAL", "MISSING") and (identity_by_key or {}).get(g["skill_key"]) == "AMBIGUOUS":
            # the skill's identity is not established (its label belongs to several taxonomy concepts): which
            # skill the postings ask for is unknown, so no gap is stated
            v2, why = "INSUFFICIENT_EVIDENCE", (f"{why}; but the skill's identity is ambiguous in the taxonomy (its "
                                               "label belongs to several concepts), so no gap is stated")
        elif v2 in ("PARTIAL", "MISSING"):
            named = _title_names(g.get("skill_label"), target_titles or [])
            if named:
                # a target course is named after the skill while its topics show little coverage: the two kinds of
                # curriculum evidence disagree; the gap is kept but needs review before it is acted on
                review = {"code": "COURSE_TITLE_NAMES_SKILL", "courses": named,
                          "detail": (f"target course(s) {', '.join(named)} are named after this skill, but topic-level "
                                     f"coverage is {level}; the curriculum evidence disagrees and needs review")}
        scope_status = (curriculum_scope or {}).get("status") or scope_mod.NOT_ASSESSED
        scope_limited = v2 in ("PARTIAL", "MISSING") and scope_status == scope_mod.INCOMPLETE
        if scope_limited and review is None:
            review = {"code": "CURRICULUM_SCOPE_INCOMPLETE",
                      "missing_semesters": curriculum_scope.get("missing_semesters"),
                      "detail": (f"coverage is {level} in the supplied curriculum, which lacks semesters "
                                 f"{scope_mod.span_label(curriculum_scope.get('missing_semesters') or [])} of the programme; "
                                 "the skill may be taught there, so this is not a whole-programme deficiency until the "
                                 "full curriculum is analysed")}
        row = {"skill_key": g["skill_key"], "skill_label": g.get("skill_label"), "gap_uid": g["gap_uid"],
               "classification_v1": g["classification"], "classification_v2": v2, "changed": v2 != g["classification"],
               "reason_v2": why, "coverage_level": level, "coverage_relation": d.get("coverage_relation"),
               "support_state": g.get("support_state"), "industry_trend": trend,
               "evidence_status": "REVIEW_REQUIRED" if review else "INFERRED", "is_source_evidence": False,
               "curriculum_scope": scope_status, "scope_limited": scope_limited}
        if review:
            row["review"] = review
        row["actionable"] = is_confirmed_gap(row)
        out.append(row)
    return out


def is_confirmed_gap(g):
    """Partial or missing coverage, supported industry demand, and no unresolved disagreement in the evidence."""
    return (g.get("classification_v2") in ("PARTIAL", "MISSING") and g.get("support_state") in SUPPORTED_DEMAND
            and g.get("evidence_status") != "REVIEW_REQUIRED")


RECOMMENDABLE_V2 = ("PARTIAL", "MISSING")
# review code of a gap -> coded reason of the recommendation withheld for that review
REVIEW_TO_WITHHELD = {"COURSE_TITLE_NAMES_SKILL": "COURSE_TITLE_CONFLICT_REVIEW_REQUIRED",
                      "CURRICULUM_SCOPE_INCOMPLETE": "CURRICULUM_SCOPE_REVIEW_REQUIRED"}
# every reason that means "withheld until a reviewer decides" (consumers count these as withheld for review)
WITHHELD_FOR_REVIEW_CODES = ("CLASSIFICATION_CONFLICT_REVIEW_REQUIRED", "COURSE_TITLE_CONFLICT_REVIEW_REQUIRED",
                             "CURRICULUM_SCOPE_REVIEW_REQUIRED")


def reconcile_recommendations(industry_gold, gaps2):
    """
    Recommendations are produced in the industry stage from gap v1 (breadth: share of target courses whose topics
    name the skill). Gap v2 (depth: DIRECT/PARTIAL topics per unit) is computed afterwards and is what the Skill Gaps
    screen shows. A recommendation whose v2 classification is not a gap (e.g. v1 PARTIAL by breadth, v2 COVERED by
    depth) contradicts the displayed gap, so it is not issued: it becomes a suppression with the coded reason
    CLASSIFICATION_CONFLICT_REVIEW_REQUIRED, keeping the would-be action and both classifications for review.
    Nothing is deleted; the trace of the skill is updated to point at the suppression. Mutates industry_gold.
    """
    v2 = {g["skill_key"]: g for g in gaps2}
    kept, moved = [], []
    for r in industry_gold["recommendations"]:
        g2 = v2.get(r["skill_key"])
        if g2 is None or (g2["classification_v2"] in RECOMMENDABLE_V2 and not g2.get("review")):
            kept.append(r)
            continue
        conflict_reason = ({"code": REVIEW_TO_WITHHELD.get(g2["review"].get("code"), "COURSE_TITLE_CONFLICT_REVIEW_REQUIRED"),
                            "detail": g2["review"]["detail"]}
                           if g2.get("review") and g2["classification_v2"] in RECOMMENDABLE_V2 else
                           {"code": "GAP_NOT_ESTABLISHED", "detail": f"gap v2: {g2['reason_v2']}"}
                           if g2["classification_v2"] == "INSUFFICIENT_EVIDENCE" else None)
        sup = {"skill_key": r["skill_key"], "skill_label": r["skill_label"], "gap_uid": r["gap_uid"], "run_id": r["run_id"],
               "classification": r["classification"], "support_state": r["support_state"],
               "suppression_uid": uid("norec", r["gap_uid"]), "recommendation_state": "SUPPRESSED",
               "reasons": [conflict_reason or {"code": "CLASSIFICATION_CONFLICT_REVIEW_REQUIRED",
                            "detail": (f"gap v1 (breadth) is {r['classification']} but gap v2 (depth) is "
                                       f"{g2['classification_v2']} ({g2['coverage_level']}: {g2['reason_v2']}); the two coverage "
                                       "measures disagree, so no recommendation is issued until a reviewer decides")}],
               "evidence_status": "INSUFFICIENT_EVIDENCE" if (conflict_reason or {}).get("code") == "GAP_NOT_ESTABLISHED"
               else "REVIEW_REQUIRED",
               "withheld_recommendation": {k: r.get(k) for k in ("action_type", "target_level", "target_course_codes",
                                                                  "rule_reasons", "uncertainty")},
               "gap_v2": {"classification": g2["classification_v2"], "coverage_level": g2["coverage_level"],
                          "reason": g2["reason_v2"]}}
        moved.append(sup)
    if moved:
        industry_gold["recommendations"] = kept
        industry_gold["suppressions"] = sorted(industry_gold["suppressions"] + moved, key=lambda x: x["suppression_uid"])
        by_key = {m["skill_key"]: m for m in moved}
        for t in industry_gold.get("traces", []):
            if t["skill_key"] in by_key:
                t["recommendation"] = None
                t["no_recommendation"] = by_key[t["skill_key"]]
    return {"kept": len(kept), "withheld_for_classification_conflict": [m["skill_label"] for m in moved]}


def run(store, cfg, run_id, repo, documents, courses, clean_topics, topics_by_uid, courses_by_uid, concepts,
        topic_to_concept, topic_mappings, prereq_edges, drift_rows, outcomes, extraction, industry_gold, postings,
        target_doc, prev_doc, reference_doc, adjudicator=None, semantic_info=None, peer_requests=None, manifest=None,
        institution_doc=None, curriculum_scope=None):
    icfg = cfg["intelligence"]
    skills = extraction["skills"]
    demand = industry_gold["demand"]
    demand_keys = {d["skill_key"] for d in demand}
    demand_skills = {k: skills[k] for k in demand_keys}

    hierarchy, hierarchy_stats = intel.topic_hierarchy(clean_topics, icfg["hierarchy"])
    occ_rows, occ_summary = intel.occupation_analysis(postings, extraction["posting_mentions"], skills, store, icfg["occupations"])
    taxonomy = intel.skill_taxonomy_context({k: s for k, s in skills.items() if s["eligible_for_analytics"]
                                             or s.get("taxonomy_candidate_uri")}, store)

    # outcomes: the same extractor and mapping; only surfaces already mapped for topics/postings
    outcome_recs = [{**o, "doc_id": courses_by_uid[o["course_uid"]]["doc_id"]} for o in outcomes if o["course_uid"] in courses_by_uid]
    raw = ind.extract(outcome_recs, "text", "outcome_uid", extraction["_index"], "course_outcome")
    doc_of = {o["outcome_uid"]: o for o in outcome_recs}
    outcome_mentions = []
    for m in raw:
        mp = extraction["mappings"].get(m["normalized_text"])
        if mp and mp["skill_key"] in demand_keys:
            o = doc_of[m["source_uid"]]
            outcome_mentions.append({**m, "skill_key": mp["skill_key"], "doc_id": o["doc_id"], "text": o["text"],
                                     "course_uid": o["course_uid"]})

    depth = {}
    for role, doc in (("TARGET", target_doc), ("PREVIOUS_VERSION", prev_doc), ("REFERENCE", reference_doc)):
        if doc:
            depth[role] = intel.coverage_depth(extraction["curriculum_mentions"], topics_by_uid, courses_by_uid, doc["doc_id"],
                                               demand_skills, outcome_mentions, prereq_edges, icfg["coverage"])
            for r in depth[role]:
                r["role"] = role
    target_depth = depth.get("TARGET", [])
    trends = intel.industry_trends(demand, industry_gold["temporal"])
    versions = {"previous_date": (prev_doc or {}).get("academic_year"), "target_date": (target_doc or {}).get("academic_year")}
    lag = intel.curriculum_industry_lag(skills, target_depth, depth.get("PREVIOUS_VERSION", []), trends, versions)
    target_titles = [(c.get("course_code"), c.get("title")) for c in courses if c.get("doc_id") == target_doc["doc_id"]] \
        if target_doc else []
    gaps2 = gap_v2(industry_gold["gaps"], {r["skill_key"]: r for r in target_depth}, {t["skill_key"]: t for t in trends},
                   identity_by_key={k: s.get("esco_status") for k, s in skills.items()}, target_titles=target_titles,
                   discipline=(target_doc or {}).get("discipline"), curriculum_scope=curriculum_scope)
    reconciliation = reconcile_recommendations(industry_gold, gaps2)
    # existing-course-first reasoning over each issued recommendation (experimental; the rule engine's output is kept).
    # institution_doc: the same institution's other curriculum (an earlier version, or another programme)
    from app.knowledge_engine import recommendation_reasoning as rr
    inst_depth = ({r["skill_key"]: r for r in intel.coverage_depth(
        extraction["curriculum_mentions"], topics_by_uid, courses_by_uid, institution_doc["doc_id"], demand_skills,
        outcome_mentions, prereq_edges, icfg["coverage"])} if institution_doc else {})
    titles = lambda doc: {c.get("course_code"): c.get("title") for c in courses if doc and c.get("doc_id") == doc["doc_id"]}
    reasoning = rr.reason(
        industry_gold["recommendations"], {r["skill_key"]: r for r in target_depth}, inst_depth,
        titles(target_doc), titles(institution_doc),
        rr.semesters_of(courses, target_doc["doc_id"]) if target_doc else [],
        rr.semesters_of(courses, institution_doc["doc_id"]) if institution_doc else [],
        " ".join(str(institution_doc.get(k)) for k in ("programme", "curriculum_version") if institution_doc.get(k))
        if institution_doc else None)
    prereq_recs, prereq_info = intel.prerequisite_recommendations(industry_gold["recommendations"], skills, target_depth,
                                                                  store, run_id)

    drift_semantic = [{"concept_uid": r["concept_uid"], "concept": r["concept"], "engine_status": r["status"],
                       "semantic_drift_category": SEMANTIC_DRIFT_CATEGORY.get(r["status"], "INSUFFICIENT_EVIDENCE")}
                      for r in drift_rows]

    # peer benchmarking: target concepts vs every REFERENCE document supplied (no ranking, no score)
    ref_docs = [d for d in documents if d["role"] == "REFERENCE"]
    benchmark = {"peers_supplied": [{"doc_id": d["doc_id"], "institution": d["institution"], "programme": d["programme"]}
                                    for d in ref_docs],
                 "coverage_by_peer": {}, "note": "only supplied documents are benchmarked; no ranking or composite score",
                 "comparison_basis": "REFERENCE (model/regulatory curriculum), not a peer institution",
                 "peer_status": "PEER_DATA_NOT_AVAILABLE",
                 "peer_status_reason": "no curriculum of a peer institution was supplied in the source manifest; "
                                       "comparisons below are against REFERENCE documents only",
                 "requested_peers_not_supplied": list(peer_requests or [])}
    for d in ref_docs:
        rows = depth.get("REFERENCE", [])
        benchmark["coverage_by_peer"][d["doc_id"]] = {
            "comparison_role": "REFERENCE",
            "demand_skills_compared": len(rows),
            "target_levels": dict(Counter(r["coverage_level"] for r in target_depth)),
            "peer_levels": dict(Counter(r["coverage_level"] for r in rows)),
            "peer_covers_target_absent": sorted(r["skill_label"] for r in rows if r["coverage_level"] in ("INTRODUCTORY", "SUBSTANTIAL", "ADVANCED")
                                                and next((t["coverage_level"] for t in target_depth if t["skill_key"] == r["skill_key"]), "ABSENT")
                                                in ("ABSENT", "MENTION")),
            "target_covers_peer_absent": sorted(t["skill_label"] for t in target_depth if t["coverage_level"] in ("INTRODUCTORY", "SUBSTANTIAL", "ADVANCED")
                                                and next((r["coverage_level"] for r in rows if r["skill_key"] == t["skill_key"]), "ABSENT")
                                                in ("ABSENT", "MENTION")),
        }

    target_id = target_doc["doc_id"] if target_doc else None
    ctx = {"documents": documents, "courses": courses, "topics": clean_topics, "hierarchy": hierarchy, "concepts": concepts,
           "topic_to_concept": topic_to_concept, "mappings": topic_mappings, "prereq_edges": prereq_edges,
           "skills": skills, "demand": demand, "scope_uid": industry_gold["scope"]["scope_uid"],
           "curriculum_mentions": extraction["curriculum_mentions"], "occupations": occ_rows, "taxonomy": taxonomy,
           "drift": drift_rows}
    # ---- semantic decisions: industry kinds were decided during extraction (they may settle alias senses);
    # topic-mapping candidates are decided here (graph annotation only). Same protocol, same adjudicator.
    if adjudicator is None:
        adjudicator, semantic_info = semantic_setup(cfg, repo)
    outcomes_by_course = intel.outcomes_by_course(outcome_recs)
    by_uid = {p["posting_uid"]: p for p in postings}
    topic_pool = [c for c in intel.adjudication_candidates([], {}, topic_mappings, topics_by_uid, by_uid, icfg["adjudication_limit"])
                  if c["kind"] == "AMBIGUOUS_TOPIC_MAPPING"]
    ctx3 = intel.V3Context(store, by_uid, extraction["posting_mentions"], extraction["mappings"], topic_mappings,
                           topics_by_uid, courses_by_uid, outcomes_by_course, extraction["curriculum_mentions"])
    decisions = list((extraction.get("semantic") or {}).get("decisions", []))
    decisions += decide_v3(adjudicator, topic_pool, ctx3, cfg, semantic_info)
    candidates = decisions
    supported_edges = semantic_edges(decisions, topic_mappings, skills)
    # a model relationship enters the graph only when the pre-declared promotion gate passed; otherwise it stays a
    # recorded, validated decision (visible via /semantic/decisions) and is counted as blocked
    ctx["semantic_edges"] = supported_edges if gate_passed(semantic_info or {}) else []

    nodes, edges = intel.knowledge_graph(ctx)
    consistency = intel.graph_consistency(nodes, edges)
    consistency["duplicate_derivations_merged_at_build"] = ctx.get("_merged_duplicate_edges", 0)

    # evidence acquisition status (offline inspection of the Source Registry; see acquisition.py)
    from app.knowledge_engine import acquisition as acq
    evidence_status = acq.evaluate(repo, {
        "postings_by_period": (industry_gold.get("temporal") or {}).get("postings_by_period"),
        "peer_documents": sum(1 for d in documents if d["role"] == "PEER"),
        "reference_documents": [d["doc_id"] for d in documents if d["role"] == "REFERENCE"],
        "postings": occ_summary.get("postings"), "established_postings": occ_summary.get("established_postings"),
        "independent_labels": acq.count_independent_labels(repo)}, cfg.get("existing_settings") or {},
        manifest or {"requested_peer_sources": list(peer_requests or [])})

    report = {
        "status": "COMPLETE",
        "evidence_status": {e["requirement_id"]: e["status"] for e in evidence_status},
        "topic_hierarchy": hierarchy_stats,
        "occupations": occ_summary,
        "skills_with_taxonomy_context": len(taxonomy),
        "outcome_mentions_of_demand_skills": len(outcome_mentions),
        "coverage_levels": {role: dict(Counter(r["coverage_level"] for r in rows)) for role, rows in depth.items()},
        "coverage_relations_target": dict(Counter(r["coverage_relation"] for r in target_depth)),
        "industry_trends": dict(Counter(t["trend_state"] for t in trends)),
        "lag": dict(Counter(r["lag_state"] for r in lag)),
        "gaps_v1_to_v2": {"v1": dict(Counter(g["classification_v1"] for g in gaps2)),
                          "v2": dict(Counter(g["classification_v2"] for g in gaps2)),
                          "changed": [{"skill": g["skill_label"], "v1": g["classification_v1"], "v2": g["classification_v2"],
                                       "why": g["reason_v2"]} for g in gaps2 if g["changed"]]},
        "curriculum_scope": {"status": (curriculum_scope or {}).get("status") or scope_mod.NOT_ASSESSED,
                             "scope_limited_gaps": sum(1 for g in gaps2 if g["scope_limited"]),
                             "review_required_gaps": sum(1 for g in gaps2 if g["evidence_status"] == "REVIEW_REQUIRED"),
                             "actionable_gaps": sum(1 for g in gaps2 if g["actionable"])},
        "prerequisite_recommendations": len(prereq_recs), "recommendation_rules": prereq_info,
        "recommendation_reconciliation": reconciliation,
        "recommendation_reasoning": {"method": "existing-course-first (deterministic, experimental)",
                                     "actions": dict(Counter(r["action"] for r in reasoning)),
                                     "rule_actions": dict(Counter(r["rule_action"] for r in reasoning))},
        "semantic_drift_categories": dict(Counter(r["semantic_drift_category"] for r in drift_semantic)),
        "semantic_drift_not_detected": NOT_DETECTED_DRIFT,
        "peer_benchmark": benchmark,
        "knowledge_graph": {k: consistency[k] for k in ("nodes", "edges", "nodes_by_type", "edges_by_relationship", "checks")},
        "semantic_adjudication": {**adjudicator.describe(), "mode": semantic_info["mode"],
                                  "replay": semantic_info.get("replay"), "replay_rejected": semantic_info.get("replay_rejected"),
                                  "gate": semantic_info.get("gate"), "candidates": len(candidates),
                                  "decisions_by_state": dict(Counter(d["decision_state"] for d in decisions)),
                                  "decisions_by_validated_state": dict(Counter(d.get("validated_state") for d in decisions)),
                                  "effects": dict(Counter(d.get("effect") for d in decisions if d.get("effect"))),
                                  "effects_blocked": sum(1 for d in decisions if d.get("effect_blocked_reason")),
                                  "candidates_by_kind": dict(Counter(d["candidate_kind"] for d in decisions)),
                                  "semantic_graph_edges": len(ctx["semantic_edges"]),
                                  "semantic_graph_edges_blocked_by_gate": len(supported_edges) - len(ctx["semantic_edges"])},
    }
    summary_counts = {"subtopics": hierarchy_stats.get("subtopics", 0), "established_occupation_postings": occ_summary["established_postings"],
                      "graph_nodes": consistency["nodes"], "graph_edges": consistency["edges"],
                      "adjudication_candidates": len(candidates), "ai_provider": adjudicator.status}
    return {"hierarchy": hierarchy, "occupations": occ_rows, "taxonomy": taxonomy, "outcome_mentions": outcome_mentions,
            "depth": depth, "trends": trends, "lag": lag, "gaps_v2": gaps2, "prerequisite_recommendations": prereq_recs,
            "recommendation_reasoning": reasoning,
            "drift_semantic": drift_semantic, "benchmark": benchmark, "graph_nodes": nodes, "graph_edges": edges,
            "consistency": consistency, "decisions": decisions, "report": report, "summary_counts": summary_counts,
            "evidence_status": evidence_status,
            "target_doc": target_id, "curriculum_scope": curriculum_scope or scope_mod.not_assessed()}


def write(d, out):
    write_jsonl(d / "topic_hierarchy.jsonl", out["hierarchy"], sort_key=lambda r: r["hierarchy_uid"])
    write_jsonl(d / "posting_occupations.jsonl", out["occupations"], sort_key=lambda r: r["posting_uid"])
    write_jsonl(d / "skill_taxonomy_context.jsonl", out["taxonomy"], sort_key=lambda r: r["skill_key"])
    write_jsonl(d / "outcome_skill_mentions.jsonl",
                [{k: v for k, v in m.items() if k != "text"} for m in out["outcome_mentions"]],
                sort_key=lambda r: (r["source_uid"], r["span"][0]))
    write_jsonl(d / "coverage_depth.jsonl", [r for rows in out["depth"].values() for r in rows],
                sort_key=lambda r: (r["role"], r["skill_key"]))
    write_jsonl(d / "industry_trends.jsonl", out["trends"], sort_key=lambda r: r["skill_key"])
    write_jsonl(d / "curriculum_industry_lag.jsonl", out["lag"], sort_key=lambda r: r["skill_key"])
    write_jsonl(d / "skill_gaps_v2.jsonl", out["gaps_v2"], sort_key=lambda r: r["skill_key"])
    write_json(d / "curriculum_scope.json", out["curriculum_scope"])
    write_jsonl(d / "recommendation_reasoning.jsonl", out.get("recommendation_reasoning", []), sort_key=lambda r: r["skill_key"])
    write_jsonl(d / "prerequisite_recommendations.jsonl", out["prerequisite_recommendations"],
                sort_key=lambda r: r["recommendation_uid"])
    write_jsonl(d / "semantic_drift.jsonl", out["drift_semantic"], sort_key=lambda r: r["concept_uid"])
    write_json(d / "peer_benchmark.json", out["benchmark"])
    write_json(d / "evidence_status.json", {"requirements": out["evidence_status"],
                                             "note": "offline inspection of data/metadata/source_registry.json; "
                                                     "acquisition itself runs via scripts/acquisition/acquire_evidence.py"})
    write_jsonl(d / "graph_nodes.jsonl", out["graph_nodes"], sort_key=lambda r: r["node_id"])
    write_jsonl(d / "graph_edges.jsonl", out["graph_edges"], sort_key=lambda r: r["edge_id"])
    write_json(d / "graph_consistency.json", out["consistency"])
    # replay misses: the exact V3 candidates (all items shown to the model + hashes) so they can be frozen and decided
    # by the model on its host (scripts/semantic/freeze_pending_candidates.py) -- never guessed here
    write_jsonl(d / "semantic_pending_candidates.jsonl",
                [x["pending_candidate"] for x in out["decisions"] if x.get("pending_candidate")],
                sort_key=lambda r: r["candidate_id"])
    write_jsonl(d / "semantic_decisions.jsonl", [{k: v for k, v in x.items() if k not in ("from_cache", "pending_candidate")}
                                                 for x in out["decisions"]],
                sort_key=lambda r: r["decision_id"])
    write_json(d / "intelligence_report.json", out["report"])


def bundle(run_id, out, skills, store):
    """Rows for db_publish (engine 2.0 tables)."""
    uid_of = {k: s["skill_uid"] for k, s in skills.items()}
    occs = sorted({r["occupation_uri"] for r in out["occupations"] if r["occupation_uri"]})
    adj = out["report"]["semantic_adjudication"]
    prov = adj["provider"]
    return {
        "esco_occupation": [{"occupation_uri": u, "pref_label": store["occupations"][u]["pref_label"],
                             "isco_code": store["occupations"][u]["isco_code"]} for u in occs],
        "posting_occupation": [{"run_id": run_id, "posting_uid": r["posting_uid"], "status": r["status"],
                                "established": r["established"], "occupation_uri": r["occupation_uri"],
                                "matched_label": r["matched_label"],
                                "isco_major_code": (r.get("isco_major_group") or {}).get("code")} for r in out["occupations"]],
        "topic_hierarchy": [{k: h[k] for k in ("hierarchy_uid", "course_uid", "parent_node_uid", "parent_text", "child_text",
                                               "position", "child_topic_uid", "method", "page_number")} for h in out["hierarchy"]],
        "concept_coverage": [{"run_id": run_id, "skill_uid": uid_of[r["skill_key"]], "doc_role": r["role"],
                              "coverage_level": r["coverage_level"], "coverage_relation": r["coverage_relation"],
                              "courses_direct_or_partial": r["courses_direct_or_partial"],
                              "units_direct_or_partial": r["units_direct_or_partial"], "outcome_mentions": r["outcome_mentions"],
                              "level_reason": r["level_reason"]} for rows in out["depth"].values() for r in rows],
        "skill_gap_v2": [{"gap_uid": g["gap_uid"], "run_id": run_id, "classification_v1": g["classification_v1"],
                          "classification_v2": g["classification_v2"], "coverage_level": g["coverage_level"],
                          "industry_trend": g["industry_trend"], "reason_v2": g["reason_v2"], "is_source_evidence": False}
                         for g in out["gaps_v2"]],
        "semantic_model_run": [{"run_id": run_id, "provider_status": adj["status"], "provider": prov.get("provider"),
                                "model": prov.get("model"), "prompt_version": adj["prompt_version"],
                                "candidates": adj["candidates"], "cache_hits": adj["stats"]["cache_hits"]}],
        "semantic_decision": list({(d["decision_id"]): {"run_id": run_id, "decision_id": d["decision_id"],
                                   "candidate_kind": d["candidate_kind"], "source_entity": d["source_entity"],
                                   "candidate_entity": d["candidate_entity"], "left_text": d["left"], "right_text": d["right"],
                                   "relationship": d["relationship"], "decision_state": d["decision_state"],
                                   "provider": d["provider"], "model": d["model"], "prompt_version": d["prompt_version"],
                                   "input_hash": d["input_hash"], "context_hash": d["context_hash"],
                                   "output_hash": d["output_hash"], "is_human_validated": d["is_human_validated"],
                                   "validated_state": d.get("validated_state"),
                                   "validation_findings": __import__("json").dumps(d.get("validation_findings") or []),
                                   "effect": d.get("effect")}
                                   for d in out["decisions"]}.values()),
        "concept_relationship": list({e["edge_id"]: {"edge_id": e["edge_id"], "run_id": run_id, "source": e["source"],
                                      "relationship": e["relationship"], "target": e["target"], "method": e["method"],
                                      "evidence_status": e["evidence_status"], "mapping_kind": e.get("mapping_kind")}
                                      for e in out["graph_edges"]}.values()),
        "semantic_contradiction": list({(c["source"], c["target"], c["kind"]): {"run_id": run_id, "source": c["source"],
                                        "target": c["target"], "kind": c["kind"],
                                        "relationships": __import__("json").dumps(c["relationships"])}
                                        for c in out["consistency"]["contradictions"]}.values()),
    }


# ------------------------------------------------------------------ semantic engine V3 (live or recorded)

REPLAY_ENTRY_FIELDS = ("cache_file", "cache_sha256", "gate_file", "gate_sha256")


def semantic_setup(cfg, repo, mode=None):
    """Adjudicator for the configured protocol. Live provider when reachable; otherwise, when a verified recorded run
    is registered (config `semantic_replay`), the recorded decisions of that run; otherwise the deterministic fallback.
    mode "replay" (the argument, else the SEMANTIC_MODE environment variable) never goes live: release builds and the
    app's upload analyses use it, so a run's result does not depend on whether a model server happens to be running."""
    import hashlib
    from app.knowledge_engine import semantic_provider as sp
    protocol = sp.protocol_for(cfg.get("semantic_ai", {}).get("prompt_version", "adjudicate-v2"))
    import os
    probes = sp.discover_providers(cfg)
    live = [(p, pr) for p, pr in probes if p is not None and pr.get("available")]
    cache_dir = repo / "data/cache/semantic_decisions"
    info = {"protocol": protocol.prompt_version, "schema": protocol.schema_version, "probes": [pr for _, pr in probes],
            "mode": None, "replay": None, "gate": None}
    requested = (mode or os.environ.get("SEMANTIC_MODE") or "").strip().lower()
    if requested == "replay":
        # replay the verified recording even when a model endpoint is reachable
        live, info["live_disabled"] = [], "SEMANTIC_MODE=replay" if not mode else "semantic_mode=replay"
    runs = (cfg.get("semantic_replay") or {}).get("runs") or []
    pinned = [repo / r["cache_file"] for r in runs if r.get("cache_file")]
    if live:
        # live decisions go to their own namespace: they never append to (or are served from) a hash-pinned
        # recording, and the live model's digest is part of the cache key, so a changed model is never served stale
        info["mode"] = "LIVE"
        return sp.Adjudicator(cfg, cache_dir / "live", "pipeline", providers=live[:1], protocol=protocol,
                              pinned_files=pinned), info
    ollama = next((p for p, pr in probes if p is not None and pr.get("kind") == "ollama"), None)
    for r in runs:
        # a malformed registry entry is rejected like any other unverifiable recording, never an exception
        missing = [k for k in REPLAY_ENTRY_FIELDS if not r.get(k)]
        if missing:
            info.setdefault("replay_rejected", []).append({"run": r.get("name"), "reason": "hash, provider or protocol mismatch",
                                                           "missing_fields": missing})
            continue
        f, g = repo / r["cache_file"], repo / r["gate_file"]
        ok = f.exists() and hashlib.sha256(f.read_bytes()).hexdigest() == r["cache_sha256"] and \
            g.exists() and hashlib.sha256(g.read_bytes()).hexdigest() == r["gate_sha256"]
        if not ok or ollama is None or r.get("prompt_version") != protocol.prompt_version:
            info.setdefault("replay_rejected", []).append({"run": r.get("name"), "reason": "hash, provider or protocol mismatch"})
            continue
        spec = next((x for x in (cfg.get("semantic_ai") or {}).get("providers", []) if x.get("kind") == "ollama"), {})
        recorded = sp.RecordedProvider(ollama, recorded_base_url=r.get("provider_base_url") or spec.get("base_url"))
        adj = sp.Adjudicator(cfg, cache_dir, "pipeline", providers=[(recorded, {"available": True})],
                             protocol=protocol, readonly_cache=True, pinned_files=pinned)
        adj.status = "AI_PROVIDER_REPLAYED"
        if adj.cache_file.name != Path(r["cache_file"]).name:
            info.setdefault("replay_rejected", []).append({"run": r.get("name"), "reason": "cache key of this configuration differs"})
            continue
        info.update(mode="REPLAY_VERIFIED_RUN", replay={k: r.get(k) for k in ("name", "cache_file", "cache_sha256")},
                    gate=json.loads(g.read_text()))
        return adj, info
    info["mode"] = "DETERMINISTIC_FALLBACK"
    return sp.Adjudicator(cfg, cache_dir, "pipeline", providers=[], protocol=protocol, pinned_files=pinned), info


def semantic_identity(adjudicator, info):
    """What the semantic layer of a run IS: mode, the adjudicator's model key (provider, model, digest, prompt,
    schema, settings) and the replayed recording's hash. Part of the run id, so a LIVE run and a REPLAY run of the
    same inputs are different runs and never overwrite each other's GOLD directory."""
    return "|".join([info.get("mode") or "-", adjudicator.model_key, ((info.get("replay") or {}).get("cache_sha256")) or "-"])


def gate_passed(info):
    """A promotion gate counts only when a verified replay/live run supplied one and it passed."""
    return bool((info.get("gate") or {}).get("passed"))


def decide_v3(adjudicator, pool, ctx, cfg, info):
    """V3 decisions for pool candidates, each re-validated by the CURRENT evidence validator (authoritative).
    effect = the configured promotion effect, only for MODEL_SUPPORTED decisions of a run whose gate PASSED."""
    from app.knowledge_engine import semantic_v3 as v3
    effects = (cfg["semantic_ai"].get("promotion") or {}).get("effects", {})
    passed = gate_passed(info)
    out = []
    for c in pool:
        c3 = intel.v3_from_pool(c, ctx)
        if c3 is None:
            continue
        c3.update(source_entity=c.get("source_entity"), candidate_entity=c.get("candidate_entity"))
        d = adjudicator.decide(c3)
        state, findings = (v3.validate_decision(d_out(d), c3) if d["decision_state"] == "MODEL_SUGGESTED"
                           else (d["decision_state"], [f"MODEL_STATE:{d['decision_state']}"]))
        d = {k: v for k, v in d.items() if k not in ("from_cache", "rejected_raw_outputs")}
        if d["decision_state"] == "MODEL_FAILURE" and getattr(adjudicator, "status", None) == "AI_PROVIDER_REPLAYED":
            # replay miss: the input/context differs from every recorded decision; the model was not called
            d.update(reason="REPLAY_MISS: no recorded decision for this exact input and context; the model was not called",
                     uncertainty="not decided in this run", timestamp=None, latency_s=None, attempts=0,
                     pending_candidate={**c3, "candidate_id": "pend:" + d["input_hash"][:16] + d["context_hash"][:8],
                                        "input_hash": d["input_hash"], "context_hash": d["context_hash"]})
        d.update(validated_state=state, validation_findings=findings, validator=v3.VALIDATOR_VERSION,
                 source_entity=c.get("source_entity"), candidate_entity=c.get("candidate_entity"), candidate_kind=c["kind"])
        effect = effects.get(c["kind"], {}).get(d["relationship"]) if state == "MODEL_SUPPORTED" else None
        d["effect"] = effect if (effect and passed) else None
        d["effect_blocked_reason"] = None if (d["effect"] or not effect) else "promotion gate did not pass"
        out.append(d)
    return out


def semantic_edges(decisions, topic_mappings, skills):
    """Graph edges for MODEL_SUPPORTED definite decisions (UNRELATED adds no edge). Evidence = the decision."""
    rel = {"SAME_CONCEPT": "SAME_AS", "PARENT": "PARENT_OF", "CHILD": "CHILD_OF", "RELATED": "RELATED_TO",
           "PARTIAL_OVERLAP": "RELATED_TO"}
    tm = {m["mapping_uid"]: m for m in topic_mappings}
    surface_skill = {}
    for s in skills.values():
        for surf in s["surfaces"]:
            surface_skill[surf] = s["skill_uid"]
    out = []
    for d in decisions:
        if d.get("validated_state") != "MODEL_SUPPORTED" or d["relationship"] not in rel:
            continue
        if d["candidate_kind"] == "AMBIGUOUS_TOPIC_MAPPING":
            src = (tm.get(d["source_entity"]) or {}).get("source_uid")
        elif d["candidate_kind"] == "AMBIGUOUS_TAXONOMY_LABEL":
            src = surface_skill.get(d["left"])
        else:
            continue  # alias decisions act on mention senses, not on graph edges
        if src and d.get("candidate_entity"):
            out.append({"source": src, "relationship": rel[d["relationship"]], "target": d["candidate_entity"],
                        "target_label": d["right"], "decision_id": d["decision_id"], "model": d["model"],
                        "prompt_version": d["prompt_version"]})
    return out


def industry_sense_resolver(cfg, adjudicator, info, store, topics_by_uid, courses_by_uid, outcomes_by_course):
    """Callable for industry_stage.extract_and_map: V3 decisions on alias/label candidates; effects only when the
    promotion gate of the replayed/live run PASSED and the decision is MODEL_SUPPORTED by the evidence validator."""

    def resolve(posting_mentions, curriculum_mentions, mappings, postings):
        by_uid = {p["posting_uid"]: p for p in postings}
        pool = intel.adjudication_candidates(posting_mentions, mappings, [], {}, by_uid, cfg["intelligence"]["adjudication_limit"])
        ctx = intel.V3Context(store, by_uid, posting_mentions, mappings, [], topics_by_uid, courses_by_uid, outcomes_by_course,
                              curriculum_mentions)
        decisions = decide_v3(adjudicator, pool, ctx, cfg, info)
        resolved = {d["source_entity"]: (d["effect"], {"decision_id": d["decision_id"], "relationship": d["relationship"],
                                                        "validated_state": d["validated_state"], "model": d["model"],
                                                        "prompt_version": d["prompt_version"]})
                    for d in decisions if d["effect"] and d["candidate_kind"] == "ALIAS_SENSE"}
        report = {"mode": info["mode"], "decisions": decisions, "established_by_model": sum(1 for v in resolved.values() if v[0] == "ESTABLISHED_BY_MODEL"),
                  "rejected_by_model": sum(1 for v in resolved.values() if v[0] == "REJECTED_BY_MODEL"),
                  "gate_passed": gate_passed(info)}
        return resolved, report
    return resolve


def d_out(d):
    return {k: d.get(k) for k in ("relationship", "reason", "evidence", "direction_justification", "alternatives", "uncertainty")}
