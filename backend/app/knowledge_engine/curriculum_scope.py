"""
Curriculum scope: does the TARGET curriculum cover the whole programme, or only part of it?

A gap is a claim about a whole programme ("the curriculum does not teach X"). When the supplied target document
covers only some semesters (for example a first-year syllabus), a skill absent from it may be taught in the semesters
that were not supplied, so a MISSING or PARTIAL classification cannot support a whole-programme deficiency claim.

The expected programme span is derived from the curriculum evidence of the same analysis, never from a fixed number
or a discipline rule:

  comparison curricula   every other healthy curriculum of the target's discipline (and degree level, when both
                         state one) whose courses carry semester labels starting at semester 1
  expected span          the largest last semester reached by at least `min_agreeing_documents` comparison curricula
                         (a single document, or one partial document such as an earlier version that stops at
                         semester IV, cannot set or lower it on its own)

  COMPLETE      the target's semesters include every semester 1..expected span
  INCOMPLETE    some of those semesters are absent from the target (listed)
  UNDETERMINED  the target has no semester labels, or no expected span is supported by enough comparison curricula

Only INCOMPLETE limits the gap claims; UNDETERMINED is reported and changes nothing.
"""
import re

COMPLETE, INCOMPLETE, UNDETERMINED, NOT_ASSESSED = "COMPLETE", "INCOMPLETE", "UNDETERMINED", "NOT_ASSESSED"
METHOD = "curriculum-scope-v1"

_ROMAN = {"i": 1, "v": 5, "x": 10}


def parse_semester(label):
    """'III' / 'iii' / '3' / 'Semester 3' / 'Sem-IV' -> 3 / 4; anything else -> None. Range 1..20."""
    if label is None:
        return None
    s = str(label).strip().lower()
    s = re.sub(r"^(semester|sem)[\s\-\.:]*", "", s)
    if re.fullmatch(r"\d{1,2}", s):
        n = int(s)
    elif s and re.fullmatch(r"[ivx]+", s):
        n, prev = 0, 0
        for ch in reversed(s):
            v = _ROMAN[ch]
            n, prev = (n - v, prev) if v < prev else (n + v, v)
        if _to_roman(n) != s:       # reject malformed numerals ('iiii', 'vx')
            return None
    else:
        return None
    return n if 1 <= n <= 20 else None


def _to_roman(n):
    out = ""
    for v, sym in ((10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out, n = out + sym, n - v
    return out


def _roman(n):
    return _to_roman(n).upper()


def semesters_of(courses):
    return sorted({s for s in (parse_semester(c.get("semester")) for c in courses) if s is not None})


def assess(target_doc, documents, courses_by_doc, cfg=None):
    """target_doc / documents: manifest document dicts (doc_id, role, discipline, degree_level); courses_by_doc:
    doc_id -> SILVER course records. Deterministic: same inputs, same result."""
    min_agree = int((cfg or {}).get("min_agreeing_documents", 2))
    base = {"method": METHOD, "min_agreeing_documents": min_agree,
            "target_doc": (target_doc or {}).get("doc_id"), "comparison": []}
    if not target_doc:
        return {**base, "status": UNDETERMINED, "reason": "no TARGET curriculum", "note": None}
    target_sems = semesters_of(courses_by_doc.get(target_doc["doc_id"], []))
    base["target_semesters"] = target_sems
    level = target_doc.get("degree_level")
    comparison = []
    for d in sorted(documents, key=lambda x: x["doc_id"]):
        if d["doc_id"] == target_doc["doc_id"] or d.get("discipline") != target_doc.get("discipline"):
            continue
        if level and d.get("degree_level") and d.get("degree_level") != level:
            continue
        sems = semesters_of(courses_by_doc.get(d["doc_id"], []))
        usable = bool(sems) and sems[0] == 1 and len(sems) >= 2
        comparison.append({"doc_id": d["doc_id"], "role": d.get("role"), "semesters": sems,
                           "last_semester": sems[-1] if sems else None, "used": usable,
                           **({} if usable else {"not_used_because": "no semester labels" if not sems else
                                                 "semester labels do not start at semester 1 or name one semester"})})
    base["comparison"] = comparison
    ends = sorted((c["last_semester"] for c in comparison if c["used"]), reverse=True)
    expected = ends[min_agree - 1] if len(ends) >= min_agree else None
    base["expected_last_semester"] = expected
    base["expected_span_support"] = sum(1 for e in ends if expected is not None and e >= expected)
    if not target_sems:
        return {**base, "status": UNDETERMINED, "reason": "the target curriculum's courses carry no semester labels",
                "missing_semesters": None, "note": None}
    if expected is None:
        return {**base, "status": UNDETERMINED, "missing_semesters": None, "note": None,
                "reason": (f"no programme span is supported by at least {min_agree} comparison curricula with semester "
                           f"labels ({len(ends)} available)")}
    missing = [s for s in range(1, expected + 1) if s not in target_sems]
    if not missing:
        return {**base, "status": COMPLETE, "missing_semesters": [], "note": None,
                "reason": f"the target covers semesters {_span(target_sems)} of the expected {_span(range(1, expected + 1))}"}
    note = (f"The target curriculum covers semesters {_span(target_sems)} of a programme that the other curricula of "
            f"this analysis show running to semester {_roman(expected)}. Skills absent from the supplied semesters may "
            f"be taught in semesters {_span(missing)}, which were not provided, so missing or partial coverage here is "
            "not a whole-programme deficiency: such gaps are marked for review and are not actionable.")
    return {**base, "status": INCOMPLETE, "missing_semesters": missing, "note": note,
            "reason": f"semesters {_span(missing)} of the expected {_span(range(1, expected + 1))} are not in the target"}


def _span(sems):
    """[1, 2, 3, 5] -> 'I–III, V'."""
    sems = sorted(sems)
    parts, start = [], None
    for i, s in enumerate(sems):
        if start is None:
            start = s
        if i == len(sems) - 1 or sems[i + 1] != s + 1:
            parts.append(_roman(start) if start == s else f"{_roman(start)}–{_roman(s)}")
            start = None
    return ", ".join(parts)


span_label = _span


def not_assessed():
    """For runs produced before the assessment existed (never recomputed for them)."""
    return {"method": METHOD, "status": NOT_ASSESSED,
            "reason": "this run was produced before curriculum scope was assessed; re-run the analysis to assess it",
            "note": None}
