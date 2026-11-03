"""
Curriculum text -> structured entities (spec Section 5/7 of the ingestion phase).

Deliberately decoupled from any PDF library: this module takes a list of
per-page plain-text strings (however they were extracted) and applies
heuristic, inspectable rules to find course codes, course names, module/unit
headings, topics, and learning outcomes. Every match keeps the page number it
came from, so a Skill -> Course -> Page -> Original Document trace is possible.

Real university syllabus PDFs are NOT uniformly formatted, so these are
heuristics with fallback, not a strict parser: if nothing matches, the
document is flagged for manual review rather than silently producing an
empty/fabricated structure.
"""
import re
from dataclasses import dataclass, field

# Two real, distinct, widely-used Indian course-code conventions, both
# genuine (found by auditing actual AICTE and CBIT documents, not guessed):
#   letter-prefix:      "CS101", "CS-101", "CSE 3021", "MATH2001", "BSC-101"
#   digit-year-prefix:  "22CSC01", "22MTC01", "22MEC38" (year + dept + seq)
# The digit-prefix branch is tried first since it is more specific (an
# unambiguous 2-digit-year anchor) and therefore lower false-positive risk.
# For the letter-prefix branch, a code glued directly to a number with NO
# separator ("AY2022") is excluded from 4-digit matches -- that shape is far
# more often a year reference than a course code. Separator-joined codes
# ("BSC-101", "AY 2022") are capped at 3 digits (every real course code
# observed uses exactly 3; a 4-digit number after a separator -- with or
# without a hyphen -- is a year/date reference, not a course code). This
# is a real, generic false positive found in the AICTE document ("AY
# 2022-23" is never a course, with or without the space), not
# university-specific.
COURSE_CODE_RE = re.compile(
    r"\b(\d{2}[A-Z]{2,6}\d{2,3}[A-Z]?|[A-Z]{2,6}(?:-\s?|\s)\d{2,3}|[A-Z]{2,4}(?!(?:19|20)\d{2}\b)\d{4}|[A-Z]{2,4}\d[A-Z]\d{2}|[A-Z]{2,6}\d{3}[A-Z]{2,3}|[A-Z]{2,6}\d{2,3})\b"
)
# The separator of the second alternative may be a hyphen followed by a space ("PCC- 05 Surveying and Geomatics"), as
# a real model curriculum writes all its professional-core headings; with one character only, those courses were
# read as part of the course before them.
# The third alternative accepts an unseparated letter prefix + FOUR digits
# ("CS1106", "MA1161") unless the four digits are year-shaped (19xx / 20xx):
# found on a real peer curriculum whose every course code has four digits
# (0 courses were recognised). "AY2022" and "CS2024" stay excluded, which is
# the same year-reference rule as above, applied by digit shape, not by name.
# The fourth alternative ("CS1M01", "CS1H02": prefix, digit, one letter, two digits) is the same kind of
# code with a stream letter inside it (minor/honours courses of the same peer document); without it, 700+
# topics of those courses were credited to the course listed before them.
# Known limitation (documented, not "fixed" by guessing): a code-shaped
# token from an unrelated administrative context can still false-positive
# if it happens to match one of these shapes exactly (e.g. an internship
# process form ID like "IAP-101" is indistinguishable, by shape alone, from
# a real letter-prefix course code). Quality gates (malformed/duplicate
# course code checks) are the intended mitigation layer for this, not a
# fragile context-sniffing regex.

MODULE_HEADING_RE = re.compile(
    r"^\s*(unit|module|chapter)\s*[-–—:]?\s*(\d+|[ivxlcdm]+)\b[\s:.\-–—]*(.*)$", re.IGNORECASE
)
# The separator accepts the en/em dash ("UNIT–II"): with only "-" and ":"
# accepted, 66 real unit headings across two documents were neither detected
# as headings nor protected from running-header removal.
# "PART A" / "PART-A" / "PART B" -- a letter-labeled structural division, seen
# in some universities' syllabi as an alternative to numbered units. Handled
# as its own regex (rather than folded into MODULE_HEADING_RE) because its
# label is a letter, not a number/roman numeral -- still maps into the same
# ExtractedModule shape, so downstream code needs no per-format branching.
PART_HEADING_RE = re.compile(r"^\s*part\s*[-:]?\s*([A-Z])\b[\s:.\-]*(.*)$", re.IGNORECASE)

