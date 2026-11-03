"""
CLI wrapper around app.pipelines.ingestion.esco.ingest_esco_file — see that
module for the actual logic. Kept thin so the API endpoint
(POST /api/v1/ingestion/esco) and this CLI never diverge.

Download instructions: docs/data_sources.md (ESCO section).

Usage:
    python scripts/ingestion/ingest_esco.py --input-dir data/raw/esco --version v1.2.1
    # or, to smoke-test against the bundled fixture:
    python scripts/ingestion/ingest_esco.py --input-dir data/external/demo_fixture --version FIXTURE --fixture
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.db.session import Base, engine, SessionLocal  # noqa: E402
from app.pipelines.ingestion.esco import ingest_esco_file  # noqa: E402
import app.models  # noqa: E402,F401


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--version", default="unspecified")
    parser.add_argument("--fixture", action="store_true", help="Look for esco_skills_fixture.csv instead of skills_en.csv")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    pattern = "esco_skills_fixture.csv" if args.fixture else "skills_en.csv"
    candidates = list(input_dir.glob(pattern)) or list(input_dir.glob("*skills*.csv"))
    if not candidates:
        print(f"ERROR: no ESCO skills CSV found in {input_dir} (looked for {pattern}).", file=sys.stderr)
        sys.exit(1)

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        result = ingest_esco_file(session, candidates[0], version=args.version)
        print(
            f"Ingested {result['skills_ingested']} ESCO skills, skipped {result['skills_skipped']} "
            f"({result['skip_reasons']}). analysis_run_id={result['analysis_run_id']} "
            f"source_id={result['source_id']}"
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
