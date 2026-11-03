"""
Gap reasoning (Phase 6, experimental). Extends gap classification v2 (intelligence_stage.gap_v2) with the
directive's states; it does not replace v2, which stays authoritative until this layer is evaluated and promoted.

  NO_GAP               taught at SUBSTANTIAL / ADVANCED depth in a course every student takes (or whose status
                       the document does not print)
  LIMITED_COVERAGE     taught, but only in elective options; or not taught itself while a directly narrower concept
                       is (the skill is reached through a specific instance)
  DEPTH_GAP            taught only at INTRODUCTORY depth in a compulsory (or unprinted-status) course
  STRUCTURAL_GAP       not taught (ABSENT, or MENTION only) in a complete document
  INSUFFICIENT_EVIDENCE the skill did not reach ANALYTICALLY_ELIGIBLE (skill_intelligence), the document is partial
                       or prints no semesters, or the skill names the programme's own discipline
  REVIEW_REQUIRED      the curriculum evidence disagrees with itself: a course title or outcome claims the skill
                       while no syllabus topic teaches it (coverage UNCERTAIN), or a whole course is named after a
                       skill whose topics show only introductory depth (the release's COURSE_TITLE_NAMES_SKILL rule)
  OUTDATED_COVERAGE    taught at SUBSTANTIAL / ADVANCED depth while the industry trend is DECLINING / REPLACED
                       (needs >= 2 comparable posting periods: with one period it cannot fire, and says so)

Corroboration (the reference curriculum, the institution's other curriculum, peer curricula) is reported beside every
gap state and never decides it: a peer that teaches the skill strengthens the reading, it is not a requirement.
A broader concept being taught is reported as context only (the taxonomy is not proof).

An optional semantic coverage scorer (e.g. a future transformer comparing skill and syllabus text) is ADVISORY: its
output is recorded under "advisory" and never changes the state.
"""
import re

from app.knowledge_engine import curriculum_understanding as cu

METHOD = "gap reasoning v0.1 (experimental, deterministic; extends gap v2)"
STATES = ("NO_GAP", "LIMITED_COVERAGE", "DEPTH_GAP", "STRUCTURAL_GAP", "INSUFFICIENT_EVIDENCE", "REVIEW_REQUIRED",
          "OUTDATED_COVERAGE")
GAP_STATES = ("LIMITED_COVERAGE", "DEPTH_GAP", "STRUCTURAL_GAP")
TO_V2 = {"NO_GAP": "COVERED", "LIMITED_COVERAGE": "PARTIAL", "DEPTH_GAP": "PARTIAL", "STRUCTURAL_GAP": "MISSING",
         "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE", "REVIEW_REQUIRED": "REVIEW_REQUIRED",
         "OUTDATED_COVERAGE": "OUTDATED"}
DECLINING = ("DECLINING", "REPLACED")
DEEP = ("SUBSTANTIAL", "ADVANCED")


def _names_discipline(label, discipline):
    lab = re.sub(r"\s+", " ", (label or "").strip().lower())
    if len(lab) < 2 or not discipline:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(lab).replace("\\ ", "\\s+") + r"(?![a-z0-9])", discipline.lower()) is not None


def corroboration(key, others):
    """others: {doc_id: (role, coverage rows)} -> what the other curricula say about the skill (never decides)."""
    out = []
    for doc_id, (role, rows) in sorted(others.items()):
        r = rows.get(key)
        level = r["coverage_level"] if r else "ABSENT"
        out.append({"doc_id": doc_id, "role": role, "coverage_level": level,
                    "teaches": level in cu.TAUGHT_LEVELS})
    by_role = {}
    for o in out:
        by_role.setdefault(o["role"], []).append(o)
    summary = {role: f"{sum(o['teaches'] for o in os_)} of {len(os_)} teach it" for role, os_ in sorted(by_role.items())}
    return {"documents": out, "summary": summary}


