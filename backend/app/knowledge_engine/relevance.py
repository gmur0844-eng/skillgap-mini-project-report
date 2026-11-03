"""Discipline-to-industry relevance (EXPERIMENTAL; not wired into the authoritative pipeline).

Problem. Every supplied posting counts towards industry demand today. A finance posting's "financial statements", a
sales posting's "help customers" and an employer's equal-opportunity sentence ("... reproductive health decisions")
therefore enter the demand of a computing programme. The release already refuses to call such skills curriculum gaps
(DISCIPLINE_RELEVANCE_UNESTABLISHED), but they still inflate demand and support states.

This module decides, for every posting/programme pair and every skill/programme pair, whether the evidence ties it to
the programme -- without a list of forbidden words, without naming a discipline, and keeping every posting:
filtering is eligibility, never deletion.

  1. Text segments. Each description is split into sentences (see boilerplate()): employer-wide or cross-employer
     text is EMPLOYER_BOILERPLATE; text shared by some of one employer's related roles is SHARED_ROLE_TEXT; a
     re-post is UNKNOWN; the rest is JOB_SPECIFIC. A skill mention inside boilerplate is kept, with provenance, but
     does not count as job evidence.
  2. Programme profile. The standardised skills the programme's own curricula mention with an established sense
     (TARGET, PREVIOUS_VERSION, REFERENCE; peers excluded), plus skills the coverage-depth stage found taught.
  3. Job signals, each SUPPORTS / CONTRADICTS / MIXED / NO_EVIDENCE:
       skills      job-specific, non-transversal skills of the posting: more inside the profile than outside it
                   and its neighbourhood supports; none inside the profile nor in its ESCO neighbourhood (skills sharing an immediate
                   parent with a profile skill) contradicts -- a skill the curriculum does not teach yet may still
                   belong to the discipline, and that is exactly a gap.
       occupation  the resolved ESCO occupation's essential+optional skills that are specific (sector- or
                   occupation-specific reuse level) and in the profile: at least OCCUPATION_MIN_SHARED supports,
                   none contradicts. An unresolved occupation is NO_EVIDENCE -- never a contradiction.
       title       the job title names a profile skill or shares a two-word phrase with a curriculum course title:
                   supports; otherwise NO_EVIDENCE (a title's silence is not evidence against).
  4. Job relevance: RELEVANT (>= 2 support, none contradicts), LIKELY_RELEVANT (1 supports, none contradicts),
     NOT_RELEVANT (>= 1 contradicts, none supports), UNCERTAIN (conflicting signals or no evidence).
     Only NOT_RELEVANT postings leave the demand population (ELIGIBLE); the stricter POSITIVE-only policy is
     reported as a sensitivity.
  5. Skill relevance (separate from job relevance): IN_PROGRAMME_PROFILE, TRANSVERSAL (ESCO transversal skill:
     general, never a discipline gap), DISCIPLINE_ADJACENT (most of its job-specific postings are eligible), or
     NOT_ESTABLISHED. DISCIPLINE_ADJACENT needs most of the skill's job-specific postings to be RELEVANT or
     LIKELY_RELEVANT (positive evidence, not mere eligibility).

The only number is OCCUPATION_MIN_SHARED; it is provisional and uncalibrated, and the audit reports results across a
range of values. Nothing here is promoted until it is evaluated against human labels.
"""
from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict

METHOD = "discipline relevance v0 (experimental, deterministic, uncalibrated)"
OCCUPATION_MIN_SHARED = 2          # provisional; sensitivity reported for 1..3
ESTABLISHED = ("ESTABLISHED", "ESTABLISHED_BY_CONTEXT")
RESOLVED = ("EXACT", "VARIANT", "CANDIDATE")
SPECIFIC_REUSE = ("sector-specific", "occupation-specific")

JOB_STATES = ("RELEVANT", "LIKELY_RELEVANT", "UNCERTAIN", "NOT_RELEVANT")
POSITIVE = ("RELEVANT", "LIKELY_RELEVANT")
# eligibility policy: a posting leaves the demand population only when evidence contradicts relevance and nothing
# supports it; UNCERTAIN postings stay (absence of evidence is not evidence of irrelevance). The stricter policy
# (POSITIVE only) is reported alongside as a sensitivity.
ELIGIBLE = ("RELEVANT", "LIKELY_RELEVANT", "UNCERTAIN")

_WORD = re.compile(r"[a-z][a-z0-9+#]*")


def _norm(text):
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


