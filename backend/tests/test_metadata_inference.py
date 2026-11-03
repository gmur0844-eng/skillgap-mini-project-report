"""Metadata suggestions from a document's own front matter: found with evidence, uncertain when it disagrees, absent
when it says nothing -- never invented."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.metadata_inference import FRONT_PAGES, infer_metadata  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
KNOWN = ["Computer Science and Engineering"]


def values(result):
    return {k: v["value"] for k, v in result["suggestions"].items()}


class Synthetic(unittest.TestCase):
    FRONT = ("SCHEME OF INSTRUCTION AND SYLLABI\n"
             "B.Tech. in MECHANICAL ENGINEERING\n"
             "(R-24 Regulations) with effect from AY 2024-25\n"
             "SRI EXAMPLE COLLEGE OF ENGINEERING (AUTONOMOUS)\n"
             "Affiliated to Example University, Approved by AICTE\n")

    def test_each_value_carries_its_page_and_line(self):
        r = infer_metadata([self.FRONT], KNOWN)
        self.assertEqual(values(r), {"institution": "SRI EXAMPLE COLLEGE OF ENGINEERING", "discipline": "Mechanical Engineering",
                                     "curriculum_version": "R24", "academic_year": "2024-25",
                                     "degree_level": "undergraduate", "programme": "B.Tech. Mechanical Engineering"})
        ev = r["suggestions"]["curriculum_version"]["evidence"]
        self.assertEqual((ev["page"], ev["text"]), (1, "(R-24 Regulations) with effect from AY 2024-25"))
        self.assertTrue(all(s["status"] == "FOUND" for s in r["suggestions"].values()))

    def test_affiliation_and_approval_lines_are_not_the_institution(self):
        r = infer_metadata(["Affiliated to Example University\nApproved by AICTE, New Delhi\n"], KNOWN)
        self.assertNotIn("institution", r["suggestions"])

    def test_conflicting_values_are_uncertain_and_nothing_is_chosen(self):
        r = infer_metadata(["R22 Regulations\nIn force from R23 Regulations onwards\n"], KNOWN)
        s = r["suggestions"]["curriculum_version"]
        self.assertEqual(s["status"], "UNCERTAIN")
        self.assertIsNone(s["value"])
        self.assertEqual([c["value"] for c in s["candidates"]], ["R22", "R23"])

    def test_a_silent_document_suggests_nothing(self):
        self.assertEqual(infer_metadata(["UNIT I\nArrays and linked lists\n"], KNOWN)["suggestions"], {})

    def test_only_the_front_pages_are_read(self):
        pages = ["Introduction"] * FRONT_PAGES + ["NATIONAL INSTITUTE OF EXAMPLES\n"]
        self.assertNotIn("institution", infer_metadata(pages, KNOWN)["suggestions"])

    def test_prose_and_course_titles_are_not_disciplines(self):
        r = infer_metadata(["To produce graduates with the best practices of computer science\n"
                            "Basic Electrical Engineering 3 0 0 3\n"], [])
        self.assertNotIn("discipline", r["suggestions"])


class RealDocuments(unittest.TestCase):
    CASES = {
        "data/raw/curricula/uploads/b50e1a3573cc/R22B.Tech.CSECourseStructureSyllabus2.pdf":
            {"institution": "JAWAHARLAL NEHRU TECHNOLOGICAL UNIVERSITY HYDERABAD", "curriculum_version": "R22",
             "programme": "B.Tech. Computer Science and Engineering", "academic_year": "2022-23"},
        "data/raw/curricula/uploads/11ead4024c66/01-syllabus-2026-27.pdf":
            {"institution": "VASAVI COLLEGE OF ENGINEERING", "curriculum_version": "R26", "academic_year": "2026-27",
             "discipline": "Computer Science and Engineering"},
        "data/raw/curricula/cbit/cbit_be_cse_r22_syllabus.pdf":
            {"institution": "CHAITANYA BHARATHI INSTITUTE OF TECHNOLOGY", "curriculum_version": "R22",
             "academic_year": "2022-23"},
    }

    def test_real_front_matter(self):
        checked = 0
        for rel, expected in self.CASES.items():
            path = REPO / rel
            if not path.exists():
                continue
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages[:FRONT_PAGES]]
            with self.subTest(rel):
                got = values(infer_metadata(pages, KNOWN))
                for k, v in expected.items():
                    self.assertEqual(got.get(k), v, k)
            checked += 1
        if not checked:
            raise unittest.SkipTest("none of the real syllabi is present in this environment")


if __name__ == "__main__":
    unittest.main()
