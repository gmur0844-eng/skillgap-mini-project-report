"""
TF-IDF text alignment (spec Section 7). CALCULATED METRIC, not a causal
measure -- called `text_alignment_score` everywhere, deliberately never
"similarity implies alignment implies quality".

Deterministic: TfidfVectorizer with no randomness (no random_state needed --
it's a deterministic transform), same input always produces the same score.
Uses the project's existing cleaned text (JobPosting.clean_description,
curriculum topic/outcome text) rather than re-implementing preprocessing.
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DEFAULT_TFIDF_CONFIG = {"ngram_range": (1, 2), "min_df": 1, "stop_words": "english"}


def compute_tfidf_alignment(
    entity_docs: dict,
    reference_doc: str,
    config: dict | None = None,
) -> dict:
    """
    entity_docs: {entity_id: text} -- e.g. one concatenated text blob per
        course (topics + outcomes + title).
    reference_doc: the aggregate industry-side text this is compared against
        (e.g. all eligible job postings' clean_description, concatenated).
    config: TF-IDF vectorizer kwargs; defaults to DEFAULT_TFIDF_CONFIG so the
        exact configuration used is always known and stored (never silently
        changed between runs).

    Returns {"vocabulary_size": int, "config": dict,
             "reference_doc_length": int,
             "entities": {entity_id: {"text_alignment_score": float, "doc_length": int}}}

    Entities with empty/whitespace-only text are skipped (no fabricated score
    for a course with no extracted text) and listed under "skipped_entity_ids".
    """
    config = {**DEFAULT_TFIDF_CONFIG, **(config or {})}

    valid_entities = {eid: text for eid, text in entity_docs.items() if text and text.strip()}
    skipped_entity_ids = [eid for eid in entity_docs if eid not in valid_entities]

    if not valid_entities or not (reference_doc and reference_doc.strip()):
        return {
            "vocabulary_size": 0,
            "config": config,
            "reference_doc_length": len(reference_doc or ""),
            "entities": {},
            "skipped_entity_ids": skipped_entity_ids + (
                [] if (reference_doc and reference_doc.strip()) else ["__reference_doc_empty__"]
            ),
        }

    entity_ids = list(valid_entities.keys())
    corpus = [valid_entities[eid] for eid in entity_ids] + [reference_doc]

    vectorizer = TfidfVectorizer(**config)
    matrix = vectorizer.fit_transform(corpus)

    reference_vector = matrix[-1:]
    entity_vectors = matrix[:-1]
    similarities = cosine_similarity(entity_vectors, reference_vector).flatten()

    entities = {
        eid: {
            "text_alignment_score": round(float(sim), 4),
            "doc_length": len(valid_entities[eid]),
        }
        for eid, sim in zip(entity_ids, similarities)
    }

    return {
        "vocabulary_size": len(vectorizer.vocabulary_),
        "config": config,
        "reference_doc_length": len(reference_doc),
        "entities": entities,
        "skipped_entity_ids": skipped_entity_ids,
    }
