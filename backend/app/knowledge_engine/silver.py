"""
SILVER: parsed curriculum structure -> contract-checked records with full
provenance (document, SHA-256, page, course, unit, extraction method).

Course validity is decided by GENERIC structural evidence, never by a list of
known-bad codes for a particular document:
  - a resolvable title-shaped name must exist in at least one occurrence;
  - the code must be placed in the programme structure: it appears under a
    semester heading, or it occurs more than once (scheme table + detailed
    syllabus). A code seen exactly once and under no semester heading (e.g.
    a programme-outcome label on a front-matter page) is quarantined with
    reason NO_STRUCTURAL_EVIDENCE -- unless the document attributes at least
    MIN_OWN_CONTENT_TOPICS topic fragments to it (a course catalogue lists
    each course once, with its own syllabus and no semester headings).
"""
import hashlib
import re
from collections import Counter, defaultdict

from app.knowledge_engine.noise import TOPIC, classify_topic, clean_topic_text
from app.pipelines.preprocessing.curriculum_structuring import COURSE_CODE_RE, _first_semester, _looks_like_title

_LTP_RE = re.compile(r"^\d+\s*L\s*:?\s*\d*\s*T?\s*:?\s*\d*\s*P?$", re.IGNORECASE)
_NUMERIC_TOKEN_RE = re.compile(r"^[\d.\-–—/]+$")
_ROMAN_RE = re.compile(r"^(I|II|III|IV|V|VI|VII|VIII)$")


def uid(prefix, *parts):
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def clean_course_title(raw):
    """
    Cut a course-title string at the first token that belongs to a scheme
    table's numeric columns: an L-T-P pattern ("3L:1T:0P"), a bare number or
    dash, the word "credit(s)", or a roman semester numeral that is followed
    by a numeric column, or a second course-code token (two-column scheme
    tables put two courses on one text line: "Software Testing  22CSE16N
    Software Testing Lab"). Whitespace is collapsed; original casing is kept.
    """
    if not raw:
        return ""
    tokens = re.sub(r"\s+", " ", raw).strip().split(" ")
    kept = []
    for i, token in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        is_column = (_LTP_RE.match(token) or _NUMERIC_TOKEN_RE.match(token)
                     or token.lower().rstrip(".") in {"credit", "credits", "hours"}
                     or COURSE_CODE_RE.fullmatch(token)
                     or (_ROMAN_RE.match(token) and kept and (_NUMERIC_TOKEN_RE.match(nxt) or _LTP_RE.match(nxt))))
        if is_column and kept:
            break
        if not is_column:
            kept.append(token)
    return " ".join(kept).strip(" -:–—,")


def _best_occurrence(entries):
    """Occurrence whose CLEANED title carries the most letters (ties: earliest
    page). Structured scheme-table rows and syllabus headers are both
    candidates; the choice never depends on which occurrence came first."""
    scored = []
    for e in entries:
        cleaned = clean_course_title(e.course_name or "")
        if cleaned and _looks_like_title(cleaned) and (cleaned[0].isalpha() and not cleaned[0].islower()):
            scored.append((-sum(ch.isalpha() for ch in cleaned), e.page_number, cleaned, e))
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]))
    return scored[0]


MIN_OWN_CONTENT_TOPICS = 5


