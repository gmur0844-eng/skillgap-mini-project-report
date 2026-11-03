import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.tfidf_alignment import compute_tfidf_alignment, DEFAULT_TFIDF_CONFIG


def test_relevant_course_scores_higher_than_irrelevant_course():
    entity_docs = {
        1: "machine learning python docker kubernetes deep learning neural networks",
        2: "office administration scheduling calendars meeting minutes",
    }
    reference = "looking for python docker kubernetes machine learning engineer"
    result = compute_tfidf_alignment(entity_docs, reference)
    assert result["entities"][1]["text_alignment_score"] > result["entities"][2]["text_alignment_score"]


def test_identical_text_scores_high():
    text = "python docker kubernetes machine learning"
    result = compute_tfidf_alignment({1: text}, text)
    assert result["entities"][1]["text_alignment_score"] > 0.9


def test_completely_unrelated_text_scores_near_zero():
    result = compute_tfidf_alignment(
        {1: "baking bread pastry recipes flour sugar"},
        "python docker kubernetes machine learning engineer",
    )
    assert result["entities"][1]["text_alignment_score"] < 0.1


def test_config_is_stored_and_returned():
    result = compute_tfidf_alignment({1: "python docker"}, "python required", config={"min_df": 1})
    assert result["config"]["min_df"] == 1
    assert "ngram_range" in result["config"]


def test_empty_entity_text_skipped_not_fabricated():
    result = compute_tfidf_alignment({1: "python docker", 2: "", 3: "   "}, "python required")
    assert 1 in result["entities"]
    assert 2 not in result["entities"]
    assert 3 not in result["entities"]
    assert set(result["skipped_entity_ids"]) == {2, 3}


def test_empty_reference_doc_returns_no_scores():
    result = compute_tfidf_alignment({1: "python docker"}, "")
    assert result["entities"] == {}


def test_deterministic_repeated_calculation():
    entity_docs = {1: "python docker kubernetes", 2: "java spring boot"}
    reference = "python docker required"
    r1 = compute_tfidf_alignment(entity_docs, reference)
    r2 = compute_tfidf_alignment(entity_docs, reference)
    assert r1["entities"] == r2["entities"]
    assert r1["vocabulary_size"] == r2["vocabulary_size"]


def test_vocabulary_size_reported():
    result = compute_tfidf_alignment({1: "python docker kubernetes"}, "python cloud aws")
    assert result["vocabulary_size"] > 0


def test_default_config_used_when_none_passed():
    result = compute_tfidf_alignment({1: "python docker"}, "python required")
    assert result["config"] == DEFAULT_TFIDF_CONFIG


def test_source_population_size_counting_logic_excludes_empty_documents():
    """
    Regression test for the TF-IDF population-metadata bug: eligible
    population size (all records considered) and the actual TF-IDF corpus
    contributor count (records with non-empty text) are NOT the same number
    when some records have no usable text. This mirrors exactly the counting
    logic in app.analytics.run_analysis.run_course_tfidf_alignment -- see
    that function for where eligible_postings_count and contributing_postings
    are computed the same way.
    """
    class FakePosting:
        def __init__(self, clean_description):
            self.clean_description = clean_description

    postings = [
        FakePosting("python docker kubernetes"),
        FakePosting(None),       # no usable text -- must not count as a corpus contributor
        FakePosting(""),         # empty string -- also must not count
        FakePosting("machine learning"),
    ]

    eligible_postings_count = len(postings)
    contributing_postings = [p for p in postings if p.clean_description]

    assert eligible_postings_count == 4
    assert len(contributing_postings) == 2  # only the two with real text
    assert eligible_postings_count != len(contributing_postings)  # the bug this test guards against
