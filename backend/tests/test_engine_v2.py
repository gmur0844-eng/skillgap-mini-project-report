"""
Engine 2.0: full ESCO store, occupation matching, prefLabel precedence, coverage relation/depth,
topic hierarchy, knowledge-graph consistency, semantic provider contract (schema, retry, cache,
fallback), and the semantic hard cases as DATA (no code path names them).
"""
import csv
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine import esco_full as ef  # noqa: E402
from app.knowledge_engine import industry as ind  # noqa: E402
from app.knowledge_engine import intelligence as intel  # noqa: E402
from app.knowledge_engine import semantic_provider as sp  # noqa: E402

S = "http://data.europa.eu/esco/skill/"
O = "http://data.europa.eu/esco/occupation/"
I = "http://data.europa.eu/esco/isco/"


def _csv(rows, cols):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    return buf.getvalue()


def _zip(tables):
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    with zipfile.ZipFile(tmp.name, "w") as z:
        for name, text in tables.items():
            z.writestr(name, text)
    return tmp.name


SKILL_COLS = ["conceptType", "conceptUri", "skillType", "reuseLevel", "preferredLabel", "altLabels", "hiddenLabels", "status",
              "modifiedDate", "scopeNote", "definition", "inScheme", "description"]


def _fixture(extra_broader=()):
    skills = [
        {"conceptUri": S + "a", "preferredLabel": "alpha query language", "altLabels": "AQL\nalpha querying", "skillType": "knowledge",
         "reuseLevel": "sector-specific", "status": "released", "modifiedDate": "2024-01-01", "description": "d"},
        {"conceptUri": S + "a", "preferredLabel": "alpha query language", "altLabels": "AQL\nalpha querying", "skillType": "knowledge",
         "reuseLevel": "sector-specific", "status": "released", "modifiedDate": "2023-01-01", "description": "old"},
        {"conceptUri": S + "b", "preferredLabel": "data stores", "altLabels": "AQL\nstores of data", "skillType": "knowledge",
         "status": "released", "modifiedDate": "2024-01-01"},
        {"conceptUri": S + "c", "preferredLabel": "beta tool", "altLabels": "bt kit", "skillType": "skill/competence",
         "status": "released", "modifiedDate": "2024-01-01"},
        {"conceptUri": S + "d", "preferredLabel": "gamma", "altLabels": "shared name", "status": "released"},
        {"conceptUri": S + "e", "preferredLabel": "delta", "altLabels": "shared name", "status": "released"},
    ]
    groups = [{"conceptType": "SkillGroup", "conceptUri": S + "g1", "preferredLabel": "information skills", "code": "S1",
               "status": "released"}]
    occs = [{"conceptType": "Occupation", "conceptUri": O + "o1", "iscoGroup": "2511", "preferredLabel": "systems analyst",
             "altLabels": "human resources manager", "status": "released", "code": "2511.1"},
            {"conceptType": "Occupation", "conceptUri": O + "o2", "iscoGroup": "2511", "preferredLabel": "account managers",
             "status": "released", "code": "2511.2"},
            {"conceptType": "Occupation", "conceptUri": O + "o3", "iscoGroup": "2511", "preferredLabel": "accounting manager",
             "status": "released", "code": "2511.3"}]
    isco = [{"conceptType": "ISCOGroup", "conceptUri": I + "C2", "code": "2", "preferredLabel": "Professionals"},
            {"conceptType": "ISCOGroup", "conceptUri": I + "C2511", "code": "2511", "preferredLabel": "Systems analysts"}]
    br_skill = [{"conceptType": "KnowledgeSkillCompetence", "conceptUri": S + u, "broaderType": "SkillGroup", "broaderUri": S + "g1"}
                for u in "abcde"] + list(extra_broader)
    br_occ = [{"conceptType": "Occupation", "conceptUri": O + o, "broaderType": "ISCOGroup", "broaderUri": I + "C2511"} for o in ("o1", "o2", "o3")] + \
             [{"conceptType": "ISCOGroup", "conceptUri": I + "C2511", "broaderType": "ISCOGroup", "broaderUri": I + "C2"}]
    osr = [{"occupationUri": O + "o1", "relationType": "essential", "skillUri": S + "a"},
           {"occupationUri": O + "o1", "relationType": "optional", "skillUri": S + "c"},
           {"occupationUri": O + "o1", "relationType": "essential", "skillUri": S + "missing"}]
    ssr = [{"originalSkillUri": S + "c", "relationType": "essential", "relatedSkillUri": S + "a"}]
    bcols = ["conceptType", "conceptUri", "conceptLabel", "broaderType", "broaderUri", "broaderLabel"]
    tables = {
        "skills_en.csv": _csv([{**r, "conceptType": "KnowledgeSkillCompetence"} for r in skills], SKILL_COLS),
        "skillGroups_en.csv": _csv(groups, ["conceptType", "conceptUri", "preferredLabel", "altLabels", "hiddenLabels", "status",
                                            "modifiedDate", "scopeNote", "inScheme", "description", "code"]),
        "occupations_en.csv": _csv(occs, ["conceptType", "conceptUri", "iscoGroup", "preferredLabel", "altLabels", "hiddenLabels",
                                          "status", "modifiedDate", "regulatedProfessionNote", "scopeNote", "definition",
                                          "inScheme", "description", "code", "naceCode"]),
        "ISCOGroups_en.csv": _csv(isco, ["conceptType", "conceptUri", "code", "preferredLabel", "status", "altLabels", "inScheme",
                                         "description"]),
        "broaderRelationsSkillPillar_en.csv": _csv(br_skill, bcols),
        "broaderRelationsOccPillar_en.csv": _csv(br_occ, bcols),
        "occupationSkillRelations_en.csv": _csv(osr, ["occupationUri", "occupationLabel", "relationType", "skillType", "skillUri", "skillLabel"]),
        "skillSkillRelations_en.csv": _csv(ssr, ["originalSkillUri", "originalSkillType", "relationType", "relatedSkillType", "relatedSkillUri"]),
        "skillsHierarchy_en.csv": _csv([], ["Level 0 URI"]),
        "conceptSchemes_en.csv": _csv([{"conceptType": "ConceptScheme", "conceptSchemeUri": "x", "preferredLabel": "p", "hasTopConcept": "a, b"}],
                                      ["conceptType", "conceptSchemeUri", "preferredLabel", "title", "status", "description", "hasTopConcept"]),
        "dictionary_en.csv": _csv([], ["filename", "data header", "property", "description"]),
    }
    t, m = ef.read_classification(_zip(tables))
    return ef.build_store(t, m)


