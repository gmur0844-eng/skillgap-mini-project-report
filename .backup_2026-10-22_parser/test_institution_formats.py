"""
Curriculum ingestion across institutional formats (regression for the JNTU R22 B.Tech. CSE upload that produced
0 courses from 4,615 topic lines).

Root cause: the course-code pattern had no "letters + 3 digits + 2-3-letter category suffix" shape (MA101BS, CS302PC),
"<Y> Year <S> Semester" headings were not semester headings, a footnote marker before a code (*MC210) blocked the
header, and running-header removal stripped each syllabus page's own "II Year II Sem." statement.

Fixtures reproduce line SHAPES; the real-document tests use the exact uploaded PDF and the frozen BRONZE text of the
existing curricula, and are reported as skipped (never passed) where those files are absent.
"""
import hashlib
import json
import sys
import unittest
from collections import Counter
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.ingestion.outcome import (  # noqa: E402
    NEEDS_REVIEW, NO_USABLE_CONTENT, SUCCESSFUL_AND_USABLE, curriculum_outcome,
)
from app.pipelines.preprocessing import curriculum_structuring as cs  # noqa: E402
from app.pipelines.preprocessing.curriculum_structuring import (  # noqa: E402
    COURSE_CODE_RE, COURSE_SEMESTER_STATEMENT_RE, SEMESTER_HEADING_RE, course_header_match,
    resolve_best_course_titles, semester_label, structure_curriculum_pages, year_semester,
)
from app.pipelines.preprocessing.layout_aware_extraction import detect_boilerplate_lines  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
JNTU_SHA256 = "b50e1a3573ccc3f5d54180cbdd9f7698998785e52e997575e737ef8313a1e82a"
JNTU_PDF = REPO / "data/raw/curricula/uploads/b50e1a3573cc/R22B.Tech.CSECourseStructureSyllabus2.pdf"


def _semesters(structure):
    return {code: v["semester"] for code, v in resolve_best_course_titles(structure.courses).items()}


def _counts_result(structure, confidence=0.8):
    """The ingestion result fields curriculum_outcome reads, as ingest_curriculum_document builds them."""
    return {"status": "succeeded", "extraction_confidence": confidence, "flagged_for_review": False,
            "courses_found": structure.courses_found, "modules_found": len(structure.modules),
            "topics_found": len(structure.topics), "outcomes_found": len(structure.outcomes),
            "topics_unattributed": sum(1 for t in structure.topics if not t.course_code)}


# --- 3. institutional course-code formats ---------------------------------------------------------------------------

class CourseCodeFormats(unittest.TestCase):
    def test_existing_shapes_still_recognised(self):
        for code in ("22MTC01", "CS-101", "CSE1001", "CS3A01", "MC210", "CS101"):
            self.assertEqual(COURSE_CODE_RE.search(code).group(1), code, code)

    def test_letters_digits_category_suffix_shape(self):
        # a general shape (2-6 letters, 3 digits, 2-3-letter category suffix), not a list of codes
        for code in ("MA101BS", "CS103ES", "CS302PC", "CS403PC", "CS601PC", "EE205ES", "CS511PE", "CS611OE", "SM306MS"):
            self.assertEqual(COURSE_CODE_RE.search(code).group(1), code, code)

    def test_shapes_that_stay_unrecognised(self):
        # a one-letter suffix, a four-digit + suffix, a year and an over-long suffix are not this shape
        for text in ("CS101X", "EN1001HS", "AY2024", "BS1001ABCD"):
            self.assertIsNone(COURSE_CODE_RE.search(text), text)

    def test_suffixed_code_heads_a_course_with_its_title(self):
        s = structure_curriculum_pages(["CS302PC: DATA STRUCTURES\nUNIT - I\nArrays, linked lists, stacks\n"])
        self.assertEqual(resolve_best_course_titles(s.courses)["CS302PC"]["title"], "DATA STRUCTURES")
        self.assertTrue(all(t.course_code == "CS302PC" for t in s.topics))

    def test_footnote_marker_before_a_code_is_a_header(self):
        self.assertIsNotNone(course_header_match("*MC210: ENVIRONMENTAL SCIENCE"))
        self.assertIsNotNone(course_header_match("10. *MC210 Environmental Science 3 0 0 0"))

    def test_code_mentioned_in_prose_is_still_not_a_header(self):
        self.assertIsNone(course_header_match("Students who completed MA101BS may register for this course"))


