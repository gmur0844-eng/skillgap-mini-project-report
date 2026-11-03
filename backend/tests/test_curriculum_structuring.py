import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.preprocessing.curriculum_structuring import (
    structure_curriculum_pages,
    extraction_confidence,
    resolve_best_course_titles,
    ExtractedCourse,
)

FIXTURE_PDF = Path(__file__).resolve().parents[2] / "data" / "external" / "demo_fixture" / "sample_curriculum.pdf"


def _load_fixture_pages():
    import pdfplumber

    pages = []
    with pdfplumber.open(FIXTURE_PDF) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return pages


def test_structuring_on_synthetic_lines():
    pages = [
        "CS101 Introduction to Programming\n"
        "Unit 1: Programming Fundamentals\n"
        "Topics: variables, control flow, functions\n"
        "Course Outcomes\n"
        "- Write basic procedural programs\n"
    ]
    structure = structure_curriculum_pages(pages)
    assert structure.courses_found == 1
    assert structure.courses[0].course_code == "CS101"
    assert len(structure.modules) == 1
    assert structure.modules[0].heading_label == "Unit 1"
    topic_texts = [t.topic_text for t in structure.topics]
    assert "variables" in topic_texts
    assert "functions" in topic_texts
    assert len(structure.outcomes) == 1


def test_structuring_on_real_fixture_pdf():
    assert FIXTURE_PDF.exists(), "Run data/external/demo_fixture/generate_fixture_pdf.py first"
    pages = _load_fixture_pages()
    structure = structure_curriculum_pages(pages)

    course_codes = {c.course_code for c in structure.courses}
    assert {"CS101", "CS301", "CS405"}.issubset(course_codes)
    assert len(structure.modules) >= 5  # 1 + 2 + 2 units across the 3 courses
    assert any("neural networks" in t.topic_text for t in structure.topics)
    assert any("Docker" in t.topic_text for t in structure.topics)

    confidence = extraction_confidence(structure, len(pages))
    assert confidence > 0.5  # every page in this fixture has recognizable structure


def test_empty_document_yields_zero_confidence():
    structure = structure_curriculum_pages(["", "", ""])
    assert structure.is_empty
    assert extraction_confidence(structure, 3) == 0.0


def test_two_courses_with_colliding_unit_labels_stay_separate():
    """
    PHASE-1 HARDENING REGRESSION TEST: Course A and Course B both have a
    "Unit 1" heading with different topics. Before the fix, topic attribution
    scanned module_by_key.items() and matched on heading_label ALONE, so
    whichever course's "Unit 1" was iterated last silently absorbed both
    courses' topics. This test fails if that bug reappears.
    """
    pages = [
        "CS101 Course A\n"
        "Unit 1: Foundations\n"
        "Topics: Topic A1, Topic A2\n"
        "CS201 Course B\n"
        "Unit 1: Foundations\n"
        "Topics: Topic B1, Topic B2\n"
    ]
    structure = structure_curriculum_pages(pages)

    course_a_topics = [t for t in structure.topics if t.course_code == "CS101"]
    course_b_topics = [t for t in structure.topics if t.course_code == "CS201"]

    course_a_texts = {t.topic_text for t in course_a_topics}
    course_b_texts = {t.topic_text for t in course_b_topics}

    assert course_a_texts == {"Topic A1", "Topic A2"}
    assert course_b_texts == {"Topic B1", "Topic B2"}
    # The critical assertion: no cross-contamination in either direction.
    assert course_a_texts.isdisjoint(course_b_texts) or course_a_texts == course_b_texts is False
    assert "Topic B1" not in course_a_texts and "Topic B2" not in course_a_texts
    assert "Topic A1" not in course_b_texts and "Topic A2" not in course_b_texts

    # Both modules are correctly labeled "Unit 1" but belong to different courses.
    module_keys = {(m.course_code, m.heading_label) for m in structure.modules}
    assert ("CS101", "Unit 1") in module_keys
    assert ("CS201", "Unit 1") in module_keys


