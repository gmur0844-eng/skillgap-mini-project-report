"""Reviewer responses of the semantic validation form: reading every worksheet, keeping answers verbatim with their
source location, statuses for incomplete / invalid / conflicting answers, idempotent immutable storage, R02 vs R03
comparison and metrics with defined denominators, separation from the independent label sets, and the API.
Synthetic packages and workbooks only."""
import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import semantic_eval as se  # noqa: E402
from app.knowledge_engine import semantic_responses as sr  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SUBSET = ["bm1-001", "bm1-002", "bm1-003"]
PKG_ID = "semantic_gold/test-discipline/v1"
C = {"SAME_CONCEPT": "A — Same concept", "PARENT": "B — Parent / broader concept",
     "CHILD": "C — Child / more specific concept", "RELATED": "D — Related", "UNRELATED": "F — Unrelated",
     "INSUFFICIENT_EVIDENCE": "H — Insufficient evidence"}


def _header(ids=SUBSET):
    h = ["Timestamp", "Reviewer ID"]
    for n, cid in enumerate(ids, start=1):
        h += [f"Case {n} (Ref. {cid}) — {p}" for p in ("Relationship", "Confidence", "Optional reasoning")]
    return h


def _row(ts, rid, answers):
    out = [ts, rid]
    for a in answers:
        out += list(a)
    return out


ROWS = [
    _row("2026-10-22 09:00:00", "R02", [(C["CHILD"], "High", "AWS is a provider — “quoted”  text"),
                                        (C["UNRELATED"], "Moderate", None), (C["RELATED"], "Low", "")]),
    _row("2026-10-22 09:05:00", "R03", [(C["CHILD"], "High", None), (C["PARENT"], "High", "broader"),
                                        (None, None, None)]),
    _row("2026-10-22 09:07:00", "R04", [("Z — something else", "High", None), (None, "Low", "no label chosen"),
                                        (C["SAME_CONCEPT"], "Very high", None)]),
]


def _xlsx(path, rows=ROWS, header=None, extra_sheet=True):
    import openpyxl
    wb = openpyxl.Workbook()
    if extra_sheet:
        notes = wb.active
        notes.title = "Notes"
        notes.append(["Instructions for the team"])
        ws = wb.create_sheet("Form responses 1")
    else:
        ws = wb.active
        ws.title = "Form responses 1"
    ws.append(header or _header())
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def _parse(path, **kw):
    return sr.parse_source(path, SUBSET, PKG_ID, kw.pop("source", "HUMAN_AI_ASSISTED"), **kw)


def _get(records, rid, qid):
    return [r for r in records if r["reviewer_id"] == rid and r["question_id"] == qid]


def test_form_constants_are_the_form_generators():
    spec = importlib.util.spec_from_file_location("sv", ROOT / "scripts/evaluation/semantic_validation.py")
    sv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sv)
    assert sr.FORM_CHOICES == sv.FORM_CHOICES and sr.FORM_CONFIDENCE == sv.FORM_CONFIDENCE
    assert sr.QUESTION_RE.pattern == sv.QUESTION_RE.pattern and sr.REVIEWER_ID_TITLE == sv.REVIEWER_ID_TITLE


def test_every_sheet_is_read_and_answers_are_kept_verbatim_with_their_location(tmp_path):
    records, report = _parse(_xlsx(tmp_path / "r.xlsx"))
    sheets = {s["sheet"]: s["status"] for s in report["sheets"]}
    assert sheets == {"Notes": "SKIPPED", "Form responses 1": "READ"}
    assert report["reviewers"] == {"R02": 1, "R03": 1, "R04": 1}
    r = _get(records, "R02", "bm1-001")[0]
    assert r["status"] == "COMPLETED" and r["relationship"] == {"raw": C["CHILD"], "code": "CHILD"}
    assert r["reasoning"] == "AWS is a provider — “quoted”  text"  # exactly as written, spaces and quotes included
    assert r["confidence"] == {"raw": "High", "code": "HIGH"}
    assert r["provenance"]["sheet"] == "Form responses 1" and r["provenance"]["row"] == 2
    assert r["provenance"]["cells"] == {"relationship": "C2", "confidence": "D2", "reasoning": "E2"}
    assert r["reviewer_source"] == "HUMAN_AI_ASSISTED" and r["counts_as_independent_label"] is False
    assert _get(records, "R02", "bm1-003")[0]["reasoning"] is None  # an empty optional box is no reasoning


