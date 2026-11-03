"""
Corpus-wide clustering for bottom-up concept discovery (Steps 3-4 of the
design). Groups real, extracted topic fragments (from BOTH AICTE and CBIT)
by statistical similarity, independent of whether a matching AICTE
reference concept already exists -- this is what lets genuinely new
concepts emerge from evidence rather than being forced into the current
29-item reference.

HONEST SCOPE: this uses TF-IDF + KMeans (scikit-learn, already a project
dependency) -- classical statistical clustering over shared vocabulary, not
meaning-based clustering. Two topics can end up in different clusters
despite being conceptually related if they share no vocabulary (the same
limitation documented for concept_semantic_matching.py). Clusters are
CANDIDATES for human review, never automatically promoted to canonical
concepts -- see docs/semantic_concept_matching.md and the review-queue
artifact this module produces.
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans

from app.analytics.concept_semantic_matching import _stemming_tokenizer


def build_topic_corpus(records, source_document, min_length=8):
    """
    records: [{"course_code", "module_heading_label", "topic_text", "page_number"}, ...]
        -- from a real CurriculumStructure's .topics list.
    source_document: a label for provenance.
    min_length: fragments shorter than this (characters) are excluded from
        clustering -- almost always noise, not real topics; not discarded
        from provenance, just not clustered.
    """
    corpus = []
    for r in records:
        text = r["topic_text"] if isinstance(r, dict) else r.topic_text
        if not text or len(text.strip()) < min_length:
            continue
        corpus.append({
            "text": text.strip(),
            "course_code": (r["course_code"] if isinstance(r, dict) else r.course_code),
            "module_heading": (r["module_heading_label"] if isinstance(r, dict) else r.module_heading_label),
            "page_number": (r["page_number"] if isinstance(r, dict) else r.page_number),
            "source_document": source_document,
        })
    return corpus


def cluster_topics(corpus, n_clusters=80, random_state=42):
    """
    n_clusters: a CONFIGURABLE exploration parameter, NOT empirically
        derived -- no labeled ground truth exists yet to tune this against.
    random_state: fixed for reproducibility.

    Returns (cluster_labels, vectorizer, matrix). Raises ValueError if the
    corpus is smaller than n_clusters (never silently reduces k).
    """
    if len(corpus) < n_clusters:
        raise ValueError(f"Corpus has {len(corpus)} entries, fewer than n_clusters={n_clusters}. Reduce n_clusters.")

    texts = [c["text"] for c in corpus]
    vectorizer = TfidfVectorizer(tokenizer=_stemming_tokenizer, token_pattern=None, lowercase=True, min_df=1)
    matrix = vectorizer.fit_transform(texts)

    km = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
    labels = km.fit_predict(matrix)
    return labels, vectorizer, matrix


def summarize_clusters(corpus, labels, vectorizer, matrix, top_terms=6, max_examples=5):
    """
    Builds the human-reviewable summary: for each cluster, its most
    distinctive terms and representative example topics WITH FULL
    PROVENANCE. Sorted by cluster size (largest first).
    """
    feature_names = vectorizer.get_feature_names_out()
    summaries = []

    for cluster_id in sorted(set(labels)):
        member_indices = [i for i, lbl in enumerate(labels) if lbl == cluster_id]
        if not member_indices:
            continue

        cluster_matrix = matrix[member_indices]
        mean_weights = cluster_matrix.mean(axis=0)
        mean_weights = mean_weights.A1 if hasattr(mean_weights, "A1") else mean_weights
        top_indices = mean_weights.argsort()[::-1][:top_terms]
        representative_terms = [feature_names[i] for i in top_indices if mean_weights[i] > 0]

        examples = [corpus[i] for i in member_indices[:max_examples]]
        source_docs = sorted({corpus[i]["source_document"] for i in member_indices})

        summaries.append({
            "cluster_id": int(cluster_id),
            "size": len(member_indices),
            "representative_terms": representative_terms,
            "examples": examples,
            "all_source_documents": source_docs,
        })

    summaries.sort(key=lambda s: -s["size"])
    return summaries


def filter_multi_document_clusters(cluster_summaries):
    """
    A cluster containing fragments from BOTH AICTE and CBIT is stronger
    evidence of a genuinely shared concept than one built entirely from a
    single document. Returns the subset with more than one source document
    -- a prioritization helper, not a claim that single-document clusters
    are worthless (they still appear in the full review list).
    """
    return [s for s in cluster_summaries if len(s["all_source_documents"]) > 1]
