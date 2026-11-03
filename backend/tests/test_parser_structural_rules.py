"""
Regression tests for generic structural parser rules added after running the
real AICTE / CBIT R22 / CBIT R22A PDFs. Each fixture reproduces the SHAPE of a
real line; no test depends on an institution name.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.preprocessing.curriculum_structuring import (
    structure_curriculum_pages,
    resolve_best_course_titles,
    course_header_match,
    SEMESTER_HEADING_RE,
)


# --- course header vs. code mention -------------------------------------------------

def test_code_at_line_start_is_a_header():
    assert course_header_match("22CSC15N") is not None
    assert course_header_match("BSC-101 Physics-I 3L:1T:2P 5 Credits") is not None


def test_enumerator_and_category_tag_prefix_still_a_header():
    assert course_header_match("1. 22CSC10 Organization and 3 1 - 3 40 60 4") is not None
    assert course_header_match("PCC CS-301 Data Structure and Algorithms 3L:0T:4P 5 Credits") is not None
    assert course_header_match("4 PCC CS-402 Computer Organization IV 3 0 4 5") is not None


def test_code_mentioned_mid_sentence_is_not_a_header():
    assert course_header_match("7. Implementation of SHA-256 cryptographic hash function.") is None
    assert course_header_match("(MD5, SHA-256), understanding") is None
    assert course_header_match("using FPGA kits in their Digital Electronics course (ESC302) and have") is None


def test_code_followed_by_lowercase_continuation_is_not_a_header():
    # real shape: "3. CS403 to be scheduled in semester after CS402"
    assert course_header_match("3. CS403 to be scheduled in semester after CS402") is None


def test_mentions_do_not_steal_topic_attribution():
    page = (
        "CS-601 Cyber Security\n"
        "UNIT-I\n"
        "Hash functions (MD5, SHA-256), understanding collisions\n"
        "Digital signatures\n"
    )
    s = structure_curriculum_pages([page])
    assert {c.course_code for c in s.courses} == {"CS-601"}
    assert all(t.course_code == "CS-601" for t in s.topics)


def test_non_course_identifier_families_are_never_headers():
    assert course_header_match("ISBN13: 9781259676512.") is None
    assert course_header_match("SHA-512 Message digest") is None


# --- prerequisite capture ------------------------------------------------------------

def test_inline_prerequisite_statement_captured_verbatim():
    page = "22CSC01 PROBLEM SOLVING\nPRE-REQUISITES: Basic knowledge of programming language such as python.\nUNIT-I\nIntro"
    s = structure_curriculum_pages([page])
    assert len(s.prerequisites) == 1
    p = s.prerequisites[0]
    assert p.course_code == "22CSC01"
    assert p.text == "Basic knowledge of programming language such as python."
    assert p.is_explicit_none is False


def test_explicit_nil_prerequisite_is_a_stated_absence():
    s = structure_curriculum_pages(["22CSC01 X\nPREREQUISITE: Nil\n"])
    assert s.prerequisites[0].is_explicit_none is True


def test_prerequisite_list_items_are_not_course_headers():
    # real shape from a model curriculum: a bare label opening an enumerated list
    page = (
        "PCC CS-403 Operating Systems 3L:0T:4P 5 Credits\n"
        "Prerequisites details:\n"
        "1. Familiarity with the C/C++ programming language\n"
        "2. PCC 402: Computer Organization and Computer Architecture\n"
        "3. CS403 to be scheduled in semester after CS402\n"
        "(both courses not to be scheduled in the same semester)\n"
        "Module 1: Introduction\n"
        "Topics: Processes, Threads\n"
    )
    s = structure_curriculum_pages([page])
    assert {c.course_code for c in s.courses} == {"CS-403"}
    assert [p.text for p in s.prerequisites] == [
        "Familiarity with the C/C++ programming language",
        "PCC 402: Computer Organization and Computer Architecture",
        "CS403 to be scheduled in semester after CS402",
    ]
    assert all(t.course_code == "CS-403" for t in s.topics)


def test_prerequisite_without_a_course_context_is_not_invented():
    s = structure_curriculum_pages(["PREREQUISITE: Calculus\n"])
    assert s.prerequisites == []


# --- semester headings ---------------------------------------------------------------

def test_semester_heading_variants_observed_in_real_documents():
    for line in ["SEMESTER – I", "SEMESTER-II", "SEMESTER –VIII", "SEMESTER - V", "Semester VII", "SEMESTER 3"]:
        assert SEMESTER_HEADING_RE.match(line), line


def test_semester_words_in_prose_or_table_headers_are_not_headings():
    for line in ["Semester End Examination 60 Marks", "Course Title Semester Hours per week",
                 "B.E. I to VIII SEMESTERS of FOUR YEAR DEGREE COURSE"]:
        assert not SEMESTER_HEADING_RE.match(line), line


def test_course_takes_semester_of_heading_in_force():
    pages = ["SEMESTER – I\n22MTC01 Linear Algebra and Calculus\n", "SEMESTER-II\n22CYC01 Chemistry\n"]
    s = structure_curriculum_pages(pages)
    resolved = resolve_best_course_titles(s.courses)
    assert resolved["22MTC01"]["semester"] == "I"
    assert resolved["22CYC01"]["semester"] == "II"


def test_semester_unknown_before_any_heading_is_none_not_guessed():
    s = structure_curriculum_pages(["22MTC01 Linear Algebra\n"])
    assert resolve_best_course_titles(s.courses)["22MTC01"]["semester"] is None


def test_semester_heading_is_not_captured_as_a_topic():
    page = "22MTC01 Linear Algebra\nUNIT-I\nMatrices, Determinants\nSEMESTER-II\n22CYC01 Chemistry\n"
    s = structure_curriculum_pages([page])
    assert not any("SEMESTER" in t.topic_text.upper() for t in s.topics)


# --- rules added after the golden-page regression run -----------------------------

def test_title_wrapped_below_header_row_is_joined():
    pages = ["SEMESTER II\nESC-201      Programming      for 3L:0T:4P      5 Credits\n"
             "                  Problem Solving\nCourse Objectives:\n1. To learn the fundamentals of computers."]
    structure = structure_curriculum_pages(pages)
    course = next(c for c in structure.courses if c.course_code == "ESC-201")
    assert course.course_name == "Programming for Problem Solving"


def test_inline_unit_title_is_content_when_no_topics_label_follows():
    pages = ["SEMESTER I\nAB101 Programming Basics\nModule II: Arithmetic expressions and precedence.\n"
             "Module III: Conditional Branching and Loops"]
    texts = [(t.module_heading_label, t.topic_text) for t in structure_curriculum_pages(pages).topics]
    assert ("Module II", "Arithmetic expressions and precedence.") in texts
    assert ("Module III", "Conditional Branching and Loops") in texts


def test_text_reference_books_heading_ends_topic_capture():
    pages = ["SEMESTER I\nAB101 Programming Basics\nUNIT-I\nArrays, Strings\nTEXT/REFERENCE BOOKS:\n"
             "2. Byron Gottfried, Schaum's Outline of Programming with C, McGraw-Hill."]
    texts = {t.topic_text for t in structure_curriculum_pages(pages).topics}
    assert texts == {"Arrays", "Strings"}


def test_sentences_in_one_table_cell_become_separate_topics():
    pages = ["AB101 Workshop\nUnit 1\nTopics: PCB prototype fabrication in the lab. Soldering using soldering iron/station."]
    texts = [t.topic_text for t in structure_curriculum_pages(pages).topics]
    assert "Soldering using soldering iron/station." in texts


# --- AICTE ECE / Mechanical / Civil / Electrical model-curriculum layouts -----------

def test_plural_course_contents_label_opens_topics():
    pages = ["SEMESTER I\nAB101 Programming Basics 3L:0T:0P 3 Credits\nCourse Contents:\nArrays, Strings"]
    texts = {t.topic_text for t in structure_curriculum_pages(pages).topics}
    assert {"Arrays", "Strings"} <= texts


def test_category_tag_joined_by_hyphen_is_a_header():
    # real shape: "PCC-ME 202  Fluid Mechanics & Hydraulic  3L:1T:0P  4 credits"
    m = course_header_match("PCC-ME 202             Fluid Mechanics & Hydraulic                3L:1T:0P          4 credits")
    assert m is not None and m.group(1).replace(" ", "") == "ME202"


def test_code_with_hyphen_and_space_is_a_header():
    m = course_header_match("PCC- 05 Surveying and Geomatics            3L:0T:2P          4 Credits")
    assert m is not None and m.group(1).replace(" ", "") == "PCC-05"


def test_code_followed_by_a_cited_year_is_a_reference_not_a_header():
    assert course_header_match("5. IS269 (2015) Ordinary Portland Cement - Specification") is None
    assert course_header_match("3. SP-35 (1987) Handbook on Water Supply and Drainage") is None
    assert course_header_match("CS101 (Theory) Programming") is not None


def test_bare_course_contents_line_opens_topics_under_a_model_curriculum_header():
    pages = ["SEMESTER IV\nPCC- 08 Structural Analysis      3L:1T:0P      4 Credits\nCourse Outcomes\n"
             "1. Determine deflection of statically determinate structures.\nCourse Contents\n1. General theorems\n"
             "Theorems relating to elastic structures, principle of virtual work"]
    s = structure_curriculum_pages(pages)
    texts = {t.topic_text for t in s.topics}
    assert {"Theorems relating to elastic structures", "principle of virtual work"} <= texts
    assert not any("elastic structures" in o.text for o in s.outcomes)
    assert "Course Contents" not in texts


def test_bare_course_contents_line_is_not_a_label_under_another_header_shape():
    pages = ["CS666 Selected Topics\nCourse Contents\nHere is a broad list of topics, to be covered, in the course"]
    assert structure_curriculum_pages(pages).topics == []


def test_heading_colon_paragraphs_under_a_model_header_are_content():
    pages = ["SEMESTER III\nPCC-ME 202   Fluid Mechanics & Hydraulic Machines   3L:1T:0P   4 credits\n"
             "1. To learn about the application of mass and momentum conservation laws\n"
             "Properties of Fluid: Definition of fluid; Newton's law of viscosity; Units and dimensions. (5)\n"
             "Dimensional Analysis: Buckingham Pi Theorem; Similitude and complete similarity; Model scales. (7)\n"
             "1. S.S. Rattan, Fluid Mechanics & Hydraulic Machines, Khanna Book Publishing, 2019."]
    s = structure_curriculum_pages(pages)
    texts = [t.topic_text for t in s.topics if t.course_code == "ME202"]
    assert "Similitude and complete similarity" in texts and "Newton's law of viscosity" in texts
    assert not any("Rattan" in t or "To learn" in t for t in texts)


def test_heading_colon_line_is_not_content_without_a_model_header_or_a_list():
    plain = ["SEMESTER I\n22PYC03 Physics Lab\nNOTE: A minimum of TWELVE experiments should be done."]
    assert structure_curriculum_pages(plain).topics == []
    no_list = ["SEMESTER I\nAB101 Workshop 0L:0T:2P 1 Credit\nCredits: 1.5"]
    assert structure_curriculum_pages(no_list).topics == []
