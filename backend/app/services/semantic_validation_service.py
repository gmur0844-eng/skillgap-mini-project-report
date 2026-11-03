"""
Reviewer responses of the semantic relationship validation packages (read side for the API and the app).

A package is data/evaluation/semantic_gold/<discipline>/<version>/ (docs/SEMANTIC_VALIDATION_PLAN.md). Its questions
are the frozen subset's cases, shown with the evidence the reviewer form showed (form_cases.json); responses are the
records stored by app.knowledge_engine.semantic_responses. The assistant's development label of a case is returned
separately as ai_reference (ASSISTANT_DEVELOPMENT_LABEL, never a human judgment) and is never part of any metric.
"""
import json
import tempfile
from pathlib import Path

from app.knowledge_engine import semantic_responses as sr

REPO = Path(__file__).resolve().parents[3]
PACKAGES_ROOT = REPO / "data/evaluation/semantic_gold"


class PackageNotFound(LookupError):
    pass


class InvalidRequest(ValueError):
    pass


def _json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def package_ids():
    return [f"{p.parent.parent.name}/{p.parent.name}" for p in sorted(PACKAGES_ROOT.glob("*/*/MANIFEST.json"))]


def default_package():
    ids = package_ids()
    return ids[0] if ids else None


def _package(package_id):
    pid = package_id or default_package()
    if not pid:
        raise PackageNotFound("no validation package exists under data/evaluation/semantic_gold/")
    if not sr.PACKAGE_ID.match(pid):
        raise InvalidRequest("package must look like <discipline>/<version>, e.g. computer-science-and-engineering/v1")
    d = PACKAGES_ROOT / pid
    man = _json(d / "MANIFEST.json")
    subset = (_json(d / "subset.json") or {}).get("case_ids")
    if man is None or not subset:
        raise PackageNotFound(f"validation package {pid} not found")
    return pid, d, man, subset


def _reviewer(rid):
    if rid is not None and not sr.REVIEWER_ID.match(rid):
        raise InvalidRequest("reviewer ids are letters, digits, '_', '.', '-' (e.g. R02)")
    return rid


def _ai_reference(d):
    doc = _json(d / "assistant_adjudication.json") or {}
    return {c["case_id"]: c.get("label") for c in doc.get("cases", [])}, doc.get("label_source")


def _questions(d, subset):
    cases = {c["case_id"]: c for c in (_json(d / "form_cases.json") or [])}
    ai, ai_source = _ai_reference(d)
    out = []
    for n, qid in enumerate(subset, start=1):
        c = cases.get(qid, {})
        out.append({"question_id": qid, "question_number": c.get("n", n),
                    "concept_a": c.get("concept_a"), "context_a": c.get("context_a") or [],
                    "concept_b": c.get("concept_b"), "description_b": c.get("description_b"),
                    "hierarchy_b": c.get("hierarchy_b"), "context_b": c.get("context_b"),
                    "question": (f"What is the relationship of Concept A ({c.get('concept_a')}) to Concept B "
                                 f"({c.get('concept_b')})?") if c else None,
                    "ai_reference": {"label": ai.get(qid), "label_source": ai_source or "ASSISTANT_DEVELOPMENT_LABEL",
                                     "is_human_judgment": False,
                                     "note": "the assistant's development label; never a reviewer answer, never in "
                                             "any metric"} if ai.get(qid) else None})
    return out


def _label_schema(man):
    choices = {code: f"{letter} — {words}" for letter, words, code in sr.FORM_CHOICES}
    return [{"code": x["code"], "form_choice": choices.get(x["code"]), "meaning": x["meaning"]}
            for x in (man.get("label_schema") or {}).get("labels", [])]


def packages():
    out = []
    for pid in package_ids():
        _, d, man, subset = _package(pid)
        records, files = sr.load(d)
        out.append({"package": pid, "discipline": man.get("discipline"), "questions": len(subset),
                    "reviewers": sorted({r["reviewer_id"] for r in records}), "imports": files,
                    "label_schema_version": man.get("label_schema_version"), "label_schema": _label_schema(man),
                    "independent_label_sets": man.get("review_count", 0), "gold_status": man.get("gold_status")})
    return {"evidence_state": "AVAILABLE" if out else "NOT_PRODUCED", "items": out,
            "reviewer_sources": sr.REVIEWER_SOURCES, "statuses": list(sr.STATUSES)}


def questions(package_id=None):
    pid, d, man, subset = _package(package_id)
    return {"package": pid, "items": _questions(d, subset), "label_schema": _label_schema(man)}


