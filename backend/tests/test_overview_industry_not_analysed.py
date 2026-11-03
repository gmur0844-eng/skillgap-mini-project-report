"""The overview of an analysis without industry evidence (regression, 2026-10-22).

A B.E. Mechanical Engineering curriculum was analysed with its AICTE reference but without job postings (none of that
discipline has been supplied, so the industry_gap gate is NOT_APPLICABLE). The overview still led with "No
evidence-supported skill gaps identified -- No skill with industry demand lacks curriculum coverage", showed
"0 confirmed gaps, 0 partial, 0 covered" and "None postings": a claim about gaps the run never assessed.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import improvement_service as svc  # noqa: E402

REASON = ("no job-posting evidence relevant to Mechanical Engineering has been supplied (the available postings are "
          "not evidence of this discipline's demand); the curriculum is analysed on its own")


class Run:
    def __init__(self, d, gate):
        self.dir, self.run_id = Path(d), "run-test"
        target = {"doc_id": "upl-1", "role": "TARGET", "institution": "Example College", "curriculum_version": "R22"}
        self.report = {"documents": [target], "generated_at": "2026-10-22T15:39:47+00:00",
                       "analytics_gates": {"industry_gap": gate}}
        self.courses = {"c1": {"doc_id": "upl-1", "course_uid": "c1"}}
        self.topics = {"t1": {"doc_id": "upl-1", "noise_label": "TOPIC"}}
        self.concepts = {"k1": {"source_roles": ["TARGET", "REFERENCE"]}}
        self.industry = {}


def overview(gate):
    with tempfile.TemporaryDirectory() as d:
        return svc.overview(Run(d, gate))


def test_not_applicable_industry_is_said_plainly_and_claims_no_gap_result():
    o = overview({"status": "NOT_APPLICABLE", "reasons": [REASON]})
    lead = o["findings"][0]
    assert lead["title"] == "Industry demand was not analysed"
    assert "No job-posting evidence relevant to Mechanical Engineering" in lead["statement"]
    assert "neither finds nor rules out gaps" in lead["statement"]
    assert not any("No evidence-supported skill gaps" in f["title"] for f in o["findings"])
    assert o["industry_analysed"] is False and o["gap_line"] == {}
    assert o["attention"] == [] and {k["key"] for k in o["kpis"]} == {"courses", "topics", "concepts"}
    assert len(o["flow"]) == 1 and o["flow"][0]["headline"] == "Industry demand was not analysed"
    assert not any("None" in str(o["flow"][0][k]) for k in ("headline", "evidence"))  # was "None postings"


def test_not_requested_industry_says_so():
    o = overview({"status": "NOT_REQUESTED", "reasons": ["industry comparison was not requested"]})
    assert o["findings"][0]["title"] == "Industry demand was not requested for this analysis"
    assert o["flow"][0]["headline"] == "Industry demand was not requested"


def test_an_analysis_with_industry_evidence_keeps_its_gap_figures():
    o = overview({"status": "ALLOWED", "reasons": []})
    assert o["industry_analysed"] is True
    assert set(o["gap_line"]) >= {"confirmed", "partial", "covered"}
    assert o["findings"][0]["title"] != "Industry demand was not analysed"
