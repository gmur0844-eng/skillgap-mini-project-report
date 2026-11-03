"""
Prerequisite relationships -- ONLY from explicit statements in the documents.

A statement ("PRE-REQUISITES: Basic knowledge of programming language such as
python.", "PCC 402: Computer Organization and Computer Architecture") is
EXTRACTED fact. Resolving it to a specific course in the same document uses
the deterministic Stage-1 matcher on the statement's parts against that
document's course titles (after removing generic lead-ins such as
"familiarity with" or "basic knowledge of"). A statement that resolves to no
course stays a free-text prerequisite (UNRESOLVED); nothing is inferred from
course order, semester or similarity, and no concept-level prerequisite is
invented.
"""
import re

from app.analytics.core_knowledge_mapping import MATCH_STATUS_COMPOUND, MATCH_STATUS_MATCHED, match_text_to_core_topics
from app.knowledge_engine.silver import uid

_LEAD_IN_RE = re.compile(
    r"^(a\s+)?(basic|basics|elementary|fundamental|good|working|prior|some)?\s*"
    r"(knowledge|familiarity|understanding|concepts?|course|exposure|background)\s+(of|with|in|on)\s+(the\s+)?",
    re.IGNORECASE,
)
_CODE_PREFIX_RE = re.compile(r"^[A-Z]{2,5}\s*-?\s*\d{2,4}[A-Z]?\s*[:\-]\s*")


def _parts(text):
    text = _CODE_PREFIX_RE.sub("", text.strip())
    text = _LEAD_IN_RE.sub("", text).rstrip(" .")
    return [p.strip() for p in re.split(r"\s*(?:,|;|\band\b|&)\s*", text, flags=re.IGNORECASE) if p.strip()]


def resolve_prerequisites(prerequisites, courses_by_doc, vocabulary):
    abbreviations, synonyms = vocabulary
    edges, unresolved = [], []
    for p in prerequisites:
        if p["is_explicit_none"]:
            continue
        doc_courses = courses_by_doc.get(p["doc_id"], [])
        candidates = [{"id": c["course_uid"], "name": c["title"]} for c in doc_courses if c["course_uid"] != p["course_uid"]]
        resolved = set()
        for part in _parts(p["text"]):
            result = match_text_to_core_topics(part, candidates, abbreviations, synonyms)
            if result["status"] == MATCH_STATUS_MATCHED:
                resolved.add((result["core_topic_id"], result["method"]))
            elif result["status"] == MATCH_STATUS_COMPOUND:
                resolved.update((c["core_topic_id"], c["method"]) for c in result["components"] if c.get("core_topic_id"))
        for prereq_course_uid, method in sorted(resolved):
            edges.append({"edge_uid": uid("edge", prereq_course_uid, p["course_uid"], "PREREQUISITE_OF", p["prerequisite_uid"]),
                          "source_uid": prereq_course_uid, "target_uid": p["course_uid"], "relationship": "PREREQUISITE_OF",
                          "method": f"explicit_statement+{method}", "evidence_status": "EXTRACTED",
                          "evidence": {"statement": p["text"], "page": p["page_number"], "doc_id": p["doc_id"]}})
        if not resolved:
            unresolved.append({**p, "resolution": "UNRESOLVED",
                               "reason": "statement names no course title of this document (kept verbatim as free text)"})
    return edges, unresolved
