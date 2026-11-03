"""Skill evidence v0.2 -- general, context-aware qualification of extracted skill mentions (EXPERIMENTAL).

This supersedes skill_qualification.py (v0.1, kept for comparison). It is not wired into the authoritative pipeline.

Stages (kept separate; each answers one question):
  EXTRACTION     what phrases appear to be skills?                 -> the release extractor (industry.extract)
  CONTEXT        where does the phrase sit?                        -> parse_posting / sentence_role / list_head
  QUALIFICATION  is this occurrence usable industry-skill evidence? -> decide()  (decision + evidence strength)
  NORMALIZATION  which canonical concept does it refer to?         -> resolve_concept()
  RELEVANCE      is that concept relevant to this programme?       -> programme_relevance()
  DEMAND         how often does qualified evidence occur among eligible postings?  (audit script)

Every decision is made from a feature record that a later semantic model can extend: features() returns the
deterministic evidence, an optional `semantic_scorer` may add a score under features["semantic"], and decide()
reads only the deterministic fields today (the hook is recorded, never silently used).

THE BOUNDED CONTEXT WINDOW (deterministic, documented):
  1. the mention's span and its clause;
  2. its sentence;
  3. its list (items separated by commas, "and", "or", "/" after a list head such as "Required:" or "Languages:");
  4. its section: the nearest heading above it in the posting (a short line without terminal punctuation, or a
     line ending in ":"), classified by the role of the heading;
  5. the posting's own job text (for an abbreviation's written-out form, and for the employer's name);
  6. posting metadata: job title and employer name;
  7. the employer-boilerplate state of the sentence (relevance.boilerplate).
  Nothing outside the posting is read for qualification.

SENTENCE ROLES (the "semantic role" of the text that holds the mention):
  REQUIRED, PREFERRED, SKILLS_LIST, EDUCATION, RESPONSIBILITY      -> the job holder needs or uses the skill
  COMPANY_DESCRIPTION, LEGAL_EEO, BENEFITS, SOCIAL_LINKS            -> text about the employer, not the job
  OTHER                                                             -> no role could be established
  The role comes, in order, from: explicit sentence cues of legal / social / benefits text; a "preferred" cue; the
  list head; a requirement cue; the section heading; a responsibility form (an imperative verb -- a verb that begins
  ESCO skill labels -- or "you will", "responsible for"); an organisation subject ("we", "our", the employer's name)
  without any reference to the candidate.
  The cue words are a genre lexicon of how job postings are written; they name no skill, discipline or employer.

EVIDENCE STRENGTH:
  STRONG  explicit requirement (required / must / proficiency / knowledge of / X skills), a skills list, an
          education requirement
  MEDIUM  experience or familiarity asked for; a task the job holder performs (responsibility)
  WEAK    optional or preferred ("a plus", "nice to have", "preferred"); job text with no role cue
  NONE    employer text (boilerplate, company description, legal, benefits, social links), the employer's name,
          or a phrase that is not used as a skill

DECISIONS (what the occurrence is; programme relevance is a separate field):
  EXCLUDED_BOILERPLATE          repeated employer text (relevance.boilerplate)
  EXCLUDED_NON_JOB_TEXT         company description, legal, benefits or social text, by role
  EXCLUDED_ENTITY_NAME          the span is part of the employer's name ("Spark Retail")
  AMBIGUOUS                     several concepts fit and the context does not decide; or an alias the context
                                does not confirm
  EXCLUDED_INSUFFICIENT_CONTEXT an ordinary word whose skill sense the context does not establish; no concept
  EXCLUDED_GENERIC_CAPABILITY   a competence phrase whose holder is not the job holder (the employer's own action,
                                "how we make decisions"), or a competence with no role at all
  TRANSVERSAL                   a transversal competency (ESCO reuse level) the job holder needs
  QUALIFIED_TECHNICAL           a technology, tool or digital skill (release technology token, or ESCO digital
                                skills collection)
  QUALIFIED_PROFESSIONAL        a non-transversal competence the job holder needs ("lead a team of engineers")
  QUALIFIED_DOMAIN              other knowledge the job holder needs (thermodynamics, financial statements)
  Each abstention carries `abstention_reason` and `resolvable_with` (what additional context would decide it).

QUALIFICATION vs NORMALIZATION: an occurrence in a job-role sentence is skill evidence even when its canonical
concept is not confirmed (an ordinary word, an alias, several candidate concepts). It is then counted under its own
wording (evidence_key "surface:<phrase>"), never under the unconfirmed concept, and it cannot make a gap. Guards
that stop a token from being read as a skill name at all: a closed-class (function) word, part of a hyphenated
compound, the first word of a capitalised multi-word name (syntactic_guard). An unconfirmed competence or quality
word ("efficiency", "decision making") must be framed as a skill (a requirement bound to it, or a skills-list item);
an unconfirmed non-technical word that modifies the next word ("banking relationships") is not a skill name.

PROGRAMME RELEVANCE (independent of the decision):
  IN_PROGRAMME_PROFILE   the programme's curricula name the concept
  NEAR_PROGRAMME_PROFILE the concept shares an immediate ESCO parent with a profile concept
  OUTSIDE_PROGRAMME_PROFILE
  A mention is gap-eligible only if it is qualified (not transversal) AND in the programme profile; at skill level
  a concept may also become DISCIPLINE_ADJACENT from posting evidence (relevance.skill_relevance).

Structural constants (document structure, not tuned on labels): HEADING_MAX_TOKENS, LIST_ITEM_MAX_TOKENS.
"""
from __future__ import annotations

