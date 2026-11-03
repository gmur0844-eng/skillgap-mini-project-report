"""Skill evidence v0.2: generalization properties, unseen phrases, writing styles, adversarial cases.

Every phrase and concept here is invented for the test (none occurs in the code, the benchmarks or the release
data), and the assertions check the reasoning pattern -- role, provenance, normalization, programme relevance --
not a memorised answer. A miniature taxonomy stands in for ESCO, so the tests run without data files.
"""
import json
import random
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import relevance as rel  # noqa: E402
from app.knowledge_engine import skill_evidence as se  # noqa: E402

T = "http://t/"
STORE = {   # invented concepts: names, types, reuse levels and parents shaped like the real taxonomy
    T + "zig": {"pref_label": "Zigzag (computer programming)", "alt_labels": "['Zigzag']", "skill_type": "knowledge",
                "reuse_level": "sector-specific", "collections": "['digitalSkillsCollection']", "broader": "['g:prog']"},
    T + "quill": {"pref_label": "Quillscript", "alt_labels": "[]", "skill_type": "knowledge",
                  "reuse_level": "sector-specific", "collections": "['digitalSkillsCollection']", "broader": "['g:prog']"},
    T + "hydro": {"pref_label": "hydroponic cultivation", "alt_labels": "[]", "skill_type": "knowledge",
                  "reuse_level": "sector-specific", "collections": "[]", "broader": "['g:agri']"},
    T + "soil": {"pref_label": "soil chemistry", "alt_labels": "[]", "skill_type": "knowledge",
                 "reuse_level": "cross-sector", "collections": "[]", "broader": "['g:agri']"},
    T + "mentor": {"pref_label": "mentor apprentices", "alt_labels": "['mentor apprentice']", "skill_type": "skill/competence",
                   "reuse_level": "cross-sector", "collections": "[]", "broader": "['g:lead']"},
    T + "resil": {"pref_label": "show resilience", "alt_labels": "[]", "skill_type": "skill/competence",
                  "reuse_level": "transversal", "collections": "['transversalSkillsCollection']", "broader": "['g:self']"},
    T + "xrf1": {"pref_label": "x-ray fluorescence", "alt_labels": "['XRF']", "skill_type": "knowledge",
                 "reuse_level": "sector-specific", "collections": "[]", "broader": "['g:lab']"},
    T + "xrf2": {"pref_label": "extended reach forklifts", "alt_labels": "['XRF']", "skill_type": "knowledge",
                 "reuse_level": "sector-specific", "collections": "[]", "broader": "['g:warehouse']"},
    T + "spectro": {"pref_label": "spectroscopy", "alt_labels": "[]", "skill_type": "knowledge",
                    "reuse_level": "sector-specific", "collections": "[]", "broader": "['g:lab']"},
    T + "brick": {"pref_label": "bricklaying", "alt_labels": "[]", "skill_type": "skill/competence",
                  "reuse_level": "occupation-specific", "collections": "[]", "broader": "['g:build']"},
}
VERBS = se.verb_lexicon({**STORE, "v1": {"pref_label": "operate cranes", "skill_type": "skill/competence"},
                         "v2": {"pref_label": "use tools", "skill_type": "skill/competence"},
                         "v3": {"pref_label": "build walls", "skill_type": "skill/competence"}})


def mention(text, phrase, key, occurrence=1, status="EXACT", sense="ESTABLISHED", method="exact_label", uid=None,
            source="p1"):
    i = -1
    for _ in range(occurrence):
        i = text.index(phrase, i + 1)
    return {"mention_uid": uid or f"m:{source}:{i}", "source_uid": source, "raw_mention": phrase,
            "normalized_text": phrase.lower(), "skill_key": key, "esco_status": status, "sense_state": sense,
            "method": method, "span": json.dumps([i, i + len(phrase)])}


def run(text, phrase, key, mapping=None, profile=(), company="Brightfield Cooperative", segment="JOB_SPECIFIC",
        related_concepts=(), occurrence=1, **kw):
    m = mention(text, phrase, key, occurrence, **kw)
    return se.qualify(m, mapping or {}, STORE, text, segment, se.parse_posting(text), VERBS, set(profile), set(),
                      related_concepts, text, company, "Field Technician")


CONTEXT_DEPENDENT = lambda *uris: {"reason": "LABEL_CONTEXT_DEPENDENT: single ordinary word",
                                   "candidates": str([{"uri": u, "label": STORE[u]["pref_label"]} for u in uris])}


