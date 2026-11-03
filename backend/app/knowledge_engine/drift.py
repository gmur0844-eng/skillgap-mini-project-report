"""
Concept-level and course-level curriculum drift between two versions of the
SAME programme (roles PREVIOUS_VERSION -> TARGET).

Comparable scope: only semesters present in BOTH versions are compared (a
version that covers semesters I-IV cannot say anything about V-VIII).
Courses without a semester placement are excluded from drift and counted.

Concept identity is shared across versions because concepts were discovered
on the joint corpus: a topic reworded between versions still falls in the
same concept, so rewording is NOT reported as added/removed.

Per concept (support = member topics from comparable-scope courses):
  ADDED             previous 0,  target >= min_support
  REMOVED           previous >= min_support, target 0
  EXPANDED          target/previous >= expansion_ratio
  REDUCED           target/previous <= reduction_ratio
  RETAINED_REWORDED present in both, ratio in between, and no member wording
                    (normalized) is shared between the versions
  RETAINED          present in both, ratio in between, some wording shared
  UNCERTAIN         present in one version only, below min_support
These are descriptive; none implies better or worse.

Course level: courses matched across versions by normalized TITLE (codes are
often renumbered between regulations), reported as RETAINED /
RETAINED_RECODED / ADDED / REMOVED.

Course lineage (second pass, only over courses left ADDED / REMOVED): a
previous and a target course correspond when their clean topics match.
share(a, b) = fraction of a's clean topics whose most similar topic of b has
similarity >= topic_match_min (the run's semantic backend). Topic-level, so it
does not depend on the course-family partition. With thresholds from
cfg["lineage"]:
  RENAMED  one-to-one, share >= renamed_min_share in BOTH directions
  EVOLVED  one-to-one, share >= related_min_share in both directions but
           below the renamed threshold
  MERGED   one target course draws >= related_min_share from two or more
           previous courses
  SPLIT    one previous course feeds >= related_min_share into two or more
           target courses
A course with fewer than min_topics clean topics cannot be traced;
it stays ADDED / REMOVED and lineage_status says INSUFFICIENT_EVIDENCE.
Lineage is content correspondence, not a claim about the institution's
intent.
"""
from collections import defaultdict

from app.knowledge_engine.mapping import _norm


def comparable_semesters(courses_prev, courses_target):
    prev = {c["semester"] for c in courses_prev if c.get("semester")}
    target = {c["semester"] for c in courses_target if c.get("semester")}
    return sorted(prev & target)


def concept_drift(concepts, topics_by_uid, courses_by_uid, prev_doc, target_doc, semesters, cfg):
    semester_set = set(semesters)
    rows, counts = [], defaultdict(int)
    for c in concepts:
        members = {"prev": [], "target": []}
        for t_uid in c["member_topic_uids"]:
            t = topics_by_uid[t_uid]
            course = courses_by_uid[t["course_uid"]]
            if course.get("semester") not in semester_set:
                continue
            if t["doc_id"] == prev_doc:
                members["prev"].append(t)
            elif t["doc_id"] == target_doc:
                members["target"].append(t)
        p, n = len(members["prev"]), len(members["target"])
        if p == 0 and n == 0:
            continue
        ms = cfg["min_support"]
        if p == 0:
            status = "ADDED" if n >= ms else "UNCERTAIN"
        elif n == 0:
            status = "REMOVED" if p >= ms else "UNCERTAIN"
        else:
            ratio = n / p
            if ratio >= cfg["expansion_ratio"]:
                status = "EXPANDED"
            elif ratio <= cfg["reduction_ratio"]:
                status = "REDUCED"
            else:
                prev_words = {_norm(t["clean_text"]) for t in members["prev"]}
                target_words = {_norm(t["clean_text"]) for t in members["target"]}
                status = "RETAINED" if prev_words & target_words else "RETAINED_REWORDED"
        counts[status] += 1
        rows.append({
            "concept_uid": c["concept_uid"], "concept": c["name"], "status": status,
            "previous_support": p, "target_support": n,
            "previous_examples": [{"text": t["clean_text"], "page": t["page_number"],
                                   "course": courses_by_uid[t["course_uid"]]["title"]} for t in members["prev"][:3]],
            "target_examples": [{"text": t["clean_text"], "page": t["page_number"],
                                 "course": courses_by_uid[t["course_uid"]]["title"]} for t in members["target"][:3]],
            "evidence_status": "MODEL_SUGGESTED",
        })
    rows.sort(key=lambda r: (r["status"], -(r["previous_support"] + r["target_support"]), r["concept"]))
    return rows, dict(sorted(counts.items()))