import ast
import re
from functools import lru_cache

METHOD = "skill evidence v0.2 (experimental, deterministic, general context model)"
HEADING_MAX_TOKENS = 8          # a heading is a short line; longer lines are sentences
LIST_ITEM_MAX_TOKENS = 5        # an item of an enumeration after a list head is a short phrase

# Two further guards were implemented and evaluated on the validation set (independent labels) and are OFF: requiring
# an unconfirmed competence word to be framed as a skill, and rejecting an unconfirmed non-technical word that modifies
# the next word. Each raised precision slightly on the development set but cost more recall on validation
# (F1 0.822 with both off vs 0.696 with both on). Kept, switched off, so the ablation is reproducible.
RULE_COMPETENCE_FRAMING = False
RULE_MODIFIER = False
QUALIFIED = ("QUALIFIED_TECHNICAL", "QUALIFIED_PROFESSIONAL", "QUALIFIED_DOMAIN")
DEMAND_ELIGIBLE = QUALIFIED + ("TRANSVERSAL",)
ABSTAIN = ("AMBIGUOUS", "EXCLUDED_INSUFFICIENT_CONTEXT")
JOB_ROLES = ("REQUIRED", "PREFERRED", "SKILLS_LIST", "EDUCATION", "RESPONSIBILITY")
EMPLOYER_ROLES = ("COMPANY_DESCRIPTION", "LEGAL_EEO", "BENEFITS", "SOCIAL_LINKS")
ESTABLISHED = ("ESTABLISHED", "ESTABLISHED_BY_CONTEXT")
REVIEW_SENSES = ("ALIAS_SENSE_REVIEW_REQUIRED", "CASE_SENSE_REVIEW_REQUIRED", "ACRONYM_SENSE_REVIEW_REQUIRED")

# ------------------------------------------------------------------ genre lexicon (how postings are written)
_H = {
    "PREFERRED": r"prefer\w*|nice[- ]to[- ]have|good[- ]to[- ]have|bonus|desirable|plus|ideally|additional",
    "EDUCATION": r"education\w*|degree|academic",
    "RESPONSIBILITY": r"responsibilit\w*|duties|what you(?:'| wi)ll do|what you will be doing|your role|the role|"
                      r"about the (?:role|job|position)|day[- ]to[- ]day|job description|role overview|you will",
    "REQUIRED": r"requirements?|required|qualifications?|must[- ]haves?|who you are|what you(?:'| wi)ll (?:need|bring)|"
                r"what we(?:'re| are) looking for|you have|eligibility|essential|minimum|key skills|skills required|"
                r"skills (?:and|&) (?:experience|qualifications)",
    "BENEFITS": r"benefits?|perks|what we offer|why join|compensation|rewards",
    "LEGAL_EEO": r"equal (?:employment )?opportunit\w*|eeo|diversity|inclusion|accommodation|privacy|disclaimer|"
                 r"legal",
    "SOCIAL_LINKS": r"follow us|connect with us|social",
    "COMPANY_DESCRIPTION": r"about|who we are|our (?:mission|story|culture|values|company)|company overview|life at|"
                           r"overview",
}
# extra cues that make a LIST HEAD ("Tools: a, b") a skills list, but are too common inside requirement lines to
# mark a whole line as a heading
_LIST_CUES = r"skills?|tools|languages|technologies|tech stack|stack|platforms|frameworks|software|experience|" \
             r"knowledge|competenc\w*"
_HEADING_ORDER = ("PREFERRED", "EDUCATION", "RESPONSIBILITY", "REQUIRED", "BENEFITS", "LEGAL_EEO", "SOCIAL_LINKS",
                  "COMPANY_DESCRIPTION")
_LEGAL = re.compile(r"\b(discriminat\w*|equal (?:employment )?opportunit\w*|reasonable accommodation\w*|"
                    r"accommodations?|protected (?:veteran )?status|regardless of|without regard to|"
                    r"applicants? with disabilit\w*|affirmative action)\b", re.I)
_SOCIAL = re.compile(r"\b(follow (?:us|\w+(?: \w+)?) on|connect with us|find us on|like us on)\b|https?://|www\.", re.I)
_BENEFITS = re.compile(r"\b(insurance|paid (?:time off|leave)|parental leave|retirement|wellness|perks|"
                       r"reimbursement|stock options?|equity grant)\b", re.I)
