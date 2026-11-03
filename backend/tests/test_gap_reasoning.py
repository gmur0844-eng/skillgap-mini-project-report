"""Phases 4-6: curriculum understanding, skill intelligence stages and gap reasoning.

Every course, institution, skill and layout here is invented for the test; the assertions check the reasoning
pattern (where evidence comes from, what each dimension says, which state follows), never a memorised answer.
"""
import itertools
import json
import random
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import curriculum_understanding as cu  # noqa: E402
from app.knowledge_engine import gap_reasoning as gr  # noqa: E402
from app.knowledge_engine import skill_evidence as se  # noqa: E402
from app.knowledge_engine import skill_intelligence as si  # noqa: E402

CFG = {"max_item_words": 8, "substantial_min_topics": 3, "substantial_min_units": 2}
K = "http://t/"


def course(uid, code, title, sem, doc="d1"):
    return {"course_uid": uid, "course_code": code, "title": title, "semester": sem, "doc_id": doc}


def profile_of(courses, pages=None, programme="B.Tech Invented Engineering", docs=None):
    doc = {"doc_id": "d1", "role": "TARGET", "institution": "Inst", "programme": programme, "discipline": "Invented"}
    return cu.build_profile(doc, docs or [doc], courses, pages)


def mention(source, text, phrase, key):
    s = text.lower().index(phrase.lower())
    return {"source_uid": source, "skill_key": key, "sense_state": "ESTABLISHED", "span": [s, s + len(phrase)],
            "normalized_text": phrase.lower(), "context": text}


def coverage(courses, topics, key, pages=None, titles=(), outcomes=(), prereq=()):
    """topics: [(course_uid, unit, text, phrase)]"""
    p = profile_of(courses, pages)
    tb, ms = {}, []
    for i, (cu_, unit, text, phrase) in enumerate(topics):
        uid = f"t{i}"
        tb[uid] = {"topic_uid": uid, "clean_text": text, "course_uid": cu_, "unit_label": unit, "doc_id": "d1"}
        if phrase:
            ms.append(mention(uid, text, phrase, key))
    tm = [{"source_uid": c, "skill_key": key, "sense_state": "ESTABLISHED", "normalized_text": "x", "span": [0, 0]}
          for c in titles]
    om, oc = [], {}
    for i, c in enumerate(outcomes):
        om.append({"source_uid": f"o{i}", "skill_key": key, "sense_state": "ESTABLISHED", "normalized_text": "x",
                   "span": [0, 0], "context": "outcome"})
        oc[f"o{i}"] = c
    rows = cu.skill_coverage(p, tb, ms, tm, om, oc, {}, list(prereq), CFG)
    return rows.get(key) or cu.absent_record(key, "d1"), p


def stage_row(key=K + "s", **kw):
    row = {"skill_key": key, "skill_label": kw.pop("label", "zarnite welding"), "decisions": {"QUALIFIED_TECHNICAL": 2},
           "decision": "QUALIFIED_TECHNICAL", "normalized_concept": True, "programme_relevance": "IN_PROGRAMME_PROFILE",
           "new": {"support_state": "SUPPORTED", "postings": 9, "companies": 5}, "gap_eligible": True}
    row.update(kw)
    return si.stage(row)


COMPLETE = {"state": "COMPLETE", "reason": "semesters 1-8 present"}
SEMS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"]


# ------------------------------------------------------------------ Phase 4: document structure

