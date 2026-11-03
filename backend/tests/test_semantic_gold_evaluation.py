"""Independent semantic evaluation: agreement, adjudication, gold, metrics, critical errors, gate v2."""
import json
import unittest
from collections import Counter
from pathlib import Path

from app.knowledge_engine import semantic_eval as se

REPO = Path(__file__).resolve().parents[2]


def cases(n):
    return [{"benchmark_id": f"c{i}", "kind": "ALIAS_SENSE", "tags": [], "left": "x", "right": "y",
             "evidence_span": {"text": "t"}} for i in range(n)]


class Agreement(unittest.TestCase):
    def test_cohen_kappa_known_values(self):
        self.assertEqual(se.cohen_kappa(list("aabb"), list("aabb")), 1.0)
        self.assertEqual(se.cohen_kappa(list("abab"), list("baba")), -1.0)

    def test_fleiss_kappa_perfect_and_undefined(self):
        self.assertEqual(se.fleiss_kappa([Counter(a=3), Counter(b=3)]), 1.0)
        self.assertIsNone(se.fleiss_kappa([Counter(a=2), Counter(a=3)]))  # unequal rater counts

    def test_measure_depends_on_reviewer_count(self):
        one = se.agreement([{"reviewer": "R1", "labels": {"c0": "RELATED"}}])
        self.assertTrue(one["measure"].startswith("NOT_APPLICABLE"))
        two = se.agreement([{"reviewer": "R1", "labels": {"c0": "RELATED", "c1": "UNRELATED"}},
                            {"reviewer": "R2", "labels": {"c0": "RELATED", "c1": "RELATED"}}])
        self.assertEqual(two["measure"], "COHEN_KAPPA")
        self.assertEqual(two["disagreements"][0]["case"], "c1")
        three = se.agreement([{"reviewer": r, "labels": {"c0": "RELATED"}} for r in ("A", "B", "C")])
        self.assertEqual(three["measure"], "FLEISS_KAPPA")

    def test_model_or_assistant_cannot_be_a_reviewer(self):
        for name in ("assistant", "Claude", "qwen-bot", "", "  "):
            with self.assertRaises(ValueError):
                se.check_reviewer(name)
        self.assertEqual(se.check_reviewer("Dr. A. Rao"), "Dr. A. Rao")


class Gold(unittest.TestCase):
    def test_adjudication_statuses_and_model_answer_never_used(self):
        sets = [{"reviewer": "R1", "labels": {"c0": "RELATED", "c1": "UNRELATED", "c2": "PARENT"}},
                {"reviewer": "R2", "labels": {"c0": "RELATED", "c1": "RELATED", "c2": "CHILD"}}]
        adj = {"adjudicator": "Dr. B", "decisions": {"c1": "UNRELATED", "c2": "SAME_CONCEPT"}}  # c2 choice not a reviewer label
        rows = {r["case_id"]: r for r in se.build_gold(cases(4), sets, adj)}
        self.assertEqual((rows["c0"]["gold"], rows["c0"]["adjudication_status"]), ("RELATED", "UNANIMOUS"))
        self.assertEqual((rows["c1"]["gold"], rows["c1"]["adjudication_status"]), ("UNRELATED", "ADJUDICATED"))
        self.assertEqual((rows["c2"]["gold"], rows["c2"]["adjudication_status"]), (None, "UNRESOLVED"))
        self.assertEqual(rows["c3"]["adjudication_status"], "UNLABELLED")


