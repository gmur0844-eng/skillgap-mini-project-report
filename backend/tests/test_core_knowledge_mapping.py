import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.core_knowledge_mapping import (
    match_text_to_core_topics,
    validate_mapping_evidence,
    scope_core_topics_to_discipline,
    validate_skill_mapping_target,
    find_duplicate_names,
    METHOD_EXACT_LABEL,
    METHOD_NORMALIZED_LABEL,
    METHOD_MANUAL_CURATED,
    MATCH_STATUS_MATCHED,
    MATCH_STATUS_NO_MATCH,
    MATCH_STATUS_AMBIGUOUS,
)
from app.analytics.data_quality import compute_core_knowledge_quality_metrics

# Synthetic ids/names only -- discipline 10 and 20 are placeholders, not real disciplines.
TOPICS = [
    {"id": 1, "name": "Fixture Topic A", "discipline_id": 10, "is_active": 1},
    {"id": 2, "name": "Fixture Topic B", "discipline_id": 10, "is_active": 1},
    {"id": 3, "name": "Fixture Topic A", "discipline_id": 20, "is_active": 1},  # same name, other discipline
    {"id": 4, "name": "Fixture Topic C", "discipline_id": 10, "is_active": 0},  # inactive
]


# --- deterministic matching ---
def test_exact_match():
    r = match_text_to_core_topics("Fixture Topic B", scope_core_topics_to_discipline(TOPICS, 10))
    assert r == {"status": MATCH_STATUS_MATCHED, "core_topic_id": 2, "method": METHOD_EXACT_LABEL, "confidence": 1.0}


def test_normalized_match():
    r = match_text_to_core_topics("  fixture   topic b ", scope_core_topics_to_discipline(TOPICS, 10))
    assert r["status"] == MATCH_STATUS_MATCHED
    assert r["method"] == METHOD_NORMALIZED_LABEL


def test_no_fuzzy_guessing():
    r = match_text_to_core_topics("Fixture Topic Bee", scope_core_topics_to_discipline(TOPICS, 10))
    assert r == {"status": MATCH_STATUS_NO_MATCH}


def test_empty_inputs_no_match():
    assert match_text_to_core_topics("", TOPICS)["status"] == MATCH_STATUS_NO_MATCH
    assert match_text_to_core_topics(None, TOPICS)["status"] == MATCH_STATUS_NO_MATCH
    assert match_text_to_core_topics("x", [])["status"] == MATCH_STATUS_NO_MATCH


def test_deterministic():
    scoped = scope_core_topics_to_discipline(TOPICS, 10)
    assert match_text_to_core_topics("Fixture Topic A", scoped) == match_text_to_core_topics("Fixture Topic A", scoped)


# --- ambiguous mappings (previously silently resolved by first-match -- fixed) ---
def test_ambiguous_match_is_flagged_not_resolved():
    unscoped = [t for t in TOPICS if t["is_active"]]  # both "Fixture Topic A" rows present
    r = match_text_to_core_topics("Fixture Topic A", unscoped)
    assert r["status"] == MATCH_STATUS_AMBIGUOUS
    assert r["candidate_ids"] == [1, 3]
    assert "core_topic_id" not in r


def test_normalized_ambiguity_flagged():
    candidates = [{"id": 7, "name": "Fixture X"}, {"id": 8, "name": "fixture  x"}]
    r = match_text_to_core_topics("FIXTURE X", candidates)
    assert r["status"] == MATCH_STATUS_AMBIGUOUS
    assert r["candidate_ids"] == [7, 8]


# --- discipline isolation (by data, never by name comparison) ---
def test_discipline_isolation_scoping():
    d10 = scope_core_topics_to_discipline(TOPICS, 10)
    d20 = scope_core_topics_to_discipline(TOPICS, 20)
    assert {t["id"] for t in d10} == {1, 2}
    assert {t["id"] for t in d20} == {3}
    assert not ({t["id"] for t in d10} & {t["id"] for t in d20})


