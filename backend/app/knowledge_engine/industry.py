"""
Industry layer: skill extraction -> ESCO normalization -> industry demand ->
curriculum coverage -> gap classification -> recommendations, all built on
the project's EXISTING pure functions:

  extraction      app.pipelines.preprocessing.skill_extraction (controlled
                  vocabulary + alias + curated technical tokens; the indexed
                  variant has identical semantics)
  demand          app.analytics.industry_demand.compute_skill_demand
  coverage        app.analytics.curriculum_coverage.compute_curriculum_coverage
  None vs zero    app.analytics.skill_set_alignment.resolve_evidence_value
  gaps            app.analytics.gap_classification.classify_skill_gap
  trend           app.analytics.trend_analysis.assess_trend_sufficiency
  actions         app.analytics.recommendation_engine.generate_recommendation

Vocabulary = the ESCO skill subset reconstructable from the supplied delta
(prefLabels, active English altLabels, qualifier-stripped prefLabels) +
the curated TECHNICAL_TOKENS list. Nothing else is a skill.

Label evidence rule (generic, label-based, no word lists): a matched label
that is a single ordinary word, lower-case or merely capitalised
("communication", "plan", "Angular" -> "Angular momentum"), a bare word left
after removing an ESCO disambiguating qualifier ("Python"), or shorter than
2 characters ("R") does not establish WHICH
sense of the word the text uses. Such skills get ESCO status
INSUFFICIENT_EVIDENCE, stay visible, are queued for review, and do not enter
demand, gaps or recommendations.

ESCO mapping status of a normalized skill:
  EXACT            matched an ESCO prefLabel with identical case
  NORMALIZED       matched a prefLabel after case/whitespace normalization, an
                   active altLabel, or a prefLabel with its "(qualifier)" removed
  SEMANTIC_MATCH   curated technical token with no label match whose TF-IDF
                   similarity to one ESCO label is >= threshold and clear of the
                   runner-up by >= ambiguous_gap (uncalibrated similarity)
  AMBIGUOUS        the matched label belongs to >1 ESCO concept, or two
                   semantic candidates are within ambiguous_gap
  UNMAPPED         no ESCO label in the supplied delta subset (NOT proof that
                   ESCO lacks the skill -- the full baseline was not supplied)
  INSUFFICIENT_EVIDENCE   see label evidence rule above

Circular evidence: only EXTRACTED records from source documents enter
coverage (see evidence_guard.require_source_records).
"""
import functools
import re
from collections import Counter, defaultdict

from app.analytics.curriculum_coverage import compute_curriculum_coverage
from app.analytics.gap_classification import classify_skill_gap
from app.analytics.industry_demand import compute_skill_demand
from app.analytics.recommendation_engine import generate_recommendation
from app.analytics.skill_set_alignment import resolve_evidence_value
from app.analytics.trend_analysis import assess_trend_sufficiency
from app.knowledge_engine.silver import uid
from app.pipelines.preprocessing.skill_extraction import (
    LEFT_BOUNDARY, RIGHT_BOUNDARY, VocabTerm, deduplicate_mentions, extract_mentions_indexed,
)
from app.pipelines.preprocessing.skill_normalization import TECHNICAL_TOKENS, normalize_skill_text

MAPPED_STATUSES = ("EXACT", "NORMALIZED", "SEMANTIC_MATCH")


# ---------------------------------------------------------------- vocabulary

def build_vocabulary(esco_vocab):
    """VocabTerm list (skill_id = ESCO URI) + label index {normalized label: [label records]}."""
    terms, label_index = [], defaultdict(list)
    for lab in esco_vocab["labels"]:
        method = "exact_label" if lab["label_kind"] == "prefLabel" else "alias"
        terms.append(VocabTerm(lab["label"], lab["uri"], lab["uri"], method))
        label_index[normalize_skill_text(lab["label"])].append(lab)
    for token in TECHNICAL_TOKENS:
        terms.append(VocabTerm(token, None, None, "technical_token"))
    return terms, dict(label_index)


def label_is_context_dependent(label, label_kinds=()):
    if len(label.replace(" ", "")) < 2:
        return True, "label shorter than 2 characters"
    word = label.strip()
    if " " not in word and word.isalpha() and (word == word.lower() or (word[0].isupper() and word[1:] == word[1:].lower())):
        # an ordinary single word, lower-case or merely capitalised ("communication", "Angular"):
        # the text can use it in another sense ("Angular momentum"). Acronyms (SQL), camel-case
        # (JavaScript), digits/symbols (C#, SA8000) and multi-word labels are distinctive.
        return True, "single ordinary word: the text match does not establish the skill sense"
    if label_kinds and set(label_kinds) == {"qualifier_stripped"}:
        return True, ("matched only the bare word of an ESCO prefLabel whose qualifier exists to disambiguate it; "
                      "the text does not establish that sense")
    return False, None


