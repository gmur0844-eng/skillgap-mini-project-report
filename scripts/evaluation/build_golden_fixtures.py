"""
Snapshot the BRONZE page text of the golden regression pages
(data/evaluation/golden_pages.json) into backend/tests/fixtures/golden/.

The snapshot is the exact text the parser receives (after hybrid extraction
and running-header removal), taken from the BRONZE cache of the current
parser fingerprint, so the regression test exercises the parser without the
PDFs. Each fixture records the source document hash and the fingerprint it
was taken under. Re-run this only when an extraction change is intended;
the test then shows whether the known-good invariants still hold.

Usage: python3 scripts/evaluation/build_golden_fixtures.py
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.knowledge_engine.pipeline import parser_fingerprint  # noqa: E402


def main():
    spec = json.loads((REPO / "data/evaluation/golden_pages.json").read_text(encoding="utf-8"))
    fingerprint = parser_fingerprint()
    out_dir = REPO / "backend/tests/fixtures/golden"
    out_dir.mkdir(parents=True, exist_ok=True)
    for page in spec["pages"]:
        cache = REPO / "data/bronze/curricula" / page["source_sha256"][:16] / f"pages.{fingerprint}.json"
        if not cache.exists():
            sys.exit(f"no BRONZE cache for {page['doc_id']} under fingerprint {fingerprint}; run the pipeline first")
        bronze = json.loads(cache.read_text(encoding="utf-8"))
        numbers = [page["page"], *page.get("extra_pages", [])]
        fixture = {
            "fixture_id": page["fixture_id"], "doc_id": page["doc_id"], "source_sha256": page["source_sha256"],
            "parser_fingerprint_at_snapshot": fingerprint,
            "pages": {str(n): bronze["pages"][n - 1] for n in numbers},
            "extraction_methods": {str(n): bronze["methods"][n - 1] for n in numbers},
            "expectations": {k: v for k, v in page.items() if k not in ("doc_id", "source_sha256", "page", "extra_pages")},
            "labelled_by": spec["labelled_by"], "human_validated": spec["human_validated"], "caveat": spec["caveat"],
        }
        path = out_dir / f"{page['fixture_id']}.json"
        path.write_text(json.dumps(fixture, indent=1, ensure_ascii=False), encoding="utf-8")
        print("wrote", path.relative_to(REPO))


if __name__ == "__main__":
    main()
