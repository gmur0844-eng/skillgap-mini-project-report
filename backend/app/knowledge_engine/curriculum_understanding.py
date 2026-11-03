"""
Curriculum understanding (Phase 4, experimental). Builds a CurriculumProfile for one curriculum document and a
per-skill coverage record with an explicit evidence hierarchy.

What it reads, all of it general document structure:

  programme level     undergraduate / postgraduate words in the programme title (degree genre, not a discipline)
  course kind         the head noun of the course title: lab / workshop / studio -> PRACTICAL, project / internship /
                      thesis -> PROJECT, seminar -> SEMINAR, MOOC / certification -> SELF_DIRECTED, else THEORY
  course status       the scheme pages: a course printed as a numbered scheme row with its hours is COMPULSORY; a
                      course printed under a heading that says "elective" is an ELECTIVE_OPTION
  practical pairing   a practical course whose title is a theory course's title plus a practical head noun
  document scope      the semesters the document contains against comparable documents of the same level
  year of study       from the semester number

The coverage of a skill in one document keeps every piece of evidence with its type, ranked:

  1 TOPIC_DIRECT          a syllabus topic item IS the skill
  2 TOPIC_PARTIAL         the skill is the head of a topic item ("advanced X")
  3 PRACTICAL_TITLE       a practical course is named after the skill
  4 COURSE_TITLE          a (non-practical) course is named after the skill
  5 OUTCOME               a course outcome names the skill
  6 TOPIC_RELATED         the skill qualifies another subject ("X injection")
  7 TOPIC_INCIDENTAL      the skill is buried in a long item
  (8 TAXONOMY_NARROWER / 9 TAXONOMY_BROADER: a narrower or broader concept is taught -- context, never proof)

Topic evidence measures depth with the release rule (intelligence.coverage_depth, same thresholds). Title and outcome
evidence say that a course claims the skill but not how much of it is taught, so when they exist without topic
depth the level is UNCERTAIN, not ABSENT. Access (compulsory or elective only), practice (practical course or paired
practical) and the spread across courses and years are separate dimensions, never folded into the level.

No function names a university, programme, discipline, skill or subject; the word lists are the genre words of a
curriculum document (lab, project, elective, bachelor ...).
"""
import re
from collections import Counter, defaultdict

from app.knowledge_engine import intelligence as intel

METHOD = "curriculum understanding v0.1 (experimental, deterministic)"

EVIDENCE_RANK = {"TOPIC_DIRECT": 1, "TOPIC_PARTIAL": 2, "PRACTICAL_TITLE": 3, "COURSE_TITLE": 4, "OUTCOME": 5,
                 "TOPIC_RELATED": 6, "TOPIC_INCIDENTAL": 7, "TAXONOMY_NARROWER": 8, "TAXONOMY_BROADER": 9}
STRONG_TOPIC = ("TOPIC_DIRECT", "TOPIC_PARTIAL")
CLAIM_ONLY = ("PRACTICAL_TITLE", "COURSE_TITLE", "OUTCOME")
TAUGHT_LEVELS = ("INTRODUCTORY", "SUBSTANTIAL", "ADVANCED")
COVERAGE_LEVELS = ("ABSENT", "MENTION", "UNCERTAIN", "INTRODUCTORY", "SUBSTANTIAL", "ADVANCED")
ESTABLISHED = ("ESTABLISHED", "ESTABLISHED_BY_CONTEXT")

# ------------------------------------------------------------------ programme level

_UG = re.compile(r"(?<![a-z])(b\.?\s?e\.?|b\.?\s?tech|b\.?\s?sc|b\.?\s?s|b\.?\s?a|b\.?\s?com|b\.?\s?arch|b\.?\s?pharm|"
                 r"bachelor\w*|ug|under\s?graduate)(?![a-z])", re.I)
_PG = re.compile(r"(?<![a-z])(m\.?\s?e\.?|m\.?\s?tech|m\.?\s?sc|m\.?\s?s|m\.?\s?a|m\.?\s?com|mba|m\.?\s?phil|ph\.?\s?d|"
                 r"master\w*|pg|post\s?graduate|doctora\w*)(?![a-z])", re.I)


