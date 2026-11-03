"""Independent labelling: model-blind export, reviewer independence, label validation, immutability."""
import csv
import importlib.util
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("bl", ROOT / "scripts/semantic/benchmark_labelling.py")
bl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bl)


def _with_tmp_out(fn):
    orig = bl.OUT
    with tempfile.TemporaryDirectory() as t:
        bl.OUT = Path(t)
        try:
            return fn(Path(t))
        finally:
            bl.OUT = orig


def test_export_is_model_blind_and_gold_blind():
    def run(out):
        bl.export(None)
        text = (out / "labelling_sheet.csv").read_text()
        bench, _ = bl.load_bench()
        rows = list(csv.DictReader((out / "labelling_sheet.csv").open()))
        assert len(rows) == len(bench) and all(r["label"] == "" for r in rows)
        for word in ("SAME_CONCEPT", "rationale", "qwen", "V3", "MODEL_SUPPORTED", "DEVELOPMENT_GOLD"):
            assert word not in text.split("\n", 1)[1], word
    _with_tmp_out(run)


def _sheet(out, rows):
    p = out / "filled.csv"
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["benchmark_id", "label", "note"])
        w.writeheader()
        w.writerows(rows)
    return p


def _raises(fn, needle):
    try:
        fn()
    except SystemExit as e:
        assert needle in str(e), str(e)
        return
    raise AssertionError("expected refusal")


def test_ingest_requires_an_independent_reviewer_valid_labels_and_is_immutable():
    def run(out):
        p = _sheet(out, [{"benchmark_id": "bm1-000", "label": "child", "note": ""},
                         {"benchmark_id": "bm1-001", "label": "", "note": ""}])
        _raises(lambda: bl.ingest(SimpleNamespace(file=p, reviewer="Claude assistant", label_version="v1")), "independent")
        _raises(lambda: bl.ingest(SimpleNamespace(file=p, reviewer=" ", label_version="v1")), "independent")
        bad = _sheet(out, [{"benchmark_id": "bm1-000", "label": "BEST_FRIENDS", "note": ""}])
        _raises(lambda: bl.ingest(SimpleNamespace(file=bad, reviewer="Dr A. Rao", label_version="v1")), "invalid label")
        p = _sheet(out, [{"benchmark_id": "bm1-000", "label": "child", "note": ""},
                         {"benchmark_id": "bm1-001", "label": "", "note": ""}])
        bl.ingest(SimpleNamespace(file=p, reviewer="Dr A. Rao", label_version="v1"))
        doc = json.loads((out / "labels_dr-a-rao_v1.json").read_text())
        assert doc["independent"] and doc["model_blind"] and doc["labelled"] == 1 and doc["labels"][0]["label"] == "CHILD"
        _raises(lambda: bl.ingest(SimpleNamespace(file=p, reviewer="Dr A. Rao", label_version="v1")), "immutable")
    _with_tmp_out(run)


def test_kappa():
    assert bl.kappa(["A", "B", "A", "B"], ["A", "B", "A", "B"]) == 1.0
    assert bl.kappa([], []) is None