def course_drift(courses_prev, courses_target, semesters, course_topics=None, lineage_cfg=None, similarity=None):
    semester_set = set(semesters)
    prev = [c for c in courses_prev if c.get("semester") in semester_set]
    target = [c for c in courses_target if c.get("semester") in semester_set]
    prev_by_title = defaultdict(list)
    for c in prev:
        prev_by_title[_norm(c["title"])].append(c)
    matched_prev, rows = set(), []
    for c in sorted(target, key=lambda c: c["course_code"]):
        candidates = prev_by_title.get(_norm(c["title"]), [])
        if candidates:
            p = candidates[0]
            matched_prev.add(p["course_uid"])
            status = "RETAINED" if p["course_code"] == c["course_code"] else "RETAINED_RECODED"
            rows.append({"status": status, "previous_code": p["course_code"], "target_code": c["course_code"],
                         "title": c["title"], "previous_semester": p["semester"], "target_semester": c["semester"],
                         "method": "normalized_title_identity", "evidence_status": "REFERENCE_MAPPED"})
        else:
            rows.append({"status": "ADDED", "previous_code": None, "target_code": c["course_code"], "title": c["title"],
                         "previous_semester": None, "target_semester": c["semester"],
                         "method": "no previous-version course with the same normalized title",
                         "evidence_status": "EXTRACTED"})
    for p in sorted(prev, key=lambda c: c["course_code"]):
        if p["course_uid"] not in matched_prev:
            rows.append({"status": "REMOVED", "previous_code": p["course_code"], "target_code": None, "title": p["title"],
                         "previous_semester": p["semester"], "target_semester": None,
                         "method": "no target-version course with the same normalized title",
                         "evidence_status": "EXTRACTED"})
    if course_topics is not None and lineage_cfg and similarity is not None:
        rows = course_lineage(rows, prev, target, course_topics, lineage_cfg, similarity)
    counts = defaultdict(int)
    for r in rows:
        counts[r["status"]] += 1
    excluded = {"previous_without_semester": sum(1 for c in courses_prev if not c.get("semester")),
                "target_without_semester": sum(1 for c in courses_target if not c.get("semester")),
                "target_outside_comparable_semesters": sum(1 for c in courses_target
                                                           if c.get("semester") and c["semester"] not in semester_set)}
    return rows, dict(sorted(counts.items())), excluded


