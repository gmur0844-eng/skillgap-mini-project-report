"""
Metadata suggestions read from an uploaded curriculum's own front matter (deterministic; nothing is guessed).

Only the first FRONT_PAGES pages are read: that is where a syllabus names its institution, degree, discipline,
regulation and year. Every suggestion carries the page and the exact line it was read from, and is either

  FOUND      one consistent value was found
  UNCERTAIN  several different candidates were found: all are listed, none is chosen for the person

A field with no evidence is simply absent. Suggestions only pre-fill the form: the person reviews and submits them,
and the server validates the submitted values as before. Nothing here names an institution or a discipline: the
discipline list used for matching is the one the system has already seen (evidence_metadata.disciplines()), plus
generic "... Engineering / Technology / Science" phrases.
"""
import re

FRONT_PAGES = 3

_INSTITUTION_WORD = re.compile(r"\b(institute|university|college|council|vidyapeeth|vishwavidyalaya)\b", re.IGNORECASE)
_NOT_A_NAME = re.compile(r"(affiliated|approved|accredited|recogni[sz]ed|sponsored|@|www\.|https?:|phone|fax|e-?mail|"
                         r"vision|mission|degree course in)", re.IGNORECASE)
_TRAILING = re.compile(r"\s*(\((?:a|autonomous)\)|,?\s*\(?autonomous\)?)\s*$", re.IGNORECASE)
_DEGREE = re.compile(r"(?<![A-Za-z])(B\.?\s?Tech\.?|B\.\s?E\.?|M\.?\s?Tech\.?|M\.\s?E\.?|B\.?\s?Sc\.?|M\.?\s?Sc\.?|"
                     r"BCA|MCA|B\.?\s?Arch\.?)(?![A-Za-z])")
_DISCIPLINE_PHRASE = re.compile(r"\b((?:[A-Z][A-Za-z]+|&|and)(?:\s+(?:[A-Z][A-Za-z]+|&|and|of)){0,6}\s+"
                                r"(?:Engineering|Technology|Science))\b", re.IGNORECASE)
_REGULATION = re.compile(r"(?<![A-Za-z0-9])R\s?[-–]?\s?(\d{2})(?![0-9])")
_YEAR = re.compile(r"\b(20\d{2})\s?[-–/]\s?(\d{2}|20\d{2})\b")
_YEAR_CONTEXT = re.compile(r"\b(a\.?\s?y\.?|academic year|admitted|with effect|applicable|batch)\b", re.IGNORECASE)