def programme_level(programme):
    """UNDERGRADUATE / POSTGRADUATE / UNKNOWN from the degree words of the programme title."""
    text = programme or ""
    ug, pg = bool(_UG.search(text)), bool(_PG.search(text))
    if ug and not pg:
        return "UNDERGRADUATE", f"degree word '{_UG.search(text).group(0)}' in the programme title"
    if pg and not ug:
        return "POSTGRADUATE", f"degree word '{_PG.search(text).group(0)}' in the programme title"
    if ug and pg:
        return "UNKNOWN", "the programme title has both undergraduate and postgraduate degree words"
    return "UNKNOWN", "no degree word in the programme title"


_ROMAN = {"i": 1, "v": 5, "x": 10}


def semester_number(sem):
    """'VI' / 'vi' / '6' / 6 -> 6; anything else -> None."""
    if sem is None:
        return None
    s = str(sem).strip().lower()
    if s.isdigit():
        return int(s) or None
    if s and all(ch in _ROMAN for ch in s):
        total, prev = 0, 0
        for ch in reversed(s):
            v = _ROMAN[ch]
            total, prev = (total - v, prev) if v < prev else (total + v, v)
        return total or None
    return None


def year_of_study(sem):
    n = semester_number(sem)
    return (n + 1) // 2 if n else None


# ------------------------------------------------------------------ course kind

_KIND_WORDS = {
    "PRACTICAL": r"lab|labs|laboratory|laboratories|workshop|practical|practicals|practicum|studio",
    "PROJECT": r"project|projects|capstone|internship|dissertation|thesis",
    "SEMINAR": r"seminar|colloquium",
    "SELF_DIRECTED": r"mooc|moocs|nptel|certification|training",
}
_KIND_RE = {k: re.compile(r"^(?:" + v + r")$", re.I) for k, v in _KIND_WORDS.items()}
# trailing qualifiers that follow the head noun of a course title: "Project Part-I", "Lab - II", "Seminar (2)"
_TRAILING = re.compile(r"(?:[\s\-–:/]+(?:part|phase|stage|work|course|[ivx]+|\d+|[a-d])\b[\s\-–.]*)+$", re.I)
_WORDS = re.compile(r"[a-z][a-z0-9+#]*", re.I)


def _head(segment):
    s = re.sub(r"\([^)]*\)", " ", segment or "")
    s = _TRAILING.sub("", s.strip())
    words = _WORDS.findall(s)
    return words[-1] if words else ""


def course_kind(title):
    """Kind from the HEAD noun of the title (or of any '/'-separated alternative): a word inside the title
    ("Laboratory Safety Management", "Software Project Management") does not change the kind."""
    heads = [_head(part) for part in re.split(r"\s/\s|/", title or "") if part.strip()]
    for kind in ("PRACTICAL", "PROJECT", "SEMINAR", "SELF_DIRECTED"):
        for h in heads:
            if _KIND_RE[kind].match(h):
                return kind, f"title head noun '{h}'"
    return "THEORY", "no practical, project, seminar or self-directed head noun in the title (title evidence only)"


def _title_key(title):
    return " ".join(w.lower() for w in _WORDS.findall(title or ""))


def practical_pairs(courses):
    """{practical course_uid: theory course_uid} when the practical title = the theory title + a practical head noun
    (same document)."""
    theory_by_title = {}
    for c in courses:
        if course_kind(c.get("title"))[0] == "THEORY":
            theory_by_title.setdefault((c["doc_id"], _title_key(c.get("title"))), c["course_uid"])
    out = {}
    for c in courses:
        if course_kind(c.get("title"))[0] != "PRACTICAL":
            continue
        s = _TRAILING.sub("", re.sub(r"\([^)]*\)", " ", c.get("title") or "").strip())
        words = _WORDS.findall(s)
        if len(words) < 2:
            continue
        base = " ".join(w.lower() for w in words[:-1])
        t = theory_by_title.get((c["doc_id"], base))
        if t:
            out[c["course_uid"]] = t
    return out


