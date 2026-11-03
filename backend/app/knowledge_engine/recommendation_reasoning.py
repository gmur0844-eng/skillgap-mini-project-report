"""Recommendation reasoning: existing-course-first, least-disruptive intervention (EXPERIMENTAL).

The rule engine (analytics/recommendation_engine.py) maps a gap class to an action: PARTIAL -> expand an existing
topic, MISSING -> add an elective or, at high demand, a new subject. It decides from coverage percentages and does not
look at the curriculum it is recommending for. This module reads the curriculum evidence behind each issued
recommendation and states the least disruptive intervention that evidence supports. It never changes the rule
engine's output (that stays the authoritative record); it adds a reasoned action with its evidence, the alternatives
considered and the limitations.

Order of preference (structural change needs more evidence than strengthening what exists):
  1 EXPAND_EXISTING_TOPIC           the curriculum already teaches the skill directly or partially in named topics
  2 STRENGTHEN_EXISTING_COURSE      the skill appears only in passing in named courses
  3 REVIEW_BEFORE_CHANGE            no coverage in this document, but the document is incomplete (it covers fewer
                                    semesters than the institution's other curriculum) or the institution's other
                                    curriculum teaches the skill -- absence here is not established as a gap
  4 CONSIDER_ELECTIVE               no coverage found anywhere in the institution's evidence and demand is HIGH_SUPPORT
  5 CONSIDER_STANDALONE_COURSE      never inferred: it needs evidence that existing courses cannot absorb the skill, that
                                    the area is coherent and that the programme structure has room -- none of which
                                    the analysed documents establish. It is listed as an alternative considered.
A recommendation with only SUPPORTED (not HIGH_SUPPORT) demand and no coverage becomes REVIEW_BEFORE_CHANGE.

Deterministic; no thresholds are introduced (only the existing support states and coverage levels are read); nothing
names a discipline, institution or course. Semesters are compared as numbers (I..XII or 1..12).
"""
from __future__ import annotations

ACTIONS = {
    "EXPAND_EXISTING_TOPIC": "Expand an existing topic",
    "STRENGTHEN_EXISTING_COURSE": "Strengthen an existing course",
    "REVIEW_BEFORE_CHANGE": "Review the curriculum before recommending a change",
    "CONSIDER_ELECTIVE": "Consider a new elective",
    "CONSIDER_STANDALONE_COURSE": "Consider a new standalone course",
}
_TAUGHT = ("INTRODUCTORY", "SUBSTANTIAL", "ADVANCED")
_DIRECT = ("DIRECT", "PARTIAL")
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12}


def semester_number(value):
    s = str(value or "").strip().upper()
    if s in _ROMAN:
        return _ROMAN[s]
    return int(s) if s.isdigit() and 0 < int(s) <= 12 else None


def semesters_of(courses, doc_id):
    return sorted({n for c in courses if c.get("doc_id") == doc_id for n in [semester_number(c.get("semester"))] if n})


def _courses(rows, relations, titles, limit=4):
    seen, out = set(), []
    for e in rows or []:
        code = e.get("course_code")
        if e.get("relation") in relations and code and code not in seen:
            seen.add(code)
            out.append({"course_code": code, "title": titles.get(code), "page": e.get("page"), "topic": e.get("text")})
    return out[:limit]


def _names(cs):
    return ", ".join(f"{c['course_code']} {c['title']}".strip() if c.get("title") else c["course_code"] for c in cs)


def reason(recommendations, target_depth, institution_depth, target_titles, institution_titles,
           target_semesters, institution_semesters, institution_label=None):
    """One reasoned row per issued recommendation. target_depth / institution_depth: {skill_key: coverage row}."""
    rows = []
    incomplete = bool(target_semesters and institution_semesters and set(target_semesters) < set(institution_semesters))
    for r in recommendations:
        key = r["skill_key"]
        t = target_depth.get(key) or {}
        level = t.get("coverage_level") or "ABSENT"
        direct = _courses(t.get("evidence"), _DIRECT, target_titles)
        passing = _courses(t.get("evidence"), ("RELATED", "INCIDENTAL"), target_titles)
        inst = institution_depth.get(key) or {}
        inst_courses = (_courses(inst.get("evidence"), _DIRECT, institution_titles)
                        if inst.get("coverage_level") in _TAUGHT else [])
        why, limits, alternatives = [], [], []
        if level in _TAUGHT and direct:
            action = "EXPAND_EXISTING_TOPIC"
            why.append(f"The curriculum already covers it ({level.lower()}) in {_names(direct)}; expanding that "
                       "coverage is the least disruptive change.")
            alternatives.append({"action": "CONSIDER_ELECTIVE",
                                 "why_not": "existing coverage is the natural place to deepen it"})
        elif passing:
            action = "STRENGTHEN_EXISTING_COURSE"
            why.append(f"It appears only in passing in {_names(passing)}; strengthening that course is the least "
                       "disruptive change.")
            alternatives.append({"action": "CONSIDER_ELECTIVE",
                                 "why_not": "an existing course already touches the subject"})
        elif incomplete or inst_courses:
            action = "REVIEW_BEFORE_CHANGE"
            if incomplete:
                why.append(f"The analysed document covers semester(s) {', '.join(map(str, target_semesters))} only; "
                           f"the institution's other curriculum covers {', '.join(map(str, institution_semesters))}. "
                           "Absence from this document is not evidence that the programme does not teach it.")
            if inst_courses:
                why.append(f"The institution teaches it in {_names(inst_courses)}"
                           f"{' (' + institution_label + ')' if institution_label else ''}.")
            alternatives.append({"action": r.get("action_type"),
                                 "why_not": "a structural change is not supported until the full curriculum is reviewed"})
        elif r.get("support_state") == "HIGH_SUPPORT":
            action = "CONSIDER_ELECTIVE"
            why.append("No coverage was found in the analysed curriculum or the institution's other curriculum, and "
                       "industry support is high.")
            limits.append("Related courses that could absorb the skill are not identified automatically; review them "
                          "before creating an elective.")
        else:
            action = "REVIEW_BEFORE_CHANGE"
            why.append("No coverage was found, but industry support is below high support; a structural change needs "
                       "stronger evidence.")
        if action != "CONSIDER_STANDALONE_COURSE":
            alternatives.append({"action": "CONSIDER_STANDALONE_COURSE",
                                 "why_not": "not inferred: it needs evidence that existing courses cannot absorb the skill, "
                                            "that the area is coherent and that the programme has room for it"})
        if r.get("action_type") in ("ADD_NEW_SUBJECT", "ADD_ELECTIVE") and action not in ("CONSIDER_ELECTIVE",):
            limits.append(f"The rule engine proposed '{r.get('action_type')}' from coverage percentages alone; the "
                          "curriculum evidence above supports a smaller change.")
        rows.append({
            "skill_key": key, "skill_label": r.get("skill_label"), "recommendation_uid": r.get("recommendation_uid"),
            "rule_action": r.get("action_type"), "action": action, "action_label": ACTIONS[action],
            "support_state": r.get("support_state"), "target_coverage_level": level,
            "evidence": {"courses_teaching_it": direct, "courses_mentioning_it": passing,
                         "institution_courses_teaching_it": inst_courses,
                         "document_semesters": target_semesters, "institution_semesters": institution_semesters},
            "why": why, "alternatives_considered": alternatives, "limitations": limits,
            "evidence_state": "INFERRED", "method": "existing-course-first reasoning (deterministic, experimental)",
        })
    return rows
