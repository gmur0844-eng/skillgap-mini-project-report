"""The semantic layer under provider failure: nothing crashes, every failure is a recorded state, and no failure
can produce a supported decision or an effect."""
import json
import socket
import sys
import tempfile
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import intelligence_stage as ist  # noqa: E402
from app.knowledge_engine import semantic_provider as sp  # noqa: E402
from app.knowledge_engine import semantic_v3 as v3  # noqa: E402
from test_semantic_v3 import E_L1, E_R1, cand, out  # noqa: E402


class Fake:
    name, kind = "fake", "http"

    def __init__(self, behaviour):
        self.behaviour = behaviour

    def describe(self):
        return {"provider": "fake", "model": "m"}

    def complete(self, prompt, schema=None):
        b = self.behaviour
        if isinstance(b, Exception):
            raise b
        return b


def decide(behaviour):
    with tempfile.TemporaryDirectory() as d:
        a = sp.Adjudicator({"semantic_ai": {"max_retries": 1}}, d, "r", providers=[(Fake(behaviour), {"available": True})],
                           protocol=sp.v3_protocol())
        return a.decide(cand()), a.stats


CASES = {
    "ollama_unavailable": urllib.error.URLError(ConnectionRefusedError("refused")),
    "timeout": socket.timeout("timed out"),
    "empty_output": "",
    "malformed_json": "{relationship: SAME_CONCEPT,,",
    "invalid_schema": json.dumps({"relationship": "BEST_FRIENDS", "reason": 3}),
    "missing_evidence": json.dumps(out("SAME_CONCEPT", [])),
    "invented_quote": json.dumps(out("SAME_CONCEPT", [{**E_L1, "quote": "never said this"}, E_R1])),
    "unexpected_fields": json.dumps({**out("UNRELATED", [E_L1]), "confidence": 0.99, "admin": True}),
    "metadata_only": json.dumps(out("SAME_CONCEPT", [{"ref": "M1", "source_type": "TAXONOMY_METADATA",
                                                        "quote": "is an ESCO altLabel"}])),
}


def test_every_failure_mode_is_a_recorded_non_supported_state():
    expected = {"ollama_unavailable": "MODEL_FAILURE", "timeout": "MODEL_FAILURE", "empty_output": "MODEL_FAILURE",
                "malformed_json": "REVIEW_REQUIRED", "invalid_schema": "REVIEW_REQUIRED"}
    for name, behaviour in CASES.items():
        d, stats = decide(behaviour)
        if name in expected:
            assert d["decision_state"] == expected[name], (name, d["decision_state"])
            assert d["relationship"] == "INSUFFICIENT_EVIDENCE", name
        elif name == "unexpected_fields":
            # extra keys are ignored (never stored as fields); the decision itself is judged on its evidence
            assert d["validated_state"] == "MODEL_SUPPORTED" and "confidence" not in d and "admin" not in d
        else:
            assert d["validated_state"] in ("INSUFFICIENT_EVIDENCE", "REVIEW_REQUIRED"), (name, d["validated_state"])
        assert d["is_human_validated"] is False


def test_model_missing_is_reported_by_the_probe_not_raised():
    p = sp.OllamaProvider("http://127.0.0.1:9", "not-a-model", timeout=1)
    probe = p.probe()
    assert probe["available"] is False and probe["reason"]


def test_pipeline_setup_without_any_provider_is_deterministic_fallback():
    cfg = {"semantic_ai": {"prompt_version": "adjudicate-v3", "providers": []}, "semantic_replay": {"runs": []}}
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "data/cache/semantic_decisions").mkdir(parents=True)
        adj, info = ist.semantic_setup(cfg, Path(d))
    assert info["mode"] == "DETERMINISTIC_FALLBACK" and info["gate"] is None
    assert not ist.gate_passed(info)


def test_tampered_recorded_run_is_rejected_not_replayed():
    cfg = {"semantic_ai": {"prompt_version": "adjudicate-v3",
                           "providers": [{"kind": "ollama", "base_url": "http://127.0.0.1:9", "model": "m"}]},
           "semantic_replay": {"runs": [{"name": "r", "cache_file": "c.jsonl", "cache_sha256": "0" * 64,
                                         "gate_file": "g.json", "gate_sha256": "0" * 64,
                                         "prompt_version": "adjudicate-v3"}]}}
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "data/cache/semantic_decisions").mkdir(parents=True)
        (Path(d) / "c.jsonl").write_text("{}\n")
        (Path(d) / "g.json").write_text('{"passed": true}')
        adj, info = ist.semantic_setup(cfg, Path(d))
    assert info["mode"] == "DETERMINISTIC_FALLBACK" and info["replay_rejected"]
    assert not ist.gate_passed(info)   # a forged "passed" gate is never read


def test_failed_decisions_never_have_effects_even_with_a_passed_gate():
    from test_semantic_v3 import _decide_with
    for behaviour in ("", "{bad", json.dumps(out("SAME_CONCEPT", []))):
        class Adj:
            def decide(self, c):
                return {"decision_id": "d", "decision_state": "REVIEW_REQUIRED" if behaviour != CASES["missing_evidence"]  # noqa: B023 -- called within this iteration
                        else "MODEL_SUGGESTED", "model": "m", "prompt_version": "v3", "left": c["left"],
                        "right": c["right"], **out("SAME_CONCEPT", [])}
        orig = ist.intel.v3_from_pool
        ist.intel.v3_from_pool = lambda c, ctx: cand()
        try:
            cfg = {"semantic_ai": {"promotion": {"effects": {"ALIAS_SENSE": {"SAME_CONCEPT": "ESTABLISHED_BY_MODEL"}}}}}
            d = ist.decide_v3(Adj(), [{"kind": "ALIAS_SENSE", "source_entity": "m:1"}], None, cfg, {"gate": {"passed": True}})[0]
        finally:
            ist.intel.v3_from_pool = orig
        assert d["effect"] is None and d["validated_state"] != "MODEL_SUPPORTED"
    assert _decide_with({"passed": True}, out("SAME_CONCEPT", [E_L1, E_R1]))["effect"] == "ESTABLISHED_BY_MODEL"


def test_v3_prompt_keeps_metadata_out_of_evidence():
    p = v3.build_prompt(cand())
    assert "NOT evidence of meaning" in p and "A string contained in another string is NOT a hierarchy" in p
