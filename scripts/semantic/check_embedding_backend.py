"""
Smoke check of the optional embedding backend on this machine (not an evaluation: a handful of hand-picked pairs proves
only that the model loads through the engine's interface and returns sensible numbers).

    .venv/bin/python scripts/semantic/check_embedding_backend.py

Prints which backend the engine resolves for "sentence_transformer" (or why it falls back), the model identity it
records, load and encode times, and cosine similarities for a few pairs under TF-IDF and under the embedding model.
Writes nothing except the embedding vector cache (data/cache/embeddings/).
"""
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.knowledge_engine.semantic_backend import get_backend  # noqa: E402

PAIRS = [
    ("relational schema design", "database normalisation"),      # paraphrase, no shared words
    ("convolutional neural networks", "deep learning for images"),
    ("TCP congestion control", "transport layer protocols"),
    ("machine learning", "machine shop safety"),                  # shared word, different sense
    ("binary search trees", "employee payroll accounting"),       # unrelated
]


def scores(backend, pairs):
    texts = sorted({t for p in pairs for t in p})
    backend.fit(texts)
    m = backend.embed(texts)
    sim = backend.similarity(m, m)
    sim = sim.toarray() if hasattr(sim, "toarray") else sim
    idx = {t: i for i, t in enumerate(texts)}
    return [float(sim[idx[a], idx[b]]) for a, b in pairs]


def main():
    t0 = time.perf_counter()
    emb, res = get_backend("sentence_transformer", fallback="tfidf")
    load_s = time.perf_counter() - t0
    print("requested sentence_transformer -> used:", res["used"])
    if res["used"] != "sentence_transformer":
        print("reason:", res["fallback_reason"])
        return 1
    d = emb.describe()
    print(f"model: {d['model_id']} @ {d['model_version'][:12]}  (load {load_s:.1f} s)")
    tfidf, _ = get_backend("tfidf")
    t1 = time.perf_counter()
    e = scores(emb, PAIRS)
    enc_s = time.perf_counter() - t1
    t = scores(tfidf, PAIRS)
    print(f"encode {len(PAIRS) * 2} texts: {enc_s:.2f} s\n")
    print(f"{'pair':<66} {'tfidf':>6} {'model':>6}")
    for (a, b), x, y in zip(PAIRS, t, e):
        print(f"{a + '  ~  ' + b:<66} {x:6.2f} {y:6.2f}")
    print("\nTF-IDF stays the default; these numbers are not evidence of quality (see docs/TRANSFORMER_STRATEGY.md §5).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
