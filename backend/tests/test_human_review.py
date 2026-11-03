"""
Human-validation workflow: the ingest step must refuse malformed or tampered
review files and must never turn a model prediction into a human label.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "review"))
sys.path.insert(0, str(ROOT / "backend"))

from build_review_set import HUMAN_FIELDS, OPTIONS, model_fields_hash, split_for  # noqa: E402
from ingest_human_review import ReviewRejected, error_category, evaluate, validate, verdict  # noqa: E402


def _item(i, rel="PARENT", kind="TOPIC_TO_REFERENCE_TOPIC"):
    rid = f"v1-{i:03d}"
    return {"review_id": rid, "priority": "HIGH", "item_kind": kind, "source": "s", "question": "q", "left_text": f"left {i}",
            "left_context": "ctx", "right_text": "right", "right_context": "rctx", "model_relationship": rel,
            "model_similarity": 0.5, "lexical_similarity": 0.5, "context_similarity": 0.1, "mapping_method": "m",
            "split": split_for(rid), "options": OPTIONS, "original_evidence": {}, **{f: None for f in HUMAN_FIELDS}}


ENGINE = {"code_fingerprint": "abc", "config_hash": "def"}


def _manifest(items):
    return {**ENGINE, "item_model_hashes": {i["review_id"]: model_fields_hash(i) for i in items}}


def _row(item, **human):
    return {**{k: ("" if v is None else v) for k, v in item.items() if k not in ("options", "original_evidence")},
            **{f: "" for f in HUMAN_FIELDS}, **human}


def test_freshly_built_items_have_no_human_labels():
    item = _item(1)
    assert all(item[f] is None for f in HUMAN_FIELDS)


def test_valid_file_with_letters_is_accepted_and_unlabelled_rows_stay_unlabelled():
    items = [_item(1), _item(2)]
    rows = [_row(items[0], human_label="C", reviewer="R. Reviewer"), _row(items[1])]
    labelled = validate(rows, items, _manifest(items), ENGINE)
    assert [(i["review_id"], label) for i, label, _ in labelled] == [("v1-001", "CHILD")]


def _rejected(rows, items, engine=ENGINE):
    try:
        validate(rows, items, _manifest(items), engine)
    except ReviewRejected as exc:
        return str(exc)
    raise AssertionError("file was accepted")


def test_rejections():
    items = [_item(1), _item(2)]
    good = [_row(items[0]), _row(items[1])]
    assert "duplicate" in _rejected(good + [good[0]], items)
    assert "missing review_id" in _rejected(good[:1], items)
    assert "invalid human_label" in _rejected([_row(items[0], human_label="MAYBE", reviewer="x"), good[1]], items)
    assert "without reviewer" in _rejected([_row(items[0], human_label="A"), good[1]], items)
    edited = dict(good[0], model_relationship="SAME_CONCEPT")
    assert "was edited" in _rejected([edited, good[1]], items)
    assert "model changed" in _rejected(good, items, {"code_fingerprint": "other", "config_hash": "def"})


def test_verdicts_and_error_categories_come_from_the_human_label():
    assert verdict("PARENT", "PARENT") == "CORRECT"
    assert verdict("PARENT", "CHILD") == "ALTERNATIVE"
    assert verdict("SAME_CONCEPT", "UNRELATED") == "INCORRECT"
    assert verdict("PARENT", "AMBIGUOUS") == "AMBIGUOUS"
    assert error_category(_item(1), "PARENT", "CHILD") == "parent/child reversal"
    assert error_category(_item(1, kind="JOB_MENTION_TO_ESCO"), "SAME_CONCEPT", "UNRELATED") == "word-sense error"
    assert error_category(_item(1), "INSUFFICIENT_EVIDENCE", "SAME_CONCEPT") == "missed semantic match"


def test_evaluation_reports_splits_and_small_sample_note():
    decisions = [{"split": "FINAL_TEST", "human_label": "CHILD", "model_relationship_code": "PARENT", "verdict": "ALTERNATIVE",
                  "error_category": "parent/child reversal"}]
    out = evaluate(decisions)
    assert out["FINAL_TEST"]["n"] == 1 and out["FINAL_TEST"]["note"].startswith("small sample")
    assert out["DEVELOPMENT"]["n"] == 0
