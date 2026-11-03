"""
Concepts vs. skills.

CONCEPT  = knowledge discovered from the curriculum (concepts.py).
SKILL    = an entry of a SKILL TAXONOMY (ESCO in this project) evidenced in text.

When a taxonomy vocabulary is supplied (rows shaped like the existing
Skill/SkillAlias tables), the project's existing extractor
(app.pipelines.preprocessing.skill_extraction) maps topic text to taxonomy
skills. When NO taxonomy is loaded -- the state of this repository, whose
ESCO file is absent -- no text is turned into a "skill". What CAN still be
surfaced without a hand-written list are TOOL/TECHNOLOGY CANDIDATES: tokens
whose spelling marks them as named products, languages, formats or
standards in any discipline (internal capitals: AutoCAD, PyTorch, MySQL;
symbols: C++, C#; dotted names: Node.js, .NET; letter-digit names: HTML5,
IPv6). They are reported as MODEL_SUGGESTED candidates awaiting taxonomy
mapping, kept separate from concepts, and never counted as skills.
All-caps acronyms are ambiguous (a tool or a concept) and are reported
separately as ACRONYM candidates requiring review.
"""
import re
from collections import defaultdict

from app.knowledge_engine.silver import uid

_TOOL_PATTERNS = [
    re.compile(r"(?<![\w.])[A-Za-z]+\+\+(?!\w)"),                      # C++
    re.compile(r"(?<![\w.])[A-Za-z]#(?!\w)"),                           # C#, F#
    re.compile(r"(?<![\w])(?:[A-Za-z]+)?\.(?:NET|js|JS|io)\b"),         # .NET, Node.js
    # mixed-case word with an INTERNAL capital and at least one lower-case
    # letter: PyTorch, JavaScript, MySQL, AutoCAD, PostgreSQL, LaTeX. ALL-CAPS
    # words ("DATA", "USING") have no lower-case letter and never match.
    re.compile(r"\b(?=[A-Za-z]*[a-z])[A-Za-z][a-z]*[A-Z][A-Za-z]*\b"),
    re.compile(r"\b[A-Za-z]{2,}[0-9]+[A-Za-z0-9]*\b"),                  # HTML5, IPv6, Python3
]
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}\b")
_ROMAN_RE = re.compile(r"^[IVXLC]+$")
_NOT_TOOLS = {"II", "III", "IV", "VI", "VII", "VIII", "AND", "OR", "OF", "THE", "FOR", "TO", "IN", "ON", "WITH",
              "CO", "PO", "PSO", "CLO", "UNIT", "MODULE"}


def _mostly_uppercase(text):
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and sum(ch.isupper() for ch in letters) / len(letters) > 0.6


def tool_candidates(text):
    found = {}
    for pattern in _TOOL_PATTERNS:
        for m in pattern.finditer(text):
            token = m.group(0).strip()
            if len(token) >= 2 and token.upper() not in _NOT_TOOLS:
                found[token] = "TOOL_OR_TECHNOLOGY"
    if not _mostly_uppercase(text):  # in ALL-CAPS headings every word looks like an acronym
        for m in _ACRONYM_RE.finditer(text):
            token = m.group(0)
            inside_found = any(token in f and token != f for f in found)
            if token not in found and not inside_found and token not in _NOT_TOOLS and not _ROMAN_RE.match(token):
                found[token] = "ACRONYM"
    return found


def build_skill_layer(topics, topic_to_concept, taxonomy_vocabulary=None):
    """
    Returns (skill_candidates, concept_skill_links, taxonomy_status).
    taxonomy_vocabulary: output of skill_extraction.build_vocabulary_index, or None.
    """
    taxonomy_status = "TAXONOMY_LOADED" if taxonomy_vocabulary else \
        "TAXONOMY_UNAVAILABLE: no skill taxonomy (ESCO) file is present in data/raw/esco -- no text is mapped to skills"
    by_token = defaultdict(lambda: {"topics": set(), "concepts": set(), "courses": set(), "docs": set(), "type": None})
    for t in topics:
        for token, kind in tool_candidates(t["clean_text"]).items():
            entry = by_token[token]
            entry["type"] = entry["type"] or kind
            entry["topics"].add(t["topic_uid"])
            entry["courses"].add(t["course_uid"])
            entry["docs"].add(t["doc_id"])
            if topic_to_concept.get(t["topic_uid"]):
                entry["concepts"].add(topic_to_concept[t["topic_uid"]])
    candidates, links = [], []
    for token in sorted(by_token):
        e = by_token[token]
        cand_uid = uid("skillcand", token)
        candidates.append({
            "skill_candidate_uid": cand_uid, "surface": token, "candidate_type": e["type"],
            "topic_count": len(e["topics"]), "course_count": len(e["courses"]), "documents": sorted(e["docs"]),
            "example_topic_uids": sorted(e["topics"])[:5],
            "taxonomy_mapping": None, "taxonomy_status": taxonomy_status.split(":")[0],
            "evidence_status": "MODEL_SUGGESTED" if e["type"] == "TOOL_OR_TECHNOLOGY" else "REVIEW_REQUIRED",
            "note": "token literally present in the topic text (EXTRACTED); treating it as a skill is a suggestion",
        })
        for concept_uid in sorted(e["concepts"]):
            links.append({"edge_uid": uid("edge", concept_uid, cand_uid, "MENTIONS_SKILL_CANDIDATE"),
                          "concept_uid": concept_uid, "skill_candidate_uid": cand_uid,
                          "method": "member topic text contains the token", "evidence_status": "MODEL_SUGGESTED"})
    return candidates, links, taxonomy_status
