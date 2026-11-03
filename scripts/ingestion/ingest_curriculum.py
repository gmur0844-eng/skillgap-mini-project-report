"""
CLI wrapper around app.pipelines.ingestion.curriculum.ingest_curriculum_document.

Programme-agnostic: works identically for ANY engineering discipline/programme
(AI&DS, CSE, ECE, EEE, Mechanical, Civil, Chemical, ...) -- every field below
is caller-supplied data, nothing branch-specific is hardcoded in the pipeline.

Usage:
    python scripts/ingestion/ingest_curriculum.py \
        --file data/raw/curricula/some_university_ece_handbook.pdf \
        --institution "Some University" --department "Dept. of Electronics and Communication Engineering" \
        --discipline "Electronics & Electrical" --programme "B.Tech Electronics and Communication Engineering" \
        --programme-code "ECE" --degree "B.Tech" --academic-year "2024-2025"

    # or against the bundled fixture PDF (clearly a synthetic document):
    python scripts/ingestion/ingest_curriculum.py \
        --file data/external/demo_fixture/sample_curriculum.pdf \
        --institution "DEMO UNIVERSITY (FIXTURE - NOT REAL)" --programme "B.Tech Computer Science"
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.db.session import Base, engine, SessionLocal  # noqa: E402
from app.pipelines.ingestion.curriculum import ingest_curriculum_document  # noqa: E402
import app.models  # noqa: E402,F401


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--institution", default=None)
    parser.add_argument("--programme", default=None)
    parser.add_argument("--version-label", default="v1")
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--department", default=None)
    parser.add_argument("--discipline", default=None, help="Data-driven reference, e.g. 'Computing & Data', 'Electronics & Electrical', 'Mechanical & Manufacturing' -- any value is accepted, not a fixed enum")
    parser.add_argument("--programme-code", default=None)
    parser.add_argument("--degree", default=None, help="e.g. B.Tech, B.E, M.Tech")
    parser.add_argument("--academic-year", default=None, help="e.g. 2024-2025")
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"ERROR: {file_path} not found.", file=sys.stderr)
        sys.exit(1)

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        result = ingest_curriculum_document(
            session,
            file_path,
            institution_name=args.institution,
            programme_name=args.programme,
            curriculum_version_label=args.version_label,
            source_url=args.source_url,
            department_name=args.department,
            discipline_name=args.discipline,
            programme_code=args.programme_code,
            degree_level=args.degree,
            academic_year=args.academic_year,
        )
        print(result)
        if result.get("flagged_for_review"):
            print(
                "WARNING: extraction confidence was low — this document is flagged "
                "for manual review rather than trusted as-is.",
                file=sys.stderr,
            )
    finally:
        session.close()


if __name__ == "__main__":
    main()
