"""Course lineage (RENAMED / EVOLVED / MERGED / SPLIT) and topic attribution
conflicts. Fixtures use invented codes and titles; nothing here depends on an
institution or subject."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine.config import load_config  # noqa: E402
from app.knowledge_engine.drift import course_drift  # noqa: E402
from app.knowledge_engine.quarantine import Quarantine  # noqa: E402
from app.knowledge_engine.silver import build_silver  # noqa: E402
from app.pipelines.preprocessing.curriculum_structuring import structure_curriculum_pages  # noqa: E402

CFG = load_config()
import numpy as np  # noqa: E402

LIN = {"min_topics": 3, "topic_match_min": 0.6, "related_min_share": 0.4, "renamed_min_share": 0.7}


def exact(a, b):
    """Stand-in semantic backend: identical topic text = 1, anything else = 0."""
    return np.array([[1.0 if x == y else 0.0 for y in b] for x in a])


def T(*ids):
    return [f"topic {i}" for i in ids]


def c(uid, code, title, sem="I"):
    return {"course_uid": uid, "course_code": code, "title": title, "semester": sem}


def statuses(rows):
    return sorted((r["status"], r["previous_code"], r["target_code"]) for r in rows)


def test_renamed_when_content_is_preserved_one_to_one():
    prev, tgt = [c("p1", "A1", "Alpha Studies")], [c("t1", "B1", "Omega Methods")]
    cc = {"p1": T(1, 2, 3, 4), "t1": T(1, 2, 3, 4, 5)}
    rows, counts, _ = course_drift(prev, tgt, ["I"], cc, LIN, exact)
    assert statuses(rows) == [("RENAMED", "A1", "B1")]
    assert rows[0]["lineage"][0]["matched_previous_topics"] == 4


def test_evolved_when_overlap_is_partial():
    prev, tgt = [c("p1", "A1", "Alpha")], [c("t1", "B1", "Beta")]
    cc = {"p1": T(1, 2, 3, 4, 5), "t1": T(1, 2, 3, 9, 10, 11)}
    rows, _, _ = course_drift(prev, tgt, ["I"], cc, LIN, exact)
    assert statuses(rows) == [("EVOLVED", "A1", "B1")]


def test_merged_and_split():
    prev = [c("p1", "A1", "Alpha"), c("p2", "A2", "Beta")]
    tgt = [c("t1", "B1", "Alpha and Beta")]
    cc = {"p1": T(1, 2, 3), "p2": T(4, 5, 6), "t1": T(1, 2, 3, 4, 5, 6)}
    rows, _, _ = course_drift(prev, tgt, ["I"], cc, LIN, exact)
    assert statuses(rows) == [("MERGED", "A1,A2", "B1")]
    prev = [c("p1", "A1", "Alpha and Beta")]
    tgt = [c("t1", "B1", "Alpha"), c("t2", "B2", "Beta")]
    cc = {"p1": T(1, 2, 3, 4, 5, 6), "t1": T(1, 2, 3), "t2": T(4, 5, 6)}
    rows, _, _ = course_drift(prev, tgt, ["I"], cc, LIN, exact)
    assert statuses(rows) == [("SPLIT", "A1", "B1,B2")]


def test_untraceable_courses_stay_added_removed_with_reason():
    prev, tgt = [c("p1", "A1", "Alpha")], [c("t1", "B1", "Beta")]
    rows, _, _ = course_drift(prev, tgt, ["I"], {"p1": T(1), "t1": T(1)}, LIN, exact)
    assert {r["status"] for r in rows} == {"ADDED", "REMOVED"}
    assert all(r["lineage_status"] == "INSUFFICIENT_EVIDENCE" for r in rows)


def test_unrelated_content_is_not_lineage():
    prev, tgt = [c("p1", "A1", "Alpha")], [c("t1", "B1", "Beta")]
    rows, _, _ = course_drift(prev, tgt, ["I"], {"p1": T(1, 2, 3), "t1": T(7, 8, 9)}, LIN, exact)
    assert {r["status"] for r in rows} == {"ADDED", "REMOVED"}
    assert all(r["lineage_status"] == "NO_CORRESPONDING_COURSE" for r in rows)


def test_title_identity_still_wins_and_lineage_is_optional():
    prev, tgt = [c("p1", "A1", "Alpha")], [c("t1", "A9", "ALPHA")]
    rows, _, _ = course_drift(prev, tgt, ["I"])
    assert statuses(rows) == [("RETAINED_RECODED", "A1", "A9")]


def test_topics_before_a_later_header_are_not_attributed_to_that_course():
    # page 1: scheme row with no readable title; page 2: a syllabus whose own
    # header code is unreadable; page 3: the course's real header
    pages = ["SEMESTER I\n1  AB101  Discrete Structures  3 0 0 3\n2  AB102   0 0 2 1\n",
             "B102\nSERIES AND SEQUENCES\nUNIT-I\nConvergence tests, Power series",
             "AB102 Graph Theory Lab\nUNIT-I\nPaths, Cycles"]
    q = Quarantine()
    silver = build_silver({"doc_id": "doc-x", "sha256": "0" * 64, "_page_methods": {}},
                          structure_curriculum_pages(pages), q, CFG["topics"])
    by_code = {}
    for t in silver["topics"]:
        by_code.setdefault(t["course_code"], set()).add(t["page_number"])
    assert by_code.get("AB102") == {3}
    conflicts = [i for i in q.items if "ATTRIBUTION_CONFLICT" in i["reason"]]
    assert conflicts and all(i["record"]["page_number"] == 2 for i in conflicts)
