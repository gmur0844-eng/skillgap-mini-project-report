"""
Read a PDF's pages on several CPU cores.

pdfplumber reads one page at a time on one core; on a long syllabus that is minutes. Pages are independent, so the
document is split into contiguous page ranges, each worker process opens the PDF and handles its range, and the
results are joined in page order: the output is exactly what the sequential loop produces (tested on the real
curricula, see tests/test_parallel_pages.py).

PDF_WORKERS sets the number of processes (default: CPU cores, at most 8); PDF_WORKERS=1 reads sequentially. Short
documents (fewer than 2 x MIN_PAGES_PER_WORKER pages) are read sequentially: starting processes would cost more than
it saves. If the process pool cannot start or a worker fails, the document is read sequentially instead.
"""
import importlib
import logging
import os
from concurrent.futures import ProcessPoolExecutor

MIN_PAGES_PER_WORKER = 8
MAX_WORKERS = 8
log = logging.getLogger("skillgap.pdf")


def workers_for(page_count):
    try:
        configured = int(os.environ.get("PDF_WORKERS") or 0)
    except ValueError:
        configured = 0
    cores = configured if configured > 0 else min(os.cpu_count() or 1, MAX_WORKERS)
    return max(1, min(cores, page_count // MIN_PAGES_PER_WORKER))


def _resolve(fn_path):
    module, name = fn_path.rsplit(":", 1)
    return getattr(importlib.import_module(module), name)


def _read_range(pdf_path, fn_path, start, end):
    import pdfplumber
    fn = _resolve(fn_path)
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for i in range(start, end):
            page = pdf.pages[i]
            out.append(fn(page))
            close = getattr(page, "close", None)
            if close:
                close()  # release the page's cached objects: a worker holds one range, not the document
    return out


def page_count(pdf_path):
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


def map_pages(pdf_path, fn_path, workers=None):
    """[fn(page) for every page], in page order. fn_path is "module:function" (picklable for worker processes)."""
    pdf_path = str(pdf_path)
    n = page_count(pdf_path)
    w = workers or workers_for(n)
    if w <= 1:
        return _read_range(pdf_path, fn_path, 0, n)
    bounds = [round(k * n / w) for k in range(w + 1)]
    ranges = [(bounds[k], bounds[k + 1]) for k in range(w) if bounds[k] < bounds[k + 1]]
    try:
        with ProcessPoolExecutor(max_workers=len(ranges)) as pool:
            parts = list(pool.map(_read_range, [pdf_path] * len(ranges), [fn_path] * len(ranges),
                                  [a for a, _ in ranges], [b for _, b in ranges]))
    except Exception as exc:  # noqa: BLE001 -- a pool that cannot start (or a worker crash) only costs time
        log.warning("parallel PDF reading failed (%s); reading sequentially", type(exc).__name__)
        return _read_range(pdf_path, fn_path, 0, n)
    return [item for part in parts for item in part]