def _norm(text):
    """Comparison key: case, punctuation, spacing and '&' / 'and' do not make two values different."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").replace("&", "and").lower())


def _heading_like(line):
    """A title line, not prose: short, and every word capitalised (or a joining word)."""
    words = [w for w in re.split(r"\s+", line.strip()) if w]
    if not words or len(words) > 10:
        return False
    joining = {"and", "of", "&", "in", "for", "the", "with"}
    return all(w.lower() in joining or not w[0].isalpha() or w[0].isupper() for w in words)


def _clean_institution(line):
    parts = [p.strip() for p in re.split(r",|–|\s-\s", line)]
    named = [p for p in parts if _INSTITUTION_WORD.search(p) and not p.lower().startswith("department")]
    name = (named[0] if named else line).strip(" .,:;")
    name = re.sub(r"\s+\d{1,4}$", "", name)  # a running footer's page number
    return _TRAILING.sub("", name).strip(" .,:;")


def _suggest(found, field):
    """found: list of (value, page, line) in reading order -> one suggestion, or None."""
    if not found:
        return None
    distinct = []
    for value, page, line in found:
        if _norm(value) not in {_norm(v) for v, _, _ in distinct}:
            distinct.append((value, page, line))
    value, page, line = distinct[0]
    out = {"field": field, "value": value, "evidence": {"page": page, "text": line.strip()[:200]},
           "status": "FOUND" if len(distinct) == 1 else "UNCERTAIN"}
    if len(distinct) > 1:
        out["candidates"] = [{"value": v, "page": p, "text": l.strip()[:200]} for v, p, l in distinct[:5]]
        out["value"] = None  # several readings: the person chooses, nothing is picked for them
    return out


def infer_metadata(pages, known_disciplines=()):
    """pages: page texts (1-based order). Returns {"suggestions": {field: suggestion}, "pages_read": n}."""
    lines = [(i + 1, raw.strip()) for i, page in enumerate(pages[:FRONT_PAGES]) for raw in (page or "").split("\n")
             if raw.strip()]
    institutions, degrees, disciplines, versions, years, known_disciplines_found = [], [], [], [], [], []
    known = sorted({d for d in known_disciplines if d}, key=len, reverse=True)
    for page, line in lines:
        words = line.split()
        if _INSTITUTION_WORD.search(line) and not _NOT_A_NAME.search(line) and len(words) <= 16:
            name = _clean_institution(line)
            if _heading_like(name) and sum(ch.isalpha() for ch in name) >= 0.6 * len(name.replace(" ", "")):
                institutions.append((name, page, line))
        for m in _DEGREE.finditer(line):
            degrees.append((re.sub(r"\s", "", m.group(1)), page, line))
        hit = next((d for d in known if _norm(d) in _norm(line)), None)
        if hit:
            known_disciplines_found.append((hit, page, line))
        else:
            # a generic "... Engineering / Technology / Science" phrase counts only on a heading-like line that names
            # a degree or a department, or is set in capitals (not course rows, not vision statements)
            m = _DISCIPLINE_PHRASE.search(line)
            framed = _DEGREE.search(line) or re.search(r"\bdepartment of\b", line, re.IGNORECASE) or line.isupper()
            if m and framed and _heading_like(line) and not _INSTITUTION_WORD.search(m.group(1)) \
                    and len(m.group(1).split()) >= 2 and not _NOT_A_NAME.search(line) \
                    and not m.group(1).lower().startswith(("of ", "and ", "& ")):
                phrase = re.sub(r"^(?:(?:in|department\s+of|the|of)\s+)+", "", m.group(1), flags=re.IGNORECASE)
                if len(phrase.split()) >= 2:
                    disciplines.append((" ".join(w.lower() if w.lower() in ("&", "and", "of") else w.capitalize()
                                                 for w in phrase.split()), page, line))
        for m in _REGULATION.finditer(line):
            if "regulation" in line.lower() or re.fullmatch(r"R\s?[-–]?\s?\d{2}", m.group(0).strip()) and (
                    len(words) <= 8):
                versions.append((f"R{m.group(1)}", page, line))
        if _YEAR_CONTEXT.search(line):
            for m in _YEAR.finditer(line):
                end = m.group(2)[-2:]
                years.append((f"{m.group(1)}-{end}", page, line))
    suggestions = {}
    # a discipline the system already knows, named in the document, outranks generic phrases
    disciplines = known_disciplines_found or disciplines
    for field, found in (("institution", institutions), ("discipline", disciplines), ("curriculum_version", versions),
                         ("academic_year", years)):
        s = _suggest(found, field)
        if s:
            suggestions[field] = s
    degree = _suggest(degrees, "degree")
    if degree and degree["status"] == "FOUND":
        d = degree["value"].upper().replace(".", "")
        level = "undergraduate" if d.startswith("B") else "postgraduate" if d.startswith("M") else None
        if level:
            suggestions["degree_level"] = {"field": "degree_level", "value": level, "evidence": degree["evidence"],
                                           "status": "FOUND"}
        disc = suggestions.get("discipline")
        if disc and disc["status"] == "FOUND":
            suggestions["programme"] = {"field": "programme", "value": f"{degree['value']} {disc['value']}",
                                        "evidence": degree["evidence"], "status": "FOUND",
                                        "derived_from": ["degree", "discipline"]}
    elif degree:
        suggestions["degree"] = degree
    return {"suggestions": suggestions, "pages_read": min(len(pages), FRONT_PAGES),
            "note": "read from the document's first pages; check each value before submitting"}
