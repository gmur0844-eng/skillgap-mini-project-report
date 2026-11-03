"""
CLI wrapper around app.pipelines.ingestion.core_knowledge.

Framework-only this phase: no real authoritative core-knowledge source has
been imported. The bundled fixtures are synthetic and MUST be ingested with
--test-data so they are flagged (DataSource.is_test_data=1) and excluded
from the API by default.

Usage:
    # Smoke test with the synthetic fixture (always pass --test-data):
    python scripts/ingestion/ingest_core_knowledge.py \
        --file data/external/demo_fixture/core_knowledge_fixture.csv \
        --discipline "FIXTURE DISCIPLINE" --source-name "DEMO/TEST FIXTURE" \
        --source-type other --test-data

    # Future real source (once acquired):
    python scripts/ingestion/ingest_core_knowledge.py --file <path.csv|.json> \
        --discipline "<discipline name>" --source-name "<authority>" \
        --source-type academic_framework --source-url <url> --version <year/edition>

    # Map a programme's curriculum topics to a discipline's core topics:
    python scripts/ingestion/ingest_core_knowledge.py --map-curriculum \
        --programme-id <id> --discipline-id <id>
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.db.session import Base, engine, SessionLocal  # noqa: E402
from app.pipelines.ingestion.core_knowledge import (  # noqa: E402
    ingest_core_knowledge_records, map_curriculum_topics_to_core_topics,
    load_records_from_csv, load_records_from_json,
)
import app.models  # noqa: E402,F401

LOADERS = {".csv": load_records_from_csv, ".json": load_records_from_json}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--file")
    p.add_argument("--discipline")
    p.add_argument("--source-name")
    p.add_argument("--source-type", default="academic_framework")
    p.add_argument("--source-url", default=None)
    p.add_argument("--version", default=None)
    p.add_argument("--test-data", action="store_true", help="Flag this source as synthetic/test (is_test_data=1)")
    p.add_argument("--map-curriculum", action="store_true")
    p.add_argument("--programme-id", type=int)
    p.add_argument("--discipline-id", type=int)
    a = p.parse_args()

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        if a.map_curriculum:
            if a.programme_id is None or a.discipline_id is None:
                sys.exit("--map-curriculum requires --programme-id and --discipline-id")
            print(map_curriculum_topics_to_core_topics(session, a.programme_id, a.discipline_id))
            return
        if not (a.file and a.discipline and a.source_name):
            sys.exit("--file, --discipline and --source-name are required for import")
        path = Path(a.file)
        loader = LOADERS.get(path.suffix.lower())
        if loader is None:
            sys.exit(f"Unsupported format {path.suffix}; supported: {sorted(LOADERS)}")
        result = ingest_core_knowledge_records(
            session, loader(path), a.discipline, a.source_name, a.source_type,
            raw_file_path=path, source_url=a.source_url, version=a.version, is_test_data=a.test_data,
        )
        print(result)
    finally:
        session.close()


if __name__ == "__main__":
    main()
