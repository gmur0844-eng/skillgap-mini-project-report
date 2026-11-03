"""
Deterministic, evidence-based curriculum recommendation rule engine. Pure,
no DB, no LLM. Built on top of a gap-classification result (as returned by
app.analytics.gap_classification.classify_skill_gap) -- this module never
recomputes demand/coverage/trend/drift itself.

CONTROLLED ACTION VOCABULARY (spec Section 1) -- never invented dynamically.
"""

ACTION_ADD_NEW_SUBJECT = "ADD_NEW_SUBJECT"
ACTION_ADD_ELECTIVE = "ADD_ELECTIVE"
ACTION_ADD_MODULE = "ADD_MODULE"
ACTION_UPDATE_EXISTING_TOPIC = "UPDATE_EXISTING_TOPIC"
ACTION_EXPAND_EXISTING_TOPIC = "EXPAND_EXISTING_TOPIC"
ACTION_REVIEW_EXISTING_COURSE = "REVIEW_EXISTING_COURSE"

VALID_ACTIONS = {
    ACTION_ADD_NEW_SUBJECT, ACTION_ADD_ELECTIVE, ACTION_ADD_MODULE,
    ACTION_UPDATE_EXISTING_TOPIC, ACTION_EXPAND_EXISTING_TOPIC, ACTION_REVIEW_EXISTING_COURSE,
}

STATE_RECOMMENDATION_SUPPORTED = "RECOMMENDATION_SUPPORTED"
STATE_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
STATE_NO_ACTION_INDICATED = "NO_ACTION_INDICATED"

TARGET_PROGRAMME = "PROGRAMME"
TARGET_COURSE = "COURSE"


def generate_recommendation(gap_record, courses_with_evidence=None, related_skill_ids=None):
    """
    gap_record: the dict returned by classify_skill_gap.
    courses_with_evidence: list[str] of course_codes where ExtractedSkill
        evidence for this skill actually exists. Empty/None if none found.
    related_skill_ids: an optional set of OTHER skill_ids this recommendation
        is grouped with -- ONLY ever populated by the caller from real
        SkillRelationship data; this function never invents a relationship.
    """
    courses_with_evidence = sorted(courses_with_evidence) if courses_with_evidence else []
    grouped = sorted(related_skill_ids) if related_skill_ids else []
    classification = gap_record["classification"]
    reasons = []

    if classification == "INSUFFICIENT_EVIDENCE":
        reasons.append(
            f"Gap classification is INSUFFICIENT_EVIDENCE (evidence_state={gap_record.get('evidence_state')}); "
            f"no curriculum-change recommendation can be responsibly made without adequate evidence."
        )
        return {
            "recommendation_state": STATE_INSUFFICIENT_EVIDENCE,
            "action_type": None,
            "target_level": None,
            "target_course_codes": [],
            "grouped_skill_ids": grouped,
            "reasons": reasons,
        }

    if classification == "COVERED":
        if gap_record.get("demand_trend_signal") == "INCREASING_DEMAND" and courses_with_evidence:
            reasons.append(
                f"Skill is COVERED, but industry demand trend is INCREASING_DEMAND "
                f"(trend_label={gap_record.get('trend_label')}); reviewing the existing course(s) for "
                f"depth/currency is a proportionate action."
            )
            return {
                "recommendation_state": STATE_RECOMMENDATION_SUPPORTED,
                "action_type": ACTION_REVIEW_EXISTING_COURSE,
                "target_level": TARGET_COURSE,
                "target_course_codes": courses_with_evidence,
                "grouped_skill_ids": grouped,
                "reasons": reasons,
            }
        reasons.append("Skill is COVERED and no trend/drift evidence indicates a need for curriculum action.")
        return {
            "recommendation_state": STATE_NO_ACTION_INDICATED,
            "action_type": None,
            "target_level": None,
            "target_course_codes": [],
            "grouped_skill_ids": grouped,
            "reasons": reasons,
        }

    if classification == "PARTIAL":
        reasons.append(
            f"Curriculum coverage ({gap_record.get('curriculum_coverage_percentage')}%) is measurable but below "
            f"the configured partial-coverage threshold; industry demand "
            f"({gap_record.get('industry_demand_percentage')}%) is real and non-zero."
        )
        if courses_with_evidence:
            action = ACTION_EXPAND_EXISTING_TOPIC
            target_level = TARGET_COURSE
            reasons.append(f"Existing evidence of this skill found in course(s): {', '.join(courses_with_evidence)}.")
        else:
            action = ACTION_ADD_MODULE
            target_level = TARGET_PROGRAMME
            reasons.append(
                "No specific existing course could be identified as the source of the measured coverage; "
                "targeting the programme level rather than inventing a course."
            )
        _append_trend_reason(reasons, gap_record)
        if gap_record.get("drift_status"):
            reasons.append(f"Curriculum drift status for this skill: {gap_record['drift_status']} (descriptive context only).")
        return {
            "recommendation_state": STATE_RECOMMENDATION_SUPPORTED,
            "action_type": action,
            "target_level": target_level,
            "target_course_codes": courses_with_evidence,
            "grouped_skill_ids": grouped,
            "reasons": reasons,
        }

    reasons.append(
        f"Industry demand ({gap_record.get('industry_demand_percentage')}%) is real and non-zero; "
        f"measured curriculum coverage is genuinely zero."
    )
    if grouped:
        action = ACTION_ADD_MODULE
        reasons.append(f"Grouped with related skill(s) {grouped} based on existing taxonomy relationship data.")
    elif gap_record.get("high_demand"):
        action = ACTION_ADD_NEW_SUBJECT
        reasons.append("Industry demand meets the configured high-demand threshold, supporting a standalone new subject.")
    else:
        action = ACTION_ADD_ELECTIVE
        reasons.append(
            "Industry demand is real but below the high-demand threshold; an elective is a more proportionate "
            "action than a mandatory new subject."
        )
    _append_trend_reason(reasons, gap_record)
    if gap_record.get("drift_status"):
        reasons.append(f"Curriculum drift status for this skill: {gap_record['drift_status']} (descriptive context only).")

    return {
        "recommendation_state": STATE_RECOMMENDATION_SUPPORTED,
        "action_type": action,
        "target_level": TARGET_PROGRAMME,
        "target_course_codes": [],
        "grouped_skill_ids": grouped,
        "reasons": reasons,
    }