class DocumentStructure(unittest.TestCase):
    def test_programme_level_from_degree_words_only(self):
        for text, level in [("B.Tech Marine Robotics", "UNDERGRADUATE"), ("BE Textile Engineering", "UNDERGRADUATE"),
                            ("Bachelor of Fine Arts", "UNDERGRADUATE"), ("M.Tech Glass Science", "POSTGRADUATE"),
                            ("Master of Design", "POSTGRADUATE"), ("Ph.D. in Seismology", "POSTGRADUATE"),
                            ("Integrated B.Sc + M.Sc", "UNKNOWN"), ("Certificate in Pottery", "UNKNOWN"),
                            ("Undergraduate Programme in Oceanography", "UNDERGRADUATE")]:
            self.assertEqual(cu.programme_level(text)[0], level, text)

    def test_semester_and_year(self):
        self.assertEqual([cu.semester_number(s) for s in ("IV", "viii", "6", 3, None, "X1")], [4, 8, 6, 3, None, None])
        self.assertEqual([cu.year_of_study(s) for s in ("I", "II", "III", "VIII")], [1, 1, 2, 4])

    def test_course_kind_reads_the_head_noun(self):
        for title, kind in [("Glassblowing Lab", "PRACTICAL"), ("Kiln Studio", "PRACTICAL"),
                            ("Lab Safety Regulations", "THEORY"), ("Project Finance Basics", "THEORY"),
                            ("Mini Project", "PROJECT"), ("Dissertation Part - II", "PROJECT"),
                            ("Research Colloquium", "SEMINAR"), ("NPTEL", "SELF_DIRECTED"),
                            ("Dye Chemistry Laboratory (II)", "PRACTICAL")]:
            self.assertEqual(cu.course_kind(title)[0], kind, title)

    def test_practical_pairs_by_title(self):
        cs = [course("a", "X1", "Loom Mechanics", "III"), course("b", "X2", "Loom Mechanics Lab", "III"),
              course("c", "X3", "Dyeing Workshop", "III")]
        self.assertEqual(cu.practical_pairs(cs), {"b": "a"})

    def test_document_scope(self):
        target = [course(f"t{i}", f"T{i}", "c", s) for i, s in enumerate(SEMS[:2])]
        other = [course(f"o{i}", f"O{i}", "c", s, doc="d2") for i, s in enumerate(SEMS)]
        partial = cu.document_scope({"doc_id": "d1"}, target + other, {"d2": other})
        self.assertEqual((partial["state"], partial["missing_semesters"]), ("PARTIAL", [3, 4, 5, 6, 7, 8]))
        full = cu.document_scope({"doc_id": "d2"}, target + other, {"d1": target})
        self.assertEqual(full["state"], "COMPLETE")
        none = cu.document_scope({"doc_id": "d3"}, [course("z", "Z", "c", None, doc="d3")], {})
        self.assertEqual(none["state"], "UNKNOWN")


class SchemeLayouts(unittest.TestCase):
    """Compulsory / option status read from scheme layouts the code has never seen."""
    CODES = ["QQ11", "QQ12", "QQ13", "QQ14", "QQ15", "QQ16", "QQ17", "QQ18"]

    def status(self, pages):
        return {c: v["status"] for c, v in cu.course_status(pages, self.CODES).items()}

    def test_scheme_rows_placeholder_and_option_list(self):
        page = """
TERM - III
 1.   QQ11   Tide Modelling          3  1  0   4
                Department Elective
 2.   QQxx                           3  0  0   3
 3.   QQ12   Tide Modelling Lab      0  0  3   1.5
               Total                 6  1  3   8.5
        Department Elective - I
 QQ13   Coastal Ecology            QQ14  Harbour Design
"""
        st = self.status([page])
        self.assertEqual((st["QQ11"], st["QQ12"]), ("COMPULSORY", "COMPULSORY"))   # placeholder opens nothing
        self.assertEqual((st["QQ13"], st["QQ14"]), ("ELECTIVE_OPTION", "ELECTIVE_OPTION"))
        self.assertEqual(st["QQ18"], "UNKNOWN")

    def test_page_level_option_table_and_honours_and_minor(self):
        pages = ["""
                 OPEN ELECTIVES OFFERED
Sl.No   Code    Title                          Credits
 1      QQ15    Sea Ice Physics                  3
 2      QQ16    Polar Logistics                  3
""", """
Honors Track:
  Code    Title                 Credits
  QQ17    Advanced Wave Theory    3
a) Fourth year
 1.   QQ11   Tide Modelling   4
"""]
        st = self.status(pages)
        self.assertEqual((st["QQ15"], st["QQ16"], st["QQ17"]), ("ELECTIVE_OPTION",) * 3)
        self.assertEqual(st["QQ11"], "COMPULSORY")   # the section heading closed the honours block

    def test_prose_mentioning_electives_is_not_a_heading(self):
        page = """
Students may replace one elective with an approved course from another department after consultation with the advisor.
 1.   QQ11   Tide Modelling   4
"""
        self.assertEqual(self.status([page])["QQ11"], "COMPULSORY")

    def test_prerequisite_column_is_a_reference_not_an_option(self):
        pages = ["""
SEMESTER 2
 1.  QQ11  Tide Modelling   4
""", """
Department Electives
Sl. No. Code  Title             Prerequisite   Credits
 1.  QQ13  Coastal Ecology        QQ11            3
"""]
        st = self.status(pages)
        self.assertEqual((st["QQ11"], st["QQ13"]), ("COMPULSORY", "ELECTIVE_OPTION"))

    def test_continuation_page_without_heading_is_not_called_compulsory(self):
        pages = ["""
Department Electives
Sl. No. Code  Title             Credits
 1.  QQ13  Coastal Ecology        3
""", """
Stream B: Offshore Systems
Sl. No. Code  Title             Credits
 1.  QQ14  Harbour Design         3
"""]
        st = self.status(pages)
        self.assertEqual(st["QQ13"], "ELECTIVE_OPTION")
        self.assertEqual(st["QQ14"], "UNKNOWN")   # may continue the option list: ambiguous, not COMPULSORY