def build_silver(doc, structure, quarantine, topic_cfg):
    """
    doc: validated DocumentRecord dict (manifest entry + sha256 + page_count).
    structure: CurriculumStructure from the parser.
    Returns dict of record lists: courses, units, topics, outcomes, prerequisites.
    """
    doc_id = doc["doc_id"]
    by_code = defaultdict(list)
    for occ in structure.courses:
        if occ.course_code:
            by_code[occ.course_code].append(occ)

    # A code seen once and under no semester heading is still placed in the programme
    # when the document gives it its OWN content (>= MIN_OWN_CONTENT_TOPICS topic
    # fragments attributed to it) -- a "courses of study" catalogue lists every course
    # exactly once, with no semester headings, and each entry carries its syllabus.
    topics_per_code = defaultdict(int)
    for t in structure.topics:
        if t.course_code:
            topics_per_code[t.course_code] += 1
    courses, valid_codes = [], {}
    for code in sorted(by_code):
        entries = by_code[code]
        first_page = min(e.page_number for e in entries)
        semester = _first_semester(entries)  # a course's own stated semester first, else the earliest heading
        best = _best_occurrence(entries)
        base = {"doc_id": doc_id, "course_code": code, "occurrences": len(entries), "first_page": first_page,
                "semester": semester, "pages": sorted({e.page_number for e in entries})}
        if best is None:
            quarantine.add("silver.course", base, "UNRESOLVED_TITLE: no occurrence carries a title-shaped name")
            continue
        if semester is None and len(entries) == 1 and topics_per_code.get(code, 0) < MIN_OWN_CONTENT_TOPICS:
            quarantine.add("silver.course", {**base, "title": best[2]},
                           "NO_STRUCTURAL_EVIDENCE: appears once and under no semester heading")
            continue
        _, title_page, title, occ = best
        record = {
            **base,
            "course_uid": uid("course", doc_id, code),
            "title": title,
            "title_raw": (occ.course_name or "").strip(),
            "title_page": title_page,
            "category": next((e.category for e in entries if e.category), None),
            "evidence_status": "EXTRACTED",
            "source_sha256": doc["sha256"],
        }
        courses.append(record)
        valid_codes[code] = record["course_uid"]

    units = []
    seen_units = set()
    for m in structure.modules:
        course_uid = valid_codes.get(m.course_code)
        if course_uid is None:
            continue
        key = (course_uid, m.heading_label)
        if key in seen_units:
            continue
        seen_units.add(key)
        units.append({"unit_uid": uid("unit", course_uid, m.heading_label), "course_uid": course_uid,
                      "label": m.heading_label, "title": m.title, "page_number": m.page_number})

    course_by_code = {c["course_code"]: c for c in courses}
    topics, ordinal = [], Counter()
    for t in structure.topics:
        course_uid = valid_codes.get(t.course_code)
        raw = (t.topic_text or "").strip()
        if not raw:
            continue
        if course_uid is None:
            quarantine.add("silver.topic", {"doc_id": doc_id, "course_code": t.course_code, "raw_text": raw,
                                            "page_number": t.page_number},
                           "ORPHAN_ATTRIBUTION: topic belongs to a course that failed validation")
            continue
        course = course_by_code[t.course_code]
        if t.page_number < course["title_page"] and t.page_number not in course["pages"]:
            # The course's own header appears only later and the course never
            # occurs on this page: the topic was carried over from an
            # unreadable preceding header, so its course is unknown.
            quarantine.add("silver.topic", {"doc_id": doc_id, "course_code": t.course_code, "raw_text": raw,
                                            "page_number": t.page_number},
                           "ATTRIBUTION_CONFLICT: topic precedes its course's header on a page where "
                           "the course does not occur")
            continue
        key = (doc_id, t.page_number, t.course_code, t.module_heading_label, raw)
        ordinal[key] += 1
        label, reason = classify_topic(raw, topic_cfg["min_alpha_chars"], topic_cfg["max_words"],
                                       source_line=getattr(t, "source_line", None))
        topics.append({
            "topic_uid": uid("topic", *key, ordinal[key]),
            "doc_id": doc_id, "course_uid": course_uid, "course_code": t.course_code,
            "unit_label": t.module_heading_label, "raw_text": raw, "clean_text": clean_topic_text(raw),
            "source_line": getattr(t, "source_line", None),
            "page_number": t.page_number, "extraction_method": doc.get("_page_methods", {}).get(t.page_number, "pdftotext_layout"),
            "noise_label": label, "noise_reason": reason,
            "evidence_status": "EXTRACTED" if label == TOPIC else "INSUFFICIENT_EVIDENCE",
        })

    def attribution_conflict(kind, code, page, text):
        course = course_by_code[code]
        if page < course["title_page"] and page not in course["pages"]:
            quarantine.add(kind, {"doc_id": doc_id, "course_code": code, "raw_text": text, "page_number": page},
                           "ATTRIBUTION_CONFLICT: precedes its course's header on a page where the course does not occur")
            return True
        return False

    outcomes = [{"outcome_uid": uid("outcome", doc_id, o.course_code, o.page_number, o.label, o.text),
                 "course_uid": valid_codes[o.course_code], "label": o.label, "text": o.text,
                 "page_number": o.page_number, "evidence_status": "EXTRACTED"}
                for o in structure.outcomes if o.course_code in valid_codes and o.text
                and not attribution_conflict("silver.outcome", o.course_code, o.page_number, o.text)]

    prerequisites = [{"prerequisite_uid": uid("prereq", doc_id, p.course_code, p.page_number, p.text),
                      "course_uid": valid_codes[p.course_code], "course_code": p.course_code, "text": p.text,
                      "page_number": p.page_number, "is_explicit_none": p.is_explicit_none,
                      "evidence_status": "EXTRACTED"}
                     for p in structure.prerequisites if p.course_code in valid_codes]

    return {"courses": courses, "units": units, "topics": topics, "outcomes": outcomes, "prerequisites": prerequisites}