# a skill word inside an education requirement ("Bachelor's degree in Computer
# Science") states a qualification, not a demanded skill; such mentions are
# kept and counted separately but do not enter skill demand
_QUALIFICATION_CONTEXT_RE = re.compile(
    r"(degree|bachelor|master|\bb\.?\s?tech|\bb\.?\s?e\b|\bm\.?\s?tech|\bb\.?\s?sc|\bm\.?\s?sc|\bmba\b|diploma|"
    r"graduat\w*|qualification|\bph\.?\s?d\.?|\b[bm]\.?\s?[sa]\.?(?=\s+(?:in|or|degree)\b|\s*[/(,])|"
    r"(?:quantitative|technical|related|relevant)\s+(?:discipline|field)|\bdiscipline\s+such\s+as)[^.;\n]{0,60}$",
    re.IGNORECASE)


def mention_role(text, start):
    before = text[max(0, start - 80):start]
    return "QUALIFICATION_REQUIREMENT" if _QUALIFICATION_CONTEXT_RE.search(before) else "SKILL"


# ---------------------------------------------------------------- extraction

def extract(records, text_key, id_key, index, source_type):
    """Mentions (with character spans) for every record's text."""
    out = []
    for r in records:
        text = r.get(text_key) or ""
        for m in deduplicate_mentions(extract_mentions_indexed(text, index)):
            out.append({"source_type": source_type, "source_uid": r[id_key], "raw_mention": m.original_text,
                        "mention_role": mention_role(text, m.start),
                        "normalized_text": m.normalized_text, "method": m.method, "esco_uri_candidate": m.skill_id,
                        "span": [m.start, m.end], "context": text[max(0, m.start - 60): m.end + 60]})
    return out


_TFIDF_CACHE = {}
_WORDS_RE = re.compile(r"[a-z0-9+#]+")


def _tfidf_semantic(surface, esco_vocab, backend_factory, cfg):
    """Best ESCO label by TF-IDF cosine for a curated technical token (lexical, uncalibrated).
    The backend is fitted once per vocabulary (the label set is identical for every surface)."""
    labels = esco_vocab["labels"]
    key = (id(esco_vocab), len(labels))
    if key not in _TFIDF_CACHE:
        backend = backend_factory()
        backend.fit([l["label"] for l in labels])
        _TFIDF_CACHE.clear()
        _TFIDF_CACHE[key] = (backend, backend.embed([l["label"] for l in labels]))
    backend, label_vecs = _TFIDF_CACHE[key]
    sims = backend.similarity(backend.embed([surface]), label_vecs)[0]
    ranked = sorted(((float(s), i) for i, s in enumerate(sims)), reverse=True)[:3]
    candidates = [{"uri": labels[i]["uri"], "label": labels[i]["label"], "similarity_score": round(s, 4)} for s, i in ranked]
    return candidates


def _scope_words(esco_vocab):
    full = esco_vocab.get("scope") == "FULL_TAXONOMY"
    return {"where": "the full ESCO v1.2.1 classification" if full else "the supplied ESCO delta subset",
            "alt_method": "altLabel_full_taxonomy" if full else "altLabel_active_after_delta",
            "hidden_method": "hiddenLabel_full_taxonomy",
            "unmapped": ("no label in the full ESCO v1.2.1 English classification matches this surface" if full else
                         "no label in the supplied ESCO delta subset matches; the full ESCO baseline was not "
                         "supplied, so this does not show that ESCO lacks the skill"),
            "alias_evidence": "(full ESCO v1.2.1 classification)" if full else "(active after the v1.2.1 delta)"}


def _category(concept):
    t = (concept or {}).get("skill_type")
    if t:
        return t.replace("/", "_").upper(), "ESCO skillType (full classification)"
    if (concept or {}).get("skill_type_change"):
        return concept["skill_type_change"]["new"].rsplit("/", 1)[-1].upper(), "ESCO skillType (changed in the delta)"
    return None, None


