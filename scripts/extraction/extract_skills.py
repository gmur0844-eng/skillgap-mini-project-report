"""
CLI wrapper around app.pipelines.ingestion.skill_extraction. Requires that
ESCO (and optionally O*NET) have already been ingested, and that job
postings/curriculum have already been ingested via the scripts in
scripts/ingestion/ -- this stage only extracts skill MENTIONS from data
that's already in the database, it does not ingest anything new itself.

Usage:
    # Extract from job postings already in the DB
    python scripts/extraction/extract_skills.py --source jobs

    # Extract from curriculum (courses/topics/outcomes) already in the DB
    python scripts/extraction/extract_skills.py --source curriculum

    # Both
    python scripts/extraction/extract_skills.py --source both

    # Optional row cap for a quick smoke test
    python scripts/extraction/extract_skills.py --source jobs --limit 50
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.db.session import Base, engine, SessionLocal  # noqa: E402
from app.pipelines.ingestion.skill_extraction import (  # noqa: E402
    extract_skills_from_job_postings,
    extract_skills_from_curriculum,
)
import app.models  # noqa: E402,F401


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["jobs", "curriculum", "both"], default="both")
    parser.add_argument("--limit", type=int, default=None, help="Optional row cap per source, for a quick test run")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        if args.source in ("jobs", "both"):
            result = extract_skills_from_job_postings(session, limit=args.limit)
            print("JOB POSTINGS EXTRACTION")
            print(f"  analysis_run_id={result['analysis_run_id']}")
            print(f"  postings_processed={result['postings_processed']}")
            print(f"  mentions_found={result['mentions_found']}")
            print(f"  mentions_inserted={result['mentions_inserted']}")
            print(f"  already_ingested_skipped={result['already_ingested_skipped']}")
            print(f"  quality_metrics={result['quality_metrics']}")
            print()

        if args.source in ("curriculum", "both"):
            result = extract_skills_from_curriculum(session, limit=args.limit)
            print("CURRICULUM EXTRACTION")
            print(f"  analysis_run_id={result['analysis_run_id']}")
            print(f"  source_records_processed={result['source_records_processed']}")
            print(f"  mentions_found={result['mentions_found']}")
            print(f"  mentions_inserted={result['mentions_inserted']}")
            print(f"  already_ingested_skipped={result['already_ingested_skipped']}")
            print(f"  quality_metrics={result['quality_metrics']}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
