"""
CLI wrapper around app.pipelines.ingestion.onet.ingest_onet_files.

Download instructions: docs/data_sources.md (O*NET section).

Usage:
    python scripts/ingestion/ingest_onet.py --input-dir data/raw/onet --version 31.0
    # or against the bundled fixture:
    python scripts/ingestion/ingest_onet.py --input-dir data/external/demo_fixture --version FIXTURE --fixture
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.db.session import Base, engine, SessionLocal  # noqa: E402
from app.pipelines.ingestion.onet import ingest_onet_files  # noqa: E402
import app.models  # noqa: E402,F401


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--version", default="unspecified")
    parser.add_argument("--fixture", action="store_true")
    args = parser.parse_args()
    input_dir = Path(args.input_dir)

    if args.fixture:
        occ_path = input_dir / "occupation_data_fixture.txt"
        tech_path = input_dir / "onet_technology_skills_fixture.txt"
    else:
        occ_path = next(input_dir.glob("Occupation Data*.txt"), None)
        tech_path = next(input_dir.glob("Technology Skills*.txt"), None)

    occ_path = occ_path if occ_path and occ_path.exists() else None
    tech_path = tech_path if tech_path and tech_path.exists() else None

    if not occ_path and not tech_path:
        print(f"ERROR: no O*NET files found in {input_dir}.", file=sys.stderr)
        sys.exit(1)

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        result = ingest_onet_files(session, occ_path, tech_path, version=args.version)
        print(
            f"Ingested {result['occupations_ingested']} occupations, "
            f"{result['technology_skills_ingested']} technology skills. "
            f"analysis_run_id={result['analysis_run_id']} source_id={result['source_id']}"
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