TOPICS_LABEL_RE = re.compile(r"^\s*(topics?|course\s+contents?|syllabus)\s*[:\-]", re.IGNORECASE)
# "Syllabus:" as an explicit content label (the label word followed by a colon
# or dash) was added for a real peer curriculum whose unit-less course content
# follows exactly that label; a bare "SYLLABUS" title line has no colon and
# does not match. The plural "Course Contents:" is accepted too: the AICTE model curricula label every syllabus that
# way (it adds 30 clean Engineering Graphics topics to the CSE reference, which the singular-only pattern had missed).
# A label alone on its own line, with no colon ("Course Contents" above numbered unit headings in the AICTE Civil
# model curriculum), or a bare "Contents:" (AICTE Mechanical), is accepted by TOPICS_LABEL_ALONE_RE, but only under a model-curriculum header with a lettered
# "3L:1T:0P" cell (see _LTP_LETTERED_RE below): in a peer curriculum the same words head a free-text table. A bare
# "SYLLABUS" title is still not a label.
TOPICS_LABEL_ALONE_RE = re.compile(r"^\s*(?:course\s+)?contents?\s*:?\s*$", re.IGNORECASE)
# Real layout (AICTE Mechanical model curriculum): the syllabus has no unit headings and no content label -- its
# "Objectives" / "Contents" side labels are not in the text layer -- so the content is a run of paragraphs that each
# open with a short heading and a colon, directly under the course header:
#   "Fluid Kinematics: Different approaches; Reynolds transport theorem; ... (6)"
# Such a line opens the course's content only under a header that carries an "3L:1T:0P" cell (the model-curriculum
# header shape), when the course has no unit heading and no content yet, and when the text after the colon is itself a
# list (at least two ";" or "," separators) -- "NOTE: A minimum of TWELVE experiments" or "Credits: 1.5" in other
# layouts never qualify. A numbered line (the reference list that follows) closes it.
_LTP_LETTERED_RE = re.compile(r"\d\s*L\s*:\s*\d\s*T\s*:\s*\d\s*P", re.IGNORECASE)
_IMPLICIT_CONTENT_HEAD_RE = re.compile(r"^([A-Z][A-Za-z&/,'\u2019\- ]{2,60}?):\s+\S")
_IMPLICIT_CONTENT_HEAD_MAX_WORDS = 6
_NUMBERED_LINE_RE = re.compile(r"^\(?\d{1,2}[.)]\s")
OUTCOMES_LABEL_RE = re.compile(
    r"^\s*(course|learning)\s*outcomes?\s*[:\-]?(?!\s*\d)\s*(.*)$", re.IGNORECASE
)
# Relaxed from requiring the label ALONE on the line: the real CBIT format is
# "COURSE OUTCOMES: After completion of this course, students will be able
# to" -- an explanatory lead-in sentence on the SAME line as the label. Group
# 2 (the lead-in text, if any) is intentionally discarded by the caller, not
# treated as outcome #0 -- it opens the outcomes block, nothing more.
# The (?!\d) negative lookahead is required so this block-header trigger does
# NOT also swallow an individually-numbered outcome line that happens to
# share the same leading words, e.g. "Learning Outcome 5: Evaluate
# tradeoffs" or "Course Outcome 4: Analyze complexity" -- those must reach
# OUTCOME_LABEL_RE's per-item parsing below instead.
# GENERIC fix for a real gap found auditing actual CBIT/AICTE documents:
# many real syllabi do NOT label unit content with an explicit "Topics:"
# marker at all -- the content is just dense paragraph text directly under
# the UNIT/MODULE/PART heading (e.g. CBIT: "UNIT-I\nPartial Differentiation
# and Its Applications: Functions of two or more variables, ..."). Without
# this, 0 topics were extracted from either real document. The fix: once a
# module/part heading has been seen, any following line that isn't itself a
# recognized special line (course code, another heading, a topics/outcomes
# label, or one of the section-boundary labels below) is treated as that
# module's content and split the same way an explicit "Topics:" list would
# be -- this SUBSUMES the explicit-label case rather than replacing it.
#
# SECTION_BOUNDARY_RE stops that fallback capture at the start of a
# reference/bibliography/objectives/matrix section, so "TEXT BOOKS:",
# "SUGGESTED READING:", etc. are never swept in as fake topics. This list
# is generic academic-document vocabulary (found in BOTH real documents),
# never a university name.
SECTION_BOUNDARY_RE = re.compile(
    r"^\s*(text\s*books?|references?|suggested\s*readings?|online\s*resources?|"
    r"course\s*objectives?|pre-?requisites?|"
    r"co-?po(-?pso)?\s*(articulation)?\s*matrix|course\s+articulation\s+matrix|"
    r"list\s+of\s+(experiments|exercises))\s*[:\-]?\s*$",
    re.IGNORECASE,
)
# Broader label set observed on the real AICTE model curriculum, where the
# strict pattern above missed every one of these and the textbook /
# contributor lists underneath were captured as unit content:
#   "Textbooks/References:", "TEXTBOOKS/REFERENCES:", "Reference Books:",
#   "Suggested text books / Online lectures or tutorials:",
#   "Suggested reference books / Online resources:", "Suggested textbooks:",
#   "Text Books/Suggested References:", "Prepared by:", "ONLINE REFERENCES:",
#   "Suggested list of experiments from the following:".
# A line counts as a boundary when it STARTS with one of these labels and is
# heading-shaped: it ends with a colon, or is at most six words, or the label
# is immediately followed by a colon. Prose that merely begins with such a
# word ("reference to economy, health, safety, ...") is not a boundary.
_BOUNDARY_LABEL_RE = re.compile(
    r"^\s*(suggested\s+)?(text\s*(/|and|&)\s*reference\s*books?|text\s*-?\s*books?|reference\s*books?|references?|readings?|"
    r"(alternative\s+)?(mooc|nptel|swayam)(\s*/\s*(mooc|nptel|swayam))*\s+courses?|"
    r"online\s+(resources?|references?|lectures?)|e-?\s?resources?|web\s*resources?|bibliography|"
    r"prepared\s+by|contributors?|list\s+of\s+(experiments|exercises|contributors)|"
    r"course\s*objectives?|co-?po(-?pso)?\s*(articulation)?\s*matrix)\b(\s*:)?",
    re.IGNORECASE,
)


def is_section_boundary(line):
    if SECTION_BOUNDARY_RE.match(line):
        return True
    match = _BOUNDARY_LABEL_RE.match(line)
    if not match:
        return False
    stripped = line.strip()
    label_then_colon = match.group(0).rstrip().endswith(":") or stripped[match.end():].lstrip().startswith(":")
    return stripped.endswith(":") or len(stripped.split()) <= 6 or label_then_colon


# Individual outcome numbering within an outcomes block: "CO1", "CLO1",
# "CO 1", "CLO 1", "Course Outcome 1", "Learning Outcome 1", or a bare
# "1." -- captures the label separately so the original identifier is
# never discarded (spec: "without losing the original wording or identifier").
OUTCOME_LABEL_RE = re.compile(
    r"^\s*(?:(CLO|CO)\s*-?\s*(\d+)|(course|learning)\s+outcome\s*(\d+)|(\d+)[.)])\s*[:\-]?\s*(.*)$",
    re.IGNORECASE,
)


@dataclass
class ExtractedCourse:
    course_code: str | None
    course_name: str | None
    page_number: int
    confidence: float
    category: str | None = None  # e.g. "Professional Elective-II" -- real text from a parenthetical line following the title, when present; never inferred/guessed
    semester: str | None = None  # the SEMESTER heading in force where this occurrence appears ("I".."VIII" or digits), exactly as the document states it; None when no heading has been seen yet -- never inferred from the course code
    semester_stated: str | None = None  # the course's own semester statement in its syllabus header ("II Year II Sem." -> "IV"), when one follows the header within STATEMENT_WINDOW_LINES lines; preferred over a carried heading


@dataclass
class ExtractedModule:
    course_code: str | None
    heading_label: str  # e.g. "Unit 1"
    title: str | None
    page_number: int


@dataclass
class ExtractedTopic:
    course_code: str | None  # PHASE-1 HARDENING FIX: without this, two courses that both
    # have a "Unit 1" heading collide -- topic attribution must key on
    # (course_code, module_heading_label), never on module_heading_label alone.
    module_heading_label: str | None
    topic_text: str
    page_number: int
    source_line: str | None = None  # the full line the fragment was split from -- lets downstream noise
    # checks see a whole citation ("2. Erwin Kreyszig, Advanced Engineering Mathematics, 9th Edition, ...")
    # instead of an innocent-looking fragment ("Erwin Kreyszig")


