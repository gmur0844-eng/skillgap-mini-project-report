"""
Replaceable semantic backend.

Every similarity computation in the engine goes through a SemanticBackend:

    backend.fit(corpus_texts)          -> learn vocabulary / load model
    backend.embed(texts)               -> row-normalised matrix (numpy or scipy)
    backend.similarity(A, B)           -> cosine matrix in [0, 1]
    backend.describe()                 -> name, version, parameters (for provenance)

Available here:
  "tfidf"                 IMPLEMENTED. Classical term statistics (word 1-2 grams,
                          sublinear tf, light suffix stemming, stop-words removed).
                          It measures SHARED VOCABULARY, not meaning: it cannot
                          recognise a paraphrase with no words in common and it
                          cannot tell two senses of the same word apart.

Optional (each raises BackendUnavailable with the concrete reason when it
cannot run, so a run records WHY it fell back instead of silently pretending):
  "sentence_transformer"  local open-source embedding model. Needs the optional
                          package (backend/requirements-embedding.txt) and a model
                          downloaded with scripts/semantic/fetch_embedding_model.py
                          (with PROVENANCE.json). Never the default: a run uses it
                          only when its configuration asks for it.
  "api_embedding"         hosted embedding API (needs an API key in the environment)

Swapping in a real embedding model = implementing embed()/describe() in a
new class and adding it to _REGISTRY; no caller changes.
"""
import importlib.util
import os
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from app.analytics.concept_semantic_matching import _stemming_tokenizer


class BackendUnavailable(RuntimeError):
    pass


class TfidfBackend:
    name = "tfidf"
    version = "1"

    def __init__(self, ngram_range=(1, 2), min_df=1, sublinear_tf=True):
        self.params = {"ngram_range": list(ngram_range), "min_df": min_df, "sublinear_tf": sublinear_tf,
                       "tokenizer": "concept_semantic_matching._stemming_tokenizer (suffix-strip + stop-words)"}
        self._vectorizer = TfidfVectorizer(tokenizer=_stemming_tokenizer, token_pattern=None, lowercase=True,
                                           ngram_range=ngram_range, min_df=min_df, sublinear_tf=sublinear_tf)
        self._fitted = False

    def fit(self, corpus_texts):
        texts = [t for t in corpus_texts if t and t.strip()]
        if not texts:
            raise ValueError("cannot fit a semantic backend on an empty corpus")
        self._vectorizer.fit(texts)
        self._fitted = True
        return self

    def embed(self, texts):
        if not self._fitted:
            raise RuntimeError("TfidfBackend.embed called before fit()")
        return normalize(self._vectorizer.transform(list(texts)))

    def similarity(self, a, b):
        sims = (a @ b.T)
        sims = sims.toarray() if hasattr(sims, "toarray") else np.asarray(sims)
        return np.clip(sims, 0.0, 1.0)

    def top_terms(self, matrix_rows, n=6):
        """Most heavily weighted terms of the mean of the given rows (used to
        NAME families -- purely descriptive)."""
        if matrix_rows.shape[0] == 0:
            return []
        mean = np.asarray(matrix_rows.mean(axis=0)).ravel()
        names = self._vectorizer.get_feature_names_out()
        # descending weight, then ascending term: equal weights never fall back on argsort's unspecified tie order.
        # Only terms weighing at least the n-th largest weight can be among the first n, so only they are sorted.
        positive = np.flatnonzero(mean > 0)
        if 0 < n < positive.size:
            cut = np.partition(mean[positive], positive.size - n)[positive.size - n]
            positive = positive[mean[positive] >= cut]
        order = sorted(positive, key=lambda i: (-mean[i], names[i]))
        return [str(names[i]) for i in order[:n]]

    def describe(self):
        return {"name": self.name, "version": self.version, "params": self.params,
                "vocabulary_size": len(self._vectorizer.vocabulary_) if self._fitted else None,
                "similarity": "cosine on L2-normalised TF-IDF vectors",
                "semantic_capability": "lexical overlap only -- not meaning-based"}


