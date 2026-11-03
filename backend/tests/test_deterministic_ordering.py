"""Deterministic outputs must not depend on unspecified tie orders.

Regression for the Mac-vs-container release-candidate comparison (2026-10-09): three concept-family names, the row
order of exports/concepts.csv and four review-queue "related concepts" lists differed between two builds of the same
code and inputs. The causes were an argsort over tied TF-IDF weights, a CSV written in clustering order, and a top-six
cut taken in edge-emission order.
"""
import itertools
import sys
from pathlib import Path

import numpy as np
from scipy import sparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import review  # noqa: E402
from app.knowledge_engine.semantic_backend import TfidfBackend  # noqa: E402


class _Vocab:
    def __init__(self, names):
        self.names = np.array(names, dtype=object)

    def get_feature_names_out(self):
        return self.names


def _backend(names):
    b = TfidfBackend()
    b._vectorizer, b._fitted = _Vocab(names), True
    return b


def test_top_terms_breaks_ties_by_term_and_ignores_column_order():
    # weights: two clear leaders, then four terms tied at 0.5, then zeros (never named)
    terms = {"graph": 0.9, "tree": 0.7, "queue": 0.5, "heap": 0.5, "stack": 0.5, "array": 0.5, "zero": 0.0}
    expected = ["graph", "tree", "array", "heap"]          # descending weight, then ascending term
    seen = set()
    for perm in itertools.permutations(terms):              # every column order of the same vocabulary
        row = sparse.csr_matrix(np.array([[terms[t] for t in perm]]))
        got = _backend(list(perm)).top_terms(row, n=4)
        seen.add(tuple(got))
        assert got == expected, (perm, got)
    assert seen == {tuple(expected)}


def test_top_terms_ties_with_a_dense_mean_and_never_names_a_zero_weight_term():
    names = ["b", "a", "d", "c"]
    rows = sparse.csr_matrix(np.array([[1.0, 0.0, 0.0, 1.0], [0.0, 1.0, 0.0, 0.0]]))   # mean: b .5, a .5, d 0, c .5
    assert _backend(names).top_terms(rows, n=6) == ["a", "b", "c"]
    assert _backend(names).top_terms(sparse.csr_matrix((0, 4)), n=6) == []


def test_top_terms_on_a_fitted_vocabulary_is_stable_for_tied_weights():
    b = TfidfBackend().fit(["alpha beta gamma", "alpha beta gamma", "delta epsilon"])
    m = b.embed(["alpha beta gamma"])
    first = b.top_terms(m, n=3)
    assert first == sorted(first) and all(isinstance(t, str) for t in first)
    assert all(b.top_terms(m, n=3) == first for _ in range(5))


def test_review_queue_related_concepts_have_a_documented_order_before_the_top_six_cut():
    names = {f"u{i}": n for i, n in enumerate(["zeta", "eta", "beta", "alpha", "gamma", "delta", "omega", "kappa"])}
    pairs = [("CO_OCCURS_IN_UNIT", u) for u in names] + [("PARENT", "u7"), ("CO_OCCURS_IN_UNIT", "missing")]
    expected = review.related_in_order(pairs, names)
    for seed in range(20):                                   # edge emission order must not matter
        shuffled = list(pairs)
        np.random.default_rng(seed).shuffle(shuffled)
        assert review.related_in_order(shuffled, names) == expected
    assert [names.get(u) for _, u in expected[:6]] == ["alpha", "beta", "delta", "eta", "gamma", "kappa"]
    assert expected[-2] == ("CO_OCCURS_IN_UNIT", "missing") and expected[-1] == ("PARENT", "u7")


def test_review_queue_uses_the_documented_order():
    src = Path(review.__file__).read_text()
    assert "related_in_order(related.get(c[\"concept_uid\"], []), names)[:6]" in src


def test_concepts_export_is_written_in_concept_uid_order():
    from app.knowledge_engine import pipeline
    src = Path(pipeline.__file__).read_text()
    assert 'write_csv(g / "exports/concepts.csv", sorted(concepts, key=lambda c: c["concept_uid"])' in src


def test_run_report_records_the_numeric_environment():
    from app.knowledge_engine.pipeline import numeric_environment
    env = numeric_environment()
    for k in ("python", "platform", "numpy", "scipy", "sklearn", "blas", "numpy_blas_build"):
        assert k in env
    assert env["numpy"] == np.__version__


def test_peer_candidate_top_k_breaks_similarity_ties_by_topic_order():
    """Repeated peer topic texts ("Introduction") give equal similarities; which of them enter the top_k candidates
    must not depend on the NumPy build's sort (the Mac and the container chose different ones)."""
    from app.knowledge_engine import peer_stage
    src = Path(peer_stage.__file__).read_text()
    assert 'np.argsort(-row, kind="stable")[: cfg["top_k"]]' in src
    row = np.array([0.4, 0.9, 0.4, 0.4, 0.9, 0.1, 0.4] * 50)
    top = np.argsort(-row, kind="stable")[:3]
    assert list(top) == [1, 4, 8]


def test_recommendations_export_does_not_follow_run_derived_ids():
    from app.knowledge_engine import pipeline
    src = Path(pipeline.__file__).read_text()
    assert ('sorted(ig["recommendations"], key=lambda r: r["skill_key"])\n'
            '              + sorted(ig["suppressions"], key=lambda r: r["skill_key"])') in src


def test_top_terms_partial_selection_equals_the_full_sort():
    """top_terms sorts only the candidates at or above the n-th largest weight; the answer must equal the full
    (-weight, term) sort, including ties straddling the cut and n larger than the vocabulary."""
    rng = np.random.default_rng(11)
    for trial in range(200):
        size = int(rng.integers(1, 40))
        names = [f"t{int(x):03d}" for x in rng.permutation(size)]
        weights = rng.choice([0.0, 0.1, 0.2, 0.2, 0.3, 0.5], size=size)       # many exact ties and zeros
        row = sparse.csr_matrix(weights.reshape(1, -1))
        b = _backend(names)
        for n in (1, 2, 4, 6, size, size + 3):
            full = [names[i] for i in sorted((i for i in range(size) if weights[i] > 0),
                                             key=lambda i: (-weights[i], names[i]))][:n]
            assert b.top_terms(row, n=n) == full, (trial, n)
    assert _backend(["a", "b"]).top_terms(sparse.csr_matrix(np.array([[0.5, 0.5]])), n=0) == []