@dataclass
class ExtractedOutcome:
    course_code: str | None  # same fix as ExtractedTopic -- outcomes must stay scoped to their course
    text: str
    page_number: int
    label: str | None = None  # original identifier as written, e.g. "CO1", "CLO1", "Course Outcome 1" -- never discarded or renumbered


@dataclass
class ExtractedPrerequisite:
    course_code: str | None  # the course whose section contains the statement
    text: str                # the statement exactly as written after the label, e.g. "Basic knowledge of programming language such as python."
    page_number: int
    is_explicit_none: bool = False  # True when the document explicitly says "Nil"/"None"/"-" -- a stated absence, distinct from "no statement found"


@dataclass
class CurriculumStructure:
    courses: list = field(default_factory=list)
    modules: list = field(default_factory=list)
    topics: list = field(default_factory=list)
    outcomes: list = field(default_factory=list)
    prerequisites: list = field(default_factory=list)
    learned_code_shapes: list = field(default_factory=list)  # code shapes this document demonstrated (learn_code_shapes)

    @property
    def courses_found(self) -> int:
        return len(self.courses)

    @property
    def is_empty(self) -> bool:
        return not (self.courses or self.modules or self.topics)


def _looks_like_title(text):
    """
    Generic heuristic (not tied to any specific course/university): does
    this line look like a course TITLE (mostly letters) rather than a
    table row of digits/dashes/credit-hour cells? Used to decide whether a
    line immediately following a bare course-code line is genuinely that
    course's title (real documents commonly put the code alone on one line
    and the title on the next) versus unrelated table noise.
    """
    if not text:
        return False
    alpha = sum(1 for ch in text if ch.isalpha())
    digit = sum(1 for ch in text if ch.isdigit())
    return alpha >= 3 and alpha > digit


_CATEGORY_PAREN_RE = re.compile(r"^\(([^)]+)\)$")

# A line consisting ONLY of a semester heading. Real variants observed across
# the AICTE, CBIT R22 and CBIT R22A documents: "SEMESTER – I", "SEMESTER-II",
# "SEMESTER –VIII", "SEMESTER - V", "Semester VII", "SEMESTER VII". Roman or
# Arabic numerals; any dash/en-dash/em-dash/colon separator. Requiring the
# whole line keeps table headers ("Course Title Semester Hours per week") and
# prose ("Semester End Examination") from matching.
SEMESTER_HEADING_RE = re.compile(r"^\s*(?:semester\s*[-\u2013\u2014:]?\s*([IVX]{1,4}|\d{1,2})|(\d{1,2})(?:st|nd|rd|th)\s+semester"
                                 r"|(I{1,3}|IV|V|VI|[1-6])\s+year\s*[-,]?\s*(I{1,2}|[12])\s+sem(?:ester)?\.?)\s*$",
                                 re.IGNORECASE)
# second form ("1st Semester", "8th Semester") found on a real peer curriculum.


def semester_label(match):
    if match.group(3):
        return year_semester(match.group(3), match.group(4))
    return (match.group(1) or match.group(2)).upper()


_ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII")


def year_semester(year, sem):
    """'II' year, 'I' semester -> 'III': the programme semester of a semester-within-year statement. Only the two
    semesters of a year (I/II) are accepted by the patterns that call this, which is the structure such a statement
    names; any other shape is not converted (and not recognised)."""
    y = int(year) if year.isdigit() else _ROMAN.index(year.upper()) + 1
    s = int(sem) if sem.isdigit() else _ROMAN.index(sem.upper()) + 1
    return _ROMAN[2 * (y - 1) + s - 1]


# A course's own semester statement inside its syllabus header ("B.Tech. II Year II Sem.  L T P C"), read only in
# the first lines after the course header: it is evidence about THAT course, unlike a heading carried across pages.
COURSE_SEMESTER_STATEMENT_RE = re.compile(r"\b(I{1,3}|IV|V|VI|[1-6])\s+year\s*[-,]?\s*(I{1,2}|[12])\s+sem(?:ester)?\b",
                                          re.IGNORECASE)
STATEMENT_WINDOW_LINES = 3


# An outcome-to-programme-outcome matrix: its header row is a run of at least
# three "PO-n"/"POn"/"PSO-n" cells, its body rows are "CO-n" followed only by
# numbers or dashes, and a numeric legend ("1 - Slightly; 2 - Moderately; ...")
# may follow. The matrix ends an outcomes block. When the matrix precedes the
# course's content (no topic captured yet for the course -- a real peer layout
# with no "Syllabus:" label for some courses), the text that follows is the
# course content; when content was already captured (the matrix closes the
# course, as in other documents), nothing is opened.
MATRIX_HEADER_RE = re.compile(r"^\s*(?:(?:P(?:S)?O\s*-?\s*\d{1,2})\s+){2,}P(?:S)?O\s*-?\s*\d{1,2}\b.*$", re.IGNORECASE)
MATRIX_ROW_RE = re.compile(r"^\s*C\s*O\s*-?\s*\d{1,2}(?:\s+[\d\-\u2013\u2014]+)+\s*$", re.IGNORECASE)
MATRIX_LEGEND_RE = re.compile(r"^\s*\d\s*[-\u2013]\s*[A-Za-z]+\s*[;,]\s*\d\s*[-\u2013]\s*[A-Za-z]+", re.IGNORECASE)

# An explicit prerequisite statement: "PREREQUISITE: ...", "PRE-REQUISITES:
# ...", "Pre-requisites (if any): ...". The text after the label is kept
# verbatim; nothing is inferred when the label is absent.
PREREQUISITE_RE = re.compile(r"^\s*pre-?\s?requisites?\s*(?:\(\s*if\s+any\s*\))?\s*(?:details|remarks?)?\s*[:\-]\s*(.*)$", re.IGNORECASE)
# An enumerated list item ("1.", "2)", "(3)", bullet) -- used only while a
# bare "Prerequisites details:" label has opened a prerequisite LIST.
_LIST_ITEM_RE = re.compile(r"^\s*(?:\(?\d{1,2}[.)]|[\u2022\u25cf\-\*o])\s+(.+)$")


def _load_non_course_prefixes():
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "reference_data" / "non_course_identifiers.json"
    try:
        return {p.upper() for p in json.loads(path.read_text(encoding="utf-8")).get("prefixes", [])}
    except (OSError, ValueError):
        return set()