class UnseenPhrasesAndStyles(unittest.TestCase):
    """The same unseen skill, written in many styles, is evidence in every job role and none in employer text."""
    STYLES = {
        "Required: Zigzag (computer programming), soil chemistry and bricklaying.": ("REQUIRED", "STRONG"),
        "Proficiency in Zigzag (computer programming).": ("REQUIRED", "STRONG"),
        "Experience building pipelines with Zigzag (computer programming).": ("REQUIRED", "MEDIUM"),
        "Zigzag (computer programming) development experience required.": ("REQUIRED", "STRONG"),
        "You will develop services in Zigzag (computer programming).": ("RESPONSIBILITY", "MEDIUM"),
        "Zigzag (computer programming) is a plus.": ("PREFERRED", "WEAK"),
        "Knowledge of Zigzag (computer programming) preferred.": ("PREFERRED", "WEAK"),
        "Languages: Zigzag (computer programming), Quillscript": ("SKILLS_LIST", "STRONG"),
        "Responsible for maintaining Zigzag (computer programming) tooling.": ("RESPONSIBILITY", "MEDIUM"),
        "Build and maintain Zigzag (computer programming) modules.": ("RESPONSIBILITY", "MEDIUM"),
    }
    NOT_JOB = [
        "About us\nBrightfield Cooperative writes all of its software in Zigzag (computer programming).\nRequirements\nPatience.",
        "Brightfield Cooperative is an equal opportunity employer; we never discriminate, including on knowledge of Zigzag (computer programming).",
        "Follow us on Zigzag (computer programming) forums and social media.",
        "We offer insurance, paid leave and Zigzag (computer programming) training perks.",
    ]

    def test_every_job_writing_style_yields_evidence_with_the_right_role_and_strength(self):
        for text, (role, strength) in self.STYLES.items():
            r = run(text, "Zigzag (computer programming)", T + "zig")
            self.assertTrue(r["eligible_for_demand"], text)
            self.assertEqual(r["sentence_role"], role, text)
            self.assertEqual(r["evidence_strength"], strength, text)
            self.assertEqual(r["decision"], "QUALIFIED_TECHNICAL", text)

    def test_the_same_skill_in_employer_text_is_never_evidence(self):
        for text in self.NOT_JOB:
            r = run(text, "Zigzag (computer programming)", T + "zig")
            self.assertFalse(r["eligible_for_demand"], text)
            self.assertEqual(r["evidence_strength"], "NONE", text)

    def test_list_items_after_a_head_are_each_evidence(self):
        text = "Required: Zigzag (computer programming), soil chemistry and bricklaying."
        for phrase, key in (("soil chemistry", T + "soil"), ("bricklaying", T + "brick")):
            r = run(text, phrase, key)
            self.assertTrue(r["eligible_for_demand"], phrase)
            self.assertEqual(r["sentence_role"], "REQUIRED")

    def test_a_competence_expressed_as_a_responsibility_verb_is_evidence(self):
        r = run("Key responsibilities\nMentor apprentices on the night shift.", "Mentor apprentices", T + "mentor")
        self.assertEqual(r["decision"], "QUALIFIED_PROFESSIONAL")
        self.assertEqual(r["evidence_strength"], "MEDIUM")

    def test_the_employers_own_action_is_not_the_job_holders_competence(self):
        r = run("At Brightfield we mentor apprentices across our farms.", "mentor apprentices", T + "mentor")
        self.assertFalse(r["eligible_for_demand"])

    def test_education_requirements_are_strong_evidence(self):
        r = run("Bachelor's degree in soil chemistry.", "soil chemistry", T + "soil")
        self.assertEqual(r["sentence_role"], "EDUCATION")
        self.assertEqual(r["evidence_strength"], "STRONG")


