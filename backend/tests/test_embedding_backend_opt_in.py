"""
The local embedding backend is optional and never the default: it is used only when the package AND a downloaded model
with provenance are present, it records the model's revision and file hashes, and its vectors are cached on disk.
A stand-in `sentence_transformers` module is used, so no model is downloaded or run here.
"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import semantic_backend as sb  # noqa: E402
from app.knowledge_engine.config import load_config  # noqa: E402

PROV = {"repo_id": "sentence-transformers/all-MiniLM-L6-v2", "revision": "abc123", "licence": "apache-2.0",
        "files_sha256": {"model.safetensors": "f" * 64, "config.json": "c" * 64}}


class FakeModel:
    calls = 0

    def __init__(self, path, device=None):
        self.path = path

    def encode(self, texts, normalize_embeddings=True, **_):
        FakeModel.calls += 1
        return np.array([[len(t), 1.0, 0.0] for t in texts], dtype=np.float32)


def fake_package():
    return mock.patch.dict(sys.modules, {"sentence_transformers": types.SimpleNamespace(SentenceTransformer=FakeModel)})


class OptIn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.model = Path(self.tmp.name) / "model"
        self.cache = Path(self.tmp.name) / "cache"
        sb._LOADED.clear()
        FakeModel.calls = 0

    def tearDown(self):
        sb._LOADED.clear()
        self.tmp.cleanup()

    def installed(self):
        real = sb.importlib.util.find_spec
        return mock.patch.object(sb.importlib.util, "find_spec",
                                 lambda name, *a: object() if name == "sentence_transformers" else real(name, *a))

    def test_the_default_backend_is_tfidf(self):
        self.assertEqual(load_config()["semantic_backend"], "tfidf")

    def test_without_the_model_it_falls_back_and_says_why(self):
        with self.installed(), fake_package():
            _, res = sb.get_backend("sentence_transformer", model_dir=self.model)
        self.assertEqual(res["used"], "tfidf")
        self.assertIn("no local embedding model", res["fallback_reason"])

    def test_a_model_without_provenance_is_not_used(self):
        self.model.mkdir()
        with self.installed(), fake_package():
            _, res = sb.get_backend("sentence_transformer", model_dir=self.model)
        self.assertEqual(res["used"], "tfidf")
        self.assertIn("PROVENANCE.json", res["fallback_reason"])

    def test_with_model_and_provenance_it_records_the_model_identity_and_caches_vectors(self):
        self.model.mkdir()
        (self.model / "PROVENANCE.json").write_text(json.dumps(PROV))
        with self.installed(), fake_package():
            backend, res = sb.get_backend("sentence_transformer", model_dir=self.model, cache_root=self.cache)
        self.assertEqual(res["used"], "sentence_transformer")
        d = backend.describe()
        self.assertEqual((d["model_id"], d["model_version"]), (PROV["repo_id"], "abc123"))
        self.assertEqual(d["config"]["files_sha256"], PROV["files_sha256"])
        first = backend.embed(["sql", "joins"])
        self.assertEqual(FakeModel.calls, 1)
        self.assertTrue(list(self.cache.glob("*.npz")))
        with self.installed(), fake_package():
            again, _ = sb.get_backend("sentence_transformer", model_dir=self.model, cache_root=self.cache)
        second = again.embed(["joins", "sql"])  # a new backend instance reads the saved vectors: no model call
        self.assertEqual(FakeModel.calls, 1)
        np.testing.assert_array_equal(first, second[::-1])
        self.assertEqual(len(sb._LOADED), 1)  # one model load per process

    def test_reporting_availability_does_not_load_the_model(self):
        self.model.mkdir()
        (self.model / "PROVENANCE.json").write_text(json.dumps(PROV))
        with self.installed(), fake_package(), mock.patch.object(sb, "DEFAULT_MODEL_DIR", self.model):
            status = sb.available_backends()
        self.assertEqual(status["sentence_transformer"], "AVAILABLE")
        self.assertEqual(sb._LOADED, {})

    def test_another_revision_gets_another_cache_file(self):
        self.model.mkdir()
        (self.model / "PROVENANCE.json").write_text(json.dumps(PROV))
        with self.installed(), fake_package():
            a, _ = sb.get_backend("sentence_transformer", model_dir=self.model, cache_root=self.cache)
            (self.model / "PROVENANCE.json").write_text(json.dumps({**PROV, "revision": "def456"}))
            b, _ = sb.get_backend("sentence_transformer", model_dir=self.model, cache_root=self.cache)
        self.assertNotEqual(a.cache.path, b.cache.path)

    def test_a_corrupt_cache_file_is_ignored(self):
        self.model.mkdir()
        (self.model / "PROVENANCE.json").write_text(json.dumps(PROV))
        with self.installed(), fake_package():
            b, _ = sb.get_backend("sentence_transformer", model_dir=self.model, cache_root=self.cache)
            self.cache.mkdir(parents=True, exist_ok=True)
            b.cache.path.write_bytes(b"broken")
            c, _ = sb.get_backend("sentence_transformer", model_dir=self.model, cache_root=self.cache)
            self.assertEqual(c.embed(["x"]).shape, (1, 3))


if __name__ == "__main__":
    unittest.main()