def test_blank_invalid_and_partial_answers_are_flagged_not_guessed(tmp_path):
    records, _ = _parse(_xlsx(tmp_path / "r.xlsx"))
    assert _get(records, "R03", "bm1-003")[0]["status"] == "PENDING"
    bad = _get(records, "R04", "bm1-001")[0]
    assert bad["status"] == "INVALID" and bad["relationship"] == {"raw": "Z — something else", "code": None}
    assert "not one of the form's eight choices" in bad["issues"][0]
    partial = _get(records, "R04", "bm1-002")[0]
    assert partial["status"] == "AMBIGUOUS" and partial["relationship"]["code"] is None
    conf = _get(records, "R04", "bm1-003")[0]
    assert conf["status"] == "INVALID" and conf["confidence"] == {"raw": "Very high", "code": None}


def test_two_different_submissions_of_one_reviewer_are_both_kept_and_flagged(tmp_path):
    rows = ROWS + [_row("2026-10-22 10:00:00", "R03", [(C["SAME_CONCEPT"], "Low", None), (C["PARENT"], "High", "broader"),
                                                        (None, None, None)])]
    records, report = _parse(_xlsx(tmp_path / "r.xlsx", rows))
    q1 = _get(records, "R03", "bm1-001")
    assert [r["status"] for r in q1] == ["CONFLICTING", "CONFLICTING"] and [r["submission"] for r in q1] == [1, 2]
    assert {r["relationship"]["code"] for r in q1} == {"CHILD", "SAME_CONCEPT"}
    same = _get(records, "R03", "bm1-002")
    assert [r["status"] for r in same] == ["COMPLETED", "COMPLETED"]
    assert "repeat submission with the same answer" in same[1]["issues"]


def test_unknown_questions_and_questions_without_columns_are_reported(tmp_path):
    header = _header(["bm1-001", "bm9-999"])
    rows = [_row("t", "R02", [(C["CHILD"], "High", None), (C["RELATED"], "High", None)])]
    records, report = _parse(_xlsx(tmp_path / "r.xlsx", rows, header))
    assert report["unknown_questions"] == ["bm9-999"]
    assert report["questions_without_columns"] == ["bm1-002", "bm1-003"]
    assert {r["question_id"]: r["status"] for r in records} == {"bm1-001": "COMPLETED", "bm1-002": "NOT_IN_SOURCE",
                                                               "bm1-003": "NOT_IN_SOURCE"}


def test_identical_timestamps_are_noted(tmp_path):
    rows = [_row("2026-10-22 09:03:53", rid, [(C["CHILD"], "High", None)] * 3) for rid in ("R02", "R03")]
    _, report = _parse(_xlsx(tmp_path / "r.xlsx", rows), reviewers=["R02"])
    assert any("all 2 submissions in the file carry the same timestamp" in n for n in report["notes"])


def test_csv_export_of_the_form_reads_the_same(tmp_path):
    path = tmp_path / "r.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(_header())
        w.writerows([[v if v is not None else "" for v in r] for r in ROWS])
    a, _ = _parse(path)
    b, _ = _parse(_xlsx(tmp_path / "r.xlsx"))
    key = lambda rs: [(r["reviewer_id"], r["question_id"], r["status"], r["relationship"]["code"],  # noqa: E731
                       r["confidence"]["code"]) for r in rs]
    assert key(a) == key(b)


def test_storage_is_idempotent_and_never_overwrites(tmp_path):
    pkg = tmp_path / "pkg"
    src = _xlsx(tmp_path / "r.xlsx")
    records, report = _parse(src)
    assert sr.store(pkg, records, report, src, "b" * 64) == {"R02": "IMPORTED", "R03": "IMPORTED", "R04": "IMPORTED"}
    before = {p.name: p.read_bytes() for p in (pkg / "responses").glob("*.json")}
    again, report2 = _parse(src)
    assert sr.store(pkg, again, report2, src, "b" * 64) == {"R02": "UNCHANGED", "R03": "UNCHANGED", "R04": "UNCHANGED"}
    changed = [list(r) for r in ROWS]
    changed[0][2] = C["PARENT"]
    other = _xlsx(tmp_path / "r2.xlsx", changed)
    records3, report3 = _parse(other, reviewers=["R02"])
    assert sr.store(pkg, records3, report3, other, "b" * 64) == {"R02": "CONFLICT"}
    assert {p.name: p.read_bytes() for p in (pkg / "responses").glob("*.json")} == before
    assert len(list((pkg / "responses" / "source").iterdir())) == 1  # the imported source, unchanged; not the refused one
    loaded, files = sr.load(pkg)
    assert len(loaded) == 9 and {f["reviewer_id"] for f in files} == {"R02", "R03", "R04"}


