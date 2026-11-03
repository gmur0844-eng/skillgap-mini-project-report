"""
Tests for the extended matching taxonomy added during the cross-university
curriculum normalization audit: abbreviation, synonym, and compound-concept
matching, plus the explicit spec examples and negative cases.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.core_knowledge_mapping import (
    match_text_to_core_topics,
    scope_core_topics_to_discipline,
    load_abbreviation_map,
    load_synonym_groups,
    METHOD_EXACT_LABEL,
    METHOD_NORMALIZED_LABEL,
    METHOD_CONJUNCTION_NORMALIZED,
    METHOD_ABBREVIATION,
    METHOD_SYNONYM,
    METHOD_COMPOUND,
    MATCH_STATUS_MATCHED,
    MATCH_STATUS_AMBIGUOUS,
    MATCH_STATUS_COMPOUND,
    MATCH_STATUS_NO_MATCH,
)

TOPICS = [
    {"id": 1, "name": "Database Management Systems", "discipline_id": 1, "is_active": 1},
    {"id": 2, "name": "Operating Systems", "discipline_id": 1, "is_active": 1},
    {"id": 3, "name": "Data Structures", "discipline_id": 1, "is_active": 1},
    {"id": 4, "name": "Computer Networks", "discipline_id": 1, "is_active": 1},
    {"id": 5, "name": "Artificial Intelligence", "discipline_id": 1, "is_active": 1},
]


def _scoped():
    return scope_core_topics_to_discipline(TOPICS, 1)


# 1. exact match
def test_exact_match():
    r = match_text_to_core_topics("Data Structures", _scoped())
    assert r == {"status": MATCH_STATUS_MATCHED, "core_topic_id": 3, "method": METHOD_EXACT_LABEL, "confidence": 1.0}


# 2. case variation
def test_case_variation_is_normalized_match():
    r = match_text_to_core_topics("data structures", _scoped())
    assert r["status"] == MATCH_STATUS_MATCHED
    assert r["method"] == METHOD_NORMALIZED_LABEL


# 3. punctuation variation (whitespace collapse counts here too)
def test_whitespace_variation_is_normalized_match():
    r = match_text_to_core_topics("  Data    Structures ", _scoped())
    assert r["status"] == MATCH_STATUS_MATCHED
    assert r["method"] == METHOD_NORMALIZED_LABEL


# 4. whitespace variation (explicit)
def test_extra_internal_whitespace():
    r = match_text_to_core_topics("Computer   Networks", _scoped())
    assert r["status"] == MATCH_STATUS_MATCHED


# 5. abbreviation
def test_abbreviation_dbms():
    r = match_text_to_core_topics("DBMS", _scoped())
    assert r["status"] == MATCH_STATUS_MATCHED
    assert r["method"] == METHOD_ABBREVIATION
    assert r["core_topic_id"] == 1


def test_abbreviation_is_whole_term_only_not_substring():
    """'DBMS Lab' must NOT match via abbreviation substring sloppiness."""
    r = match_text_to_core_topics("DBMS Lab", _scoped())
    assert r["status"] == MATCH_STATUS_NO_MATCH


# 6. known synonym
def test_synonym_database_systems():
    r = match_text_to_core_topics("Database Systems", _scoped())
    assert r["status"] == MATCH_STATUS_MATCHED
    assert r["method"] == METHOD_SYNONYM
    assert r["core_topic_id"] == 1


def test_synonym_operating_system_concepts():
    r = match_text_to_core_topics("Operating System Concepts", _scoped())
    assert r["status"] == MATCH_STATUS_MATCHED
    assert r["method"] == METHOD_SYNONYM


# 7. compound topic
def test_compound_data_structures_and_algorithms():
    r = match_text_to_core_topics("Data Structures and Algorithms", _scoped())
    assert r["status"] == MATCH_STATUS_COMPOUND
    assert r["method"] == METHOD_COMPOUND
    assert r["matched_component_count"] == 1
    assert r["total_component_count"] == 2
    matched = [c for c in r["components"] if c["status"] == MATCH_STATUS_MATCHED]
    assert len(matched) == 1
    assert matched[0]["core_topic_id"] == 3  # Data Structures
    unmatched = [c for c in r["components"] if c["status"] == MATCH_STATUS_NO_MATCH]
    assert unmatched[0]["text"] == "Algorithms"


def test_compound_never_claims_full_identity_with_whole_phrase():
    """CRITICAL: a compound match must never carry a single core_topic_id
    standing in for the whole phrase."""
    r = match_text_to_core_topics("Data Structures and Algorithms", _scoped())
    assert "core_topic_id" not in r


def test_compound_computer_networks_variant():
    r = match_text_to_core_topics("Computer Networks and Data Communication", _scoped())
    # "Computer Networks and Data Communication" is not itself a listed core
    # topic or synonym entry verbatim, but "Computer Networks" is a
    # component and should match; "Data Communication" should not.
    assert r["status"] in (MATCH_STATUS_COMPOUND, MATCH_STATUS_MATCHED)


def test_compound_with_ampersand_and_slash_separators():
    topics = [{"id": 10, "name": "Data Structures", "discipline_id": 1, "is_active": 1},
              {"id": 11, "name": "Operating Systems", "discipline_id": 1, "is_active": 1}]
    r = match_text_to_core_topics("Data Structures & Operating Systems", topics)
    assert r["status"] == MATCH_STATUS_COMPOUND
    assert r["matched_component_count"] == 2


# 8. ambiguous topic
def test_ambiguous_topic_same_name_different_ids():
    topics = [{"id": 1, "name": "Data Structures", "discipline_id": 1, "is_active": 1},
              {"id": 2, "name": "Data Structures", "discipline_id": 1, "is_active": 1}]
    r = match_text_to_core_topics("Data Structures", topics)
    assert r["status"] == MATCH_STATUS_AMBIGUOUS
    assert "core_topic_id" not in r


# 9. no match -- the critical negative case from the spec
def test_advanced_data_structures_is_not_automatically_data_structures():
    r = match_text_to_core_topics("Advanced Data Structures", _scoped())
    assert r["status"] == MATCH_STATUS_NO_MATCH


def test_completely_unrelated_text_no_match():
    r = match_text_to_core_topics("Quantum Chromodynamics", _scoped())
    assert r["status"] == MATCH_STATUS_NO_MATCH


# 10. semantic candidate -- reserved, not implemented
def test_semantic_match_is_reserved_not_implemented():
    """No code path produces METHOD_SEMANTIC yet -- confirm it stays that
    way rather than someone accidentally wiring up an unverified guess."""
    for text in ["DBMS", "Advanced Data Structures", "Data Structures and Algorithms"]:
        r = match_text_to_core_topics(text, _scoped())
        assert r.get("method") != "semantic_match"


# 11. provenance preservation -- structural, verified at the orchestration layer
# (see test_core_knowledge_db_simulation.py for the curriculum-wording-unchanged check)


# 12. original-term preservation (compound components keep their own exact text)
def test_compound_components_preserve_original_wording():
    r = match_text_to_core_topics("Data Structures and Algorithms", _scoped())
    texts = [c["text"] for c in r["components"]]
    assert texts == ["Data Structures", "Algorithms"]


# 13. programme isolation -- covered by scope_core_topics_to_discipline tests already in test_core_knowledge_mapping.py


# 14. curriculum-version isolation -- structural (CurriculumTopicCoreTopicMapping keys on
# curriculum_topic_id, which is itself scoped to one CurriculumVersion via Course -> Programme;
# no cross-version aggregation occurs anywhere in match_text_to_core_topics or its caller)


def test_reference_data_files_load_and_exclude_broader_narrower_forms():
    abbrevs = load_abbreviation_map()
    assert abbrevs["DBMS"] == "Database Management Systems"
    assert "ADVANCED DATA STRUCTURES" not in {k.upper() for k in abbrevs}

    groups = load_synonym_groups()
    all_terms = {t for group in groups for t in group}
    assert "Advanced Data Structures" not in all_terms
    assert "Data Structures and Algorithms" not in all_terms


def test_deterministic_repeated_calls():
    r1 = match_text_to_core_topics("Data Structures and Algorithms", _scoped())
    r2 = match_text_to_core_topics("Data Structures and Algorithms", _scoped())
    assert r1 == r2


def test_empty_and_none_inputs():
    assert match_text_to_core_topics("", _scoped())["status"] == MATCH_STATUS_NO_MATCH
    assert match_text_to_core_topics(None, _scoped())["status"] == MATCH_STATUS_NO_MATCH
    assert match_text_to_core_topics("Data Structures", [])["status"] == MATCH_STATUS_NO_MATCH


def test_custom_abbreviation_map_override_for_testing():
    custom = {"ML": "Artificial Intelligence"}  # deliberately loose, test-only mapping
    r = match_text_to_core_topics("ML", _scoped(), abbreviation_map=custom, synonym_map=[])
    assert r["status"] == MATCH_STATUS_MATCHED
    assert r["core_topic_id"] == 5


def test_real_world_finding_ampersand_vs_and_now_generically_normalized():
    """
    Real finding from the AICTE/CBIT core-knowledge mapping phase: AICTE's
    'Computer Organization & Architecture' and CBIT's real course title
    'Computer Organization And Architecture' refer to the same subject.
    FIXED generically via _normalize_conjunctions (spec: fix this without a
    CSE-specific rule) -- this now matches via METHOD_CONJUNCTION_NORMALIZED,
    a textual normalization tier available for ANY discipline's terms, not
    a lookup keyed to this specific phrase.
    """
    topics = [{"id": 1, "name": "Computer Organization & Architecture"}]
    result = match_text_to_core_topics("Computer Organization And Architecture", topics)
    assert result["status"] == MATCH_STATUS_MATCHED
    assert result["method"] == METHOD_CONJUNCTION_NORMALIZED
    assert result["core_topic_id"] == 1


def test_conjunction_normalization_is_generic_not_cse_specific():
    """Same mechanism, unrelated discipline/terms -- proves this is a
    general textual rule, not a special case for one phrase."""
    topics = [{"id": 7, "name": "Heat Transfer & Fluid Mechanics"}]
    result = match_text_to_core_topics("Heat Transfer and Fluid Mechanics", topics)
    assert result["status"] == MATCH_STATUS_MATCHED
    assert result["method"] == METHOD_CONJUNCTION_NORMALIZED


def test_conjunction_normalization_does_not_touch_proper_nouns_without_spaces():
    """'&' with no surrounding whitespace (AT&T, R&D) must never be split --
    this guards against the normalization becoming too aggressive."""
    topics_at_and_t = [{"id": 1, "name": "AT and T Case Study"}]
    result = match_text_to_core_topics("AT&T Case Study", topics_at_and_t)
    assert result["status"] == MATCH_STATUS_NO_MATCH  # correctly NOT matched -- no false conjunction expansion


def test_conjunction_normalization_does_not_create_false_ambiguity():
    """Two genuinely different topics must not be accidentally merged by
    over-aggressive conjunction normalization."""
    topics = [
        {"id": 1, "name": "Signals & Systems"},
        {"id": 2, "name": "Signals and Images"},
    ]
    result = match_text_to_core_topics("Signals and Systems", topics)
    assert result["status"] == MATCH_STATUS_MATCHED
    assert result["core_topic_id"] == 1


# --- Regression tests for real findings from the complete CBIT R-22A (Semesters I-VIII) mapping ---

def test_real_finding_exact_match_against_richer_reference_population():
    """Real finding: with the full I-VIII curriculum available, CBIT's real
    'Operating Systems' (22CSC15N) and 'Compiler Design' (22CSC24N) course
    titles now genuinely exact-match the AICTE reference -- these courses
    simply weren't reachable in the earlier Semesters I-IV-only source."""
    topics = [{"id": 1, "name": "Operating Systems"}, {"id": 2, "name": "Compiler Design"}]
    r1 = match_text_to_core_topics("Operating Systems", topics)
    r2 = match_text_to_core_topics("Compiler Design", topics)
    assert r1["status"] == MATCH_STATUS_MATCHED and r1["method"] == METHOD_EXACT_LABEL
    assert r2["status"] == MATCH_STATUS_MATCHED and r2["method"] == METHOD_EXACT_LABEL


