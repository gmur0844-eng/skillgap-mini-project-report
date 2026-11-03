"""
Skill-text normalization (Phase: ESCO normalization + skill extraction).

CRITICAL CONSTRAINT: normalization here means lowercasing and whitespace
collapsing ONLY. It must never strip or alter punctuation, because
punctuation is semantically load-bearing in technical skill names:

    C++      must stay C++      (not "C")
    C#       must stay C#       (not "C")
    .NET     must stay .NET     (not "NET")
    Node.js  must stay Node.js  (not "Node")
    ASP.NET  must stay ASP.NET  (not "ASPNET")

Any generic text-cleaning step (stemming, lemmatization, punctuation
stripping) is NEVER applied to skill mentions -- that is exactly the kind of
"blind" normalization the project spec prohibits.
"""
import re
import unicodedata
from functools import lru_cache

_WHITESPACE_RE = re.compile(r"\s+")


@lru_cache(maxsize=262_144)  # a pure function of the text, called for every mention and label of a run
def normalize_skill_text(text: str) -> str:
    """
    "Python" / "python" / "PYTHON" / "  Python  " all normalize to "python".
    "C++" normalizes to "c++" (case only -- the '++' is untouched).
    Deterministic: same input always produces the same output.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.strip().lower()
    text = _WHITESPACE_RE.sub(" ", text)
    return text


# Curated technical-token vocabulary (spec-mandated list). These are checked
# as their own extraction method ("technical_token") independent of whatever
# ESCO coverage happens to exist, because ESCO may not list every specific
# technology/library by name. A technical-token match does NOT by itself mean
# "mapped to ESCO" -- mapping_status stays "unmapped" unless the token ALSO
# resolves against the ESCO vocabulary index (see skill_extraction.py).
TECHNICAL_TOKENS = [
    "C++", "C#", ".NET", "Node.js", "React.js", "Next.js", "Vue.js",
    "PyTorch", "TensorFlow", "scikit-learn", "SQL", "MySQL", "PostgreSQL",
    "MongoDB", "AWS", "Azure", "GCP", "Docker", "Kubernetes", "ASP.NET",
]

# Deterministic per-method confidence tiers. Not derived from any real data
# (there is no "confidence dataset" for this) -- these are fixed, documented
# extraction-method confidences, analogous to the project's other named
# thresholds (see backend/app/core/config.py), not a fabricated analytical
# result.
METHOD_CONFIDENCE = {
    "structured_tag": 1.0,      # an explicit human-provided tag (e.g. Naukri's skills column)
    "exact_label": 1.0,         # case-sensitive exact match to an ESCO preferred_label
    "alias": 0.9,               # matched an ESCO alternative label
    "normalized_label": 0.85,   # matched an ESCO preferred_label only after case/whitespace normalization
    "technical_token": 0.6,     # matched the curated technical-token list, not (necessarily) ESCO
}