_NON_COURSE_PREFIXES = _load_non_course_prefixes()
# A document-structure heading that ends the current course's scope:
# "Appendix – II: A Guide to Induction Program", "Appendix 4", "Appendix- 5:",
# "Annexure I". Content after it belongs to no coded course until the next
# course header -- it stays unattributed rather than being credited to the
# last course seen (real case: a model curriculum's appendices of policy
# notes and uncoded mathematics courses were being credited to its last
# professional-core course). Note: unit numbering restarting inside a course
# is NOT such a signal -- real courses offer alternative syllabi that restart
# at "Module I".
APPENDIX_HEADING_RE = re.compile(r"^\s*(appendix|annexure|annex)\b\s*[-\u2013\u2014:]?\s*([IVX]{1,4}|\d{1,2}|[A-Z])?\b[\s:.\-\u2013\u2014]*(.{0,80})$", re.IGNORECASE)

_WRAP_END_RE = re.compile(r"\b(and|of|&|for|in|to|with|on)\s*$", re.IGNORECASE)


def _is_wrapped_title_fragment(text):
    """A title-shaped line that is not itself a structural marker -- used for
    table cells whose text wraps onto the lines above and below the row."""
    return bool(text) and _looks_like_title(text) and not COURSE_CODE_RE.search(text) \
        and not MODULE_HEADING_RE.match(text) and not SEMESTER_HEADING_RE.match(text)
# L-T-P / credit cells written as dash- or colon-joined digit groups, optionally
# followed by a parenthesised or bare credit count: "3-0-2 (4)", "4-0-0 (4)",
# "3-0-0-9", "3:0:2 4". Plain score-table rows ("3 - - 3 40 60 3") do not match.
_LTP_CELLS_RE = re.compile(r"\d{1,2}(?:\s*[-:]\s*\d{1,2}){2,3}(?:\s*\(?\s*\d{1,2}(?:\.\d)?\s*\)?)?")
_EXPLICIT_NONE_RE = re.compile(r"^\s*(nil|none|not applicable|n/?a|-+)\s*\.?\s*$", re.IGNORECASE)


# What may legitimately precede a course code on a course-HEADER line: nothing,
# a row enumerator ("1.", "12", "3)"), and/or a short upper-case category tag
# ("PCC", "PEC", "PROJ") as used in scheme-of-instruction tables. Anything
# else before the code means the code is being MENTIONED inside prose.
_HEADER_PREFIX_RE = re.compile(r"(?:\d{1,3}\s*[.)]?\s*)?[*\u2020#]?(?:[A-Z]{2,5}\s*[-\u2013]?\s*)?")
# The category tag may be joined to the code by a hyphen ("PCC-ME 201 Heat Transfer ... 3L:1T:0P 4 credits"): without
# it, every professional-core course of a real model curriculum was read as part of the course before it.


# ---- document-learned course-code shapes ---------------------------------------------------------------------
# Institutions number courses in their own way ("U26BS130MA", "UII26ES120CS"). Instead of a pattern per college,
# a document can SHOW its code shape: a scheme-of-instruction row is a code, a title and at least three numeric
# credit/hour/mark cells ("U26BS130MA Calculus & Linear Algebra 3 - - 3 60 40 3"). A shape is learned only when at
# least LEARNED_SHAPE_MIN_ROWS distinct codes of that shape head such rows and the built-in pattern does not already
# recognise them; it is then used for this document only. Nothing is learned from prose.
_SCHEME_ROW_RE = re.compile(
    r"^\s*(?:\d{1,3}\s*[.)]?\s+)?(?:[A-Z]{2,5}\s+)?([A-Z0-9]{5,14})\s+([A-Za-z(][^\n]*?[A-Za-z)])"
    r"((?:\s+(?:\d{1,3}(?:\.\d)?|[-\u2013\u2014])){3,})\s*$")
LEARNED_SHAPE_MIN_ROWS = 3
_RUN_RE = re.compile(r"[A-Z]+|\d+")


def _shape_key(token):
    """Letter runs and digit runs: digit-run lengths are kept exactly, letter-run lengths are generalised."""
    return tuple("A" if r.isalpha() else f"D{len(r)}" for r in _RUN_RE.findall(token))


def learn_code_shapes(pages):
    """Code shapes this document demonstrates in its scheme rows and the built-in pattern misses.
    Returns a list of {"pattern", "examples", "rows"}; empty for documents the built-in pattern already covers."""
    groups = {}
    for page_text in pages:
        for raw in (page_text or "").split("\n"):
            m = _SCHEME_ROW_RE.match(raw.strip())
            if not m:
                continue
            token, title = m.group(1), m.group(2)
            letters = sum(ch.isalpha() for ch in token)
            digits = sum(ch.isdigit() for ch in token)
            if letters < 2 or digits < 2 or not _looks_like_title(title) or COURSE_CODE_RE.fullmatch(token):
                continue
            if re.match(r"\d*([A-Za-z]+)", token).group(1).upper() in _NON_COURSE_PREFIXES:
                continue
            groups.setdefault(_shape_key(token), set()).add(token)
    shapes = []
    for key, tokens in sorted(groups.items()):
        if len(tokens) < LEARNED_SHAPE_MIN_ROWS:
            continue
        runs = [_RUN_RE.findall(t) for t in tokens]
        parts = []
        for i, kind in enumerate(key):
            if kind == "A":
                lengths = [len(r[i]) for r in runs]
                parts.append(f"[A-Z]{{{min(lengths)},{max(lengths)}}}")
            else:
                parts.append(f"\\d{{{kind[1:]}}}")
        shapes.append({"pattern": "".join(parts), "examples": sorted(tokens)[:5], "rows": len(tokens)})
    return shapes


def document_code_re(shapes):
    """COURSE_CODE_RE extended with a document's learned shapes (COURSE_CODE_RE itself when there are none)."""
    if not shapes:
        return COURSE_CODE_RE
    learned = "|".join(s["pattern"] for s in shapes)
    return re.compile(COURSE_CODE_RE.pattern.replace(r"\b(", r"\b(" + learned + "|", 1))