def test_full_store_counts_dedupe_and_dangling_relations_are_reported():
    store, audit = _fixture()
    assert audit["counts"]["skills"] == 5 and audit["duplicate_rows_collapsed"]["skills_en.csv"] == 1
    assert store["skills"][S + "a"]["description"] == "d"  # latest modifiedDate kept
    assert audit["integrity"]["dangling_references_by_file"]["occupationSkillRelations_en.csv"] == 1
    assert store["occupations"][O + "o1"]["essential_skills"] == [S + "a"]
    assert store["skill_skill"] == [{"skill_uri": S + "c", "related_skill_uri": S + "a", "relation": "essential"}]
    assert [g["code"] for g in ef.isco_path(store, O + "o1")] == ["2511", "2"]


def test_broader_cycle_detected_not_repaired():
    cyc = [{"conceptType": "SkillGroup", "conceptUri": S + "g1", "broaderType": "KnowledgeSkillCompetence", "broaderUri": S + "a"}]
    _, audit = _fixture(cyc)
    assert audit["integrity"]["skill_pillar_broader_cycles"] >= 1


def test_skill_groups_are_not_matching_targets_and_pref_label_precedence():
    store, _ = _fixture()
    vocab, vaudit = ef.skill_vocabulary(store)
    assert S + "g1" not in vocab["concepts"] and vaudit["reconstruction_scope"] == "FULL_TAXONOMY"
    terms, label_index = ind.build_vocabulary(vocab)
    cfg = {"esco_semantic_min_similarity": 0.5, "ambiguous_gap": 0.03}
    mentions = [{"normalized_text": "aql", "raw_mention": "AQL", "method": "alias"},
                {"normalized_text": "alpha query language", "raw_mention": "alpha query language", "method": "exact_label"},
                {"normalized_text": "shared name", "raw_mention": "shared name", "method": "alias"}]
    maps = ind.map_skills(mentions, vocab, label_index, lambda: None, cfg)
    # "AQL" is an altLabel of two concepts, prefLabel of none -> AMBIGUOUS
    assert maps["aql"]["status"] == "AMBIGUOUS"
    assert maps["alpha query language"]["status"] == "EXACT" and maps["alpha query language"]["skill_category"] == "KNOWLEDGE"
    assert maps["shared name"]["status"] == "AMBIGUOUS"