# ------------------------------------------------------------------ compulsory / elective status

_SERIAL = re.compile(r"^\s*\d{1,2}[.)]?\s+\S")
_OPTION_HEADING = re.compile(r"\b(electives?|honou?rs|minors?)\b", re.I)
HEADING_MAX_WORDS = 12       # a heading is a short line; prose that mentions electives is not one
_TOTAL = re.compile(r"^\s*total\b", re.I)
_NUMERIC = re.compile(r"(?<![\w.])(?:\d+(?:\.\d+)?|-)(?![\w.])")
_TOKEN = re.compile(r"[A-Za-z0-9]+")
SCHEME_ROW_MIN_NUMBERS = 1   # a scheme row prints at least its credits next to the numbered course


_SECTION_MARK = re.compile(r"^\s*(?:[a-h]|[ivx]{1,4}|\d{1,2})[.)]\s+\S+\s+\S+", re.I)
_ORDINAL = r"(?:[ivx]{1,4}|\d{1,2}|first|second|third|fourth|fifth|sixth|seventh|eighth|final)"
_SECTION_WORD = re.compile(r"\b(?:(?:semester|year|session|term)\W{0,3}" + _ORDINAL + r"|" + _ORDINAL +
                           r"(?:st|nd|rd|th)?\W{0,3}(?:semester|year|session|term))\b", re.I)
_TABLE_HEADER = re.compile(r"\b(code|title|credits?|hours|l-t-p|s\.?\s?no|sl\.?\s?no)\b", re.I)


def _line_kind(line, codes):
    found = sorted({t for t in _TOKEN.findall(line) if t in codes})
    serial = bool(_SERIAL.match(line))
    n = len(_TOKEN.findall(line))
    if found:
        return "COURSE", found, serial
    if _TOTAL.match(line):
        return "TOTAL", found, serial
    if 0 < n <= HEADING_MAX_WORDS and not serial and _OPTION_HEADING.search(line):
        return "OPTION_HEADING", found, serial
    if 0 < n <= HEADING_MAX_WORDS and _TABLE_HEADER.search(line):
        return "TABLE_HEADER", found, serial
    numeric = len(_NUMERIC.findall(line))
    if 0 < n <= HEADING_MAX_WORDS and ((_SECTION_MARK.match(line) and not numeric)
                                       or (_SECTION_WORD.search(line) and numeric <= 1)):
        return "SECTION_HEADING", found, serial
    return ("BLANK" if not n else "OTHER"), found, serial