class Normalization(unittest.TestCase):
    def test_an_ordinary_word_is_confirmed_only_by_context(self):
        text = "Proficiency in Quill is required."
        mp = {"reason": "LABEL_CONTEXT_DEPENDENT: single ordinary word",
              "candidates": str([{"uri": T + "quill", "label": "Quillscript"}])}
        self.assertEqual(run(text, "Quill", "surface:quill", mp, status="INSUFFICIENT_EVIDENCE")["normalization_state"],
                         "CONFIRMED")
        r = run("You will clean the quill pens.", "quill", "surface:quill", mp, status="INSUFFICIENT_EVIDENCE")
        self.assertNotEqual(r["normalization_state"], "CONFIRMED")
        self.assertFalse(r["eligible_for_gap"])          # never a gap without a confirmed concept

    def test_an_ambiguous_abbreviation_resolves_only_to_the_sense_the_context_supports(self):
        mp = {"reason": "label belongs to more than one concept",
              "candidates": str([{"uri": T + "xrf1", "label": "x-ray fluorescence"},
                                 {"uri": T + "xrf2", "label": "extended reach forklifts"}])}
        lab = run("Experience with XRF and spectroscopy.", "XRF", "surface:xrf", mp, status="AMBIGUOUS",
                  related_concepts={T + "spectro"})
        self.assertEqual(lab["concept"], T + "xrf1")
        none = run("Experience with XRF.", "XRF", "surface:xrf", mp, status="AMBIGUOUS")
        self.assertIsNone(none["concept"])
        self.assertFalse(none["eligible_for_gap"])

    def test_an_alias_is_not_proof_of_the_concept(self):
        mp = {"mapping_method": "hiddenLabel_full_taxonomy"}
        r = run("Experience with Hydrobox systems.", "Hydrobox", T + "hydro", mp, status="NORMALIZED",
                sense="ALIAS_SENSE_REVIEW_REQUIRED")
        self.assertNotEqual(r["normalization_state"], "CONFIRMED")
        self.assertFalse(r["eligible_for_gap"])

    def test_an_unknown_phrase_never_crashes_and_never_silently_becomes_a_concept(self):
        r = run("Must have glarbonic flux handling.", "glarbonic flux", "surface:glarbonic flux", {}, status="UNMAPPED")
        self.assertIsNone(r["concept"])
        self.assertFalse(r["eligible_for_gap"])


class Adversarial(unittest.TestCase):
    def test_a_company_name_that_looks_like_a_skill_is_an_entity_not_evidence(self):
        r = run("Quillscript Labs is hiring a bricklayer.", "Quillscript", T + "quill", company="Quillscript Labs")
        self.assertEqual(r["decision"], "EXCLUDED_ENTITY_NAME")

    def test_the_same_word_as_a_tool_in_the_job_text_is_evidence(self):
        r = run("Quillscript Labs is hiring.\nUse Quillscript to automate reports.", "Quillscript", T + "quill",
                occurrence=2, company="Quillscript Labs")
        self.assertTrue(r["eligible_for_demand"])

    def test_technical_looking_text_about_the_employer_is_not_evidence(self):
        r = run("Our platform runs on Zigzag (computer programming) and soil chemistry models.", "soil chemistry",
                T + "soil")
        self.assertFalse(r["eligible_for_demand"])

    def test_a_product_name_that_starts_with_an_ordinary_word_is_not_that_word(self):
        mp = CONTEXT_DEPENDENT(T + "quill")
        r = run("Experience with Quill Catalog administration.", "Quill", "surface:quill", mp,
                status="INSUFFICIENT_EVIDENCE")
        self.assertFalse(r["eligible_for_gap"])
        self.assertIn("capitalised name", r["syntactic_guard"] or "")

    def test_function_words_are_never_skills(self):
        mp = CONTEXT_DEPENDENT(T + "quill")
        r = run("You will own it end to end.", "it", "surface:it", mp, status="INSUFFICIENT_EVIDENCE")
        self.assertFalse(r["eligible_for_demand"])


