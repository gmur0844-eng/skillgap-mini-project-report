import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.corpus_clustering import (
    build_topic_corpus,
    cluster_topics,
    summarize_clusters,
    filter_multi_document_clusters,
)


def _record(course_code, module, text, page):
    return {"course_code": course_code, "module_heading_label": module, "topic_text": text, "page_number": page}


def test_build_topic_corpus_preserves_provenance():
    records = [_record("CS101", "Unit I", "Deadlock prevention and avoidance", 42)]
    corpus = build_topic_corpus(records, source_document="Test Document")
    assert corpus[0]["course_code"] == "CS101"
    assert corpus[0]["module_heading"] == "Unit I"
    assert corpus[0]["page_number"] == 42
    assert corpus[0]["source_document"] == "Test Document"


def test_build_topic_corpus_excludes_short_noise_fragments():
    records = [_record("CS101", "Unit I", "and", 1), _record("CS101", "Unit I", "Deadlock management strategies", 2)]
    corpus = build_topic_corpus(records, source_document="Test", min_length=8)
    assert len(corpus) == 1
    assert corpus[0]["text"] == "Deadlock management strategies"


def test_build_topic_corpus_handles_missing_text():
    records = [_record("CS101", "Unit I", "", 1), _record("CS101", "Unit I", None, 2)]
    corpus = build_topic_corpus(records, source_document="Test")
    assert corpus == []


def test_cluster_topics_raises_on_corpus_smaller_than_k():
    corpus = build_topic_corpus([_record("CS101", "U1", "Deadlock prevention", 1)], "Test")
    try:
        cluster_topics(corpus, n_clusters=10)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_cluster_topics_groups_similar_fragments_together():
    records = [
        _record("CS101", "U1", "Deadlock prevention techniques", 1),
        _record("CS101", "U1", "Deadlock avoidance methods", 2),
        _record("CS101", "U1", "Deadlock detection algorithms", 3),
        _record("CS102", "U2", "Sorting algorithms merge sort", 4),
        _record("CS102", "U2", "Sorting algorithms quick sort", 5),
        _record("CS102", "U2", "Sorting algorithms bubble sort", 6),
    ]
    corpus = build_topic_corpus(records, "Test")
    labels, vectorizer, matrix = cluster_topics(corpus, n_clusters=2)
    # the three deadlock fragments should cluster together, separately from the three sorting fragments
    deadlock_labels = {labels[i] for i in range(3)}
    sorting_labels = {labels[i] for i in range(3, 6)}
    assert len(deadlock_labels) == 1
    assert len(sorting_labels) == 1
    assert deadlock_labels != sorting_labels


def test_cluster_topics_deterministic():
    records = [_record("CS101", "U1", f"Topic number {i} about algorithms", i) for i in range(6)]
    corpus = build_topic_corpus(records, "Test")
    labels1, _, _ = cluster_topics(corpus, n_clusters=2)
    labels2, _, _ = cluster_topics(corpus, n_clusters=2)
    assert list(labels1) == list(labels2)


def test_summarize_clusters_includes_full_provenance():
    records = [
        _record("CS101", "U1", "Deadlock prevention techniques", 10),
        _record("CS102", "U2", "Sorting algorithms merge sort", 20),
    ]
    corpus = build_topic_corpus(records, "Test Doc")
    labels, vectorizer, matrix = cluster_topics(corpus, n_clusters=2)
    summaries = summarize_clusters(corpus, labels, vectorizer, matrix)
    assert len(summaries) == 2
    for s in summaries:
        assert "representative_terms" in s
        assert len(s["examples"]) >= 1
        assert "page_number" in s["examples"][0]
        assert "course_code" in s["examples"][0]


def test_summarize_clusters_sorted_by_size_descending():
    records = (
        [_record("CS101", "U1", "Deadlock prevention topic A", i) for i in range(5)]
        + [_record("CS102", "U2", "Sorting algorithm topic B", i) for i in range(2)]
    )
    corpus = build_topic_corpus(records, "Test")
    labels, vectorizer, matrix = cluster_topics(corpus, n_clusters=2)
    summaries = summarize_clusters(corpus, labels, vectorizer, matrix)
    assert summaries[0]["size"] >= summaries[1]["size"]


def test_filter_multi_document_clusters():
    summaries = [
        {"cluster_id": 1, "all_source_documents": ["AICTE"]},
        {"cluster_id": 2, "all_source_documents": ["AICTE", "CBIT"]},
    ]
    filtered = filter_multi_document_clusters(summaries)
    assert len(filtered) == 1
    assert filtered[0]["cluster_id"] == 2


def test_never_auto_promotes_clusters_to_concepts():
    """Structural guard: this module's public API has no 'promote' or
    'accept' function -- clustering output is always a review artifact."""
    import app.analytics.corpus_clustering as module
    public_names = [n for n in dir(module) if not n.startswith("_")]
    assert not any("promote" in n.lower() or "accept" in n.lower() for n in public_names)
