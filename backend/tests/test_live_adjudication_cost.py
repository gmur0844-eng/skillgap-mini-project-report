"""Regression for the R26 upload analysis (job-569cfd48c93f, run cb63f123f77a2a5c): industry.extract took 802 s, of
which 768 s were 78 sequential live calls to a local 7B model (~10 s each) whose decisions could not have any effect
(LIVE mode has no promotion gate). Another 238 candidates failed with "Connection refused", and those failures were
written to the live decision cache, so a later run would have served them instead of asking again.

Guards:
  * upload analyses run in replay mode by default (no live model calls); ANALYSIS_SEMANTIC_MODE=live opts in;
  * semantic_setup(mode="replay") never goes live, whatever the environment;
  * a transport failure is never persisted, and one persisted earlier is retried; a pinned recording is still served
    exactly as recorded; schema-invalid model output (a real model response) is still cached;
  * the label search used by the industry sense check gives identical answers to the original implementation.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import industry  # noqa: E402
from app.knowledge_engine import intelligence_stage as ist  # noqa: E402
from app.knowledge_engine import semantic_provider as sp  # noqa: E402
from app.pipelines.preprocessing.skill_extraction import LEFT_BOUNDARY, RIGHT_BOUNDARY  # noqa: E402
from app.services import analysis_jobs  # noqa: E402
from test_semantic_v3 import E_L1, cand, out  # noqa: E402


class Live:
    name, kind = "ollama", "http"

    def __init__(self, behaviour="ok"):
        self.behaviour, self.calls = behaviour, 0

    def describe(self):
        return {"provider": "ollama", "model": "m", "model_version": "m", "base_url": "u", "temperature": 0.0}

    def complete(self, prompt, schema=None):
        self.calls += 1
        if self.behaviour == "down":
            raise OSError("[Errno 61] Connection refused")
        if self.behaviour == "invalid":
            return "{not json"
        return json.dumps(out("UNRELATED", [E_L1]))


def adj(d, provider, **kw):
    return sp.Adjudicator({"semantic_ai": {}}, d, "r", providers=[(provider, {"available": True})],
                          protocol=sp.v3_protocol(), **kw)


def env(**values):
    base = {k: v for k, v in os.environ.items() if k not in ("SEMANTIC_MODE", "ANALYSIS_SEMANTIC_MODE")}
    return mock.patch.dict(os.environ, {**base, **values}, clear=True)


# ---------------------------------------------------------------- upload analyses never wait on a live model
def test_upload_analysis_defaults_to_replay_and_live_is_an_explicit_opt_in():
    with env():
        assert analysis_jobs.job_semantic_mode() == "replay"
    with env(ANALYSIS_SEMANTIC_MODE="live"):
        assert analysis_jobs.job_semantic_mode() is None          # the pipeline default: live when reachable
    seen = {}

    def fake_run(**kw):
        seen.update(kw)
        return {"run_id": "x"}

    with env(), mock.patch("app.knowledge_engine.pipeline.run", side_effect=fake_run):
        analysis_jobs._default_runner("ctx.json")
    # the progress listener (job progress events) is passed through; it never affects results
    assert seen == {"manifest_path": "ctx.json", "set_latest": False, "semantic_mode": "replay", "progress": None}


def test_replay_mode_argument_never_calls_a_reachable_model():
    live = Live()
    repo = Path(tempfile.mkdtemp())
    cfg = {"semantic_ai": {"prompt_version": "adjudicate-v3"}, "semantic_replay": {"runs": []}}
    with env(), mock.patch.object(sp, "discover_providers", return_value=[(live, {"available": True, "kind": "ollama"})]):
        a, info = ist.semantic_setup(cfg, repo, mode="replay")
        a.decide(cand())
        a_live, info_live = ist.semantic_setup(cfg, repo)        # no argument, no environment: unchanged default
    assert info["mode"] != "LIVE" and info["live_disabled"] == "semantic_mode=replay" and live.calls == 0
    assert info_live["mode"] == "LIVE"


def test_pipeline_passes_the_semantic_mode_through():
    from app.knowledge_engine import pipeline
    src = Path(pipeline.__file__).read_text()
    assert "semantic_setup(cfg, REPO, mode=semantic_mode)" in src


# ---------------------------------------------------------------- transient failures are not decisions
def test_a_transport_failure_is_not_persisted_and_is_retried_next_run():
    with tempfile.TemporaryDirectory() as d:
        down = Live("down")
        a = adj(d, down)
        r = a.decide(cand())
        assert r["decision_state"] == "MODEL_FAILURE" and down.calls == 3        # max_retries 2 -> 3 attempts
        assert a.decide(cand())["from_cache"] and down.calls == 3                # not hammered again in this run
        assert not a.cache_file.exists() or a.cache_file.read_text() == ""      # nothing persisted
        up = Live("ok")
        b = adj(d, up)
        r2 = b.decide(cand())
        assert r2["decision_state"] == "MODEL_SUGGESTED" and up.calls == 1 and not r2["from_cache"]
        assert adj(d, Live("ok")).decide(cand())["from_cache"]                   # a real decision is cached


def test_a_failure_persisted_by_earlier_code_is_ignored_in_a_writable_cache_but_served_from_a_recording():
    with tempfile.TemporaryDirectory() as d:
        a = adj(d, Live("down"))
        rec = a.decide(cand())
        stale = {k: v for k, v in rec.items() if k != "from_cache"}
        a.cache_file.write_text(json.dumps(stale) + "\n")                      # as the R26 live cache holds
        up = Live("ok")
        r = adj(d, up).decide(cand())
        assert up.calls == 1 and r["decision_state"] == "MODEL_SUGGESTED"
        a.cache_file.write_text(json.dumps(stale) + "\n")
        pinned = adj(d, Live("ok"), pinned_files=[a.cache_file])
        served = pinned.decide(cand())
        assert served["from_cache"] and served["decision_state"] == "MODEL_FAILURE"   # recordings are evidence


def test_schema_invalid_model_output_is_still_cached():
    with tempfile.TemporaryDirectory() as d:
        bad = Live("invalid")
        r = adj(d, bad).decide(cand())
        assert r["decision_state"] == "REVIEW_REQUIRED" and r["rejected_raw_outputs"]
        again = Live("invalid")
        assert adj(d, again).decide(cand())["from_cache"] and again.calls == 0


# ---------------------------------------------------------------- label search: same answers, compiled once
def _original_contains_label(text_lower, label):
    body = re.escape(label).replace("\\ ", "\\s+")
    return re.search(LEFT_BOUNDARY + body + RIGHT_BOUNDARY, text_lower) is not None


def test_contains_label_matches_the_original_implementation():
    texts = ["we use machine  learning and c++ daily", "experience with node.js, ci/cd and a/b testing",
             "data-driven decisions; r programming", "it's a team player role", "machinelearning is one word",
             "the  project\tmanagement office", "", "c# and .net core", "learning machine"]
    labels = ["machine learning", "c++", "node.js", "ci/cd", "a/b testing", "r", "r programming", "team player",
              "project management", "c#", ".net", "net", "learning", "machine", "", "it's", "s", "data-driven",
              "driven", "core"]
    for t in texts:
        for lab in labels:
            assert industry._contains_label(t, lab) == _original_contains_label(t, lab), (t, lab)


def test_contains_label_compiles_each_label_once():
    industry._label_pattern.cache_clear()
    for _ in range(50):
        industry._contains_label("we use machine learning", "machine learning")
    info = industry._label_pattern.cache_info()
    assert info.misses == 1 and info.hits == 49
    industry._contains_label("unrelated text", "kubernetes")       # a word is absent: no regex is built
    assert industry._label_pattern.cache_info().misses == 1
