"""Skill qualification (EXPERIMENTAL; not wired into the authoritative pipeline).

Extraction finds phrases; qualification decides what each extracted phrase is and whether it may count as
curriculum-demand evidence. The two are separate stages:

  RAW JOB -> BOILERPLATE DETECTION -> JOB/DISCIPLINE RELEVANCE -> SKILL EXTRACTION -> SKILL QUALIFICATION
          -> NORMALIZATION / ESCO -> INDUSTRY DEMAND -> CURRICULUM COVERAGE -> GAP -> RECOMMENDATION

Every extracted mention is kept with its raw phrase, normalised phrase, span, sentence, posting and provenance; the
qualification adds a type, a decision, a confidence and the reason. Nothing is deleted.

Evidence used (no word list of skills, disciplines or institutions anywhere):
  * provenance       the text kind of the span (relevance.boilerplate): employer boilerplate is not job evidence;
  * taxonomy         the ESCO concept the mention resolves to: its type (knowledge / skill-competence), reuse level
                     (transversal / cross-sector / sector-specific / occupation-specific), immediate parents, and how
                     the surface matched it (preferred/alternative label, or a hidden search label, which is not proof
                     of the same concept);
  * sentence context requirement framing in the mention's clause -- the reader-facing grammar of a requirement
                     ("experience with X", "X skills", "ability to X", "knowledge of X") -- and taxonomy siblings
                     mentioned in the same sentence ("Python, Java and SQL");
  * surface form     a skill-competence concept named by its own verb phrase ("make decisions") vs. a nominal form
                     ("decision-making skills");
  * programme        the programme profile and its ESCO neighbourhood (relevance.programme_profile / neighbourhood).

Concept resolution
  * the release's established concept is used as is;
  * a surface with several candidate concepts resolves to the one candidate related (shared immediate ESCO parent)
    to another skill in the same sentence, if exactly one is;
  * a surface the release withheld because a single ordinary word does not establish a skill sense
    (LABEL_CONTEXT_DEPENDENT), or whose alias sense needs review, or which matched only a hidden label, resolves to
    its single ESCO candidate ONLY when the sentence supplies context: requirement framing, or another resolved
    mention in the same sentence that shares an immediate ESCO parent with the candidate. Otherwise it stays
    unresolved (EXCLUDED_INSUFFICIENT_CONTEXT) or ambiguous (AMBIGUOUS).

Decisions (first that applies), with the type of skill:
  EXCLUDED_BOILERPLATE         the span is employer boilerplate
  AMBIGUOUS                    several candidate concepts, or an alias / hidden-label match the context does not
                               confirm
  EXCLUDED_INSUFFICIENT_CONTEXT a context-dependent surface the sentence does not confirm, or no concept at all
  EXCLUDED_GENERIC_CAPABILITY  a skill-competence concept named by its bare verb phrase with no requirement framing:
                               the sentence describes an activity ("help customers modernise", "make decisions
                               about ..."), not a required competency
  TRANSVERSAL                  a transversal competency stated as a requirement or in nominal form (communication,
                               leadership): kept, reported, never a discipline gap
  QUALIFIED_TECHNICAL          a technology/tool, or a concept the programme's curricula name (the profile)
  QUALIFIED_PROFESSIONAL       a non-transversal skill-competence stated as a requirement (lead a team)
  QUALIFIED_DOMAIN             a knowledge (or non-transversal competence) concept the curricula do not name, e.g.
                               a finance concept for a computing programme: legitimate domain knowledge, counted in
                               demand, but not a gap for this programme unless the skill-level evidence (most of its
                               job-specific postings positively relevant) makes it DISCIPLINE_ADJACENT. Being next to
                               the profile in the taxonomy is recorded but is not enough on its own.
  DISCIPLINE_ADJACENT          (skill level) QUALIFIED_DOMAIN whose job-specific postings are mostly RELEVANT or
                               LIKELY_RELEVANT (relevance.skill_relevance)

Only QUALIFIED_TECHNICAL and DISCIPLINE_ADJACENT skills may become curriculum gaps; every QUALIFIED_* decision,
TRANSVERSAL and DISCIPLINE_ADJACENT counts in demand (in eligible postings).

Confidence is categorical (HIGH / MEDIUM / LOW), from the kind of evidence, never a model score:
  HIGH    preferred/alternative label or established sense, and (for skill-competences) requirement framing
  MEDIUM  resolved by sentence context (bound framing for an ordinary word; a related skill for an alias)
  LOW     ambiguous or unresolved
The requirement-framing cue words below are a grammatical lexicon of how requirements are phrased in English job
text; they name no skill, discipline or institution, and they are documented as such.
"""
from __future__ import annotations

import ast
import re

