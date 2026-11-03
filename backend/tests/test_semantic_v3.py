"""Semantic Engine V3: context separation, prompt, and the authoritative evidence validator v2."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import semantic_provider as sp  # noqa: E402
from app.knowledge_engine import semantic_v3 as v3  # noqa: E402


def cand(kind="ALIAS_SENSE"):
    return {"kind": kind, "left": "XQ", "question": "q?", "right": "some concept",
            "right_concept": {"uri": "u", "label": "some concept", "type": "knowledge"},
            "left_items": [{"id": "L1", "source_type": "SOURCE_TEXT", "text": "Hands-on work with XQ gauges in the lab."},
                           {"id": "L2", "source_type": "JOB_TITLE", "text": "Quality Engineer"}],
            "right_items": [{"id": "R1", "source_type": "ESCO_DESCRIPTION", "text": "A family of software quality models."}],
            "metadata_items": [{"id": "M1", "source_type": "TAXONOMY_METADATA", "text": "'XQ' is an ESCO altLabel of 'some concept'"}]}


def out(rel, ev, direction=""):
    return {"relationship": rel, "reason": "r", "evidence": ev, "direction_justification": direction,
            "alternatives": [], "uncertainty": "u"}


E_L1 = {"ref": "L1", "source_type": "SOURCE_TEXT", "quote": "XQ gauges"}
E_R1 = {"ref": "R1", "source_type": "ESCO_DESCRIPTION", "quote": "software quality models"}
E_M1 = {"ref": "M1", "source_type": "TAXONOMY_METADATA", "quote": "is an ESCO altLabel"}


def test_metadata_is_shown_but_labelled_not_evidence():
    p = v3.build_prompt(cand())
    assert "CANDIDATE-GENERATION METADATA" in p and "NOT evidence of meaning" in p
    assert p.index("[M1]") > p.index("CANDIDATE-GENERATION METADATA") > p.index("[R1]") > p.index("[L1]")
    assert "A string contained in another string is NOT a hierarchy" in p


def test_supported_when_both_sides_cited():
    assert v3.validate_decision(out("SAME_CONCEPT", [E_L1, E_R1]), cand())[0] == "MODEL_SUPPORTED"
    assert v3.validate_decision(out("UNRELATED", [E_L1]), cand())[0] == "MODEL_SUPPORTED"


def test_taxonomy_metadata_alone_never_supports_same_concept():
    state, f = v3.validate_decision(out("SAME_CONCEPT", [E_M1]), cand())
    assert state == "INSUFFICIENT_EVIDENCE" and any(x.startswith("METADATA_CITED") for x in f)
    state, f = v3.validate_decision(out("SAME_CONCEPT", [E_M1, E_R1]), cand())
    assert state == "INSUFFICIENT_EVIDENCE" and "ALIAS_SAME_CONCEPT_WITHOUT_SOURCE_TEXT" in f


def test_invented_or_empty_quotes():
    fake = {"ref": "L1", "source_type": "SOURCE_TEXT", "quote": "expert in XQ modelling"}
    assert v3.validate_decision(out("SAME_CONCEPT", [fake, E_R1]), cand())[0] == "REVIEW_REQUIRED"
    assert v3.validate_decision(out("SAME_CONCEPT", [{"ref": "L9", "source_type": "SOURCE_TEXT", "quote": "x"}, E_R1]), cand())[0] == "REVIEW_REQUIRED"
    empty = {"ref": "L1", "source_type": "SOURCE_TEXT", "quote": ""}
    assert v3.validate_decision(out("SAME_CONCEPT", [empty, E_R1]), cand())[0] == "INSUFFICIENT_EVIDENCE"


def test_direction_needs_justification_and_source_type_comes_from_our_item():
    assert v3.validate_decision(out("CHILD", [E_L1, E_R1]), cand())[0] == "INSUFFICIENT_EVIDENCE"
    # a justification alone is not directional evidence (containment/shared words are never hierarchy) ...
    state, f = v3.validate_decision(out("CHILD", [E_L1, E_R1], "XQ is one kind of the concept"), cand())
    assert state == "INSUFFICIENT_EVIDENCE" and "NO_DIRECTIONAL_EVIDENCE" in f
    # ... a cited structural item (here an ESCO hierarchy fact) is
    c = cand()
    c["right_items"] = c["right_items"] + [{"id": "R2", "source_type": "ESCO_HIERARCHY",
                                            "text": "broader concept: quality models"}]
    e_r2 = {"ref": "R2", "source_type": "ESCO_HIERARCHY", "quote": "broader concept"}
    assert v3.validate_decision(out("CHILD", [E_L1, E_R1, e_r2], "XQ is one kind of the concept"), c)[0] \
        == "MODEL_SUPPORTED"
    mislabel = {**E_L1, "source_type": "ESCO_DESCRIPTION"}
    state, f = v3.validate_decision(out("RELATED", [mislabel, E_R1]), cand())
    assert state == "MODEL_SUPPORTED" and any(x.startswith("SOURCE_TYPE_MISLABELLED") for x in f)


def test_non_definite_and_schema_failures():
    assert v3.validate_decision(out("AMBIGUOUS", []), cand())[0] == "MODEL_SUGGESTED"
    assert v3.validate_decision({"relationship": "SAME_CONCEPT"}, cand())[0] == "REVIEW_REQUIRED"
    assert v3.validate_output(out("SAME_CONCEPT", ["plain string"])) != []


def test_adjudicator_v3_protocol_records_validated_state_and_separate_cache():
    class Fake:
        name, kind = "fake", "http"

        def describe(self):
            return {"provider": "fake", "model": "m"}

        def complete(self, prompt, schema=None):
            assert schema["properties"]["evidence"]["items"]["type"] == "object"
            return json.dumps(out("SAME_CONCEPT", [E_M1]))
    with tempfile.TemporaryDirectory() as d:
        a3 = sp.Adjudicator({"semantic_ai": {}}, d, "r", providers=[(Fake(), {"available": True})], protocol=sp.v3_protocol())
        r = a3.decide(cand())
        a2 = sp.Adjudicator({"semantic_ai": {}}, d, "r", providers=[(Fake(), {"available": True})])
    assert r["prompt_version"] == "adjudicate-v3" and r["schema_version"] == "decision-schema-v2"
    assert r["decision_state"] == "MODEL_SUGGESTED" and r["validated_state"] == "INSUFFICIENT_EVIDENCE"
    assert a3.model_key != a2.model_key


def test_candidate_hash_covers_every_item_shown():
    c = cand()
    h1 = v3.candidate_hashes(c, sp.sha)
    c["metadata_items"][0]["text"] += "!"
    assert v3.candidate_hashes(c, sp.sha)[1] != h1[1] and v3.candidate_hashes(c, sp.sha)[0] == h1[0]


def _decide_with(gate, model_out, monkey_candidate=None):
    """decide_v3 with a stub adjudicator: the effect is applied only for MODEL_SUPPORTED + passed gate."""
    from app.knowledge_engine import intelligence_stage as ist
    c3 = monkey_candidate or cand()

    class StubAdj:
        def decide(self, c):
            return {"decision_id": "d1", "decision_state": "MODEL_SUGGESTED", "model": "m", "prompt_version": "v3",
                    "left": c["left"], "right": c["right"], **model_out}

    orig = ist.intel.v3_from_pool
    ist.intel.v3_from_pool = lambda c, ctx: dict(c3)
    try:
        cfg = {"semantic_ai": {"promotion": {"effects": {"ALIAS_SENSE": {"SAME_CONCEPT": "ESTABLISHED_BY_MODEL",
                                                                          "UNRELATED": "REJECTED_BY_MODEL"}}}}}
        pool = [{"kind": "ALIAS_SENSE", "source_entity": "mention:1", "candidate_entity": "u"}]
        return ist.decide_v3(StubAdj(), pool, None, cfg, {"gate": gate} if gate is not None else {})[0]
    finally:
        ist.intel.v3_from_pool = orig


def test_promotion_effect_requires_supported_decision_and_passed_gate():
    good = out("SAME_CONCEPT", [E_L1, E_R1])
    d = _decide_with({"passed": True}, good)
    assert d["validated_state"] == "MODEL_SUPPORTED" and d["effect"] == "ESTABLISHED_BY_MODEL"
    d = _decide_with({"passed": False}, good)
    assert d["effect"] is None and d["effect_blocked_reason"] == "promotion gate did not pass"
    assert _decide_with(None, good)["effect"] is None                       # no gate at all
    d = _decide_with({"passed": True}, out("SAME_CONCEPT", [E_M1]))          # metadata-only evidence
    assert d["validated_state"] != "MODEL_SUPPORTED" and d["effect"] is None


def test_replay_hit_and_miss_are_distinguished_and_miss_is_not_a_model_call():
    class Live:
        name, kind = "fake", "http"

        def describe(self):
            return {"provider": "fake", "model": "m"}

        def complete(self, prompt, schema=None):
            return json.dumps(out("UNRELATED", [E_L1]))
    with tempfile.TemporaryDirectory() as d:
        live = sp.Adjudicator({"semantic_ai": {}}, d, "r", providers=[(Live(), {"available": True})], protocol=sp.v3_protocol())
        recorded = live.decide(cand())
        rep = sp.Adjudicator({"semantic_ai": {}}, d, "r", providers=[(sp.RecordedProvider(Live()), {"available": True})],
                             protocol=sp.v3_protocol(), readonly_cache=True)
        hit = rep.decide(cand())
        other = cand()
        other["left_items"] = other["left_items"] + [{"id": "L3", "source_type": "SOURCE_TEXT", "text": "new context"}]
        miss = rep.decide(other)
    assert hit["output_hash"] == recorded["output_hash"] and hit.get("from_cache")
    assert miss["decision_state"] == "MODEL_FAILURE" and miss["reason"].startswith("REPLAY_MISS")
    assert rep.stats.get("model_calls", 0) == 0 and rep.stats["replay_misses"] == 1