def map_skills(mentions, esco_vocab, label_index, backend_factory, cfg):
    """One mapping record per normalized skill surface.

    Several ESCO concepts can share a label. When exactly ONE of them has it as prefLabel (SKOS: the
    preferred name of that concept) and the others only as alt/hidden label, the prefLabel concept is
    chosen and the others are kept as alternative_concepts; any other multi-concept label is AMBIGUOUS."""
    words = _scope_words(esco_vocab)
    by_surface = defaultdict(list)
    for m in mentions:
        by_surface[m["normalized_text"]].append(m)
    concepts = esco_vocab["concepts"]
    mappings = {}
    for surface in sorted(by_surface):
        ms = by_surface[surface]
        methods = Counter(m["method"] for m in ms)
        labels = label_index.get(surface, [])
        uris = sorted({l["uri"] for l in labels})
        rec = {"normalized_label": surface, "raw_mentions": sorted({m["raw_mention"] for m in ms})[:10],
               "extraction_methods": dict(methods), "esco_uri": None, "esco_pref_label": None,
               "mapping_method": None, "similarity_score": None, "score_is_calibrated": False,
               "candidates": [], "alternative_concepts": [], "status": None, "reason": None,
               "taxonomy_scope": esco_vocab.get("scope", "PARTIAL_DELTA_SUBSET"),
               "skill_category": "TECHNOLOGY_TOOL" if methods.get("technical_token") else "UNCATEGORIZED",
               "category_evidence": ("curated technical-token list" if methods.get("technical_token") else
                                     f"ESCO skillType is not available in {words['where']} for this concept")}
        matched_label = labels[0]["label"] if labels else next((m["raw_mention"] for m in ms), surface)
        dependent, why = label_is_context_dependent(matched_label if labels else surface, [l["label_kind"] for l in labels])
        pref_uris = sorted({l["uri"] for l in labels if l["label_kind"] == "prefLabel"})
        chosen = uris[0] if len(uris) == 1 else (pref_uris[0] if len(uris) > 1 and len(pref_uris) == 1 else None)
        if dependent and not methods.get("technical_token"):
            rec.update(status="INSUFFICIENT_EVIDENCE", reason=f"LABEL_CONTEXT_DEPENDENT: {why}",
                       candidates=[{"uri": u, "label": concepts[u]["pref_label"]} for u in uris])
        elif len(uris) > 1 and chosen is None:
            rec.update(status="AMBIGUOUS", reason=f"label belongs to more than one ESCO concept in {words['where']}",
                       candidates=[{"uri": u, "label": concepts[u]["pref_label"],
                                    "label_kinds": sorted({l["label_kind"] for l in labels if l["uri"] == u})} for u in uris])
        elif chosen:
            own = [l for l in labels if l["uri"] == chosen]
            kinds = {l["label_kind"] for l in own}
            if "prefLabel" in kinds and any(m["method"] == "exact_label" for m in ms):
                status, method = "EXACT", "prefLabel_exact"
            elif "prefLabel" in kinds:
                status, method = "NORMALIZED", "prefLabel_case_whitespace_normalized"
            elif "altLabel" in kinds:
                status, method = "NORMALIZED", words["alt_method"]
            elif "hiddenLabel" in kinds:
                status, method = "NORMALIZED", words["hidden_method"]
            else:
                status, method = "NORMALIZED", f"prefLabel_qualifier_removed ({own[0].get('qualifier')})"
            rec.update(status=status, esco_uri=chosen, esco_pref_label=concepts[chosen]["pref_label"],
                       mapping_method=method, reason=f"label match in {words['where']}")
            if len(uris) > 1:
                rec["alternative_concepts"] = [{"uri": u, "label": concepts[u]["pref_label"],
                                                "label_kinds": sorted({l["label_kind"] for l in labels if l["uri"] == u})}
                                               for u in uris if u != chosen]
                rec["reason"] += "; prefLabel precedence over other concepts' alt/hidden labels"
            cat, evidence = _category(concepts[chosen])
            if cat and not methods.get("technical_token"):
                rec["skill_category"], rec["category_evidence"] = cat, evidence
        else:
            candidates = _tfidf_semantic(surface, esco_vocab, backend_factory, cfg) if methods.get("technical_token") else []
            # a surface whose words are a strict subset of a longer label's words names a PART of that label
            # ("x" inside "x y z"), never the same concept: such candidates are kept as RELATED, not matched
            s_tokens = set(_WORDS_RE.findall(surface))
            for c in candidates:
                c_tokens = set(_WORDS_RE.findall(normalize_skill_text(c["label"])))
                c["lexical_relation"] = ("CONTAINED_IN_LONGER_LABEL" if s_tokens and s_tokens < c_tokens else
                                         "SAME_WORDS" if s_tokens == c_tokens else "OTHER")
            rec["candidates"] = candidates
            if candidates and candidates[0]["lexical_relation"] == "CONTAINED_IN_LONGER_LABEL" \
                    and candidates[0]["similarity_score"] >= cfg["esco_semantic_min_similarity"]:
                rec.update(status="UNMAPPED", reason=("the closest ESCO label contains the surface as a part of a longer "
                                                      "name (RELATED, not the same concept); " + words["unmapped"]))
            elif candidates and candidates[0]["similarity_score"] >= cfg["esco_semantic_min_similarity"]:
                second = candidates[1]["similarity_score"] if len(candidates) > 1 else 0.0
                if candidates[0]["similarity_score"] - second < cfg["ambiguous_gap"] and candidates[1]["uri"] != candidates[0]["uri"]:
                    rec.update(status="AMBIGUOUS", reason="two ESCO labels within ambiguous_gap of each other")
                else:
                    top = candidates[0]
                    kind = next((l["label_kind"] for l in esco_vocab["labels"] if l["uri"] == top["uri"] and l["label"] == top["label"]),
                                None)
                    rec.update(status="SEMANTIC_MATCH", esco_uri=top["uri"], esco_pref_label=concepts[top["uri"]]["pref_label"],
                               mapping_method="tfidf_cosine_to_esco_label", similarity_score=top["similarity_score"],
                               matched_label=top["label"], matched_label_kind=kind,
                               reason="lexical similarity to one ESCO label above threshold (uncalibrated)")
            else:
                rec.update(status="UNMAPPED", reason=words["unmapped"])
        rec["skill_key"] = rec["esco_uri"] if rec["status"] in MAPPED_STATUSES else f"surface:{surface}"
        rec["mapping_uid"] = uid("escomap", surface)
        rec["evidence_status"] = {"EXACT": "REFERENCE_MAPPED", "NORMALIZED": "NORMALIZED",
                                  "SEMANTIC_MATCH": "MODEL_SUGGESTED", "AMBIGUOUS": "REVIEW_REQUIRED",
                                  "UNMAPPED": "NORMALIZED", "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE"}[rec["status"]]
        mappings[surface] = rec
    return mappings