def _span(value):
    return tuple(ast.literal_eval(value)) if isinstance(value, str) else tuple(value)


# ------------------------------------------------------------------------------------------------- 1 boilerplate

def segments(text):
    """(start, end, sentence) for every sentence of every line, with character offsets into text."""
    out = []
    for line in re.finditer(r"[^\n]+", text or ""):
        for s in re.finditer(r"[^.!?]+[.!?]?", line.group(0)):
            if s.group(0).strip():
                out.append((line.start() + s.start(), line.start() + s.end(), s.group(0).strip()))
    return out


def boilerplate(postings, text_key="clean_description"):
    """{posting_uid: [(start, end, state, repeated_in)]}. Sentences of fewer than three words are not judged.

    EMPLOYER_BOILERPLATE  the sentence is in every posting of its employer (two or more postings, different titles),
                          e.g. an equal-opportunity statement, or recurs verbatim across employers (a template)
    SHARED_ROLE_TEXT      it recurs in some, not all, of one employer's postings with different titles: a requirement
                          block shared by related roles -- job evidence, kept
    UNKNOWN               it recurs only under the same title (a re-post)
    JOB_SPECIFIC          it occurs once
    No number is involved: "every posting of the employer" and "more than one employer" are the definitions."""
    seen = defaultdict(set)
    segs = {}
    per_employer = Counter(p.get("company_key") for p in postings)
    for p in postings:
        segs[p["posting_uid"]] = segments(p.get(text_key))
        for _, _, s in segs[p["posting_uid"]]:
            n = _norm(s)
            if len(n.split()) >= 3:
                seen[n].add(p["posting_uid"])
    by = {p["posting_uid"]: p for p in postings}
    out = {}
    for uid, ss in segs.items():
        rows = []
        for a, b, s in ss:
            n = _norm(s)
            where = seen.get(n, set())
            employers = Counter(by[x].get("company_key") for x in where)
            titles = {(by[x].get("job_title") or "").strip().lower() for x in where}
            if len(n.split()) < 3 or len(where) < 2:
                state = "JOB_SPECIFIC"
            elif len(employers) > 1:
                state = "EMPLOYER_BOILERPLATE"
            elif len(titles) == 1:
                state = "UNKNOWN"
            elif all(per_employer[e] == k for e, k in employers.items()):
                state = "EMPLOYER_BOILERPLATE"
            else:
                state = "SHARED_ROLE_TEXT"
            rows.append((a, b, state, len(where)))
        out[uid] = rows
    return out


def segment_state(segs, span):
    a, b = span
    for x, y, state, _ in segs:
        if x <= a and b <= y:
            return state
    return "JOB_SPECIFIC"  # a mention that spans sentences is treated as job text


# ------------------------------------------------------------------------------------------------- 2 profile

def programme_profile(curriculum_mentions, topic_doc, programme_docs, coverage_rows=()):
    prof = {m["skill_key"] for m in curriculum_mentions
            if m.get("sense_state") in ESTABLISHED and str(m.get("skill_key", "")).startswith("http")
            and topic_doc.get(m.get("source_uid")) in programme_docs}
    prof |= {c["skill_key"] for c in coverage_rows
             if c.get("coverage_level") not in (None, "ABSENT") and c.get("role") != "PEER"}
    return prof


# ------------------------------------------------------------------------------------------------- 3 signals

def neighbourhood(profile, broader):
    """Skills that share an immediate ESCO parent (skill or skill group) with a profile skill: the discipline's
    neighbourhood in the taxonomy, beyond what the curriculum itself names."""
    parents = set().union(*(set(broader.get(k) or ()) for k in profile)) if profile else set()
    return {k for k, b in broader.items() if k not in profile and set(b or ()) & parents}


def skill_signal(skill_keys, profile, reuse, near=frozenset()):
    """skill_keys: the posting's job-specific, established skills. Transversal skills carry no discipline evidence.
    Support needs more curriculum skills than skills outside both the curriculum and its neighbourhood (neighbourhood
    skills are neutral); contradiction needs no skill in the curriculum nor in its taxonomy neighbourhood (a skill the curriculum does not teach yet may still belong to the discipline: that is a gap)."""
    keys = {k for k in skill_keys if reuse.get(k) != "transversal"}
    inside = sorted(k for k in keys if k in profile)
    nearby = sorted(k for k in keys if k in near)
    outside = sorted(k for k in keys if k not in profile and k not in near)
    if not keys:
        state = "NO_EVIDENCE"
    elif len(inside) > len(outside):
        state = "SUPPORTS"
    elif not inside and not nearby:
        state = "CONTRADICTS"
    else:
        state = "MIXED"
    return {"state": state, "inside_profile": inside, "near_profile": nearby, "outside_profile": outside}