def test_responses_never_become_independent_label_sets(tmp_path):
    pkg = tmp_path / "pkg"
    src = _xlsx(tmp_path / "r.xlsx")
    records, report = _parse(src, source="HUMAN_UNASSISTED")
    sr.store(pkg, records, report, src, "b" * 64)
    (pkg / "labels").mkdir()
    assert se.load_label_sets(pkg / "labels", "b" * 64) == []
    assert all(r["counts_as_independent_label"] is False for r in records)
    assert sr.metrics(records, SUBSET, "R02", "R03")["counts_towards_gate"] is False


def test_metrics_use_defined_denominators_and_missing_is_not_disagreement(tmp_path):
    records, _ = _parse(_xlsx(tmp_path / "r.xlsx"))
    m = sr.metrics(records, SUBSET, "R02", "R03")
    # bm1-001 both CHILD (agree), bm1-002 UNRELATED vs PARENT (disagree), bm1-003 R03 blank (not comparable)
    assert (m["both_completed"], m["agreements"], m["disagreements"]) == (2, 1, 1)
    assert m["agreement_rate"] == 0.5 and m["disagreement_questions"] == ["bm1-002"]
    assert m["cohen_kappa"] == se.cohen_kappa(["CHILD", "UNRELATED"], ["CHILD", "PARENT"])
    assert m["per_reviewer"]["R03"]["assessments_present"] == 2
    assert m["per_reviewer"]["R03"]["status_counts"] == {"COMPLETED": 2, "PENDING": 1}
    assert m["per_reviewer"]["R02"]["completion_rate"] == 1.0
    assert m["per_reviewer"]["R02"]["confidence_distribution"] == {"HIGH": 1, "MODERATE": 1, "LOW": 1}
    assert {i["question_id"] for i in m["issues"]} == {"bm1-003"}
    assert set(m["definitions"]) >= {"agreement_rate", "cohen_kappa", "both_completed"}
    rows = sr.compare(records, SUBSET, "R02", "R03")
    assert [r["comparison"] for r in rows] == ["AGREE", "DISAGREE", "NOT_COMPARABLE"]
    none = sr.metrics(records, SUBSET, "R02", "R99")
    assert none["agreement_rate"] is None and "agreement_rate" in none["unavailable"]
    assert none["per_reviewer"]["R99"]["imported"] is False


def test_export_keeps_raw_text_and_source(tmp_path):
    records, _ = _parse(_xlsx(tmp_path / "r.xlsx"))
    rows = list(csv.DictReader(sr.export_csv(records, {"R04"}).splitlines()))
    assert len(rows) == 3 and rows[0]["relationship_raw"] == "Z — something else" and rows[0]["status"] == "INVALID"
    assert rows[0]["source_sheet"] == "Form responses 1" and rows[0]["source_row"] == "4"


# ------------------------------------------------------------------ API

def _package(root):
    d = root / "test-discipline" / "v1"
    d.mkdir(parents=True)
    (d / "MANIFEST.json").write_text(json.dumps({
        "package": PKG_ID, "discipline": "Test discipline", "benchmark": {"sha256": "b" * 64},
        "label_schema_version": "relationship-labels-v1",
        "label_schema": {"labels": [{"code": c, "meaning": "m"} for _, _, c in sr.FORM_CHOICES]}}))
    (d / "subset.json").write_text(json.dumps({"case_ids": SUBSET}))
    (d / "form_cases.json").write_text(json.dumps([
        {"n": i + 1, "case_id": c, "concept_a": f"A{i}", "context_a": [f"line {i}"], "concept_b": f"B{i}",
         "description_b": "desc"} for i, c in enumerate(SUBSET)]))
    (d / "assistant_adjudication.json").write_text(json.dumps(
        {"label_source": "ASSISTANT_ADJUDICATION", "cases": [{"case_id": "bm1-001", "label": "SAME_CONCEPT"}]}))
    return d


@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import semantic_validation_service as svc
    monkeypatch.setattr(svc, "PACKAGES_ROOT", tmp_path / "gold")
    _package(tmp_path / "gold")
    return TestClient(app), tmp_path