# An explicitly labelled code field: the label itself is the evidence that the token is a course code, wherever the
# field sits in a header block. Two real layouts: a field inside a line, with a separator ("... SEE Marks : 60 Course
# Code : U26BS130MA"), and a two-column header block whose line is only the label and the code ("Course Code
# CSPC11", followed by "Course Title  Discrete Structures"). The token must still have this document's code shape.
_LABELLED_CODE_LINE_RE = re.compile(r"^\s*course\s*code\s*[:\-\u2013]?\s*([A-Z0-9][A-Z0-9\-]{3,15})\s*$", re.IGNORECASE)
_LABELLED_CODE_INLINE_RE = re.compile(r"\bcourse\s*code\s*[:\u2013]\s*([A-Z0-9][A-Z0-9\-]{3,15})\b", re.IGNORECASE)
_LABELLED_TITLE_RE = re.compile(r"^\s*course\s*(?:title|name)\s*[:\-\u2013]?\s*(.+?)\s*$", re.IGNORECASE)
LABELLED_TITLE_WINDOW_LINES = 2
# Inside a labelled header block, the block's own semester statement ("SYLLABUS FOR B.E. I-SEMESTER", "Semester:
# III") within STATEMENT_WINDOW_LINES lines before or after the code field. A semester heading carried over from
# earlier pages is NOT used for a labelled course: such blocks form the detailed-syllabus section, which often follows
# the last semester's scheme table (a real peer document would otherwise have placed every elective in semester VI).
_BLOCK_SEMESTER_RE = re.compile(r"\b(?:([IVX]{1,4})\s*[-\u2013]?\s*semester|semester\s*[-\u2013:]?\s*([IVX]{1,4}|[1-9]|1[0-2]))\b",
                                re.IGNORECASE)


_SEMESTER_LIST_RE = re.compile(r"\b[IVX]{1,4}\s*(?:,|and|&|to|[-\u2013])\s*[IVX]{1,4}\b\s*[-\u2013]?\s*semesters?\b", re.IGNORECASE)


def _block_semester(line):
    """The single semester a header-block line states (roman or arabic), or None (none, or more than one --
    "I and II SEMESTER", "I to VIII Semesters" name a range, not a course's semester)."""
    if _SEMESTER_LIST_RE.search(line):
        return None
    found = {(m.group(1) or m.group(2)).upper() for m in _BLOCK_SEMESTER_RE.finditer(line)}
    year_sem = COURSE_SEMESTER_STATEMENT_RE.search(line)
    if year_sem:
        found.add(year_semester(year_sem.group(1), year_sem.group(2)))
    if len(found) != 1:
        return None
    value = found.pop()
    if value.isdigit():
        return _ROMAN[int(value) - 1] if 1 <= int(value) <= len(_ROMAN) else None
    return value if value in _ROMAN else None


def labelled_course_code(line, code_re=None):
    """The course code of a labelled code field on this line, or None."""
    m = _LABELLED_CODE_LINE_RE.match(line) or _LABELLED_CODE_INLINE_RE.search(line)
    if not m:
        return None
    token = m.group(1).replace("-", "").upper()
    if not (code_re or COURSE_CODE_RE).fullmatch(token):
        return None
    if re.match(r"\d*([A-Za-z]+)", token).group(1).upper() in _NON_COURSE_PREFIXES:
        return None
    return token


# A code followed at once by a year in brackets is a citation (a standard, a handbook, an edition), which reference
# lists put at the start of a numbered line just like a course row: "5. IS269 (2015), Ordinary Portland Cement".
_CITED_YEAR_RE = re.compile(r"\(\s*(?:19|20)\d{2}\s*\)")


def course_header_match(line, code_re=None):
    """
    Returns the COURSE_CODE_RE match only when the code heads the line as a
    course header; None when the code is merely mentioned.

    Real bug this fixes (found on the actual AICTE and CBIT R22A PDFs):
    code-shaped mentions inside prose were treated as new course headers and
    captured every following topic -- "3. CS403 to be scheduled in semester
    after CS402" took 408 AICTE topics away from the real course, "(MD5,
    SHA-256), understanding" took 164, "Applications of AI for COVID-19
    Pandemic" took 36 in CBIT. Two generic structural rules decide:
      1. only an enumerator and/or a short category tag may precede the code;
      2. the text after the code must be empty or start like a title/credit
         row -- a lower-case word or closing punctuation means the code sits
         in the middle of a sentence.
    """
    match = (code_re or COURSE_CODE_RE).search(line)
    if not match:
        return None
    alpha_prefix = re.match(r"\d*([A-Za-z]+)", match.group(1))
    if alpha_prefix and alpha_prefix.group(1).upper() in _NON_COURSE_PREFIXES:
        return None
    prefix = line[:match.start()].strip()
    if prefix and not _HEADER_PREFIX_RE.fullmatch(prefix):
        return None
    remainder = line[match.end():].strip(" -:\u2013\u2014")
    if remainder and (remainder[0].islower() or remainder[0] in ",.;:)]}"):
        return None
    if _CITED_YEAR_RE.match(remainder):
        return None  # "IS456 (2000), Plain and Reinforced Concrete.": a cited standard or edition, not a course
    return match


def resolve_best_course_titles(courses):
    """
    Real academic documents commonly list each course code MORE THAN ONCE
    (a semester-overview summary table row, plus a full detailed-syllabus
    section) -- and the quality of the captured title can differ between
    occurrences. This function NEVER assumes "first occurrence is best":
    for each course_code, it selects the occurrence whose course_name most
    looks like a real title (see _looks_like_title), breaking ties
    deterministically (most alphabetic content, then earliest page number).

    Returns {course_code: {"title": str|None, "category": str|None,
    "page_number": int, "confidence": float}} -- title is None (never
    fabricated) when NO occurrence of that code had a title-shaped name.
    This is a general-purpose resolver, not tied to any specific
    university/document; it operates purely on the structural quality of
    already-extracted text.
    """
    by_code = {}
    for c in courses:
        if c.course_code:
            by_code.setdefault(c.course_code, []).append(c)

    resolved = {}
    for code, entries in by_code.items():
        title_like = [e for e in entries if _looks_like_title(e.course_name or "")]
        if not title_like:
            best = min(entries, key=lambda e: e.page_number)
            resolved[code] = {"title": None, "category": None, "page_number": best.page_number, "confidence": 0.0,
                              "semester": _first_semester(entries)}
            continue

        def _score(e):
            name = e.course_name or ""
            alpha = sum(1 for ch in name if ch.isalpha())
            digit = sum(1 for ch in name if ch.isdigit())
            # Most alpha content wins first; if tied (a common case: a messy
            # summary-table row can have the same alpha count as a clean
            # detailed-syllabus title, just with extra credit/hour digits
            # appended), prefer FEWER digits -- the cleaner occurrence --
            # before finally falling back to earliest page for determinism.
            return (-alpha, digit, e.page_number)

        title_like.sort(key=_score)
        winner = title_like[0]
        resolved[code] = {
            "title": winner.course_name.strip(),
            "category": winner.category,
            "page_number": winner.page_number,
            "confidence": winner.confidence,
            "semester": _first_semester(entries),
        }
    return resolved


