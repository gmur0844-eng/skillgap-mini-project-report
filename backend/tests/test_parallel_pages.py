"""
Reading a PDF's pages on several processes gives exactly the sequential result, in page order, and falls back to the
sequential loop when the pool cannot run. Measured on the real curricula (docs/performance/PERFORMANCE_AUDIT.md §8).
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.preprocessing import parallel_pages as pp  # noqa: E402

PDF = Path(__file__).resolve().parents[2] / "data/external/demo_fixture/sample_curriculum.pdf"
GEOMETRY = "app.pipelines.preprocessing.layout_aware_extraction:_record_page"
TEXT = "tests.test_parallel_pages:page_text"


def page_text(page):
    return page.extract_text() or ""


@unittest.skipUnless(PDF.exists(), "the demo fixture PDF is missing")
class ParallelPages(unittest.TestCase):
    def test_parallel_equals_sequential(self):
        for fn in (GEOMETRY, TEXT):
            seq = pp.map_pages(PDF, fn, workers=1)
            par = pp.map_pages(PDF, fn, workers=2)
            self.assertEqual(seq, par, fn)
            self.assertEqual(len(seq), pp.page_count(PDF))

    def test_a_pool_that_cannot_start_falls_back_to_sequential(self):
        seq = pp.map_pages(PDF, TEXT, workers=1)
        with mock.patch.object(pp, "ProcessPoolExecutor", side_effect=OSError("no processes")):
            self.assertEqual(pp.map_pages(PDF, TEXT, workers=2), seq)

    def test_worker_count(self):
        with mock.patch.dict("os.environ", {"PDF_WORKERS": "1"}):
            self.assertEqual(pp.workers_for(500), 1)
        with mock.patch.dict("os.environ", {"PDF_WORKERS": "4"}):
            self.assertEqual(pp.workers_for(500), 4)
            self.assertEqual(pp.workers_for(10), 1)  # short documents are read sequentially


if __name__ == "__main__":
    unittest.main()