class Metrics(unittest.TestCase):
    def test_metrics_confusion_and_critical_errors(self):
        cs = cases(6)
        cs[3]["tags"] = ["lexical_collision"]
        gold = {"c0": "SAME_CONCEPT", "c1": "SAME_CONCEPT", "c2": "PARENT", "c3": "UNRELATED", "c4": "AMBIGUOUS", "c5": "CHILD"}
        pred = {"c0": "SAME_CONCEPT", "c1": "RELATED", "c2": "CHILD", "c3": "SAME_CONCEPT", "c4": "RELATED", "c5": None}
        r = se.evaluate_system(cs, gold, pred, {"c3": ["QUOTE_NOT_IN_ITEM:L1"]})
        self.assertEqual(r["accuracy"], round(1 / 6, 4))
        self.assertEqual(r["abstained"], 1)
        e = r["critical_errors"]
        self.assertEqual(e["FALSE_SAME_CONCEPT"], 1)
        self.assertEqual(e["MISSED_SAME_CONCEPT"], 1)
        self.assertEqual(e["WRONG_HIERARCHY_DIRECTION"], 1)
        self.assertEqual(e["LEXICAL_COLLISION"], 1)
        self.assertEqual(e["UNSUPPORTED_TAXONOMY_EVIDENCE"], 1)
        self.assertEqual(e["INSUFFICIENT_CONTEXT_ERROR"], 1)
        self.assertEqual(r["confusion_matrix"]["CHILD"]["NO_PREDICTION"], 1)
        self.assertEqual(len(r["per_case"]), 6)  # every case reported, none selected

    def test_abstention_is_not_a_sense_error(self):
        r = se.evaluate_system(cases(1), {"c0": "RELATED"}, {"c0": "AMBIGUOUS"})
        self.assertNotIn("ALIAS_SENSE_ERROR", r["critical_errors"])
        self.assertEqual(r["definite_predictions"], 0)

    def test_contingency(self):
        a = [{"case_id": "c0", "correct": True}, {"case_id": "c1", "correct": False}, {"case_id": "c2", "correct": False}]
        b = [{"case_id": "c0", "correct": False}, {"case_id": "c1", "correct": True}, {"case_id": "c2", "correct": False}]
        t = se.contingency(a, b)
        self.assertEqual((t["baseline_correct_model_incorrect"], t["baseline_incorrect_model_correct"], t["both_incorrect"]), (1, 1, 1))


class GateV2(unittest.TestCase):
    def gate(self):
        return json.loads((REPO / "data/evaluation/semantic_gate_v2.json").read_text())

    def test_declared_gate_file_matches_config_hash(self):
        cfg = json.loads((REPO / "backend/app/knowledge_engine/engine_config.json").read_text())
        raw = (REPO / "data/evaluation/semantic_gate_v2.json").read_bytes()
        self.assertEqual(se.sha256_bytes(raw), cfg["semantic_promotion_v2"]["gate_sha256"])

    def test_gate_fails_on_a_single_wrong_hierarchy_direction(self):
        n = 90
        cs = cases(n)
        gold = {f"c{i}": ("SAME_CONCEPT" if i < 30 else "UNRELATED" if i < 89 else "PARENT") for i in range(n)}
        pred = dict(gold)
        pred["c89"] = "CHILD"
        res = se.evaluate_system(cs, gold, pred)
        rows = [{"gold": g} for g in gold.values()]
        out = se.apply_gate(self.gate(), rows, {"kappa": None}, res, [{"reviewer": "R1"}])
        self.assertFalse(out["passed"])
        self.assertFalse(out["checks"]["wrong_hierarchy_direction"]["pass"])
        self.assertEqual(out["mode"], "SAFE_MODE")

    def test_gate_pass_promotes_only_classes_meeting_their_own_precision(self):
        n = 90
        cs = cases(n)
        gold = {f"c{i}": ("SAME_CONCEPT" if i < 30 else "UNRELATED" if i < 85 else "RELATED") for i in range(n)}
        pred = dict(gold)
        res = se.evaluate_system(cs, gold, pred)
        out = se.apply_gate(self.gate(), [{"gold": g} for g in gold.values()], {"kappa": None}, res, [{"reviewer": "R1"}])
        self.assertTrue(out["passed"])
        self.assertEqual(out["promotable_classes"], ["SAME_CONCEPT", "UNRELATED"])  # RELATED: only 5 predictions (< 8)

    def test_pending_without_independent_labels(self):
        st = se.pending_status("sha", self.gate(), [])
        self.assertEqual((st["status"], st["mode"]), ("PENDING_INDEPENDENT_LABELS", "SAFE_MODE"))


if __name__ == "__main__":
    unittest.main()
