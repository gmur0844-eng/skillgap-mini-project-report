"""Discipline-to-industry relevance (experimental): eligibility, not deletion; no blacklist; skill relevance is not
job relevance; unresolved occupation is not evidence against; boilerplate does not inflate demand."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import relevance as rel  # noqa: E402

EEO = "We do not discriminate based upon race, religion, sex, pregnancy or reproductive health decisions."


def posting(uid, company, title, text):
    return {"posting_uid": uid, "company_key": company, "company_name": company, "job_title": title,
            "clean_description": text}


class Boilerplate(unittest.TestCase):
    def setUp(self):
        self.p = [
            posting("a", "acme", "Data Engineer", f"Build pipelines in Spark.\n{EEO}\nA degree in a related field is required here."),
            posting("b", "acme", "Accountant", f"Prepare financial statements monthly.\n{EEO}"),
            posting("c", "acme", "Platform Engineer", f"Operate clusters on Kubernetes.\n{EEO}\nA degree in a related field is required here."),
            posting("d", "beta", "Analyst", "Analyse the market every quarter."),
        ]
        self.b = rel.boilerplate(self.p)

    def state_of(self, uid, needle):
        text = next(x["clean_description"] for x in self.p if x["posting_uid"] == uid)
        i = text.index(needle)
        return rel.segment_state(self.b[uid], (i, i + len(needle)))

    def test_text_in_every_posting_of_an_employer_is_boilerplate(self):
        self.assertEqual(self.state_of("a", "reproductive health"), "EMPLOYER_BOILERPLATE")

    def test_text_shared_by_some_related_roles_is_kept_as_job_evidence(self):
        self.assertEqual(self.state_of("a", "related field"), "SHARED_ROLE_TEXT")

    def test_unique_text_is_job_specific(self):
        self.assertEqual(self.state_of("b", "financial statements"), "JOB_SPECIFIC")

    def test_boilerplate_mentions_are_kept_with_provenance_but_not_job_evidence(self):
        mentions = [{"source_type": "job_posting", "sense_state": "ESTABLISHED", "skill_key": "k:rh", "source_uid": "a",
                     "span": str(list((self.p[0]["clean_description"].index("reproductive health"),
                                       self.p[0]["clean_description"].index("reproductive health") + 19)))}]
        rows = rel.mention_rows(mentions, {"k:rh"}, self.b)
        self.assertFalse(rows["a"]["k:rh"]["job"])
        self.assertEqual(rows["a"]["k:rh"]["states"]["EMPLOYER_BOILERPLATE"], 1)


class Signals(unittest.TestCase):
    profile = {"k:spark", "k:sql"}
    reuse = {"k:spark": "sector-specific", "k:sql": "sector-specific", "k:ledger": "sector-specific",
             "k:team": "transversal", "k:etl": "sector-specific"}

    def test_skill_signal(self):
        self.assertEqual(rel.skill_signal({"k:spark", "k:sql", "k:ledger"}, self.profile, self.reuse)["state"], "SUPPORTS")
        self.assertEqual(rel.skill_signal({"k:ledger"}, self.profile, self.reuse)["state"], "CONTRADICTS")
        self.assertEqual(rel.skill_signal({"k:team"}, self.profile, self.reuse)["state"], "NO_EVIDENCE")  # transversal
        # a skill the curriculum does not teach but that sits next to it in the taxonomy is not a contradiction
        self.assertEqual(rel.skill_signal({"k:etl"}, self.profile, self.reuse, near={"k:etl"})["state"], "MIXED")

    def test_unresolved_occupation_is_never_evidence_against(self):
        for r in (None, {"state": "UNMAPPED"}, {"state": "INSUFFICIENT_EVIDENCE"}, {"state": "AMBIGUOUS"}):
            self.assertEqual(rel.occupation_signal(r, {}, self.profile, self.reuse)["state"], "NO_EVIDENCE")

    def test_occupation_signal(self):
        occ = {"o:dev": {"k:spark", "k:sql"}, "o:clerk": {"k:ledger"}}
        r = lambda u: {"state": "EXACT", "occupation_uri": u, "occupation_label": u}
        self.assertEqual(rel.occupation_signal(r("o:dev"), occ, self.profile, self.reuse)["state"], "SUPPORTS")
        self.assertEqual(rel.occupation_signal(r("o:clerk"), occ, self.profile, self.reuse)["state"], "CONTRADICTS")

    def test_a_silent_title_is_not_evidence_against(self):
        self.assertEqual(rel.title_signal("Analyst III", {"sql"}, set())["state"], "NO_EVIDENCE")
        self.assertEqual(rel.title_signal("Senior SQL Developer", {"sql"}, set())["state"], "SUPPORTS")

    def test_classification(self):
        s = lambda *x: [{"state": v} for v in x]
        self.assertEqual(rel.classify(s("SUPPORTS", "SUPPORTS", "NO_EVIDENCE")), "RELEVANT")
        self.assertEqual(rel.classify(s("SUPPORTS", "NO_EVIDENCE", "NO_EVIDENCE")), "LIKELY_RELEVANT")
        self.assertEqual(rel.classify(s("CONTRADICTS", "NO_EVIDENCE", "NO_EVIDENCE")), "NOT_RELEVANT")
        self.assertEqual(rel.classify(s("CONTRADICTS", "SUPPORTS", "NO_EVIDENCE")), "UNCERTAIN")
        self.assertEqual(rel.classify(s("NO_EVIDENCE", "NO_EVIDENCE", "NO_EVIDENCE")), "UNCERTAIN")

    def test_only_contradicted_postings_leave_the_population(self):
        self.assertEqual(set(rel.JOB_STATES) - set(rel.ELIGIBLE), {"NOT_RELEVANT"})


class SkillRelevanceIsNotJobRelevance(unittest.TestCase):
    def test_states(self):
        reuse = {"k:team": "transversal"}
        jobs = {"p1": "RELEVANT", "p2": "LIKELY_RELEVANT", "p3": "UNCERTAIN"}
        self.assertEqual(rel.skill_relevance("k:sql", {"k:sql"}, reuse, {"p3"}, jobs), "IN_PROGRAMME_PROFILE")
        self.assertEqual(rel.skill_relevance("k:team", set(), reuse, {"p1", "p2"}, jobs), "TRANSVERSAL")
        self.assertEqual(rel.skill_relevance("k:k8s", set(), reuse, {"p1", "p2", "p3"}, jobs), "DISCIPLINE_ADJACENT")
        # a skill demanded mostly by postings without positive relevance evidence is not established
        self.assertEqual(rel.skill_relevance("k:fs", set(), reuse, {"p1", "p3", "p4"}, jobs), "NOT_ESTABLISHED")


class NoBlacklistNoDiscipline(unittest.TestCase):
    def test_code_names_no_term_discipline_or_institution(self):
        src = (Path(__file__).resolve().parents[1] / "app/knowledge_engine/relevance.py").read_text()
        code = re.sub(r'"""[\s\S]*?"""', "", src)
        code = "\n".join(l.split("#")[0] for l in code.splitlines())
        for w in ("reproductive", "customers", "financial", "CSE", "computer", "CBIT", "IIT", "software", "Mechanical"):
            self.assertNotIn(w, code)


if __name__ == "__main__":
    unittest.main()