def course_status(pages, codes):
    """
    {course_code: {"status", "evidence"}} from the scheme pages.
      - an OPTION heading is a short line (<= HEADING_MAX_WORDS words) that says elective, honours or minor, is not
        a numbered row and names no course of the document (honours and minor lists are options a student may add);
      - an option heading whose next line is a numbered row is a placeholder INSIDE a scheme table ("Professional
        Elective" printed beside its row): it opens nothing;
      - any other option heading opens a block of options that lasts until a 'Total' line, a section heading
        (a short line that starts with a section mark such as "c." / "IV." / "2." and has no numeric column, or
        that names an ordinal semester / year / session, e.g. "SEMESTER - VI", "Semester 3") or the next option
        heading;
      - a course on a NUMBERED line with >= SCHEME_ROW_MIN_NUMBERS numeric column (credits, hours) besides the serial
        number, outside an option block, is a COMPULSORY scheme row (a syllabus page header "CODE  L-T-P (C)" is not
        numbered, so it is not a scheme row).
    A numbered row on a page that follows an open option list, before any heading on that page, may continue the
    list: alone it leaves the course UNKNOWN. A code printed after another course on an option line (e.g. in a
    prerequisite column) is a reference when the course is also a scheme row. A course found both ways otherwise is CONFLICTING; found neither way, UNKNOWN.
    """
    codes = set(codes)
    ev = defaultdict(list)
    block = None
    for pno, page in enumerate(pages or [], 1):
        lines = (page or "").splitlines()
        kinds = [_line_kind(line, codes) for line in lines]
        # a page that follows an open option list may continue it without repeating the heading: its rows are
        # ambiguous until a heading or a total on the page settles where they belong
        carried, block = block, None
        for i, (line, (kind, found, serial)) in enumerate(zip(lines, kinds)):
            if kind == "OPTION_HEADING":
                nxt = next((k for k in kinds[i + 1:] if k[0] != "BLANK"), None)
                block, carried = (None if (nxt and nxt[2]) else line.strip()[:80]), None
                continue
            if kind in ("TOTAL", "SECTION_HEADING"):
                block = carried = None
                continue
            if kind != "COURSE":
                continue
            body = _SERIAL.sub(lambda m: m.group(0)[-1], line, count=1) if serial else line
            numeric = serial and len(_NUMERIC.findall(body)) >= SCHEME_ROW_MIN_NUMBERS
            first = min(found, key=line.index)
            for code in found:
                if block:
                    ev[code].append({"kind": "ELECTIVE_LIST", "page": pno, "heading": block, "first_on_line": code == first})
                elif numeric and carried:
                    ev[code].append({"kind": "ROW_AFTER_OPTION_LIST", "page": pno, "heading": carried})
                elif numeric:
                    ev[code].append({"kind": "SCHEME_ROW", "page": pno})
    out = {}
    for code in sorted(codes):
        rows = ev.get(code, [])
        if any(e["kind"] == "SCHEME_ROW" for e in rows):
            # a code printed later on an option line beside another course (a prerequisite column) is a reference to
            # that course, not an option entry
            rows = [e for e in rows if e["kind"] == "SCHEME_ROW" or e.get("first_on_line")]
        kinds = {e["kind"] for e in rows} - {"ROW_AFTER_OPTION_LIST"}   # ambiguous rows settle nothing
        if kinds == {"ELECTIVE_LIST"}:
            status = "ELECTIVE_OPTION"
        elif kinds == {"SCHEME_ROW"}:
            status = "COMPULSORY"
        elif kinds:
            status = "CONFLICTING"
        else:
            status = "UNKNOWN"
        out[code] = {"status": status, "evidence": rows[:4]}
    return out


# ------------------------------------------------------------------ document scope

def document_scope(doc, courses, comparable_docs_courses):
    """
    Semesters this document contains, against the most semesters found in comparable documents (same level: the
    institution's other curricula and the reference). COMPLETE when it has semesters 1..N for that N; PARTIAL when
    it has fewer; UNKNOWN when its semesters are not printed. Absence of a skill from a PARTIAL document is not
    evidence that the programme lacks it.
    """
    own = sorted({n for c in courses if c["doc_id"] == doc["doc_id"] for n in [semester_number(c.get("semester"))] if n})
    expected = max([max(own) if own else 0] + [max(ns) for ns in ({semester_number(c.get("semester")) for c in cs} - {None}
                                                     for cs in comparable_docs_courses.values()) if ns])
    if not own:
        return {"state": "UNKNOWN", "semesters": [], "expected_semesters": expected or None,
                "reason": "the document prints no semester for its courses"}
    full = list(range(1, expected + 1))
    missing = [n for n in full if n not in own]
    if not missing:
        return {"state": "COMPLETE", "semesters": own, "expected_semesters": expected,
                "reason": f"semesters 1-{expected} present"}
    return {"state": "PARTIAL", "semesters": own, "expected_semesters": expected, "missing_semesters": missing,
            "reason": (f"the document contains semester(s) {', '.join(map(str, own))} of {expected}; comparable "
                       f"documents of the same level have {expected}")}


def comparable_documents(doc, documents):
    """The institution's other curricula and REFERENCE documents of the same programme level."""
    lvl = programme_level(doc.get("programme"))[0]
    out = []
    for d in documents:
        if d["doc_id"] == doc["doc_id"]:
            continue
        same_level = programme_level(d.get("programme"))[0] in (lvl, "UNKNOWN") or lvl == "UNKNOWN"
        if same_level and (d.get("role") == "REFERENCE" or d.get("institution") == doc.get("institution")):
            out.append(d["doc_id"])
    return out


