"""
Lightweight semantic concept matching -- Stage 2/3 of the multi-stage
architecture, layered ON TOP of (never replacing) the existing deterministic
taxonomy in core_knowledge_mapping.py.

HONEST CAPABILITY STATEMENT (read this before using or extending this
module): this project's build environment has no PyTorch, no `transformers`,
no `sentence-transformers`, and no network access to download any embedding
or NLI model (HuggingFace itself returns 403 from this sandbox's egress
proxy -- verified directly, not assumed). This module therefore does NOT
implement true semantic/transformer embeddings, cross-encoders, or Natural
Language Inference, despite those being the ideal architecture. What it
DOES implement, using only scikit-learn (already a project dependency):

  Stage 2: TF-IDF + cosine similarity retrieval (classical statistical
           term-overlap, not meaning-based embeddings)
  Stage 3: a DETERMINISTIC, rule-based relationship classifier (token
           overlap + containment heuristics, NOT NLI-based reasoning)

This is a real, working, honestly-labeled approximation -- it can catch
cases sharing distinctive vocabulary (e.g. "deadlock", "normalization")
that exact/normalized matching misses, but it CANNOT reliably recognize a
pure paraphrase with no shared words, and it must never be described to a
user as "semantic understanding" in the deep-learning sense. See
docs/semantic_concept_matching.md for the full capability statement and
what would be needed to close this gap (network/model access).

MODEL ABSTRACTION (Step 4's requirement, honored even without a real
embedding model): `retrieve_candidate_concepts` takes a `vectorize_fn`
parameter (defaults to the TF-IDF implementation below) so a genuine
transformer-based embedder can be substituted later without changing any
caller or the result shape.
"""
import re
from functools import lru_cache
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# --- Relationship taxonomy (Step 6/11) ---
REL_SAME_CONCEPT = "SAME_CONCEPT"
REL_RELATED = "RELATED"
REL_PARENT = "PARENT"          # candidate is BROADER than the topic
REL_CHILD = "CHILD"            # candidate is NARROWER than the topic
REL_PARTIAL_OVERLAP = "PARTIAL_OVERLAP"
REL_UNRELATED = "UNRELATED"
REL_AMBIGUOUS = "AMBIGUOUS"
REL_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"

# Configurable, documented defaults -- NOT empirically calibrated against a
# labeled validation set (none exists yet; see Step 16's evaluation gap in
# docs/semantic_concept_matching.md). These are starting points only.
DEFAULT_MIN_SIMILARITY = 0.15   # below this, no candidate is retrieved at all -> INSUFFICIENT_EVIDENCE
DEFAULT_HIGH_SIMILARITY = 0.55  # at/above this + containment evidence -> higher-confidence relationship
DEFAULT_AMBIGUOUS_GAP = 0.05    # if top-2 candidates are within this of each other -> AMBIGUOUS

# Minimal, transparent, deterministic suffix-stripping (NOT a Porter
# stemmer, NOT nltk -- neither is installed and there is no network to
# fetch nltk's data files). Intentionally small and conservative: it only
# strips a handful of common English suffixes so morphological variants
# like "Searching"/"Search" or "Scheduling"/"Schedule" share a token,
# without attempting the full generality (and occasional wrongness) of a
# real stemmer.
_SUFFIX_RULES = [("ing", ""), ("tion", "t"), ("sion", "s"), ("ies", "y"), ("es", ""), ("s", "")]


@lru_cache(maxsize=None)
def _simple_stem(word):
    lower = word.lower()
    if len(lower) <= 4:
        return lower
    for suffix, replacement in _SUFFIX_RULES:
        if lower.endswith(suffix) and len(lower) - len(suffix) >= 3:
            return lower[: -len(suffix)] + replacement
    return lower


