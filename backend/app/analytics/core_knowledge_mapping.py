"""
Pure mapping logic for the Core Discipline Knowledge Layer. No DB, no
fabricated certainty, no fuzzy matching, no LLM.

MATCHING TAXONOMY (spec: cross-university normalization audit, Phase 3).
Every result carries an overall "status" (MATCHED | AMBIGUOUS | COMPOUND |
NO_MATCH) and, when matched, a "method" identifying WHICH deterministic
technique produced it -- these are never collapsed into one generic
"matched" flag, because a curated exact match and an abbreviation expansion
carry different evidentiary weight (see validate_mapping_evidence).

Methods implemented, tried in this fixed order (first hit wins per phrase):
    1. exact_label_match        -- byte-identical to a core topic's name
    2. normalized_label_match   -- identical after normalize_skill_text
       (Unicode NFKC, case, whitespace -- NOT punctuation, NOT stemming)
    3. abbreviation_match       -- the WHOLE trimmed phrase, case-insensitively,
       is a known abbreviation key (data-driven, app/reference_data/term_abbreviations.json)
       whose expansion then normalized-matches a core topic
    4. synonym_match            -- the phrase belongs to a configured synonym
       group (app/reference_data/term_synonyms.json) whose group also
       contains a core topic's name

semantic_match is a RESERVED, NOT-YET-IMPLEMENTED method name (spec Phase 8:
"create a clean extension point", not a big embedding pipeline). No code
path produces it today; it exists so a future embedding-based matcher slots
into the same result shape without a redesign.

COMPOUND CONCEPTS (spec Phase 9): "Data Structures and Algorithms" is tried
as a WHOLE phrase first (methods 1-4 above). Only if that fails is it split
on connector words (", ", " and ", "&", "/") and each part matched
independently. This means "Data Structures and Algorithms" is NEVER
silently treated as identical to "Data Structures" -- if no core topic is
literally named "Data Structures and Algorithms", decomposition can at most
report a PARTIAL, component-by-component match (status COMPOUND), never a
single core_topic_id standing in for the whole compound phrase. Likewise
"Advanced Data Structures" has no comma/and/&//, so it is never decomposed,
and normalized/exact/abbreviation/synonym matching correctly find no match
against a core topic named only "Data Structures" -- broader/narrower terms
are NOT synonyms and are deliberately excluded from term_synonyms.json.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from app.pipelines.preprocessing.skill_normalization import normalize_skill_text

_REFERENCE_DATA_DIR = Path(__file__).resolve().parents[1] / "reference_data"

METHOD_EXACT_LABEL = "exact_label_match"
METHOD_NORMALIZED_LABEL = "normalized_label_match"
METHOD_CONJUNCTION_NORMALIZED = "conjunction_normalized_match"
METHOD_ABBREVIATION = "abbreviation_match"
METHOD_SYNONYM = "synonym_match"
METHOD_COMPOUND = "compound_concept_match"
METHOD_SEMANTIC = "semantic_match"  # reserved -- not implemented, see module docstring
METHOD_MANUAL_CURATED = "manual_curated"

MATCH_STATUS_MATCHED = "MATCHED"
MATCH_STATUS_NO_MATCH = "NO_MATCH"
MATCH_STATUS_AMBIGUOUS = "AMBIGUOUS"
MATCH_STATUS_COMPOUND = "COMPOUND"

_COMPOUND_SPLIT_RE = re.compile(r"\s*(?:,|&|/|\band\b)\s*", re.IGNORECASE)


@lru_cache(maxsize=1)
def load_abbreviation_map():
    """{"DBMS": "Database Management Systems", ...} from the reference JSON.
    Returns {} if the file is missing rather than raising -- a missing
    reference file means "no abbreviations configured", not a crash."""
    path = _REFERENCE_DATA_DIR / "term_abbreviations.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


@lru_cache(maxsize=1)
def load_synonym_groups():
    """[["Database Management System", "Database Management Systems", "Database Systems"], ...]"""
    path = _REFERENCE_DATA_DIR / "term_synonyms.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("groups", [])


def discipline_slug(name):
    """Stable, language-neutral key for a discipline name taken from source
    metadata ("Computer Science & Engineering" -> "computer-science-and-engineering").
    Pure string transformation; knows nothing about any particular discipline."""
    if not name:
        return None
    text = normalize_skill_text(str(name)).replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or None


def _applies(meta, slug):
    scopes = meta.get("_applies_to_disciplines") or []
    return (not scopes) or (slug is not None and slug in scopes)


def load_scoped_vocabulary(discipline=None):
    """
    Discipline-scoped abbreviations + synonym groups. Unlike the legacy
    load_abbreviation_map()/load_synonym_groups() (which return every entry
    regardless of discipline and are kept unchanged for existing callers),
    this applies a vocabulary file ONLY when its `_applies_to_disciplines`
    list is empty (discipline-neutral) or contains the given discipline's
    slug. discipline=None -> only discipline-neutral vocabulary applies.
    Returns (abbreviation_map, synonym_groups, sources) where sources lists
    the files actually applied, for provenance.
    """
    slug = discipline_slug(discipline) if discipline else None
    abbreviations, groups, sources = {}, [], []
    abbr_path = _REFERENCE_DATA_DIR / "term_abbreviations.json"
    syn_path = _REFERENCE_DATA_DIR / "term_synonyms.json"
    if abbr_path.exists():
        data = json.loads(abbr_path.read_text(encoding="utf-8"))
        if _applies(data, slug):
            abbreviations.update({k: v for k, v in data.items() if not k.startswith("_")})
            sources.append(abbr_path.name)
    if syn_path.exists():
        data = json.loads(syn_path.read_text(encoding="utf-8"))
        if _applies(data, slug):
            groups.extend(data.get("groups", []))
            sources.append(syn_path.name)
    vocab_dir = _REFERENCE_DATA_DIR / "vocab"
    if vocab_dir.exists():
        for path in sorted(vocab_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if _applies(data, slug):
                abbreviations.update(data.get("abbreviations", {}))
                groups.extend(data.get("synonym_groups", []))
                sources.append(f"vocab/{path.name}")
    return abbreviations, groups, sources


def _normalize_conjunctions(text):
    """
    Generic textual normalization (spec: fix the '&' vs 'and' gap
    generically, not with a CSE-specific rule): converts '&' used as a
    word-conjunction ("X & Y") to 'and', so "Computer Organization &
    Architecture" and "Computer Organization And Architecture" compare
    equal after this + normalize_skill_text. Requires whitespace on BOTH
    sides of the '&' -- this is what distinguishes a conjunction ("X & Y")
    from a symbol embedded in a proper noun or code with no surrounding
    spaces ("AT&T", "R&D" written without spaces), which are deliberately
    left untouched. This is pure text substitution, not a lookup table of
    known phrases -- it applies to ANY pair of terms differing only this
    way, for any discipline.
    """
    return re.sub(r"\s+&\s+", " and ", text)


def _match_single_phrase(text, core_topics, abbreviation_map, synonym_map):
    """One phrase, methods 1-4 in order. Never decomposes compounds -- that
    is match_text_to_core_topics's job, one level up."""
    if not text or not core_topics:
        return {"status": MATCH_STATUS_NO_MATCH}
    stripped = text.strip()

    exact = [t["id"] for t in core_topics if stripped == t["name"].strip()]
    if len(exact) == 1:
        return {"status": MATCH_STATUS_MATCHED, "core_topic_id": exact[0], "method": METHOD_EXACT_LABEL, "confidence": 1.0}
    if len(exact) > 1:
        return {"status": MATCH_STATUS_AMBIGUOUS, "candidate_ids": sorted(exact), "method": METHOD_EXACT_LABEL}

    normalized_text = normalize_skill_text(stripped)
    normalized = [t["id"] for t in core_topics if normalized_text == normalize_skill_text(t["name"])]
    if len(normalized) == 1:
        return {"status": MATCH_STATUS_MATCHED, "core_topic_id": normalized[0], "method": METHOD_NORMALIZED_LABEL, "confidence": 0.9}
    if len(normalized) > 1:
        return {"status": MATCH_STATUS_AMBIGUOUS, "candidate_ids": sorted(normalized), "method": METHOD_NORMALIZED_LABEL}

    conjunction_normalized_text = normalize_skill_text(_normalize_conjunctions(stripped))
    conjunction_normalized = [
        t["id"] for t in core_topics
        if conjunction_normalized_text == normalize_skill_text(_normalize_conjunctions(t["name"]))
    ]
    if len(conjunction_normalized) == 1:
        return {
            "status": MATCH_STATUS_MATCHED, "core_topic_id": conjunction_normalized[0],
            "method": METHOD_CONJUNCTION_NORMALIZED, "confidence": 0.88,
        }
    if len(conjunction_normalized) > 1:
        return {"status": MATCH_STATUS_AMBIGUOUS, "candidate_ids": sorted(conjunction_normalized), "method": METHOD_CONJUNCTION_NORMALIZED}

    upper_map = {k.upper(): v for k, v in abbreviation_map.items()}
    if stripped.upper() in upper_map:
        expanded_normalized = normalize_skill_text(upper_map[stripped.upper()])
        candidates = sorted(t["id"] for t in core_topics if normalize_skill_text(t["name"]) == expanded_normalized)
        if len(candidates) == 1:
            return {"status": MATCH_STATUS_MATCHED, "core_topic_id": candidates[0], "method": METHOD_ABBREVIATION, "confidence": 0.85}
        if len(candidates) > 1:
            return {"status": MATCH_STATUS_AMBIGUOUS, "candidate_ids": candidates, "method": METHOD_ABBREVIATION}

    for group in synonym_map:
        normalized_group = {normalize_skill_text(term) for term in group}
        if normalized_text in normalized_group:
            candidates = sorted({t["id"] for t in core_topics if normalize_skill_text(t["name"]) in normalized_group})
            if len(candidates) == 1:
                return {"status": MATCH_STATUS_MATCHED, "core_topic_id": candidates[0], "method": METHOD_SYNONYM, "confidence": 0.8}
            if len(candidates) > 1:
                return {"status": MATCH_STATUS_AMBIGUOUS, "candidate_ids": candidates, "method": METHOD_SYNONYM}

    return {"status": MATCH_STATUS_NO_MATCH}


