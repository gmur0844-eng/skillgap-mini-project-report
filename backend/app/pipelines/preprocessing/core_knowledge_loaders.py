"""
Pure format loaders for the Core Discipline Knowledge Layer (spec Phase 8).
No DB dependency -- each loader reads a file and returns plain dicts in the
same shape, so the DB-dependent orchestration
(app.pipelines.ingestion.core_knowledge.ingest_core_knowledge_records) never
needs to change to support a new format; only a new loader here does.

PDF / JSONL / ODS / XML loaders are not implemented this phase (framework
only, no real source acquisition yet) -- adding one means adding a function
here with the same {"domain", "topic", "subtopic", "description"} record
shape as the two below.
"""
import csv
import json


def load_records_from_csv(path):
    """Expected columns: domain, topic, subtopic (optional), description (optional)."""
    records = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(
                {
                    "domain": (row.get("domain") or "").strip(),
                    "topic": (row.get("topic") or "").strip(),
                    "subtopic": (row.get("subtopic") or "").strip() or None,
                    "description": (row.get("description") or "").strip() or None,
                }
            )
    return records


def load_records_from_json(path):
    """Expects a JSON array of objects with the same fields as the CSV loader."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array of records, got {type(data).__name__}")
    records = []
    for row in data:
        records.append(
            {
                "domain": (row.get("domain") or "").strip(),
                "topic": (row.get("topic") or "").strip(),
                "subtopic": (row.get("subtopic") or "").strip() or None,
                "description": (row.get("description") or "").strip() or None,
            }
        )
    return records


def validate_records(records):
    """
    Pure validation: a record needs at minimum a non-empty domain and topic.
    Returns (valid_records, invalid_records) -- never silently drops
    anything, the caller decides what to do with invalid_records.
    """
    required_fields = {"domain", "topic"}
    valid, invalid = [], []
    for r in records:
        if all(r.get(f) for f in required_fields):
            valid.append(r)
        else:
            invalid.append(r)
    return valid, invalid


def records_fingerprint(records):
    """
    Deterministic content hash of a record list (order-insensitive), used as
    the DataSource idempotency key when records arrive WITHOUT a raw file.
    Previously such calls created a new DataSource every time, duplicating
    provenance on re-run; this makes them idempotent the same way file_hash
    does for file-based imports.
    """
    import hashlib

    canonical = sorted(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in records)
    return hashlib.sha256("\n".join(canonical).encode("utf-8")).hexdigest()