_PREFERRED = re.compile(r"\b(is a plus|a plus|nice[- ]to[- ]have|good[- ]to[- ]have|preferred|preferably|bonus|"
                        r"desirable|ideally|advantage)\b", re.I)
_STRONG = re.compile(r"\b(required|requirements?|must|mandatory|essential|proficien\w*|expert\w*|knowledge|"
                     r"knowledgeable|skills?|skilled|strong|solid|excellent|proven|demonstrated|deep|degree|"
                     r"certifi\w*|qualif\w*|fluen\w*|hands[- ]on|abilit(?:y|ies)|able to|competen\w*|"
                     r"understanding|background|command of|working knowledge)\b", re.I)
_MEDIUM = re.compile(r"\b(experience[ds]?|familiar\w*|exposure|worked with|working with|track record|"
                     r"comfortable)\b", re.I)
_YOU = re.compile(r"\b(you|your|you'll|candidate|applicant|the ideal|this role|the role|the position|"
                  r"the successful)\b", re.I)
_YOU_WILL = re.compile(r"^\W*(you will|you'll|you would|responsible for|in this role|as (?:a|an|the) \w+[, ]+you)\b",
                       re.I)
_ORG_SUBJECT = re.compile(r"^\W*(we|we're|we've|our|us|at \w+)\b", re.I)
_FUNCTION = r"(?:in|with|of|on|for|using|and|or|the|a|an|to|at|via)"
_BOUND_BEFORE = re.compile(r"\b(" + _STRONG.pattern[3:-3] + "|" + _MEDIUM.pattern[3:-3] + r")\W*(?:" + _FUNCTION
                           + r"\W+)*$", re.I)
_BOUND_AFTER = re.compile(r"^\W*(?:development |programming |engineering )?(skills?|experience|knowledge|"
                          r"proficiency|expertise|background|fluency|required|certification)\b", re.I)
_WORD = re.compile(r"[a-z][a-z0-9+#.\-]*", re.I)


# English closed-class (function) words: pronouns, determiners, auxiliaries, prepositions, conjunctions. A standard
# grammatical class, not a list of skills: such a token is never read as a skill name.
_CLOSED_CLASS = frozenset("""
a an the this that these those it its it's they them their we us our you your he she his her i me my
is are was were be been being am do does did done have has had having will would shall should can could may might
must of in on at by for with from to into onto over under about as than then so if or and but nor not no yes
all any each every some such own same other another both either neither which who whom whose what where when why how
""".split())


def syntactic_guard(text, span, raw):
    """None if the span can stand alone as a skill name; else why not. Applies to occurrences whose concept is not
    confirmed: a closed-class word, part of a hyphenated compound ("open-source"), or the first word of a
    capitalised multi-word name ("Unity Catalog")."""
    a, b = span
    word = (raw or "").strip()
    if word.lower() in _CLOSED_CLASS:
        return "a function word"
    if (a > 0 and text[a - 1] == "-") or (b < len(text) and text[b] == "-"):
        return "part of a hyphenated compound"
    nxt = re.match(r" ([A-Z][a-z]+)\b", text[b:b + 30])
    if word[:1].isupper() and nxt and not word.isupper():
        return "part of a capitalised name"
    return None


def modifies_next_word(text, span):
    """The span is directly followed by a content word ("banking relationships", "lead flows"): it modifies that
    word rather than naming a skill on its own."""
    m = re.match(r" ([A-Za-z][a-z]+)\b", text[span[1]:span[1] + 30])
    return bool(m) and m.group(1).lower() not in _CLOSED_CLASS


def _lit(v):
    return ast.literal_eval(v) if isinstance(v, str) and v[:1] in "[{(" else v


def _tokens(s):
    return _WORD.findall(s or "")


def verb_lexicon(store_skills):
    """Verbs that begin ESCO skill/competence labels ("build", "lead", "handle", ...): a data-derived lexicon used
    to recognise imperative responsibility lines. Taken from the taxonomy, not written by hand."""
    out = set()
    for s in store_skills.values():
        lab = (s.get("pref_label") or "").split()
        if lab and s.get("skill_type") == "skill/competence":
            out.add(lab[0].lower())
    return frozenset(out)


# ------------------------------------------------------------------ context: posting structure

def heading_role(line):
    t = line.strip().strip(":").strip("*#-• ").lower()
    for role in _HEADING_ORDER:
        if re.search(r"\b(?:" + _H[role] + r")\b", t):
            return role
    return None


def _is_heading(line, next_line):
    s = line.strip()
    if not s:
        return False
    if ":" in s and s.split(":", 1)[1].strip():
        return False                                   # "Label: content" is a labelled list, not a heading
    if s.endswith(":") and len(_tokens(s)) <= HEADING_MAX_TOKENS:
        return True
    return (len(_tokens(s)) <= HEADING_MAX_TOKENS and s[-1] not in ".!?;," and bool(next_line.strip())
            and heading_role(s) is not None)


