"""Generic decoder rules added for the peer curricula (no institution names anywhere in the rules)."""
import unittest

from app.pipelines.preprocessing.curriculum_structuring import (
    COURSE_CODE_RE, MATRIX_HEADER_RE, MATRIX_LEGEND_RE, MATRIX_ROW_RE, SEMESTER_HEADING_RE, TOPICS_LABEL_RE,
    course_header_match, semester_label, structure_curriculum_pages,
)
from app.pipelines.preprocessing.layout_aware_extraction import _course_row_layout, _rejoin_split_words
from app.knowledge_engine.silver import MIN_OWN_CONTENT_TOPICS, build_silver
from app.knowledge_engine.quarantine import Quarantine


class CourseCodes(unittest.TestCase):
    def test_four_digit_codes_are_codes_unless_year_shaped(self):
        self.assertEqual(course_header_match("CS1106 3-0-2 (4)").group(1), "CS1106")
        self.assertEqual(course_header_match("MA1161 2-0-0 (3)").group(1), "MA1161")
        self.assertIsNone(course_header_match("AY2022"))
        self.assertIsNone(course_header_match("CS2024 onwards"))
        self.assertIsNone(COURSE_CODE_RE.fullmatch("AB1999"))

    def test_stream_letter_codes(self):
        self.assertEqual(course_header_match("CS1M01 2-0-2 (3)").group(1), "CS1M01")
        self.assertEqual(course_header_match("CS1H02").group(1), "CS1H02")

    def test_existing_shapes_unchanged(self):
        for line, code in (("22CSC11N Title", "22CSC11N"), ("PCC CS301 Operating Systems", "CS301"), ("BSC-101 Physics", "BSC-101")):
            self.assertEqual(course_header_match(line).group(1), code)


class Layout(unittest.TestCase):
    def test_title_on_the_line_after_a_credit_only_header(self):
        s = structure_curriculum_pages(["CS1106                3-0-2 (4)\nData Structures and Algorithms\nSyllabus:\n"
                                        "Trees: Binary Trees, AVL Trees\nText Books:\n1. Someone, A Book, 2009."])
        self.assertEqual([(c.course_code, c.course_name) for c in s.courses], [("CS1106", "Data Structures and Algorithms")])
        texts = [t.topic_text for t in s.topics]
        self.assertIn("AVL Trees", texts)
        self.assertFalse(any("Book" in t for t in texts), texts)

    def test_syllabus_label_needs_a_colon(self):
        self.assertTrue(TOPICS_LABEL_RE.match("Syllabus: a, b"))
        self.assertFalse(TOPICS_LABEL_RE.match("SCHEME AND SYLLABUS"))
        self.assertFalse(TOPICS_LABEL_RE.match("COURSE CONTENTS:"))  # deliberately unchanged (baseline stability)

    def test_matrix_rows_are_skipped_and_content_after_a_leading_matrix_is_captured(self):
        page = ("CS1301   4-0-0 (4)\nData Warehousing and Data Mining\nCourse Outcomes:\nCO-1 Understand stages.\n"
                "PO-1 PO-2 PO-3 PO-4 PSO-1\nCO-1 1 1 3 - -\n1 - Slightly; 2 - Moderately; 3 - Substantially\n"
                "Data Warehousing: KDD Process, Data Cube Computation")
        s = structure_curriculum_pages([page])
        texts = [t.topic_text for t in s.topics]
        self.assertIn("Data Cube Computation", texts)
        self.assertFalse(any("Slightly" in t or t.startswith("CO-1") for t in texts), texts)
        self.assertEqual(len(s.outcomes), 1)

    def test_matrix_after_content_opens_nothing(self):
        page = ("CS201 Networks\nUNIT-I\nRouting, Switching\nCO-PO Articulation Matrix\nPO1 PO2 PO3\nCO1 3 2 1\n"
                "Stray footer text, more text")
        texts = [t.topic_text for t in structure_curriculum_pages([page]).topics]
        self.assertEqual(texts, ["Routing", "Switching"])

    def test_matrix_shapes(self):
        self.assertTrue(MATRIX_HEADER_RE.match("PO-1 PO-2 PO-3 PO-4 PSO-1"))
        self.assertTrue(MATRIX_ROW_RE.match("CO-2 2 2 3 – – 1"))
        self.assertTrue(MATRIX_LEGEND_RE.match("1 - Slightly; 2 - Moderately; 3 - Substantially"))
        self.assertFalse(MATRIX_ROW_RE.match("CO-2 Apply orthogonal transformations"))

    def test_ordinal_semester_heading(self):
        self.assertEqual(semester_label(SEMESTER_HEADING_RE.match("1st Semester")), "1")
        self.assertEqual(semester_label(SEMESTER_HEADING_RE.match("SEMESTER – III")), "III")
        self.assertIsNone(SEMESTER_HEADING_RE.match("Semester End Examination"))


