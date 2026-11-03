"""
RAW / BRONZE / SILVER pipeline artifact persistence (Phase-1 hardening item 7).

The database is the application's persistence layer; these files exist
alongside it purely for reproducibility and presentation -- so a reviewer can
open a folder and see exactly what came in, what passed validation, and what
the cleaned/deduplicated result was, without querying the database.

Layout (deterministic, one directory per run so re-running never overwrites
a previous run's artifacts):

    data/raw/<dataset>/<run_id>/source.<ext>       -- byte-for-byte copy of the input file
    data/bronze/<dataset>/<run_id>/records.jsonl   -- validated + standardized records (one JSON object per line)
    data/silver/<dataset>/<run_id>/records.jsonl   -- cleaned + deduplicated records

dataset is one of "jobs" | "curricula" (esco/onet artifact writing is not
wired in yet -- see README status table).
"""
import json
import shutil
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parents[4] / "data"  # backend/app/pipelines/preprocessing/../../../.. -> repo root/data


def _run_dir(stage: str, dataset: str, run_id: int) -> Path:
    d = DATA_ROOT / stage / dataset / str(run_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_raw_copy(dataset: str, run_id: int, source_path: Path) -> Path:
    """Byte-for-byte copy of the original input file. Never modifies the original."""
    dest_dir = _run_dir("raw", dataset, run_id)
    dest = dest_dir / f"source{source_path.suffix.lower()}"
    shutil.copyfile(source_path, dest)
    return dest


def write_jsonl_records(stage: str, dataset: str, run_id: int, records: list[dict]) -> Path:
    """
    Used for both bronze (validated + standardized) and silver (cleaned +
    deduplicated) stages -- same format, different stage/content.
    """
    dest_dir = _run_dir(stage, dataset, run_id)
    dest = dest_dir / "records.jsonl"
    with dest.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
    return dest


def read_jsonl_records(path: Path) -> list[dict]:
    """Reads back a records.jsonl file -- used by tests to verify what was written."""
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
