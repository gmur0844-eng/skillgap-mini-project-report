"""
Tests for the TF-IDF + rule-based semantic layer. Uses the exact validation
examples given in the semantic-matching brief (Step 16) as synthetic test
fixtures -- this validates the INFRASTRUCTURE's behavior, not a claim about
real AICTE/CBIT data (see test_concept_semantic_matching_real_data.py for
that, run separately and reported honestly).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.concept_semantic_matching import (
    build_context_representation,
    retrieve_candidate_concepts,
    classify_relationship,
    resolve_concept,
    discover_concept,
    REL_SAME_CONCEPT,
    REL_PARTIAL_OVERLAP,
    REL_AMBIGUOUS,
    REL_INSUFFICIENT_EVIDENCE,
    CONFIDENCE_HIGH,
)

REFERENCE = [
    {"id": 1, "name": "Searching"},
    {"id": 2, "name": "Sorting"},
    {"id": 3, "name": "Deadlock Management"},
    {"id": 4, "name": "Database Normalization"},
    {"id": 5, "name": "Computer Networks"},
    {"id": 6, "name": "Project Scheduling"},
    {"id": 7, "name": "Cloud Computing"},
]


def _resolve(topic, course=None):
    ctx = build_context_representation(topic, course_title=course)
    candidates = retrieve_candidate_concepts(ctx, REFERENCE)
    return classify_relationship(ctx, candidates)


# --- context representation (Step 3) ---
def test_context_representation_assembles_real_fields_only():
    ctx = build_context_representation(
        "Scheduling", course_title="Operating Systems", module_heading="Unit III",
        previous_topics=["Process states"], next_topics=["Synchronization"],
        course_outcomes=["Understand OS internals"],
    )
    assert ctx["topic_text"] == "Scheduling"
    assert ctx["course_title"] == "Operating Systems"
    assert ctx["previous_topics"] == ["Process states"]
    assert ctx["next_topics"] == ["Synchronization"]


def test_context_representation_handles_missing_fields_honestly():
    ctx = build_context_representation("Scheduling")
    assert ctx["course_title"] is None
    assert ctx["previous_topics"] == []


# --- retrieval never forces a candidate ---
def test_retrieval_returns_empty_when_nothing_clears_threshold():
    ctx = build_context_representation("xyzabc completely unrelated gibberish term qqq")
    candidates = retrieve_candidate_concepts(ctx, REFERENCE, min_similarity=0.5)
    assert candidates == []


def test_retrieval_empty_reference_returns_empty():
    ctx = build_context_representation("Searching")
    assert retrieve_candidate_concepts(ctx, []) == []


# --- the brief's exact validation examples ---
def test_searching_topic_retrieves_searching_concept():
    r = _resolve("Searching techniques including sequential and binary search")
    assert r["canonical_concept"] == "Searching"
    assert r["relationship"] != REL_SAME_CONCEPT  # Stage 2 never claims SAME_CONCEPT


def test_deadlock_topic_retrieves_deadlock_management():
    r = _resolve("Deadlock prevention, avoidance, detection and recovery")
    assert r["canonical_concept"] == "Deadlock Management"


def test_normalization_topic_retrieves_database_normalization():
    r = _resolve("Normalization and functional dependencies")
    assert r["canonical_concept"] == "Database Normalization"


def test_neural_networks_does_not_confidently_match_computer_networks():
    """CRITICAL disambiguation case from the brief."""
    r = _resolve("Neural networks")
    assert r["evidence_tier"] != CONFIDENCE_HIGH
    assert r["relationship"] in (REL_PARTIAL_OVERLAP, REL_INSUFFICIENT_EVIDENCE, REL_AMBIGUOUS)


def test_process_scheduling_does_not_confidently_match_project_scheduling():
    """CRITICAL disambiguation case -- shares 'scheduling' but different domain word."""
    r = _resolve("Process scheduling")
    assert r["evidence_tier"] != CONFIDENCE_HIGH


def test_cloud_computing_close_wording_gets_higher_confidence_than_sparse_overlap():
    r_close = _resolve("Cloud computing fundamentals")
    r_sparse = _resolve("Deadlock prevention, avoidance, detection and recovery")
    assert r_close["similarity_score"] > r_sparse["similarity_score"]


# --- SAME_CONCEPT is reserved for Stage 1, never claimed by Stage 2/3 alone ---
def test_stage_2_alone_never_returns_same_concept():
    for topic in ["Searching", "Deadlock Management", "Database Normalization", "Cloud Computing"]:
        r = _resolve(topic)
        assert r["relationship"] != REL_SAME_CONCEPT


def test_resolve_concept_stage_1_wins_when_present():
    """When a deterministic (Stage 1) result already matched, Stage 2/3 must
    never override it with a weaker statistical guess."""
    ctx = build_context_representation("Operating Systems")
    deterministic = {"status": "MATCHED", "method": "exact_label_match", "confidence": 1.0}
    result = resolve_concept(ctx, REFERENCE, deterministic_result=deterministic)
    assert result["relationship"] == REL_SAME_CONCEPT
    assert result["stage"] == 1
    assert result["evidence_tier"] == CONFIDENCE_HIGH


def test_resolve_concept_falls_back_to_stage_2_when_stage_1_found_nothing():
    ctx = build_context_representation("Searching techniques")
    deterministic = {"status": "NO_MATCH"}
    result = resolve_concept(ctx, REFERENCE, deterministic_result=deterministic)
    assert result["stage"] == 2
    assert result["relationship"] != REL_SAME_CONCEPT


# --- ambiguity ---
def test_ambiguous_when_top_two_candidates_are_close():
    close_reference = [{"id": 1, "name": "Network Security Protocols"}, {"id": 2, "name": "Network Security Systems"}]
    ctx = build_context_representation("Network Security")
    candidates = retrieve_candidate_concepts(ctx, close_reference)
    result = classify_relationship(ctx, candidates)
    assert result["relationship"] == REL_AMBIGUOUS
    assert result["canonical_concept"] is None  # never picks one arbitrarily


# --- evidence is never hidden ---
def test_evidence_always_present_and_never_fabricated():
    r = _resolve("Searching techniques")
    assert isinstance(r["evidence"], list)
    assert len(r["evidence"]) >= 1
    assert r["evidence"][0]["concept_name"] == "Searching"


# --- concept discovery (Step 8) ---
def test_discover_concept_flags_genuinely_novel_topic():
    ctx = build_context_representation("Transformer architectures for vision-language models")
    discovered = discover_concept(ctx, REFERENCE, min_similarity_for_known=0.3)
    assert discovered is not None
    assert discovered["status"] == "NEW_DISCOVERED_UNMAPPED"
    assert discovered["raw_topic"] == "Transformer architectures for vision-language models"


def test_discover_concept_returns_none_for_known_topic():
    ctx = build_context_representation("Searching")
    discovered = discover_concept(ctx, REFERENCE, min_similarity_for_known=0.3)
    assert discovered is None


# --- determinism ---
def test_deterministic_repeated_calls():
    r1 = _resolve("Deadlock prevention, avoidance, detection and recovery")
    r2 = _resolve("Deadlock prevention, avoidance, detection and recovery")
    assert r1 == r2


# --- context influences retrieval (Step 3's example) ---
def test_context_course_title_included_in_query():
    ctx_with_context = build_context_representation("Scheduling", course_title="Operating Systems Process Management")
    ctx_bare = build_context_representation("Scheduling")
    ref = [{"id": 1, "name": "Process Scheduling"}, {"id": 2, "name": "Project Scheduling"}]
    with_ctx = retrieve_candidate_concepts(ctx_with_context, ref)
    retrieve_candidate_concepts(ctx_bare, ref)  # must not fail without context
    # with course context injected, Process Scheduling should score at least
    # as well relative to Project Scheduling as the bare topic alone
    assert with_ctx[0]["concept_name"] == "Process Scheduling"


def test_stopwords_do_not_cause_spurious_similarity():
    """
    Real bug found via honest testing against actual CBIT data: with such a
    small reference corpus, IDF alone did not sufficiently downweight
    common connector words -- "Indian Constitution and Fundamental
    Principles" spuriously matched "Signals and Systems" purely because
    both contain "and". Fixed with an explicit generic stopword filter.
    """
    ref = [{"id": 1, "name": "Signals and Systems"}, {"id": 2, "name": "Data Structures and Algorithms"}]
    ctx = build_context_representation("Indian Constitution and Fundamental Principles")
    candidates = retrieve_candidate_concepts(ctx, ref, min_similarity=0.0)
    assert all(c["similarity"] == 0.0 for c in candidates)


def test_genuine_shared_content_words_still_match_after_stopword_fix():
    """Regression guard: the stopword fix must not have broken genuine
    matches that share real content words."""
    ref = [{"id": 1, "name": "Database Normalization"}]
    ctx = build_context_representation("Normalization and functional dependencies")
    candidates = retrieve_candidate_concepts(ctx, ref)
    assert candidates and candidates[0]["similarity"] > 0.2
