"""
Golden regression: known-good real pages (CBIT R22, CBIT R22A, AICTE) frozen
as the exact text the parser receives (backend/tests/fixtures/golden/, built
by scripts/evaluation/build_golden_fixtures.py from the BRONZE cache).

For every fixture the parser must still find the course, its title, its
units, its prerequisite statement, the listed topics ATTRIBUTED TO THAT
COURSE, and must not keep the listed non-topics (marks, CO rows, outcome
sentences, bibliography) as topics. Expectations were written by the
assistant from the page text (labelled_by=assistant, human_validated=false).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine.config import load_config
from app.knowledge_engine.noise import TOPIC, classify_topic, clean_topic_text
from app.knowledge_engine.silver import clean_course_title
from app.pipelines.preprocessing.curriculum_structuring import structure_curriculum_pages

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "golden"
TOPICS_CFG = load_config()["topics"]


def _norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#/() -]", " ", (text or "").lower())).strip()


def _label(text):
    return re.sub(r"[\s\-–—:.]", "", (text or "").upper())


def _fixtures():
    return sorted(FIXTURES.glob("*.json"))


def _parse(fixture):
    numbers = sorted(int(n) for n in fixture["pages"])
    pages = [""] * numbers[-1]
    for n in numbers:
        pages[n - 1] = fixture["pages"][str(n)]
    return structure_curriculum_pages(pages)


def _kept_topics(structure, code):
    kept = []
    for t in structure.topics:
        if t.course_code != code:
            continue
        label, _ = classify_topic(t.topic_text, TOPICS_CFG["min_alpha_chars"], TOPICS_CFG["max_words"], source_line=t.source_line)
        if label == TOPIC:
            kept.append((clean_topic_text(t.topic_text), t.module_heading_label))
    return kept


def test_fixtures_present_and_provenanced():
    files = _fixtures()
    assert len(files) >= 4, "golden fixtures missing: run scripts/evaluation/build_golden_fixtures.py"
    for f in files:
        fx = json.loads(f.read_text(encoding="utf-8"))
        assert re.fullmatch(r"[0-9a-f]{64}", fx["source_sha256"])
        assert fx["labelled_by"] == "assistant" and fx["human_validated"] is False
        assert all(text.strip() for text in fx["pages"].values())


def test_golden_pages_keep_their_known_good_structure():
    failures = []
    for f in _fixtures():
        fx = json.loads(f.read_text(encoding="utf-8"))
        exp = fx["expectations"]
        code = exp["course_code"]
        structure = _parse(fx)
        occurrences = [c for c in structure.courses if c.course_code == code]
        if not occurrences:
            failures.append(f"{f.name}: course {code} not found")
            continue
        titles = {clean_course_title(c.course_name or "").lower() for c in occurrences}
        if exp["course_title"].lower() not in titles:
            failures.append(f"{f.name}: title {exp['course_title']!r} not in {titles}")
        kept = _kept_topics(structure, code)
        kept_norm = [_norm(t) for t, _ in kept]
        for topic in exp["expected_topics"]:
            if not any(_norm(topic) in k or k in _norm(topic) for k in kept_norm if len(k) > 3):
                failures.append(f"{f.name}: expected topic {topic!r} not kept for {code}")
        for bad in exp.get("must_not_be_topics", []):
            if any(_norm(bad) == k or (len(_norm(bad)) > 8 and _norm(bad) in k) for k in kept_norm):
                failures.append(f"{f.name}: non-topic {bad!r} kept as a topic")
        units = {_label(m.heading_label) for m in structure.modules if m.course_code == code}
        for unit in exp.get("unit_labels", []):
            if _label(unit) not in units:
                failures.append(f"{f.name}: unit {unit!r} not detected (found {sorted(units)})")
        for topic, unit in exp.get("unit_of_topic", {}).items():
            owners = {_label(u) for t, u in kept if _norm(topic) in _norm(t)}
            if _label(unit) not in owners:
                failures.append(f"{f.name}: {topic!r} not under {unit} (under {owners})")
        if exp.get("prerequisite_contains"):
            stated = [p.text for p in structure.prerequisites if p.course_code == code]
            if not any(exp["prerequisite_contains"].lower() in s.lower() for s in stated):
                failures.append(f"{f.name}: prerequisite not captured (got {stated})")
        if exp.get("extraction_method"):
            methods = set(fx["extraction_methods"].values())
            if exp["extraction_method"] not in methods:
                failures.append(f"{f.name}: expected extraction method {exp['extraction_method']}, got {methods}")
    assert not failures, "\n".join(failures)