def test_learning_outcomes_attributed_to_correct_course():
    """Companion regression test: outcomes must not cross courses either."""
    pages = [
        "CS101 Course A\n"
        "Course Outcomes\n"
        "- Outcome A1\n"
        "CS201 Course B\n"
        "Course Outcomes\n"
        "- Outcome B1\n"
    ]
    structure = structure_curriculum_pages(pages)
    a_outcomes = {o.text for o in structure.outcomes if o.course_code == "CS101"}
    b_outcomes = {o.text for o in structure.outcomes if o.course_code == "CS201"}
    assert a_outcomes == {"Outcome A1"}
    assert b_outcomes == {"Outcome B1"}


def test_resolve_extraction_method_supports_pdf_and_txt():
    from app.pipelines.preprocessing.curriculum_structuring import resolve_extraction_method

    assert resolve_extraction_method(".pdf") == "pdfplumber"
    assert resolve_extraction_method(".txt") == "plain_text_read"


def test_resolve_extraction_method_rejects_csv():
    """
    PHASE-1 HARDENING: .csv must be explicitly rejected, not silently read as
    plain text and misrepresented as "supported".
    """
    from app.pipelines.preprocessing.curriculum_structuring import resolve_extraction_method

    try:
        resolve_extraction_method(".csv")
        assert False, "Expected ValueError for .csv"
    except ValueError as e:
        assert "csv" in str(e).lower()


def test_resolve_extraction_method_rejects_docx():
    from app.pipelines.preprocessing.curriculum_structuring import resolve_extraction_method

    try:
        resolve_extraction_method(".docx")
        assert False, "Expected ValueError for .docx"
    except ValueError:
        pass


def test_part_heading_recognized_as_module():
    structure = structure_curriculum_pages(["CS301 Something\nPART A\nSome topic line"])
    assert any(m.heading_label == "Part A" for m in structure.modules)


def test_course_content_label_treated_as_topics_block():
    structure = structure_curriculum_pages(["CS301 X\nCourse Content:\nRecursion, Sorting"])
    topic_texts = [t.topic_text for t in structure.topics]
    assert "Recursion" in topic_texts and "Sorting" in topic_texts


def test_co_and_clo_outcome_labels_extracted():
    page = "CS301 X\nCourse Outcomes\nCO1: First outcome\nCLO2: Second outcome\nCO 3 Third outcome"
    structure = structure_curriculum_pages([page])
    labels = {o.label: o.text for o in structure.outcomes}
    assert labels["CO1"] == "First outcome"
    assert labels["CLO2"] == "Second outcome"
    assert labels["CO3"] == "Third outcome"


def test_course_outcome_and_learning_outcome_word_forms():
    page = "CS301 X\nCourse Outcomes\nCourse Outcome 4: Fourth\nLearning Outcome 5: Fifth"
    structure = structure_curriculum_pages([page])
    labels = {o.label: o.text for o in structure.outcomes}
    assert labels["Course Outcome 4"] == "Fourth"
    assert labels["Learning Outcome 5"] == "Fifth"


def test_bare_numbered_outcome():
    page = "CS301 X\nCourse Outcomes\n6. Bare numbered outcome"
    structure = structure_curriculum_pages([page])
    assert structure.outcomes[0].label == "6"
    assert structure.outcomes[0].text == "Bare numbered outcome"


def test_outcome_without_any_label_still_captured_with_none_label():
    page = "CS301 X\nCourse Outcomes\nJust a plain outcome line with no label"
    structure = structure_curriculum_pages([page])
    assert structure.outcomes[0].label is None
    assert structure.outcomes[0].text == "Just a plain outcome line with no label"


def test_part_heading_does_not_break_existing_unit_module_chapter_parsing():
    """Regression: adding PART support must not change UNIT/MODULE/CHAPTER
    behavior for universities that don't use PART at all."""
    page = "CS301 X\nUNIT-I\nTopics: A, B\nCHAPTER 2\nTopics: C"
    structure = structure_curriculum_pages([page])
    labels = [m.heading_label for m in structure.modules]
    assert labels == ["Unit I", "Chapter 2"]


