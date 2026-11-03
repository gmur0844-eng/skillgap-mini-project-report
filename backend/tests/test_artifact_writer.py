import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.pipelines.preprocessing.artifact_writer as aw


def _with_tmp_data_root(tmp_root, fn):
    """Temporarily redirect DATA_ROOT so tests never touch the real data/ dir."""
    original = aw.DATA_ROOT
    aw.DATA_ROOT = tmp_root
    try:
        return fn()
    finally:
        aw.DATA_ROOT = original


def test_write_raw_copy_is_byte_identical():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp) / "data"
        source = Path(tmp) / "source.csv"
        source.write_text("a,b\n1,2\n")

        dest = _with_tmp_data_root(tmp_root, lambda: aw.write_raw_copy("jobs", 42, source))
        assert dest.exists()
        assert dest.read_text() == source.read_text()
        assert dest.parent == tmp_root / "raw" / "jobs" / "42"


def test_write_jsonl_records_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp) / "data"
        records = [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]

        path = _with_tmp_data_root(tmp_root, lambda: aw.write_jsonl_records("bronze", "jobs", 7, records))
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"id": 1, "title": "A"}
        assert json.loads(lines[1]) == {"id": 2, "title": "B"}

        read_back = _with_tmp_data_root(tmp_root, lambda: aw.read_jsonl_records(path))
        assert read_back == records


def test_different_runs_do_not_overwrite_each_other():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp) / "data"

        path_run1 = _with_tmp_data_root(
            tmp_root, lambda: aw.write_jsonl_records("silver", "jobs", 1, [{"run": 1}])
        )
        path_run2 = _with_tmp_data_root(
            tmp_root, lambda: aw.write_jsonl_records("silver", "jobs", 2, [{"run": 2}])
        )

        assert path_run1 != path_run2
        assert path_run1.exists() and path_run2.exists()
        assert json.loads(path_run1.read_text().strip()) == {"run": 1}
        assert json.loads(path_run2.read_text().strip()) == {"run": 2}


def test_rerunning_same_run_id_overwrites_only_that_runs_file():
    """Re-writing records.jsonl for the SAME run_id is expected to overwrite
    (it's the same run being re-processed); a DIFFERENT run_id must never
    touch another run's file -- covered by the test above."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp) / "data"

        _with_tmp_data_root(tmp_root, lambda: aw.write_jsonl_records("silver", "jobs", 5, [{"v": 1}]))
        path = _with_tmp_data_root(tmp_root, lambda: aw.write_jsonl_records("silver", "jobs", 5, [{"v": 2}]))
        assert json.loads(path.read_text().strip()) == {"v": 2}


def test_deterministic_path_naming_includes_dataset_and_run_id():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp) / "data"
        path = _with_tmp_data_root(tmp_root, lambda: aw.write_jsonl_records("bronze", "curricula", 99, [{}]))
        assert "curricula" in str(path)
        assert "99" in str(path)
        assert path.name == "records.jsonl"
