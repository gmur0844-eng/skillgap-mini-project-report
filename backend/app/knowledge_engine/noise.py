"""
Topic-text noise classification -- generic, language-level rules only.

Every rule targets a SHAPE of text that is not curriculum content in any
discipline: bibliography entries, URLs, assessment/administrative prose,
merged table columns, line-wrap fragments, outcome statements. No rule names
a subject. Each rule was derived from noise actually observed in the real
AICTE and CBIT documents (examples in the comments), not guessed.

Noise is EXCLUDED from concept processing but never deleted: the raw
fragment stays in the topic records with its noise label.
"""
import re

TOPIC = "TOPIC"

_URL_RE = re.compile(r"(https?://|www\.|\.(com|org|in|edu|html?|ac\.in)\b|@[a-z0-9-]+\.)", re.IGNORECASE)

# "5. B.S. Grewal", "9. E. A. Coddington", "3. Kalpakjian S. And Steven S. Schmid",
# "Robert Tibshirani", "Springer, 2nd edition", "ISBN13: ...", "T1: Chapter 3", "12 of T2."
_BIBLIO_RE = re.compile(
    r"(\bisbn\b|\bedition\b|\bed\.\s|\bpublish(er|ing|ers)\b|\bpress\b|\bpearson\b|\bmcgraw|\bwiley\b|"
    r"\bspringer\b|\bprentice\b|\belsevier\b|\bcengage\b|\bo'?reilly\b|\bet\s+al\b|\breprint\b|\bchapters?\s+\d|"
    r"\b[TR]\d\s*[:.]|\bof\s+[TR]\d\b|\bsec(tion)?\.?\s+\d+\.\d+|\bvol(ume)?\.?\s*\d|\b(19|20)\d\d\b)",
    re.IGNORECASE,
)
# Person-name shape: initials followed by a capitalised surname ("B.S. Grewal",
# "E. A. Coddington", "P. K. Biswas").
_INITIALS_NAME_RE = re.compile(r"(^|\s)([A-Z]\.\s?){1,3}\s?[A-Z][a-z]{2,}")
# NOTE: a "Firstname Lastname" shape rule was tried and REMOVED -- it also
# matches ordinary two-word topics ("Linked Lists", "Heat Transfer"). Bare
# author names without initials therefore leak through; the topic-quality
# evaluation measures that leakage instead of hiding it.

# Assessment / delivery / administrative vocabulary. "Teaching Load: Faculty
# member...", "2. Tutorials: Weekly problem-solving sessions.", "CIE 40 Marks".
_ADMIN_RE = re.compile(
    r"(\d+\s*(marks?|credits?|hours?)\b|\bhours?\s+per\s+week|\bduration\s+of\b|\bsemester\s+end\b|"
    r"\btutorials?\s*:|\bweekly\b|\bfaculty\b|\bteaching\s+load\b|\bstudents?\s+(should|will|shall|may|are)\b|"
    r"\bassignments?\s*:|\battendance\b|\binternal\s+assessment\b|\blecture\s+hours\b|"
    r"\bcourse\s+(objectives?|outcomes?)\b|\bprogramme\s+outcomes?\b|\bprepared\s+by\b|\bsyllabus\s+committee\b)",
    re.IGNORECASE,
)
# Assessment acronyms are matched case-SENSITIVELY so the English word "see"
# is never mistaken for Semester End Examination.
_ADMIN_ACRONYM_RE = re.compile(r"\b(CIE|SEE|L-T-P|\d+L:\d+T:\d+P)\b")
_OUTCOME_RE = re.compile(r"^\s*(CO|CLO|PO|PSO)\s*-?\s*\d+\b|^\s*(able\s+to|students?\s+will)\b", re.IGNORECASE)
_INTERLEAVED_RE = re.compile(r"\S\s{5,}\S.*\S\s{5,}\S|\S\s{12,}\S")
_LEADING_FUNCTION_WORD = re.compile(r"^(and|or|of|the|so|to|try|which|that|with|for|in|on|by|as|is|are|if|then)\b", re.IGNORECASE)
_TRAILING_FUNCTION_WORD = re.compile(r"\b(and|or|of|the|to|for|in|with|on|by|as|a|an|from|into|using|its|their|is|are)\s*$", re.IGNORECASE)
_ENUM_PREFIX_RE = re.compile(r"^\s*(\(?[ivx]{1,4}\)|\(?\d{1,2}[.)]|\(?[a-h]\)|[•●▪\-\*o])\s+", re.IGNORECASE)