# --- 4. titles without a familiar code ------------------------------------------------------------------------------

class TitlesWithoutCodes(unittest.TestCase):
    PAGE = "DATA STRUCTURES\nUNIT - I\nArrays, linked lists, stacks and queues\nUNIT - II\nTrees and graphs\n"

    def test_no_code_is_invented_for_an_uncoded_title(self):
        s = structure_curriculum_pages([self.PAGE])
        self.assertEqual(s.courses, [])
        self.assertTrue(s.topics)
        self.assertTrue(all(t.course_code is None for t in s.topics))

    def test_uncoded_document_is_flagged_not_analysis_ready(self):
        o = curriculum_outcome(_counts_result(structure_curriculum_pages([self.PAGE])))
        self.assertEqual(o["outcome"], NO_USABLE_CONTENT)
        self.assertFalse(o["usable_for_analysis"])
        self.assertEqual(o["review_status"], "NEEDS_REVIEW")


# --- 5. multi-semester and single-semester documents ---------------------------------------------------------------

class SemesterStructure(unittest.TestCase):
    def test_year_semester_headings(self):
        for line, label in (("I Year I Semester", "I"), ("I YEAR II SEMESTER", "II"), ("II Year I Sem.", "III"),
                            ("III Year - II Semester", "VI"), ("IV Year II Sem", "VIII"), ("2 year 1 semester", "III")):
            m = SEMESTER_HEADING_RE.match(line)
            self.assertIsNotNone(m, line)
            self.assertEqual(semester_label(m), label, line)

    def test_year_semester_conversion_is_two_semesters_per_year(self):
        self.assertEqual([year_semester(y, s) for y in ("I", "II", "III", "IV") for s in ("I", "II")],
                         ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"])

    def test_not_year_semester_headings(self):
        for line in ("III Year III Semester", "Environmental Science in III Yr II Sem Should be Registered",
                     "B.Tech. II Year II Sem. L T P C"):
            self.assertIsNone(SEMESTER_HEADING_RE.match(line), line)

    def test_existing_semester_headings_unchanged(self):
        for line in ("SEMESTER – I", "SEMESTER-II", "Semester VII", "SEMESTER 3", "3rd Semester"):
            self.assertIsNotNone(SEMESTER_HEADING_RE.match(line), line)

    def test_multi_semester_document(self):
        pages = ["I YEAR I SEMESTER\nMA101BS Matrices and Calculus 3 1 0 4\nII YEAR I SEMESTER\nCS302PC Data Structures 3 0 0 3\n",
                 "IV YEAR II SEMESTER\nCS863PE Deep Learning 3 0 0 3\n"]
        self.assertEqual(_semesters(structure_curriculum_pages(pages)),
                         {"MA101BS": "I", "CS302PC": "III", "CS863PE": "VIII"})

    def test_single_semester_document(self):
        page = "SEMESTER - V\n22CSC21 Software Engineering\n22CSC22 Computer Networks\n"
        self.assertEqual(set(_semesters(structure_curriculum_pages([page])).values()), {"V"})

    def test_no_semester_evidence_is_none_not_guessed(self):
        self.assertIsNone(_semesters(structure_curriculum_pages(["CS302PC: DATA STRUCTURES\n"]))["CS302PC"])

    def test_course_statement_overrides_a_carried_heading(self):
        # a scheme table's last heading (VIII) carries over the detailed syllabus pages; each syllabus header states
        # its own year/semester, which is evidence about that course
        pages = ["IV YEAR II SEMESTER\nCS863PE Deep Learning 3 0 0 3\n",
                 "CS511PE: SOFTWARE TESTING METHODOLOGIES (Professional Elective - I)\nB.Tech. III Year I Sem. L T P C\n"
                 "UNIT - I\nPurpose of testing\n"]
        sem = _semesters(structure_curriculum_pages(pages))
        self.assertEqual(sem["CS511PE"], "V")
        self.assertEqual(sem["CS863PE"], "VIII")

    def test_statement_far_from_a_header_is_not_attributed(self):
        page = ("SEMESTER - II\nCS302PC: DATA STRUCTURES\nUNIT - I\nArrays\nStacks\nQueues\n"
                "Registered by students of III Year I Sem only\n")
        s = structure_curriculum_pages([page])
        self.assertIsNone(s.courses[0].semester_stated)
        self.assertEqual(_semesters(s)["CS302PC"], "II")

    def test_statement_is_not_a_topic(self):
        s = structure_curriculum_pages(["CS302PC: DATA STRUCTURES\nB.Tech. II Year I Sem. L T P C\nUNIT - I\nArrays\n"])
        self.assertFalse(any("Year" in t.topic_text for t in s.topics))


class RunningHeaderRemoval(unittest.TestCase):
    def test_course_semester_statement_survives_boilerplate_removal(self):
        pages = [f"CS{300 + i}PC: COURSE {i}\nB.Tech. II Year I Sem. L T P C\nFooter text of the university\n"
                 for i in range(10)]
        removed = detect_boilerplate_lines(pages)
        self.assertIn("Footer text of the university", removed)
        self.assertNotIn("B.Tech. II Year I Sem. L T P C", removed)
        self.assertIsNotNone(COURSE_SEMESTER_STATEMENT_RE.search("B.Tech. II Year I Sem. L T P C"))


# --- 6 / 7. topics without identifiable courses; extraction succeeds, structuring fails -----------------------------

class StructuringOutcome(unittest.TestCase):
    def test_reported_jntu_counts_are_not_analysis_ready(self):
        # the exact figures the failed upload reported: text extracted from 66% of pages, no course recognised
        o = curriculum_outcome({"status": "succeeded", "extraction_confidence": 0.66, "flagged_for_review": False,
                                "courses_found": 0, "modules_found": 353, "topics_found": 4615, "outcomes_found": 777,
                                "topics_unattributed": 4615})
        self.assertEqual(o["outcome"], NO_USABLE_CONTENT)
        self.assertEqual(o["execution_status"], "SUCCEEDED")
        self.assertEqual(o["structuring_status"], "NOT_STRUCTURED")
        self.assertFalse(o["usable_for_analysis"])
        self.assertIn("text was extracted (4615 topic lines) but no course code or course header was recognised",
                      o["reasons"][0])

    def test_mostly_unattributed_topics_need_review(self):
        o = curriculum_outcome({"status": "succeeded", "extraction_confidence": 0.8, "courses_found": 3,
                                "modules_found": 10, "topics_found": 100, "outcomes_found": 12,
                                "topics_unattributed": 70})
        self.assertEqual((o["outcome"], o["structuring_status"]), (NEEDS_REVIEW, "PARTIALLY_STRUCTURED"))
        self.assertFalse(o["usable_for_analysis"])

    def test_some_unattributed_topics_stay_usable(self):
        # the AICTE model curriculum attributes 27% of its topic lines to no course and is used for analysis
        o = curriculum_outcome({"status": "succeeded", "extraction_confidence": 0.6, "courses_found": 40,
                                "modules_found": 200, "topics_found": 100, "outcomes_found": 50,
                                "topics_unattributed": 27})
        self.assertEqual((o["outcome"], o["structuring_status"]), (SUCCESSFUL_AND_USABLE, "STRUCTURED"))

    def test_results_without_the_unattributed_count_keep_their_outcome(self):
        o = curriculum_outcome({"status": "succeeded", "extraction_confidence": 0.8, "courses_found": 5,
                                "modules_found": 5, "topics_found": 50, "outcomes_found": 5})
        self.assertEqual((o["outcome"], o["structuring_status"]), (SUCCESSFUL_AND_USABLE, "STRUCTURED"))
        self.assertNotIn("topics_unattributed", o["counts"])

    def test_unsupported_code_format_extracts_text_but_no_course(self):
        # a code shape no pattern covers: the text is read, nothing is invented, and the outcome says so
        page = "Q-7/ALPHA: COMPILER DESIGN\nUNIT - I\nLexical analysis, parsing\nUNIT - II\nCode generation\n"
        s = structure_curriculum_pages([page])
        self.assertEqual(s.courses, [])
        o = curriculum_outcome(_counts_result(s))
        self.assertEqual((o["outcome"], o["structuring_status"]), (NO_USABLE_CONTENT, "NOT_STRUCTURED"))


# --- 1. existing curricula: structuring is unchanged ------------------------------------------------------------------

# sha256 (first 16) of every structured record and resolved course, from the release BRONZE text (parser fingerprint
# 6d93cd03ca5098d9); identical under the parser before this change (verified when the change was made).
FROZEN_BRONZE = {
    "bc14c2f0e5170367": ("cbit-be-cse-r22", "0966fb44b0dec7e6"),
    "f98246ad7ea53425": ("cbit-be-cse-r22a", "f020755125c4a95c"),
    "d29ccbce0a342c58": ("upl-d29ccbce0a34", "84a6232c7769f825"),
    "187ff968b3fe98a0": ("iitk", "65a37c95d9d586ad"),
    "5c4bd3b16c2865fb": ("aicte-ug-cse-model", "2d293b73f0197031"),
    "c7cec69aa6655dee": ("nitw", "02e5f92514c8d170"),
    # changed deliberately (2026-10-11), from 0e6e3e058e166b38: NITT's detailed syllabi open with a labelled header
    # block ("Course Code  CSPC11" / "Course Title  Discrete Structures"); unrecognised, 2,715 of its 2,914 topic lines
    # were credited to one course (CSOH18). Now 95 courses carry their own topics (NittLabelledHeaders below).
    "f98c230df8bb7ba2": ("nitt-btech-cse-2024-25", "a3a3456836827824"),
}
# courses whose OWN header block states their semester (all other occurrences carry none)
STATED_SEMESTERS = {"f98c230df8bb7ba2": {"CSPC11": "II", "CSPC31": "III", "CSPC41": "IV", "CSPC51": "V", "CSPC61": "VI"}}


def _structure_digest(pages):
    s = structure_curriculum_pages(pages)
    rec = {k: [{f: v for f, v in sorted(vars(x).items()) if f != "semester_stated"} for x in getattr(s, k)]
           for k in ("courses", "modules", "topics", "outcomes", "prerequisites")}
    payload = json.dumps({"records": rec, "resolved": resolve_best_course_titles(s.courses)}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16], s


class ExistingCurricula(unittest.TestCase):
    def test_existing_curricula_structure_identically(self):
        checked = []
        for key, (doc_id, expected) in FROZEN_BRONZE.items():
            path = REPO / "data/bronze/curricula" / key / "pages.6d93cd03ca5098d9.json"
            if not path.exists():
                continue
            with self.subTest(doc_id):
                digest, s = _structure_digest(json.loads(path.read_text(encoding="utf-8"))["pages"])
                self.assertEqual(digest, expected)
                self.assertEqual({c.course_code: c.semester_stated for c in s.courses if c.semester_stated},
                                 STATED_SEMESTERS.get(key, {}))
                checked.append(doc_id)
        if not {"cbit-be-cse-r22", "cbit-be-cse-r22a"} & set(checked):
            raise unittest.SkipTest("frozen CBIT BRONZE text not present in this environment")

    def test_cbit_shaped_scheme_still_parses(self):
        pages = ["SEMESTER – I\n22MTC01 Linear Algebra and Calculus 3 1 0 4\n22CYC01 Chemistry 3 0 0 3\n",
                 "SEMESTER-II\n22CSC01 Problem Solving and Programming 2 1 0 3\n"]
        self.assertEqual(_semesters(structure_curriculum_pages(pages)),
                         {"22MTC01": "I", "22CYC01": "I", "22CSC01": "II"})


# --- 2. the exact failing upload ------------------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _jntu_pages(path_kind):
    if not JNTU_PDF.exists() or hashlib.sha256(JNTU_PDF.read_bytes()).hexdigest() != JNTU_SHA256:
        raise unittest.SkipTest("the uploaded JNTU R22 syllabus is not present in this environment")
    if path_kind == "upload":
        try:
            from app.pipelines.ingestion.curriculum import _extract_pages_from_pdf
        except ImportError:  # same pdfplumber reading, where the database layer is not installed
            import pdfplumber

            def _extract_pages_from_pdf(p):
                with pdfplumber.open(p) as pdf:
                    return [page.extract_text() or "" for page in pdf.pages]
        return tuple(_extract_pages_from_pdf(JNTU_PDF))
    from app.knowledge_engine.pipeline import _pdftotext_pages
    from app.pipelines.preprocessing.layout_aware_extraction import extract_document_pages_as_text
    pages, _ = extract_document_pages_as_text(str(JNTU_PDF), fallback_pages=_pdftotext_pages(JNTU_PDF))
    return tuple(pages)


class JntuR22Upload(unittest.TestCase):
    # read from the document: each course's code, title and its own "<Y> Year <S> Sem." header line
    EXPECTED = {"MA101BS": ("MATRICES AND CALCULUS", "I"), "CS302PC": ("DATA STRUCTURES", "III"),
                "CS601PC": ("MACHINE LEARNING", "VI"), "CS103ES": (None, "I"), "CS403PC": (None, "IV"),
                "CS511PE": (None, "V"), "CS611OE": (None, "VI"), "CS863PE": (None, "VIII"), "MC210": (None, "II")}

    def _check(self, path_kind):
        s = structure_curriculum_pages(list(_jntu_pages(path_kind)))
        resolved = resolve_best_course_titles(s.courses)
        self.assertEqual(len(resolved), 100)
        for code, (title, semester) in self.EXPECTED.items():
            self.assertIn(code, resolved)
            self.assertEqual(resolved[code]["semester"], semester, code)
            if title:
                self.assertEqual(resolved[code]["title"], title, code)
        self.assertTrue(all(v["title"] and v["semester"] for v in resolved.values()))
        self.assertEqual(set(Counter(v["semester"] for v in resolved.values())),
                         {"I", "II", "III", "IV", "V", "VI", "VII", "VIII"})
        self.assertEqual(sum(1 for t in s.topics if not t.course_code), 0)
        o = curriculum_outcome(_counts_result(s, cs.extraction_confidence(s, len(_jntu_pages(path_kind)))))
        self.assertEqual(o["structuring_status"], "STRUCTURED")
        self.assertGreater(o["counts"]["courses"], 0)
        return {code: v["semester"] for code, v in resolved.items()}

    def test_upload_ingestion_path(self):
        self._check("upload")

    def test_pipeline_bronze_path_agrees(self):
        self.assertEqual(self._check("layout"), self._check("upload"))


# --- document-learned code shapes, labelled header fields, table totals ------------------------------------------------

from app.knowledge_engine.readiness import curriculum_readiness  # noqa: E402
from app.pipelines.preprocessing.curriculum_structuring import (  # noqa: E402
    document_code_re, labelled_course_code, learn_code_shapes,
)

SCHEME = ("SCHEME OF INSTRUCTION\n"
          "U26BS130MA Calculus & Linear Algebra 3 - - 3 60 40 3\n"
          "U26BS110PH Physics of Semiconductors 2 - - 3 60 40 2\n"
          "UII26ES120CS Programming for Problem Solving 3 - - 3 60 40 3\n"
          "TOTAL 16 - 8 - 630 420 20\n"
          "GRAND TOTAL 24 - 1050 -\n")


class LearnedCodeShapes(unittest.TestCase):
    def test_a_shape_is_learned_from_scheme_rows(self):
        shapes = learn_code_shapes([SCHEME])
        self.assertEqual(len(shapes), 1)
        code_re = document_code_re(shapes)
        for code in ("U26BS130MA", "UII26ES120CS", "U26HS040EH"):
            self.assertEqual(code_re.fullmatch(code).group(0), code)
        self.assertIsNone(course_header_match("TOTAL 16 - 8 - 630 420 20", code_re))
        self.assertIsNone(course_header_match("GRAND TOTAL 24 - 1050 -", code_re))

    def test_fewer_than_three_rows_teach_nothing(self):
        self.assertEqual(learn_code_shapes(["U26BS130MA Calculus 3 - - 3 60 40 3\nU26BS110PH Physics 2 - - 3 60 40 2\n"]), [])

    def test_nothing_is_learned_from_prose(self):
        prose = "\n".join(f"Students who passed U26BS13{i}MA may opt for the minor in the next year." for i in range(5))
        self.assertEqual(learn_code_shapes([prose]), [])

    def test_a_shape_the_builtin_pattern_covers_is_not_relearned(self):
        rows = "\n".join(f"22CSC0{i} Course Title Number {i} 3 0 0 3 40 60 3" for i in range(1, 6))
        self.assertEqual(learn_code_shapes([rows]), [])

    def test_learned_codes_head_courses_and_totals_never_do(self):
        s = structure_curriculum_pages([SCHEME + "UNIT - I\nLimits and continuity\n"])
        codes = {c.course_code for c in s.courses}
        self.assertEqual(codes, {"U26BS130MA", "U26BS110PH", "UII26ES120CS"})
        self.assertFalse(any(c.startswith("TOTAL") for c in codes))

    def test_table_totals_are_not_courses_with_the_builtin_pattern_either(self):
        s = structure_curriculum_pages(["SEMESTER - I\n22MTC01 Linear Algebra 3 1 0 4\nTOTAL 16 - 8 - 630 420 20\n"])
        self.assertEqual({c.course_code for c in s.courses}, {"22MTC01"})


class LabelledHeaderFields(unittest.TestCase):
    def test_inline_and_whole_line_labels(self):
        self.assertEqual(labelled_course_code("L:T:P (Hrs./week):3:0:0 SEE Marks : 60 Course Code : 22CSC01"), "22CSC01")
        self.assertEqual(labelled_course_code("Course Code                             CSPC11"), "CSPC11")
        # a table header, a token that is not a code, and a label without a separator mid-line are not code fields
        self.assertIsNone(labelled_course_code("Course Code          Course Name          Resource Link"))
        self.assertIsNone(labelled_course_code("Course Code : PROJECT"))
        self.assertIsNone(labelled_course_code("the Course Code 22CSC01 is listed below"))

    def test_labelled_block_takes_its_labelled_title(self):
        page = ("Course Code    CSPC11\nCourse Title   Discrete Structures\nPrerequisites  -\n"
                "UNIT I\nSets, relations and functions\n")
        s = structure_curriculum_pages([page])
        r = resolve_best_course_titles(s.courses)
        self.assertEqual(r["CSPC11"]["title"], "Discrete Structures")
        self.assertTrue(all(t.course_code == "CSPC11" for t in s.topics))
        self.assertFalse(any("Course Title" in t.topic_text for t in s.topics))

    def test_labelled_course_never_inherits_a_carried_heading(self):
        # the detailed-syllabus section follows the last scheme table's heading; electives are not in that semester
        pages = ["SEMESTER VI\nCSPC61 Compiler Design 3 0 0 3\n",
                 "Course Code    CSPE37\nCourse Title   Deep Learning\nUNIT I\nPerceptrons\n"]
        r = resolve_best_course_titles(structure_curriculum_pages(pages).courses)
        self.assertEqual(r["CSPC61"]["semester"], "VI")
        self.assertIsNone(r["CSPE37"]["semester"])

    def test_header_block_semester_statement_before_or_after_the_code(self):
        before = "CALCULUS & LINEAR ALGEBRA\nSYLLABUS FOR B.E. I-SEMESTER\nL:T:P 3:0:0 Course Code : 22MTC01\nUNIT I\nLimits\n"
        after = "Course Code    CSPC31\nSemester: III\nCourse Title   Programming Languages\n"
        self.assertEqual(resolve_best_course_titles(structure_curriculum_pages([before]).courses)["22MTC01"]["semester"], "I")
        self.assertEqual(resolve_best_course_titles(structure_curriculum_pages([after]).courses)["CSPC31"]["semester"], "III")

    def test_a_block_naming_two_semesters_states_none(self):
        page = "B.E. I and II SEMESTER courses\nCourse Code : 22MTC01\nUNIT I\nLimits\n"
        self.assertIsNone(resolve_best_course_titles(structure_curriculum_pages([page]).courses)["22MTC01"]["semester"])


class NittLabelledHeaders(unittest.TestCase):
    PATH = REPO / "data/bronze/curricula/f98c230df8bb7ba2/pages.6d93cd03ca5098d9.json"

    def test_topics_belong_to_their_own_courses(self):
        if not self.PATH.exists():
            raise unittest.SkipTest("frozen NITT BRONZE text not present in this environment")
        s = structure_curriculum_pages(json.loads(self.PATH.read_text(encoding="utf-8"))["pages"])
        per_course = Counter(t.course_code for t in s.topics)
        self.assertLess(max(per_course.values()), 200)          # was 2,715 on one course
        self.assertGreaterEqual(sum(1 for v in per_course.values() if v), 90)
        r = resolve_best_course_titles(s.courses)
        labelled = [c for c in s.courses if c.course_code == "CSPC11" and c.course_name == "Discrete Structures"]
        self.assertEqual(len(labelled), 1)                      # the labelled header block, with its page
        self.assertEqual(r["CSPC11"]["semester"], "II")         # its block states "II SEMESTER"
        self.assertFalse([c for c, v in r.items() if c.startswith("CSPE") and v["semester"] == "VI"])


VASAVI_SHA256 = "11ead4024c66a1492244aaf7add0b17158b48f2db490cfcca6a1df0337b4ca58"
VASAVI_PDF = REPO / "data/raw/curricula/uploads/11ead4024c66/01-syllabus-2026-27.pdf"


class VasaviR26Upload(unittest.TestCase):
    """The upload that ingestion called 'ready' with 4 courses (table totals) and the pipeline then failed."""

    @classmethod
    def setUpClass(cls):
        if not VASAVI_PDF.exists() or hashlib.sha256(VASAVI_PDF.read_bytes()).hexdigest() != VASAVI_SHA256:
            raise unittest.SkipTest("the uploaded Vasavi R26 syllabus is not present in this environment")
        import pdfplumber
        with pdfplumber.open(VASAVI_PDF) as pdf:
            cls.pages = [p.extract_text() or "" for p in pdf.pages]
        cls.s = structure_curriculum_pages(cls.pages)
        cls.r = resolve_best_course_titles(cls.s.courses)

    def test_courses_are_the_documents_own_codes(self):
        self.assertEqual(len(self.s.learned_code_shapes), 1)
        self.assertEqual(len(self.r), 25)
        self.assertFalse([c for c in self.r if c.startswith("TOTAL")])
        for code in ("U26BS130MA", "UII26ES120CS", "UII26ES220CS", "U26MC010CE"):
            self.assertIn(code, self.r)
        self.assertEqual(sum(1 for t in self.s.topics if not t.course_code), 0)

    def test_semesters_come_from_each_syllabus_header(self):
        self.assertEqual(self.r["U26BS130MA"]["semester"], "I")
        self.assertEqual(self.r["UII26ES220CS"]["semester"], "II")
        self.assertEqual(Counter(v["semester"] for v in self.r.values()), Counter({"II": 12, "I": 11, None: 2}))

    def test_upload_check_and_analysis_check_agree(self):
        readiness = curriculum_readiness(self.s, "upl-11ead4024c66", VASAVI_SHA256)
        self.assertEqual(readiness["status"], "PASS")
        self.assertGreaterEqual(readiness["valid_courses"], 20)

    def test_pipeline_text_path_agrees(self):
        from app.knowledge_engine.pipeline import _pdftotext_pages
        from app.pipelines.preprocessing.layout_aware_extraction import extract_document_pages_as_text
        pages, _ = extract_document_pages_as_text(str(VASAVI_PDF), fallback_pages=_pdftotext_pages(VASAVI_PDF))
        r = resolve_best_course_titles(structure_curriculum_pages(pages).courses)
        self.assertEqual(set(r), set(self.r))
        self.assertEqual({c: v["semester"] for c, v in r.items()}, {c: v["semester"] for c, v in self.r.items()})


class AnalysisReadiness(unittest.TestCase):
    def test_fabricated_courses_fail_the_analysis_check_and_the_upload_needs_review(self):
        # what the old parser produced for the Vasavi upload: table totals as the only "courses"
        from app.pipelines.preprocessing.curriculum_structuring import CurriculumStructure, ExtractedCourse
        st = CurriculumStructure(courses=[
            ExtractedCourse(course_code="TOTAL16", course_name="8 - 630 420 20", page_number=6, confidence=0.8),
            ExtractedCourse(course_code="TOTAL24", course_name="1050", page_number=6, confidence=0.8)])
        readiness = curriculum_readiness(st, "upl-x", "0" * 64)
        self.assertEqual(readiness["status"], "FAIL")
        self.assertTrue(any("course(s) could be validated" in r for r in readiness["reasons"]))
        o = curriculum_outcome({"status": "succeeded", "extraction_confidence": 0.55, "courses_found": 4,
                                "modules_found": 61, "topics_found": 1319, "outcomes_found": 484,
                                "topics_unattributed": 0, "analysis_readiness": readiness})
        self.assertEqual(o["outcome"], NEEDS_REVIEW)
        self.assertFalse(o["usable_for_analysis"])
        self.assertEqual(o["analysis_readiness"], "FAIL")
        self.assertTrue(any(r.startswith("analysis check:") for r in o["reasons"]))

    def test_a_check_that_could_not_run_is_reported(self):
        o = curriculum_outcome({"status": "succeeded", "extraction_confidence": 0.8, "courses_found": 5,
                                "modules_found": 5, "topics_found": 50, "outcomes_found": 5,
                                "analysis_readiness": {"status": "NOT_CHECKED", "reasons": ["could not run (OSError)"]}})
        self.assertEqual(o["outcome"], NEEDS_REVIEW)


if __name__ == "__main__":
    unittest.main()
