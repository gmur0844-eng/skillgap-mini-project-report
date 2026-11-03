"""Evidence acquisition: statuses, escalation, licence quarantine, registration, and no fabrication."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import acquisition as acq  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SETTINGS = {"min_periods_for_trend": 2, "min_eligible_postings_per_period": 30}


def _repo(tmp):
    r = Path(tmp)
    (r / "data/metadata").mkdir(parents=True)
    reg = json.loads((REPO / "data/metadata/source_registry.json").read_text())
    (r / "data/metadata/source_registry.json").write_text(json.dumps(reg))
    (r / "data/raw/jobs/incoming").mkdir(parents=True)
    return r


def facts(**over):
    base = {"postings_by_period": {"2026-09": 100}, "peer_documents": 0, "reference_documents": ["ref"],
            "postings": 100, "established_postings": 22, "independent_labels": 0}
    base.update(over)
    return base


def by_id(rows):
    return {r["requirement_id"]: r for r in rows}


def test_current_evidence_gaps_are_reported_with_attempts_and_next_action():
    with tempfile.TemporaryDirectory() as t:
        r = by_id(acq.evaluate(_repo(t), facts(), SETTINGS, {"requested_peer_sources": [{"name": "Peer X"}]}))
    trend = r["TEMPORAL_TREND"]
    assert trend["status"] == "PARTIAL"   # 1 of the 2 required periods; every other source unavailable
    assert trend["measured"] == 1 and trend["required"] == 2 and trend["what_is_missing"] and trend["next_action"]
    assert {a["source_id"] for a in trend["sources_attempted"]} == {"job-postings-drop-folder", "jooble-api-india"}
    assert [l["level"] for l in trend["escalation"]][0] == 0 and trend["escalation"][-1]["level"] == 6
    assert r["PEER_BENCHMARK"]["status"] == "SOURCE_UNAVAILABLE"
    assert "Peer X" in json.dumps(r["PEER_BENCHMARK"]["sources_attempted"])
    assert r["OCCUPATION_MAPPING"]["status"] == "PARTIAL" and r["OCCUPATION_MAPPING"]["measured"] == 0.22
    assert r["INDEPENDENT_SEMANTIC_LABELS"]["status"] == "REVIEW_REQUIRED"


def test_sufficient_evidence_is_available_without_attempts():
    with tempfile.TemporaryDirectory() as t:
        r = by_id(acq.evaluate(_repo(t), facts(postings_by_period={"2026-08": 40, "2026-09": 100}), SETTINGS, {}))
    assert r["TEMPORAL_TREND"]["status"] == "AVAILABLE" and not r["TEMPORAL_TREND"]["sources_attempted"]


def test_drop_folder_quarantines_undeclared_licences_and_registers_valid_files():
    with tempfile.TemporaryDirectory() as t:
        repo = _repo(t)
        inc = repo / "data/raw/jobs/incoming"
        (inc / "a.csv").write_text("title,description\nx,y\n")                      # no sidecar
        (inc / "b.csv").write_text("title,description\nx,y\n")
        (inc / "b.csv.source.json").write_text(json.dumps({"source_url": "https://example.org/data", "license": "unclear",
                                                           "collected_on": "2026-10-01", "geographic_scope": "IN",
                                                           "collected_by": "owner"}))
        src = next(s for s in acq.load_registry(repo)["sources"] if s["source_id"] == "job-postings-drop-folder")
        res = acq.CONNECTORS["drop_folder"].inspect(src, repo, {})
        assert res["status"] == "LICENSE_RESTRICTED" and len(res["quarantined"]) == 2 and not res["pending"]
        (inc / "c.csv").write_text("title,description\nx,y\n")
        (inc / "c.csv.source.json").write_text(json.dumps({"source_url": "https://example.org/c", "license": "CC BY 4.0",
                                                           "collected_on": "2026-10-01", "geographic_scope": "IN",
                                                           "collected_by": "owner"}))
        manifest = {"industry_sources": []}
        assert acq.CONNECTORS["drop_folder"].inspect(src, repo, manifest)["status"] == "VALIDATING"
        res = acq.CONNECTORS["drop_folder"].acquire(src, repo, manifest, register=True)
        assert res["registered"] == ["data/raw/jobs/incoming/c.csv"]
        entry = manifest["industry_sources"][0]
        assert len(entry["expected_sha256"]) == 64 and entry["provenance"]["license"] == "CC BY 4.0"
        # once registered the file is no longer pending; unregistered invalid files stay quarantined
        assert acq.CONNECTORS["drop_folder"].inspect(src, repo, manifest)["status"] == "LICENSE_RESTRICTED"


def test_credentialed_source_without_key_is_unavailable_not_faked():
    src = {"enabled": True, "credential_env": "SURELY_NOT_SET_ENV_123", "source_id": "x"}
    assert acq.CONNECTORS["credentialed_api"].inspect(src, ".", {})["status"] == "SOURCE_UNAVAILABLE"
    assert acq.CONNECTORS["credentialed_api"].inspect({**src, "enabled": False}, ".", {})["status"] == "SOURCE_UNAVAILABLE"


def test_attempts_are_recorded_in_state():
    with tempfile.TemporaryDirectory() as t:
        repo = _repo(t)
        acq.record_attempt(repo, "s1", {"status": "SOURCE_UNAVAILABLE", "reason": "r"})
        acq.record_attempt(repo, "s1", {"status": "AVAILABLE", "reason": "ok"})
        st = acq.load_state(repo)["sources"]["s1"]
        assert st["last_failure"] and st["last_success"] and st["last_status"] == "AVAILABLE"


def test_independent_label_count_ignores_non_independent_or_model_aware_sets():
    with tempfile.TemporaryDirectory() as t:
        d = Path(t) / "data/evaluation/semantic_benchmark_v1/independent_labels"
        d.mkdir(parents=True)
        (d / "labels_a.json").write_text(json.dumps({"independent": False, "model_blind": True, "labels": [{"label": "X"}]}))
        (d / "labels_b.json").write_text(json.dumps({"independent": True, "model_blind": False, "labels": [{"label": "X"}]}))
        assert acq.count_independent_labels(t) == 0
        (d / "labels_c.json").write_text(json.dumps({"independent": True, "model_blind": True,
                                                     "labels": [{"label": "X"}, {"label": ""}]}))
        assert acq.count_independent_labels(t) == 1