def test_pref_label_wins_over_other_concepts_alt_label():
    store, _ = _fixture()
    store["skills"][S + "b"]["alt_labels"].append("beta tool")
    vocab, _ = ef.skill_vocabulary(store)
    _, label_index = ind.build_vocabulary(vocab)
    maps = ind.map_skills([{"normalized_text": "beta tool", "raw_mention": "beta tool", "method": "exact_label"}], vocab,
                          label_index, lambda: None, {"esco_semantic_min_similarity": 0.5, "ambiguous_gap": 0.03})
    m = maps["beta tool"]
    assert m["status"] == "EXACT" and m["esco_uri"] == S + "c"
    assert [a["uri"] for a in m["alternative_concepts"]] == [S + "b"]


def test_occupation_matching_rules():
    store, _ = _fixture()
    idx = ef.occupation_index(store)
    assert ef.match_occupation("Systems Analyst", idx)["status"] == "OCCUPATION_EXACT"
    r = ef.match_occupation("Human Resource Manager", idx)  # plural-only variant of an altLabel
    assert r["status"] == "OCCUPATION_VARIANT" and r["occupation_uri"] == O + "o1"
    assert ef.match_occupation("Account Manager", idx)["occupation_uri"] == O + "o2"  # never "accounting manager"
    c = ef.match_occupation("Senior Systems Analyst Intern", idx)
    assert c["status"] == "OCCUPATION_CANDIDATE" and not c["established"] and c["uncovered_title_words"] == ["senior", "intern"]
    assert ef.match_occupation("Co-Founder", idx)["status"] == "OCCUPATION_UNMAPPED"
    assert ef.match_occupation("Systems Analyst - City Office", idx)["status"] == "OCCUPATION_EXACT"


def test_mention_relation_positions():
    rel = lambda text, label: intel.mention_relation(text, (text.index(label), text.index(label) + len(label)), 8)
    assert rel("AQL", "AQL") == "DIRECT"
    assert rel("Joins, AQL, views", "AQL") == "DIRECT"
    assert rel("Introduction to AQL", "AQL") == "PARTIAL"
    assert rel("AQL injection attacks", "AQL") == "RELATED"
    assert rel("the course discusses how a long list of many things including AQL can be used later", "AQL") == "INCIDENTAL"