def clean_topic_text(text):
    """Deterministic cleaning: drop list markers, collapse whitespace, trim
    trailing punctuation. The raw text is always kept separately."""
    if not text:
        return ""
    cleaned = _ENUM_PREFIX_RE.sub("", text.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .;:,-–—")
    return cleaned


_CITATION_MARKERS = [
    re.compile(r"\bedition\b|\b\d+(st|nd|rd|th)\s+ed", re.IGNORECASE),
    re.compile(r"\bpublish(er|ers|ing)\b|\bpublications?\b|\bpress\b|\breprint\b", re.IGNORECASE),
    re.compile(r"\b(19|20)\d\d\b"),
    re.compile(r"\bisbn\b", re.IGNORECASE),
    re.compile(r"\b(pearson|wiley|springer|prentice|mcgraw|elsevier|cengage|pragati|khanna|laxmi|tata|narosa|s\.?\s?chand)\b", re.IGNORECASE),
    re.compile(r"(^|\s)([A-Z]\.\s?){1,3}\s?[A-Z][a-z]{2,}"),
    re.compile(r"\bet\s+al\b", re.IGNORECASE),
]


def looks_like_citation_line(line):
    """A whole source line with >= 2 independent citation markers is a
    bibliography entry; every fragment split from it is bibliography too."""
    if not line:
        return False
    return sum(1 for marker in _CITATION_MARKERS if marker.search(line)) >= 2


def classify_topic(raw_text, min_alpha_chars=4, max_words=25, source_line=None):
    """Returns (label, reason). label == TOPIC means usable curriculum content.
    source_line, when given, is the full line the fragment was split from."""
    raw = raw_text or ""
    if looks_like_citation_line(source_line):
        return "NOISE_BIBLIOGRAPHY", "fragment of a citation line (>= 2 citation markers on the source line)"
    text = clean_topic_text(raw)
    alpha = sum(ch.isalpha() for ch in text)
    if alpha < min_alpha_chars:
        return "NOISE_EMPTY", f"fewer than {min_alpha_chars} letters"
    if _URL_RE.search(raw):
        return "NOISE_URL", "URL, e-mail or file path"
    if _INTERLEAVED_RE.search(raw):
        return "NOISE_LAYOUT_INTERLEAVED", "multiple wide whitespace gaps: text from separate table columns merged into one line"
    if _BIBLIO_RE.search(text) or _INITIALS_NAME_RE.search(text):
        return "NOISE_BIBLIOGRAPHY", "bibliography / citation / author-name shape"
    if _OUTCOME_RE.search(text):
        return "NOISE_OUTCOME_STATEMENT", "course/programme outcome statement, not syllabus content"
    if _ADMIN_RE.search(text) or _ADMIN_ACRONYM_RE.search(text):
        return "NOISE_ADMINISTRATIVE", "assessment, delivery or administrative wording"
    words = text.split()
    if len(words) > max_words:
        return "NOISE_LONG_PROSE", f"more than {max_words} words: prose, not a topic"
    if _LEADING_FUNCTION_WORD.match(text) and text[0].islower():
        return "NOISE_FRAGMENT", "starts mid-sentence (line-wrap continuation)"
    if _TRAILING_FUNCTION_WORD.search(text) and len(words) <= 3:
        return "NOISE_FRAGMENT", "short fragment ending on a function word (line-wrap truncation)"
    if sum(ch.isdigit() for ch in text) > alpha:
        return "NOISE_EMPTY", "mostly digits"
    return TOPIC, ""