# ---------------------------------------------------------------- embedding backends
#
# An embedding backend = an encoder (list[str] -> float matrix) + a model id + a
# configuration. Vectors are cached per (model id, configuration hash, text hash)
# so an unchanged text is never re-embedded. Contextual input is built by
# contextual_input(): the text is embedded together with its document / course /
# unit / neighbouring-topic context, never as an isolated word, and with no
# subject assumptions (context is whatever metadata the record carries).


def contextual_input(text, context=None):
    """'discipline | document | course | unit | text | neighbours: a; b' -- only the parts present."""
    context = context or {}
    parts = [context.get(k) for k in ("discipline", "document", "course", "unit")]
    parts = [p for p in parts if p]
    neighbours = [n for n in context.get("neighbours", []) if n and n != text][:6]
    body = " | ".join(parts + [text])
    return body + (f" | neighbours: {'; '.join(neighbours)}" if neighbours else "")


class EmbeddingCache:
    def __init__(self, root, model_id, config_hash):
        import hashlib
        self._h = hashlib
        self.path = Path(root) / f"{_safe(model_id)}.{config_hash[:16]}.npz"
        self.vectors = {}
        if self.path.exists():
            try:
                with np.load(self.path) as data:
                    self.vectors = {k: data[k] for k in data.files}
            except (OSError, ValueError):
                self.vectors = {}  # an unreadable cache only costs time
        self.hits = self.misses = 0

    def key(self, text):
        return self._h.sha256(text.encode("utf-8")).hexdigest()

    def get_or_compute(self, texts, encoder):
        keys = [self.key(t) for t in texts]
        self.hits += sum(1 for k in keys if k in self.vectors)
        missing = {}
        for k, t in zip(keys, texts):
            if k not in self.vectors and k not in missing:
                missing[k] = t
        if missing:
            self.misses += len(missing)
            order = sorted(missing)
            vectors = np.asarray(encoder([missing[k] for k in order]), dtype=np.float32)
            for k, v in zip(order, vectors):
                self.vectors[k] = v
        return np.vstack([self.vectors[k] for k in keys])

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.stem}.{os.getpid()}.tmp.npz")
        np.savez(tmp, **self.vectors)
        os.replace(tmp, self.path)
        return self.path.stat().st_size


def _safe(name):
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)


class EmbeddingBackend:
    """Any sentence-embedding encoder behind the same interface as TfidfBackend."""
    name = "embedding"

    def __init__(self, encoder, model_id, model_version, config, cache_root=None):
        import hashlib
        import json
        self.encoder, self.model_id, self.model_version, self.config = encoder, model_id, model_version, dict(config)
        self.config_hash = hashlib.sha256(json.dumps(self.config, sort_keys=True).encode()).hexdigest()
        self.cache = EmbeddingCache(cache_root, model_id, self.config_hash) if cache_root else None

    def fit(self, corpus_texts):
        return self  # pre-trained model: nothing is learnt from the corpus

    def embed(self, texts):
        texts = list(texts)
        if not self.cache:
            return normalize(np.asarray(self.encoder(texts), dtype=np.float32))
        before = self.cache.misses
        vectors = self.cache.get_or_compute(texts, self.encoder)
        if self.cache.misses > before:
            try:
                self.cache.save()
            except OSError:
                pass  # an unwritable cache only costs time
        return normalize(vectors)

    def similarity(self, a, b):
        return np.clip(np.asarray(a) @ np.asarray(b).T, 0.0, 1.0)

    def describe(self):
        return {"name": self.name, "model_id": self.model_id, "model_version": self.model_version, "config": self.config,
                "config_hash": self.config_hash, "similarity": "cosine on L2-normalised embeddings",
                "semantic_capability": "embedding-based semantic similarity (uncalibrated; not confidence)"}


REPO = Path(__file__).resolve().parents[3]
DEFAULT_MODEL_DIR = REPO / "data/models/embedding/all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_CACHE = REPO / "data/cache/embeddings"
_LOADED = {}  # model directory -> (model, provenance); one load per process