def test_coverage_levels_from_evidence():
    topics = {f"t{i}": {"topic_uid": f"t{i}", "doc_id": "D", "course_uid": "c1", "unit_label": f"U{i % 2}", "page_number": 1,
                        "clean_text": txt} for i, txt in enumerate(["AQL", "AQL injection", "Advanced AQL", "AQL"])}
    courses = {"c1": {"course_code": "X1"}, "c2": {"course_code": "X2"}}
    skills = {"k": {"label": "alpha"}, "absent": {"label": "none"}}
    ms = [{"source_uid": t, "skill_key": "k", "span": [v["clean_text"].index("AQL"), v["clean_text"].index("AQL") + 3],
           "sense_established": True, "raw_mention": "AQL"} for t, v in topics.items()]
    cfg = {"max_item_words": 8, "substantial_min_topics": 3, "substantial_min_units": 2}
    rows = {r["skill_key"]: r for r in intel.coverage_depth(ms, topics, courses, "D", skills, [], [], cfg)}
    assert rows["k"]["coverage_level"] == "SUBSTANTIAL" and rows["k"]["relation_counts"]["RELATED"] == 1
    assert rows["absent"]["coverage_level"] == "ABSENT"
    only_related = [m for m in ms if m["source_uid"] == "t1"]
    r = intel.coverage_depth(only_related, topics, courses, "D", {"k": skills["k"]}, [], [], cfg)[0]
    assert r["coverage_level"] == "MENTION"  # "AQL injection" never counts as covering AQL
    # progression: covered in a course and in its prerequisite -> ADVANCED
    topics["t9"] = {"topic_uid": "t9", "doc_id": "D", "course_uid": "c2", "unit_label": "U", "page_number": 2, "clean_text": "AQL"}
    ms2 = [ms[0], {"source_uid": "t9", "skill_key": "k", "span": [0, 3], "sense_established": True, "raw_mention": "AQL"}]
    r = intel.coverage_depth(ms2, topics, courses, "D", {"k": skills["k"]}, [], [{"source_uid": "c1", "target_uid": "c2"}], cfg)[0]
    assert r["coverage_level"] == "ADVANCED"


def test_topic_hierarchy_needs_explicit_head():
    base = {"course_uid": "c", "unit_label": "U", "doc_id": "D", "page_number": 1}
    topics = [{**base, "topic_uid": "1", "clean_text": "Sorting: bubble sort", "source_line": "Sorting: bubble sort, insertion sort, merge sort"},
              {**base, "topic_uid": "2", "clean_text": "insertion sort", "source_line": "Sorting: bubble sort, insertion sort, merge sort"},
              {**base, "topic_uid": "3", "clean_text": "apples", "source_line": "apples, oranges, pears"}]
    rows, stats = intel.topic_hierarchy(topics, {"max_head_words": 8, "max_item_words": 6, "structural_head_min_courses": 5})
    assert [r["child_text"] for r in rows] == ["bubble sort", "insertion sort", "merge sort"]
    assert {r["parent_text"] for r in rows} == {"Sorting"} and rows[1]["child_topic_uid"] == "2"
    assert stats["lines_without_head"] == 1  # commas alone never create a hierarchy


def test_graph_consistency_checks():
    nodes = [{"node_id": x, "node_type": "T", "label": x} for x in "abcd"]
    e = lambda s, r, t: {"edge_id": s + r + t, "source": s, "relationship": r, "target": t, "method": "m", "evidence_status": "X"}
    edges = [e("a", "SAME_AS", "b"), e("a", "PARENT_OF", "b"), e("c", "PARENT_OF", "c"), e("a", "PREREQUISITE_OF", "d"),
             e("d", "PREREQUISITE_OF", "a"), e("a", "SAME_AS", "b"), e("a", "RELATED_TO", "zz")]
    c = intel.graph_consistency(nodes, edges)["checks"]
    assert c["duplicate_edges"] == 1 and c["dangling_edges"] == 1 and c["self_parent_or_self_prerequisite"] == 1
    assert c["same_as_not_symmetric"] == 1 and c["contradictions"] >= 1 and c["prerequisite_cycles"] >= 1
    assert c["parent_child_missing_inverse"] >= 1


class _FakeProvider:
    name = "fake"
    kind = "http"

    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), 0

    def describe(self):
        return {"provider": "fake", "model": "fake-1", "model_version": "1"}

    def complete(self, prompt, schema=None):
        self.calls += 1
        self.last_schema = schema
        return self.outputs.pop(0)


def _cand(**kw):
    return {"kind": "ALIAS_SENSE", "left": "X", "right": "Y", "left_context": "ctx", "rule_relationship": "AMBIGUOUS", **kw}