def _first_semester(entries):
    """A course's own semester statement (its syllabus header, e.g. "II Year
    II Sem.") when any occurrence carries one, earliest by page; otherwise the
    semester of the EARLIEST occurrence that sits under a semester heading.
    Scheme-of-instruction tables normally precede the detailed syllabus, so
    that is the scheme's placement; None when neither exists (never guessed)."""
    ordered = sorted(entries, key=lambda e: e.page_number)
    stated = next((e.semester_stated for e in ordered if getattr(e, "semester_stated", None)), None)
    if stated:
        return stated
    for e in ordered:
        if getattr(e, "semester", None):
            return e.semester
    return None


def structure_curriculum_pages(pages):
    """
    pages[i] = raw extracted text of page (i+1). Page numbers in the returned
    structure are 1-indexed to match how a human would reference "page 3 of
    the PDF".
    """
    result = CurriculumStructure()
    result.learned_code_shapes = learn_code_shapes(pages)
    code_re = document_code_re(result.learned_code_shapes)
    current_module_label = None
    current_course_code = None
    in_topics_block = False
    in_outcomes_block = False
    module_content_open = False  # True once a module/part heading has been seen and no boundary/new-course/new-module has ended it yet
    pending_course_ref = None  # ExtractedCourse awaiting a title on the next non-empty line (real documents commonly put a bare course code on its own line, title on the next) -- persists across page boundaries deliberately
    pending_category_ref = None  # ExtractedCourse awaiting a possible parenthetical category line ("(Professional Elective-II)") immediately after its title
    current_semester = None  # most recent SEMESTER heading seen; carried across pages
    in_prerequisite_list = False  # a bare "Prerequisites details:" label opened an enumerated list
    previous_line = None  # last non-empty line, for table cells that wrap ABOVE a code row
    title_topic_refs = []  # topics taken from the current unit's inline title (withdrawn if a Topics: label follows)
    wrapped_ref = None  # (ExtractedCourse, text_above) awaiting the continuation line BELOW a code row
    header_ref, lines_since_header = None, 0  # the latest course occurrence, and how many lines have followed it
    labelled_ref = None  # (course, lines seen) after a labelled code field, awaiting a labelled title field
    labelled_ids = set()  # id() of course occurrences opened by a labelled code field
    recent_lines = []  # the last STATEMENT_WINDOW_LINES non-empty lines before the current one
    course_has_module = False  # a unit/module/part heading has been seen since the current course header
    implicit_content = False  # the open content was opened by a "Heading: content" line (no unit heading, no label)
    header_has_ltp = False  # the current course header carries a lettered "3L:1T:0P" cell

    for page_idx, page_text in enumerate(pages):
        page_number = page_idx + 1
        lines = [ln.strip() for ln in (page_text or "").split("\n")]
        recent_lines = []  # a header block's look-back never crosses a page break

        for line in lines:
            if not line:
                continue
            line_above, previous_line = previous_line, line
            lines_before = recent_lines
            recent_lines = (recent_lines + [line])[-STATEMENT_WINDOW_LINES:]
            lines_since_header += 1
            if header_ref is not None and header_ref.semester_stated is None and lines_since_header <= STATEMENT_WINDOW_LINES:
                if id(header_ref) in labelled_ids:
                    # inside a labelled block even a heading-shaped line ("Semester: III") is the block's own statement
                    header_ref.semester_stated = _block_semester(line)
                else:
                    stated = COURSE_SEMESTER_STATEMENT_RE.search(line)
                    if stated and not SEMESTER_HEADING_RE.match(line):
                        header_ref.semester_stated = year_semester(stated.group(1), stated.group(2))

            if wrapped_ref is not None:
                course_ref, text_above = wrapped_ref
                wrapped_ref = None
                if _is_wrapped_title_fragment(line):
                    # Real layout: a scheme-table title cell wrapped around its
                    # row -- "Data Analysis and" / "3. 22CSC52  3 - - 3 40 60 3" /
                    # "Visualization". Accepted only when the text above ends on
                    # a joining word AND the line below is title-shaped; the
                    # occurrence gets a lower confidence than an inline title.
                    course_ref.course_name = f"{text_above} {line}"
                    course_ref.confidence = 0.6
                    continue

            if pending_category_ref is not None:
                cat_match = _CATEGORY_PAREN_RE.match(line)
                if cat_match:
                    pending_category_ref.category = cat_match.group(1).strip()
                pending_category_ref = None  # only ever checked once, right after the title -- no fabrication if absent

            if pending_course_ref is not None:
                # This line is a candidate title for the immediately
                # preceding BARE course-code line. Accept it only if it
                # looks like a real title and is not itself another
                # structural marker (a new course code or a module/part
                # heading) -- otherwise give up silently, never fabricating
                # a title. A parenthetical category line right after the
                # title ("(Professional Elective-II)") is captured too,
                # when present.
                is_new_code = code_re.search(line)
                is_heading = MODULE_HEADING_RE.match(line) or PART_HEADING_RE.match(line)
                if not is_new_code and not is_heading and _looks_like_title(line):
                    pending_course_ref.course_name = line
                    pending_course_ref.confidence = 0.8
                    pending_category_ref = pending_course_ref
                    pending_course_ref = None
                    continue
                pending_course_ref = None  # give up -- name stays whatever it already was (often None), never guessed

            if APPENDIX_HEADING_RE.match(line) and len(line.split()) <= 12:
                current_course_code = None
                current_module_label = None
                module_content_open = False
                in_topics_block = False
                in_outcomes_block = False
                in_prerequisite_list = False
                continue

            semester_match = SEMESTER_HEADING_RE.match(line)
            if semester_match:
                current_semester = semester_label(semester_match)
                module_content_open = False  # a semester heading ends any open unit's content
                in_topics_block = False
                in_outcomes_block = False
                continue

            if in_prerequisite_list:
                item = _LIST_ITEM_RE.match(line)
                if item and current_course_code is not None:
                    result.prerequisites.append(ExtractedPrerequisite(
                        course_code=current_course_code, text=item.group(1).strip(), page_number=page_number))
                    continue
                if line.startswith("(") and result.prerequisites:
                    continue  # parenthetical continuation of the previous list item
                in_prerequisite_list = False

            prereq_match = PREREQUISITE_RE.match(line)
            if prereq_match and current_course_code is not None:
                statement = prereq_match.group(1).strip()
                if statement:
                    result.prerequisites.append(ExtractedPrerequisite(
                        course_code=current_course_code, text=statement, page_number=page_number,
                        is_explicit_none=bool(_EXPLICIT_NONE_RE.match(statement)),
                    ))
                else:
                    in_prerequisite_list = True
                continue

            if labelled_ref is not None:
                course_ref, seen = labelled_ref
                titled = _LABELLED_TITLE_RE.match(line)
                if titled and _looks_like_title(titled.group(1)):
                    course_ref.course_name = titled.group(1)
                    course_ref.confidence = 0.8
                    labelled_ref = None
                    continue
                labelled_ref = (course_ref, seen + 1) if seen + 1 < LABELLED_TITLE_WINDOW_LINES else None

            code_match = course_header_match(line, code_re)
            if not code_match:
                token = labelled_course_code(line, code_re)
                if token:
                    # the field label is the evidence; a title is taken only from a labelled title field below it
                    title_topic_refs = []
                    current_course_code = token
                    course = ExtractedCourse(course_code=token, course_name=None, page_number=page_number,
                                             confidence=0.5, semester=None)
                    labelled_ids.add(id(course))
                    course.semester_stated = next((sem for sem in (_block_semester(b) for b in reversed(lines_before))
                                                   if sem), None)
                    result.courses.append(course)
                    header_ref, lines_since_header = course, 0
                    labelled_ref = (course, 0)
                    module_content_open = False
                    course_has_module = implicit_content = header_has_ltp = False
                    in_topics_block = False
                    in_outcomes_block = False
                    continue
            if code_match:
                recent_lines = []  # lines above this header belong to it, not to a labelled block below it
                title_topic_refs = []
                current_course_code = code_match.group(1).replace(" ", "").upper()
                # naive course-name heuristic: rest of the line after the code
                remainder = line[code_match.end():].strip(" -:\u2013\u2014")
                course = ExtractedCourse(
                    course_code=current_course_code,
                    course_name=remainder or None,
                    page_number=page_number,
                    confidence=0.8 if remainder else 0.5,
                    semester=current_semester,
                )
                result.courses.append(course)
                header_ref, lines_since_header = course, 0
                title_prefix = re.split(r"\s\S*\d", " " + remainder, maxsplit=1)[0].strip()
                if not remainder:
                    pending_course_ref = course  # look at the next non-empty line for its title
                elif title_prefix and _WRAP_END_RE.search(title_prefix) and len(title_prefix.split()) >= 2:
                    # Real layout: the title cell wraps BELOW the header row --
                    # "ESC-201  Programming  for  3L:0T:4P  5 Credits" / "Problem Solving".
                    # Joined only when the next line is title-shaped (same rule as above).
                    wrapped_ref = (course, " ".join(title_prefix.split()))
                elif not any(ch.isalpha() for ch in remainder) and line_above \
                        and _WRAP_END_RE.search(line_above) and _is_wrapped_title_fragment(line_above):
                    wrapped_ref = (course, line_above.strip())
                elif not any(ch.isalpha() for ch in remainder) and _LTP_CELLS_RE.fullmatch(remainder):
                    # Real peer layout: "CS1106   3-0-2 (4)" -- the header row carries only the
                    # L-T-P/credit cells and the title is the NEXT line. Same acceptance rule as a
                    # bare code line (title-shaped, not another marker), else nothing is guessed.
                    pending_course_ref = course
                in_topics_block = False
                in_outcomes_block = False
                module_content_open = False
                course_has_module = implicit_content = False
                header_has_ltp = bool(_LTP_LETTERED_RE.search(remainder))
                continue

            module_match = MODULE_HEADING_RE.match(line)
            part_match = None if module_match else PART_HEADING_RE.match(line)
            if module_match or part_match:
                if module_match:
                    label = f"{module_match.group(1).title()} {module_match.group(2)}"
                    title = module_match.group(3).strip() or None
                else:
                    label = f"Part {part_match.group(1).upper()}"
                    title = part_match.group(2).strip() or None
                current_module_label = label
                result.modules.append(
                    ExtractedModule(
                        course_code=current_course_code,
                        heading_label=label,
                        title=title,
                        page_number=page_number,
                    )
                )
                title_topic_refs = []
                if title:
                    # "Module II: Arithmetic expressions and precedence." -- an inline
                    # unit title IS the unit's content in this layout; it is kept as the
                    # unit title AND as topic fragments (it was previously dropped).
                    # If the unit then has an explicit "Topics:" label, the title was
                    # only a heading and these fragments are withdrawn again.
                    for topic in _split_topic_list(title):
                        ref = ExtractedTopic(current_course_code, current_module_label, topic, page_number, source_line=line)
                        result.topics.append(ref)
                        title_topic_refs.append(ref)
                in_topics_block = False
                in_outcomes_block = False
                module_content_open = True
                course_has_module, implicit_content = True, False
                continue

            if MATRIX_HEADER_RE.match(line) or MATRIX_ROW_RE.match(line) or MATRIX_LEGEND_RE.match(line):
                if MATRIX_HEADER_RE.match(line):
                    in_outcomes_block = False
                    in_topics_block = False
                    course_has_topics = any(t.course_code == current_course_code for t in result.topics[-400:]) \
                        if current_course_code else True
                    module_content_open = bool(current_course_code) and not course_has_topics and current_module_label is None
                    implicit_content = False
                continue

            if is_section_boundary(line):
                title_topic_refs = []
                module_content_open = False
                in_topics_block = False
                in_outcomes_block = False
                continue

            if TOPICS_LABEL_RE.match(line) or (header_has_ltp and TOPICS_LABEL_ALONE_RE.match(line)):
                if title_topic_refs:
                    withdrawn = {id(r) for r in title_topic_refs}
                    result.topics = [t for t in result.topics if id(t) not in withdrawn]
                    title_topic_refs = []
                in_topics_block = True
                in_outcomes_block = False
                after_label = TOPICS_LABEL_RE.sub("", line).strip() if TOPICS_LABEL_RE.match(line) else ""
                if after_label:
                    for topic in _split_topic_list(after_label):
                        result.topics.append(
                            ExtractedTopic(current_course_code, current_module_label, topic, page_number, source_line=line)
                        )
                continue

            if OUTCOMES_LABEL_RE.match(line) and line[:1].isupper():
                # The isupper() guard is required because of a real false
                # positive found in the AICTE document: a sentence that
                # simply WRAPS onto a new line starting with "learning
                # outcomes, etc." (all-lowercase, mid-sentence, not a
                # header) would otherwise falsely open the outcomes block
                # for the rest of the document. Every genuine header
                # observed in both real documents ("Course Outcomes:",
                # "COURSE OUTCOMES: ...") starts with an uppercase letter;
                # lowercase-first prose never is one.
                in_outcomes_block = True
                in_topics_block = False
                continue

            if in_topics_block:
                for topic in _split_topic_list(line):
                    if topic:
                        result.topics.append(
                            ExtractedTopic(current_course_code, current_module_label, topic, page_number, source_line=line)
                        )
                continue

            if in_outcomes_block:
                cleaned = line.lstrip("-*").lstrip("\u2022").strip()
                if cleaned:
                    label_match = OUTCOME_LABEL_RE.match(cleaned)
                    if label_match:
                        if label_match.group(1):  # CO / CLO
                            outcome_label = f"{label_match.group(1).upper()}{label_match.group(2)}"
                        elif label_match.group(3):  # "Course Outcome N" / "Learning Outcome N"
                            outcome_label = f"{label_match.group(3).title()} Outcome {label_match.group(4)}"
                        else:  # bare "N."
                            outcome_label = label_match.group(5)
                        outcome_text = label_match.group(6).strip() or cleaned
                    else:
                        outcome_label, outcome_text = None, cleaned
                    result.outcomes.append(ExtractedOutcome(current_course_code, outcome_text, page_number, outcome_label))
                continue

            if module_content_open and implicit_content and _NUMBERED_LINE_RE.match(line):
                module_content_open = implicit_content = False  # the numbered reference list after the content
                continue

            if header_has_ltp and not module_content_open and not course_has_module and current_course_code is not None:
                head = _IMPLICIT_CONTENT_HEAD_RE.match(line)
                after = line[head.end() - 1:] if head else ""
                if head and len(head.group(1).split()) <= _IMPLICIT_CONTENT_HEAD_MAX_WORDS and \
                        after.count(";") + after.count(",") >= 2 and not any(
                        t.course_code == current_course_code for t in result.topics[-400:]):
                    module_content_open = implicit_content = True

            if module_content_open:
                # No explicit "Topics:"/"Course Content:" label exists in
                # this real document's format -- the plain paragraph text
                # directly under a UNIT/MODULE/PART heading IS the content,
                # same splitting rule as the explicit-label case.
                for topic in _split_topic_list(line):
                    if topic:
                        result.topics.append(
                            ExtractedTopic(current_course_code, current_module_label, topic, page_number, source_line=line)
                        )
                continue

    return result