class CourseRowTables(unittest.TestCase):
    ROWS = [["", "", "", "continued text from the previous page about recovery algorithms and logging"],
            ["CS330", "Operating Systems", "3-0-3-12", "Introduction: review of computer organization, system calls, "
             "functions of OS, evolution of operating systems, process scheduling and synchronization"],
            ["CS335", "Compiler Design", "3-0-0-9", "Lexical analysis, parsing, syntax directed translation, type checking, "
             "intermediate code generation, code optimisation and register allocation"]]

    def test_detects_code_title_content_columns(self):
        self.assertEqual(_course_row_layout(self.ROWS), (0, 1, 3))

    def test_scheme_table_is_not_a_course_row_table(self):
        scheme = [["S.No", "Code", "Course Title", "L", "T", "P", "Credits"],
                  ["1", "CS101", "Programming and Data Structures", "3", "0", "0", "3"],
                  ["2", "CS103", "Programming and Data Structures Lab", "0", "1", "2", "2"]]
        self.assertIsNone(_course_row_layout(scheme))

    def test_split_words_rejoined_only_on_document_evidence(self):
        vocab = {"systems": 133, "syst": 5, "ems": 5, "in": 900, "input": 20, "put": 3, "of": 800, "sum": 10}
        self.assertEqual(_rejoin_split_words("Database Syst ems", vocab), "Database Systems")
        self.assertEqual(_rejoin_split_words("data in put", vocab), "data in put")
        self.assertEqual(_rejoin_split_words("rule of sum", vocab), "rule of sum")


class CatalogueCourses(unittest.TestCase):
    def _doc(self):
        return {"doc_id": "doc", "role": "PEER", "institution": "i", "programme": "p", "discipline": "d",
                "curriculum_version": "v", "path": "x.pdf", "sha256": "0" * 64, "_page_methods": {1: "pdftotext_layout"}}

    def test_single_occurrence_course_with_own_content_is_kept(self):
        page = "CS330 Operating Systems\nTopics: " + ", ".join(f"topic {i}" for i in range(MIN_OWN_CONTENT_TOPICS))
        q = Quarantine()
        rec = build_silver(self._doc(), structure_curriculum_pages([page]), q, {"min_alpha_chars": 3, "max_words": 40})
        self.assertEqual([c["course_code"] for c in rec["courses"]], ["CS330"])

    def test_single_occurrence_code_without_content_is_quarantined(self):
        q = Quarantine()
        rec = build_silver(self._doc(), structure_curriculum_pages(["CS330 Operating Systems\nTopics: one, two"]), q,
                           {"min_alpha_chars": 3, "max_words": 40})
        self.assertEqual(rec["courses"], [])
        self.assertTrue(any(i["reason"].startswith("NO_STRUCTURAL_EVIDENCE") for i in q.items))


if __name__ == "__main__":
    unittest.main()