# ------------------------------------------------------------------ Phase 4: coverage and evidence hierarchy

class Coverage(unittest.TestCase):
    CS = [course("a", "Q1", "Tide Modelling", "III"), course("b", "Q2", "Tide Modelling Lab", "III"),
          course("c", "Q3", "Coastal Ecology", "V"), course("e", "Q5", "Harbour Design", "VII")]
    PAGES = ["""
SEMESTER - III
 1.  Q1  Tide Modelling        3  0  0  3
 2.  Q2  Tide Modelling Lab    0  0  3  1
 3.  Q5  Harbour Design        3  0  0  3
     Elective - I
 Q3  Coastal Ecology
"""]

    def test_levels_from_topic_relations(self):
        k = K + "swash"
        r, _ = coverage(self.CS, [("a", "U1", "Swash zones", "swash zones")], k, self.PAGES)
        self.assertEqual(r["coverage_level"], "INTRODUCTORY")
        r, _ = coverage(self.CS, [("a", "U1", "Swash zones", "swash zones"), ("a", "U2", "Modelling swash zones", "swash zones"),
                                  ("e", "U1", "Swash zones", "swash zones")], k, self.PAGES)
        self.assertEqual(r["coverage_level"], "SUBSTANTIAL")
        r, _ = coverage(self.CS, [("a", "U1", "Swash zones erosion control", "swash zones")], k, self.PAGES)
        self.assertEqual(r["coverage_level"], "MENTION")
        r, _ = coverage(self.CS, [("a", "U1", "Swash zones", "swash zones"), ("e", "U1", "Swash zones", "swash zones")],
                        k, self.PAGES, prereq=[{"source_uid": "a", "target_uid": "e"}])
        self.assertEqual((r["coverage_level"], r["cross_course"]["pattern"]), ("ADVANCED", "PROGRESSION_EXPLICIT"))

    def test_title_or_outcome_without_topics_is_uncertain_not_absent(self):
        r, _ = coverage(self.CS, [], K + "tides", self.PAGES, titles=["a"])
        self.assertEqual((r["coverage_level"], r["strongest_evidence"]), ("UNCERTAIN", "COURSE_TITLE"))
        r, _ = coverage(self.CS, [], K + "tides", self.PAGES, outcomes=["a"])
        self.assertEqual(r["coverage_level"], "UNCERTAIN")
        r, _ = coverage(self.CS, [], K + "tides", self.PAGES)
        self.assertEqual(r["coverage_level"], "ABSENT")

    def test_evidence_is_ranked_by_hierarchy(self):
        r, _ = coverage(self.CS, [("a", "U1", "Swash zones erosion control", "swash zones"),
                                  ("a", "U2", "Swash zones", "swash zones")], K + "sw", self.PAGES, titles=["b"], outcomes=["a"])
        ranks = [e["rank"] for e in r["evidence"]]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(r["strongest_evidence"], "TOPIC_DIRECT")

    def test_access_and_practice_dimensions(self):
        r, _ = coverage(self.CS, [("c", "U1", "Dune flora", "dune flora")], K + "dune", self.PAGES)
        self.assertEqual(r["access"], "ELECTIVE_ONLY")
        r, _ = coverage(self.CS, [("a", "U1", "Dune flora", "dune flora")], K + "dune", self.PAGES)
        self.assertEqual((r["access"], r["practice"], r["paired_practicals"]), ("COMPULSORY", "PAIRED_PRACTICAL", ["Q2"]))
        r, _ = coverage(self.CS, [("e", "U1", "Dune flora", "dune flora")], K + "dune", self.PAGES)
        self.assertEqual(r["practice"], "THEORY_ONLY")
        r, _ = coverage(self.CS, [], K + "dune", self.PAGES, titles=["b"])
        self.assertEqual(r["practice"], "PRACTISED")

    def test_taxonomy_relations_are_context(self):
        store = {K + "broad": {"pref_label": "coastal engineering", "broader": []},
                 K + "narrow": {"pref_label": "breakwater design", "broader": [K + "broad"]},
                 K + "other": {"pref_label": "groyne layout", "broader": [K + "broad"]}}
        rows = {K + "narrow": {"coverage_level": "INTRODUCTORY"}, K + "broad": {"coverage_level": "ABSENT"},
                K + "other": {"coverage_level": "ABSENT"}}
        rel = cu.taxonomy_related(rows, store)
        self.assertEqual([n["key"] for n in rel[K + "broad"]["narrower_taught"]], [K + "narrow"])
        self.assertEqual(rel.get(K + "other"), None)   # a sibling is not related coverage

    def test_syllabus_concept_matches_skill_evidence_profile_rule(self):
        mappings = {"tidal": {"reason": "LABEL_CONTEXT_DEPENDENT: single ordinary word",
                              "candidates": [{"uri": K + "tidal", "label": "tidal"}]},
                    "wave": {"reason": "label belongs to more than one", "candidates": [
                        {"uri": K + "w1", "label": "wave"}, {"uri": K + "w2", "label": "wave energy"}]},
                    "surge": {"reason": "x", "candidates": [{"uri": K + "s1", "label": "storm surge"},
                                                             {"uri": K + "s2", "label": "surge tank"}]}}
        ms = [{"source_uid": "t", "skill_key": K + "est", "sense_state": "ESTABLISHED", "normalized_text": "est"},
              {"source_uid": "t", "skill_key": "surface:tidal", "esco_status": "INSUFFICIENT_EVIDENCE",
               "sense_state": "ESTABLISHED", "normalized_text": "tidal"},
              {"source_uid": "t", "skill_key": "surface:wave", "esco_status": "AMBIGUOUS", "normalized_text": "wave"},
              {"source_uid": "t", "skill_key": "surface:surge", "esco_status": "AMBIGUOUS", "normalized_text": "surge"}]
        mine = {cu.syllabus_concept(m, mappings) for m in ms} - {None}
        theirs = se.curriculum_profile(ms, {"t": "d1"}, {"d1"}, (), mappings)
        self.assertEqual({k for k in mine if k.startswith("http")}, theirs)