def parse_posting(text):
    """Line index -> (heading text, heading role) of the section the line belongs to."""
    lines = (text or "").split("\n")
    out, current = [], (None, None)
    pos = 0
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        start, end = pos, pos + len(line)
        if _is_heading(line, nxt):
            current = (line.strip(), heading_role(line))
            out.append((start, end, current[0], current[1], True))
        else:
            out.append((start, end, current[0], current[1], False))
        pos = end + 1
    return out


def section_at(structure, pos):
    for start, end, heading, role, is_heading in structure:
        if start <= pos <= end:
            return heading, role, is_heading
    return None, None, False


def line_of(text, span):
    a = span[0]
    start = text.rfind("\n", 0, a) + 1
    end = text.find("\n", span[1])
    return start, (len(text) if end == -1 else end)


def sentence_bounds(text, span):
    a, b = span
    start = max(text.rfind(c, 0, a) for c in ".!?\n") + 1
    ends = [i for i in (text.find(c, b) for c in ".!?\n") if i != -1]
    return start, (min(ends) + 1 if ends else len(text))


def list_head(text, span):
    """If the mention is an item of an enumeration introduced by a head ("Required: a, b and c",
    "Languages: Python, Java"), return the head text; else None."""
    ls, le = line_of(text, span)
    line = text[ls:le]
    rel = span[0] - ls
    colon = line.rfind(":", 0, rel)
    if colon == -1:
        return None
    head, tail = line[:colon], line[colon + 1:]
    items = [x for x in re.split(r",|/|;|\band\b|\bor\b|&", tail) if x.strip()]
    if items and all(len(_tokens(x)) <= LIST_ITEM_MAX_TOKENS for x in items) and len(_tokens(head)) <= HEADING_MAX_TOKENS:
        return head.strip()
    return None


def employer_name_spans(text, company):
    """Spans where the employer's name (its distinctive leading words) occurs."""
    return list(_employer_name_spans(text or "", company))


@lru_cache(maxsize=8192)  # asked once per mention; a posting has many mentions and one employer
def _employer_name_spans(text, company):
    return tuple(_employer_name_spans_uncached(text, company))


def _employer_name_spans_uncached(text, company):
    words = [w for w in _tokens(company) if w.lower() not in ("pvt", "ltd", "inc", "llc", "limited", "private",
                                                                "the", "co", "corp", "corporation", "company")]
    if not words:
        return []
    name = r"\b" + r"\s+".join(re.escape(w) for w in words[:2]) + r"\b"
    if len(words) >= 2:
        return [(m.start(), m.end()) for m in re.finditer(name, text or "", re.I)]
    # a one-word employer name: its occurrences as a name (capitalised as given, or possessive)
    return [(m.start(), m.end()) for m in re.finditer(r"\b" + re.escape(words[0]) + r"(?:'s|’s)?\b", text or "")]


def sentence_role(text, span, structure, verbs, company=None, title=None):
    """(role, cue) of the text holding the mention -- see the module docstring for the order."""
    s0, s1 = sentence_bounds(text, span)
    sent = text[s0:s1]
    heading, sec_role, is_heading = section_at(structure, span[0])
    if is_heading:
        return "OTHER", "the mention is in a heading"
    if _LEGAL.search(sent):
        return "LEGAL_EEO", "legal / equal-opportunity wording"
    if _SOCIAL.search(sent):
        return "SOCIAL_LINKS", "social-media wording"
    if _BENEFITS.search(sent) and sec_role not in ("REQUIRED", "RESPONSIBILITY", "PREFERRED"):
        return "BENEFITS", "benefits wording"
    if _PREFERRED.search(sent) or sec_role == "PREFERRED":
        return "PREFERRED", "preferred wording" if _PREFERRED.search(sent) else f"section: {heading}"
    head = list_head(text, span)
    if head is not None:
        hr = heading_role(head)
        if hr is None and re.search(r"\b(?:" + _LIST_CUES + r")\b", head, re.I):
            hr = "REQUIRED"
        if hr == "PREFERRED":
            return "PREFERRED", f"list head: {head}"
        if hr in ("REQUIRED", None) and not _ORG_SUBJECT.search(head):
            return "SKILLS_LIST" if hr is None or not re.search(r"requir|must", head, re.I) else "REQUIRED", \
                f"list head: {head}"
        if hr:
            return hr, f"list head: {head}"
    # the employer is a subject of the sentence: "we"/"our" at its start, or the employer's name anywhere in it
    org = bool(_ORG_SUBJECT.search(sent)) or bool(employer_name_spans(sent, company or ""))
    candidate = bool(_YOU.search(sent))
    if (_STRONG.search(sent) or _MEDIUM.search(sent)) and not (org and not candidate):
        if re.search(r"\b(degree|bachelor|master|diploma|graduat\w*|ph\.?d)\b", sent, re.I):
            return "EDUCATION", "education wording"
        return "REQUIRED", "requirement wording"
    if sec_role in ("REQUIRED", "EDUCATION", "RESPONSIBILITY"):
        return sec_role, f"section: {heading}"
    first = (_tokens(sent)[:1] or [""])[0].lower()
    if _YOU_WILL.search(sent) or (first in verbs and not org):
        return "RESPONSIBILITY", "responsibility form (you will / imperative verb)"
    if sec_role in EMPLOYER_ROLES:
        return sec_role, f"section: {heading}"
    if org and not candidate:
        return "COMPANY_DESCRIPTION", "the employer is the subject"
    return "OTHER", "no role cue"


