"""Evidence acquisition v2 (duplicates, licence, peer PARTIAL) and automatic recomputation lineage."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.knowledge_engine import acquisition as acq
from app.knowledge_engine import recompute as rc


def repo_with(files):
    d = Path(tempfile.mkdtemp())
    (d / "data/metadata").mkdir(parents=True)
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode())
    return d


SOURCE = {"source_id": "drop", "source_type": "JOB_POSTINGS", "connector": "drop_folder", "path": "data/raw/jobs/incoming",
          "accepted_extensions": [".csv"], "manifest_kind": "job_postings", "enabled": True, "priority": 2}
SIDECAR = {"source_url": "https://example.org/export", "license": "CC BY 4.0", "collected_on": "2026-10-01",
           "geographic_scope": "IN", "collected_by": "owner"}


class DropFolder(unittest.TestCase):
    def test_duplicate_acquisition_is_refused(self):
        content = b"title,description\nA,B\n"
        repo = repo_with({"data/raw/jobs/incoming/new.csv": content,
                          "data/raw/jobs/incoming/new.csv.source.json": json.dumps(SIDECAR)})
        manifest = {"industry_sources": [{"path": "data/raw/jobs/old.csv", "expected_sha256": hashlib.sha256(content).hexdigest()}]}
        res = acq.DropFolderConnector().inspect(SOURCE, repo, manifest)
        self.assertEqual(res["pending"], [])
        self.assertTrue(res["quarantined"][0]["reason"].startswith("DUPLICATE_ACQUISITION"))

    def test_unclear_licence_is_restricted_and_valid_file_registers_with_population(self):
        repo = repo_with({"data/raw/jobs/incoming/a.csv": b"x", "data/raw/jobs/incoming/a.csv.source.json":
                          json.dumps({**SIDECAR, "license": "unknown"}),
                          "data/raw/jobs/incoming/b.csv": b"y", "data/raw/jobs/incoming/b.csv.source.json": json.dumps(SIDECAR)})
        manifest = {"industry_sources": []}
        res = acq.DropFolderConnector().acquire(SOURCE, repo, manifest, register=True)
        self.assertEqual(res["registered"], ["data/raw/jobs/incoming/b.csv"])
        self.assertTrue(any("LICENSE_RESTRICTED" in q["reason"] for q in res["quarantined"]))
        entry = manifest["industry_sources"][0]
        self.assertEqual(entry["provenance"]["license"], "CC BY 4.0")
        self.assertTrue(entry["population_id"])


class PeerRequirement(unittest.TestCase):
    def test_partial_when_requested_peers_are_missing(self):
        repo = repo_with({})
        registry = {"sources": [], "requirements": [{"requirement_id": "PEER_BENCHMARK", "analysis": "peer",
                                                      "source_types": [], "measure": "peer_documents", "min_required": 1,
                                                      "why_it_matters": "x"}]}
        out = acq.evaluate(repo, {"peer_documents": 2, "peer_doc_ids": ["p1", "p2"], "requested_peers_missing": ["IIT X"]},
                           {}, {}, registry=registry, state={"sources": {}})
        self.assertEqual(out[0]["status"], "PARTIAL")
        self.assertIn("IIT X", out[0]["what_is_missing"])
        full = acq.evaluate(repo, {"peer_documents": 2, "requested_peers_missing": []}, {}, {}, registry=registry, state={"sources": {}})
        self.assertEqual(full[0]["status"], "AVAILABLE")


class Recompute(unittest.TestCase):
    def test_source_changes_and_plan(self):
        parent = {"document:t": {"sha256": "a", "type": "CURRICULUM:TARGET"}}
        now = {"document:t": {"sha256": "a", "type": "CURRICULUM:TARGET"}, "document:p": {"sha256": "b", "type": "CURRICULUM:PEER"}}
        ch = rc.source_changes(parent, now)
        self.assertEqual([x["source"] for x in ch["added"]], ["document:p"])
        plan = rc.plan(ch, code_or_config_changed=False)
        self.assertEqual(plan["source_types"], ["CURRICULUM:PEER"])
        self.assertIn("peer benchmark", plan["affected_analytics"])
        self.assertNotIn("skill gaps v1/v2", plan["affected_analytics"])
        self.assertFalse(rc.plan(rc.source_changes(parent, parent), False)["recompute"])

    def test_diff_normalises_run_ids_and_derived_ids(self):
        root = Path(tempfile.mkdtemp())
        a, b = root / "aaaaaaaaaaaaaaaa", root / "bbbbbbbbbbbbbbbb"
        for d, rid, scope in ((a, "aaaaaaaaaaaaaaaa", "scope:1111111111111111"), (b, "bbbbbbbbbbbbbbbb", "scope:2222222222222222")):
            (d / "industry").mkdir(parents=True)
            (d / "industry/demand.jsonl").write_text(f'{{"run_id": "{rid}", "scope": "{scope}", "n": 5}}\n')
            (d / "same.json").write_text('{"x": 1}')
        (b / "industry/demand.jsonl").write_text('{"run_id": "bbbbbbbbbbbbbbbb", "scope": "scope:2222222222222222", "n": 5}\n')
        (b / "new.json").write_text("{}")
        (a / "changed.json").write_text('{"v": 1}')
        (b / "changed.json").write_text('{"v": 2}')
        d = rc.diff_runs(a, b)
        self.assertEqual(d["added"], ["new.json"])
        self.assertEqual(d["changed"], ["changed.json"])
        self.assertIn("industry/demand.jsonl", d["unchanged"])

    def test_lineage_written_outside_run_directories(self):
        repo = Path(tempfile.mkdtemp())
        rec = rc.lineage_record("p" * 16, "n" * 16, {"added": [], "removed": [], "changed": []}, {"recompute": True},
                                {"counts": {}}, "fp1", "fp2")
        path = rc.write_lineage(repo, rec)
        self.assertEqual(path.parent, repo / "data/gold/knowledge/lineage")
        self.assertTrue(json.loads(path.read_text())["code_fingerprint"]["changed"])


if __name__ == "__main__":
    unittest.main()


def test_integrity_sql_is_schema_aware():
    """A database published before migration 0003 is verified with the base checks; the improvement checks
    (peer / temporal / occupation) are part of the full query and are never silently dropped from a publish."""
    from app.knowledge_engine import db_publish as d
    base, full = d.integrity_sql(False), d.integrity_sql(True)
    assert full == d.INTEGRITY_SQL and "{" + "improvement" not in full and "{" + "improvement" not in base
    for key in ("peer_supported_without_context", "trend_classified_without_temporal_evidence",
                "peer_topics_in_target_analytics", "peer_relation_on_non_comparison_document", "'occupation_resolution'"):
        assert key in full and key not in base
    for key in ("edges_with_unknown_endpoints", "recommendations_without_gap", "semantic_decisions_claiming_human_validation"):
        assert key in base and key in full
