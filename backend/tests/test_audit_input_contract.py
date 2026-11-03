"""An experimental audit must not silently depend on an artifact the working tree or the release does not ship.

Regression for the Phase 4-6 Mac failure of 2026-10-09: gap_reasoning_audit.py opened a BRONZE page-text cache
(data/bronze/curricula/<sha16>/pages.<fingerprint>.json) that exists only where the pipeline has once processed that
document. BRONZE is a cache and is excluded from every package, so a working tree may lack it; the audit failed with a
bare FileNotFoundError. The audit now declares its inputs, opens them only through the contract, rebuilds a missing
cache only from the run's own source and parser, and otherwise stops with an explicit reason.
"""
import hashlib
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts/analysis"))
sys.path.insert(0, str(REPO / "scripts/audit"))

import gap_reasoning_audit as audit  # noqa: E402

RUN = "r0000000000000000"


class StaticContract(unittest.TestCase):
    SRC = (REPO / "scripts/analysis/gap_reasoning_audit.py").read_text()

    def test_every_repository_path_in_the_audit_is_declared(self):
        # every literal "data/..." or "backend/..." path the audit builds must fall under a declared pattern
        literals = set(re.findall(r'["\']((?:data|backend)/[\w./-]+)(?=["\'{*])', self.SRC))
        literals = {l for l in literals if not l.startswith("data/experiments/gap_reasoning")}   # its own output
        self.assertTrue(literals)
        for lit in literals:
            ok = any(re.match(re.escape(p.split("{")[0].split("*")[0]), lit) or
                     re.match(re.escape(lit), p.split("{")[0].split("*")[0]) for p, _ in audit.INPUT_CONTRACT)
            self.assertTrue(ok, f"path literal {lit!r} is not covered by INPUT_CONTRACT")

    def test_no_direct_reads_bypass_the_contract(self):
        # inputs are opened through need() / page_text(); a bare .read_text() is allowed only on a value need()
        # returned or on the declared cache inside page_text()
        for m in re.finditer(r"\.read_text\(\)", self.SRC):
            line = self.SRC[self.SRC.rfind("\n", 0, m.start()) + 1:self.SRC.find("\n", m.start())]
            self.assertTrue("need(" in line or "cache.read_text" in line or "write_text" in line or "r(" in line,
                            f"direct read outside the contract: {line.strip()}")

    def test_unshipped_classes_match_the_packaging_rules(self):
        # whatever package_integrity forbids in a release zip must be declared as not packaged by the audit
        import package_integrity as pkg
        for pattern, cls in audit.INPUT_CONTRACT:
            example = "root/" + pattern.replace("{run}", RUN).replace("*", "x/y.json")
            prohibited = any(rx.search(example) for name, rx in pkg.PROHIBITED.items() if "BRONZE" in name)
            if prohibited:
                self.assertIn(cls, audit.NOT_PACKAGED, pattern)


class AnalysisScriptsDeclareCaches(unittest.TestCase):
    def test_no_analysis_audit_reads_a_cache_without_a_contract(self):
        # BRONZE / SILVER are never packaged: an analysis audit that reads them must declare an INPUT_CONTRACT
        for f in sorted((REPO / "scripts/analysis").glob("*.py")):
            src = f.read_text()
            if re.search(r"data/bronze", src):
                self.assertIn("INPUT_CONTRACT", src, f"{f.name} reads BRONZE without declaring its inputs")


class SilverIsNotRunPinned(unittest.TestCase):
    """SILVER is rewritten by every run that processes a document; the only fields a run stamps on it after parsing
    are the ones the audit excludes from its content check (found on the owner's Mac: a later trial run had left
    R22A's topics with role PREVIOUS_VERSION)."""

    def test_run_assigned_fields_match_the_pipeline(self):
        src = (REPO / "backend/app/knowledge_engine/pipeline.py").read_text()
        stamped = set(re.findall(r'for t in records\["topics"\]:\s*\n\s*t\["(\w+)"\] = doc\["\w+"\]', src))
        self.assertEqual(stamped, set(audit.RUN_ASSIGNED_SILVER_FIELDS["topics"]))


class Guarded(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.patch = mock.patch.object(audit, "REPO", self.root)
        self.patch.start()
        src = self.root / "data/raw/curricula/x/doc.pdf"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"%PDF-invented")
        self.doc = {"doc_id": "d1", "path": "data/raw/curricula/x/doc.pdf",
                    "sha256": hashlib.sha256(b"%PDF-invented").hexdigest()}

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_undeclared_input_is_refused(self):
        p = self.root / "data/somewhere/else.json"
        p.parent.mkdir(parents=True)
        p.write_text("{}")
        with self.assertRaises(audit.InputContractError):
            audit.need(p, RUN)

    def test_missing_declared_input_is_explicit_not_file_not_found(self):
        with self.assertRaises(audit.InputContractError) as e:
            audit.need(self.root / f"data/gold/knowledge/{RUN}/run_report.json", RUN)
        self.assertIn("RELEASE", str(e.exception))

    def test_missing_cache_with_another_parser_is_not_rebuilt(self):
        with mock.patch("app.knowledge_engine.pipeline.parser_fingerprint", return_value="ffffffffffffffff"), \
                mock.patch("app.knowledge_engine.pipeline.bronze_pages") as build:
            with self.assertRaises(audit.InputContractError) as e:
                audit.page_text(self.doc, "0123456789abcdef", RUN)
            build.assert_not_called()
        self.assertIn("would not reproduce the run", str(e.exception))

    def test_missing_cache_with_a_changed_source_is_not_rebuilt(self):
        (self.root / self.doc["path"]).write_bytes(b"%PDF-edited")
        with mock.patch("app.knowledge_engine.pipeline.bronze_pages") as build:
            with self.assertRaises(audit.InputContractError):
                audit.page_text(self.doc, "0123456789abcdef", RUN)
            build.assert_not_called()

    def test_missing_cache_with_the_runs_parser_is_rebuilt_and_recorded(self):
        pages = {"pages": ["p1"], "methods": ["pdftotext_layout"], "image_pages": [], "raw_alpha_per_page": [2]}
        audit._ACCESS.clear()
        with mock.patch("app.knowledge_engine.pipeline.parser_fingerprint", return_value="0123456789abcdef"), \
                mock.patch("app.knowledge_engine.pipeline.bronze_pages", return_value=(pages, "EXTRACTED")) as build:
            got = audit.page_text(self.doc, "0123456789abcdef", RUN)
        build.assert_called_once()
        self.assertEqual(got, pages)
        self.assertEqual([a[2] for a in audit._ACCESS], ["source for a cache rebuild", "rebuilt from source"])

    def test_missing_source_is_explicit(self):
        (self.root / self.doc["path"]).unlink()
        with self.assertRaises(audit.InputContractError) as e:
            audit.page_text(self.doc, "0123456789abcdef", RUN)
        self.assertIn("SOURCE", str(e.exception))

    def test_page_text_hash_ignores_cache_timestamps(self):
        a = {"pages": ["x"], "methods": ["m"], "image_pages": [], "raw_alpha_per_page": [1],
             "extracted_at": "2026-09-28T01:47:00+00:00", "doc_id": "a"}
        b = {**a, "extracted_at": "2026-10-09T11:00:00+00:00", "doc_id": "b"}
        self.assertEqual(audit.page_text_sha(a), audit.page_text_sha(b))
        self.assertNotEqual(audit.page_text_sha(a), audit.page_text_sha({**a, "pages": ["y"]}))


if __name__ == "__main__":
    unittest.main()