# ------------------------------------------------------------------ Phase 5: stages

class Stages(unittest.TestCase):
    def test_each_stage_stops_with_a_reason(self):
        cases = [({"decisions": {}}, "MENTIONED"), ({"decision": "EXCLUDED_BOILERPLATE"}, "QUALIFIED"),
                 ({"normalized_concept": False}, "NORMALIZED"), ({"decision": "TRANSVERSAL"}, "DISCIPLINE_RELEVANT"),
                 ({"programme_relevance": "OUTSIDE_PROGRAMME_PROFILE"}, "DISCIPLINE_RELEVANT"),
                 ({"new": {"support_state": "OBSERVED", "postings": 3, "companies": 2}}, "DEMAND_SUPPORTED"),
                 ({"gap_eligible": False}, "ANALYTICALLY_ELIGIBLE")]
        for kw, stop in cases:
            st = stage_row(**kw)
            self.assertFalse(st["eligible"])
            self.assertEqual(st["stopped_at"]["stage"], stop, kw)
            self.assertTrue(st["stopped_at"]["reason"])
        self.assertTrue(stage_row()["eligible"])

    def test_discipline_adjacent_counts_as_relevant(self):
        self.assertTrue(stage_row(programme_relevance="DISCIPLINE_ADJACENT")["eligible"])