# --- Regression tests for real bugs found auditing actual AICTE/CBIT PDFs ---

def test_digit_year_prefix_course_code_recognized():
    """Real CBIT format: '22CSC01', '22MTC01' -- digit-year prefix, not the
    letter-prefix format ('BSC-101') originally assumed."""
    structure = structure_curriculum_pages(["22CSC01 Data Structures\nUNIT-I\nArrays, Lists"])
    assert structure.courses[0].course_code == "22CSC01"


def test_year_reference_not_mistaken_for_course_code():
    """Real AICTE false positive: 'AY 2022-23' must never be treated as a
    course code -- it has no separator and 4 glued digits, unlike a real
    letter-prefix code's 2-3 glued digits."""
    structure = structure_curriculum_pages(["(Inline with AICTE Model Curriculum with effect from AY 2022-23)"])
    assert structure.courses == []


def test_letter_prefix_with_separator_still_works():
    """Real AICTE format: 'BSC-101' -- letter-prefix WITH a hyphen separator,
    allowed up to 4 digits since the separator removes the year-glued ambiguity."""
    structure = structure_curriculum_pages(["BSC-101 Physics-I\nUNIT-I\nMechanics"])
    assert structure.courses[0].course_code == "BSC-101"


def test_module_content_without_explicit_topics_label():
    """Real CBIT format: no 'Topics:' label at all -- the paragraph directly
    under the UNIT heading IS the content."""
    page = "22CSC01 X\nUNIT-I\nPartial Differentiation and Its Applications: Functions of two variables, Partial derivatives."
    structure = structure_curriculum_pages([page])
    topic_texts = [t.topic_text for t in structure.topics]
    assert any("Functions of two variables" in t for t in topic_texts)


def test_section_boundary_stops_module_content_capture():
    """TEXT BOOKS / REFERENCES / etc. must never be captured as topic content."""
    page = "22CSC01 X\nUNIT-I\nReal topic content here.\nTEXT BOOKS:\nSome Book Title, 2020.\nSome Author Name."
    structure = structure_curriculum_pages([page])
    topic_texts = " ".join(t.topic_text for t in structure.topics)
    assert "Real topic content" in topic_texts
    assert "Some Book Title" not in topic_texts
    assert "Some Author Name" not in topic_texts


def test_outcomes_label_with_same_line_lead_in_text():
    """Real CBIT format: 'COURSE OUTCOMES: After completion of this course,
    students will be able to' -- explanatory text on the SAME line as the label."""
    page = "22CSC01 X\nCOURSE OUTCOMES: After completion of this course, students will be able to\n1. Do the first thing.\n2. Do the second thing."
    structure = structure_curriculum_pages([page])
    labels = {o.label: o.text for o in structure.outcomes}
    assert labels.get("1") == "Do the first thing."
    assert labels.get("2") == "Do the second thing."
    # the lead-in sentence itself must never become a fake outcome
    assert not any("After completion" in o.text for o in structure.outcomes)


def test_individually_numbered_outcome_not_swallowed_by_block_header_regex():
    """Regression for a real bug introduced and then fixed during this same
    audit: 'Course Outcome 4: Analyze complexity' must reach the per-item
    parser, not be intercepted as a (redundant) block-header re-trigger."""
    page = "22CSC01 X\nCourse Outcomes\nCourse Outcome 4: Analyze complexity\nLearning Outcome 5: Evaluate tradeoffs"
    structure = structure_curriculum_pages([page])
    labels = {o.label: o.text for o in structure.outcomes}
    assert labels.get("Course Outcome 4") == "Analyze complexity"
    assert labels.get("Learning Outcome 5") == "Evaluate tradeoffs"


