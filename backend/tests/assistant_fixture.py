"""A small synthetic analysis run and a scripted chat model, for the assistant tests (no real data, no real model)."""
import json
from pathlib import Path

RUN_ID = "a" * 16
SHA_T, SHA_R = "t" * 64, "r" * 64


def _jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def build_run(root):
    """gold/<RUN_ID>/... and silver/... under root; returns (gold_root, silver_root)."""
    gold, silver = Path(root) / "gold", Path(root) / "silver"
    d = gold / RUN_ID
    docs = [{"doc_id": "tgt", "role": "TARGET", "institution": "Test College", "programme": "B.E. CSE",
             "curriculum_version": "R1"},
            {"doc_id": "ref", "role": "REFERENCE", "institution": "AICTE", "programme": "Model"}]
    d.mkdir(parents=True)
    (d / "run_report.json").write_text(json.dumps({"run_id": RUN_ID, "documents": docs}))
    (gold / "latest_run.json").write_text(json.dumps({"run_id": RUN_ID}))
    _jsonl(d / "courses.jsonl", [
        {"course_uid": "c:db", "doc_id": "tgt", "course_code": "CS301", "title": "Database Systems", "semester": "V",
         "source_sha256": SHA_T},
        {"course_uid": "c:ref1", "doc_id": "ref", "course_code": "PC10", "title": "Cloud Computing", "semester": "VI",
         "source_sha256": SHA_R, "pages": [2], "first_page": 2},
        {"course_uid": "c:ref2", "doc_id": "ref", "course_code": "PC11", "title": "Data Structures", "semester": "III",
         "source_sha256": SHA_R}])

    def topic(uid, doc, course, code, text, unit="Unit I", page=3, noise="TOPIC"):
        return {"topic_uid": uid, "doc_id": doc, "course_uid": course, "course_code": code, "clean_text": text,
                "raw_text": text, "noise_label": noise, "evidence_status": "EXTRACTED", "unit_label": unit,
                "page_number": page, "extraction_method": "test"}
    _jsonl(silver / "tgt" / SHA_T[:16] / "topics.jsonl", [
        topic("t:1", "tgt", "c:db", "CS301", "relational model and SQL queries"),
        topic("t:2", "tgt", "c:db", "CS301", "normalisation and functional dependencies", "Unit II", 4),
        topic("t:3", "tgt", "c:db", "CS301", "punch cards", "Unit III", 5)])
    _jsonl(silver / "ref" / SHA_R[:16] / "topics.jsonl", [
        topic("r:1", "ref", "c:ref1", "PC10", "containers with docker and container orchestration", page=40),
        topic("r:2", "ref", "c:ref1", "PC10", "NoSQL databases and document stores", page=41),
        topic("r:3", "ref", "c:ref2", "PC11", "binary search trees", page=12)])
    ind = d / "industry"

    def demand(key, label, n, support):
        return {"skill_key": key, "skill_label": label, "posting_count": n, "eligible_postings": 200,
                "support_state": support, "statement": f"{n} of the 200 eligible supplied postings mention this skill"}
    _jsonl(ind / "industry_demand.jsonl", [demand("k:docker", "docker", 31, "HIGH_SUPPORT"),
                                           demand("k:nosql", "NoSQL", 22, "SUPPORTED"),
                                           demand("k:sql", "SQL", 60, "HIGH_SUPPORT"),
                                           demand("k:cobol", "COBOL", 2, "INSUFFICIENT_EVIDENCE")])
    _jsonl(ind / "recommendations.jsonl", [{"skill_key": "k:docker", "skill_label": "docker",
                                            "action_type": "ADD_NEW_TOPIC", "classification": "MISSING",
                                            "target_course_codes": ["CS301"], "support_state": "HIGH_SUPPORT"}])
    _jsonl(d / "intelligence" / "skill_gaps_v2.jsonl", [
        {"skill_key": "k:docker", "skill_label": "docker", "classification_v2": "MISSING", "coverage_level": "ABSENT",
         "support_state": "HIGH_SUPPORT", "evidence_status": "INFERRED", "reason_v2": "not taught"},
        {"skill_key": "k:nosql", "skill_label": "NoSQL", "classification_v2": "PARTIAL", "coverage_level": "MENTION",
         "support_state": "SUPPORTED", "evidence_status": "REVIEW_REQUIRED", "reason_v2": "mentioned once"},
        {"skill_key": "k:sql", "skill_label": "SQL", "classification_v2": "COVERED", "coverage_level": "SUBSTANTIAL",
         "support_state": "HIGH_SUPPORT", "evidence_status": "INFERRED", "reason_v2": "taught"},
        {"skill_key": "k:cobol", "skill_label": "COBOL", "classification_v2": "INSUFFICIENT_EVIDENCE",
         "coverage_level": "ABSENT", "support_state": "INSUFFICIENT_EVIDENCE", "evidence_status": "INFERRED"}])
    pages = ["Semester VI course list", "PC10 Cloud Computing\nUnit I containers with docker\n\nText Books:\n"
             "1. A. Author, Cloud Computing Concepts, Pearson, 2019.\n2. B. Writer and C. Writer, Containers in\n"
             "   Practice, 2nd Edition, Manning, 2021.\n3. lecture notes\nOnline resources:\n"
             "1. Docker docs: https://docs.docker.com/get-started/\nCourse Outcomes:\n1. Deploy a service"]
    bronze = Path(root) / "bronze" / SHA_R[:16]
    bronze.mkdir(parents=True)
    (bronze / "pages.test.json").write_text(json.dumps({"pages": pages}))
    return gold, silver


def load(root):
    from app.services import knowledge_service as ks
    gold, silver = build_run(root)
    return ks.KnowledgeRun(RUN_ID, gold_root=gold, silver_root=silver)


class ScriptedModel:
    """Returns the scripted replies in order; records what it was asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def describe(self):
        return {"provider": "scripted", "model": "test-model"}

    def chat(self, messages, tools=None, json_schema=None, temperature=0.2):
        self.calls.append({"messages": messages, "tools": tools, "json_schema": json_schema})
        if not self.replies:
            raise AssertionError("the model was asked more often than scripted")
        r = self.replies.pop(0)
        if isinstance(r, dict) and ("content" in r or "tool_calls" in r):
            return {"content": r.get("content", ""), "tool_calls": r.get("tool_calls", [])}
        return {"content": r if isinstance(r, str) else json.dumps(r), "tool_calls": []}


def call(name, **arguments):
    return {"content": "", "tool_calls": [{"name": name, "arguments": arguments}]}