def reason(stage_row, target, scope, discipline=None, trend="INSUFFICIENT_EVIDENCE", related=None, others=None,
           semantic_coverage=None):
    """
    One skill against one target curriculum.
      stage_row  skill_intelligence.stage(...)
      target     curriculum_understanding coverage record of the skill in the target document (None = no evidence)
      scope      the target document's scope (curriculum_understanding.document_scope)
      related    taxonomy_related(...) entry of the skill in the target, if any
      others     {doc_id: (role, coverage rows)} for corroboration
    """
    key = stage_row["skill_key"]
    c = target or cu.absent_record(key, None)
    level, access = c["coverage_level"], c["access"]
    reasons = []
    if not stage_row["eligible"]:
        state = "INSUFFICIENT_EVIDENCE"
        reasons.append(f"skill not analytically eligible: stopped at {stage_row['stopped_at']['stage']} "
                       f"({stage_row['stopped_at']['reason']})")
    elif _names_discipline(stage_row.get("skill_label"), discipline):
        state = "INSUFFICIENT_EVIDENCE"
        reasons.append(f"'{stage_row.get('skill_label')}' names the programme's own discipline ({discipline}); "
                       "topic coverage cannot measure it")
    elif level in DEEP and trend in DECLINING:
        state = "OUTDATED_COVERAGE"
        reasons.append(f"taught at {level} depth while the industry trend is {trend}")
    elif level in DEEP:
        if access == "ELECTIVE_ONLY":
            state = "LIMITED_COVERAGE"
            reasons.append(f"taught at {level} depth only in elective option(s) "
                           f"{', '.join(c['carrying_courses'])}: students who do not choose them are not taught it")
        else:
            state = "NO_GAP"
            reasons.append(f"{c['level_reason']}; access {access}")
    elif level == "INTRODUCTORY":
        titled = [e["course_code"] for e in c.get("evidence", []) if e["type"] in ("COURSE_TITLE", "PRACTICAL_TITLE")]
        if access == "ELECTIVE_ONLY":
            state = "LIMITED_COVERAGE"
            reasons.append(f"introduced only in elective option(s) {', '.join(c['carrying_courses'])}")
        elif titled:
            state = "REVIEW_REQUIRED"
            reasons.append(f"a whole course ({', '.join(sorted(set(map(str, titled))))}) is named after the skill, but "
                           f"only {c['level_reason']} teach it directly: the two kinds of evidence disagree on depth "
                           "(practical experiments are not extracted)")
        else:
            state = "DEPTH_GAP"
            reasons.append(f"taught only at introductory depth ({c['level_reason']})")
    elif level == "UNCERTAIN":
        state = "REVIEW_REQUIRED"
        reasons.append(c["level_reason"])
    else:  # ABSENT or MENTION
        nar = (related or {}).get("narrower_taught") or []
        if nar:
            state = "LIMITED_COVERAGE"
            reasons.append("not taught itself, but directly narrower concept(s) are: "
                           + ", ".join(f"{n['label']} ({n['level']})" for n in nar[:4])
                           + " (taxonomy relation: the skill is reached through a specific instance)")
        else:
            state = "STRUCTURAL_GAP"
            reasons.append("no syllabus topic, course title or outcome teaches it" if level == "ABSENT" else
                           "only mentioned where it qualifies another subject")
    # a partial document can show what is taught, never what is missing
    if state in GAP_STATES + ("REVIEW_REQUIRED",) and scope.get("state") != "COMPLETE":
        reasons.append(f"but the document scope is {scope.get('state')}: {scope.get('reason')}; absence or shallow "
                       "coverage in the supplied part does not show the programme lacks it")
        state = "INSUFFICIENT_EVIDENCE"
    out = {"skill_key": key, "skill_label": stage_row.get("skill_label"), "gap_state": state,
           "as_v2": TO_V2[state], "reasons": reasons, "coverage_level": level, "access": access,
           "practice": c["practice"], "cross_course": c["cross_course"], "carrying_courses": c["carrying_courses"],
           "strongest_evidence": c["strongest_evidence"], "evidence_types": c["evidence_types"],
           "skill_stage": stage_row["stage_reached"], "support_state": stage_row.get("support_state"),
           "industry_trend": trend, "document_scope": scope.get("state"),
           "broader_taught": [b["label"] for b in (related or {}).get("broader_taught", [])],
           "narrower_taught": [n["label"] for n in (related or {}).get("narrower_taught", [])],
           "evidence_status": "INFERRED", "is_source_evidence": False, "method": METHOD}
    if others is not None:
        out["corroboration"] = corroboration(key, others)
    if state == "NO_GAP" and c["practice"] == "THEORY_ONLY":
        out["note"] = "no practical course or paired practical names it (practical experiments are not extracted)"
    if semantic_coverage is not None:
        out["advisory"] = {"semantic_coverage": semantic_coverage(stage_row, c), "applied": False,
                           "note": "advisory only: recorded, never changes the gap state"}
    return out
