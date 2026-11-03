"""Skill qualification (experimental): extraction is not qualification; provenance is preserved; generic action
phrases and boilerplate do not become demand; legitimate domain knowledge is kept but is a gap only for a programme
whose curricula name it; aliases need taxonomy context; no word list; deterministic."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import skill_qualification as sq  # noqa: E402

STORE = {
    "http://t/decide": {"pref_label": "make decisions", "alt_labels": "['make decision', 'take decisions']",
                 "skill_type": "skill/competence", "reuse_level": "transversal", "broader": "['g:self']"},
    "http://t/team": {"pref_label": "lead a team", "alt_labels": "[]", "skill_type": "skill/competence",
               "reuse_level": "cross-sector", "broader": "['g:lead']"},
    "http://t/fin": {"pref_label": "financial statements", "alt_labels": "['financial statement']", "skill_type": "knowledge",
              "reuse_level": "cross-sector", "broader": "['g:finance']"},
    "http://t/py": {"pref_label": "Python (computer programming)", "alt_labels": "['Python']", "skill_type": "knowledge",
             "reuse_level": "sector-specific", "broader": "['g:prog']"},
    "http://t/java": {"pref_label": "Java (computer programming)", "alt_labels": "['Java']", "skill_type": "knowledge",
               "reuse_level": "sector-specific", "broader": "['g:prog']"},
    "http://t/cloud": {"pref_label": "cloud technologies", "alt_labels": "[]", "skill_type": "knowledge",
                "reuse_level": "sector-specific", "broader": "['g:net']"},
    "http://t/vm": {"pref_label": "virtualisation", "alt_labels": "[]", "skill_type": "knowledge",
             "reuse_level": "sector-specific", "broader": "['g:net']"},
}


def mention(text, phrase, key, status="EXACT", sense="ESTABLISHED", method="exact_label", uid="m1"):
    i = text.index(phrase)
    return {"mention_uid": uid, "source_uid": "p1", "raw_mention": phrase, "normalized_text": phrase.lower(),
            "skill_key": key, "esco_status": status, "sense_state": sense, "method": method,
            "span": json.dumps([i, i + len(phrase)])}


def q(text, phrase, key, mapping=None, kind="JOB_SPECIFIC", profile=(), siblings=(), **kw):
    return sq.qualify(mention(text, phrase, key, **kw), mapping or {}, STORE, text, kind, set(profile), set(), siblings)


CONTEXT_DEPENDENT = {"reason": "LABEL_CONTEXT_DEPENDENT: single ordinary word", "candidates": "[{'uri': 'http://t/py'}]"}


class Provenance(unittest.TestCase):
    def test_every_record_keeps_the_raw_evidence(self):
        text = "We value people who make decisions quickly."
        r = q(text, "make decisions", "http://t/decide")
        for k in ("raw_phrase", "normalized_phrase", "span", "sentence", "posting_uid", "boilerplate", "text_kind",
                  "decision", "type", "confidence", "reason", "eligible_for_demand", "eligible_for_gap"):
            self.assertIn(k, r)
        self.assertEqual(r["sentence"], text)
        self.assertEqual(text[r["span"][0]:r["span"][1]], "make decisions")


class GenericCapability(unittest.TestCase):
    def test_a_bare_verb_phrase_describing_an_activity_is_not_demand(self):
        r = q("Our values guide how we make decisions and win.", "make decisions", "http://t/decide")
        self.assertEqual(r["decision"], "EXCLUDED_GENERIC_CAPABILITY")
        self.assertFalse(r["eligible_for_demand"])

    def test_the_same_competence_stated_as_a_requirement_is_kept_as_transversal(self):
        r = q("Ability to make decisions under pressure.", "make decisions", "http://t/decide")
        self.assertEqual(r["decision"], "TRANSVERSAL")
        self.assertTrue(r["eligible_for_demand"])
        self.assertFalse(r["eligible_for_gap"])          # never a discipline gap

    def test_a_professional_competence_stated_as_a_requirement_is_qualified(self):
        r = q("Proven ability to lead a team of five.", "lead a team", "http://t/team")
        self.assertEqual(r["decision"], "QUALIFIED_PROFESSIONAL")


class DomainKnowledge(unittest.TestCase):
    text = "Evaluate business models and financial statements of merchants."

    def test_legitimate_domain_knowledge_is_preserved_in_demand(self):
        r = q(self.text, "financial statements", "http://t/fin")
        self.assertEqual(r["decision"], "QUALIFIED_DOMAIN")
        self.assertTrue(r["eligible_for_demand"])
        self.assertFalse(r["eligible_for_gap"])

    def test_relevance_depends_on_the_programme_not_on_the_word(self):
        r = q(self.text, "financial statements", "http://t/fin", profile={"http://t/fin"})   # a programme that teaches it
        self.assertEqual(r["decision"], "QUALIFIED_TECHNICAL")
        self.assertTrue(r["eligible_for_gap"])

    def test_skill_level_discipline_adjacency_needs_posting_evidence(self):
        self.assertEqual(sq.skill_decision(["QUALIFIED_DOMAIN"] * 3, "DISCIPLINE_ADJACENT"), "DISCIPLINE_ADJACENT")
        self.assertEqual(sq.skill_decision(["QUALIFIED_DOMAIN"] * 3, "NOT_ESTABLISHED"), "QUALIFIED_DOMAIN")


class Boilerplate(unittest.TestCase):
    def test_employer_text_is_excluded_but_kept(self):
        text = "We do not discriminate based on financial statements or anything else."
        r = q(text, "financial statements", "http://t/fin", kind="EMPLOYER_BOILERPLATE")
        self.assertEqual(r["decision"], "EXCLUDED_BOILERPLATE")
        self.assertTrue(r["boilerplate"])
        self.assertFalse(r["eligible_for_demand"])


class Context(unittest.TestCase):
    def test_an_ordinary_word_resolves_only_when_the_requirement_is_bound_to_it(self):
        yes = q("Proficiency in Python is required.", "Python", "surface:python", CONTEXT_DEPENDENT,
                status="INSUFFICIENT_EVIDENCE")
        self.assertEqual(yes["concept"], "http://t/py")
        no = q("Experience building systems; the team mascot is a python.", "python", "surface:python",
               CONTEXT_DEPENDENT, status="INSUFFICIENT_EVIDENCE")
        self.assertEqual(no["decision"], "EXCLUDED_INSUFFICIENT_CONTEXT")

    def test_a_related_skill_in_the_sentence_resolves_an_ordinary_word(self):
        r = q("We work in Python and Java.", "Python", "surface:python", CONTEXT_DEPENDENT,
              status="INSUFFICIENT_EVIDENCE", siblings={"http://t/java"})
        self.assertEqual(r["concept"], "http://t/py")
        self.assertIn("sibling", r["resolved_by"])

    def test_an_alias_is_not_proof_of_the_same_concept(self):
        hidden = {"mapping_method": "hiddenLabel_full_taxonomy"}
        framed_only = q("Experience with AWS required.", "AWS", "http://t/cloud", hidden, status="NORMALIZED")
        self.assertEqual(framed_only["decision"], "AMBIGUOUS")
        related = q("Experience with AWS and virtualisation.", "AWS", "http://t/cloud", hidden, status="NORMALIZED",
                    siblings={"http://t/vm"})
        self.assertNotEqual(related["decision"], "AMBIGUOUS")


class NoWordListNoBranch(unittest.TestCase):
    def test_code_names_no_skill_discipline_or_institution(self):
        src = (Path(__file__).resolve().parents[1] / "app/knowledge_engine/skill_qualification.py").read_text()
        code = re.sub(r'"""[\s\S]*?"""', "", src)
        code = "\n".join(l.split("#")[0] for l in code.splitlines())
        for w in ("reproductive", "financial", "customers", "make decisions", "social media", "python", "Python", "SQL",
                  "CSE", "computer", "CBIT", "IIT", "Mechanical", "leadership", "communication"):
            self.assertNotIn(w, code, w)


class Deterministic(unittest.TestCase):
    def test_same_input_same_output(self):
        a = q("Ability to make decisions under pressure.", "make decisions", "http://t/decide")
        b = q("Ability to make decisions under pressure.", "make decisions", "http://t/decide")
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual(sq.skill_decision(["TRANSVERSAL", "QUALIFIED_DOMAIN"], None),
                         sq.skill_decision(["QUALIFIED_DOMAIN", "TRANSVERSAL"], None))


if __name__ == "__main__":
    unittest.main()