def test_fallback_provider_is_explicit_and_cached():
    with tempfile.TemporaryDirectory() as d:
        a = sp.Adjudicator({"semantic_ai": {}}, d, "run1", providers=[])
        r1 = a.decide(_cand())
        assert a.status == "AI_PROVIDER_UNAVAILABLE" and r1["decision_state"] == "RULE_VERDICT_NO_MODEL"
        assert r1["relationship"] == "AMBIGUOUS" and "AI_PROVIDER_UNAVAILABLE" in r1["uncertainty"]
        assert r1["is_human_validated"] is False and r1["score_is_confidence"] is False
        b = sp.Adjudicator({"semantic_ai": {}}, d, "run2", providers=[])
        r2 = b.decide(_cand())
        assert r2["from_cache"] and r2["decision_id"] == r1["decision_id"] and r2["output_hash"] == r1["output_hash"]


def test_model_output_schema_validated_retried_then_review_required():
    good = json.dumps({"relationship": "UNRELATED", "reason": "different sense", "evidence": ["momentum"], "uncertainty": "low context"})
    with tempfile.TemporaryDirectory() as d:
        fake = _FakeProvider(["not json", good])
        a = sp.Adjudicator({"semantic_ai": {"max_retries": 2}}, d, "r", providers=[(fake, {"available": True})])
        r = a.decide(_cand())
        assert r["decision_state"] == "MODEL_SUGGESTED" and r["relationship"] == "UNRELATED" and r["attempts"] == 2
        bad = _FakeProvider(['{"relationship": "SYNONYM"}'] * 5)
        b = sp.Adjudicator({"semantic_ai": {"max_retries": 1}}, d + "/b", "r", providers=[(bad, {"available": True})])
        r = b.decide(_cand(left="Z"))
        assert r["decision_state"] == "REVIEW_REQUIRED" and r["relationship"] == "INSUFFICIENT_EVIDENCE" and bad.calls == 2
    assert sp.validate_decision({"relationship": "SAME_CONCEPT", "reason": "r", "evidence": [], "uncertainty": "u"}) == []
    assert sp.validate_decision({"relationship": "SAME"}) != []


def test_semantic_hard_cases_are_test_data_not_code():
    cases = json.loads((ROOT / "data/evaluation/semantic_hard_cases_v2.json").read_text())
    assert len(cases["cases"]) >= 16
    src = "".join((ROOT / "backend/app/knowledge_engine" / f).read_text() for f in
                  ("esco_full.py", "intelligence.py", "intelligence_stage.py", "semantic_provider.py"))
    import re
    for c in cases["cases"]:
        for term in (c["left"], c["right"]):
            cond = re.compile(r"(==|!=|\bin\s*[\(\[\{]|startswith\(|endswith\()\s*[\"']" + re.escape(term) + r"[\"']", re.IGNORECASE)
            assert not cond.search(src), term


def test_lexical_fallback_never_maps_a_word_to_a_longer_label_containing_it():
    from app.knowledge_engine.config import load_config
    from app.knowledge_engine.semantic_backend import get_backend
    store, _ = _fixture()
    store["skills"][S + "c"]["alt_labels"].append("zeta beta store")
    vocab, _ = ef.skill_vocabulary(store)
    _, label_index = ind.build_vocabulary(vocab)
    cfg = load_config()
    maps = ind.map_skills([{"normalized_text": "zeta", "raw_mention": "Zeta", "method": "technical_token"}], vocab, label_index,
                          lambda: get_backend(cfg["semantic_backend"])[0], {"esco_semantic_min_similarity": 0.3, "ambiguous_gap": 0.0})
    m = maps["zeta"]
    assert m["status"] == "UNMAPPED" and m["esco_uri"] is None
    assert m["candidates"][0]["lexical_relation"] == "CONTAINED_IN_LONGER_LABEL"


