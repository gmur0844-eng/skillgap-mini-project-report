"""adjudicate-v4: an opt-in prompt for the frozen experiment. Production keeps adjudicate-v3 (recorded decisions and
their replay unchanged), the validator is v3's, the prompt states every rule the validator applies, and it names no
benchmark pair (it was designed with development labels in view, and must not carry their answers)."""
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import semantic_provider as sp  # noqa: E402
from app.knowledge_engine import semantic_v3 as v3  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CANDS = ROOT / "data/semantic_runs/qwen-270-v3/candidates.json"
BENCH = ROOT / "data/evaluation/semantic_benchmark_v1/benchmark.json"


def _candidate():
    if CANDS.exists():
        return json.loads(CANDS.read_text())[0]
    return {"question": "q", "left": "L", "right": "R", "kind": "ALIAS_SENSE", "right_concept": {},
            "left_items": [{"id": "L1", "source_type": "SOURCE_TEXT", "text": "a line"}],
            "right_items": [{"id": "R1", "source_type": "ESCO_DESCRIPTION", "text": "desc"}],
            "metadata_items": [{"id": "M1", "source_type": "TAXONOMY_METADATA", "text": "meta"}]}


def test_v4_is_opt_in_and_production_stays_on_v3():
    cfg = json.loads((ROOT / "backend/app/knowledge_engine/engine_config.json").read_text())
    assert cfg["semantic_ai"]["prompt_version"] == "adjudicate-v3"
    p3, p4 = sp.protocol_for("adjudicate-v3"), sp.protocol_for("adjudicate-v4")
    assert (p3.prompt_version, p4.prompt_version) == ("adjudicate-v3", "adjudicate-v4")
    assert p4.post_validate is v3.validate_decision and p4.schema_version == p3.schema_version
    c = _candidate()
    assert p4.hashes(c) == p3.hashes(c)            # same frozen inputs
    assert p3.build_prompt(c) == v3.build_prompt(c)  # v3 prompt untouched


def test_v4_states_every_rule_the_validator_applies():
    text = v3.build_prompt_v4(_candidate())
    for rule in ("at least one SOURCE CONTEXT item", "also need at least one CONCEPT CONTEXT item",
                 "direction_justification", "ESCO_HIERARCHY, ESCO_RELATION, COURSE_TITLE, UNIT_TITLE or LEARNING_OUTCOME",
                 "SOURCE_TEXT or JOB_TITLE", "Never cite CANDIDATE-GENERATION METADATA", "exact words"):
        assert rule in text, rule
    assert set(v3.DIRECTIONAL_TYPES) == {"ESCO_HIERARCHY", "ESCO_RELATION", "COURSE_TITLE", "UNIT_TITLE",
                                         "LEARNING_OUTCOME"}
    assert set(v3.MEANING_RELATIONS) == {"SAME_CONCEPT", "PARENT", "CHILD", "RELATED", "PARTIAL_OVERLAP"}


def test_v4_instructions_name_no_benchmark_pair():
    if not BENCH.exists():
        return
    bench = json.loads(BENCH.read_text())
    bench = bench.get("cases", bench) if isinstance(bench, dict) else bench
    fixed = (v3.DECISION_PROCEDURE_V4 + v3.EVIDENCE_RULES_V4).lower()
    leaked = sorted({t for b in bench for t in (b["left_text"], b["right_concept"])
                     if len(t) > 3 and f" {t.lower()} " in f" {fixed} "})
    assert leaked == [], leaked


def test_scoring_keeps_development_and_independent_references_apart(tmp_path):
    spec = importlib.util.spec_from_file_location("score", ROOT / "scripts/semantic/score_against_reviewers.py")
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)
    pkg = ROOT / "data/evaluation/semantic_gold/computer-science-and-engineering/v1"
    if not (pkg / "responses").exists():
        return
    refs = sc.references(pkg, "R02", "R03")
    assert "not independent labels" in refs["DEVELOPMENT"]["what"] and len(refs["DEVELOPMENT"]["labels"]) == 45
    assert refs["INDEPENDENT"]["labels"] is None and refs["INDEPENDENT"]["what"].startswith("PENDING")