def test_same_name_different_discipline_resolves_within_scope_only():
    r10 = match_text_to_core_topics("Fixture Topic A", scope_core_topics_to_discipline(TOPICS, 10))
    r20 = match_text_to_core_topics("Fixture Topic A", scope_core_topics_to_discipline(TOPICS, 20))
    assert r10["core_topic_id"] == 1
    assert r20["core_topic_id"] == 3


def test_unknown_discipline_yields_empty_scope():
    assert scope_core_topics_to_discipline(TOPICS, 999) == []


# --- inactive records ---
def test_inactive_topic_excluded_by_default():
    r = match_text_to_core_topics("Fixture Topic C", scope_core_topics_to_discipline(TOPICS, 10))
    assert r["status"] == MATCH_STATUS_NO_MATCH


def test_inactive_topic_included_when_requested():
    scoped = scope_core_topics_to_discipline(TOPICS, 10, include_inactive=True)
    assert 4 in {t["id"] for t in scoped}


# --- skill -> core topic mapping target validity ---
def test_mapping_target_exactly_one():
    assert validate_skill_mapping_target(1, None)[0] is True
    assert validate_skill_mapping_target(None, 5)[0] is True
    assert validate_skill_mapping_target(None, None)[0] is False
    assert validate_skill_mapping_target(1, 5)[0] is False


# --- mapping evidence / authority (semantic similarity never auto-authoritative) ---
def test_manual_curated_authoritative():
    assert validate_mapping_evidence(METHOD_MANUAL_CURATED, None)[0] is True


def test_none_confidence_never_authoritative():
    ok, reason = validate_mapping_evidence("semantic_similarity", None)
    assert ok is False and "no assessed confidence" in reason


def test_low_confidence_not_authoritative():
    assert validate_mapping_evidence("semantic_similarity", 0.5)[0] is False


def test_high_confidence_inferred_authoritative_boundary():
    assert validate_mapping_evidence(METHOD_NORMALIZED_LABEL, 0.85)[0] is True
    assert validate_mapping_evidence(METHOD_NORMALIZED_LABEL, 0.849)[0] is False


# --- duplicate detection ---
def test_duplicate_detection_normalized():
    rows = [
        {"id": 1, "domain_id": 5, "name": "Fixture Topic A"},
        {"id": 2, "domain_id": 5, "name": "fixture  topic a"},
        {"id": 3, "domain_id": 6, "name": "Fixture Topic A"},  # different domain -> not a duplicate
    ]
    assert find_duplicate_names(rows, ("domain_id", "name")) == [[1, 2]]


def test_no_duplicates():
    rows = [{"id": 1, "domain_id": 5, "name": "A"}, {"id": 2, "domain_id": 5, "name": "B"}]
    assert find_duplicate_names(rows, ("domain_id", "name")) == []


# --- quality metrics + NULL vs zero ---
def test_quality_metrics_counts():
    m = compute_core_knowledge_quality_metrics(
        domains=[{"source_id": 1, "is_active": 1}, {"source_id": None, "is_active": 0}],
        topics=[{"source_id": 1, "is_active": 1}],
        subtopics=[],
        skill_mappings=[{"confidence": 0.9}, {"confidence": None}],
        curriculum_mappings=[{}],
    )
    assert m["domains_missing_provenance"] == 1
    assert m["inactive_domains"] == 1
    assert m["skill_mappings_with_confidence"] == 1
    assert m["skill_mappings_unassessed"] == 1


def test_null_confidence_counted_as_unassessed_not_zero():
    m = compute_core_knowledge_quality_metrics([], [], [], [{"confidence": None}, {"confidence": 0.0}], [])
    # 0.0 is a real (if poor) assessed confidence; None is unassessed. They must not be merged.
    assert m["skill_mappings_with_confidence"] == 1
    assert m["skill_mappings_unassessed"] == 1


def test_quality_metrics_empty():
    m = compute_core_knowledge_quality_metrics([], [], [], [], [])
    assert m["total_domains"] == 0 and m["total_skill_mappings"] == 0