# ------------------------------------------------------------------ Phase 6: gap states

class GapStates(unittest.TestCase):
    def rec(self, level, access="COMPULSORY", practice="THEORY_ONLY", evidence=(), carrying=("Q1",)):
        r = cu.absent_record(K + "s", "d1")
        r.update(coverage_level=level, access=access, practice=practice, evidence=list(evidence),
                 carrying_courses=list(carrying), level_reason=f"{level} evidence")
        return r

    def state(self, rec, scope=COMPLETE, **kw):
        return gr.reason(stage_row(**kw.pop("stage", {})), rec, scope, **kw)["gap_state"]

    def test_every_state(self):
        self.assertEqual(self.state(self.rec("SUBSTANTIAL")), "NO_GAP")
        self.assertEqual(self.state(self.rec("ADVANCED", access="UNKNOWN")), "NO_GAP")
        self.assertEqual(self.state(self.rec("SUBSTANTIAL", access="ELECTIVE_ONLY")), "LIMITED_COVERAGE")
        self.assertEqual(self.state(self.rec("INTRODUCTORY", access="ELECTIVE_ONLY")), "LIMITED_COVERAGE")
        self.assertEqual(self.state(self.rec("INTRODUCTORY")), "DEPTH_GAP")
        self.assertEqual(self.state(self.rec("ABSENT")), "STRUCTURAL_GAP")
        self.assertEqual(self.state(self.rec("MENTION")), "STRUCTURAL_GAP")
        self.assertEqual(self.state(self.rec("UNCERTAIN")), "REVIEW_REQUIRED")
        self.assertEqual(self.state(self.rec("SUBSTANTIAL"), trend="DECLINING"), "OUTDATED_COVERAGE")
        self.assertEqual(self.state(self.rec("SUBSTANTIAL"), stage={"decision": "TRANSVERSAL"}), "INSUFFICIENT_EVIDENCE")

    def test_whole_course_named_after_a_shallow_skill_needs_review(self):
        rec = self.rec("INTRODUCTORY", evidence=[{"type": "PRACTICAL_TITLE", "course_code": "Q2"}])
        self.assertEqual(self.state(rec), "REVIEW_REQUIRED")

    def test_narrower_taught_limits_broader_is_context(self):
        nar = {"narrower_taught": [{"key": "n", "label": "breakwater design", "level": "INTRODUCTORY"}],
               "broader_taught": []}
        bro = {"narrower_taught": [], "broader_taught": [{"key": "b", "label": "coastal engineering", "level": "SUBSTANTIAL"}]}
        self.assertEqual(self.state(self.rec("ABSENT"), related=nar), "LIMITED_COVERAGE")
        out = gr.reason(stage_row(), self.rec("ABSENT"), COMPLETE, related=bro)
        self.assertEqual((out["gap_state"], out["broader_taught"]), ("STRUCTURAL_GAP", ["coastal engineering"]))

    def test_partial_document_shows_what_is_taught_not_what_is_missing(self):
        partial = {"state": "PARTIAL", "reason": "semesters 1-2 of 8"}
        self.assertEqual(self.state(self.rec("ABSENT"), partial), "INSUFFICIENT_EVIDENCE")
        self.assertEqual(self.state(self.rec("INTRODUCTORY"), partial), "INSUFFICIENT_EVIDENCE")
        self.assertEqual(self.state(self.rec("UNCERTAIN"), partial), "INSUFFICIENT_EVIDENCE")
        self.assertEqual(self.state(self.rec("SUBSTANTIAL"), partial), "NO_GAP")

    def test_skill_naming_the_discipline(self):
        self.assertEqual(self.state(self.rec("INTRODUCTORY"), discipline="Marine Robotics and Automation",
                                    stage={"label": "marine robotics"}), "INSUFFICIENT_EVIDENCE")

    def test_semantic_scorer_is_advisory_only(self):
        for level in ("ABSENT", "INTRODUCTORY", "SUBSTANTIAL", "UNCERTAIN"):
            plain = gr.reason(stage_row(), self.rec(level), COMPLETE)
            adv = gr.reason(stage_row(), self.rec(level), COMPLETE, semantic_coverage=lambda s, c: {"score": 0.99})
            self.assertEqual(plain["gap_state"], adv["gap_state"])
            self.assertFalse(adv["advisory"]["applied"])

    def test_corroboration_never_decides(self):
        others = {"p1": ("PEER", {K + "s": {"coverage_level": "SUBSTANTIAL"}}), "r": ("REFERENCE", {})}
        with_ = gr.reason(stage_row(), self.rec("ABSENT"), COMPLETE, others=others)
        without = gr.reason(stage_row(), self.rec("ABSENT"), COMPLETE)
        self.assertEqual(with_["gap_state"], without["gap_state"])
        self.assertEqual(with_["corroboration"]["summary"], {"PEER": "1 of 1 teach it", "REFERENCE": "0 of 1 teach it"})