def match_text_to_core_topics(text, core_topics, abbreviation_map=None, synonym_map=None):
    """
    text: raw text to match (e.g. a CurriculumTopic.topic_text).
    core_topics: [{"id": int, "name": str}, ...] candidate CoreTopic rows --
        the CALLER scopes these to one discipline first (see
        scope_core_topics_to_discipline); this function never looks across
        disciplines on its own.
    abbreviation_map / synonym_map: override the default reference-data
        files (mainly for tests); None loads the real, swappable
        configuration files.

    Returns a dict with "status":
      MATCHED   -> exactly one candidate matched a single phrase; includes
                   core_topic_id, method, confidence.
      AMBIGUOUS -> 2+ candidates matched at the same method level; includes
                   candidate_ids and method, NEVER a core_topic_id -- never
                   silently resolved by picking one.
      COMPOUND  -> the WHOLE phrase matched nothing, but it decomposes (on
                   ",", "&", "/", " and ") into 2+ parts and at least one
                   part matched independently. Includes "components" (one
                   entry per part, each itself MATCHED/AMBIGUOUS/NO_MATCH)
                   and matched_component_count/total_component_count --
                   this is a PARTIAL result, never claimed as full identity
                   with the compound phrase.
      NO_MATCH  -> nothing matched at any level; never guesses a "closest" topic.
    """
    if not text or not core_topics:
        return {"status": MATCH_STATUS_NO_MATCH}

    abbreviation_map = load_abbreviation_map() if abbreviation_map is None else abbreviation_map
    synonym_map = load_synonym_groups() if synonym_map is None else synonym_map

    whole = _match_single_phrase(text, core_topics, abbreviation_map, synonym_map)
    if whole["status"] in (MATCH_STATUS_MATCHED, MATCH_STATUS_AMBIGUOUS):
        return whole

    parts = [p.strip() for p in _COMPOUND_SPLIT_RE.split(text) if p.strip()]
    if len(parts) < 2:
        return whole  # nothing to decompose -- stays NO_MATCH, e.g. "Advanced Data Structures"

    components = []
    matched_count = 0
    for part in parts:
        result = _match_single_phrase(part, core_topics, abbreviation_map, synonym_map)
        components.append({"text": part, **result})
        if result["status"] == MATCH_STATUS_MATCHED:
            matched_count += 1

    if matched_count == 0:
        return {"status": MATCH_STATUS_NO_MATCH}
    return {
        "status": MATCH_STATUS_COMPOUND,
        "method": METHOD_COMPOUND,
        "components": components,
        "matched_component_count": matched_count,
        "total_component_count": len(parts),
    }