# ------------------------------------------------------------------ concept of a curriculum mention

def _lit(v):
    import ast
    return ast.literal_eval(v) if isinstance(v, str) and v[:1] in "[{(" else (v or [])


def syllabus_concept(m, mappings):
    """
    The concept a curriculum mention names, with the syllabus-genre rule of skill evidence v0.2 (curriculum_profile):
    an established taxonomy key; an ordinary word with exactly one candidate concept; or the one candidate whose
    preferred label is the wording. Otherwise the wording itself ("surface:<wording>") when its sense is established,
    else None.
    """
    key = str(m.get("skill_key") or "")
    if key.startswith("http") and m.get("sense_state") in ESTABLISHED:
        return key
    mp = (mappings or {}).get(m.get("normalized_text")) or {}
    cands = _lit(mp.get("candidates"))
    if m.get("esco_status") == "INSUFFICIENT_EVIDENCE" and len(cands) == 1 \
            and (mp.get("reason") or "").startswith("LABEL_CONTEXT_DEPENDENT"):
        return cands[0]["uri"]
    if len(cands) > 1:
        same = [c["uri"] for c in cands if (c.get("label") or "").lower() == (m.get("normalized_text") or "").lower()]
        if len(same) == 1:
            return same[0]
    if m.get("sense_established") and m.get("normalized_text"):
        return "surface:" + m["normalized_text"]
    return None


# ------------------------------------------------------------------ the profile

def build_profile(doc, documents, courses, pages=None):
    """CurriculumProfile of one document: identity, level, scope, and every course with year, kind, status and
    practical pairing."""
    mine = [c for c in courses if c["doc_id"] == doc["doc_id"]]
    level, level_reason = programme_level(doc.get("programme"))
    comp = comparable_documents(doc, documents)
    scope = document_scope(doc, courses, {d: [c for c in courses if c["doc_id"] == d] for d in comp})
    status = course_status(pages, [c["course_code"] for c in mine if c.get("course_code")]) if pages else {}
    pairs = practical_pairs(mine)
    paired_theory = defaultdict(list)
    for p, t in pairs.items():
        paired_theory[t].append(p)
    rows = {}
    for c in mine:
        kind, kind_reason = course_kind(c.get("title"))
        st = status.get(c.get("course_code"), {"status": "UNKNOWN", "evidence": []})
        rows[c["course_uid"]] = {
            "course_uid": c["course_uid"], "course_code": c.get("course_code"), "title": c.get("title"),
            "semester": c.get("semester"), "semester_number": semester_number(c.get("semester")),
            "year_of_study": year_of_study(c.get("semester")), "kind": kind, "kind_reason": kind_reason,
            "status": st["status"], "status_evidence": st["evidence"],
            "practical_of": pairs.get(c["course_uid"]), "practicals": sorted(paired_theory.get(c["course_uid"], []))}
    return {"doc_id": doc["doc_id"], "institution": doc.get("institution"), "programme": doc.get("programme"),
            "discipline": doc.get("discipline"), "role": doc.get("role"), "level": level, "level_reason": level_reason,
            "scope": scope, "comparable_documents": comp, "courses": rows,
            "course_kinds": dict(Counter(r["kind"] for r in rows.values())),
            "course_status": dict(Counter(r["status"] for r in rows.values())),
            "status_read_from_pages": bool(pages), "method": METHOD}


# ------------------------------------------------------------------ coverage with an evidence hierarchy

def _concept_rows(mentions, mappings, source_ok):
    out = defaultdict(list)
    for m in mentions:
        if not source_ok(m.get("source_uid")) or m.get("mention_role", "SKILL") != "SKILL":
            continue
        k = syllabus_concept(m, mappings)
        if k:
            out[k].append(m)
    return out


