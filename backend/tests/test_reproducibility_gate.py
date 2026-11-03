"""The cross-machine reproducibility gate (scripts/audit/reproducibility_gate.py) passes only identical runs and the
documented platform-sensitive differences, reports each allowed difference, and fails on anything else."""
import copy
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("reproducibility_gate", ROOT / "scripts/audit/reproducibility_gate.py")
gate_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate_mod)
POLICY = json.loads((ROOT / "scripts/audit/reproducibility_policy.json").read_text())

RUN = "0123456789abcdef"
REPORT = {"run_id": RUN, "code_fingerprint": "c", "parser_fingerprint": "p", "config_hash": "h",
          "semantic_identity": "REPLAY_VERIFIED_RUN|k|s", "pipeline_version": "v", "numeric_environment": {"numpy": "x"}}
FAMILIES = [{"family_uid": "family:a", "name": "graph / tree", "course_uids": ["course:1"]},
            {"family_uid": "family:b", "name": "data / query", "course_uids": ["course:2"]}]
RELATIONS = ([{"relation_uid": "peerrel:%016x" % i, "run_id": RUN, "comparison_doc_id": "peer-x", "relationship": "AMBIGUOUS",
               "target": {"concept": f"t{i}"}, "comparison": {"concept": f"c{i}"}} for i in range(100)]
             + [{"relation_uid": "peerrel:%016x" % 999, "run_id": RUN, "comparison_doc_id": "peer-x",
                 "relationship": "SAME_CONCEPT", "target": {"concept": "graphs"}, "comparison": {"concept": "graphs"}}])


def build(root, families=FAMILIES, relations=RELATIONS, report=REPORT, extra=None):
    d = Path(root) / RUN
    (d / "peers").mkdir(parents=True)
    (d / "run_report.json").write_text(json.dumps(report))
    (d / "concept_families.jsonl").write_text("\n".join(json.dumps(f) for f in families))
    (d / "peers/peer_relations.jsonl").write_text("\n".join(json.dumps(r) for r in relations))
    (d / "health.json").write_text(json.dumps({"status": "HEALTHY"}))
    for name, text in (extra or {}).items():
        (d / name).write_text(text)
    return d


def run(**candidate):
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        return gate_mod.gate(build(a), build(b, **candidate), POLICY)


def test_identical_runs_pass_with_no_exceptions():
    out = run()
    assert out["verdict"] == "PASS" and out["allowed_differences"] == [] and out["files"]["changed"] == 0


def test_a_family_label_difference_is_allowed_and_reported():
    fams = copy.deepcopy(FAMILIES)
    fams[0]["name"] = "tree / graph"
    out = run(families=fams)
    assert out["verdict"] == "PASS"
    [g] = out["allowed_differences"]
    assert g["file"] == "concept_families.jsonl" and g["differences"] == [
        {"record": "family:a", "field": "name", "reference": "graph / tree", "candidate": "tree / graph"}]


def test_a_family_membership_difference_fails():
    fams = copy.deepcopy(FAMILIES)
    fams[0]["course_uids"] = ["course:9"]
    out = run(families=fams)
    assert out["verdict"] == "FAIL" and any("course_uids" in f for f in out["failures"])


def test_bounded_ambiguous_churn_is_allowed_but_a_same_concept_change_fails():
    rel = copy.deepcopy(RELATIONS)
    rel = rel[2:]                                         # two fewer AMBIGUOUS relations: within tolerance
    out = run(relations=rel)
    assert out["verdict"] == "PASS"
    assert out["allowed_differences"][0]["differences"][0]["reference_count"] == 100
    rel = copy.deepcopy(RELATIONS)
    rel[-1]["comparison"]["concept"] = "trees"            # a supported SAME_CONCEPT relation changed
    out = run(relations=rel)
    assert out["verdict"] == "FAIL" and any("SAME_CONCEPT" in f for f in out["failures"])


def test_ambiguous_changes_beyond_the_count_tolerance_fail():
    out = run(relations=RELATIONS[50:])                   # half the AMBIGUOUS relations gone
    assert out["verdict"] == "FAIL" and any("tolerance" in f for f in out["failures"])


def test_an_unlisted_file_difference_fails():
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        ref = build(a)
        new = build(b)
        (new / "health.json").write_text(json.dumps({"status": "DEGRADED"}))
        out = gate_mod.gate(ref, new, POLICY)
    assert out["verdict"] == "FAIL" and any("health.json" in f and "no policy rule" in f for f in out["failures"])


def test_added_files_and_a_different_identity_fail():
    out = run(extra={"new_output.json": "{}"})
    assert out["verdict"] == "FAIL" and any("only in the candidate" in f for f in out["failures"])
    out = run(report={**REPORT, "code_fingerprint": "other"})
    assert out["verdict"] == "FAIL" and any("code_fingerprint" in f for f in out["failures"])


def test_every_policy_rule_is_narrow_and_explained():
    for rule in POLICY["rules"]:
        assert rule["why"] and rule["kind"] in gate_mod.KINDS and "*" not in rule["file"]
        if rule["kind"] == "label_fields":
            assert rule["fields"] and all(f in ("name", "concept_family", "label") for f in rule["fields"])
        if rule["kind"] == "peer_relations":
            assert set(rule["variable_relationships"]) <= {"AMBIGUOUS", "RELATED"}
    assert not any(r["file"] == "exports/concepts.csv" for r in POLICY["rules"])
