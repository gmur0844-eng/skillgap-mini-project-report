"""
A fresh clone has no analysis (data/ is git-ignored). The API must say so as its own state, NO_ANALYSIS_YET, with how
to start, not as a failed request; a named run that does not exist stays RUN_NOT_FOUND.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import knowledge_service as ks  # noqa: E402


class FreshInstallation(unittest.TestCase):
    def test_no_run_at_all_is_no_analysis_yet(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(ks.NoAnalysisYet) as cm:
                ks.latest_run_id(empty)
        self.assertEqual(ks.not_found_code(cm.exception), "NO_ANALYSIS_YET")
        self.assertIn("New analysis", str(cm.exception))
        self.assertIsInstance(cm.exception, ks.RunNotFound)  # every existing handler still catches it

    def test_a_missing_named_run_is_still_run_not_found(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(ks.RunNotFound) as cm:
                ks.KnowledgeRun("0123456789abcdef", gold_root=empty)
        self.assertEqual(ks.not_found_code(cm.exception), "RUN_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