def normalized_skills(mappings):
    """Group surfaces into normalized skills (an ESCO URI, or the surface when not mapped)."""
    skills = {}
    for surface, m in mappings.items():
        s = skills.setdefault(m["skill_key"], {"skill_key": m["skill_key"], "skill_uid": uid("skill", m["skill_key"]),
                                               "label": m["esco_pref_label"] or surface, "surfaces": [],
                                               "esco_status": m["status"], "esco_uri": m["esco_uri"],
                                               "esco_pref_label": m["esco_pref_label"], "mapping_method": m["mapping_method"],
                                               "skill_category": m["skill_category"], "eligible_for_analytics": None})
        s["surfaces"].append(surface)
        rank = ["EXACT", "NORMALIZED", "SEMANTIC_MATCH", "AMBIGUOUS", "UNMAPPED", "INSUFFICIENT_EVIDENCE"]
        if rank.index(m["status"]) < rank.index(s["esco_status"]):
            s["esco_status"], s["mapping_method"] = m["status"], m["mapping_method"]
        if m["skill_category"] != "UNCATEGORIZED":
            s["skill_category"] = m["skill_category"]
    for s in skills.values():
        s["surfaces"].sort()
        s["eligible_for_analytics"] = s["esco_status"] != "INSUFFICIENT_EVIDENCE"
    return skills


# ---------------------------------------------------------------- sense validation
#
# A label match establishes a TAXONOMY fact (this string is a label of that ESCO
# concept). Whether the text MEANS that concept is a separate question:
#   prefLabel exact / case-normalized        -> meaning established (identity preserved)
#   altLabel whose prefLabel differs         -> TAXONOMY_ALIAS_MATCH; meaning established only if the
#                                               same text also contains ANOTHER label of that concept
#                                               (its prefLabel, the prefLabel's base word, or a different
#                                               active altLabel); otherwise ALIAS_SENSE_REVIEW_REQUIRED
#   altLabel that is a spelling variant of the prefLabel (same words, char ratio >= config) -> established
#   short upper-case curated acronym token    -> meaning established only if another curated technical
#                                               token or technical-looking label (digit, symbol, camel case)
#                                               occurs in the same text; otherwise ACRONYM_SENSE_REVIEW_REQUIRED
# Unestablished mentions are kept (with their contexts) for review and never enter demand,
# coverage, gaps or recommendations. No surface, label or subject is special-cased.

# ESTABLISHED_BY_MODEL: a MODEL_SUPPORTED semantic decision (evidence validator v2 passed) on a run whose promotion
# gate passed on the frozen benchmark -- see semantic_v3 / intelligence_stage.industry_sense_resolver
SENSE_ESTABLISHED = ("ESTABLISHED", "ESTABLISHED_BY_CONTEXT", "ESTABLISHED_BY_MODEL")
_ACRONYM_RE = re.compile(r"^[A-Z]{2,4}$")


def concept_labels(esco_vocab):
    out = defaultdict(set)
    for lab in esco_vocab["labels"]:
        out[lab["uri"]].add(normalize_skill_text(lab["label"]))
    return out


@functools.lru_cache(maxsize=None)
def _label_pattern(label):
    body = re.escape(label).replace("\\ ", "\\s+")
    return re.compile(LEFT_BOUNDARY + body + RIGHT_BOUNDARY)


def _contains_label(text_lower, label):
    # every word of the label must occur literally for the pattern to match, so the substring test only skips
    # searches that cannot succeed; the compiled pattern is reused (re's own cache thrashed on ~10^4 labels)
    if not all(w in text_lower for w in label.split()):
        return False
    return _label_pattern(label).search(text_lower) is not None


def _distinctive(label):
    """Technical-looking label: a digit, a symbol (C++, .NET, ASP.NET) or camel case inside a word
    (JavaScript, DevOps). Title Case phrases ("Risk Management") and all-caps words (GDPR, SAP) are
    not treated as technical evidence -- acronyms are exactly what is being disambiguated."""
    if any(ch.isdigit() for ch in label) or any(not ch.isalnum() and not ch.isspace() for ch in label):
        return True
    return re.search(r"[a-z][A-Z]", label) is not None


def _orthographic_variant(a, b, min_ratio):
    """Spelling variants of the same words ('color grading' / 'colour grading'): same number of words
    and a character-level similarity ratio >= min_ratio. Identity-preserving, like case normalization."""
    from difflib import SequenceMatcher
    return len(a.split()) == len(b.split()) and SequenceMatcher(None, a, b).ratio() >= min_ratio