def skill_coverage(profile, topics_by_uid, topic_mentions, title_mentions, outcome_mentions, outcome_course,
                   mappings, prereq_edges, cfg, keys=None):
    """
    {skill key: coverage record} for one document.
      topic_mentions   extractor mentions over syllabus topics (source_uid = topic_uid)
      title_mentions   extractor mentions over course titles (source_uid = course_uid)
      outcome_mentions extractor mentions over course outcomes (source_uid = outcome_uid); outcome_course maps
                       outcome_uid -> course_uid
    """
    courses = profile["courses"]
    doc_id = profile["doc_id"]
    topics = _concept_rows(topic_mentions, mappings,
                           lambda u: (topics_by_uid.get(u) or {}).get("doc_id") == doc_id)
    titles = _concept_rows(title_mentions, mappings, lambda u: u in courses)
    outs = _concept_rows(outcome_mentions, mappings, lambda u: outcome_course.get(u) in courses)
    prereq_pairs = {(e["source_uid"], e["target_uid"]) for e in prereq_edges}
    universe = sorted(set(topics) | set(titles) | set(outs)) if keys is None else sorted(keys)
    rows = {}
    for key in universe:
        ev = []
        for m in topics.get(key, []):
            t = topics_by_uid[m["source_uid"]]
            rel = intel.mention_relation(t["clean_text"], m["span"], cfg["max_item_words"])
            c = courses.get(t["course_uid"], {})
            ev.append({"type": "TOPIC_" + rel, "course_uid": t["course_uid"], "course_code": c.get("course_code"),
                       "unit": t.get("unit_label"), "page": t.get("page_number"), "text": t["clean_text"][:160]})
        for m in titles.get(key, []):
            c = courses[m["source_uid"]]
            ev.append({"type": "PRACTICAL_TITLE" if c["kind"] == "PRACTICAL" else "COURSE_TITLE",
                       "course_uid": c["course_uid"], "course_code": c["course_code"], "text": c["title"]})
        for m in outs.get(key, []):
            c = courses[outcome_course[m["source_uid"]]]
            ev.append({"type": "OUTCOME", "course_uid": c["course_uid"], "course_code": c["course_code"],
                       "text": (m.get("context") or "")[:160]})
        for e in ev:
            c = courses.get(e["course_uid"], {})
            e.update(rank=EVIDENCE_RANK[e["type"]], course_kind=c.get("kind"), course_status=c.get("status"),
                     year_of_study=c.get("year_of_study"))
        ev.sort(key=lambda e: (e["rank"], str(e.get("course_code")), str(e.get("unit")), str(e.get("page"))))
        rows[key] = coverage_record(key, doc_id, ev, courses, prereq_pairs, cfg)
    return rows