def model_provenance(model_dir):
    """PROVENANCE.json written by scripts/semantic/fetch_embedding_model.py (repo id, resolved revision, licence,
    sha256 of every file). A model directory without it is not used: its identity could not be recorded."""
    import json
    try:
        prov = json.loads((Path(model_dir) / "PROVENANCE.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return prov if isinstance(prov, dict) and prov.get("files_sha256") and prov.get("revision") else None


def _probe_sentence_transformer(model_dir=None, cache_root=None, probe_only=False, **_):
    """Available only when the package is installed AND a downloaded model with provenance is present. The engine's
    default backend stays "tfidf" (engine_config.json); this one is used only when a run asks for it, and then the
    model's repo id, revision and file hashes enter the run's configuration and identity."""
    model_dir = Path(model_dir or os.environ.get("EMBEDDING_MODEL_DIR") or DEFAULT_MODEL_DIR)
    if importlib.util.find_spec("sentence_transformers") is None:
        raise BackendUnavailable("package 'sentence_transformers' is not installed (optional: "
                                 "pip install -r backend/requirements-embedding.txt)")
    if not model_dir.exists():
        raise BackendUnavailable(f"no local embedding model at {model_dir} "
                                 "(download it with scripts/semantic/fetch_embedding_model.py)")
    prov = model_provenance(model_dir)
    if prov is None:
        raise BackendUnavailable(f"{model_dir} has no valid PROVENANCE.json, so the model's identity cannot be "
                                 "recorded; re-run scripts/semantic/fetch_embedding_model.py")
    if probe_only:
        return None  # available; not loaded (reporting availability never loads a model)
    key = str(model_dir.resolve())
    if key not in _LOADED:
        from sentence_transformers import SentenceTransformer  # pragma: no cover - needs the optional package
        _LOADED[key] = SentenceTransformer(str(model_dir), device="cpu")
    model = _LOADED[key]
    weights = sorted(prov["files_sha256"].items())
    config = {"normalize": True, "repo_id": prov.get("repo_id"), "revision": prov["revision"],
              "files_sha256": dict(weights)}
    return EmbeddingBackend(lambda texts: model.encode(list(texts), normalize_embeddings=True, batch_size=64,
                                                       show_progress_bar=False),
                            prov.get("repo_id") or model_dir.name, prov["revision"], config,
                            cache_root or os.environ.get("EMBEDDING_CACHE_DIR") or DEFAULT_EMBEDDING_CACHE)


def _probe_onnx_embedding(model_dir=None, **_):
    if importlib.util.find_spec("onnxruntime") is None:
        raise BackendUnavailable("onnxruntime is not installed")
    if importlib.util.find_spec("tokenizers") is None:
        raise BackendUnavailable("onnxruntime is installed but the 'tokenizers' package is not, and no local "
                                 "sentence-embedding ONNX model is present (only unrelated ONNX files ship with other packages)")
    if not model_dir or not Path(model_dir).exists():
        raise BackendUnavailable("no local ONNX sentence-embedding model directory configured")
    raise BackendUnavailable("onnx embedding loader not implemented for this model layout")


def _probe_api_embedding(**_):
    if not os.environ.get("EMBEDDING_API_KEY"):
        raise BackendUnavailable("EMBEDDING_API_KEY is not set")
    raise BackendUnavailable("api_embedding backend is registered but not implemented")


_REGISTRY = {
    "tfidf": lambda **kw: TfidfBackend(**kw),
    "sentence_transformer": _probe_sentence_transformer,
    "onnx_embedding": _probe_onnx_embedding,
    "api_embedding": _probe_api_embedding,
}


def get_backend(name="tfidf", fallback="tfidf", **kwargs):
    """
    Returns (backend, resolution) where resolution records what was requested,
    what was actually used and why -- stored in the run manifest.
    """
    resolution = {"requested": name, "used": None, "fallback_reason": None}
    try:
        backend = _REGISTRY[name](**kwargs)
        resolution["used"] = name
        return backend, resolution
    except KeyError:
        resolution["fallback_reason"] = f"unknown backend '{name}'"
    except BackendUnavailable as exc:
        resolution["fallback_reason"] = str(exc)
    if fallback is None:
        raise BackendUnavailable(resolution["fallback_reason"])
    backend = _REGISTRY[fallback]()
    resolution["used"] = fallback
    return backend, resolution


def available_backends():
    status = {}
    for name, factory in _REGISTRY.items():
        try:
            factory() if name == "tfidf" else factory(probe_only=True)
            status[name] = "AVAILABLE"
        except BackendUnavailable as exc:
            status[name] = f"UNAVAILABLE: {exc}"
    return status