def evidence_strength(role, text, span, heading=None):
    s0, s1 = sentence_bounds(text, span)
    sent = text[s0:s1]
    if role == "REQUIRED" and heading and re.search(r"requir|must|essential|mandatory|minimum", heading, re.I):
        return "STRONG"
    if role in EMPLOYER_ROLES:
        return "NONE"
    if role == "PREFERRED":
        return "WEAK"
    if role in ("SKILLS_LIST", "EDUCATION"):
        return "STRONG"
    if role == "REQUIRED":
        return "STRONG" if _STRONG.search(sent) or not _MEDIUM.search(sent) else "MEDIUM"
    if role == "RESPONSIBILITY":
        return "MEDIUM"
    return "WEAK"


def bound_framing(text, span):
    """Requirement framing bound to the mention itself ("proficiency in X", "X skills", "X development
    experience")."""
    s0, s1 = sentence_bounds(text, span)
    return bool(_BOUND_BEFORE.search(text[s0:span[0]]) or _BOUND_AFTER.search(text[span[1]:s1]))


# ------------------------------------------------------------------ extraction: every occurrence

def expand_occurrences(mentions, texts):
    """The release extractor keeps only the FIRST occurrence of a surface in a posting. Evidence is judged per
    occurrence (the first one may be employer text while a later one is a requirement), so every further
    whole-word occurrence of the same raw phrase is added as a derived mention (same surface, same mapping, own span;
    mention_uid suffixed "#n"). The original mentions are unchanged."""
    taken = {}
    for m in mentions:
        taken.setdefault(m["source_uid"], []).append(tuple(_lit(m["span"])))
    out = list(mentions)
    for m in mentions:
        text = texts.get(m["source_uid"]) or ""
        raw = m.get("raw_mention") or ""
        if not raw.strip():
            continue
        n = 0
        for occ in re.finditer(r"(?<![\w])" + re.escape(raw) + r"(?![\w])", text, re.I):
            a, b = occ.span()
            if any(not (b <= x or a >= y) for x, y in taken[m["source_uid"]]):
                continue
            n += 1
            taken[m["source_uid"]].append((a, b))
            out.append({**m, "span": [a, b], "raw_mention": text[a:b], "mention_uid": f"{m.get('mention_uid')}#{n}",
                        "derived_occurrence_of": m.get("mention_uid")})
    return out


# ------------------------------------------------------------------ normalization helpers

def parents(uri, store_skills):
    return set(_lit((store_skills.get(uri) or {}).get("broader")) or [])


def related(uri, others, store_skills):
    mine = parents(uri, store_skills)
    for o in sorted(x for x in others if x):
        if o == uri:
            continue
        theirs = parents(o, store_skills)
        if mine & theirs or o in mine or uri in theirs:
            return (store_skills.get(o) or {}).get("pref_label") or o
    return None


def _stems(s):
    """Content words of a label, lower-cased, hyphens split, plural -s removed ("decision-making" -> {decision,
    making}); a shared WHOLE word, not a shared prefix, links an alias to its concept's name."""
    out = set()
    for w in re.split(r"[\s\-/]+", (s or "").lower()):
        w = re.sub(r"[^a-z0-9+#]", "", w)
        if len(w) > 3 and w not in _CLOSED_CLASS:
            out.add(w[:-1] if w.endswith("s") and not w.endswith("ss") else w)
    return out


def expansion_in_posting(uri, store_skills, posting_text):
    """The concept's preferred label (an abbreviation's written-out form) appears in the posting's job text."""
    lab = (store_skills.get(uri) or {}).get("pref_label") or ""
    return bool(lab) and len(lab) > 4 and lab.lower() in (posting_text or "").lower()


def candidate_concepts(mention, mapping):
    """The concept(s) the extraction proposed for the surface, confirmed or not."""
    key = mention.get("skill_key") or ""
    if key.startswith("http"):
        return [key]
    return [c.get("uri") for c in (_lit((mapping or {}).get("candidates")) or []) if c.get("uri")]