# ------------------------------------------------------------------ properties

SEVERITY = {"NO_GAP": 0, "LIMITED_COVERAGE": 1, "DEPTH_GAP": 2, "REVIEW_REQUIRED": 2, "STRUCTURAL_GAP": 3}


class Properties(unittest.TestCase):
    CS = Coverage.CS
    PAGES = Coverage.PAGES

    def test_more_teaching_never_makes_a_gap_worse(self):
        rng = random.Random(7)
        pool = [("a", "U1"), ("a", "U2"), ("e", "U1"), ("e", "U3"), ("a", "U4")]
        for _ in range(40):
            n = rng.randint(0, 4)
            base = [(c, u, "Rip currents", "rip currents") for c, u in rng.sample(pool, n)]
            extra = base + [(c, u, "Rip currents", "rip currents") for c, u in pool if (c, u) not in {(b[0], b[1]) for b in base}][:1]
            r1, _ = coverage(self.CS, base, K + "rip", self.PAGES)
            r2, _ = coverage(self.CS, extra, K + "rip", self.PAGES)
            s1 = gr.reason(stage_row(K + "rip"), r1, COMPLETE)["gap_state"]
            s2 = gr.reason(stage_row(K + "rip"), r2, COMPLETE)["gap_state"]
            self.assertLessEqual(SEVERITY[s2], SEVERITY[s1], (base, extra, s1, s2))

    def test_ineligible_is_always_insufficient_whatever_the_coverage(self):
        for level, access in itertools.product(cu.COVERAGE_LEVELS, ("COMPULSORY", "ELECTIVE_ONLY", "UNKNOWN", "NONE")):
            rec = cu.absent_record(K + "s", "d1")
            rec.update(coverage_level=level, access=access)
            for stop in ({"normalized_concept": False}, {"decision": "TRANSVERSAL"},
                         {"new": {"support_state": "OBSERVED", "postings": 3, "companies": 1}}):
                self.assertEqual(gr.reason(stage_row(**stop), rec, COMPLETE)["gap_state"], "INSUFFICIENT_EVIDENCE")

    def test_no_gap_state_from_an_incomplete_document(self):
        for level, scope in itertools.product(cu.COVERAGE_LEVELS, ("PARTIAL", "UNKNOWN")):
            rec = cu.absent_record(K + "s", "d1")
            rec.update(coverage_level=level, access="COMPULSORY")
            st = gr.reason(stage_row(), rec, {"state": scope, "reason": "r"})["gap_state"]
            self.assertNotIn(st, gr.GAP_STATES + ("REVIEW_REQUIRED",))

    def test_order_of_evidence_does_not_matter(self):
        topics = [("a", "U1", "Rip currents", "rip currents"), ("e", "U2", "Rip currents and swash", "rip currents"),
                  ("c", "U1", "Rip currents", "rip currents")]
        ref, _ = coverage(self.CS, topics, K + "rip", self.PAGES, titles=["a"], outcomes=["e"])
        for perm in itertools.permutations(topics):
            r, _ = coverage(self.CS, list(perm), K + "rip", self.PAGES, titles=["a"], outcomes=["e"])
            self.assertEqual(json.dumps(r, sort_keys=True), json.dumps(ref, sort_keys=True))

    def test_status_is_invariant_to_unrelated_prose(self):
        page = Coverage.PAGES[0]
        noisy = "Regulations apply.\nThe department reserves the right to modify the scheme.\n" + page
        a = cu.course_status([page], ["Q1", "Q2", "Q3", "Q5"])
        b = cu.course_status([noisy], ["Q1", "Q2", "Q3", "Q5"])
        self.assertEqual({k: v["status"] for k, v in a.items()}, {k: v["status"] for k, v in b.items()})