METHOD = "skill qualification v0.1 (experimental, deterministic)"
# v0.1 (after reading the v0 demand output, see docs/skill_qualification_methodology.md): an ordinary word resolves
# only when the requirement framing is bound to the word itself, not anywhere in its clause; an alias or hidden-label
# match resolves only through taxonomy context (a related skill in the sentence), never through framing alone; a
# concept merely next to the profile in the taxonomy is QUALIFIED_DOMAIN, not QUALIFIED_TECHNICAL.

DECISIONS = ("EXCLUDED_BOILERPLATE", "AMBIGUOUS", "EXCLUDED_INSUFFICIENT_CONTEXT", "EXCLUDED_GENERIC_CAPABILITY",
             "TRANSVERSAL", "QUALIFIED_TECHNICAL", "QUALIFIED_PROFESSIONAL", "QUALIFIED_DOMAIN")
DEMAND_ELIGIBLE = ("TRANSVERSAL", "QUALIFIED_TECHNICAL", "QUALIFIED_PROFESSIONAL", "QUALIFIED_DOMAIN",
                   "DISCIPLINE_ADJACENT")
GAP_ELIGIBLE = ("QUALIFIED_TECHNICAL", "DISCIPLINE_ADJACENT")
ESTABLISHED = ("ESTABLISHED", "ESTABLISHED_BY_CONTEXT")
REVIEW_SENSES = ("ALIAS_SENSE_REVIEW_REQUIRED", "CASE_SENSE_REVIEW_REQUIRED", "ACRONYM_SENSE_REVIEW_REQUIRED")

# grammatical cues of a stated requirement (English job-text grammar; no skill or discipline is named)
_FRAMING = re.compile(
    r"\b(skills?|skilled|experience[ds]?|knowledge|knowledgeable|proficien\w*|expert\w*|familiar\w*|competen\w*|"
    r"abilit(?:y|ies)|able to|understanding|background|fluen\w*|hands-on|working with|track record|"
    r"required|requirements?|qualifications?|must|should|preferred|desired|degree|certifi\w*|strong|excellent|"
    r"solid|proven|demonstrated)\b", re.I)


def _lit(v):
    return ast.literal_eval(v) if isinstance(v, str) and v[:1] in "[{(" else v


def clause_bounds(text, span):
    """The clause holding the span: the sentence cut at ; : ( ) bullets and line breaks (commas do not cut: lists)."""
    a, b = span
    start = max(text.rfind(c, 0, a) for c in ".!?\n;:()[]•") + 1
    ends = [i for i in (text.find(c, b) for c in ".!?\n;:()[]•") if i != -1]
    return start, (min(ends) if ends else len(text))


def framed(text, span):
    """Requirement framing in the mention's clause, outside the mention itself."""
    start, end = clause_bounds(text, span)
    rest = text[start:span[0]] + " " + text[span[1]:end]
    return bool(_FRAMING.search(rest))


_FUNCTION = r"(?:in|with|of|on|for|using|and|or|the|a|an|to)"
_BOUND_BEFORE = re.compile(r"\b(" + _FRAMING.pattern[3:-3] + r")\b\W*(?:" + _FUNCTION + r"\W+)*$", re.I)
_BOUND_AFTER = re.compile(r"^\W*(skills?|experience|knowledge|proficiency|expertise|background|fluency)\b", re.I)


def bound(text, span):
    """Requirement framing bound to the mention itself: a cue directly before it (only function words between, e.g.
    "proficiency in X", "experience with X") or a cue noun directly after it ("X skills"). Used for ordinary words,
    where framing elsewhere in the clause says nothing about the word ("experience building systems from scratch")."""
    start, end = clause_bounds(text, span)
    return bool(_BOUND_BEFORE.search(text[start:span[0]]) or _BOUND_AFTER.search(text[span[1]:end]))


def sentence_of(text, span):
    a, b = span
    start = max(text.rfind(c, 0, a) for c in ".!?\n") + 1
    ends = [i for i in (text.find(c, b) for c in ".!?\n") if i != -1]
    return text[start:(min(ends) + 1 if ends else len(text))].strip()


def _labels(concept):
    out = {(concept.get("pref_label") or "").lower()}
    out |= {x.lower() for x in (_lit(concept.get("alt_labels")) or [])}
    return {x for x in out if x}


def verbal_form(raw, concept):
    """A skill-competence concept named by its own verb phrase: the surface IS the preferred label or an alternative
    label that starts with the same verb as the preferred label ("make decisions", "make decision")."""
    if not concept or concept.get("skill_type") != "skill/competence":
        return False
    pref = (concept.get("pref_label") or "").lower().split()
    s = re.sub(r"\W+", " ", (raw or "").lower()).strip()
    if not pref or not s:
        return False
    return s.split()[0] == pref[0] and s in _labels(concept)


