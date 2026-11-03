"""
Job-description text cleaning (spec Section 8).

Goal: strip noise (HTML, URLs, emails, boilerplate, excess whitespace) WITHOUT
destroying technical tokens like C++, C#, .NET, Node.js, AWS, PyTorch. This is
why we don't use a generic "strip all punctuation" approach — punctuation is
semantically load-bearing in tech skill names.
"""
import re
import unicodedata

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_MULTI_WHITESPACE_RE = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

# Common recruitment boilerplate phrases we strip as whole lines/sentences —
# intentionally conservative (exact/near-exact phrase match) rather than
# aggressive keyword stripping, to avoid accidentally deleting real content.
_BOILERPLATE_PATTERNS = [
    re.compile(r"(?i)^\s*equal opportunity employer.*$", re.MULTILINE),
    re.compile(r"(?i)^\s*we are an equal opportunity.*$", re.MULTILINE),
    re.compile(r"(?i)^\s*job\s*id[:#]?\s*\S+\s*$", re.MULTILINE),
    re.compile(r"(?i)^\s*apply now.*$", re.MULTILINE),
    re.compile(r"(?i)^\s*click here to apply.*$", re.MULTILINE),
]


def clean_job_description(raw_text: str) -> str:
    """
    Deterministic, inspectable cleaning. Given the same raw_text, always
    produces the same clean_text (required for reproducibility, Section 42).
    """
    if not raw_text:
        return ""

    text = unicodedata.normalize("NFKC", raw_text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _EMAIL_RE.sub(" ", text)

    for pattern in _BOILERPLATE_PATTERNS:
        text = pattern.sub("", text)

    text = _MULTI_WHITESPACE_RE.sub(" ", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return text.strip()


# Tokens that must never be damaged by any future tokenization/cleaning step.
# Used by unit tests (Section 41) to assert the cleaner is technical-token-safe.
TECHNICAL_TOKEN_SAMPLES = [
    "C++", "C#", ".NET", "Node.js", "React.js", "AWS", "GCP", "SQL", "PyTorch",
]
