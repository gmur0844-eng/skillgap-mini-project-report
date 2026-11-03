"""Safety invariants checked on the latest published GOLD run (skipped when no run exists):
graph integrity, recommendation safety, 'insufficient evidence is not zero / zero is not missing', semantic safe mode."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import intelligence as intel  # noqa: E402

GOLD = Path(__file__).resolve().parents[2] / "data/gold/knowledge"


def _run():
    p = GOLD / "latest_run.json"
    if not p.exists():
        raise unittest.SkipTest("no GOLD run")
    d = GOLD / json.loads(p.read_text())["run_id"]
    if not (d / "intelligence").exists():
        raise unittest.SkipTest("run without intelligence outputs")
    return d


def rows(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()] if Path(path).exists() else []


def test_graph_integrity_recomputed_from_the_published_edges():
    d = _run()
    c = intel.graph_consistency(rows(d / "intelligence/graph_nodes.jsonl"), rows(d / "intelligence/graph_edges.jsonl"))
    for k in ("duplicate_edges", "dangling_edges", "self_parent_or_self_prerequisite", "contradictions",
              "parent_of_cycles", "prerequisite_cycles", "self_edges", "invalid_relationship_types",
              "edges_without_provenance"):
        assert c["checks"][k] == 0, (k, c["checks"][k])


def test_graph_consistency_detects_injected_defects():
    nodes = [{"node_id": "a", "node_type": "X"}, {"node_id": "b", "node_type": "X"}]
    e = lambda s, r, t, m="m", ev="E": {"source": s, "relationship": r, "target": t, "method": m, "evidence_status": ev}  # noqa: E731
    c = intel.graph_consistency(nodes, [e("a", "RELATED_TO", "a"), e("a", "LIKES", "b"), e("a", "MAPS_TO", "b", m=""),
                                        e("a", "PARENT_OF", "b"), e("b", "PARENT_OF", "a"), e("a", "MAPS_TO", "zz")])
    ch = c["checks"]
    assert ch["self_edges"] == 1 and ch["invalid_relationship_types"] == 1 and ch["edges_without_provenance"] == 1
    assert ch["contradictions"] >= 1 and ch["parent_of_cycles"] >= 1 and ch["dangling_edges"] == 1


def test_recommendations_are_supported_explained_and_never_source_evidence():
    d = _run()
    report = json.loads((d / "run_report.json").read_text())
    allowed = set(report["config"]["industry"]["recommendation"]["min_support_states"])
    recs = rows(d / "industry/recommendations.jsonl")
    for r in recs:
        assert r["support_state"] in allowed and r["is_source_evidence"] is False and r["rule_reasons"]
        assert r["classification"] not in ("INSUFFICIENT_EVIDENCE", "COVERED")
    for s in rows(d / "industry/recommendation_suppressions.jsonl"):
        assert s["recommendation_state"] == "SUPPRESSED" and s["reasons"] and all(x.get("code") for x in s["reasons"])
    gaps = {g["skill_key"] for g in rows(d / "industry/skill_gaps.jsonl")}
    decided = {r["skill_key"] for r in recs} | {s["skill_key"] for s in rows(d / "industry/recommendation_suppressions.jsonl")}
    assert gaps == decided   # every gap is either recommended or explicitly suppressed (WHY_NOT is always answerable)


def test_insufficient_evidence_is_not_zero_and_zero_is_not_missing():
    d = _run()
    for g in rows(d / "industry/skill_gaps.jsonl"):
        assert isinstance(g["industry_prevalence_pct"], (int, float))           # observed demand is kept, not zeroed
        if g["classification"] == "INSUFFICIENT_EVIDENCE":
            assert g["reasons"]                                                 # and explained
        if g["classification"] == "MISSING":
            assert g["curriculum_count"] == 0 and g["evidence_state"] == "BOTH_MEASURED"   # measured zero
    for t in rows(d / "intelligence/industry_trends.jsonl"):
        assert t["trend_state"] == "INSUFFICIENT_EVIDENCE" and "trend" not in {k for k, v in t.items() if v == 0}
        assert "periods" in t["reason"]


def test_semantic_safe_mode_has_no_effects_and_no_human_validation():
    d = _run()
    rep = json.loads((d / "intelligence/intelligence_report.json").read_text())["semantic_adjudication"]
    decisions = rows(d / "intelligence/semantic_decisions.jsonl")
    assert all(x["is_human_validated"] is False for x in decisions)
    if not (rep.get("gate") or {}).get("passed"):
        assert not any(x.get("effect") for x in decisions) and rep.get("semantic_graph_edges", 0) == 0
    mentions = rows(d / "industry/skill_mentions.jsonl")
    assert not any(m.get("sense_state") == "ESTABLISHED_BY_MODEL" for m in mentions) or (rep.get("gate") or {}).get("passed")


def test_gap_v2_never_claims_missing_for_unsupported_demand():
    from app.knowledge_engine.intelligence_stage import gap_v2
    base = {"skill_key": "k", "skill_label": "x", "gap_uid": "gap:1", "classification": "MISSING", "reasons": []}
    thin = gap_v2([{**base, "support_state": "INSUFFICIENT_EVIDENCE"}], {}, {})[0]
    assert thin["classification_v2"] == "INSUFFICIENT_EVIDENCE" and "needs" in thin["reason_v2"]
    firm = gap_v2([{**base, "support_state": "SUPPORTED"}], {}, {})[0]
    assert firm["classification_v2"] == "MISSING"
    d = _run()
    for g in rows(d / "intelligence/skill_gaps_v2.jsonl"):
        if g["classification_v2"] == "MISSING":
            assert g["support_state"] in ("SUPPORTED", "HIGH_SUPPORT"), g["skill_label"]