def scope_core_topics_to_discipline(core_topics, discipline_id, include_inactive=False):
    """
    core_topics: [{"id", "name", "discipline_id", "is_active"}, ...] -- the
    DB layer resolves discipline_id through CoreTopic -> CoreKnowledgeDomain.
    Discipline isolation is enforced HERE by data (the discipline_id each
    row carries), never by comparing discipline names in code. Inactive
    topics are excluded by default so a retracted/superseded topic can never
    become a new mapping target.
    """
    return [
        t for t in core_topics
        if t.get("discipline_id") == discipline_id and (include_inactive or t.get("is_active", 1) == 1)
    ]


def validate_skill_mapping_target(core_topic_id, core_subtopic_id):
    """A CoreKnowledgeSkillMapping must target exactly one of topic/subtopic.
    Returns (is_valid, reason)."""
    if core_topic_id is None and core_subtopic_id is None:
        return False, "Mapping has neither core_topic_id nor core_subtopic_id."
    if core_topic_id is not None and core_subtopic_id is not None:
        return False, "Mapping sets both core_topic_id and core_subtopic_id; exactly one is required."
    return True, "OK"


def find_duplicate_names(rows, key_fields):
    """
    rows: plain dicts; key_fields: e.g. ("domain_id", "name"). Duplicate
    detection uses the SAME normalization as matching, so "Digital
    Electronics" and "digital  electronics" under one domain are reported as
    duplicates even though the DB UniqueConstraint (exact string) would not
    catch them. Returns a list of sorted id-lists, one per duplicate group.
    """
    groups = {}
    for r in rows:
        key = tuple(normalize_skill_text(r[f]) if f == "name" else r.get(f) for f in key_fields)
        groups.setdefault(key, []).append(r["id"])
    return [sorted(ids) for ids in groups.values() if len(ids) > 1]


def validate_mapping_evidence(method, confidence):
    """
    Guards against silently treating an unassessed/low-confidence mapping as
    authoritative. Returns (is_authoritative, reason). A mapping with
    method="manual_curated" is always authoritative regardless of confidence
    (a human verified it). Any other method requires a real, non-None
    confidence to be treated as authoritative.
    """
    if method == METHOD_MANUAL_CURATED:
        return True, "Manually curated mapping."
    if confidence is None:
        return False, f"Method '{method}' has no assessed confidence; not treated as authoritative."
    return confidence >= 0.85, f"Method '{method}' with confidence {confidence}."