def _append_trend_reason(reasons, gap_record):
    signal = gap_record.get("demand_trend_signal")
    if signal == "INCREASING_DEMAND":
        reasons.append("Demand trend is INCREASING_DEMAND, strengthening the case for this recommendation.")
    elif signal == "DECREASING_DEMAND":
        reasons.append(
            "Demand trend is DECREASING_DEMAND; noted as evidence, but this does not by itself invalidate "
            "the current classification or reverse this recommendation -- a decrease is never treated as "
            "'outdated' without independent evidence."
        )
    elif signal == "STABLE_DEMAND":
        reasons.append("Demand trend is STABLE_DEMAND.")
    else:
        reasons.append("Trend evidence is insufficient; this recommendation rests on the current classification alone.")


def group_related_skills(candidate_skill_ids, skill_relationship_lookup):
    """
    candidate_skill_ids: skills eligible for grouping (e.g. all MISSING
        skills in one run).
    skill_relationship_lookup: {skill_id: set(related_skill_id)} built by the
        caller from REAL SkillRelationship rows -- an empty/missing entry
        means "no known relationship", never invented here.

    Returns a list of frozensets partitioning candidate_skill_ids via
    connected components over the relationship graph, restricted to
    candidate_skill_ids only.
    """
    parent = {sid: sid for sid in candidate_skill_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for sid in candidate_skill_ids:
        for related in skill_relationship_lookup.get(sid, set()):
            if related in candidate_skill_ids:
                union(sid, related)

    groups = {}
    for sid in candidate_skill_ids:
        root = find(sid)
        groups.setdefault(root, set()).add(sid)
    return [frozenset(g) for g in groups.values()]
