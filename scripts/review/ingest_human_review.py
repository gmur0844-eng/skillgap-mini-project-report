"""
Validate and store a COMPLETED human review file, then evaluate the frozen model on it.

    python3 scripts/review/ingest_human_review.py data/human_validation/v1/review_file_completed.csv [--version v1]

Refuses the file (exit 2, nothing stored) when:
  - a review_id is missing, unknown or duplicated
  - a human_label is not one of the allowed labels (A-H letters are accepted and expanded)
  - a labelled row has no reviewer
  - any model field of a row differs from the frozen item (item hash mismatch)
  - the current engine (code fingerprint / config hash) differs from the frozen manifest
    (the model must not change while a review is in progress) -- UNLESS --frozen-outputs-only is
    given: then the labels are evaluated against the model outputs stored in the frozen items
    (the v1 run), the engine change is recorded, and nothing is said about the current engine

On success writes data/human_validation/<version>/:
  decisions.jsonl                 one record per labelled item: reviewer, timestamp, model version,
                                  dataset version, original evidence, model output, human decision, verdict
  gold_semantic_validation.json   ONLY human-labelled items, grouped by split
  evaluation_v1.json              metrics of the frozen (pre-validation) model per split

Human decisions are VALIDATION evidence about a mapping. They never alter or add to the
source evidence (curriculum documents, job postings, ESCO): nothing here edits data/raw or SILVER.
Unlabelled rows stay unlabelled -- a model prediction is never copied into human_label.
"""
import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_review_set import HUMAN_FIELDS, LETTERS, OPTIONS, model_fields_hash  # noqa: E402


class ReviewRejected(ValueError):
    pass


def _model_relationship_code(text):
    """'SAME_CONCEPT (counted as coverage)' -> 'SAME_CONCEPT'; 'drift REMOVED: ...' -> 'UNRELATED' (no match claimed)."""
    head = (text or "").split(" ")[0].strip()
    if head in OPTIONS:
        return head
    if head in ("TAXONOMY_ALIAS_MATCH", "CURATED_TOKEN", "UNMAPPED", "NEW_DISCOVERED_UNMAPPED"):
        return "INSUFFICIENT_EVIDENCE"
    if head == "drift":
        return "UNRELATED"
    return "INSUFFICIENT_EVIDENCE"


def verdict(model_code, human):
    if human in ("AMBIGUOUS", "INSUFFICIENT_EVIDENCE"):
        return human
    if human == model_code:
        return "CORRECT"
    if human == "UNRELATED" or model_code in ("UNRELATED", "INSUFFICIENT_EVIDENCE"):
        return "INCORRECT"
    return "ALTERNATIVE"


def error_category(item, model_code, human):
    """Derived only from the human label + the frozen model output; a reviewer-supplied
    human_error_category (if any) is kept alongside."""
    if human == model_code or human in ("AMBIGUOUS", "INSUFFICIENT_EVIDENCE"):
        return None
    if {model_code, human} == {"PARENT", "CHILD"}:
        return "parent/child reversal"
    if human == "UNRELATED" and model_code != "UNRELATED":
        return "word-sense error" if item["item_kind"] == "JOB_MENTION_TO_ESCO" else "unrelated match / lexical false positive"
    if model_code in ("UNRELATED", "INSUFFICIENT_EVIDENCE") and human in ("SAME_CONCEPT", "PARENT", "CHILD", "RELATED", "PARTIAL_OVERLAP"):
        return "missed semantic match"
    if model_code == "SAME_CONCEPT" and human in ("PARENT", "RELATED", "PARTIAL_OVERLAP"):
        return "overly broad concept"
    if model_code == "SAME_CONCEPT" and human == "CHILD":
        return "overly narrow concept"
    return "relationship type error"


def current_engine_state():
    from app.knowledge_engine.config import config_hash, load_config
    from app.knowledge_engine.pipeline import code_fingerprint, existing_settings
    cfg = load_config()
    cfg["existing_settings"] = existing_settings()
    return {"code_fingerprint": code_fingerprint(), "config_hash": config_hash(cfg)}


def validate(rows, items, manifest, engine_state, frozen_outputs_only=False):
    errors = []
    by_id = {i["review_id"]: i for i in items}
    seen = Counter(r.get("review_id") for r in rows)
    errors += [f"duplicate review_id {k}" for k, n in seen.items() if n > 1]
    errors += [f"missing review_id {k}" for k in by_id if k not in seen]
    errors += [f"unknown review_id {k}" for k in seen if k not in by_id]
    for key in ("code_fingerprint", "config_hash"):
        if engine_state.get(key) != manifest.get(key) and not frozen_outputs_only:
            errors.append(f"model changed during review: {key} {manifest.get(key)} -> {engine_state.get(key)}")
    labelled = []
    for r in rows:
        item = by_id.get(r.get("review_id"))
        if item is None:
            continue
        for k in item:
            if k in r and k not in HUMAN_FIELDS and k not in ("options", "original_evidence"):
                if str(r[k] if r[k] is not None else "") != str(item[k] if item[k] is not None else ""):
                    errors.append(f"{item['review_id']}: model field '{k}' was edited")
        if model_fields_hash(item) != manifest["item_model_hashes"].get(item["review_id"]):
            errors.append(f"{item['review_id']}: frozen item hash mismatch")
        label = (r.get("human_label") or "").strip().upper()
        if not label:
            continue
        label = LETTERS.get(label, label)
        if label not in OPTIONS:
            errors.append(f"{item['review_id']}: invalid human_label {r.get('human_label')!r}")
            continue
        if not (r.get("reviewer") or "").strip():
            errors.append(f"{item['review_id']}: labelled without reviewer")
            continue
        labelled.append((item, label, r))
    if errors:
        raise ReviewRejected("; ".join(errors[:25]) + (f" (+{len(errors) - 25} more)" if len(errors) > 25 else ""))
    return labelled