def resolve_concept(mention, mapping, store_skills, text, span, related_in_sentence, job_text):
    """NORMALIZATION: -> (confirmed concept_uri | None, how, abstention_reason, resolvable_with)."""
    key = mention.get("skill_key") or ""
    candidates = _lit((mapping or {}).get("candidates")) or []
    reason_code = ((mapping or {}).get("reason") or "").split(":")[0]
    hidden = "hiddenlabel" in ((mapping or {}).get("mapping_method") or "").lower()
    if key.startswith("surface:") and mention.get("method") == "technical_token":
        return None, "technology token", None, None
    if key.startswith("http"):
        if mention.get("sense_state") in REVIEW_SENSES or hidden:
            rel = related(key, related_in_sentence, store_skills)
            if rel:
                return key, f"alias confirmed by a related skill in the sentence: {rel}", None, None
            if expansion_in_posting(key, store_skills, job_text):
                return key, "the abbreviation's written-out form appears in the posting", None, None
            pref = (store_skills.get(key) or {}).get("pref_label") or ""
            if bound_framing(text, span) and _stems(mention.get("raw_mention")) & _stems(pref):
                return key, "alias stated as a requirement and sharing a word stem with the concept's name", None, None
            return None, None, "alias or hidden search label not confirmed by context", \
                "a related skill in the sentence, the written-out form in the posting, or a requirement naming it"
        return key, "label match with an established sense", None, None
    surface = (mention.get("normalized_text") or mention.get("raw_mention") or "").lower()
    pref_same = [c.get("uri") for c in candidates
                 if ((store_skills.get(c.get("uri")) or {}).get("pref_label") or c.get("label") or "").lower() == surface]
    if mention.get("esco_status") == "INSUFFICIENT_EVIDENCE" and reason_code == "LABEL_CONTEXT_DEPENDENT" \
            and (len(candidates) == 1 or len(pref_same) == 1):
        # one candidate, or one candidate whose preferred name is the phrase itself: the concept is clear, the
        # SENSE of the ordinary word still needs context
        cand = candidates[0].get("uri") if len(candidates) == 1 else pref_same[0]
        guard = syntactic_guard(text, span, mention.get("raw_mention"))
        if guard:
            return None, None, f"ordinary word that is {guard}", "the word used on its own as a skill name"
        rel = related(cand, related_in_sentence, store_skills)
        if rel:
            return cand, f"ordinary word confirmed by a related skill in the sentence: {rel}", None, None
        if bound_framing(text, span):
            return cand, "ordinary word stated as a requirement", None, None
        if list_head(text, span) is not None:
            return cand, "ordinary word as an item of a skills list", None, None
        return None, None, "ordinary word whose skill sense the context does not establish", \
            "a related skill in the sentence, a requirement naming the word, or a skills list"
    if len(candidates) > 1:
        surface = (mention.get("normalized_text") or mention.get("raw_mention") or "").lower()
        same = [c.get("uri") for c in candidates
                if ((store_skills.get(c.get("uri")) or {}).get("pref_label") or "").lower() == surface]
        if len(same) == 1:
            return same[0], "the one candidate whose preferred name is the phrase itself", None, None
    if candidates and (mention.get("esco_status") == "AMBIGUOUS" or len(candidates) > 1):
        fits = [c.get("uri") for c in candidates if related(c.get("uri"), related_in_sentence, store_skills)
                or expansion_in_posting(c.get("uri"), store_skills, job_text)]
        if len(fits) == 1:
            return fits[0], "the one candidate that fits the context", None, None
        return None, None, f"{len(candidates)} candidate concepts; the context fits {len(fits)}", \
            "context that relates to exactly one of the candidate concepts"
    return None, None, "no standardised concept for this phrase", "a taxonomy concept for the phrase"


def intrinsic_type(concept_uri, store_skills, mention):
    """What the skill is, independently of any programme."""
    if mention.get("method") == "technical_token" or mention.get("skill_category") == "TECHNOLOGY_TOOL":
        return "TECHNICAL"
    c = store_skills.get(concept_uri) or {}
    cols = " ".join(_lit(c.get("collections")) or [])
    if c.get("reuse_level") == "transversal":
        return "TRANSVERSAL"
    if "digital" in cols.lower() and c.get("skill_type") == "knowledge":
        return "TECHNICAL"
    if c.get("skill_type") == "skill/competence":
        return "COMPETENCE"
    return "DOMAIN"


def programme_relevance(key, profile, near):
    if key in profile:
        return "IN_PROGRAMME_PROFILE"
    if key in near:
        return "NEAR_PROGRAMME_PROFILE"
    return "OUTSIDE_PROGRAMME_PROFILE"


# ------------------------------------------------------------------ features -> decision

