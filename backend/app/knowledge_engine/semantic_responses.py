"""
Reviewer responses to the semantic relationship validation form, kept as collected research data.

The validation package (data/evaluation/semantic_gold/<discipline>/<version>/) holds the frozen 48-case subset and the
reviewer form built from it (docs/SEMANTIC_HUMAN_VALIDATION_FORM.md). This module reads the form's responses (the
Google Forms export as .xlsx or .csv, every worksheet) into one record per reviewer x question, without changing
anything a reviewer wrote, and compares reviewers.

Records are stored under <package>/responses/, apart from <package>/labels/. Only label sets in labels/ (written by
`semantic_validation.py import-form` for INDEPENDENT_HUMAN_REVIEWER sets) count towards agreement, the gold labels and
the promotion gate; nothing stored here ever does. Each import states how the responses were produced
(REVIEWER_SOURCES); the statement is recorded with every record and shown wherever the responses are shown.

Record status (per reviewer x question):
  COMPLETED       a relationship from the form's eight choices (and a valid confidence, or none)
  PENDING         nothing answered for the question
  AMBIGUOUS       a confidence or reasoning without a relationship: not read as any relationship
  INVALID         a relationship or confidence outside the form's values: kept verbatim, never converted
  CONFLICTING     the reviewer submitted the form more than once with different answers: every submission is kept
  NOT_IN_SOURCE   the source has no column for the question
The raw cell text is always kept (relationship.raw, confidence.raw, reasoning) next to the code it was read as.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from app.knowledge_engine import semantic_eval as se

# The form's choices, confidence values and question titles. These are scripts/evaluation/semantic_validation.py's
# FORM_CHOICES, FORM_CONFIDENCE, REVIEWER_ID_TITLE and QUESTION_RE (the form generator); a test keeps them identical.
FORM_CHOICES = [("A", "Same concept", "SAME_CONCEPT"), ("B", "Parent / broader concept", "PARENT"),
                ("C", "Child / more specific concept", "CHILD"), ("D", "Related", "RELATED"),
                ("E", "Partial overlap", "PARTIAL_OVERLAP"), ("F", "Unrelated", "UNRELATED"),
                ("G", "Ambiguous", "AMBIGUOUS"), ("H", "Insufficient evidence", "INSUFFICIENT_EVIDENCE")]
FORM_CONFIDENCE = [("High", "HIGH", "certain"), ("Moderate", "MODERATE", "fairly sure"), ("Low", "LOW", "guess")]
REVIEWER_ID_TITLE = "Reviewer ID"
QUESTION_RE = re.compile(r"^Case (\d+) \(Ref\. ([^)]+)\) — (Relationship|Confidence|Optional reasoning)$")
PARTS = {"Relationship": "relationship", "Confidence": "confidence", "Optional reasoning": "reasoning"}

# How the responses were produced, as stated by whoever imports them. None of these makes a response count as an
# independent label (that path is semantic_validation.py import-form into labels/).
REVIEWER_SOURCES = {
    "HUMAN_UNASSISTED": "a person answered from the form alone",
    "HUMAN_AI_ASSISTED": "a person answered after reading about the topics with an AI assistant",
    "NOT_STATED": "how the answers were produced was not stated",
}
STATUSES = ("COMPLETED", "PENDING", "AMBIGUOUS", "INVALID", "CONFLICTING", "NOT_IN_SOURCE")
PACKAGE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}/v[0-9]{1,3}$")
REVIEWER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _text(v):
    """A cell as the reviewer's text (None when empty). Dates become ISO text; nothing else is changed."""
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    s = str(v)
    return s if s.strip() else None


def read_label(raw):
    """(code, issue) for a relationship cell: the form's choice text ("C — Child / more specific concept"), the
    choice words alone, or the code itself. Anything else is INVALID and kept verbatim."""
    v = (raw or "").strip()
    if not v:
        return None, None
    for letter, words, code in FORM_CHOICES:
        if v == f"{letter} — {words}" or v.lower() == words.lower() or v == code:
            return code, None
    return None, f"relationship {v!r} is not one of the form's eight choices"