def test_lowercase_wrapped_sentence_does_not_falsely_open_outcomes_block():
    """Real AICTE false positive: a sentence that happens to WRAP onto a new
    line starting with lowercase 'learning outcomes, etc.' (mid-sentence
    prose, not a header) must never open the outcomes block."""
    page = (
        "22CSC01 X\n"
        "programs like honors for advanced students with more credits or advanced\n"
        "learning outcomes, etc.\n"
        "UNIT-I\n"
        "Real topic here."
    )
    structure = structure_curriculum_pages([page])
    assert structure.outcomes == []
    assert any("Real topic here" in t.topic_text for t in structure.topics)


def test_genuine_capitalized_header_still_opens_outcomes_block():
    """Regression guard: the isupper() fix must not break genuine headers."""
    page = "22CSC01 X\nCourse Outcomes\n1. A real outcome."
    structure = structure_curriculum_pages([page])
    assert len(structure.outcomes) == 1
    assert structure.outcomes[0].text == "A real outcome."


# --- Regression tests for the population-repair fixes (real bugs found auditing CBIT R-22A) ---

def test_bare_course_code_then_title_on_next_line():
    """Real CBIT R-22A detailed-syllabus format: the course code is ALONE on
    its own line, with the real title on the line immediately after."""
    page = "22CSC15N\nOPERATING SYSTEMS\n(Professional Core)\nUNIT-I\nIntroduction"
    structure = structure_curriculum_pages([page])
    course = next(c for c in structure.courses if c.course_code == "22CSC15N")
    assert course.course_name == "OPERATING SYSTEMS"
    assert course.category == "Professional Core"


def test_bare_course_code_title_lookahead_spans_page_boundary():
    """The code can be the LAST line of a page with its title as the FIRST
    line of the next page -- the lookahead must not reset per page."""
    page1 = "Some content\n22CSC24N"
    page2 = "COMPILER DESIGN\n(Professional Core)"
    structure = structure_curriculum_pages([page1, page2])
    course = next(c for c in structure.courses if c.course_code == "22CSC24N")
    assert course.course_name == "COMPILER DESIGN"


def test_bare_course_code_followed_by_another_code_does_not_fabricate_a_title():
    """If the line after a bare code is itself another course code (no real
    title exists between them), the pending lookahead must give up silently
    -- never borrowing the next course's identity as a title."""
    page = "22CSC15N\n22CSC24N\nCOMPILER DESIGN"
    structure = structure_curriculum_pages([page])
    first = next(c for c in structure.courses if c.course_code == "22CSC15N")
    assert first.course_name is None


def test_bare_course_code_followed_by_numeric_table_row_does_not_fabricate_a_title():
    page = "22CSC15N\n3    -   -    3    40   60   3"
    structure = structure_curriculum_pages([page])
    course = next(c for c in structure.courses if c.course_code == "22CSC15N")
    assert course.course_name is None


def test_digit_prefix_code_with_letter_suffix_recognized():
    """Real CBIT R-22A finding: many real course codes carry a trailing
    letter suffix (e.g. '22CSC15N', '22CSE06N') that the original
    digit-year-prefix pattern did not account for -- these codes were
    PREVIOUSLY INVISIBLE to extraction entirely, not merely badly titled."""
    structure = structure_curriculum_pages(["22CSC15N\nOPERATING SYSTEMS"])
    codes = [c.course_code for c in structure.courses]
    assert "22CSC15N" in codes


def test_resolve_best_course_titles_prefers_clean_occurrence_over_noisy_one_with_equal_alpha():
    """
    Regression for a real scoring bug: a messy summary-table row
    ('Operating Systems' + trailing credit/hour digits) can have the SAME
    alphabetic character count as a clean detailed-syllabus title ('Operating
    Systems' alone) -- the resolver must break that tie by preferring FEWER
    digits (the cleaner occurrence), not by earliest page number (which
    would wrongly favor the noisier, usually-earlier summary-table row).
    """
    noisy_first = ExtractedCourse(course_code="X1", course_name="Operating Systems             3    -   -       3        40     60        3", page_number=8, confidence=0.8)
    clean_second = ExtractedCourse(course_code="X1", course_name="Operating Systems", page_number=95, confidence=0.8)
    resolved = resolve_best_course_titles([noisy_first, clean_second])
    assert resolved["X1"]["title"] == "Operating Systems"