# ------------------------------------------------------------------ static audit and the synthetic suite

class StaticAudit(unittest.TestCase):
    FILES = ("app/knowledge_engine/curriculum_understanding.py", "app/knowledge_engine/skill_intelligence.py",
             "app/knowledge_engine/gap_reasoning.py")
    FORBIDDEN = ("python", "java", "sql", "docker", "kubernetes", "machine learning", "computer science", "cse",
                 "mechanical", "civil", "electrical", "electronics", "biotech", "finance", "chemistry", "agricultur",
                 "cbit", "iit", "nit ", "nitw", "nitt", "aicte", "chaitanya", "devops", "cloud", "statistics",
                 "communication", "commerce", "22cs", "cs1", "csp")   # degree words (bachelor, mba, ...) are genre

    def test_production_code_names_no_skill_subject_college_or_discipline(self):
        root = Path(__file__).resolve().parents[1]
        for f in self.FILES:
            src = (root / f).read_text()
            code = re.sub(r'"""[\s\S]*?"""', "", src)
            code = "\n".join(l.split("#")[0] for l in code.splitlines()).lower()
            for w in self.FORBIDDEN:
                self.assertIsNone(re.search(r"\b" + re.escape(w), code), f"{f}: '{w}'")


class SyntheticSuite(unittest.TestCase):
    """The frozen cross-discipline suite (AUTHOR_LABELLED). Two course-kind cases are known failures of the head-noun
    rule and are asserted as such, so that a change in either direction is noticed."""
    KNOWN_FAILURES = {("course_kind", "MOOCS / Training / Internship"), ("course_kind", "Engineering Workshop Practice")}

    def test_suite(self):
        repo = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(repo / "scripts/analysis"))
        suite_path = repo / "data/evaluation/gap_reasoning_suite_v1/suite.json"
        if not suite_path.exists():
            raise unittest.SkipTest("suite not present")
        import gap_reasoning_audit as audit
        results, summary = audit.run_suite(json.loads(suite_path.read_text()))
        failed = {(k, r.get("title") or r.get("code") or r.get("skill")) for k, rs in results.items() for r in rs if not r["ok"]}
        self.assertEqual(failed, self.KNOWN_FAILURES)
        self.assertEqual(summary["gap"]["accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