def qualify(mention, mapping, store_skills, text, segment_kind, profile, near, siblings_in_sentence=()):
    """One extracted mention -> its qualification record (the mention itself is copied, not changed)."""
    span = tuple(_lit(mention["span"]))
    raw, norm = mention.get("raw_mention"), mention.get("normalized_text")
    key = mention.get("skill_key") or ""
    candidates = _lit((mapping or {}).get("candidates")) or []
    reason_code = ((mapping or {}).get("reason") or "").split(":")[0]
    hidden = "hiddenlabel" in ((mapping or {}).get("mapping_method") or "").lower()
    is_framed = framed(text, span)
    base = {"mention_uid": mention.get("mention_uid"), "posting_uid": mention.get("source_uid"),
            "raw_phrase": raw, "normalized_phrase": norm, "span": list(span), "sentence": sentence_of(text, span),
            "text_kind": segment_kind, "boilerplate": segment_kind == "EMPLOYER_BOILERPLATE",
            "release_concept": key, "release_esco_status": mention.get("esco_status"),
            "release_sense": mention.get("sense_state"), "requirement_framing": is_framed, "method": METHOD}

    def done(decision, concept_uri, qtype, confidence, reason, resolved_by=None):
        return {**base, "concept": concept_uri,
                "concept_label": (store_skills.get(concept_uri) or {}).get("pref_label") if concept_uri else None,
                "type": qtype, "decision": decision, "confidence": confidence, "reason": reason,
                "resolved_by": resolved_by,
                "eligible_for_demand": decision in DEMAND_ELIGIBLE, "eligible_for_gap": decision in GAP_ELIGIBLE}

    # --- resolve the concept --------------------------------------------------------------------------------
    concept_uri, resolved_by, confidence = None, None, "HIGH"
    sibling = None
    if key.startswith("http"):
        concept_uri = key
        if mention.get("sense_state") in REVIEW_SENSES or hidden:
            # framing shows a phrase is used as a skill; only taxonomy context shows WHICH concept an alias or a
            # hidden search label names (an alias is not proof of the same concept)
            sibling = _sibling(concept_uri, siblings_in_sentence, store_skills)
            if sibling:
                resolved_by, confidence = f"sibling in sentence: {sibling}", "MEDIUM"
            else:
                return done("EXCLUDED_BOILERPLATE" if segment_kind == "EMPLOYER_BOILERPLATE" else "AMBIGUOUS",
                            concept_uri, "UNRESOLVED", "LOW",
                            "the surface matched only an alias or hidden search label, and no related skill in the "
                            "sentence confirms the concept (an alias is not proof of the same concept)")
    elif mention.get("esco_status") == "INSUFFICIENT_EVIDENCE" and reason_code == "LABEL_CONTEXT_DEPENDENT" \
            and len(candidates) == 1:
        cand = candidates[0].get("uri")
        sibling = _sibling(cand, siblings_in_sentence, store_skills)
        is_bound = bound(text, span)
        if is_bound or sibling:
            concept_uri, confidence = cand, "MEDIUM"
            resolved_by = "requirement framing bound to the word" if is_bound else f"sibling in sentence: {sibling}"
        else:
            return done("EXCLUDED_BOILERPLATE" if segment_kind == "EMPLOYER_BOILERPLATE" else "EXCLUDED_INSUFFICIENT_CONTEXT",
                        None, "UNRESOLVED", "LOW",
                        "an ordinary word that can name a skill; the sentence neither frames it as a requirement nor "
                        "names a related skill")
    elif key.startswith("surface:") and mention.get("method") == "technical_token":
        concept_uri = None  # a technology token kept by the release (no ESCO concept)
    elif (mention.get("esco_status") == "AMBIGUOUS" or len(candidates) > 1) and \
            len([c for c in candidates if _sibling(c.get("uri"), siblings_in_sentence, store_skills)]) == 1:
        # several candidates, exactly one of which is related to another skill in the same sentence
        concept_uri = next(c.get("uri") for c in candidates if _sibling(c.get("uri"), siblings_in_sentence, store_skills))
        resolved_by, confidence = f"the one candidate related to another skill in the sentence: " \
                                  f"{_sibling(concept_uri, siblings_in_sentence, store_skills)}", "MEDIUM"
    elif mention.get("esco_status") == "AMBIGUOUS" or len(candidates) > 1:
        return done("EXCLUDED_BOILERPLATE" if segment_kind == "EMPLOYER_BOILERPLATE" else "AMBIGUOUS", None,
                    "UNRESOLVED", "LOW", "several candidate concepts; the extraction does not decide between them")
    else:
        return done("EXCLUDED_BOILERPLATE" if segment_kind == "EMPLOYER_BOILERPLATE" else "EXCLUDED_INSUFFICIENT_CONTEXT",
                    None, "UNRESOLVED", "LOW", "no standardised concept for this phrase")

    # --- provenance -------------------------------------------------------------------------------------------
    if segment_kind == "EMPLOYER_BOILERPLATE":
        return done("EXCLUDED_BOILERPLATE", concept_uri, _type(concept_uri, store_skills, mention), confidence,
                    "the sentence is employer text found in every posting of the employer (or across employers); "
                    "kept with provenance, not job evidence")

    # --- type and decision --------------------------------------------------------------------------------------
    c = store_skills.get(concept_uri) or {}
    qtype = _type(concept_uri, store_skills, mention)
    key_for_profile = concept_uri or key
    if qtype == "TECHNOLOGY_TOOL":
        return done("QUALIFIED_TECHNICAL", concept_uri, qtype, confidence, "a named technology or tool", resolved_by)
    if qtype == "SKILL_COMPETENCE":
        if not is_framed and verbal_form(raw, c):
            return done("EXCLUDED_GENERIC_CAPABILITY", concept_uri, "GENERIC_CAPABILITY", confidence,
                        "a competence named by its bare verb phrase, with no requirement framing in its clause: the "
                        "sentence describes an activity, not a required competency", resolved_by)
        if not is_framed and c.get("reuse_level") in ("transversal", "cross-sector"):
            return done("EXCLUDED_GENERIC_CAPABILITY", concept_uri, "GENERIC_CAPABILITY", "MEDIUM",
                        "a general competence mentioned without requirement framing", resolved_by)
        if c.get("reuse_level") == "transversal":
            return done("TRANSVERSAL", concept_uri, "PROFESSIONAL_COMPETENCY",
                        confidence if is_framed else "MEDIUM",
                        "a recognised transversal competency stated as a requirement: reported, never a discipline gap",
                        resolved_by)
        if key_for_profile in profile:
            return done("QUALIFIED_TECHNICAL", concept_uri, qtype, confidence,
                        "a competence the programme's curricula name", resolved_by)
        return done("QUALIFIED_PROFESSIONAL", concept_uri, "PROFESSIONAL_COMPETENCY", confidence,
                    "a recognised professional competence stated as a requirement", resolved_by)
    # knowledge
    if c.get("reuse_level") == "transversal":
        return done("TRANSVERSAL", concept_uri, "PROFESSIONAL_COMPETENCY", confidence,
                    "transversal knowledge: reported, never a discipline gap", resolved_by)
    if key_for_profile in profile:
        return done("QUALIFIED_TECHNICAL", concept_uri, "KNOWLEDGE", confidence,
                    "knowledge the programme's curricula name", resolved_by)
    return done("QUALIFIED_DOMAIN", concept_uri, "KNOWLEDGE", confidence,
                "domain knowledge the programme's curricula do not name"
                + (" (it sits next to them in the taxonomy)" if key_for_profile in near else "")
                + ": counted in demand, not a gap for this programme unless its postings show discipline relevance",
                resolved_by)


