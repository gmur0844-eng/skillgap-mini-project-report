"""Curriculum identity: when two curriculum documents are the same institution and the same programme.

One rule, used by the upload workflow (which earlier document becomes the comparison) and by the pipeline (which
comparison may run). It is branch- and institution-agnostic: names are compared after normalisation, acronyms are
recognised from the words themselves ("CBIT" / "Chaitanya Bharathi Institute of Technology"), and no institution,
discipline or specialisation is named in code.

Relations
  SAME_PROGRAMME                      same institution, same discipline, same specialisation (and degree level when
                                      both are stated) -> versions of one programme: curriculum changes (drift)
  SAME_INSTITUTION_OTHER_PROGRAMME    same institution, a different or unidentified programme -> a cross-programme
                                      comparison, never presented as version changes
  DIFFERENT_INSTITUTION               -> peer comparison only
  UNKNOWN                             an institution name is missing -> no comparison is inferred

A programme is identified only by what the metadata states: when one document names a specialisation and the other
does not, they are NOT assumed to be the same programme.
"""
from __future__ import annotations

import re

SAME_PROGRAMME = "SAME_PROGRAMME"
SAME_INSTITUTION_OTHER_PROGRAMME = "SAME_INSTITUTION_OTHER_PROGRAMME"
DIFFERENT_INSTITUTION = "DIFFERENT_INSTITUTION"
UNKNOWN = "UNKNOWN"

_STOP = {"of", "and", "the", "for", "in", "with"}
# words that name a degree rather than a programme ("B.E.", "B.Tech", "Bachelor of Engineering"); stripped only from the
# programme title when no discipline is stated, never from a discipline name
_DEGREE_WORDS = {"b", "e", "be", "btech", "tech", "bachelor", "bachelors", "m", "me", "mtech", "ug", "pg", "hons",
                 "honours", "degree", "programme", "program"}


def normalise(name) -> list[str]:
    return re.sub(r"[^a-z0-9 ]+", " ", (name or "").replace("&", " and ").lower()).split()


def _forms(name) -> set[str]:
    """The ways a name can be written: its words, its acronym, and any parenthesised acronym."""
    text = name or ""
    words = normalise(re.sub(r"\(([^)]*)\)", " ", text))
    inner = ["".join(normalise(x)) for x in re.findall(r"\(([^)]*)\)", text)]
    out = set()
    if words:
        out.add(" ".join(words))
        out.add("".join(words))                       # "ai ml" and "aiml" are one form
        out.add("".join(w for w in words if w not in _STOP))   # "AI & ML" and "AIML" are one form
        if len(words) > 1:
            out.add("".join(w[0] for w in words if w not in _STOP))
    out |= {i for i in inner if i}
    return out


def same_name(a, b) -> bool:
    """True when two names denote the same thing after normalisation or as acronym and expansion. Empty never matches."""
    fa, fb = _forms(a), _forms(b)
    return bool(fa and fb and fa & fb)


same_institution = same_name


def _discipline(doc) -> str:
    if (doc.get("discipline") or "").strip() and not (doc.get("discipline") or "").startswith("("):
        return doc["discipline"]
    words = [w for w in normalise(doc.get("programme")) if w not in _DEGREE_WORDS]
    return " ".join(words)


def relation(a: dict, b: dict) -> dict:
    """How two curriculum documents relate; returns {"relation", "reasons"} with reasons in plain words."""
    ia, ib = a.get("institution"), b.get("institution")
    if not (ia or "").strip() or not (ib or "").strip() or str(ia).startswith("(") or str(ib).startswith("("):
        return {"relation": UNKNOWN, "reasons": ["an institution is not stated, so no comparison is inferred"]}
    if not same_name(ia, ib):
        return {"relation": DIFFERENT_INSTITUTION, "reasons": [f"different institutions ({ia} / {ib})"]}
    reasons = []
    da, db = _discipline(a), _discipline(b)
    if not da or not db:
        reasons.append("the programme of one document is not identified")
    elif not same_name(da, db):
        reasons.append(f"different disciplines ({da} / {db})")
    sa, sb = (a.get("specialization") or "").strip(), (b.get("specialization") or "").strip()
    if sa or sb:
        if not (sa and sb):
            reasons.append(f"only one document states a specialisation ({sa or sb})")
        elif not same_name(sa, sb):
            reasons.append(f"different specialisations ({sa} / {sb})")
    la, lb = (a.get("degree_level") or "").strip(), (b.get("degree_level") or "").strip()
    if la and lb and not same_name(la, lb):
        reasons.append(f"different degree levels ({la} / {lb})")
    if reasons:
        return {"relation": SAME_INSTITUTION_OTHER_PROGRAMME, "reasons": reasons}
    return {"relation": SAME_PROGRAMME, "reasons": ["same institution and programme"]}