def _split_topic_list(line):
    """
    Splits a dense topic/content line into individual entries. Semicolons
    are tried FIRST when present: real syllabi commonly use them to
    separate higher-level topic groups while using commas only WITHIN each
    group for finer sub-items (verified against real CBIT R-22A text, e.g.
    "Types of communication: verbal and non-verbal; Barriers to
    communication; ..." -- splitting only on commas there would fragment
    each group into incoherent pieces). Falls back to comma-splitting when
    no semicolon is present.

    Sentences are separated first ("... fabrication in the lab. Soldering
    using soldering iron/station. ..." is one real table cell): a period
    after a lowercase letter, digit or ")" followed by a capital starts a new
    entry. Initials ("E. Balaguruswamy") and "vs. desktop" are not split.
    """
    line = line.lstrip("-*").lstrip("\u2022").strip()
    out = []
    for sentence in _SENTENCE_SPLIT_RE.split(line):
        sentence = sentence.strip()
        if ";" in sentence:
            out.extend(t.strip() for t in sentence.split(";") if t.strip())
        elif "," in sentence:
            out.extend(t.strip() for t in sentence.split(",") if t.strip())
        elif sentence:
            out.append(sentence)
    return out


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[a-z0-9)])\.\s+(?=[A-Z])")


def extraction_confidence(structure, page_count):
    """
    Simple, transparent confidence score: fraction of pages that contributed at
    least one recognized element (course code, module heading, or topic line).
    Not a learned model — deliberately explainable, per spec's explainability
    requirement, even at this early ingestion stage.
    """
    if page_count == 0:
        return 0.0
    contributing_pages = set()
    for c in structure.courses:
        contributing_pages.add(c.page_number)
    for m in structure.modules:
        contributing_pages.add(m.page_number)
    for t in structure.topics:
        contributing_pages.add(t.page_number)
    return round(len(contributing_pages) / page_count, 2)


