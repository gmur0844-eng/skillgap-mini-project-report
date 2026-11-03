"""The agents registry and the experimental gap review read stored outputs only and label their authority."""
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import agents_service as a  # noqa: E402


class Run:
    def __init__(self, d, run_id="r1"):
        self.dir, self.run_id = Path(d), run_id


def test_registry_has_five_ordered_agents_with_code_and_outputs():
    assert [x["order"] for x in a.AGENTS] == [1, 2, 3, 4, 5]
    root = Path(__file__).resolve().parents[1] / "app"
    for x in a.AGENTS:
        for layer in (x["authoritative"], x["experimental"] or {"code": []}):
            for c in layer["code"]:
                assert (root / c.split(" ")[0]).exists(), c


def test_missing_outputs_are_reported_not_hidden():
    with tempfile.TemporaryDirectory() as d, mock.patch.object(a, "EXPERIMENTS", Path(d) / "exp"):
        out = a.agents(Run(d))
        assert all(x["status"] == "NOT_PRODUCED" and x["authoritative"]["missing"] for x in out["items"])
        g = a.gap_review(Run(d))
        assert g["evidence_state"] == "NOT_PRODUCED" and g["items"] == [] and "gap_reasoning_audit.py" in g["how_to_produce"]


def test_gap_review_shows_only_eligible_skills_beside_the_authoritative_class():
    with tempfile.TemporaryDirectory() as d:
        exp = Path(d) / "exp" / "gap_reasoning" / "r1"
        exp.mkdir(parents=True)
        (Path(d) / "intelligence").mkdir()
        rows = [("k1", True, "DEPTH_GAP"), ("k2", False, "INSUFFICIENT_EVIDENCE")]
        (exp / "skill_stages.jsonl").write_text("".join(json.dumps({"skill_key": k, "eligible": e}) + "\n" for k, e, _ in rows))
        (exp / "gap_states.jsonl").write_text("".join(json.dumps(
            {"skill_key": k, "skill_label": k, "gap_state": s, "coverage_level": "INTRODUCTORY", "access": "COMPULSORY",
             "practice": "NONE", "carrying_courses": ["C1"], "reasons": ["r"],
             "corroboration": {"summary": {"PEER": "1 of 2 teach it"}}}) + "\n" for k, _, s in rows))
        (Path(d) / "intelligence" / "skill_gaps_v2.jsonl").write_text(json.dumps({"skill_key": "k1", "classification_v2": "PARTIAL"}) + "\n")
        with mock.patch.object(a, "EXPERIMENTS", Path(d) / "exp"):
            g = a.gap_review(Run(d))
        assert g["authority"] == "EXPERIMENTAL" and [i["skill_key"] for i in g["items"]] == ["k1"]
        assert g["items"][0]["authoritative_classification"] == "PARTIAL"
        assert g["items"][0]["other_curricula"] == "peer: 1 of 2 teach it"