class Properties(unittest.TestCase):
    PHRASES = [("Zigzag (computer programming)", T + "zig"), ("soil chemistry", T + "soil"),
               ("bricklaying", T + "brick"), ("hydroponic cultivation", T + "hydro")]

    def test_employer_boilerplate_never_creates_demand_whatever_its_vocabulary(self):
        rng = random.Random(7)
        for _ in range(40):
            phrase, key = rng.choice(self.PHRASES)
            text = f"Required: {phrase}."
            self.assertFalse(run(text, phrase, key, segment="EMPLOYER_BOILERPLATE")["eligible_for_demand"])

    def test_adding_unrelated_employer_boilerplate_does_not_increase_demand(self):
        eeo = "Brightfield Cooperative is an equal opportunity employer and values soil chemistry in every team."
        base = [{"posting_uid": u, "company_key": "bf", "job_title": t, "clean_description": d}
                for u, t, d in (("a", "Grower", "Required: hydroponic cultivation."),
                                ("b", "Mason", "Required: bricklaying."))]
        noisy = [{**p, "clean_description": p["clean_description"] + "\n" + eeo} for p in base]

        def demand(postings):
            boiler = rel.boilerplate(postings)
            n = 0
            for p in postings:
                for phrase, key in self.PHRASES:
                    for occ in re.finditer(re.escape(phrase), p["clean_description"]):
                        m = {"mention_uid": f"{p['posting_uid']}:{occ.start()}", "source_uid": p["posting_uid"],
                             "raw_mention": phrase, "normalized_text": phrase.lower(), "skill_key": key,
                             "esco_status": "EXACT", "sense_state": "ESTABLISHED", "method": "exact_label",
                             "span": json.dumps(list(occ.span()))}
                        q = se.qualify(m, {}, STORE, p["clean_description"],
                                       rel.segment_state(boiler[p["posting_uid"]], occ.span()),
                                       se.parse_posting(p["clean_description"]), VERBS, set(), set(), (),
                                       p["clean_description"], "Brightfield Cooperative", p["job_title"])
                        n += q["eligible_for_demand"]
            return n
        self.assertLessEqual(demand(noisy), demand(base))

    def test_frequency_alone_never_makes_a_gap(self):
        text = "\n".join(["Required: hydroponic cultivation."] * 50)
        for i in range(1, 51):
            r = run(text, "hydroponic cultivation", T + "hydro", occurrence=i)
            self.assertTrue(r["eligible_for_demand"])
            self.assertFalse(r["eligible_for_gap"])          # outside this programme's profile

    def test_unnormalized_evidence_never_makes_a_gap_however_frequent(self):
        occ = [{"normalization_state": "UNCONFIRMED_MULTIPLE", "eligible_for_demand": True}] * 500
        self.assertFalse(se.skill_gap_eligible("QUALIFIED_DOMAIN", "DISCIPLINE_ADJACENT", occ))
        self.assertTrue(se.skill_gap_eligible("QUALIFIED_DOMAIN", "DISCIPLINE_ADJACENT",
                                              occ + [{"normalization_state": "CONFIRMED", "eligible_for_demand": True}]))
        self.assertFalse(se.skill_gap_eligible("TRANSVERSAL", "IN_PROGRAMME_PROFILE",
                                               [{"normalization_state": "CONFIRMED", "eligible_for_demand": True}]))

    def test_programme_relevance_follows_the_programme_profile(self):
        text = "Required: hydroponic cultivation."
        agri = run(text, "hydroponic cultivation", T + "hydro", profile={T + "hydro"})
        other = run(text, "hydroponic cultivation", T + "hydro", profile={T + "brick"})
        self.assertEqual(agri["programme_relevance"], "IN_PROGRAMME_PROFILE")
        self.assertEqual(other["programme_relevance"], "OUTSIDE_PROGRAMME_PROFILE")
        self.assertTrue(agri["eligible_for_gap"])
        self.assertFalse(other["eligible_for_gap"])
        # the decision (what the skill IS) does not change with the programme
        self.assertEqual(agri["decision"], other["decision"])

    def test_provenance_is_kept_back_to_the_source_span(self):
        text = "Experience with soil chemistry and bricklaying."
        r = run(text, "bricklaying", T + "brick")
        self.assertEqual(text[r["span"][0]:r["span"][1]], "bricklaying")
        for k in ("raw_phrase", "sentence", "section_role", "sentence_role", "evidence_strength", "decision",
                  "normalization_state", "programme_relevance", "posting_uid"):
            self.assertIn(k, r)

    def test_identical_evidence_gives_identical_output(self):
        a = run("Experience with soil chemistry.", "soil chemistry", T + "soil")
        b = run("Experience with soil chemistry.", "soil chemistry", T + "soil")
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_raw_evidence_is_never_lost_when_occurrences_are_expanded(self):
        text = "About us: we love bricklaying.\nRequired: bricklaying."
        m = mention(text, "bricklaying", T + "brick")
        out = se.expand_occurrences([m], {"p1": text})
        self.assertIn(m, out)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1]["derived_occurrence_of"], m["mention_uid"])

    def test_a_later_job_occurrence_counts_even_if_the_first_is_employer_text(self):
        text = "About us\nWe love bricklaying.\nRequirements\nProven bricklaying skills."
        ms = se.expand_occurrences([mention(text, "bricklaying", T + "brick")], {"p1": text})
        results = [se.qualify(m, {}, STORE, text, "JOB_SPECIFIC", se.parse_posting(text), VERBS, set(), set(), (),
                              text, "Brightfield Cooperative", "Mason") for m in ms]
        self.assertFalse(results[0]["eligible_for_demand"])
        self.assertTrue(results[1]["eligible_for_demand"])

    def test_the_decision_trace_never_uses_a_semantic_score_unless_supplied(self):
        r = run("Experience with soil chemistry.", "soil chemistry", T + "soil")
        self.assertIsNone(r["semantic"])
        scored = se.qualify(mention("Experience with soil chemistry.", "soil chemistry", T + "soil"), {}, STORE,
                            "Experience with soil chemistry.", "JOB_SPECIFIC",
                            se.parse_posting("Experience with soil chemistry."), VERBS, set(), set(), (), "", None,
                            None, semantic_scorer=lambda f: {"model": "stub", "score": 0.5})
        self.assertEqual(scored["semantic"]["score"], 0.5)
        self.assertEqual(scored["decision"], r["decision"])   # the hook is recorded, not used