def coverage_record(key, doc_id, ev, courses, prereq_pairs, cfg):
    types = Counter(e["type"] for e in ev)
    strong = [e for e in ev if e["type"] in STRONG_TOPIC]
    strong_courses = sorted({e["course_uid"] for e in strong})
    strong_units = sorted({(e["course_uid"], str(e.get("unit"))) for e in strong})
    progression = sorted((a, b) for a in strong_courses for b in strong_courses if (a, b) in prereq_pairs)
    claims = [e for e in ev if e["type"] in CLAIM_ONLY]
    # depth: the release rule over topic evidence (intelligence.coverage_depth, same thresholds)
    if not ev:
        level, why = "ABSENT", "no topic, title or outcome of this curriculum names the skill"
    elif strong and progression:
        level, why = "ADVANCED", "taught in a course and in a course it lists as prerequisite (progression)"
    elif strong and (len(strong) >= cfg["substantial_min_topics"] or len(strong_units) >= cfg["substantial_min_units"]):
        level, why = "SUBSTANTIAL", f"{len(strong)} direct/partial topics in {len(strong_units)} unit(s)"
    elif strong:
        level, why = "INTRODUCTORY", f"{len(strong)} direct/partial topic(s) in {len(strong_units)} unit(s)"
    elif claims:
        kinds = sorted({e["type"].lower().replace("_", " ") for e in claims})
        level, why = "UNCERTAIN", (f"named by {' and '.join(kinds)} ({', '.join(sorted({str(e['course_code']) for e in claims}))}) "
                                   "but no syllabus topic teaches it directly: the course claims the skill, the depth "
                                   "cannot be measured")
    else:
        level, why = "MENTION", "only related or incidental topic mentions (the skill qualifies another subject)"
    # access: the courses that carry direct evidence (topics or titles)
    carrying = sorted({e["course_uid"] for e in ev if e["type"] in STRONG_TOPIC + ("PRACTICAL_TITLE", "COURSE_TITLE")})
    statuses = {courses.get(u, {}).get("status", "UNKNOWN") for u in carrying}
    if not carrying:
        access = "NONE"
    elif "COMPULSORY" in statuses:
        access = "COMPULSORY"
    elif statuses == {"ELECTIVE_OPTION"}:
        access = "ELECTIVE_ONLY"
    else:
        access = "UNKNOWN"
    # practice: a practical course names it, a topic sits in a practical/project course, or the theory course that
    # teaches it has a paired practical course (inferred: practical experiments are not extracted)
    in_practical = any(e["type"] == "PRACTICAL_TITLE" or (e["type"] in STRONG_TOPIC and e.get("course_kind") in ("PRACTICAL", "PROJECT"))
                       for e in ev)
    paired = sorted({p for u in strong_courses + [e["course_uid"] for e in claims] for p in courses.get(u, {}).get("practicals", [])})
    if in_practical:
        practice = "PRACTISED"
    elif paired:
        practice = "PAIRED_PRACTICAL"
    elif strong:
        practice = "THEORY_ONLY"
    else:
        practice = "NONE"
    years = sorted({courses[u]["year_of_study"] for u in strong_courses if courses.get(u, {}).get("year_of_study")})
    if not strong_courses:
        pattern = "NONE"
    elif progression:
        pattern = "PROGRESSION_EXPLICIT"
    elif len(years) >= 2:
        pattern = "SPREAD_ACROSS_YEARS"
    elif len(strong_courses) >= 2:
        pattern = "SEVERAL_COURSES_ONE_YEAR"
    else:
        pattern = "SINGLE_COURSE"
    return {"skill_key": key, "doc_id": doc_id, "coverage_level": level, "level_reason": why,
            "evidence_types": dict(sorted(types.items(), key=lambda kv: EVIDENCE_RANK[kv[0]])),
            "strongest_evidence": ev[0]["type"] if ev else None,
            "access": access, "carrying_courses": [courses[u]["course_code"] for u in carrying if u in courses],
            "practice": practice, "paired_practicals": [courses[u]["course_code"] for u in paired if u in courses],
            "cross_course": {"courses": len(strong_courses), "years": years, "pattern": pattern,
                             "progression_pairs": len(progression)},
            "evidence": ev[:12], "method": METHOD}


def taxonomy_related(rows, store_skills):
    """For skills a document does not teach (ABSENT / MENTION): directly narrower or broader concepts it DOES teach
    (taxonomy hierarchy, one step). Context, never proof that the skill is taught."""
    taught = {k for k, r in rows.items() if r["coverage_level"] in TAUGHT_LEVELS}
    out = {}
    for key in rows:
        if rows[key]["coverage_level"] not in ("ABSENT", "MENTION") or key not in store_skills:
            continue
        broader = [b for b in _lit(store_skills[key].get("broader")) if b in store_skills]
        narrower = [u for u in taught if key in _lit((store_skills.get(u) or {}).get("broader"))]
        nar = sorted(u for u in narrower)
        bro = sorted(b for b in broader if b in taught)
        if nar or bro:
            out[key] = {"narrower_taught": [{"key": u, "label": store_skills[u]["pref_label"],
                                             "level": rows[u]["coverage_level"]} for u in nar],
                        "broader_taught": [{"key": u, "label": store_skills[u]["pref_label"],
                                            "level": rows[u]["coverage_level"]} for u in bro]}
    return out


def absent_record(key, doc_id):
    return coverage_record(key, doc_id, [], {}, set(), {"substantial_min_topics": 1, "substantial_min_units": 1})