def _upload(c, path, source="HUMAN_AI_ASSISTED", reviewers="R02,R03"):
    with open(path, "rb") as f:
        return c.post("/api/v1/semantic-validation/import", files={"file": (path.name, f.read())},
                      data={"source": source, "reviewers": reviewers, "note": "stated by the project owner"})


def test_api_import_compare_filter_and_export(client):
    c, tmp = client
    base = "/api/v1/semantic-validation"
    assert c.get(f"{base}/compare").json()["metrics"]["both_completed"] == 0  # nothing imported: an empty state
    r = _upload(c, _xlsx(tmp / "r.xlsx"))
    assert r.status_code == 200 and r.json()["stored"] == {"R02": "IMPORTED", "R03": "IMPORTED"}
    assert _upload(c, tmp / "r.xlsx").json()["stored"] == {"R02": "UNCHANGED", "R03": "UNCHANGED"}
    pk = c.get(f"{base}/packages").json()
    assert pk["items"][0]["package"] == "test-discipline/v1" and pk["items"][0]["reviewers"] == ["R02", "R03"]
    q = c.get(f"{base}/questions").json()["items"]
    assert q[0]["ai_reference"]["label"] == "SAME_CONCEPT" and q[0]["ai_reference"]["is_human_judgment"] is False
    assert q[1]["ai_reference"] is None
    cmp = c.get(f"{base}/compare", params={"a": "R02", "b": "R03"}).json()
    assert [x["comparison"] for x in cmp["items"]] == ["AGREE", "DISAGREE", "NOT_COMPARABLE"]
    assert cmp["metrics"]["agreements"] == 1 and "SAME_CONCEPT" not in json.dumps(cmp["metrics"]["per_reviewer"])
    assert len(c.get(f"{base}/compare", params={"outcome": "DISAGREE"}).json()["items"]) == 1
    only = c.get(f"{base}/assessments", params={"reviewer": "R03", "status": "PENDING"}).json()
    assert only["total"] == 1 and only["items"][0]["question_id"] == "bm1-003"
    assert c.get(f"{base}/assessments", params={"label": "CHILD"}).json()["total"] == 2
    one = c.get(f"{base}/assessments/bm1-001/R02").json()
    assert one["records"][0]["reasoning"].startswith("AWS is a provider") and one["question"]["concept_a"] == "A0"
    miss = c.get(f"{base}/missing").json()["reviewers"]
    assert miss["R02"]["not_completed"] == [] and miss["R03"]["not_completed"][0]["question_id"] == "bm1-003"
    exp = c.get(f"{base}/export.csv", params={"reviewers": "R03"})
    assert exp.status_code == 200 and exp.text.splitlines()[0].startswith("question_id,question_number,reviewer_id")
    assert len(exp.text.strip().splitlines()) == 4


def test_api_errors_use_the_structured_shape(client):
    c, tmp = client
    base = "/api/v1/semantic-validation"
    _upload(c, _xlsx(tmp / "r.xlsx"))
    r = c.get(f"{base}/assessments", params={"label": "NOT_A_LABEL"})
    assert r.status_code == 400 and r.json()["code"] == "INVALID_REQUEST"
    assert c.get(f"{base}/assessments/bm9-999/R02").status_code == 404
    assert c.get(f"{base}/assessments/bm1-001/R99").status_code == 404
    assert c.get(f"{base}/questions", params={"package": "../etc"}).status_code == 400
    assert c.get(f"{base}/compare", params={"a": "R02", "b": "R02"}).status_code == 400
    bad = c.post(f"{base}/import", files={"file": ("r.txt", b"x")}, data={"source": "HUMAN_AI_ASSISTED"})
    assert bad.status_code == 400
    wrong_source = _upload(c, tmp / "r.xlsx", source="MODEL")
    assert wrong_source.status_code == 400
    changed = [list(r) for r in ROWS]
    changed[0][2] = C["PARENT"]
    conflict = _upload(c, _xlsx(tmp / "r2.xlsx", changed))
    assert conflict.status_code == 409 and conflict.json()["details"]["R02"] == "CONFLICT"


def test_no_package_is_a_clear_not_found(tmp_path, monkeypatch):
    from app.services import semantic_validation_service as svc
    monkeypatch.setattr(svc, "PACKAGES_ROOT", tmp_path / "none")
    assert svc.packages()["evidence_state"] == "NOT_PRODUCED"
    with pytest.raises(svc.PackageNotFound):
        svc.questions()