def features(mention, mapping, store_skills, text, segment_kind, structure, verbs, profile, near,
             related_in_sentence=(), job_text="", company=None, title=None, semantic_scorer=None):
    span = tuple(_lit(mention["span"]))
    role, cue = sentence_role(text, span, structure, verbs, company, title)
    heading, sec_role, _ = section_at(structure, span[0])
    s0, s1 = sentence_bounds(text, span)
    concept, how, why_not, resolvable = resolve_concept(mention, mapping, store_skills, text, span,
                                                        related_in_sentence, job_text)
    in_name = any(a <= span[0] and span[1] <= b for a, b in employer_name_spans(text, company or ""))
    cands = candidate_concepts(mention, mapping)
    if concept or how == "technology token":
        norm_state = "CONFIRMED"
    elif len(cands) == 1:
        norm_state = "UNCONFIRMED_CANDIDATE"
    elif cands:
        norm_state = "UNCONFIRMED_MULTIPLE"
    else:
        norm_state = "NONE"
    surface_type = intrinsic_type(cands[0], store_skills, mention) if (not concept and len(cands) == 1) else None
    f = {
        "mention_uid": mention.get("mention_uid"), "posting_uid": mention.get("source_uid"),
        "raw_phrase": mention.get("raw_mention"), "normalized_phrase": mention.get("normalized_text"),
        "span": list(span), "sentence": text[s0:s1].strip(), "section_heading": heading, "section_role": sec_role,
        "list_head": list_head(text, span), "sentence_role": role, "role_cue": cue,
        "text_kind": segment_kind, "boilerplate": segment_kind == "EMPLOYER_BOILERPLATE",
        "in_employer_name": in_name, "bound_framing": bound_framing(text, span),
        "release_concept": mention.get("skill_key"), "release_esco_status": mention.get("esco_status"),
        "release_sense": mention.get("sense_state"),
        "concept": concept, "concept_label": (store_skills.get(concept) or {}).get("pref_label") if concept else None,
        "resolved_by": how, "abstention_reason": why_not, "resolvable_with": resolvable,
        "intrinsic_type": intrinsic_type(concept, store_skills, mention) if (concept or how) else surface_type,
        "normalization_state": norm_state, "candidate_concepts": cands,
        "syntactic_guard": syntactic_guard(text, span, mention.get("raw_mention")) if norm_state != "CONFIRMED" else None,
        "modifies_next_word": modifies_next_word(text, span),
        "evidence_key": concept or (mention.get("skill_key") if norm_state == "CONFIRMED"
                                    else "surface:" + (mention.get("normalized_text") or "")),
        "evidence_strength": evidence_strength(role, text, span, heading),
        "programme_relevance": programme_relevance(concept or mention.get("skill_key"), profile, near),
        "method": METHOD,
    }
    # extension point for a future pretrained semantic classifier/reranker: recorded, not used by decide()
    f["semantic"] = semantic_scorer(f) if semantic_scorer else None
    return f


def decide(f):
    """Deterministic decision from the feature record."""
    def out(decision, reason, strength=None):
        d = dict(f)
        d.update(decision=decision, reason=reason,
                 evidence_strength=strength if strength is not None else f["evidence_strength"])
        d["eligible_for_demand"] = decision in DEMAND_ELIGIBLE and d["evidence_strength"] != "NONE"
        d["eligible_for_gap"] = decision in QUALIFIED and f["programme_relevance"] == "IN_PROGRAMME_PROFILE" \
            and d["eligible_for_demand"]
        d["abstained"] = decision in ABSTAIN
        return d

    if f["in_employer_name"]:
        return out("EXCLUDED_ENTITY_NAME", "the phrase is part of the employer's name", "NONE")
    if f["boilerplate"]:
        return out("EXCLUDED_BOILERPLATE", "repeated employer text: kept with provenance, not job evidence", "NONE")
    if f["sentence_role"] in EMPLOYER_ROLES:
        return out("EXCLUDED_NON_JOB_TEXT", f"the sentence is employer text ({f['sentence_role']}; {f['role_cue']})",
                   "NONE")
    if f["concept"] is None and f["resolved_by"] != "technology token":
        # QUALIFICATION is separate from NORMALIZATION: an occurrence in a job-role sentence (requirement,
        # responsibility, preference, skills list, education) is skill evidence even when the canonical concept is
        # not confirmed. It is counted under its own surface, never under the unconfirmed concept, and it can never
        # make a gap (a gap needs a confirmed concept).
        unresolved_why = f["abstention_reason"]
        t = f["intrinsic_type"] or "DOMAIN"
        framed_as_skill = f["bound_framing"] or f["list_head"] is not None
        if RULE_COMPETENCE_FRAMING and t in ("TRANSVERSAL", "COMPETENCE") and not framed_as_skill:
            return out("EXCLUDED_GENERIC_CAPABILITY",
                       "an unconfirmed competence or quality word not framed as a skill (a requirement bound to it, or "
                       "an item of a skills list): it describes the work, not a required competence", "NONE")
        if RULE_MODIFIER and t != "TECHNICAL" and f["modifies_next_word"] and not framed_as_skill:
            return out("EXCLUDED_INSUFFICIENT_CONTEXT",
                       f"{unresolved_why}; the word modifies the next word rather than naming a skill", "NONE")
        if f["sentence_role"] in JOB_ROLES and f["normalization_state"] in ("UNCONFIRMED_CANDIDATE", "UNCONFIRMED_MULTIPLE") \
                and not f["syntactic_guard"]:
            decision = {"TRANSVERSAL": "TRANSVERSAL", "TECHNICAL": "QUALIFIED_TECHNICAL",
                        "COMPETENCE": "QUALIFIED_PROFESSIONAL"}.get(t, "QUALIFIED_DOMAIN")
            d = out(decision, f"skill evidence in a {f['sentence_role'].lower()} sentence; canonical concept not "
                              f"confirmed ({unresolved_why}), so it is counted under its own wording and cannot make a gap")
            d["eligible_for_gap"] = False
            return d
        why = unresolved_why if not f["syntactic_guard"] else f"{unresolved_why}; {f['syntactic_guard']}"
        return out("AMBIGUOUS" if f["normalization_state"] == "UNCONFIRMED_MULTIPLE" or "alias" in (unresolved_why or "")
                   else "EXCLUDED_INSUFFICIENT_CONTEXT", why, "NONE")
    t = f["intrinsic_type"]
    if t in ("COMPETENCE", "TRANSVERSAL") and f["sentence_role"] == "OTHER" and not f["bound_framing"]:
        return out("EXCLUDED_GENERIC_CAPABILITY",
                   "a competence phrase with no role tying it to the job holder (an action described, not required)",
                   "NONE")
    if t == "TRANSVERSAL":
        return out("TRANSVERSAL", "a transversal competency the job holder needs: reported, never a discipline gap")
    if t == "TECHNICAL":
        return out("QUALIFIED_TECHNICAL", "a technology, tool or digital skill the job holder needs or uses")
    if t == "COMPETENCE":
        return out("QUALIFIED_PROFESSIONAL", "a professional competence the job holder needs or exercises")
    return out("QUALIFIED_DOMAIN", "knowledge the job holder needs")