def course_lineage(rows, prev, target, course_topics, cfg, similarity):
    """Re-classify unmatched ADDED/REMOVED rows by topic-match lineage.
    similarity(texts_a, texts_b) -> matrix of pairwise similarities in [0, 1]."""
    by_code_prev = {c["course_code"]: c for c in prev}
    by_code_target = {c["course_code"]: c for c in target}
    added = [r for r in rows if r["status"] == "ADDED"]
    removed = [r for r in rows if r["status"] == "REMOVED"]
    topics_of = lambda c: list(course_topics.get(c["course_uid"], ()))
    traceable = lambda c: len(topics_of(c)) >= cfg["min_topics"]
    rel, tmin = cfg["related_min_share"], cfg["topic_match_min"]
    links = []  # (prev_row, target_row, share_prev, share_target, matched_prev_topics)
    for rp in removed:
        p = by_code_prev[rp["previous_code"]]
        if not traceable(p):
            continue
        for ra in added:
            t = by_code_target[ra["target_code"]]
            if not traceable(t):
                continue
            sims = similarity(topics_of(p), topics_of(t))
            matched_p = int((sims.max(axis=1) >= tmin).sum())
            matched_t = int((sims.max(axis=0) >= tmin).sum())
            sp, st = matched_p / sims.shape[0], matched_t / sims.shape[1]
            if max(sp, st) >= rel:
                links.append((rp, ra, sp, st, matched_p))
    out_prev, out_target = defaultdict(list), defaultdict(list)
    for l in links:
        out_prev[l[0]["previous_code"]].append(l)
        out_target[l[1]["target_code"]].append(l)
    replaced, new_rows = set(), []

    def evidence(l):
        return {"previous_code": l[0]["previous_code"], "previous_title": l[0]["title"],
                "target_code": l[1]["target_code"], "target_title": l[1]["title"],
                "matched_previous_topics": l[4], "share_of_previous": round(l[2], 3), "share_of_target": round(l[3], 3)}

    for code, ls in sorted(out_target.items()):   # MERGED: many previous -> one target
        strong = [l for l in ls if l[2] >= rel]
        if len(strong) >= 2 and all(len(out_prev[l[0]["previous_code"]]) == 1 for l in strong):
            t = strong[0][1]
            new_rows.append({"status": "MERGED", "previous_code": ",".join(sorted(l[0]["previous_code"] for l in strong)),
                             "target_code": code, "title": t["title"], "previous_semester": None,
                             "target_semester": t["target_semester"], "method": "topic_match_lineage",
                             "evidence_status": "MODEL_SUGGESTED", "lineage": [evidence(l) for l in strong]})
            replaced.update(id(l[0]) for l in strong)
            replaced.add(id(t))
    for code, ls in sorted(out_prev.items()):     # SPLIT: one previous -> many target
        strong = [l for l in ls if l[3] >= rel and id(l[1]) not in replaced]
        if len(strong) >= 2 and all(len(out_target[l[1]["target_code"]]) == 1 for l in strong):
            p = strong[0][0]
            new_rows.append({"status": "SPLIT", "previous_code": code,
                             "target_code": ",".join(sorted(l[1]["target_code"] for l in strong)), "title": p["title"],
                             "previous_semester": p["previous_semester"], "target_semester": None,
                             "method": "topic_match_lineage", "evidence_status": "MODEL_SUGGESTED",
                             "lineage": [evidence(l) for l in strong]})
            replaced.update(id(l[1]) for l in strong)
            replaced.add(id(p))
    for l in sorted(links, key=lambda l: (-min(l[2], l[3]), l[0]["previous_code"], l[1]["target_code"])):
        rp, ra = l[0], l[1]
        if id(rp) in replaced or id(ra) in replaced:
            continue
        if len(out_prev[rp["previous_code"]]) != 1 or len(out_target[ra["target_code"]]) != 1:
            continue
        if min(l[2], l[3]) < rel:
            continue
        status = "RENAMED" if min(l[2], l[3]) >= cfg["renamed_min_share"] else "EVOLVED"
        new_rows.append({"status": status, "previous_code": rp["previous_code"], "target_code": ra["target_code"],
                         "title": ra["title"], "previous_title": rp["title"],
                         "previous_semester": rp["previous_semester"], "target_semester": ra["target_semester"],
                         "method": "topic_match_lineage", "evidence_status": "MODEL_SUGGESTED",
                         "lineage": [evidence(l)]})
        replaced.update((id(rp), id(ra)))
    result = []
    for r in rows:
        if id(r) in replaced:
            continue
        if r["status"] in ("ADDED", "REMOVED"):
            code = r["target_code"] or r["previous_code"]
            c = by_code_target.get(code) if r["status"] == "ADDED" else by_code_prev.get(code)
            r = dict(r, lineage_status="NO_CORRESPONDING_COURSE" if traceable(c) else "INSUFFICIENT_EVIDENCE",
                     lineage_note=None if traceable(c) else
                     f"fewer than {cfg['min_topics']} clean topics; lineage cannot be traced")
        result.append(r)
    return result + new_rows