def test_resolve_best_course_titles_never_uses_first_occurrence_blindly():
    """A malformed FIRST occurrence must not cause a real course to
    disappear or be mis-titled when a later occurrence has a real title."""
    malformed_first = ExtractedCourse(course_code="X2", course_name="3 -   -   3   40  60   3", page_number=5, confidence=0.5)
    real_second = ExtractedCourse(course_code="X2", course_name="DATABASE MANAGEMENT SYSTEMS", page_number=80, confidence=0.8)
    resolved = resolve_best_course_titles([malformed_first, real_second])
    assert resolved["X2"]["title"] == "DATABASE MANAGEMENT SYSTEMS"


def test_resolve_best_course_titles_returns_none_not_fabricated_when_no_occurrence_has_a_title():
    """If NO occurrence of a code ever has a title-shaped name, the resolver
    must say so explicitly (None) -- never guess one from the course code."""
    only_numeric = ExtractedCourse(course_code="X3", course_name="3 -  -  3  40 60 3", page_number=9, confidence=0.5)
    resolved = resolve_best_course_titles([only_numeric])
    assert resolved["X3"]["title"] is None


def test_resolve_best_course_titles_is_deterministic():
    entries = [
        ExtractedCourse(course_code="X4", course_name="3 -  -  3", page_number=1, confidence=0.5),
        ExtractedCourse(course_code="X4", course_name="REAL TITLE HERE", page_number=50, confidence=0.8),
    ]
    r1 = resolve_best_course_titles(entries)
    r2 = resolve_best_course_titles(entries)
    assert r1 == r2


def test_course_table_extraction_independent_of_occurrence_order():
    """Whether the clean occurrence comes first or second in the input list,
    the resolver must pick the same winner -- order-independence, not a
    'first wins' or 'last wins' rule."""
    clean = ExtractedCourse(course_code="X5", course_name="NETWORK SECURITY", page_number=50, confidence=0.8)
    messy = ExtractedCourse(course_code="X5", course_name="4 -  -  3  40 60 3", page_number=5, confidence=0.5)
    assert resolve_best_course_titles([clean, messy])["X5"]["title"] == "NETWORK SECURITY"
    assert resolve_best_course_titles([messy, clean])["X5"]["title"] == "NETWORK SECURITY"


def test_all_recovered_courses_retain_provenance():
    resolved = resolve_best_course_titles([
        ExtractedCourse(course_code="X6", course_name="SOME COURSE", page_number=42, confidence=0.8),
    ])
    assert resolved["X6"]["page_number"] == 42
    assert resolved["X6"]["confidence"] == 0.8


def test_semicolon_split_produces_coherent_groups_not_fragments():
    """Real finding: syllabi use semicolons to separate topic GROUPS while
    commas separate finer items WITHIN a group. Splitting only on commas
    fragments coherent phrases (verified against real CBIT R-22A text)."""
    page = ("CS101 X\nTopics: Types of communication: verbal and non-verbal; "
            "Barriers to communication; Intrapersonal, Interpersonal communication.")
    structure = structure_curriculum_pages([page])
    texts = [t.topic_text for t in structure.topics]
    assert "Types of communication: verbal and non-verbal" in texts
    assert "Barriers to communication" in texts
    assert "Intrapersonal, Interpersonal communication." in texts


def test_comma_split_still_works_when_no_semicolon_present():
    """Regression: the original comma-splitting behavior must be unchanged
    for lines that never use semicolons."""
    page = "CS101 X\nTopics: Arrays, Linked Lists, Stacks"
    structure = structure_curriculum_pages([page])
    texts = [t.topic_text for t in structure.topics]
    assert texts == ["Arrays", "Linked Lists", "Stacks"]