# Real bug found via honest real-data testing (not hypothetical): with such
# a small reference corpus (29 short course-level names), TF-IDF's own IDF
# weighting does not sufficiently downweight common connector words --
# "INDIAN CONSTITUTION AND FUNDAMENTAL PRINCIPLES" spuriously matched
# "Signals and Systems" at nonzero similarity purely because both contain
# "and". This stopword list is small, generic English function words --
# NOT a domain-specific or CBIT/AICTE-specific list.
_STOPWORDS = {
    "and", "or", "the", "a", "an", "of", "for", "to", "in", "on", "with",
    "using", "based", "including", "into", "as", "by", "is", "are", "at",
}


def _stemming_tokenizer(text):
    # the same texts are tokenised again by every TF-IDF fit and transform of a run (families, concepts, mapping,
    # peers, segments): their tokens are cached (a pure function of the text); a new list is returned each time
    return list(_stem_tokens(text))


@lru_cache(maxsize=200_000)
def _stem_tokens(text):
    words = re.findall(r"[A-Za-z]+", text)
    return tuple(_simple_stem(w) for w in words if len(w) > 2 and w.lower() not in _STOPWORDS)


def build_context_representation(
    topic_text,
    course_title=None,
    module_heading=None,
    previous_topics=None,
    next_topics=None,
    course_outcomes=None,
    programme=None,
    discipline=None,
):
    """
    Step 3: a topic is never interpreted in isolation. Pure data assembly --
    no ML. Returns a plain dict; every field is either the raw topic itself
    or real surrounding context the caller already has (course title,
    module heading, adjacent topics, outcomes) -- nothing here is inferred
    or fabricated.
    """
    return {
        "topic_text": topic_text,
        "course_title": course_title,
        "module_heading": module_heading,
        "previous_topics": list(previous_topics) if previous_topics else [],
        "next_topics": list(next_topics) if next_topics else [],
        "course_outcomes": list(course_outcomes) if course_outcomes else [],
        "programme": programme,
        "discipline": discipline,
    }


def _contextualized_text(context):
    """
    Builds the actual string handed to the retrieval stage: the topic text
    PLUS its course title (Step 3's example -- "Scheduling" under "Operating
    Systems" must retrieve differently than "Scheduling" under "Project
    Management"). This is a real, if simple, context-injection mechanism --
    not the deep contextual disambiguation a transformer encoder would give,
    but genuinely better than the bare topic string alone.
    """
    parts = [context["topic_text"]]
    if context.get("course_title"):
        parts.append(context["course_title"])
    if context.get("module_heading"):
        parts.append(context["module_heading"])
    return " ".join(parts)


def scope_concepts_to_domain(reference_concepts, domain):
    """
    Subject-agnostic isolation, enforced by DATA -- never by this module
    knowing which disciplines exist. A reference concept may carry an opaque
    "domain" value (any string/ID assigned upstream from real source
    metadata). When the query context names a discipline, only reference
    concepts carrying that SAME value are eligible, so a topic from one
    discipline is never even compared against another discipline's
    concepts, whatever vocabulary they share.

    domain=None means the caller supplied no discipline context: no
    filtering, an explicit and visible choice. Reference concepts WITHOUT a
    "domain" key are treated as unscoped legacy entries and stay eligible
    only in that domain=None case.
    """
    if domain is None:
        return list(reference_concepts)
    return [c for c in reference_concepts if c.get("domain") == domain]


def retrieve_candidate_concepts(context, reference_concepts, top_k=3, min_similarity=DEFAULT_MIN_SIMILARITY, vectorize_fn=None):
    """
    Stage 2. context: a dict from build_context_representation (or just
    {"topic_text": "..."} for the bare case). reference_concepts:
    [{"id": ..., "name": "...", "domain": optional}, ...]. When
    context["discipline"] is set, candidates are first restricted to that
    domain (scope_concepts_to_domain) before any similarity is computed.

    vectorize_fn: MODEL ABSTRACTION POINT (Step 4). Defaults to TF-IDF+cosine
    (below). A real embedding model would be substituted here later, taking
    the same (query_text, corpus_texts) -> similarity_scores signature.

    Returns candidates sorted by similarity, each:
    {"concept_id", "concept_name", "similarity", "method": "tfidf_cosine"}
    -- an EMPTY list (not a forced guess) when nothing clears min_similarity.
    """
    if not reference_concepts:
        return []

    reference_concepts = scope_concepts_to_domain(reference_concepts, context.get("discipline"))
    if not reference_concepts:
        return []

    query_text = _contextualized_text(context)
    corpus_texts = [c["name"] for c in reference_concepts]

    if vectorize_fn is not None:
        scores = vectorize_fn(query_text, corpus_texts)
    else:
        scores = _tfidf_cosine_scores(query_text, corpus_texts)

    ranked = sorted(zip(reference_concepts, scores), key=lambda pair: -pair[1])
    candidates = [
        {"concept_id": c["id"], "concept_name": c["name"], "similarity": round(float(sim), 4), "method": "tfidf_cosine"}
        for c, sim in ranked
        if sim >= min_similarity
    ]
    return candidates[:top_k]


