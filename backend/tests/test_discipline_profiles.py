"""
Discipline profiles and the pipeline's discipline guard (data/metadata/discipline_profiles.json).

  * free-text disciplines resolve to one profile; unknown or ambiguous text resolves to none (never guessed)
  * industry evidence is used only when its population is listed in the analysed curriculum's profile
  * peer and reference curricula of another discipline are not compared; their analyses become NOT_APPLICABLE with
    the reason (not BLOCKED, and never silently replaced)
  * the published CSE release manifest is unaffected: every source is kept and every curriculum is comparable
  * support status is computed from the evidence actually present, not asserted
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import discipline_profiles as dp  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RELEASE_MANIFEST = REPO / "data/metadata/curriculum_sources.json"
JOBS = [{"source_id": "general-1", "population_id": "CURRENT_JOB_DATASET_2026_09"},
        {"source_id": "boards-1", "population_id": "EMPLOYER_JOB_BOARDS_IN"}]


def rid(text):
    p = dp.resolve(text)
    return p["id"] if p else None


class Resolution(unittest.TestCase):
    def test_common_forms_of_each_discipline(self):
        cases = {
            "Computer Science and Engineering": "cse", "computer science & engineering": "cse", "CSE": "cse",
            "B.Tech CSE": "cse", "B.E. CSE (AIML)": "cse", "CSE (AI & ML)": "cse",
            "Information Technology": "it", "B.E. IT": "it",
            "Artificial Intelligence and Data Science": "aids", "AI & DS": "aids",
            "Electronics and Communication Engineering": "ece", "ECE": "ece",
            "Electrical and Electronics Engineering": "eee", "EEE": "eee",
            "Mechanical Engineering": "mech", "Mechanical (Robotics)": "mech",
            "Civil Engineering": "civil", "Civil": "civil",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(rid(text), want)

    def test_unknown_and_ambiguous_text_is_never_guessed(self):
        for text in ("", None, "(unspecified)", "Chemical Engineering", "Landscape Architecture",
                     "ME", "CE",  # Master of Engineering / Computer Engineering: deliberately not aliases
                     "Computer Science and Information Technology"):  # two disciplines named
            with self.subTest(text=text):
                self.assertIsNone(rid(text))

    def test_short_aliases_match_only_the_whole_text(self):
        self.assertIsNone(rid("it is a curriculum"))
        self.assertIsNone(rid("cs and statistics"))

    def test_profile_ref_records_versions(self):
        ref = dp.profile_ref(dp.resolve("CSE"))
        self.assertEqual((ref["id"], ref["registry_version"]), ("cse", "discipline-profiles-v1"))
        self.assertIsNone(dp.profile_ref(None))


class Comparability(unittest.TestCase):
    def test_same_profile_is_comparable_across_spellings(self):
        self.assertTrue(dp.comparable("Computer Science and Engineering", "B.Tech CSE"))
        self.assertFalse(dp.comparable("Computer Science and Engineering", "Mechanical Engineering"))
        self.assertFalse(dp.comparable("Information Technology", "Computer Science and Engineering"))

    def test_without_a_profile_only_identical_text_is_comparable(self):
        self.assertTrue(dp.comparable("Naval Architecture", "naval architecture"))
        self.assertFalse(dp.comparable("Naval Architecture", "Computer Science and Engineering"))
        self.assertFalse(dp.comparable("(unspecified)", "Computer Science and Engineering"))
        self.assertFalse(dp.comparable("", ""))


class IndustryScope(unittest.TestCase):
    def test_relevant_populations_are_kept(self):
        for d in ("CSE", "Information Technology", "AI & DS"):
            relevant, excluded = dp.industry_sources_for(dp.resolve(d), JOBS)
            self.assertEqual((len(relevant), excluded), (2, []))

    def test_a_discipline_without_relevant_postings_is_curriculum_only(self):
        docs = [{"doc_id": "t", "role": "TARGET", "discipline": "Mechanical Engineering"}]
        profile, jobs, exclusion = dp.scope_industry(docs, JOBS)
        self.assertEqual((profile["id"], jobs), ("mech", []))
        self.assertEqual(exclusion["excluded_sources"], ["boards-1", "general-1"])
        self.assertIn("Mechanical Engineering", exclusion["reason"])

    def test_an_unrecognised_discipline_says_how_to_fix_it(self):
        docs = [{"doc_id": "t", "role": "TARGET", "discipline": "(unspecified)"}]
        _, jobs, exclusion = dp.scope_industry(docs, JOBS)
        self.assertEqual(jobs, [])
        self.assertIn("does not match a discipline profile", exclusion["reason"])

    def test_no_target_or_no_jobs_changes_nothing(self):
        self.assertEqual(dp.scope_industry([{"role": "PEER", "discipline": "Civil"}], JOBS)[1:], (JOBS, None))
        self.assertEqual(dp.scope_industry([{"role": "TARGET", "discipline": "Civil"}], [])[1:], ([], None))


class Gates(unittest.TestCase):
    def test_industry_gates_become_not_applicable(self):
        gates = {"industry_gap": {"status": "BLOCKED"}, "industry_demand": {"status": "BLOCKED"}}
        dp.apply_gates(gates, [], {}, {"reason": "no relevant postings"}, [])
        for g in dp.INDUSTRY_GATES:
            self.assertEqual(gates[g], {"status": "NOT_APPLICABLE", "reasons": ["no relevant postings"]})

    def test_other_discipline_peers_and_reference_are_not_compared(self):
        docs = [{"doc_id": "t", "role": "TARGET", "discipline": "Civil Engineering"},
                {"doc_id": "ref", "role": "REFERENCE", "discipline": "Computer Science and Engineering"},
                {"doc_id": "p1", "role": "PEER", "discipline": "Computer Science and Engineering"},
                {"doc_id": "p2", "role": "PEER", "discipline": "Civil Engineering"}]
        nc = dp.not_comparable_documents(docs)
        self.assertEqual([d["doc_id"] for d in nc], ["ref", "p1"])
        gates = {"reference_mapping": {"status": "ALLOWED", "reasons": []},
                 "peer_benchmark": {"status": "ALLOWED", "reasons": []},
                 "industry_gap": {"status": "BLOCKED", "reasons": ["needs reference mapping"]},
                 "recommendations": {"status": "BLOCKED", "reasons": []}}
        dp.apply_gates(gates, nc, {"PEER": [docs[3]], "REFERENCE": []}, None, JOBS)
        self.assertEqual(gates["reference_mapping"]["status"], "NOT_APPLICABLE")
        self.assertEqual(gates["reference_mapping"]["not_comparable"], ["ref"])
        # the comparable peer is still compared; the other-discipline one is named, never substituted
        self.assertEqual(gates["peer_benchmark"], {"status": "ALLOWED", "reasons": [], "not_comparable": ["p1"]})
        for g in ("industry_gap", "recommendations"):
            self.assertEqual(gates[g]["status"], "NOT_APPLICABLE")
            self.assertIn("reference curriculum of the same discipline", gates[g]["reasons"][0])

    def test_nothing_changes_when_everything_is_comparable(self):
        gates = {"peer_benchmark": {"status": "ALLOWED", "reasons": []}}
        before = json.loads(json.dumps(gates))
        self.assertEqual(dp.apply_gates(gates, [], {"PEER": [1]}, None, JOBS), before)


class ReleaseManifestUnchanged(unittest.TestCase):
    """The published CSE analysis keeps all of its evidence under the guard."""

    def setUp(self):
        self.m = json.loads(RELEASE_MANIFEST.read_text())

    def test_every_job_source_is_relevant_to_the_release_target(self):
        docs = self.m["documents"]
        profile, jobs, exclusion = dp.scope_industry(docs, self.m["industry_sources"])
        self.assertEqual(profile["id"], "cse")
        self.assertIsNone(exclusion)
        self.assertEqual(len(jobs), len(self.m["industry_sources"]))

    def test_every_peer_and_reference_is_comparable(self):
        self.assertEqual(dp.not_comparable_documents(self.m["documents"]), [])


class Summary(unittest.TestCase):
    def test_support_status_follows_the_evidence_present(self):
        m = json.loads(RELEASE_MANIFEST.read_text())
        by_id = {p["id"]: p for p in dp.summary(m)["profiles"]}
        self.assertEqual(set(by_id), {"cse", "aids", "it", "ece", "eee", "mech", "civil"})
        cse = by_id["cse"]["capabilities"]
        self.assertEqual(cse, {"curriculum_analysis": "AVAILABLE", "industry_analysis": "AVAILABLE",
                               "reference_mapping": "AVAILABLE", "peer_comparison": "AVAILABLE"})
        for pid in ("aids", "it"):
            caps = by_id[pid]["capabilities"]
            self.assertEqual((caps["industry_analysis"], caps["reference_mapping"], caps["peer_comparison"]),
                             ("AVAILABLE", "NO_REFERENCE_CURRICULUM", "NO_PEER_CURRICULUM"))
        for pid in ("ece", "eee", "mech", "civil"):
            caps = by_id[pid]["capabilities"]
            self.assertEqual(caps["industry_analysis"], "NO_RELEVANT_EVIDENCE")
            self.assertTrue(by_id[pid]["validation"].startswith("Curriculum analysis only"))

    def test_only_the_cse_profile_claims_validation(self):
        validated = [p["id"] for p in dp.summary()["profiles"] if p["validation"].startswith("Validated")]
        self.assertEqual(validated, ["cse"])


class PipelineUsesTheGuard(unittest.TestCase):
    def test_pipeline_calls_the_guard_before_the_run_id(self):
        src = (REPO / "backend/app/knowledge_engine/pipeline.py").read_text()
        guard = src.index("discipline_profiles.scope_industry(documents, job_sources)")
        self.assertLess(guard, src.index("run_id = hashlib.sha256"))
        self.assertIn("discipline_profiles.apply_gates(", src)
        self.assertIn('"discipline_profile": discipline_profiles.profile_ref(target_profile)', src)


if __name__ == "__main__":
    unittest.main()
