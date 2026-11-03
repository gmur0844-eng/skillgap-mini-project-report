"""Regression tests for the discrepancies found by the full consistency audit (docs/FULL_CONSISTENCY_AUDIT.md)."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine import mapping  # noqa: E402
from app.knowledge_engine.intelligence_stage import reconcile_recommendations  # noqa: E402


from tests.data_requirements import requires_run  # noqa: E402

class ContextGate(unittest.TestCase):
    """Shared words are never enough on their own (topic → reference mapping)."""
    G = {"applications", "concepts"}

    def gate(self, rel, method, text, ctx):
        return mapping.context_gate(rel, method, "MODEL_SUGGESTED" if method != "normalized_text_identity" else "REFERENCE_MAPPED",
                                    text, ctx, 0.12, self.G)

    def test_specific_identity_keeps_reference_mapped(self):
        self.assertEqual(self.gate("SAME_CONCEPT", "normalized_text_identity", "Matrix chain multiplication", 0.01)[0],
                         "REFERENCE_MAPPED")

    def test_single_word_identity_needs_course_context(self):
        self.assertEqual(self.gate("SAME_CONCEPT", "normalized_text_identity", "Concepts", 0.02)[0], "REVIEW_REQUIRED")
        self.assertEqual(self.gate("SAME_CONCEPT", "normalized_text_identity", "Recursion", 0.02)[0], "REVIEW_REQUIRED")
        self.assertEqual(self.gate("SAME_CONCEPT", "normalized_text_identity", "Recursion", 0.18)[0], "REFERENCE_MAPPED")

    def test_generic_word_identity_is_never_enough(self):
        status, why = self.gate("SAME_CONCEPT", "normalized_text_identity", "Applications", 0.27)
        self.assertEqual(status, "REVIEW_REQUIRED")
        self.assertIn("generic", why)

    def test_containment_and_similarity_need_course_context(self):
        # "Network Design" (optimisation course) CHILD of "Network" (ML course): lexical collision
        for rel, method in (("CHILD", "tfidf_cosine+token_containment"), ("PARENT", "tfidf_cosine+token_containment"),
                            ("RELATED", "tfidf_cosine"), ("PARTIAL_OVERLAP", "tfidf_cosine")):
            self.assertEqual(self.gate(rel, method, "Network Design", 0.04)[0], "REVIEW_REQUIRED", rel)
            self.assertEqual(self.gate(rel, method, "Network Design", 0.2)[0], "MODEL_SUGGESTED", rel)
        self.assertEqual(self.gate("CHILD", "tfidf_cosine+token_containment", "x y", None)[0], "REVIEW_REQUIRED")

    def test_generic_words_are_data_driven(self):
        topics = [{"course_uid": f"c{i}", "clean_text": f"Applications of topic{i}"} for i in range(10)]
        topics.append({"course_uid": "c0", "clean_text": "Recursion"})
        g = mapping.generic_words(topics, 0.5)
        self.assertIn("applications", g)
        self.assertNotIn("recursion", g)


class RecommendationReconciliation(unittest.TestCase):
    def _gold(self):
        rec = {"skill_key": "k1", "skill_label": "SQL", "gap_uid": "gap:1", "run_id": "r", "classification": "PARTIAL",
               "support_state": "SUPPORTED", "action_type": "EXPAND_EXISTING_TOPIC", "target_level": "COURSE",
               "target_course_codes": ["C1"], "rule_reasons": ["x"], "uncertainty": []}
        return {"recommendations": [rec], "suppressions": [], "traces": [{"skill_key": "k1", "recommendation": rec,
                                                                             "no_recommendation": None}]}

    def test_recommendation_contradicting_gap_v2_is_withheld(self):
        g = self._gold()
        res = reconcile_recommendations(g, [{"skill_key": "k1", "classification_v2": "COVERED", "coverage_level": "SUBSTANTIAL",
                                             "reason_v2": "2 DIRECT/PARTIAL topics in 2 unit(s)"}])
        self.assertEqual(g["recommendations"], [])
        self.assertEqual(res["withheld_for_classification_conflict"], ["SQL"])
        s = g["suppressions"][0]
        self.assertEqual(s["recommendation_state"], "SUPPRESSED")
        self.assertEqual(s["reasons"][0]["code"], "CLASSIFICATION_CONFLICT_REVIEW_REQUIRED")
        self.assertEqual(s["withheld_recommendation"]["action_type"], "EXPAND_EXISTING_TOPIC")   # nothing lost
        self.assertIsNone(g["traces"][0]["recommendation"])
        self.assertEqual(g["traces"][0]["no_recommendation"]["suppression_uid"], s["suppression_uid"])

    def test_consistent_recommendation_is_kept(self):
        for v2 in ("PARTIAL", "MISSING"):
            g = self._gold()
            reconcile_recommendations(g, [{"skill_key": "k1", "classification_v2": v2, "coverage_level": "INTRODUCTORY",
                                           "reason_v2": "x"}])
            self.assertEqual(len(g["recommendations"]), 1, v2)


class SchemaAndLabels(unittest.TestCase):
    def test_graph_edge_key_is_run_scoped(self):
        sql = (ROOT / "backend/app/db/knowledge_schema_consistency.sql").read_text()
        self.assertIn("PRIMARY KEY (run_id, edge_id)", sql)
        self.assertIn("mapping_kind", sql)

    def test_every_graph_edge_carries_a_mapping_kind(self):
        src = (ROOT / "backend/app/knowledge_engine/intelligence.py").read_text()
        body = src[src.index("def knowledge_graph"):src.index("GRAPH_RELATIONSHIPS")]
        calls = re.findall(r"\bedge\((.*?)\)\n", body, re.S)
        self.assertTrue(calls)
        for c in calls:
            self.assertIn("kind=", c, c[:80])

    def test_overview_gap_label_matches_its_population(self):
        src = (ROOT / "backend/app/services/improvement_service.py").read_text()
        self.assertNotIn("PARTIAL or MISSING with supported demand (gap v2)", src)   # the false wording found by the audit
        self.assertIn("Evidence-supported gaps", src)
        for label in ("Target-curriculum courses", "Target-curriculum topics", "Target-curriculum concepts",
                      "Normalized industry skills eligible for analysis"):
            self.assertIn(label, src)


if __name__ == "__main__":
    unittest.main()


class WithheldRecommendationsApi(unittest.TestCase):
    """A candidate withheld because the coverage measures disagree is listed as withheld, never as issued."""

    def test_withheld_listed_apart_from_issued(self):
        from types import SimpleNamespace
        from app.services import intelligence_service as svc
        sup_conflict = {"skill_key": "sql", "skill_label": "SQL", "evidence_status": "REVIEW_REQUIRED",
                        "reasons": [{"code": "CLASSIFICATION_CONFLICT_REVIEW_REQUIRED", "detail": "measures disagree"}],
                        "withheld_recommendation": {"action_type": "EXPAND_EXISTING_TOPIC"},
                        "gap_v2": {"classification": "COVERED"}}
        sup_thin = {"skill_key": "go", "skill_label": "Go", "reasons": [{"code": "INSUFFICIENT_DEMAND"}]}
        ir = SimpleNamespace(available=True, report={}, rows=lambda name: [],
                             run=SimpleNamespace(run_id="r", report={}, industry={"recommendations": [],
                                                                                  "suppressions": [sup_conflict, sup_thin]}))
        orig = svc._scope
        svc._scope = lambda ir: {"run_id": "r"}
        try:
            out = svc.recommendations(ir)
        finally:
            svc._scope = orig
        self.assertEqual(out["v1"], [])
        self.assertEqual(out["suppressed"], 2)
        self.assertEqual([w["skill_key"] for w in out["withheld_for_review"]], ["sql"])
        self.assertEqual(out["suppressed_by_reason"],
                         {"CLASSIFICATION_CONFLICT_REVIEW_REQUIRED": 1, "INSUFFICIENT_DEMAND": 1})


class MappingAuditAssistantLookup(unittest.TestCase):
    """Assistant readings match course titles case-insensitively and by prefix (titles are truncated in reports)."""

    def test_prefix_and_case(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("tcma", ROOT / "scripts/audit/topic_concept_mapping_audit.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.assistant_reading("Initialization", "PROBLEM SOLVING AND PROGRAMMING USING C", "Machine Learning")[0],
                         "UNRELATED")
        self.assertEqual(mod.assistant_reading("Initialization", "Problem Solving and Programming usi…", "machine learning")[0],
                         "UNRELATED")
        self.assertIsNone(mod.assistant_reading("Initialization", "Compiler Design", "Machine Learning"))
        self.assertIsNone(mod.assistant_reading("Initialization", "", "Machine Learning"))


class GeneralizationAudit(unittest.TestCase):
    """No discipline-specific production logic: the audit script runs and reports zero disallowed hits."""

    def test_audit_runs_clean(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "gen.json"
            r = subprocess.run([sys.executable, str(ROOT / "scripts/audit/generalization_audit.py"), "--out", str(out)],
                               capture_output=True, text=True, cwd=ROOT, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            rep = json.loads(out.read_text())
        self.assertEqual(rep["not_allowed"], [])
        self.assertEqual(rep["ranking_logic"], [])
        self.assertTrue(rep["structural_checks"]["discipline_is_free_text"])


@requires_run("84d7737ccb8e4d87")
class Readiness(unittest.TestCase):
    """System health as product states derived from the run (never a new measurement, never inflated)."""

    @classmethod
    def setUpClass(cls):
        from app.services import improvement_service as im, knowledge_service as ks
        cls.r = im.readiness(ks.load_run("84d7737ccb8e4d87"))

    def test_four_primary_states(self):
        self.assertEqual([p["key"] for p in self.r["primary"]], ["analysis", "evidence", "ai", "traceability"])
        states = {p["key"]: p["state"] for p in self.r["primary"]}
        self.assertEqual(states, {"analysis": "READY", "evidence": "AVAILABLE_WITH_LIMITATIONS", "ai": "ADVISORY",
                                  "traceability": "COMPLETE"})

    def test_limitations_stay_visible(self):
        cov = {c["key"]: c["state"] for c in self.r["coverage"]}
        self.assertEqual(cov["trends"], "NOT_ESTABLISHED")
        self.assertEqual(cov["peers"], "PARTIAL")
        self.assertEqual(cov["occupations"], "PARTIAL")
        for c in self.r["coverage"]:
            if c["state"] not in ("AVAILABLE", "ESTABLISHED"):
                self.assertTrue(c["missing"] and c["why_it_matters"] and c["resolve"], c["key"])

    def test_ai_is_advisory_and_technical_details_are_separate(self):
        self.assertEqual(self.r["ai_interpretation"]["state"], "ADVISORY")
        self.assertIn("pending", self.r["ai_interpretation"]["why"])
        primary_text = json.dumps({k: self.r[k] for k in ("headline", "summary", "primary", "coverage", "what_to_know",
                                                          "ai_interpretation")})
        for internal in ("SAFE_MODE", "effects_blocked", "INTERNAL_DEVELOPMENT", "AI_PROVIDER_REPLAYED", "84d7737c"):
            self.assertNotIn(internal, primary_text)
        self.assertEqual(self.r["technical"]["semantic_mode"], "SAFE_MODE")
        self.assertEqual(self.r["technical"]["run_id"], "84d7737ccb8e4d87")
        self.assertEqual(len(self.r["what_to_know"]), 3)


class EvidenceSenseAndConflicts(unittest.TestCase):
    """Rules found by spot-checking the evidence-expansion run (docs/DATA_EXPANSION_AUDIT.md)."""

    def test_lower_case_word_is_not_an_all_caps_taxonomy_label(self):
        from app.knowledge_engine import industry
        mapping = {"status": "EXACT", "mapping_method": "prefLabel_case_whitespace_normalized", "esco_pref_label": "LESS",
                   "esco_uri": "u"}
        state = industry.sense_check({"normalized_text": "less", "raw_mention": "less", "method": "normalized_label"},
                                     mapping, "spend less time", {}, [])[0]
        self.assertEqual(state, "CASE_SENSE_REVIEW_REQUIRED")
        self.assertNotIn(state, industry.SENSE_ESTABLISHED)
        state = industry.sense_check({"normalized_text": "less", "raw_mention": "LESS", "method": "normalized_label"},
                                     mapping, "Sass or LESS", {}, [])[0]
        self.assertEqual(state, "ESTABLISHED")

    def test_degree_abbreviations_are_qualifications(self):
        from app.knowledge_engine.industry import mention_role
        for text, word in (("BS in Computer Science", "Computer"), ("MS or Ph.D. in Computer Science", "Computer"),
                           ("a quantitative discipline such as Statistics, Computer Science", "Computer")):
            self.assertEqual(mention_role(text, text.find(word)), "QUALIFICATION_REQUIREMENT", text)
        self.assertEqual(mention_role("MS Excel and Python", 13), "SKILL")

    def test_ambiguous_identity_and_course_title_conflict(self):
        from app.knowledge_engine.intelligence_stage import gap_v2, is_confirmed_gap
        gaps = [{"skill_key": k, "skill_label": lab, "gap_uid": k, "classification": "PARTIAL", "support_state": "HIGH_SUPPORT",
                 "reasons": []} for k, lab in (("a", "ml"), ("b", "operating systems"), ("c", "docker"))]
        depth = {k: {"coverage_level": "INTRODUCTORY", "level_reason": "1 topic"} for k in "abc"}
        out = {g["skill_key"]: g for g in gap_v2(gaps, depth, {}, identity_by_key={"a": "AMBIGUOUS"},
                                                  target_titles=[("CS15", "OPERATING SYSTEMS"), ("CS20", "Cloud Computing")])}
        self.assertEqual(out["a"]["classification_v2"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(out["b"]["evidence_status"], "REVIEW_REQUIRED")
        self.assertEqual(out["b"]["review"]["courses"], ["CS15"])
        self.assertFalse(is_confirmed_gap(out["b"]))
        self.assertTrue(is_confirmed_gap(out["c"]))


class DisciplineNameIsNotASkillGap(unittest.TestCase):
    def test_skill_naming_the_discipline(self):
        from app.knowledge_engine.intelligence_stage import gap_v2
        gaps = [{"skill_key": "cs", "skill_label": "computer science", "gap_uid": "g", "classification": "PARTIAL",
                 "support_state": "SUPPORTED", "reasons": []}]
        out = gap_v2(gaps, {"cs": {"coverage_level": "INTRODUCTORY", "level_reason": "x"}}, {},
                     discipline="Computer Science and Engineering")
        self.assertEqual(out[0]["classification_v2"], "INSUFFICIENT_EVIDENCE")
        out = gap_v2(gaps, {"cs": {"coverage_level": "INTRODUCTORY", "level_reason": "x"}}, {}, discipline="Mechanical Engineering")
        self.assertEqual(out[0]["classification_v2"], "PARTIAL")
