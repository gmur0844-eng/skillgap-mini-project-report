"""Occupation resolution v2 on a synthetic ESCO fixture (labels and profiles are invented test data)."""
import unittest

from app.knowledge_engine import esco_full
from app.knowledge_engine import occupation_resolution as occ

CFG = {"occupations_v2": {"min_context_skills": 3, "min_context_overlap": 2, "max_profile_candidates": 3,
                          "min_postings_per_group": 2, "top_n": 5}}
S = {f"s{i}": f"http://esco/skill/s{i}" for i in range(12)}


def occupation(uri, pref, alts=(), ess=(), opt=(), isco="2511"):
    return uri, {"uri": uri, "kind": "occupation", "pref_label": pref, "alt_labels": list(alts), "hidden_labels": [],
                 "isco_code": isco, "broader": [f"isco:{isco}"], "narrower": [],
                 "essential_skills": [S[s] for s in ess], "optional_skills": [S[s] for s in opt]}


def store():
    occs = dict([
        occupation("o:analyst", "data analyst", ess=("s1", "s2", "s3")),
        occupation("o:scientist", "data scientist", ess=("s4", "s5", "s6")),
        occupation("o:foundry", "foundry manager", alts=("process manager",), ess=("s7", "s8"), isco="1321"),
        occupation("o:pm1", "project manager", ess=("s9", "s10")),
        occupation("o:acc1", "accountant", alts=("assistant manager",), ess=("s1", "s11")),
        occupation("o:acc2", "operations assistant", alts=("assistant manager",), ess=("s4", "s5"), isco="4110"),
    ])
    isco = {}
    for code in ("2511", "251", "25", "2", "1321", "132", "13", "1", "4110", "411", "41", "4"):
        isco[f"isco:{code}"] = {"uri": f"isco:{code}", "kind": "isco_group", "code": code, "pref_label": f"group {code}",
                                "broader": [f"isco:{code[:-1]}"] if len(code) > 1 else [], "narrower": []}
    return {"occupations": occs, "isco_groups": isco, "skills": {}}


def posting(uid, title, skills):
    return ({"posting_uid": uid, "job_title": title},
            [{"source_uid": uid, "skill_key": k, "mention_role": "SKILL", "sense_established": True} for k in skills])


SKILLS = {k: {"esco_uri": v, "eligible_for_analytics": True, "label": k} for k, v in S.items()}


def resolve(*items):
    esco_full._SHAPE_CACHE.clear()
    ps = [p for p, _ in items]
    ms = [m for _, ms in items for m in ms]
    rows, summary = occ.resolve(ps, ms, SKILLS, store(), CFG)
    return {r["posting_uid"]: r for r in rows}, summary


class Resolution(unittest.TestCase):
    def test_exact_title_with_agreeing_context_is_established_by_title(self):
        r, _ = resolve(posting("p1", "Data Analyst", ["s1", "s2", "s9"]))
        self.assertEqual((r["p1"]["state"], r["p1"]["established_by"], r["p1"]["context_support"]), ("EXACT", "title", "CONFIRMED"))

    def test_exact_title_contradicted_by_context_becomes_ambiguous(self):
        r, s = resolve(posting("p1", "Data Analyst", ["s4", "s5", "s6"]))
        self.assertEqual(r["p1"]["state"], "AMBIGUOUS")
        self.assertFalse(r["p1"]["established"])
        self.assertEqual(r["p1"]["context_support"], "CONTRADICTED")
        self.assertEqual(s["title_contradicted_by_context"], 1)
        self.assertIn("o:scientist", [c["occupation_uri"] for c in r["p1"]["skill_profile_candidates"]])

    def test_candidate_needs_context_to_be_established(self):
        r, _ = resolve(posting("p1", "Associate Process Manager", ["s9", "s10", "s1"]),
                       posting("p2", "Senior Project Manager Lead", ["s9", "s10", "s3"]))
        self.assertEqual(r["p1"]["state"], "CANDIDATE")
        self.assertFalse(r["p1"]["established"])  # "process manager" -> foundry manager: no profile skill in the posting
        self.assertTrue(r["p2"]["established"])
        self.assertEqual(r["p2"]["established_by"], "context")

    def test_ambiguous_label_resolved_only_by_unique_context(self):
        r, _ = resolve(posting("p1", "Assistant Manager", ["s4", "s5", "s2"]), posting("p2", "Assistant Manager", ["s2", "s3", "s9"]))
        self.assertEqual(r["p1"]["occupation_uri"], "o:acc2")
        self.assertTrue(r["p1"]["established"])
        self.assertFalse(r["p2"]["established"])
        self.assertEqual(len(r["p2"]["title_candidates"]), 2)  # both kept, none forced

    def test_unmapped_without_enough_context_is_insufficient(self):
        r, _ = resolve(posting("p1", "Video Wizard", ["s1"]), posting("p2", "Growth Ninja", ["s4", "s5", "s6"]))
        self.assertEqual(r["p1"]["state"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(r["p2"]["state"], "UNMAPPED")
        self.assertFalse(r["p2"]["established"])
        self.assertEqual(r["p2"]["skill_profile_candidates"][0]["occupation_uri"], "o:scientist")

    def test_analysis_keeps_occupations_separate_and_gates_small_groups(self):
        items = [posting(f"p{i}", t, sk) for i, (t, sk) in enumerate([
            ("Data Analyst", ["s1", "s2", "s3"]), ("Data Analyst", ["s1", "s2"]), ("Data Scientist", ["s4", "s5", "s6"])])]
        esco_full._SHAPE_CACHE.clear()
        rows, _ = occ.resolve([p for p, _ in items], [m for _, ms in items for m in ms], SKILLS, store(), CFG)
        pairs = {("s1", "p0"), ("s1", "p1"), ("s2", "p0"), ("s2", "p1"), ("s4", "p2")}
        out = occ.occupation_analysis(rows, pairs, SKILLS, store(), {S["s1"]}, {}, [], CFG)
        by = {e["name"]: e for e in out["occupation"]}
        self.assertEqual(set(by), {"data analyst", "data scientist"})
        self.assertEqual(by["data analyst"]["evidence_state"], "SUFFICIENT")
        self.assertEqual(by["data scientist"]["evidence_state"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(by["data analyst"]["esco_profile_alignment"]["mentioned_in_target_curriculum"], 1)


if __name__ == "__main__":
    unittest.main()
