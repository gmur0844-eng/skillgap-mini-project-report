"""Phase 10: a LIVE semantic run can neither corrupt a hash-pinned recording, nor crash on an unwritable cache, nor be
served stale decisions of another model, nor overwrite the GOLD directory of a run made in another semantic mode.

Regression for the defect observed on the owner's Mac (2026-10-03): with Ollama reachable, the adjudicator appended
to the read-only, hash-pinned replay cache and the run died with PermissionError after 4.5 minutes of model calls.
"""
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.knowledge_engine import intelligence_stage as ist  # noqa: E402
from app.knowledge_engine import pipeline  # noqa: E402
from app.knowledge_engine import semantic_provider as sp  # noqa: E402
from test_semantic_v3 import E_L1, cand, out  # noqa: E402


class Live:
    name, kind = "ollama", "http"

    def __init__(self, digest=None):
        self.digest = digest

    def describe(self):
        d = {"provider": "ollama", "model": "m", "model_version": "m", "base_url": "u", "temperature": 0.0}
        if self.digest:
            d["model_digest"] = self.digest
        return d

    def complete(self, prompt, schema=None):
        return json.dumps(out("UNRELATED", [E_L1]))


def semantic_mode(value=None):
    """The test, not the caller's shell, decides SEMANTIC_MODE (rc_validation once exported it to the whole run)."""
    env = {k: v for k, v in os.environ.items() if k != "SEMANTIC_MODE"}
    if value is not None:
        env["SEMANTIC_MODE"] = value
    return mock.patch.dict(os.environ, env, clear=True)


def adj(d, provider, **kw):
    return sp.Adjudicator({"semantic_ai": {}}, d, "r", providers=[(provider, {"available": True})],
                          protocol=sp.v3_protocol(), **kw)


def test_pinned_recording_is_never_appended_to():
    with tempfile.TemporaryDirectory() as d:
        pinned = adj(d, Live()).cache_file
        pinned.write_text("")
        before = pinned.read_bytes()
        a = adj(d, Live(), pinned_files=[pinned])
        assert a.cache_file == pinned and a.readonly_cache
        a.decide(cand())
        assert pinned.read_bytes() == before


def test_unwritable_cache_never_fails_the_run():
    with tempfile.TemporaryDirectory() as d:
        a = adj(d, Live())
        a.cache_file.write_text("")
        os.chmod(a.cache_file, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        if os.access(a.cache_file, os.W_OK):     # running as a user that ignores permissions (root)
            a.cache_file = Path(d) / "missing-dir" / "x.jsonl"
        r = a.decide(cand())                      # previously: PermissionError
        assert r["decision_state"] and "cache_write_failed" in a.stats and a.readonly_cache


def test_model_digest_is_part_of_the_cache_key():
    with tempfile.TemporaryDirectory() as d:
        k1, k2, k0 = adj(d, Live("sha256:aaa")).model_key, adj(d, Live("sha256:bbb")).model_key, adj(d, Live()).model_key
        assert len({k1, k2, k0}) == 3


def test_ollama_probe_records_the_digest_and_unreachable_keeps_the_recorded_key():
    p = sp.OllamaProvider("http://127.0.0.1:9", "qwen")
    base = p.describe()
    assert "model_digest" not in base            # unreachable: the description replay relies on is unchanged

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "qwen", "digest": "sha256:abc"}]}).encode()

    with mock.patch("urllib.request.urlopen", return_value=R()):
        assert p.probe()["available"]
    assert p.describe()["model_digest"] == "sha256:abc"


def test_live_mode_uses_its_own_namespace_and_leaves_the_recording_untouched():
    repo = Path(tempfile.mkdtemp())
    rec = repo / "data/cache/semantic_decisions/ollama-x.jsonl"
    rec.parent.mkdir(parents=True)
    rec.write_text("")
    cfg = {"semantic_ai": {"prompt_version": "adjudicate-v3"},
           "semantic_replay": {"runs": [{"name": "r", "cache_file": str(rec.relative_to(repo))}]}}
    with semantic_mode(None), \
            mock.patch.object(sp, "discover_providers", return_value=[(Live("sha256:z"), {"available": True, "kind": "ollama"})]):
        a, info = ist.semantic_setup(cfg, repo)
    assert info["mode"] == "LIVE" and a.cache_file.parent.name == "live"
    a.decide(cand())
    assert rec.read_text() == "" and a.cache_file.exists()


def test_malformed_replay_entry_is_rejected_not_raised():
    """A registry entry without cache_file, gate_file or a required hash is an unverifiable recording: it is reported
    in replay_rejected and the run falls back, in every mode (previously KeyError: 'gate_file')."""
    repo = Path(tempfile.mkdtemp())
    rec = repo / "data/cache/semantic_decisions/ollama-x.jsonl"
    rec.parent.mkdir(parents=True)
    rec.write_text("")
    full = {"name": "r", "cache_file": str(rec.relative_to(repo)), "cache_sha256": "0" * 64,
            "gate_file": "data/cache/semantic_decisions/gate.json", "gate_sha256": "0" * 64,
            "prompt_version": "adjudicate-v3"}
    for field in ist.REPLAY_ENTRY_FIELDS:
        entry = {k: v for k, v in full.items() if k != field}
        cfg = {"semantic_ai": {"prompt_version": "adjudicate-v3"}, "semantic_replay": {"runs": [entry]}}
        for mode in (None, "replay"):
            with semantic_mode(mode), \
                    mock.patch.object(sp, "discover_providers", return_value=[(Live("sha256:z"), {"available": True, "kind": "ollama"})]):
                a, info = ist.semantic_setup(cfg, repo)
            if mode is None:
                assert info["mode"] == "LIVE"            # a live run never consults the replay registry
                continue
            assert info["mode"] == "DETERMINISTIC_FALLBACK", (field, info)
            assert info["replay_rejected"] == [{"run": "r", "reason": "hash, provider or protocol mismatch",
                                                "missing_fields": [field]}]
            assert rec.read_text() == ""


def test_semantic_identity_separates_runs_of_different_modes():
    with tempfile.TemporaryDirectory() as d:
        live = adj(d, Live("sha256:z"))
        fallback = sp.Adjudicator({"semantic_ai": {}}, d, "r", providers=[], protocol=sp.v3_protocol())
        ids = {ist.semantic_identity(live, {"mode": "LIVE"}),
               ist.semantic_identity(fallback, {"mode": "DETERMINISTIC_FALLBACK"}),
               ist.semantic_identity(adj(d, Live()), {"mode": "REPLAY_VERIFIED_RUN", "replay": {"cache_sha256": "h"}})}
        assert len(ids) == 3


def test_protected_release_is_never_regenerated_in_place():
    assert "c066b227857f9eaf" in pipeline.protected_runs()
    src = Path(pipeline.__file__).read_text()
    assert src.index("if run_id in protected_runs()") < src.index("shutil.rmtree(gold_dir)")
    assert src.index("semantic_identity(") < src.index("run_id = hashlib.sha256")