def test_structural_heads_are_not_parent_topics():
    rows = []
    for i in range(6):
        rows.append({"course_uid": f"c{i}", "unit_label": "U", "doc_id": "D", "page_number": 1, "topic_uid": f"t{i}",
                     "clean_text": "a", "source_line": "Module II: alpha one, beta two"})
    rows.append({"course_uid": "c0", "unit_label": "U", "doc_id": "D", "page_number": 1, "topic_uid": "x",
                 "clean_text": "x", "source_line": "Trees: binary trees, heaps"})
    out, stats = intel.topic_hierarchy(rows, {"max_head_words": 8, "max_item_words": 6, "structural_head_min_courses": 5})
    assert {r["parent_text"] for r in out} == {"Trees"} and stats["head_is_structural_label"] == 6


def test_schema_is_sent_and_rejected_raw_output_is_kept():
    bad = _FakeProvider(['{"relationship": "SAME_CONCEPT", "reason": "r", "evidence": [], "alternatives": [], "uncertainty": 0.2}'] * 3)
    with tempfile.TemporaryDirectory() as d:
        a = sp.Adjudicator({"semantic_ai": {"max_retries": 1}}, d, "r", providers=[(bad, {"available": True})])
        r = a.decide(_cand(left="W"))
    assert bad.last_schema["properties"]["uncertainty"]["type"] == "string"
    assert r["decision_state"] == "REVIEW_REQUIRED"
    assert any("raw output" in x for errs in r["validation_errors"] for x in errs)
    assert "do not use numbers" in sp.build_prompt(_cand())


class _DownProvider(_FakeProvider):
    def complete(self, prompt, schema=None):
        self.calls += 1
        raise ConnectionError("endpoint down")


def test_no_model_text_is_model_failure_not_a_verdict():
    down = _DownProvider([])
    with tempfile.TemporaryDirectory() as d:
        a = sp.Adjudicator({"semantic_ai": {"max_retries": 1}}, d, "r", providers=[(down, {"available": True})])
        r = a.decide(_cand(left="V"))
    assert r["decision_state"] == "MODEL_FAILURE" and r["relationship"] == "INSUFFICIENT_EVIDENCE"
    assert r["rejected_raw_outputs"] == [] and down.calls == 2


def test_decision_records_schema_version_latency_tokens_and_candidate_id():
    good = json.dumps({"relationship": "RELATED", "reason": "r", "evidence": ["ctx"], "alternatives": [], "uncertainty": "u"})
    fake = _FakeProvider([good])
    fake.last_meta = {"prompt_tokens": 11, "output_tokens": 7}
    with tempfile.TemporaryDirectory() as d:
        a = sp.Adjudicator({"semantic_ai": {}}, d, "r", providers=[(fake, {"available": True})])
        r = a.decide(_cand(left="U", candidate_id="cand:x"))
    assert r["schema_version"] == sp.SCHEMA_VERSION and r["candidate_id"] == "cand:x"
    assert r["tokens"] == {"prompt_tokens": 11, "output_tokens": 7} and r["latency_s"] >= 0


def test_evidence_grounding_check():
    sys.path.insert(0, str(ROOT / "scripts" / "semantic"))
    import analyze_frozen_run as an
    d = {"left": "X", "left_context": "Web Programming, TypeScript", "right": "Y", "right_context": "a framework",
         "evidence": ["web programming", "a framework"]}
    assert an.grounding(d)[0] == "ALL_GROUNDED"
    assert an.grounding({**d, "evidence": ["invented quote"]})[0] == "UNGROUNDED"
    assert an.grounding({**d, "evidence": []})[0] == "NO_EVIDENCE"


def test_v3_sentence_window_always_contains_the_mention():
    from app.knowledge_engine import semantic_v3 as v3
    long = "Intro. " + "word " * 120 + "data privacy" + " tail" * 80 + ". Next sentence here."
    i = long.index("data privacy")
    cur, prev, nxt = v3.sentence_at(long, i, i + len("data privacy"))
    assert "data privacy" in cur and len(cur) <= 330 and prev == "Intro." and nxt.startswith("Next")
    short = "We need SQL. Also Python!"
    cur, prev, nxt = v3.sentence_at(short, 8, 11)
    assert cur == "We need SQL." and nxt == "Also Python!"
