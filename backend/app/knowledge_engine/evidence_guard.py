"""
Circular-evidence guard.

Only these may serve as SOURCE evidence for any analysis:
  - original curriculum documents          data/raw/curricula/...
  - original job-posting files             data/raw/jobs/...
  - ESCO / taxonomy files                  data/raw/esco/...
  - explicitly recorded human decisions    data/metadata/review_decisions.json
  - documented historical versions         (curriculum documents with role PREVIOUS_VERSION, same rule)

Generated outputs -- GOLD analytics, gaps, recommendations, predictions,
BRONZE/SILVER intermediates -- are DERIVED and are refused as sources. Two
checks enforce this:
  1. require_source_path: every manifest path must live under data/raw/ (or be
     the human-decisions file) and never under data/bronze|silver|gold.
  2. require_source_records: records entering coverage/demand must carry a
     source evidence status (EXTRACTED, or HUMAN_VALIDATED for decisions);
     anything MODEL_SUGGESTED / DERIVED / recommendation-shaped is refused.
"""
from pathlib import Path

SOURCE_ROOTS = ("data/raw/curricula", "data/raw/jobs", "data/raw/esco")
HUMAN_DECISION_FILES = ("data/metadata/review_decisions.json",)
DERIVED_ROOTS = ("data/bronze", "data/silver", "data/gold")
SOURCE_RECORD_STATUSES = {"EXTRACTED", "HUMAN_VALIDATED"}


class CircularEvidenceError(ValueError):
    pass


def require_source_path(path, repo_root):
    p = Path(path)
    rel = (p if not p.is_absolute() else p.resolve().relative_to(Path(repo_root).resolve())).as_posix()
    if any(rel == d or rel.startswith(d + "/") for d in DERIVED_ROOTS):
        raise CircularEvidenceError(f"{rel}: generated/derived output cannot be used as source evidence")
    if rel in HUMAN_DECISION_FILES:
        return rel
    if not any(rel.startswith(root + "/") for root in SOURCE_ROOTS):
        raise CircularEvidenceError(f"{rel}: source evidence must be an original file under {SOURCE_ROOTS}")
    return rel


def require_source_records(records, what):
    bad = [r for r in records if r.get("evidence_status") not in SOURCE_RECORD_STATUSES
           or r.get("is_source_evidence") is False or "recommendation_uid" in r or "action_type" in r]
    if bad:
        raise CircularEvidenceError(
            f"{len(bad)} {what} record(s) are derived outputs (e.g. evidence_status={bad[0].get('evidence_status')!r}) "
            "and cannot be used as source evidence")
    return records
