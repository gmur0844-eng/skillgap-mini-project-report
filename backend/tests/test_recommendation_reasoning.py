"""Existing-course-first recommendation reasoning: the least disruptive intervention the curriculum evidence supports.
Cases from the completion directive §29 (recommendations). Discipline-, institution- and course-agnostic."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import recommendation_reasoning as rr  # noqa: E402


def rec(key="k", action="ADD_ELECTIVE", support="HIGH_SUPPORT"):
    return {"skill_key": key, "skill_label": key.upper(), "action_type": action, "support_state": support,
            "recommendation_uid": "rec:" + key}


def depth(level, *evidence):
    return {"coverage_level": level, "evidence": [{"course_code": c, "relation": r, "page": 3, "text": t}
                                                  for c, r, t in evidence]}


def run(r, target=None, inst=None, tsem=(1, 2, 3, 4, 5, 6, 7, 8), isem=(1, 2, 3, 4, 5, 6, 7, 8)):
    rows = rr.reason([r], {r["skill_key"]: target} if target else {}, {r["skill_key"]: inst} if inst else {},
                     {"T-1": "Course One", "T-2": "Course Two"}, {"I-9": "Other Course"}, list(tsem), list(isem), "Other")
    return rows[0]


class Reasoning(unittest.TestCase):
    def test_partial_coverage_with_strong_demand_expands_the_existing_topic(self):
        r = run(rec(action="EXPAND_EXISTING_TOPIC"), target=depth("INTRODUCTORY", ("T-1", "DIRECT", "the skill")))
        self.assertEqual(r["action"], "EXPAND_EXISTING_TOPIC")
        self.assertEqual(r["evidence"]["courses_teaching_it"][0]["course_code"], "T-1")

    def test_a_passing_mention_strengthens_that_course_instead_of_an_elective(self):
        r = run(rec(action="ADD_ELECTIVE"), target=depth("MENTION", ("T-2", "RELATED", "uses the skill")))
        self.assertEqual(r["action"], "STRENGTHEN_EXISTING_COURSE")
        self.assertIn("T-2 Course Two", " ".join(r["why"]))

    def test_an_existing_course_elsewhere_in_the_institution_prevents_an_unjustified_new_subject(self):
        r = run(rec(action="ADD_NEW_SUBJECT"), target=depth("ABSENT"),
                inst=depth("SUBSTANTIAL", ("I-9", "DIRECT", "the skill in depth")))
        self.assertEqual(r["action"], "REVIEW_BEFORE_CHANGE")
        self.assertIn("I-9 Other Course", " ".join(r["why"]))
        self.assertTrue(any("ADD_NEW_SUBJECT" in x for x in r["limitations"]))

    def test_an_incomplete_document_prevents_an_unjustified_elective(self):
        r = run(rec(action="ADD_ELECTIVE"), target=depth("ABSENT"), tsem=(1, 2))
        self.assertEqual(r["action"], "REVIEW_BEFORE_CHANGE")
        self.assertIn("covers semester(s) 1, 2 only", " ".join(r["why"]))

    def test_missing_skill_with_no_suitable_course_and_high_support_is_a_possible_elective(self):
        r = run(rec(action="ADD_ELECTIVE"), target=depth("ABSENT"))
        self.assertEqual(r["action"], "CONSIDER_ELECTIVE")
        self.assertEqual(r["action_label"], "Consider a new elective")      # a consideration, never "Add elective"
        self.assertTrue(r["limitations"])

    def test_supported_but_not_high_demand_goes_to_review(self):
        r = run(rec(action="ADD_ELECTIVE", support="SUPPORTED"), target=depth("ABSENT"))
        self.assertEqual(r["action"], "REVIEW_BEFORE_CHANGE")

    def test_a_standalone_course_is_never_inferred_and_is_listed_as_an_alternative(self):
        for t in (depth("ABSENT"), depth("MENTION", ("T-1", "RELATED", "x")), depth("SUBSTANTIAL", ("T-1", "DIRECT", "x"))):
            r = run(rec(action="ADD_NEW_SUBJECT"), target=t)
            self.assertNotEqual(r["action"], "CONSIDER_STANDALONE_COURSE")
            self.assertIn("CONSIDER_STANDALONE_COURSE", [a["action"] for a in r["alternatives_considered"]])

    def test_a_course_title_alone_cannot_justify_an_intervention(self):
        # no topic evidence at all: the title of a course is not read as coverage
        r = run(rec(action="EXPAND_EXISTING_TOPIC"), target=depth("ABSENT"))
        self.assertNotEqual(r["action"], "EXPAND_EXISTING_TOPIC")

    def test_every_row_carries_its_evidence_chain(self):
        r = run(rec(action="EXPAND_EXISTING_TOPIC"), target=depth("INTRODUCTORY", ("T-1", "DIRECT", "topic text")))
        for k in ("rule_action", "action", "why", "evidence", "alternatives_considered", "limitations", "evidence_state"):
            self.assertIn(k, r)
        self.assertEqual(r["evidence"]["courses_teaching_it"][0]["topic"], "topic text")
        self.assertEqual(r["evidence_state"], "INFERRED")

    def test_semesters_are_compared_as_numbers(self):
        self.assertEqual(rr.semesters_of([{"doc_id": "d", "semester": "IV"}, {"doc_id": "d", "semester": "2"},
                                          {"doc_id": "d", "semester": None}, {"doc_id": "x", "semester": "I"}], "d"), [2, 4])

    def test_no_institution_discipline_or_course_is_named_in_code(self):
        src = (Path(__file__).resolve().parents[1] / "app/knowledge_engine/recommendation_reasoning.py").read_text()
        code = re.sub(r'"""[\s\S]*?"""', "", src)
        for word in ("CBIT", "IIT", "CSE", "Computer Science", "SQL", "Docker", "Mechanical", "Civil"):
            self.assertNotIn(word, code)


if __name__ == "__main__":
    unittest.main()