def _tfidf_cosine_scores(query_text, corpus_texts):
    """The actual (non-transformer) default vectorizer: TF-IDF over the
    query + corpus together, with the minimal stemming tokenizer above."""
    documents = [query_text] + list(corpus_texts)
    vectorizer = TfidfVectorizer(tokenizer=_stemming_tokenizer, token_pattern=None, lowercase=True)
    try:
        matrix = vectorizer.fit_transform(documents)
    except ValueError:
        # Empty vocabulary (e.g. query_text and corpus share no tokens at
        # all after stemming) -- scikit-learn raises rather than returning
        # all-zero scores; treat this as "no similarity to anyone".
        return [0.0] * len(corpus_texts)
    query_vec = matrix[0:1]
    corpus_matrix = matrix[1:]
    sims = cosine_similarity(query_vec, corpus_matrix)[0]
    return list(sims)


def _token_containment(text_a, text_b):
    """
    Pure, deterministic token-overlap helper for relationship
    classification. Returns (shared_ratio_a, shared_ratio_b): what fraction
    of A's stemmed tokens appear in B, and vice versa. Used to distinguish
    PARENT/CHILD (asymmetric containment) from RELATED (partial, roughly
    symmetric overlap) -- NOT NLI-based entailment reasoning.
    """
    tokens_a = set(_stemming_tokenizer(text_a))
    tokens_b = set(_stemming_tokenizer(text_b))
    if not tokens_a or not tokens_b:
        return 0.0, 0.0
    shared = tokens_a & tokens_b
    return len(shared) / len(tokens_a), len(shared) / len(tokens_b)


