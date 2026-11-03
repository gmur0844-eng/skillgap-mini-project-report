"""Curriculum scope (regression for the R26 analysis da7a75d8501e81a6, 2026-10-10).

An uploaded CBIT CSE (AIML) curriculum covering semesters I-II only was compared with industry demand as if it were a
whole programme: all 243 demand skills came out ABSENT and 24 skills were reported as evidence-supported gaps
(SQL, machine learning, operating systems, ...), which the later semesters may well teach.

Guards:
  * the expected programme span is derived from the other curricula of the analysis (no discipline rule, no fixed
    semester count); one partial document cannot lower it, one document alone cannot set it;
  * an incomplete target keeps every classification but marks its PARTIAL/MISSING gaps for review, so they are not
    actionable and their recommendations are withheld with a coded reason;
  * a complete target and an undetermined scope change nothing;
  * runs made before the assessment report NOT_ASSESSED.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import curriculum_scope as cs  # noqa: E402
from app.knowledge_engine import intelligence_stage as ist  # noqa: E402

DISC = "Computer Science and Engineering"
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


def doc(doc_id, role="PEER", discipline=DISC, level=None):
    return {"doc_id": doc_id, "role": role, "discipline": discipline, "degree_level": level}


def courses(sems, roman=True):
    return [{"course_uid": f"c{s}{i}", "semester": (ROMAN[s - 1] if roman else str(s)) if s else None}
            for s in sems for i in range(2)]


# ------------------------------------------------------------------ semester labels
def test_semester_labels():
    for label, n in (("I", 1), ("iv", 4), ("VIII", 8), ("IX", 9), ("XII", 12), ("3", 3), ("Semester 3", 3),
                     ("Sem-IV", 4), (" ii ", 2)):
        assert cs.parse_semester(label) == n, label
    for label in (None, "", "None", "0", "21", "iiii", "vx", "Year 1", "odd"):
        assert cs.parse_semester(label) is None, label
    assert cs.span_label([1, 2, 3, 5, 7, 8]) == "I–III, V, VII–VIII"


# ------------------------------------------------------------------ the assessment
def release_like():
    """The published release: target I-VIII; AICTE I-VIII; the earlier version R22 only I-IV; a peer 1-8; peers
    without semester labels."""
    docs = [doc("aicte", "REFERENCE"), doc("r22", "PREVIOUS_VERSION"), doc("r22a", "TARGET"), doc("nitw"), doc("iitk")]
    by_doc = {"aicte": courses(range(1, 9)), "r22": courses(range(1, 5)), "r22a": courses(range(1, 9)),
              "nitw": courses(range(1, 9), roman=False), "iitk": courses([None])}
    return docs, by_doc


def test_complete_curriculum_is_complete_and_a_partial_earlier_version_does_not_lower_the_span():
    docs, by_doc = release_like()
    a = cs.assess(docs[2], docs, by_doc, {"min_agreeing_documents": 2})
    assert a["status"] == cs.COMPLETE and a["expected_last_semester"] == 8 and a["missing_semesters"] == []
    used = {c["doc_id"]: c["used"] for c in a["comparison"]}
    assert used == {"aicte": True, "r22": True, "nitw": True, "iitk": False}
    assert a["note"] is None


def test_first_year_curriculum_is_incomplete_with_the_missing_semesters_named():
    docs = [doc("aicte", "REFERENCE"), doc("r22a", "PREVIOUS_VERSION"), doc("nitw"), doc("r26", "TARGET", level="undergraduate")]
    by_doc = {"aicte": courses(range(1, 9)), "r22a": courses(range(1, 9)), "nitw": courses(range(1, 9), roman=False),
              "r26": courses([1, 2])}
    a = cs.assess(docs[3], docs, by_doc, {"min_agreeing_documents": 2})
    assert a["status"] == cs.INCOMPLETE and a["expected_last_semester"] == 8
    assert a["target_semesters"] == [1, 2] and a["missing_semesters"] == [3, 4, 5, 6, 7, 8]
    assert "semesters I–II" in a["note"] and "III–VIII" in a["note"] and "may be taught" in a["note"]


def test_the_span_comes_from_the_data_not_a_fixed_count():
    # a six-semester programme family: a target with I-VI is complete, one with I-IV is not
    docs = [doc("a"), doc("b"), doc("t", "TARGET")]
    six = {"a": courses(range(1, 7)), "b": courses(range(1, 7))}
    assert cs.assess(docs[2], docs, {**six, "t": courses(range(1, 7))})["status"] == cs.COMPLETE
    a = cs.assess(docs[2], docs, {**six, "t": courses(range(1, 5))})
    assert a["status"] == cs.INCOMPLETE and a["missing_semesters"] == [5, 6]


def test_no_reliable_span_is_undetermined():
    t = doc("t", "TARGET")
    # one full comparison curriculum alone cannot set the span
    a = cs.assess(t, [t, doc("a")], {"t": courses([1, 2]), "a": courses(range(1, 9))})
    assert a["status"] == cs.UNDETERMINED and a["expected_last_semester"] is None and "at least 2" in a["reason"]
    # comparison curricula without semester labels
    a = cs.assess(t, [t, doc("a"), doc("b")], {"t": courses([1, 2]), "a": courses([None]), "b": courses([None])})
    assert a["status"] == cs.UNDETERMINED
    # the target carries no semester labels
    a = cs.assess(t, [t, doc("a"), doc("b")], {"t": courses([None]), "a": courses(range(1, 9)), "b": courses(range(1, 9))})
    assert a["status"] == cs.UNDETERMINED and "no semester labels" in a["reason"]
    # labels that do not start at semester 1 (an excerpt of the later years) are not a programme span
    a = cs.assess(t, [t, doc("a"), doc("b")], {"t": courses([1, 2]), "a": courses([5, 6, 7, 8]), "b": courses([7, 8])})
    assert a["status"] == cs.UNDETERMINED
    assert cs.assess(None, [], {})["status"] == cs.UNDETERMINED


def test_other_disciplines_and_degree_levels_are_not_comparison_curricula():
    t = doc("t", "TARGET", level="undergraduate")
    docs = [t, doc("mech1", discipline="Mechanical"), doc("mech2", discipline="Mechanical"),
            doc("pg1", level="postgraduate"), doc("pg2", level="postgraduate")]
    by_doc = {"t": courses([1, 2]), "mech1": courses(range(1, 9)), "mech2": courses(range(1, 9)),
              "pg1": courses(range(1, 5)), "pg2": courses(range(1, 5))}
    a = cs.assess(t, docs, by_doc)
    assert a["status"] == cs.UNDETERMINED and a["comparison"] == []


def test_the_assessment_is_deterministic():
    docs, by_doc = release_like()
    assert cs.assess(docs[2], docs, by_doc) == cs.assess(docs[2], list(reversed(docs)), by_doc)


# ------------------------------------------------------------------ gaps: classification kept, claim limited
def gaps_fixture():
    rows = [("k_missing", "ABSENT", "HIGH_SUPPORT", "MISSING"), ("k_partial", "INTRODUCTORY", "SUPPORTED", "PARTIAL"),
            ("k_covered", "SUBSTANTIAL", "HIGH_SUPPORT", "PARTIAL"), ("k_thin", "ABSENT", "OBSERVED", "MISSING"),
            ("k_title", "ABSENT", "HIGH_SUPPORT", "MISSING")]
    gaps = [{"skill_key": k, "skill_label": {"k_title": "data structures"}.get(k, k), "gap_uid": "gap:" + k,
             "classification": v1, "support_state": sup} for k, _, sup, v1 in rows]
    depth = {k: {"coverage_level": lvl, "level_reason": f"{lvl} coverage", "coverage_relation": "NONE"} for k, lvl, _, _ in rows}
    return gaps, depth


def run_gap_v2(scope):
    gaps, depth = gaps_fixture()
    out = ist.gap_v2(gaps, depth, {}, target_titles=[("26CSC03", "Data Structures using C")], discipline=DISC,
                     curriculum_scope=scope)
    return {g["skill_key"]: g for g in out}


INCOMPLETE_SCOPE = {"status": cs.INCOMPLETE, "missing_semesters": [3, 4, 5, 6, 7, 8], "target_semesters": [1, 2]}


def test_incomplete_scope_keeps_classifications_and_marks_gaps_for_review():
    base, scoped = run_gap_v2({"status": cs.COMPLETE}), run_gap_v2(INCOMPLETE_SCOPE)
    for k in base:
        for f in ("classification_v1", "classification_v2", "coverage_level", "reason_v2", "support_state"):
            assert base[k][f] == scoped[k][f], (k, f)              # the underlying classification is never rewritten
    m = scoped["k_missing"]
    assert m["classification_v2"] == "MISSING" and m["curriculum_scope"] == cs.INCOMPLETE and m["scope_limited"]
    assert m["evidence_status"] == "REVIEW_REQUIRED" and m["review"]["code"] == "CURRICULUM_SCOPE_INCOMPLETE"
    assert m["review"]["missing_semesters"] == [3, 4, 5, 6, 7, 8] and "III–VIII" in m["review"]["detail"]
    assert m["actionable"] is False and not ist.is_confirmed_gap(m)
    assert scoped["k_partial"]["scope_limited"] and scoped["k_partial"]["actionable"] is False
    # not a gap: neither scope-limited nor reviewed
    assert scoped["k_covered"]["classification_v2"] == "COVERED" and not scoped["k_covered"]["scope_limited"]
    assert "review" not in scoped["k_covered"] and scoped["k_covered"]["evidence_status"] == "INFERRED"
    # thin demand stays INSUFFICIENT_EVIDENCE, untouched
    assert scoped["k_thin"]["classification_v2"] == "INSUFFICIENT_EVIDENCE" and not scoped["k_thin"]["scope_limited"]
    # a more specific review (a target course is named after the skill) is kept; the scope limit is still stated
    t = scoped["k_title"]
    assert t["review"]["code"] == "COURSE_TITLE_NAMES_SKILL" and t["scope_limited"] and not t["actionable"]


def test_complete_and_undetermined_scope_change_nothing():
    for scope in ({"status": cs.COMPLETE}, {"status": cs.UNDETERMINED}, None):
        g = run_gap_v2(scope)
        assert g["k_missing"]["actionable"] is True and "review" not in g["k_missing"]
        assert g["k_partial"]["actionable"] is True and not any(x["scope_limited"] for x in g.values())
        assert g["k_missing"]["curriculum_scope"] == ((scope or {}).get("status") or cs.NOT_ASSESSED)
        assert g["k_title"]["review"]["code"] == "COURSE_TITLE_NAMES_SKILL"     # unchanged behaviour


def test_scope_review_withholds_the_recommendation_with_its_own_code():
    gaps2 = list(run_gap_v2(INCOMPLETE_SCOPE).values())
    rec = lambda k: {"skill_key": k, "skill_label": k, "gap_uid": "gap:" + k, "run_id": "r", "classification": "MISSING",  # noqa: E731
                     "support_state": "HIGH_SUPPORT", "action_type": "ADD_MODULE"}
    ig = {"recommendations": [rec("k_missing"), rec("k_title")], "suppressions": [], "traces": []}
    ist.reconcile_recommendations(ig, gaps2)
    assert ig["recommendations"] == []
    codes = {s["skill_key"]: s["reasons"][0]["code"] for s in ig["suppressions"]}
    assert codes == {"k_missing": "CURRICULUM_SCOPE_REVIEW_REQUIRED", "k_title": "COURSE_TITLE_CONFLICT_REVIEW_REQUIRED"}
    assert all(s["evidence_status"] == "REVIEW_REQUIRED" and s["withheld_recommendation"]["action_type"] == "ADD_MODULE"
               for s in ig["suppressions"])
    assert set(codes.values()) <= set(ist.WITHHELD_FOR_REVIEW_CODES)


def test_complete_scope_keeps_recommendations():
    gaps2 = list(run_gap_v2({"status": cs.COMPLETE}).values())
    ig = {"recommendations": [{"skill_key": "k_missing", "skill_label": "k", "gap_uid": "gap:k_missing", "run_id": "r",
                               "classification": "MISSING", "support_state": "HIGH_SUPPORT"}], "suppressions": [], "traces": []}
    ist.reconcile_recommendations(ig, gaps2)
    assert len(ig["recommendations"]) == 1 and ig["suppressions"] == []


# ------------------------------------------------------------------ one definition of "withheld for review"
def test_every_consumer_counts_the_same_withheld_codes():
    root = Path(__file__).resolve().parents[2]
    from app.services import improvement_service, intelligence_service
    assert set(improvement_service.WITHHELD_CODES) == set(ist.WITHHELD_FOR_REVIEW_CODES)
    assert set(intelligence_service.WITHHELD_CODES) == set(ist.WITHHELD_FOR_REVIEW_CODES)
    for script in ("scripts/audit/release_gap_qa.py", "scripts/audit/compare_runs.py"):
        assert "WITHHELD_FOR_REVIEW_CODES" in (root / script).read_text(), script
    dart = (root / "flutter_app/lib/screens/premium/recommendations_screen.dart").read_text()
    for code in ist.WITHHELD_FOR_REVIEW_CODES:
        assert f"'{code}'" in dart, code


def test_runs_made_before_the_assessment_report_not_assessed():
    from app.services import improvement_service

    class Run:
        report = {"run_id": "x"}

    s = improvement_service.curriculum_scope(Run())
    assert s["status"] == cs.NOT_ASSESSED and "re-run" in s["reason"]
    Run.report = {"curriculum_scope": {"status": cs.INCOMPLETE, "note": "n"}}
    assert improvement_service.curriculum_scope(Run())["status"] == cs.INCOMPLETE


def test_pipeline_assesses_scope_and_records_it():
    root = Path(__file__).resolve().parents[2]
    src = (root / "backend/app/knowledge_engine/pipeline.py").read_text()
    assert "curriculum_scope_mod.assess(" in src and '"curriculum_scope": curriculum_scope' in src
    assert "curriculum_scope=curriculum_scope)" in src
    assert 'write_json(d / "curriculum_scope.json"' in (root / "backend/app/knowledge_engine/intelligence_stage.py").read_text()
