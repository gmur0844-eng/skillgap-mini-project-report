"""Readiness 'data' component: only BLOCKED analyses and FAILed documents degrade the data; NOT_APPLICABLE and WARN do
not (regression: the 2026-10-09 RC reported DEGRADED for a NOT_APPLICABLE programme comparison and WARN peers)."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.health import data_component  # noqa: E402


def _run(gates, docs):
    root = Path(tempfile.mkdtemp())
    d = root / "r1"
    d.mkdir()
    (d / "run_report.json").write_text("{}")
    (d / "health.json").write_text(json.dumps({"analytics_gates": {k: {"status": v} for k, v in gates.items()},
                                               "documents": {k: {"status": v} for k, v in docs.items()}}))
    (root / "latest_run.json").write_text(json.dumps({"run_id": "r1"}))
    return data_component(root)


def test_not_applicable_and_warn_are_healthy_with_details():
    c = _run({"a": "ALLOWED", "b": "NOT_APPLICABLE"}, {"t": "PASS", "p": "WARN"})
    assert c["status"] == "HEALTHY"
    assert c["not_applicable_analytics"] == ["b"] and c["documents_with_warnings"] == ["p"]


def test_blocked_analysis_or_failed_document_degrades():
    assert _run({"a": "BLOCKED"}, {"t": "PASS"})["status"] == "DEGRADED"
    c = _run({"a": "ALLOWED"}, {"t": "FAIL"})
    assert c["status"] == "DEGRADED" and c["failed_documents"] == ["t"]