def qualify(mention, mapping, store_skills, text, segment_kind, structure, verbs, profile, near,
            related_in_sentence=(), job_text="", company=None, title=None, semantic_scorer=None):
    return decide(features(mention, mapping, store_skills, text, segment_kind, structure, verbs, profile, near,
                           related_in_sentence, job_text, company, title, semantic_scorer))


def curriculum_profile(curriculum_mentions, topic_doc, programme_docs, coverage_rows=(), mappings=None):
    """The programme profile with curriculum-side qualification: in a syllabus topic the genre itself establishes the
    teaching sense, so an ordinary word with exactly one candidate concept (e.g. a one-word subject name) resolves to
    it; aliases still need their established sense."""
    prof = set()
    for m in curriculum_mentions:
        if topic_doc.get(m.get("source_uid")) not in programme_docs:
            continue
        key = str(m.get("skill_key") or "")
        if key.startswith("http") and m.get("sense_state") in ESTABLISHED:
            prof.add(key)
        elif mappings is not None:
            mp = mappings.get(m.get("normalized_text")) or {}
            cands = _lit(mp.get("candidates")) or []
            if m.get("esco_status") == "INSUFFICIENT_EVIDENCE" and len(cands) == 1 \
                    and (mp.get("reason") or "").startswith("LABEL_CONTEXT_DEPENDENT"):
                prof.add(cands[0]["uri"])
            elif len(cands) > 1:
                same = [c["uri"] for c in cands
                        if (c.get("label") or "").lower() == (m.get("normalized_text") or "").lower()]
                if len(same) == 1:
                    prof.add(same[0])
    prof |= {c["skill_key"] for c in coverage_rows
             if c.get("coverage_level") not in (None, "ABSENT") and c.get("role") != "PEER"}
    return prof


def skill_level_relevance(mention_relevance, posting_relevance_state):
    """Skill level: in profile if any occurrence is; else DISCIPLINE_ADJACENT when most of its eligible postings
    have positive job relevance (relevance.skill_relevance semantics); else the most common occurrence state."""
    states = list(mention_relevance)
    if "IN_PROGRAMME_PROFILE" in states:
        return "IN_PROGRAMME_PROFILE"
    if posting_relevance_state == "DISCIPLINE_ADJACENT":
        return "DISCIPLINE_ADJACENT"
    return "NEAR_PROGRAMME_PROFILE" if "NEAR_PROGRAMME_PROFILE" in states else "OUTSIDE_PROGRAMME_PROFILE"


def skill_gap_eligible(skill_decision, skill_programme_relevance, occurrences):
    """Skill level: a gap needs a qualified (non-transversal) skill, programme relevance (in the profile, or
    discipline-adjacent by posting evidence) AND at least one occurrence whose canonical concept is confirmed.
    Evidence counted only under its own wording can never make a gap, however often it occurs."""
    return (skill_decision in QUALIFIED
            and skill_programme_relevance in ("IN_PROGRAMME_PROFILE", "DISCIPLINE_ADJACENT")
            and any(o.get("normalization_state") == "CONFIRMED" and o.get("eligible_for_demand") for o in occurrences))