def _type(concept_uri, store_skills, mention):
    if mention.get("method") == "technical_token" or (mention.get("skill_category") == "TECHNOLOGY_TOOL"):
        return "TECHNOLOGY_TOOL"
    t = (store_skills.get(concept_uri) or {}).get("skill_type")
    return {"knowledge": "KNOWLEDGE", "skill/competence": "SKILL_COMPETENCE"}.get(t, "KNOWLEDGE")


def parents(uri, store_skills):
    return set(_lit((store_skills.get(uri) or {}).get("broader")) or [])


def _sibling(uri, others, store_skills):
    """Another resolved mention in the same sentence sharing an immediate ESCO parent with uri (or being its
    parent or child)."""
    mine = parents(uri, store_skills)
    for o in sorted(x for x in others if x):   # sorted: the reported sibling is reproducible
        if o == uri:
            continue
        theirs = parents(o, store_skills)
        if mine & theirs or o in mine or uri in theirs:
            return (store_skills.get(o) or {}).get("pref_label") or o
    return None


def skill_decision(mention_decisions, skill_relevance_state):
    """Skill-level decision from its demand-eligible mentions: the most common qualified decision; a domain skill
    whose postings are mostly positively relevant becomes DISCIPLINE_ADJACENT."""
    counts = {}
    for d in mention_decisions:
        counts[d] = counts.get(d, 0) + 1
    qualified = {d: n for d, n in counts.items() if d in DEMAND_ELIGIBLE}
    if not qualified:
        return max(counts, key=lambda d: (counts[d], d)) if counts else "EXCLUDED_INSUFFICIENT_CONTEXT"
    top = max(qualified, key=lambda d: (qualified[d], d))
    if top == "QUALIFIED_DOMAIN" and skill_relevance_state == "DISCIPLINE_ADJACENT":
        return "DISCIPLINE_ADJACENT"
    return top