def sense_check(mention, mapping, context_text, labels_by_uri, other_mentions, orthographic_min_ratio=0.9):
    """Returns (sense_state, taxonomy_relationship, evidence dict)."""
    surface = mention["normalized_text"]
    method = mapping.get("mapping_method") or ""
    text = (context_text or "").lower()
    pref_norm = normalize_skill_text(mapping.get("esco_pref_label") or "")
    alias = method.startswith(("altLabel", "hiddenLabel")) or mapping.get("matched_label_kind") in ("altLabel", "hiddenLabel")
    if mapping["status"] in ("NORMALIZED", "SEMANTIC_MATCH") and alias and pref_norm and pref_norm != surface \
            and _orthographic_variant(surface, pref_norm, orthographic_min_ratio):
        return "ESTABLISHED", "TAXONOMY_ALIAS_MATCH", {"orthographic_variant_of_preflabel": mapping["esco_pref_label"]}
    if mapping["status"] in ("NORMALIZED", "SEMANTIC_MATCH") and alias and pref_norm and pref_norm != surface:
        others = sorted(l for l in labels_by_uri.get(mapping["esco_uri"], ()) if l != surface and _contains_label(text, l))
        if others:
            return "ESTABLISHED_BY_CONTEXT", "TAXONOMY_ALIAS_MATCH", {"other_labels_of_concept_in_text": others}
        return "ALIAS_SENSE_REVIEW_REQUIRED", "TAXONOMY_ALIAS_MATCH", {
            "observed_text": mention["raw_mention"], "esco_candidate": mapping["esco_pref_label"],
            "esco_uri": mapping["esco_uri"],
            "esco_evidence": (f"'{mention['raw_mention']}' is an English ESCO {method.split('_')[0]} of "
                              if not mapping.get("matched_label") else
                              f"'{mention['raw_mention']}' is lexically similar (uncalibrated) to the ESCO "
                              f"{mapping.get('matched_label_kind')} '{mapping['matched_label']}' of ")
                             + f"'{mapping['esco_pref_label']}' "
                             + ("(full ESCO v1.2.1 classification)" if "full_taxonomy" in method else "(active after the v1.2.1 delta)"),
            "question": f"Does this occurrence of '{mention['raw_mention']}' refer to the ESCO concept "
                        f"'{mapping['esco_pref_label']}'?"}
    if mention["method"] == "technical_token" and _ACRONYM_RE.match(mention["raw_mention"]):
        support = sorted({o["raw_mention"] for o in other_mentions if o["normalized_text"] != surface
                          and (o["method"] == "technical_token" or _distinctive(o["raw_mention"]))})
        if support:
            return "ESTABLISHED_BY_CONTEXT", "CURATED_TOKEN", {"other_technical_terms_in_text": support}
        return "ACRONYM_SENSE_REVIEW_REQUIRED", "CURATED_TOKEN", {
            "observed_text": mention["raw_mention"],
            "question": f"Does '{mention['raw_mention']}' here denote the curated technology token, or another expansion?"}
    raw = (mention.get("raw_mention") or "").strip()
    pref = (mapping.get("esco_pref_label") or "").strip()
    if pref and len(pref) >= 2 and pref.isupper() and raw and raw.islower():
        # the taxonomy writes this label in capitals (a product or acronym: "LESS", "SPARK"); the text writes it in
        # lower case, where it is usually the ordinary word ("less time", "a spark of inspiration"). Case is part
        # of the identity here, so the sense is not established from the match alone.
        return "CASE_SENSE_REVIEW_REQUIRED", "PREFLABEL_NORMALIZED", {
            "observed_text": raw, "esco_candidate": pref,
            "question": f"Does the lower-case '{raw}' here denote '{pref}', or the ordinary word?"}
    relationship = {"prefLabel_exact": "PREFLABEL_EXACT", "prefLabel_case_whitespace_normalized": "PREFLABEL_NORMALIZED"}.get(
        method, "TAXONOMY_ALIAS_MATCH" if method.startswith(("altLabel", "hiddenLabel")) else ("CURATED_TOKEN" if mention["method"] == "technical_token" else None))
    return "ESTABLISHED", relationship, None


# ---------------------------------------------------------------- demand

def support_state(postings, companies, cfg):
    s = cfg["support"]
    if postings >= s["high_support_min_postings"] and companies >= s["high_support_min_companies"]:
        return "HIGH_SUPPORT"
    if postings >= s["supported_min_postings"] and companies >= s["supported_min_companies"]:
        return "SUPPORTED"
    if postings >= s["observed_min_postings"]:
        return "OBSERVED"
    return "INSUFFICIENT_EVIDENCE"