def occupation_signal(resolution, occupation_skills, profile, reuse, min_shared=OCCUPATION_MIN_SHARED):
    if not resolution or resolution.get("state") not in RESOLVED or not resolution.get("occupation_uri"):
        return {"state": "NO_EVIDENCE", "occupation": None, "shared_specific_skills": [],
                "note": "occupation unresolved: not evidence against relevance"}
    skills = occupation_skills.get(resolution["occupation_uri"], set())
    shared = sorted(s for s in skills if s in profile and reuse.get(s) in SPECIFIC_REUSE)
    state = "SUPPORTS" if len(shared) >= min_shared else "CONTRADICTS" if not shared else "MIXED"
    return {"state": state, "occupation": resolution.get("occupation_label"), "shared_specific_skills": shared}


def _bigrams(text):
    w = [t[:6] for t in _WORD.findall((text or "").lower()) if len(t) > 2]
    return {(a, b) for a, b in zip(w, w[1:])}


def title_signal(title, profile_labels, course_bigrams):
    t = " " + _norm(title) + " "
    named = sorted(lab for lab in profile_labels if lab and f" {lab} " in t)
    phrases = sorted(" ".join(b) for b in _bigrams(title) & course_bigrams)
    state = "SUPPORTS" if named or phrases else "NO_EVIDENCE"
    return {"state": state, "names_profile_skill": named, "shares_course_phrase": phrases}


def classify(signals):
    states = [s["state"] for s in signals]
    sup, con = states.count("SUPPORTS"), states.count("CONTRADICTS")
    if con == 0 and sup >= 2:
        return "RELEVANT"
    if con == 0 and sup == 1:
        return "LIKELY_RELEVANT"
    if con >= 1 and sup == 0:
        return "NOT_RELEVANT"
    return "UNCERTAIN"


def job_relevance(posting, job_skills, resolution, profile, profile_labels, course_bigrams, occupation_skills, reuse,
                  min_shared=OCCUPATION_MIN_SHARED, near=frozenset()):
    sig = {
        "skills": skill_signal(job_skills, profile, reuse, near),
        "occupation": occupation_signal(resolution, occupation_skills, profile, reuse, min_shared),
        "title": title_signal(posting.get("job_title"), profile_labels, course_bigrams),
    }
    state = classify(sig.values())
    supporting = [k for k, v in sig.items() if v["state"] == "SUPPORTS"]
    contradicting = [k for k, v in sig.items() if v["state"] == "CONTRADICTS"]
    return {"posting_uid": posting["posting_uid"], "job_title": posting.get("job_title"),
            "company": posting.get("company_name"), "relevance": state,
            "evidence_strength": f"{len(supporting)} supporting, {len(contradicting)} contradicting of {len(sig)} signals",
            "supporting_evidence": supporting, "contradicting_evidence": contradicting, "signals": sig,
            "contributes_to_demand": state in ELIGIBLE, "method": METHOD}


# ------------------------------------------------------------------------------------------------- 5 skill relevance

def skill_relevance(skill_key, profile, reuse, job_postings_with_skill, relevance_by_posting):
    if skill_key in profile:
        return "IN_PROGRAMME_PROFILE"
    if reuse.get(skill_key) == "transversal":
        return "TRANSVERSAL"
    eligible = sum(1 for u in job_postings_with_skill if relevance_by_posting.get(u) in POSITIVE)
    if job_postings_with_skill and eligible * 2 > len(job_postings_with_skill):
        return "DISCIPLINE_ADJACENT"
    return "NOT_ESTABLISHED"


def mention_rows(skill_mentions, demanded, boiler):
    """Per posting: {skill_key: {"job": bool, "states": Counter}} for established mentions of demanded skills."""
    out = defaultdict(dict)
    for m in skill_mentions:
        if m.get("source_type") != "job_posting" or m.get("sense_state") not in ESTABLISHED:
            continue
        if m["skill_key"] not in demanded or m["source_uid"] not in boiler:
            continue
        state = segment_state(boiler[m["source_uid"]], _span(m["span"]))
        row = out[m["source_uid"]].setdefault(m["skill_key"], {"job": False, "states": Counter()})
        row["states"][state] += 1
        row["job"] = row["job"] or state != "EMPLOYER_BOILERPLATE"
    return out
