"""Each recommendation says how the institution can check that it worked, from its own gap and evidence."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import intelligence_service as svc  # noqa: E402


class Verification(unittest.TestCase):
    def test_partial_gap_in_an_existing_course(self):
        rec = {"action_type": "EXPAND_EXISTING_TOPIC", "classification": "PARTIAL", "skill_label": "MySQL",
               "support_state": "HIGH_SUPPORT", "target_course_codes": ["22CSC42"]}
        v = svc.verification_criteria(rec, {"target_coverage_level": "INTRODUCTORY"})
        self.assertIn("MySQL taught in 22CSC42 beyond its current introductory coverage", v[0])
        self.assertIn("no longer classified partial", v[0])
        self.assertTrue(any("learning outcomes" in x for x in v))
        self.assertTrue(any("high support" in x for x in v))

    def test_missing_skill_needs_a_named_course(self):
        rec = {"action_type": "ADD_ELECTIVE", "classification": "MISSING", "skill_label": "lead others",
               "support_state": "HIGH_SUPPORT", "target_course_codes": []}
        v = svc.verification_criteria(rec)
        self.assertIn("teaches lead others in a named course", v[0])
        self.assertIn("no longer classifies the gap as missing", v[0])

    def test_no_numbers_are_invented(self):
        rec = {"action_type": "EXPAND_EXISTING_TOPIC", "classification": "PARTIAL"}
        for line in svc.verification_criteria(rec):
            self.assertFalse(any(ch.isdigit() for ch in line), line)


if __name__ == "__main__":
    unittest.main()
