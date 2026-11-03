"""
CLI wrapper around app.pipelines.ingestion.job_postings.ingest_job_postings_file.

Primary real dataset (India-focused): Kaggle PromptCloudHQ/jobs-on-naukricom.
See docs/data_sources.md for download steps, license (CC BY-NC-SA 4.0), and the
column-header verification caveat.

Usage:
    python scripts/ingestion/ingest_job_postings.py \
        --input-file data/raw/jobs/naukri_jobs.csv --dataset naukri \
        --source-name "Jobs on Naukri.com (Kaggle, PromptCloudHQ)" \
        --source-url "https://www.kaggle.com/datasets/PromptCloudHQ/jobs-on-naukricom"

    # smoke test against the bundled India-focused fixture:
    python scripts/ingestion/ingest_job_postings.py \
        --input-file data/external/demo_fixture/naukri_job_postings_fixture.csv --dataset fixture
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.db.session import Base, engine, SessionLocal  # noqa: E402
from app.pipelines.ingestion.job_postings import ingest_job_postings_file, COLUMN_MAP_PRESETS  # noqa: E402
import app.models  # noqa: E402,F401


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-file", required=True)
    parser.add_argument(
        "--dataset", choices=list(COLUMN_MAP_PRESETS.keys()), default="naukri",
        help="Which column-map preset to use (default: naukri, the primary India-focused dataset)",
    )
    parser.add_argument("--source-name", default=None)
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"ERROR: {input_path} not found.", file=sys.stderr)
        sys.exit(1)

    column_map = COLUMN_MAP_PRESETS[args.dataset]
    default_names = {
        "naukri": "Jobs on Naukri.com (Kaggle, PromptCloudHQ) — CC BY-NC-SA 4.0",
        "linkedin": "LinkedIn Job Postings (Kaggle, arshkon) — optional global comparison",
        "fixture": "DEMO/TEST FIXTURE - India-focused job postings (synthetic)",
    }
    source_name = args.source_name or default_names[args.dataset]

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        result = ingest_job_postings_file(
            session,
            input_path,
            column_map=column_map,
            source_name=source_name,
            source_url=args.source_url,
            limit=args.limit,
        )
        print(f"analysis_run_id={result['analysis_run_id']} source_id={result['source_id']}")
        print("Quality metrics:", result["quality_metrics"])
    finally:
        session.close()


if __name__ == "__main__":
    main()
