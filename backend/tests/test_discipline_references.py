"""
A registered reference curriculum of another discipline (data/metadata/discipline_references.json) joins an uploaded
curriculum's analysis only when the upload is of that discipline and the context has no reference of it. The default
analysis (curriculum_sources.json) never contains it, so the published run's inputs are unchanged.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import analysis_jobs as aj  # noqa: E402
from tests.test_standalone_analysis import BASE, NEW_COLLEGE  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CSE, AIDS = "Computer Science and Engineering", "Artificial Intelligence and Data Science"
CSE_BASE = {**BASE, "documents": [{**d, "discipline": CSE} for d in BASE["documents"]]}
AIDS_REF = {"doc_id": "aicte-aids", "role": "REFERENCE", "institution": "AICTE", "programme": "AI&DS model",
            "discipline": AIDS, "path": "r.pdf", "expected_sha256": "r" * 64}
AIDS_UPLOAD = {**NEW_COLLEGE, "metadata": {**NEW_COLLEGE["metadata"], "programme": "B.E. AI&DS", "discipline": "AI & DS"}}


class Context(unittest.TestCase):
    def roles(self, m):
        return {d["doc_id"]: d["role"] for d in m["documents"]}

    def test_an_aids_upload_gets_the_aids_reference(self):
        m, notes = aj.derived_manifest(CSE_BASE, AIDS_UPLOAD, references=[AIDS_REF])
        self.assertEqual(self.roles(m)["aicte-aids"], "REFERENCE")
        self.assertTrue(any("aicte-aids" in n and "reference" in n for n in notes))
        # the CSE reference stays in the context; the pipeline's discipline guard sets it aside as not comparable
        self.assertEqual(self.roles(m)["aicte"], "REFERENCE")

    def test_a_cse_upload_is_unchanged(self):
        with_ref, _ = aj.derived_manifest(CSE_BASE, NEW_COLLEGE, references=[AIDS_REF])
        without, _ = aj.derived_manifest(CSE_BASE, NEW_COLLEGE, references=[])
        self.assertEqual(with_ref, without)

    def test_a_reference_of_the_same_discipline_already_present_is_kept_alone(self):
        base = {**CSE_BASE, "documents": CSE_BASE["documents"] + [{**AIDS_REF, "doc_id": "uni-aids-ref"}]}
        m, _ = aj.derived_manifest(base, AIDS_UPLOAD, references=[AIDS_REF])
        self.assertNotIn("aicte-aids", self.roles(m))

    def test_a_peer_or_previous_version_upload_gets_no_reference(self):
        for role in ("PEER", "PREVIOUS_VERSION"):
            m, _ = aj.derived_manifest(CSE_BASE, {**AIDS_UPLOAD, "document_role": role}, references=[AIDS_REF])
            self.assertNotIn("aicte-aids", self.roles(m))

    def test_an_unknown_discipline_gets_no_reference(self):
        up = {**AIDS_UPLOAD, "metadata": {**AIDS_UPLOAD["metadata"], "discipline": "Underwater Basket Weaving"}}
        m, _ = aj.derived_manifest(CSE_BASE, up, references=[AIDS_REF])
        self.assertNotIn("aicte-aids", self.roles(m))


class Registry(unittest.TestCase):
    def test_the_registered_aids_reference_exists_with_its_hash_and_is_not_in_the_default_analysis(self):
        refs = aj.discipline_references()
        aids = next(r for r in refs if r["doc_id"] == "aicte-ug-cse-aids-model")
        self.assertEqual(aids["role"], "REFERENCE")
        path = REPO / aids["path"]
        if path.exists():
            import hashlib
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), aids["expected_sha256"])
        default = json.loads((REPO / "data/metadata/curriculum_sources.json").read_text())
        self.assertNotIn(aids["doc_id"], {d["doc_id"] for d in default["documents"]})
        self.assertNotIn(aids["expected_sha256"], {d.get("expected_sha256") for d in default["documents"]})

    def test_the_discipline_summary_reports_the_aids_reference(self):
        from app.knowledge_engine import discipline_profiles
        base = json.loads((REPO / "data/metadata/curriculum_sources.json").read_text())
        summary = discipline_profiles.summary({**base, "documents": base["documents"] + aj.discipline_references()})
        profiles = {p["id"]: p for p in summary["profiles"]}
        self.assertEqual(profiles["aids"]["capabilities"]["reference_mapping"], "AVAILABLE")
        self.assertIn("aicte-ug-cse-aids-model", profiles["aids"]["evidence"]["reference_curricula"])
        self.assertEqual(profiles["it"]["capabilities"]["reference_mapping"], "NO_REFERENCE_CURRICULUM")

    def test_the_engineering_branch_references_are_registered_with_their_profiles_and_hashes(self):
        import hashlib
        from app.knowledge_engine import discipline_profiles
        refs = {r["doc_id"]: r for r in aj.discipline_references()}
        registry = json.loads((REPO / "data/metadata/discipline_references.json").read_text())
        limits = {r["doc_id"]: r.get("known_limitations") for r in registry["references"]}
        default = json.loads((REPO / "data/metadata/curriculum_sources.json").read_text())
        for doc_id, profile in (("aicte-ug-ece-model", "ece"), ("aicte-ug-mech-model", "mech"),
                                ("aicte-ug-civil-model", "civil"), ("aicte-ug-eee-model", "eee")):
            ref = refs[doc_id]
            self.assertEqual(ref["role"], "REFERENCE")
            self.assertEqual(discipline_profiles.resolve(ref["discipline"])["id"], profile)
            self.assertTrue(limits[doc_id])
            self.assertNotIn(doc_id, {d["doc_id"] for d in default["documents"]})
            path = REPO / ref["path"]
            if path.exists():
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), ref["expected_sha256"])


if __name__ == "__main__":
    unittest.main()


class CoverageOfSetAsideCurricula(unittest.TestCase):
    """Regression (2026-10-21): an AI & DS or IT upload crashed in industry coverage because skill mentions of the
    set-aside CSE reference had no topic in the run's topic index."""

    def test_mentions_of_topics_outside_the_run_are_ignored(self):
        from app.knowledge_engine import industry as ind
        topics = {"topic:in": {"topic_uid": "topic:in", "doc_id": "t", "course_uid": "c1", "clean_text": "SQL joins",
                               "course_code": "X1", "page_number": 3}}
        courses = {"c1": {"course_uid": "c1", "doc_id": "t", "title": "Databases", "course_code": "X1"}}
        m = {"normalized_text": "sql", "sense_established": True, "raw_mention": "SQL", "span": [0, 3],
             "method": "exact_label"}
        mentions = [{**m, "source_uid": "topic:set-aside"}, {**m, "source_uid": "topic:in"}]
        mappings = {"sql": {"skill_key": "skill:sql", "status": "MAPPED"}}
        out, n_courses = ind.curriculum_coverage(mentions, topics, courses, "t", mappings, {})
        self.assertEqual(n_courses, 1)
        self.assertEqual(out["skill:sql"]["course_codes"], ["X1"])  # the run's own topic is counted; the unknown one is skipped instead of crashing