def demand(mentions_by_skill_posting, postings, scope, cfg, segment=None):
    eligible_ids = {p["posting_uid"] for p in postings}
    company_of = {p["posting_uid"]: p.get("company_key") for p in postings}
    eligible_companies = {c for c in company_of.values() if c}
    base = compute_skill_demand([{"job_posting_id": pid, "normalized_skill_id": sk} for sk, pid in mentions_by_skill_posting],
                                eligible_ids)
    rows = []
    for skill_key, d in sorted(base.items()):
        mentioning = sorted({pid for sk, pid in mentions_by_skill_posting if sk == skill_key and pid in eligible_ids})
        companies = {company_of[p] for p in mentioning if company_of.get(p)}
        company_prev = round(len(companies) / len(eligible_companies) * 100, 2) if eligible_companies else None
        rows.append({
            "skill_key": skill_key, "segment": segment or "ALL_POSTINGS",
            "posting_count": d["posting_count"], "eligible_postings": d["total_relevant_postings"],
            "posting_prevalence_pct": d["demand_percentage"],
            "company_count": len(companies), "eligible_companies": len(eligible_companies),
            "company_prevalence_pct": company_prev,
            "support_state": support_state(d["posting_count"], len(companies), cfg),
            "posting_uids": mentioning,
            "statement": (f"{d['posting_count']} of the {d['total_relevant_postings']} eligible supplied postings "
                          f"({d['demand_percentage']}%) mention this skill; observed prevalence, not importance"),
            "evidence_status": "EXTRACTED",
        })
    return rows


def temporal_demand(pairs, postings, cfg_settings, population_ids=None):
    """v1 temporal view: one series over all postings. Periods of DIFFERENT populations (collection methods) are never
    compared: with more than one population the v1 view reports INSUFFICIENT_EVIDENCE and points to the
    per-population trends of industry intelligence v2."""
    pops = sorted(set(population_ids or []))
    if len(pops) > 1:
        return {"postings_by_period": {}, "period_granularity": "month", "trend_status": "INSUFFICIENT_EVIDENCE",
                "reason": (f"{len(pops)} job-posting populations ({', '.join(pops)}); periods of different collection "
                           "methods are not compared -- see the per-population temporal trends"),
                "trend_label_for_all_skills": "INSUFFICIENT_DATA", "populations": pops}
    periods = defaultdict(set)
    for p in postings:
        whens = p.get("open_on_snapshots") or [p["temporal_date"] if "temporal_date" in p else p.get("posted_date")]
        for when in whens:  # see jobs.temporal_date_of; a posting open on several snapshots is in each
            periods[(when or "UNKNOWN")[:7]].add(p["posting_uid"])
    per_period = {k: len(v) for k, v in sorted(periods.items())}
    per_skill = Counter(skill for skill, _ in pairs)
    best_skill_count = max(per_skill.values()) if per_skill else 0  # best case: if even this is insufficient, every skill is
    sufficient = assess_trend_sufficiency(len(periods), list(per_period.values()), best_skill_count,
                                          cfg_settings["min_periods_for_trend"], cfg_settings["min_eligible_postings_per_period"],
                                          cfg_settings["min_skill_postings_for_trend"])
    return {"postings_by_period": per_period, "period_granularity": "month",
            "trend_status": "COMPUTED" if sufficient else "INSUFFICIENT_EVIDENCE",
            "reason": None if sufficient else (
                f"{len(periods)} period(s) with {per_period} postings; trends need >= "
                f"{cfg_settings['min_periods_for_trend']} periods of >= {cfg_settings['min_eligible_postings_per_period']} "
                "postings. No trend is produced and no recency weighting is applied."),
            "trend_label_for_all_skills": None if sufficient else "INSUFFICIENT_DATA"}


def _distinct_rows(matrix):
    """Number of distinct posting vectors (values rounded to 6 decimals). Sparse rows are compared by their non-zero
    entries, so the matrix is never densified (a dense copy of a few hundred postings x the vocabulary does not fit
    in memory)."""
    import numpy as np
    if hasattr(matrix, "tocsr"):
        m = matrix.tocsr(copy=True)
        m.sort_indices()
        keys = set()
        for i in range(m.shape[0]):
            lo, hi = m.indptr[i], m.indptr[i + 1]
            vals = np.round(m.data[lo:hi], 6)
            nz = vals != 0
            keys.add((tuple(m.indices[lo:hi][nz]), tuple(vals[nz])))
        return len(keys)
    return len({tuple(np.round(row, 6)) for row in np.asarray(matrix)})


