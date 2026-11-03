"""Semantic peer benchmarking: decision rules, statuses, and an end-to-end comparison on synthetic curricula."""
import unittest

from app.knowledge_engine import peer_stage as ps
from app.knowledge_engine.semantic_backend import get_backend

CFG = {"candidate_min_similarity": 0.35, "related_min_similarity": 0.35, "course_context_min_similarity": 0.12,
       "same_member_share": 0.5, "top_k": 3, "list_limit": 40}


def ev(**kw):
    base = {"similarity": 0.5, "normalized_name_equal": False, "generic_name_equal": False, "specific_wording": True,
            "shared_member_topics": 0, "shared_member_share": 0.0, "shared_direct_skills": [], "esco_hierarchy": None,
            "course_context": 0.3}
    return {**base, **kw}


class Decide(unittest.TestCase):
    def test_same_concept_needs_context(self):
        self.assertEqual(ps.decide(ev(normalized_name_equal=True), CFG)[:2], ("SAME_CONCEPT", "SUPPORTED"))
        self.assertEqual(ps.decide(ev(normalized_name_equal=True, course_context=0.05), CFG)[:2],
                         ("SAME_CONCEPT", "REVIEW_REQUIRED"))

    def test_shared_word_without_context_is_ambiguous_not_a_match(self):
        # "Network Security" vs "Computer Networks": similar wording, different courses
        rel, state, _ = ps.decide(ev(similarity=0.55, course_context=0.03), CFG)
        self.assertEqual((rel, state), ("AMBIGUOUS", "REVIEW_REQUIRED"))

    def test_hierarchy_direction_comes_from_esco_only(self):
        self.assertEqual(ps.decide(ev(esco_hierarchy="TARGET_BROADER"), CFG)[0], "PARENT")
        self.assertEqual(ps.decide(ev(esco_hierarchy="TARGET_NARROWER"), CFG)[0], "CHILD")

    def test_partial_overlap_and_related(self):
        self.assertEqual(ps.decide(ev(shared_member_topics=1, shared_member_share=0.2), CFG)[0], "PARTIAL_OVERLAP")
        self.assertEqual(ps.decide(ev(), CFG)[:2], ("RELATED", "SUPPORTED"))
        self.assertNotEqual(ps.decide(ev(specific_wording=False), CFG)[0], "RELATED")

    def test_generic_names_are_never_equality_evidence(self):
        self.assertFalse(ps._specific("systems"))
        self.assertTrue(ps._specific("binary search trees"))
        rel, state, _ = ps.decide(ev(generic_name_equal=True, course_context=0.02, similarity=0.2), CFG)
        self.assertEqual((rel, state), ("AMBIGUOUS", "REVIEW_REQUIRED"))


class Status(unittest.TestCase):
    def test_statuses(self):
        peer = {"doc_id": "p1", "institution": "Peer One"}
        self.assertEqual(ps.peer_status([], [], {})["status"], ps.PEER_DATA_NOT_AVAILABLE)
        self.assertEqual(ps.peer_status([{"name": "A", "status": "SUPPLIED"}], [peer], {"p1": "PASS"})["status"],
                         ps.PEER_DATA_AVAILABLE)
        st = ps.peer_status([{"name": "A", "status": "SUPPLIED"}, {"name": "B", "status": "NOT_SUPPLIED", "reason": "r"}],
                            [peer], {"p1": "WARN"})
        self.assertEqual(st["status"], ps.PEER_DATA_PARTIAL)
        self.assertEqual([m["name"] for m in st["missing"]], ["B"])
        self.assertEqual(ps.peer_status([], [peer], {"p1": "FAIL"})["status"], ps.PEER_DATA_NOT_AVAILABLE)
        self.assertIn("how_to_add", st)

    def test_depth_difference(self):
        self.assertEqual(ps._depth_difference("SUBSTANTIAL", "ABSENT"), "TARGET_ONLY")
        self.assertEqual(ps._depth_difference("MENTION", "INTRODUCTORY"), "COMPARISON_ONLY")
        self.assertEqual(ps._depth_difference("ADVANCED", "INTRODUCTORY"), "TARGET_DEEPER")
        self.assertEqual(ps._depth_difference("ABSENT", "MENTION"), "NEITHER")


def side(doc_id, role, courses, concepts):
    topics, cs, cons = {}, {}, []
    for ci, (code, title, texts) in enumerate(courses):
        cu = f"{doc_id}:c{ci}"
        cs[cu] = {"course_uid": cu, "course_code": code, "title": title}
        for ti, t in enumerate(texts):
            tu = f"{cu}:t{ti}"
            topics[tu] = {"topic_uid": tu, "course_uid": cu, "clean_text": t, "unit_label": None, "page_number": 1, "doc_id": doc_id}
    for k, (name, members) in enumerate(concepts):
        cons.append({"concept_uid": f"{doc_id}:k{k}", "name": name,
                     "member_topic_uids": [u for u, t in topics.items() if t["clean_text"] in members]})
    return ps._Side(doc_id, role, cons, topics, cs, {}, {"skills": {}})


class EndToEnd(unittest.TestCase):
    def test_same_concept_in_matching_course_and_ambiguity_across_unrelated_courses(self):
        target = side("T", "TARGET", [
            ("T1", "Data Structures", ["binary search trees", "AVL trees rotations", "hash tables chaining", "graph traversal BFS DFS"]),
            ("T2", "Network Security", ["network security threats", "firewalls and intrusion detection", "public key cryptography"])],
            [("binary search trees", ["binary search trees", "AVL trees rotations"]),
             ("network security", ["network security threats", "firewalls and intrusion detection"])])
        peer = side("P", "PEER", [
            ("P1", "Data Structures and Algorithms", ["binary search trees", "AVL trees rotations", "hash tables open addressing",
                                                     "graph traversal BFS DFS"]),
            ("P2", "Computer Networks", ["computer networks layering", "network routing protocols", "network congestion control"])],
            [("binary search trees", ["binary search trees", "AVL trees rotations"]),
             ("computer networks", ["computer networks layering", "network routing protocols"])])
        rows, best = ps.compare_concepts(target, peer, lambda: get_backend("tfidf")[0], CFG, "r")
        bst = best["T:k0"]
        self.assertEqual((bst["relationship"], bst["evidence_state"]), ("SAME_CONCEPT", "SUPPORTED"))
        sec = best.get("T:k1")
        self.assertTrue(sec is None or sec["evidence_state"] != "SUPPORTED" or sec["relationship"] not in ps.COVERING)
        self.assertTrue(all(r["semantic_decision"]["model_consulted"] is False for r in rows))


if __name__ == "__main__":
    unittest.main()