def test_real_finding_ai_and_ml_compound_partial_match():
    """Real finding: CBIT's real 'Artificial Intelligence and Machine
    Learning' course (22CSC50) decomposes correctly -- only the 'Machine
    Learning' component matches a reference that doesn't separately list
    'Artificial Intelligence'. This must stay a PARTIAL compound result,
    never a full match implying AI itself is covered."""
    topics = [{"id": 1, "name": "Machine Learning"}]
    r = match_text_to_core_topics("Artificial Intelligence and Machine Learning", topics)
    assert r["status"] == MATCH_STATUS_COMPOUND
    assert r["matched_component_count"] == 1
    assert r["total_component_count"] == 2
    matched = [c for c in r["components"] if c["status"] == MATCH_STATUS_MATCHED]
    assert matched[0]["text"] == "Machine Learning"
    unmatched = [c for c in r["components"] if c["status"] == MATCH_STATUS_NO_MATCH]
    assert unmatched[0]["text"] == "Artificial Intelligence"


def test_known_limitation_short_abbreviation_can_false_positive_on_fragmented_text():
    """
    DOCUMENTED, KNOWN LIMITATION (not a bug to silently 'fix' by removing
    short abbreviations, which would lose genuine cases like 'DBMS'/'OS'
    written deliberately as abbreviations): a bare 2-letter fragment like
    'OS' appearing in EXTRACTED text can match the abbreviation tier even
    when, in its real source context, it was actually a corrupted remnant
    of an unrelated term (e.g. 'OSI' truncated by comma-splitting/line-wrap
    during topic-fragment extraction -- a real case found in the CBIT
    R-22A document, course 22ECO05, where 'OS' came from '...the OSI
    Reference Model...', a NETWORKING topic, not Operating Systems).
    This test locks in that the matching tier behaves exactly as designed
    (it cannot and should not try to infer surrounding context) -- the
    mitigation is at the extraction-quality layer (topic-fragment
    granularity), not by weakening the abbreviation tier itself.
    """
    topics = [{"id": 1, "name": "Operating Systems"}]
    fragment_from_osi_truncation = "OS"
    r = match_text_to_core_topics(fragment_from_osi_truncation, topics)
    assert r["status"] == MATCH_STATUS_MATCHED
    assert r["method"] == METHOD_ABBREVIATION
    # The match is real per the deterministic rules; whether it's SEMANTICALLY
    # correct depends on context this pure function does not have -- that
    # judgment belongs to a human reviewing the source, documented explicitly
    # in the mapping artifact rather than silently trusted.