def read_confidence(raw):
    v = (raw or "").strip()
    if not v:
        return None, None
    for words, code, _ in FORM_CONFIDENCE:
        if v.lower() == words.lower() or v == code:
            return code, None
    return None, f"confidence {v!r} is not High, Moderate or Low"


# ------------------------------------------------------------------ reading a source

def _col_letter(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def read_tables(path):
    """[(sheet name, header, [(row number, values)])] of an .xlsx (every worksheet) or .csv file."""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                out.append((ws.title, [], []))
                continue
            header = [_text(h) or "" for h in rows[0]]
            out.append((ws.title, header, [(i, list(r)) for i, r in enumerate(rows[1:], start=2)]))
        wb.close()
        return out
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        header = rows[0] if rows else []
        return [("csv", header, [(i, r) for i, r in enumerate(rows[1:], start=2)])]
    raise ValueError(f"unsupported file type {path.suffix!r}: use the form export as .xlsx or .csv")


def map_columns(header):
    """{question id: {part: column index}}, the Reviewer ID and Timestamp columns, and headers that look like questions
    but do not match the form's title pattern."""
    questions, numbers, unread = {}, {}, []
    rid = ts = None
    for i, h in enumerate(header):
        t = (h or "").strip()
        m = QUESTION_RE.match(t)
        if m:
            questions.setdefault(m.group(2), {})[PARTS[m.group(3)]] = i
            numbers[m.group(2)] = int(m.group(1))
        elif t == REVIEWER_ID_TITLE:
            rid = i
        elif t == "Timestamp":
            ts = i
        elif t.lower().startswith("case "):
            unread.append(t)
    return questions, numbers, rid, ts, unread


# ------------------------------------------------------------------ records

def parse_source(path, subset, package_id, reviewer_source, reviewers=None, attestation_note=None):
    """All responses of the file as records (see the module docstring), and a report of what was found. subset: the
    package's question ids in order. reviewers: only these reviewer ids (None: all)."""
    if reviewer_source not in REVIEWER_SOURCES:
        raise ValueError(f"reviewer source must be one of {sorted(REVIEWER_SOURCES)}")
    data = Path(path).read_bytes()
    file_sha = sha256(data)
    tables = read_tables(path)
    report = {"file": Path(path).name, "file_sha256": file_sha, "sheets": [], "unknown_questions": [],
              "questions_without_columns": [], "rows_without_reviewer": [], "notes": []}
    submissions = {}  # reviewer -> [submission dicts]
    timestamps = []
    want = {r.strip() for r in reviewers} if reviewers else None
    seen_questions = set()
    for sheet, header, rows in tables:
        questions, numbers, rid, ts, unread = map_columns(header)
        if rid is None or not questions:
            report["sheets"].append({"sheet": sheet, "status": "SKIPPED",
                                     "reason": "no Reviewer ID column and form question columns on this sheet"})
            continue
        report["sheets"].append({"sheet": sheet, "status": "READ", "rows": len(rows), "question_columns": len(questions),
                                 "unread_question_like_headers": unread})
        report["unknown_questions"] += sorted(set(questions) - set(subset))
        seen_questions |= set(questions)
        for row_no, values in rows:
            def cell(i, values=values):
                return values[i] if i is not None and i < len(values) else None
            reviewer = (_text(cell(rid)) or "").strip()
            if not reviewer:
                if any(_text(v) for v in values):
                    report["rows_without_reviewer"].append({"sheet": sheet, "row": row_no})
                continue
            submitted = _text(cell(ts))
            timestamps.append(submitted)  # every submission of the file, imported or not
            if want is not None and reviewer not in want:
                continue
            if not REVIEWER_ID.match(reviewer):
                report["notes"].append(f"{sheet} row {row_no}: reviewer id {reviewer!r} is not a plain identifier; kept")
            answers = {}
            for qid in subset:
                cols = questions.get(qid)
                if cols is None:
                    continue
                answers[qid] = {part: (_text(cell(i)), f"{_col_letter(i)}{row_no}") for part, i in cols.items()}
            submissions.setdefault(reviewer, []).append({"sheet": sheet, "row": row_no, "submitted_at": submitted,
                                                         "answers": answers, "numbers": numbers})
    report["questions_without_columns"] = [q for q in subset if q not in seen_questions]
    if len(timestamps) > 1 and len(set(timestamps)) == 1:
        report["notes"].append(f"all {len(timestamps)} submissions in the file carry the same timestamp ({timestamps[0]}); "
                               "independent form submissions are stamped when each is sent")
    imported_at = now()
    records = []
    for reviewer, subs in sorted(submissions.items()):
        for qid in subset:
            per_sub = [_record(package_id, reviewer, qid, k + 1, s, file_sha, report["file"], reviewer_source,
                               attestation_note, imported_at)
                       for k, s in enumerate(subs)]
            answered = [r for r in per_sub if r["status"] != "PENDING"]
            if len(per_sub) > 1 and len({_answer_key(r) for r in answered}) > 1:
                for r in per_sub:
                    r["issues"].append(f"{len(per_sub)} submissions with different answers; all kept")
                    r["status"] = "CONFLICTING"
            elif len(per_sub) > 1:
                for r in per_sub[1:]:
                    r["issues"].append("repeat submission with the same answer")
            records += per_sub
    report["reviewers"] = {r: len(s) for r, s in sorted(submissions.items())}
    return records, report


def _answer_key(r):
    return (r["relationship"]["code"], r["relationship"]["raw"], r["confidence"]["code"], r["reasoning"])


def _record(package_id, reviewer, qid, submission, sub, file_sha, file_name, reviewer_source, note, imported_at):
    got = sub["answers"].get(qid)
    base = {"record_uid": "resp:" + sha256(f"{package_id}|{reviewer}|{qid}|{submission}".encode())[:16],
            "package": package_id, "question_id": qid, "question_number": sub["numbers"].get(qid),
            "reviewer_id": reviewer, "submission": submission,
            "reviewer_source": reviewer_source, "reviewer_source_meaning": REVIEWER_SOURCES[reviewer_source],
            "attestation_note": note, "human_reviewed": reviewer_source.startswith("HUMAN_"),
            "counts_as_independent_label": False, "imported_at": imported_at}
    if got is None:
        return {**base, "relationship": {"raw": None, "code": None}, "confidence": {"raw": None, "code": None},
                "reasoning": None, "status": "NOT_IN_SOURCE", "issues": ["the source has no column for this question"],
                "provenance": {"file": file_name, "file_sha256": file_sha, "sheet": sub["sheet"], "row": sub["row"],
                               "cells": {}, "submitted_at": sub["submitted_at"]}}
    raw_label, raw_conf, reasoning = (got.get(p, (None, None))[0] for p in ("relationship", "confidence", "reasoning"))
    code, label_issue = read_label(raw_label)
    conf, conf_issue = read_confidence(raw_conf)
    issues = [x for x in (label_issue, conf_issue) if x]
    if issues:
        status = "INVALID"
    elif code:
        status = "COMPLETED"
    elif raw_conf or reasoning:
        status = "AMBIGUOUS"
        issues.append("a confidence or reasoning was given without a relationship")
    else:
        status = "PENDING"
    return {**base, "relationship": {"raw": raw_label, "code": code}, "confidence": {"raw": raw_conf, "code": conf},
            "reasoning": reasoning, "status": status, "issues": issues,
            "provenance": {"file": file_name, "file_sha256": file_sha, "sheet": sub["sheet"], "row": sub["row"],
                           "cells": {p: got[p][1] for p in got}, "submitted_at": sub["submitted_at"]}}


# ------------------------------------------------------------------ storage (immutable, idempotent)

def responses_dir(pkg_dir):
    return Path(pkg_dir) / "responses"


def _file_for(pkg_dir, reviewer):
    return responses_dir(pkg_dir) / f"responses_{re.sub(r'[^a-z0-9]+', '-', reviewer.lower()).strip('-')}_v1.json"


def _stable(records):
    return [{k: v for k, v in r.items() if k != "imported_at"} for r in records]


def store(pkg_dir, records, report, source_path, benchmark_sha256):
    """One file per reviewer. Importing the same responses again changes nothing (UNCHANGED); a different set of
    responses for a reviewer who already has a file is refused (CONFLICT): stored responses are never overwritten.
    The source file of an import that stored anything is kept unchanged under responses/source/."""
    out = {}
    d = responses_dir(pkg_dir)
    d.mkdir(parents=True, exist_ok=True)
    by_reviewer = {}
    for r in records:
        by_reviewer.setdefault(r["reviewer_id"], []).append(r)
    for reviewer, recs in sorted(by_reviewer.items()):
        path = _file_for(pkg_dir, reviewer)
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            out[reviewer] = "UNCHANGED" if _stable(old["records"]) == _stable(recs) else "CONFLICT"
            continue
        doc = {"package": recs[0]["package"], "benchmark_sha256": benchmark_sha256, "reviewer_id": reviewer,
               "reviewer_source": recs[0]["reviewer_source"], "attestation_note": recs[0]["attestation_note"],
               "counts_as_independent_label": False,
               "source": {k: report[k] for k in ("file", "file_sha256")}, "source_notes": report["notes"],
               "imported_at": recs[0]["imported_at"], "records": recs}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        out[reviewer] = "IMPORTED"
    if "IMPORTED" in out.values():
        src_dir = d / "source"
        src_dir.mkdir(exist_ok=True)
        kept = src_dir / f"{report['file_sha256'][:16]}_{Path(source_path).name}"
        if not kept.exists():
            kept.write_bytes(Path(source_path).read_bytes())
    return out


def load(pkg_dir):
    """Every stored record, and the per-reviewer file headers."""
    records, files = [], []
    for p in sorted(responses_dir(pkg_dir).glob("responses_*_v1.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        records += doc["records"]
        files.append({k: doc.get(k) for k in ("reviewer_id", "reviewer_source", "attestation_note", "source",
                                               "source_notes", "imported_at")} | {"file": p.name})
    return records, files


# ------------------------------------------------------------------ comparison and metrics

def _by(records, reviewer):
    """question id -> the reviewer's records (a list: several when there were several submissions)."""
    out = {}
    for r in records:
        if r["reviewer_id"] == reviewer:
            out.setdefault(r["question_id"], []).append(r)
    return out


def _summary(recs):
    """One reviewer's position on a question: its status and, when completed, its relationship."""
    if not recs:
        return {"status": "NOT_IMPORTED", "label": None}
    statuses = {r["status"] for r in recs}
    if "CONFLICTING" in statuses:
        return {"status": "CONFLICTING", "label": None, "labels": sorted({r["relationship"]["code"] or "" for r in recs})}
    r = recs[0]
    return {"status": r["status"], "label": r["relationship"]["code"] if r["status"] == "COMPLETED" else None,
            "confidence": r["confidence"]["code"], "reasoning": r["reasoning"], "record_uid": r["record_uid"]}


def compare(records, subset, a, b):
    """Per question: both reviewers' positions and AGREE / DISAGREE (both completed) or NOT_COMPARABLE (anything
    else: a missing answer is never a disagreement)."""
    ra, rb = _by(records, a), _by(records, b)
    rows = []
    for qid in subset:
        sa, sb = _summary(ra.get(qid)), _summary(rb.get(qid))
        if sa["status"] == "COMPLETED" and sb["status"] == "COMPLETED":
            outcome = "AGREE" if sa["label"] == sb["label"] else "DISAGREE"
        else:
            outcome = "NOT_COMPARABLE"
        rows.append({"question_id": qid, a: sa, b: sb, "comparison": outcome})
    return rows


METRIC_DEFINITIONS = {
    "questions_in_package": "questions of the package's frozen subset (the denominator for completion)",
    "questions_found_in_source": "subset questions with columns in the imported source",
    "assessments_present": "per reviewer: questions with a COMPLETED answer",
    "status_counts": "per reviewer: records by status (a reviewer x question pair can have several records only "
                     "when the reviewer submitted more than once)",
    "completion_rate": "per reviewer: COMPLETED questions / questions in package",
    "both_completed": "questions COMPLETED by both compared reviewers (the denominator for agreement)",
    "agreements": "both-completed questions with the same relationship",
    "disagreements": "both-completed questions with different relationships (a missing answer is never counted)",
    "agreement_rate": "agreements / both_completed",
    "cohen_kappa": "Cohen's kappa of the two reviewers' relationships over the both-completed questions "
                   "(semantic_eval.cohen_kappa); chance agreement from each reviewer's own label distribution",
    "label_distribution": "per reviewer: COMPLETED answers by relationship",
    "confidence_distribution": "per reviewer: COMPLETED answers by stated confidence",
    "issues": "records that are not COMPLETED, with the reason",
}


def metrics(records, subset, a, b):
    rows = compare(records, subset, a, b)
    both = [r for r in rows if r["comparison"] in ("AGREE", "DISAGREE")]
    agree = sum(1 for r in both if r["comparison"] == "AGREE")
    per = {}
    for rev in (a, b):
        recs = [r for r in records if r["reviewer_id"] == rev and r["question_id"] in set(subset)]
        done = [r for r in recs if r["status"] == "COMPLETED"]
        per[rev] = {"assessments_present": len({r["question_id"] for r in done}),
                    "status_counts": dict(Counter(r["status"] for r in recs)),
                    "completion_rate": round(len({r["question_id"] for r in done}) / len(subset), 4) if subset else None,
                    "label_distribution": dict(Counter(r["relationship"]["code"] for r in done)),
                    "confidence_distribution": dict(Counter(r["confidence"]["code"] or "NOT_GIVEN" for r in done)),
                    "reviewer_source": recs[0]["reviewer_source"] if recs else None,
                    "imported": bool(recs)}
    kappa = se.cohen_kappa([r[a]["label"] for r in both], [r[b]["label"] for r in both]) if both else None
    found = {r["question_id"] for r in records if r["status"] != "NOT_IN_SOURCE"}
    return {"reviewers": [a, b], "questions_in_package": len(subset),
            "questions_found_in_source": len(found & set(subset)),
            "per_reviewer": per, "both_completed": len(both), "agreements": agree, "disagreements": len(both) - agree,
            "agreement_rate": round(agree / len(both), 4) if both else None,
            "cohen_kappa": kappa,
            "unavailable": {k: v for k, v in {
                "agreement_rate": None if both else "no question was completed by both reviewers",
                "cohen_kappa": None if kappa is not None else (
                    "no question was completed by both reviewers" if not both else
                    "undefined: both reviewers used one and the same relationship throughout")}.items() if v},
            "disagreement_questions": [r["question_id"] for r in both if r["comparison"] == "DISAGREE"],
            "issues": [{"question_id": r["question_id"], "reviewer_id": r["reviewer_id"], "status": r["status"],
                        "issues": r["issues"]} for r in records
                       if r["reviewer_id"] in (a, b) and r["status"] != "COMPLETED"],
            "counts_towards_gate": False,
            "definitions": METRIC_DEFINITIONS}


EXPORT_COLUMNS = ["question_id", "question_number", "reviewer_id", "submission", "status", "relationship_code",
                  "relationship_raw", "confidence_code", "confidence_raw", "reasoning", "reviewer_source",
                  "source_file", "source_sheet", "source_row", "submitted_at", "record_uid"]


def export_csv(records, reviewers=None):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    w.writeheader()
    for r in records:
        if reviewers and r["reviewer_id"] not in reviewers:
            continue
        p = r["provenance"]
        w.writerow({"question_id": r["question_id"], "question_number": r["question_number"],
                    "reviewer_id": r["reviewer_id"], "submission": r["submission"], "status": r["status"],
                    "relationship_code": r["relationship"]["code"] or "", "relationship_raw": r["relationship"]["raw"] or "",
                    "confidence_code": r["confidence"]["code"] or "", "confidence_raw": r["confidence"]["raw"] or "",
                    "reasoning": r["reasoning"] or "", "reviewer_source": r["reviewer_source"],
                    "source_file": p["file"], "source_sheet": p["sheet"], "source_row": p["row"],
                    "submitted_at": p["submitted_at"] or "", "record_uid": r["record_uid"]})
    return buf.getvalue()