def classify_relationship(context, candidates, high_similarity=DEFAULT_HIGH_SIMILARITY, ambiguous_gap=DEFAULT_AMBIGUOUS_GAP):
    """
    Stage 3/6 -- rule-based (NOT NLI) relationship classification.
    context: from build_context_representation. candidates: from
    retrieve_candidate_concepts (already sorted by similarity, already
    filtered by min_similarity).

    Returns a structured Concept Resolution (Step 5's shape):
    {
        "raw_topic", "normalized_topic", "canonical_concept" (best
        candidate name, or None), "relationship" (NOT a confidence -- see below), "similarity_score" (raw
        TF-IDF cosine from retrieval, 0.0 if none), "evidence_tier"
        (HIGH/MEDIUM/LOW -- a rule-derived tier, not a probability),
        "score_is_calibrated" (always False until a labelled benchmark
        large enough to calibrate against exists), "method", "evidence" (the full candidate list,
        never hidden), "review_required" (bool)
    }

    NEVER returns SAME_CONCEPT -- that status is reserved for the
    deterministic Stage 1 taxonomy (exact/normalized/etc.), which this
    function does not have access to and must not imitate. The strongest
    relationship this rule-based stage can respons‌ibly claim is RELATED.
    """
    topic_text = context["topic_text"]

    if not candidates:
        return {
            "raw_topic": topic_text, "normalized_topic": topic_text.strip().lower(),
            "canonical_concept": None, "relationship": REL_INSUFFICIENT_EVIDENCE,
            "similarity_score": 0.0, "evidence_tier": CONFIDENCE_LOW, "score_is_calibrated": False,
            "method": "tfidf_cosine", "evidence": [], "review_required": True,
        }

    top = candidates[0]
    if len(candidates) > 1 and (top["similarity"] - candidates[1]["similarity"]) < ambiguous_gap:
        return {
            "raw_topic": topic_text, "normalized_topic": topic_text.strip().lower(),
            "canonical_concept": None, "relationship": REL_AMBIGUOUS,
            "similarity_score": top["similarity"], "evidence_tier": CONFIDENCE_MEDIUM, "score_is_calibrated": False,
            "method": "tfidf_cosine", "evidence": candidates, "review_required": True,
        }

    ratio_topic_in_candidate, ratio_candidate_in_topic = _token_containment(topic_text, top["concept_name"])

    if top["similarity"] >= high_similarity:
        if ratio_candidate_in_topic >= 0.8 and ratio_topic_in_candidate < 0.5:
            # nearly all of the (short) candidate's tokens are inside the
            # (longer, more specific) topic text -> the topic is NARROWER
            relationship, tier = REL_CHILD, CONFIDENCE_MEDIUM
        elif ratio_topic_in_candidate >= 0.8 and ratio_candidate_in_topic < 0.5:
            relationship, tier = REL_PARENT, CONFIDENCE_MEDIUM
        else:
            relationship, tier = REL_RELATED, CONFIDENCE_MEDIUM
    else:
        relationship, tier = REL_PARTIAL_OVERLAP, CONFIDENCE_LOW

    return {
        "raw_topic": topic_text, "normalized_topic": topic_text.strip().lower(),
        "canonical_concept": top["concept_name"], "relationship": relationship,
        "similarity_score": top["similarity"], "evidence_tier": tier, "score_is_calibrated": False,
        "method": "tfidf_cosine+token_containment", "evidence": candidates,
        "review_required": tier != CONFIDENCE_HIGH,
    }


def resolve_concept(context, reference_concepts, deterministic_result=None, **kwargs):
    """
    Top-level entry point combining Stage 1 (deterministic, passed in by the
    caller from core_knowledge_mapping.match_text_to_core_topics) with
    Stage 2/3 (this module) as a FALLBACK only when Stage 1 found nothing.
    Stage 1 always wins when it has a result -- this function never
    second-guesses a real exact/normalized/abbreviation/synonym/compound
    match with a weaker statistical one.
    """
    if deterministic_result is not None and deterministic_result.get("status") in ("MATCHED", "COMPOUND"):
        return {
            "raw_topic": context["topic_text"], "normalized_topic": context["topic_text"].strip().lower(),
            "canonical_concept": None, "relationship": REL_SAME_CONCEPT,
            "similarity_score": None, "method_rank_score": deterministic_result.get("confidence", 1.0), "evidence_tier": CONFIDENCE_HIGH, "score_is_calibrated": False,
            "method": deterministic_result.get("method", "deterministic"), "evidence": [deterministic_result],
            "review_required": False, "stage": 1,
        }

    candidates = retrieve_candidate_concepts(context, reference_concepts, **kwargs)
    result = classify_relationship(context, candidates)
    result["stage"] = 2
    return result


def discover_concept(context, reference_concepts, min_similarity_for_known=DEFAULT_MIN_SIMILARITY):
    """
    Step 8: if a topic's best similarity to EVERY reference concept is
    below min_similarity_for_known, it is a genuine candidate for a NEW,
    not-yet-catalogued concept -- never forced into an unrelated existing
    one. Returns a "discovered concept" record if so, else None.
    """
    candidates = retrieve_candidate_concepts(context, reference_concepts, top_k=1, min_similarity=0.0)
    best_similarity = candidates[0]["similarity"] if candidates else 0.0
    if best_similarity < min_similarity_for_known:
        return {
            "raw_topic": context["topic_text"], "status": "NEW_DISCOVERED_UNMAPPED",
            "closest_known_concept": candidates[0]["concept_name"] if candidates else None,
            "closest_known_similarity": best_similarity,
            "similarity_score": 0.0, "review_required": True,
        }
    return None