def evaluate(decisions):
    from app.knowledge_engine.evaluation import classification_report
    out = {}
    for split in ("DEVELOPMENT", "VALIDATION", "FINAL_TEST", "ALL"):
        ds = [d for d in decisions if split == "ALL" or d["split"] == split]
        if not ds:
            out[split] = {"n": 0, "note": "no human-labelled items in this split"}
            continue
        rep = classification_report([d["human_label"] for d in ds], [d["model_relationship_code"] for d in ds])
        out[split] = {**rep, "verdicts": dict(Counter(d["verdict"] for d in ds)),
                      "error_categories": dict(Counter(d["error_category"] for d in ds if d["error_category"])),
                      "note": "small sample: no significance claimed" if len(ds) < 30 else None}
    out["reporting_rule"] = ("FINAL_TEST is the only split reported as final performance; DEVELOPMENT may be used for "
                             "changes (Version 2), which must then be re-evaluated on VALIDATION/FINAL_TEST only")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("review_file")
    ap.add_argument("--version", default="v1")
    ap.add_argument("--frozen-outputs-only", action="store_true",
                    help="accept labels after the engine changed; evaluate only the frozen v1 outputs")
    args = ap.parse_args(argv)
    base = REPO / "data/human_validation" / args.version
    items = json.loads((base / "review_items.json").read_text())
    manifest = json.loads((base / "freeze_manifest.json").read_text())
    path = Path(args.review_file)
    if path.suffix.lower() in (".xlsx", ".xls"):
        import pandas as pd
        rows = [{k: ("" if v != v else v) for k, v in r.items()} for r in pd.read_excel(path, sheet_name="review", dtype=str).to_dict("records")]
    else:
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
    try:
        engine_now = current_engine_state()
        labelled = validate(rows, items, manifest, engine_now, frozen_outputs_only=args.frozen_outputs_only)
    except ReviewRejected as exc:
        print("REJECTED:", exc)
        return 2
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    decisions = []
    for item, label, r in labelled:
        code = _model_relationship_code(item["model_relationship"])
        decisions.append({
            "review_id": item["review_id"], "split": item["split"], "item_kind": item["item_kind"],
            "left_text": item["left_text"], "left_context": item["left_context"], "right_text": item["right_text"],
            "right_context": item["right_context"], "original_evidence": item["original_evidence"],
            "model_relationship": item["model_relationship"], "model_relationship_code": code,
            "model_similarity": item["model_similarity"], "human_label": label, "human_note": r.get("human_note") or None,
            "human_error_category": r.get("human_error_category") or None, "reviewer": r["reviewer"].strip(),
            "review_timestamp": r.get("review_timestamp") or None, "ingested_at": now,
            "verdict": verdict(code, label), "error_category": error_category(item, code, label),
            "model_version": {k: manifest[k] for k in ("run_id", "code_fingerprint", "config_hash", "pipeline_version")},
            "dataset_version": manifest["dataset_version"],
            "evidence_class": "HUMAN_VALIDATION (about the mapping; not source evidence)",
        })
    with (base / "decisions.jsonl").open("w", encoding="utf-8") as fh:
        for d in decisions:
            fh.write(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n")
    gold = {"dataset_version": manifest["dataset_version"], "human_labelled_items": len(decisions),
            "unlabelled_items": len(items) - len(decisions),
            "splits": {s: [d for d in decisions if d["split"] == s] for s in ("DEVELOPMENT", "VALIDATION", "FINAL_TEST")}}
    (base / "gold_semantic_validation.json").write_text(json.dumps(gold, indent=1, ensure_ascii=False), encoding="utf-8")
    evaluation = {"model": "Version 1 (pre-validation, frozen)", **evaluate(decisions),
                  "engine_changed_since_freeze": {k: engine_now.get(k) != manifest.get(k) for k in ("code_fingerprint", "config_hash")},
                  "scope": ("labels evaluated against the model outputs stored in the frozen items (run "
                            f"{manifest['run_id']}); they say nothing about a later engine version")}
    (base / "evaluation_v1.json").write_text(json.dumps(evaluation, indent=1), encoding="utf-8")
    print(json.dumps({"labelled": len(decisions), "verdicts": dict(Counter(d["verdict"] for d in decisions))}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