def segment_postings(postings, backend_factory, cfg):
    """Data-driven role/domain segments: KMeans on TF-IDF of title + description,
    k chosen by cosine silhouette. Descriptive only; each segment keeps its size."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    texts = [f"{p.get('job_title') or ''}. {p.get('job_title') or ''}. {p['clean_description']}" for p in postings]
    backend = backend_factory()
    backend.fit(texts)
    matrix = backend.embed(texts)
    tried, best = [], None
    distinct = _distinct_rows(matrix)
    if distinct <= cfg["segments"]["k_min"]:
        uids = sorted(p["posting_uid"] for p in postings)
        return {"segments": [{"segment_uid": uid("segment", *uids), "label": "all postings (no segmentation possible)",
                              "label_method": "none", "posting_uids": uids, "size": len(uids), "example_titles": []}],
                "selection": {"method": "KMeans + cosine silhouette", "tried": [],
                              "chosen": {"k": 1, "silhouette_cosine": None},
                              "reason": f"only {distinct} distinct posting vectors; clustering is not meaningful"}}
    for k in range(cfg["segments"]["k_min"], min(cfg["segments"]["k_max"], distinct - 1) + 1):
        labels = KMeans(n_clusters=k, n_init=10, random_state=cfg["segments"]["random_state"]).fit_predict(matrix)
        if len(set(labels)) < 2:
            continue
        score = float(silhouette_score(matrix, labels, metric="cosine"))
        tried.append({"k": k, "silhouette_cosine": round(score, 4)})
        if best is None or score > best[0]:
            best = (score, k, labels)
    score, k, labels = best
    segments = []
    for c in range(k):
        idx = [i for i, l in enumerate(labels) if l == c]
        titles = Counter((postings[i].get("job_title") or "").strip() for i in idx)
        top = backend.top_terms(matrix[idx], n=4)
        segments.append({"segment_uid": uid("segment", *sorted(postings[i]["posting_uid"] for i in idx)),
                         "label": " / ".join(top), "label_method": "top TF-IDF terms of member postings",
                         "posting_uids": sorted(postings[i]["posting_uid"] for i in idx), "size": len(idx),
                         "example_titles": [t for t, _ in titles.most_common(5)]})
    return {"segments": sorted(segments, key=lambda s: (-s["size"], s["label"])),
            "selection": {"method": "KMeans + cosine silhouette", "tried": tried, "chosen": {"k": k, "silhouette_cosine": round(score, 4)}}}


# ---------------------------------------------------------------- coverage

def curriculum_coverage(curriculum_mentions, topics_by_uid, courses_by_uid, doc_id, mappings, topic_to_concept):
    """Coverage of each normalized skill in ONE curriculum document from topic text
    evidence only (never from course titles)."""
    doc_courses = {u for u, c in courses_by_uid.items() if c["doc_id"] == doc_id}
    rows, detail = [], defaultdict(lambda: {"topics": [], "direct": set(), "normalized": set()})
    for m in curriculum_mentions:
        t = topics_by_uid.get(m["source_uid"])
        if t is None or t["doc_id"] != doc_id:  # a topic of a curriculum not analysed in this run
            continue
        mp = mappings.get(m["normalized_text"])
        if mp is None or mp["status"] == "INSUFFICIENT_EVIDENCE" or not m.get("sense_established", True):
            continue
        key = mp["skill_key"]
        rows.append({"course_id": t["course_uid"], "normalized_skill_id": key, "mention_source": "curriculum_topic",
                     "source_record_id": t["topic_uid"]})
        d = detail[key]
        d["topics"].append({"topic_uid": t["topic_uid"], "text": t["clean_text"], "course_code": t["course_code"],
                            "course_title": courses_by_uid[t["course_uid"]]["title"], "page": t["page_number"],
                            "unit": t.get("unit_label"), "raw_mention": m["raw_mention"], "span": m["span"],
                            "concept_uid": topic_to_concept.get(t["topic_uid"])})
        (d["direct"] if m["method"] in ("exact_label", "technical_token") else d["normalized"]).add(t["course_uid"])
    measured = compute_curriculum_coverage(rows, doc_courses)
    out = {}
    for key, v in measured.items():
        d = detail[key]
        out[key] = {**v, "doc_id": doc_id,
                    "course_codes": sorted({courses_by_uid[c]["course_code"] for c in {x["course_id"] for x in rows if x["normalized_skill_id"] == key}}),
                    "courses_with_direct_textual_evidence": len(d["direct"]),
                    "courses_with_normalized_evidence_only": len(d["normalized"] - d["direct"]),
                    "concept_uids": sorted({x["concept_uid"] for x in d["topics"] if x["concept_uid"]}),
                    "topic_evidence": sorted(d["topics"], key=lambda x: (x["course_code"], x["page"]))[:12]}
    return out, len(doc_courses)


# ---------------------------------------------------------------- gaps + recommendations

def classify_gaps(skills, demand_rows, target_cov, target_population, reference_cov, previous_cov,
                  industry_population, settings, scope_ref, run_id):
    demand_by = {d["skill_key"]: d for d in demand_rows}
    gaps = []
    for key in sorted(demand_by):
        s = skills[key]
        d = demand_by[key]
        industry_pct = resolve_evidence_value(d["posting_prevalence_pct"], True, industry_population)
        cov = target_cov.get(key)
        curriculum_pct = resolve_evidence_value(cov["coverage_percentage"] if cov else None, cov is not None, target_population)
        g = classify_skill_gap(industry_pct, curriculum_pct, settings["high_demand_threshold"],
                               settings["partial_coverage_threshold"], trend_label="INSUFFICIENT_DATA")
        discipline_evidence = {"target_courses": cov["courses_with_skill"] if cov else 0,
                               "reference_courses": reference_cov[key]["courses_with_skill"] if key in reference_cov else 0,
                               "previous_version_courses": previous_cov[key]["courses_with_skill"] if key in previous_cov else 0}
        classification, reasons = g["classification"], list(g["reasons"])
        evidence_state = g["evidence_state"]
        if classification == "MISSING" and discipline_evidence["reference_courses"] == 0 and discipline_evidence["previous_version_courses"] == 0:
            classification = "INSUFFICIENT_EVIDENCE"
            evidence_state = "DISCIPLINE_RELEVANCE_UNESTABLISHED"
            reasons.append("The postings are a mixed-occupation population and no curriculum document of this "
                           "discipline (target, previous version or reference) mentions the skill; its absence from "
                           "the target curriculum is therefore not established as a gap for this programme. Flagged for review.")
        elif classification == "MISSING" and discipline_evidence["reference_courses"] > 0:
            reasons.append(f"The reference curriculum mentions the skill in {discipline_evidence['reference_courses']} course(s).")
        gaps.append({
            "gap_uid": uid("gap", run_id, key), "skill_key": key, "skill_label": s["label"], "esco_status": s["esco_status"],
            "esco_uri": s["esco_uri"], "classification": classification, "evidence_state": evidence_state,
            "industry_population": industry_population, "industry_count": d["posting_count"],
            "industry_prevalence_pct": industry_pct, "company_count": d["company_count"],
            "company_prevalence_pct": d["company_prevalence_pct"], "support_state": d["support_state"],
            "curriculum_population": target_population, "curriculum_count": cov["courses_with_skill"] if cov else 0,
            "curriculum_coverage_pct": curriculum_pct, "high_demand": g["high_demand"],
            "demand_trend_signal": g["demand_trend_signal"], "discipline_evidence": discipline_evidence,
            "reasons": reasons, "population_scope_ref": scope_ref, "run_id": run_id, "evidence_status": "MODEL_SUGGESTED",
        })
    return gaps


def recommend(gaps, target_cov, cfg):
    """Returns (recommendations, suppressions). Every gap gets exactly one of them."""
    recs, suppressed = [], []
    allowed_support = set(cfg["recommendation"]["min_support_states"])
    for g in gaps:
        why = []
        if g["classification"] == "INSUFFICIENT_EVIDENCE":
            why.append({"code": "GAP_INSUFFICIENT_EVIDENCE", "detail": g["evidence_state"]})
        if g["classification"] == "COVERED":
            why.append({"code": "COVERAGE_SUFFICIENT", "detail": g["reasons"][0]})
        if g["support_state"] not in allowed_support:
            why.append({"code": "INDUSTRY_SUPPORT_BELOW_THRESHOLD",
                        "detail": f"{g['industry_count']} posting(s) at {g['company_count']} compan(ies) -> {g['support_state']}; "
                                  f"recommendations need {sorted(allowed_support)}"})
        if g["esco_status"] == "AMBIGUOUS":
            why.append({"code": "ESCO_MAPPING_AMBIGUOUS", "detail": "the skill label maps to more than one ESCO concept"})
        base = {"skill_key": g["skill_key"], "skill_label": g["skill_label"], "gap_uid": g["gap_uid"], "run_id": g["run_id"],
                "classification": g["classification"], "support_state": g["support_state"]}
        if why:
            suppressed.append({**base, "suppression_uid": uid("norec", g["gap_uid"]), "recommendation_state": "SUPPRESSED",
                               "reasons": why, "evidence_status": "INSUFFICIENT_EVIDENCE"})
            continue
        cov = target_cov.get(g["skill_key"])
        gap_record = {"classification": g["classification"], "evidence_state": g["evidence_state"],
                      "industry_demand_percentage": g["industry_prevalence_pct"],
                      "curriculum_coverage_percentage": g["curriculum_coverage_pct"], "high_demand": g["high_demand"],
                      "demand_trend_signal": g["demand_trend_signal"], "trend_label": "INSUFFICIENT_DATA", "drift_status": None}
        r = generate_recommendation(gap_record, courses_with_evidence=cov["course_codes"] if cov else [])
        if r["recommendation_state"] != "RECOMMENDATION_SUPPORTED":
            suppressed.append({**base, "suppression_uid": uid("norec", g["gap_uid"]), "recommendation_state": "SUPPRESSED",
                               "reasons": [{"code": r["recommendation_state"], "detail": " ".join(r["reasons"])}],
                               "evidence_status": "INSUFFICIENT_EVIDENCE"})
            continue
        uncertainty = []
        if g["esco_status"] in ("UNMAPPED",):
            uncertainty.append("ESCO_UNMAPPED: the skill is normalized but no ESCO concept label in the taxonomy used matches it")
        if g["esco_status"] == "SEMANTIC_MATCH":
            uncertainty.append("ESCO_SEMANTIC_MATCH: ESCO link is lexical similarity, not a label match")
        if g["support_state"] == "SUPPORTED":
            uncertainty.append("BORDERLINE_SUPPORT: support is SUPPORTED, not HIGH_SUPPORT")
        if g["classification"] == "MISSING":
            uncertainty.append("CURRICULUM_ABSENCE_IS_TEXTUAL: no topic text of the target curriculum names the skill; "
                               "a differently worded topic could still teach it")
        recs.append({**base, "recommendation_uid": uid("rec", g["gap_uid"], r["action_type"]),
                     "recommendation_state": "RECOMMENDATION_SUPPORTED", "action_type": r["action_type"],
                     "target_level": r["target_level"], "target_course_codes": r["target_course_codes"],
                     "rule_reasons": r["reasons"], "uncertainty": uncertainty,
                     "evidence_status": "MODEL_SUGGESTED", "is_source_evidence": False})
    return recs, suppressed