# Only .pdf and .txt are genuinely implemented. .csv was previously accepted
# by the ingestion pipeline and silently read as one blob of plain text --
# that is NOT real CSV parsing (no column/field mapping, no per-row
# structure), so per Phase-1 hardening it is removed from the supported set
# rather than misrepresented as supported. python-docx is not wired in yet
# either. Add real CSV/DOCX support only when an actual column-mapped parser
# exists for a curriculum CSV schema.
SUPPORTED_CURRICULUM_EXTENSIONS = {".pdf": "pdfplumber", ".txt": "plain_text_read"}


def resolve_extraction_method(suffix):
    """
    Pure function (no I/O, no SQLAlchemy import) so the "is this file type
    actually supported" decision is independently unit-testable without
    pulling in the whole DB-dependent ingestion module. Raises ValueError
    with a message that names exactly what's missing -- never silently
    downgrades an unsupported type to plain-text reading.
    """
    suffix = suffix.lower()
    if suffix not in SUPPORTED_CURRICULUM_EXTENSIONS:
        raise ValueError(
            f"Unsupported curriculum file type: '{suffix}'. Supported: "
            f"{sorted(SUPPORTED_CURRICULUM_EXTENSIONS.keys())}. "
            f".csv is intentionally not supported yet -- it would previously "
            f"have been read as one plain-text blob with no real column "
            f"parsing, which is not genuine CSV support."
        )
    return SUPPORTED_CURRICULUM_EXTENSIONS[suffix]