def assessments(package_id=None, reviewer=None, label=None, status=None, question_id=None):
    pid, d, man, subset = _package(package_id)
    _reviewer(reviewer)
    if label is not None and label not in {c for _, _, c in sr.FORM_CHOICES}:
        raise InvalidRequest(f"label must be one of {[c for _, _, c in sr.FORM_CHOICES]}")
    if status is not None and status not in sr.STATUSES:
        raise InvalidRequest(f"status must be one of {list(sr.STATUSES)}")
    records, files = sr.load(d)
    rows = [r for r in records if (reviewer is None or r["reviewer_id"] == reviewer)
            and (label is None or r["relationship"]["code"] == label) and (status is None or r["status"] == status)
            and (question_id is None or r["question_id"] == question_id)]
    return {"package": pid, "total": len(rows), "items": rows, "imports": files}


def assessment(package_id, question_id, reviewer):
    pid, d, man, subset = _package(package_id)
    _reviewer(reviewer)
    if question_id not in subset:
        raise PackageNotFound(f"question {question_id} is not in package {pid}")
    records, _ = sr.load(d)
    rows = [r for r in records if r["question_id"] == question_id and r["reviewer_id"] == reviewer]
    if not rows:
        raise PackageNotFound(f"no imported response of reviewer {reviewer} in package {pid}")
    q = next(x for x in _questions(d, subset) if x["question_id"] == question_id)
    return {"package": pid, "question": q, "records": rows}


def missing(package_id=None, reviewers=("R02", "R03")):
    pid, d, man, subset = _package(package_id)
    records, _ = sr.load(d)
    out = {}
    for rev in reviewers:
        _reviewer(rev)
        by_q = {}
        for r in records:
            if r["reviewer_id"] == rev:
                by_q.setdefault(r["question_id"], []).append(r["status"])
        if not by_q:
            out[rev] = {"imported": False, "not_completed": list(subset)}
            continue
        out[rev] = {"imported": True,
                    "not_completed": [{"question_id": q, "statuses": by_q.get(q, ["NOT_IMPORTED"])}
                                      for q in subset if "COMPLETED" not in by_q.get(q, []) or len(set(by_q[q])) > 1]}
    return {"package": pid, "questions": len(subset), "reviewers": out}


def compare(package_id=None, a="R02", b="R03", outcome=None):
    pid, d, man, subset = _package(package_id)
    _reviewer(a)
    _reviewer(b)
    if a == b:
        raise InvalidRequest("choose two different reviewers")
    if outcome is not None and outcome not in ("AGREE", "DISAGREE", "NOT_COMPARABLE"):
        raise InvalidRequest("outcome must be AGREE, DISAGREE or NOT_COMPARABLE")
    records, files = sr.load(d)
    qs = {q["question_id"]: q for q in _questions(d, subset)}
    rows = [{**r, "question": qs[r["question_id"]]} for r in sr.compare(records, subset, a, b)
            if outcome is None or r["comparison"] == outcome]
    return {"package": pid, "reviewers": [a, b], "items": rows,
            "metrics": sr.metrics(records, subset, a, b), "imports": [f for f in files if f["reviewer_id"] in (a, b)]}


def metrics(package_id=None, a="R02", b="R03"):
    pid, d, man, subset = _package(package_id)
    _reviewer(a)
    _reviewer(b)
    records, _ = sr.load(d)
    return {"package": pid, **sr.metrics(records, subset, a, b)}


def export_csv(package_id=None, reviewers=None):
    pid, d, man, subset = _package(package_id)
    for r in reviewers or ():
        _reviewer(r)
    records, _ = sr.load(d)
    return sr.export_csv(records, set(reviewers) if reviewers else None)


def import_upload(package_id, filename, content, source, reviewers=None, note=None):
    """An uploaded .xlsx/.csv of form responses -> stored records (see semantic_responses.store)."""
    pid, d, man, subset = _package(package_id)
    suffix = Path(filename or "").suffix.lower()
    if suffix not in (".xlsx", ".csv"):
        raise InvalidRequest("upload the form responses as .xlsx or .csv")
    if source not in sr.REVIEWER_SOURCES:
        raise InvalidRequest(f"source must be one of {sorted(sr.REVIEWER_SOURCES)}")
    for r in reviewers or ():
        _reviewer(r)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(filename).name
        path.write_bytes(content)
        try:
            records, report = sr.parse_source(path, subset, man["package"], source, reviewers, note)
        except Exception as exc:  # an unreadable workbook is the uploader's error, not a server error
            raise InvalidRequest(f"the file could not be read as form responses: {type(exc).__name__}") from exc
        if report["unknown_questions"]:
            raise InvalidRequest(f"the file has questions outside this package: {report['unknown_questions'][:10]}")
        if not records:
            raise InvalidRequest("no responses found in the file" + (f" for {reviewers}" if reviewers else ""))
        stored = sr.store(d, records, report, path, man["benchmark"]["sha256"])
    return {"package": pid, "stored": stored, "records": len(records), "report": report}
