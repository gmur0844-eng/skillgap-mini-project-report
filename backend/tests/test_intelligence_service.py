"""Service layer for the engine-2.0 APIs: envelopes carry scope + evidence_state; old runs return NOT_PRODUCED."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import intelligence_service as svc  # noqa: E402
from app.services import knowledge_service as ks  # noqa: E402

V1_RUN = "6472ec43cba27593"


from tests.data_requirements import requires_published_run  # noqa: E402

def _latest_v2():
    ir = svc.load()
    return ir if ir.available else None


def test_old_run_returns_not_produced_without_numbers():
    if not (ks.GOLD_ROOT / V1_RUN / "run_report.json").exists():
        return
    ir = svc.IntelligenceRun(ks.load_run(V1_RUN))
    for fn in (svc.gaps, svc.curriculum_coverage, svc.industry_occupations, svc.semantic_decisions):
        out = fn(ir)
        assert out["evidence_state"] == "NOT_PRODUCED" and out["items"] == [] and out["scope"]["run_id"] == V1_RUN


@requires_published_run
def test_latest_run_envelopes():
    ir = _latest_v2()
    if ir is None:
        return
    for out in (svc.gaps(ir), svc.curriculum_coverage(ir), svc.industry_occupations(ir), svc.semantic_decisions(ir),
                svc.semantic_relationships(ir, limit=5), svc.semantic_contradictions(ir), svc.curriculum_drift(ir),
                svc.curriculum_topic_hierarchy(ir), svc.industry_trends(ir), svc.semantic_review(ir)):
        assert out["evidence_state"] == "AVAILABLE"
        assert out["scope"]["population_scope"]["representativeness_warning"]
    rev = svc.semantic_review(ir)
    assert rev["human_labels"] == 0
    for d in svc.semantic_decisions(ir, limit=1000)["items"]:
        assert d["is_human_validated"] is False
        if d["provider_status"] == "AI_PROVIDER_UNAVAILABLE":
            assert d["decision_state"] == "RULE_VERDICT_NO_MODEL"
    for g in svc.gaps(ir, limit=1000)["items"]:
        assert g["is_source_evidence"] is False


@requires_published_run
def test_why_not_and_trace_for_every_gap_skill():
    ir = _latest_v2()
    if ir is None:
        return
    for g in svc.gaps(ir, limit=20)["items"]:
        w = svc.why_not(ir, g["skill_key"])
        t = svc.evidence_trace(ir, g["skill_key"])
        assert w["gap_v2"]["skill_key"] == g["skill_key"] and t["skill_key"] == g["skill_key"]


@requires_published_run
def test_graph_evidence_labels_come_from_the_run_graph():
    ir = _latest_v2()
    if ir is None:
        return
    edges = ir.rows("graph_edges.jsonl")
    if not edges:
        return
    node = edges[0]["source"]
    out = svc.semantic_evidence(ir, node)
    labelled = {n["node_id"] for n in ir.rows("graph_nodes.jsonl")}
    assert out["edges"] and all(node in (e["source"], e["target"]) for e in out["edges"])
    ids = {node} | {e["source"] for e in out["edges"]} | {e["target"] for e in out["edges"]}
    # every label returned belongs to the node or a real neighbour, and exists in graph_nodes
    assert set(out["nodes"]) <= ids and set(out["nodes"]) <= labelled