class StaticAudit(unittest.TestCase):
    """No skill-, phrase-, subject-, college- or discipline-specific branch in the production layer."""
    FILES = ("app/knowledge_engine/skill_evidence.py", "app/knowledge_engine/skill_qualification.py",
             "app/knowledge_engine/relevance.py")
    FORBIDDEN = ("python", "java", "sql", "docker", "kubernetes", "machine learning", "make decisions",
                 "reproductive", "financial", "social media", "linkedin", "help customers", "customer",
                 "computer science", "cse", "mechanical", "civil", "electrical", "electronics", "biotech",
                 "finance", "cbit", "iit", "nit ", "aicte", "chaitanya", "mongodb", "databricks", "twilio",
                 "leadership", "communication", "matlab", "thermodynamics", "statistics")

    def test_production_code_names_no_skill_subject_college_or_employer(self):
        root = Path(__file__).resolve().parents[1]
        for f in self.FILES:
            src = (root / f).read_text()
            code = re.sub(r'"""[\s\S]*?"""', "", src)                      # docstrings explain, never decide
            code = "\n".join(l.split("#")[0] for l in code.splitlines())   # comments likewise
            low = code.lower()
            for w in self.FORBIDDEN:
                self.assertIsNone(re.search(r"\b" + re.escape(w) + r"\b", low), f"{f}: '{w}'")

    def test_lexicons_are_grammatical_or_genre_cues_only(self):
        # the only word lists are function words and posting-genre cues; none overlaps a skill label of the
        # miniature taxonomy or any concept name used in the evaluation suites
        suite = Path(__file__).resolve().parents[2] / "data/evaluation/skill_generalization_suite_v1/suite.json"
        labels = {s["pref_label"].lower() for s in STORE.values()}
        if suite.exists():
            labels |= {c["phrase"].lower() for c in json.loads(suite.read_text())["cases"]}
        for w in se._CLOSED_CLASS:
            self.assertNotIn(w, labels)


if __name__ == "__main__":
    unittest.main()


class EndToEndSyntheticSuite(unittest.TestCase):
    """The frozen synthetic suite through the REAL extractor and taxonomy (skipped when the ESCO files are absent)."""

    @classmethod
    def setUpClass(cls):
        repo = Path(__file__).resolve().parents[2]
        manifest = repo / "data/metadata/curriculum_sources.json"
        paths = [repo / t["path"] for t in json.loads(manifest.read_text()).get("taxonomy_sources", [])] \
            if manifest.exists() else []
        if not paths or not all(p.exists() for p in paths):
            raise unittest.SkipTest("ESCO classification not available")
        sys.path.insert(0, str(repo / "scripts/analysis"))
        import skill_evidence_audit as audit
        cls.audit = audit
        cls.suite = json.loads((repo / "data/evaluation/skill_generalization_suite_v1/suite.json").read_text())
        _, cls.quals, cls.profiles, cls.store = audit.run_synthetic(cls.suite)
        cls.result = audit.evaluate_synthetic(cls.suite, cls.quals, cls.profiles, cls.store)

    def test_employer_text_and_entity_names_never_become_evidence(self):
        bad = [d for d in self.result["disagreements"] if d["expected"] == "NOT_DEMAND_EVIDENCE"]
        self.assertEqual(bad, [])

    def test_programme_relevance_depends_on_the_programme(self):
        for prog_a, prog_b in (("finance", "mechanical"), ("civil", "biotechnology")):
            self.assertNotEqual(self.profiles[prog_a][0], self.profiles[prog_b][0])

    def test_every_record_is_traceable(self):
        by = {p["posting_uid"]: p["clean_description"] for p in self.suite["postings"]}
        for q in self.quals:
            self.assertEqual(by[q["posting_uid"]][q["span"][0]:q["span"][1]].lower(), (q["raw_phrase"] or "").lower())
