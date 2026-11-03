"""Deterministic GOLD writers (JSONL + CSV) and a content digest used to prove
that a rerun with identical inputs produces byte-identical analytical output."""
import csv
import hashlib
import json
from pathlib import Path


def _default(obj):
    if isinstance(obj, (set, tuple)):
        return sorted(obj) if isinstance(obj, set) else list(obj)
    raise TypeError(f"not JSON serialisable: {type(obj).__name__}")


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=_default, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_jsonl(path, records, sort_key=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(records, key=sort_key) if sort_key else list(records)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, default=_default, ensure_ascii=False) + "\n")
    return path


def write_csv(path, records, fields, null_marker=None):
    """null_marker: when given (the database load uses "\\N"), None is written
    as that marker so PostgreSQL keeps NULL distinct from an empty string;
    otherwise None is written as an empty field (human-facing exports)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            row = {k: (json.dumps(v, default=_default, ensure_ascii=False) if isinstance(v, (list, dict, set, tuple)) else v)
                   for k, v in r.items() if k in fields}
            if null_marker is not None:
                row = {k: row.get(k, None) for k in fields}
                row = {k: (null_marker if v is None else v) for k, v in row.items()}
            writer.writerow(row)
    return path


def content_digest(directory, exclude=("run_report.json", "run_report.md", "observability.json", "publish_report.json")):
    """SHA-256 over every analytical file in the run directory (sorted by
    relative path), excluding timing/memory reports that legitimately differ
    between reruns."""
    root = Path(directory)
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name not in exclude):
        h.update(str(path.relative_to(root)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
