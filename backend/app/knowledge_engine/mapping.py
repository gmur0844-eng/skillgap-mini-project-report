"""
Target -> reference mapping, with an explanation for every non-match.

TOPIC level (target topic -> reference topic):
  Candidates are restricted to reference topics in the SAME discipline AND
  the same course family as the target topic's course (scoping, so a word
  shared with an unrelated subject cannot produce a candidate). The best
  out-of-scope candidate is still reported in the explanation so a reviewer
  can see what the scoping rejected.

  Decision (thresholds from config; only course_context_min_similarity is calibrated, see below):
    normalized texts identical                    -> SAME_CONCEPT, REFERENCE_MAPPED
    best similarity < min_similarity              -> unmapped (see below)
    runner-up from a DIFFERENT reference course
      within ambiguous_gap of the best            -> AMBIGUOUS, REVIEW_REQUIRED
    otherwise, by name-token containment:
      reference tokens inside target (target narrower) -> CHILD
      target tokens inside reference (target broader)  -> PARENT
      similarity >= high_similarity                     -> RELATED
      else                                              -> PARTIAL_OVERLAP
    all of these are MODEL_SUGGESTED (lexical similarity, not verified meaning)

  Course-context gate (consistency release): shared words are never enough on their own. A linked relationship
  keeps its state only when
    - identity of SPECIFIC wording (>= 2 content words), or
    - the target and reference COURSES are comparable: whole-course topic-text cosine (titles excluded)
      >= course_context_min_similarity (the threshold calibrated on course pairs of known identity,
      artifacts/calibration/peer_course_context.json; the same measure and threshold the peer benchmark uses),
      and, for an identity, the wording is not a single generic word (a word that occurs in the topics of
      >= generic_word_course_share of all courses, e.g. "Applications", "Concepts").
  Otherwise the relationship is kept as the candidate and the evidence status becomes REVIEW_REQUIRED, with the
  reason and the course context recorded (never silently dropped, never promoted).

  Unmapped topics carry: reason code, candidates considered (in scope) with
  their similarity, why each was rejected, the best out-of-scope candidate,
  and a suggested action. Relationship is NEW_DISCOVERED_UNMAPPED when the
  topic belongs to a discovered concept that has no reference members, else
  INSUFFICIENT_EVIDENCE.

CONCEPT level:
  A discovered concept whose members include reference topics is
  REFERENCE_SUPPORTED (the reference topics, pages and courses are its
  evidence). A concept with only target/previous-version members is
  TARGET_ONLY and gets the same kind of explanation.

COURSE correspondence:
  For each target course, how its mapped topics distribute over reference
  courses. Reported as counts; not an alignment score.
"""
from collections import Counter, defaultdict

import numpy as np

from app.analytics.concept_semantic_matching import _token_containment
from app.analytics.core_knowledge_mapping import _normalize_conjunctions
from app.knowledge_engine.silver import uid
from app.pipelines.preprocessing.skill_normalization import normalize_skill_text

HIGH_SIMILARITY = 0.55  # tier boundary shared with concept_semantic_matching.DEFAULT_HIGH_SIMILARITY


_QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"})


def _norm(text):
    # typographic quotes/dashes are normalized first: "Newton\u2019s" and "Newton's"
    # are the same text (found in the real benchmark)
    return normalize_skill_text(_normalize_conjunctions((text or "").translate(_QUOTES)))


def _relationship(target_text, reference_text, similarity):
    if _norm(target_text) == _norm(reference_text):
        return "SAME_CONCEPT", "normalized_text_identity", "REFERENCE_MAPPED"
    t_in_r, r_in_t = _token_containment(target_text, reference_text)
    if r_in_t >= 0.8 and t_in_r < 0.8:
        return "CHILD", "tfidf_cosine+token_containment", "MODEL_SUGGESTED"
    if t_in_r >= 0.8 and r_in_t < 0.8:
        return "PARENT", "tfidf_cosine+token_containment", "MODEL_SUGGESTED"
    if similarity >= HIGH_SIMILARITY:
        return "RELATED", "tfidf_cosine", "MODEL_SUGGESTED"
    return "PARTIAL_OVERLAP", "tfidf_cosine", "MODEL_SUGGESTED"


def _content(text):
    from app.knowledge_engine.concepts import _content_words
    return _content_words(text or "")


def course_context_fn(target_topics, reference_topics):
    """Whole-course topic-text cosine between target and reference courses (titles excluded), TF-IDF fitted on both
    sides -- the measure calibrated in scripts/evaluation/calibrate_peer_context.py."""
    from app.knowledge_engine.semantic_backend import TfidfBackend
    texts = defaultdict(list)
    for t in list(target_topics) + list(reference_topics):
        texts[t["course_uid"]].append(t["clean_text"])
    uids = sorted(texts)
    if len(uids) < 2:
        return lambda a, b: None
    docs = [" ; ".join(texts[u]) for u in uids]
    be = TfidfBackend()
    be.fit(docs)
    emb = be.embed(docs)
    sims = be.similarity(emb, emb)
    pos = {u: i for i, u in enumerate(uids)}
    return lambda a, b: float(sims[pos[a], pos[b]]) if a in pos and b in pos else None


def generic_words(topics, share):
    """Words that occur in the topics of >= share of all courses (data-driven, discipline-independent)."""
    by_course = defaultdict(set)
    for t in topics:
        by_course[t["course_uid"]].update(w.lower() for w in _content(t["clean_text"]))
    n = len(by_course) or 1
    df = Counter(w for ws in by_course.values() for w in ws)
    return {w for w, c in df.items() if c / n >= share}


def context_gate(relationship, method, status, target_text, course_context, min_context, generic):
    """(evidence_status, reason) after the course-context gate; pure function."""
    words = [w.lower() for w in _content(target_text)]
    specific = len(words) >= 2
    comparable = course_context is not None and course_context >= min_context
    if relationship == "SAME_CONCEPT" and method == "normalized_text_identity":
        if specific:
            return status, None
        if comparable and not (words and all(w in generic for w in words)):
            return status, None
        why = ("single generic word" if words and all(w in generic for w in words) else "single-word identity")
        return "REVIEW_REQUIRED", (f"{why}; course context {course_context if course_context is None else round(course_context, 3)} "
                                   f"(comparable >= {min_context}): shared words are not enough for SAME_CONCEPT")
    if comparable:
        return status, None
    return "REVIEW_REQUIRED", (f"lexical overlap without comparable course context ({course_context if course_context is None else round(course_context, 3)} "
                               f"< {min_context}); relationship kept as a candidate, not counted until reviewed")


def map_topics(target_topics, reference_topics, course_to_family, topic_to_concept, concept_roles,
               backend, cfg, courses_by_uid):
    """Returns list of mapping records (one per target topic)."""
    if not target_topics:
        return []
    cctx = course_context_fn(target_topics, reference_topics)
    generic = generic_words(list(target_topics) + list(reference_topics), cfg.get("generic_word_course_share", 0.1))
    min_context = cfg.get("course_context_min_similarity", 0.12)
    ref_by_family = defaultdict(list)
    for r in reference_topics:
        ref_by_family[course_to_family.get(r["course_uid"])].append(r)
    all_refs = list(reference_topics)
    all_ref_matrix = backend.embed([r["clean_text"] for r in all_refs]) if all_refs else None
    target_matrix = backend.embed([t["clean_text"] for t in target_topics])
    ref_index = {r["topic_uid"]: i for i, r in enumerate(all_refs)}
    ref_family = [course_to_family.get(r["course_uid"]) for r in all_refs]
    out_of_family = {}  # family -> indices of the reference topics outside it (ascending), computed once per family
    records = []
    min_sim, gap, top_k = cfg["min_similarity"], cfg["ambiguous_gap"], cfg["top_k_candidates"]

    sims_all = backend.similarity(target_matrix, all_ref_matrix) if all_refs else None
    # context signal: the topic's unit context (course title + unit + sibling topics), compared with
    # the same backend. Recorded as a SEPARATE signal; it does not change the relationship decision.
    ctx_text = unit_contexts(list(target_topics) + list(reference_topics), courses_by_uid)
    ctx_keys = sorted(ctx_text)
    ctx_pos = {k: i for i, k in enumerate(ctx_keys)}
    ctx_matrix = backend.embed([ctx_text[k] for k in ctx_keys]) if ctx_keys else None
    describe = backend.describe() if hasattr(backend, "describe") else {"name": "unknown"}
    for i, topic in enumerate(target_topics):
        family = course_to_family.get(topic["course_uid"])
        in_scope = ref_by_family.get(family, [])
        base = {"mapping_uid": uid("map", topic["topic_uid"]), "source_uid": topic["topic_uid"],
                "source_text": topic["clean_text"], "source_course_uid": topic["course_uid"],
                "family_uid": family, "score_is_calibrated": False}
        row = sims_all[i] if sims_all is not None else np.array([])
        scope_idx = [ref_index[r["topic_uid"]] for r in in_scope]
        ranked = sorted(((float(row[j]), all_refs[j]) for j in scope_idx), key=lambda x: (-x[0], x[1]["topic_uid"]))
        candidates = [{"reference_topic_uid": r["topic_uid"], "reference_text": r["clean_text"],
                       "reference_course_uid": r["course_uid"], "reference_page": r["page_number"],
                       "similarity_score": round(s, 4)} for s, r in ranked[:top_k]]
        if family not in out_of_family:
            out_of_family[family] = np.array([j for j, f in enumerate(ref_family) if f != family], dtype=int)
        out_scope = out_of_family[family]
        best_out = None
        if out_scope.size:
            # the highest similarity, the lowest index among equals (argmax returns the first maximum)
            j = int(out_scope[np.argmax(row[out_scope])])
            best_out = {"reference_topic_uid": all_refs[j]["topic_uid"], "reference_text": all_refs[j]["clean_text"],
                        "reference_family_uid": course_to_family.get(all_refs[j]["course_uid"]),
                        "similarity_score": round(float(row[j]), 4),
                        "rejected_because": "outside the target topic's course family (scope)"}

        def unmapped(reason, action):
            concept = topic_to_concept.get(topic["topic_uid"])  # noqa: B023 -- called within this iteration
            relationship = ("NEW_DISCOVERED_UNMAPPED" if concept and "REFERENCE" not in concept_roles.get(concept, ())
                            else "INSUFFICIENT_EVIDENCE")
            rejected = [{**c, "rejected_because": f"similarity {c['similarity_score']} < min_similarity {min_sim}"}
                        for c in candidates]  # noqa: B023 -- called within this iteration
            return {**base, "target_uid": None, "relationship": relationship, "similarity_score": None,  # noqa: B023 -- called within this iteration
                    "method": "tfidf_cosine_scoped", "evidence_status": "INSUFFICIENT_EVIDENCE",
                    "explanation": {"reason": reason, "candidates_considered": rejected,
                                    "best_out_of_scope_candidate": best_out, "suggested_action": action,  # noqa: B023 -- called within this iteration
                                    "discovered_concept_uid": concept}}

        if not in_scope:
            records.append(unmapped("NO_REFERENCE_TOPICS_IN_SCOPE",
                                    "NEW_CONCEPT_CANDIDATE: the reference has no topics in this course family"))
            continue
        best_sim, best = ranked[0]
        if best_sim < min_sim:
            records.append(unmapped("NO_CANDIDATE_ABOVE_THRESHOLD",
                                    "HUMAN_REVIEW if the topic is important; otherwise treat as not evidenced in the reference"))
            continue
        runner = next(((s, r) for s, r in ranked[1:] if r["course_uid"] != best["course_uid"]), None)
        if runner and best_sim - runner[0] < gap:
            records.append({**base, "target_uid": None, "relationship": "AMBIGUOUS",
                            "similarity_score": round(best_sim, 4), "method": "tfidf_cosine_scoped",
                            "evidence_status": "REVIEW_REQUIRED",
                            "explanation": {"reason": "TOP_CANDIDATES_FROM_DIFFERENT_REFERENCE_COURSES_TOO_CLOSE",
                                            "candidates_considered": candidates, "ambiguous_gap": gap,
                                            "suggested_action": "HUMAN_REVIEW: choose between the candidates"}})
            continue
        relationship, method, status = _relationship(topic["clean_text"], best["clean_text"], best_sim)
        course_ctx = cctx(topic["course_uid"], best["course_uid"])
        status, gate_reason = context_gate(relationship, method, status, topic["clean_text"], course_ctx, min_context, generic)
        a, b = ctx_pos[_unit_key(topic)], ctx_pos[_unit_key(best)]
        context_sim = float(backend.similarity(ctx_matrix[a], ctx_matrix[b])[0][0])
        signals = {"lexical_similarity": round(best_sim, 4), "context_similarity": round(context_sim, 4),
                   "course_context": None if course_ctx is None else round(course_ctx, 4),
                   "course_context_min_similarity": min_context, "context_gate": gate_reason or "PASSED",
                   "semantic_similarity": None, "taxonomy_similarity": None,
                   "semantic_similarity_status": "EMBEDDING_BACKEND_UNAVAILABLE",
                   "composite_score": None, "provenance": {
                       "backend": describe.get("name"), "backend_config": {k: v for k, v in describe.items() if k != "name"},
                       "similarity_method": "cosine", "score_is_calibrated": False,
                       "source_text_sha256": _sha(topic["clean_text"]), "reference_text_sha256": _sha(best["clean_text"])}}
        records.append({**base, "target_uid": best["topic_uid"], "relationship": relationship, "signals": signals,
                        "similarity_score": round(best_sim, 4), "method": method, "evidence_status": status,
                        "reference_course_uid": best["course_uid"],
                        "evidence": {"target_page": topic["page_number"], "reference_page": best["page_number"],
                                     "target_text": topic["clean_text"], "reference_text": best["clean_text"],
                                     "reference_course": courses_by_uid[best["course_uid"]]["title"],
                                     "candidates_considered": candidates}})
    return records


def _unit_key(topic):
    return f"{topic['course_uid']}|{topic.get('unit_label') or ''}"


def _sha(text):
    import hashlib
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def unit_contexts(topics, courses_by_uid):
    """course title + unit label + the unit's topic texts, per (course, unit)."""
    parts = defaultdict(list)
    for t in topics:
        parts[_unit_key(t)].append(t["clean_text"])
    out = {}
    for key, texts in parts.items():
        course_uid, unit = key.split("|", 1)
        title = courses_by_uid.get(course_uid, {}).get("title", "")
        out[key] = f"{title}. {unit}. " + "; ".join(sorted(texts))
    return out


def concept_reference_status(concepts, topics_by_uid, courses_by_uid, concept_family_centroids=None):
    """REFERENCE_SUPPORTED vs TARGET_ONLY for each discovered concept."""
    out = []
    for c in concepts:
        ref_members = [topics_by_uid[u] for u in c["member_topic_uids"] if topics_by_uid[u]["role"] == "REFERENCE"]
        if ref_members:
            out.append({"concept_uid": c["concept_uid"], "status": "REFERENCE_SUPPORTED",
                        "evidence_status": "MODEL_SUGGESTED",
                        "reference_evidence": [{"topic_uid": m["topic_uid"], "text": m["clean_text"],
                                                "page": m["page_number"],
                                                "course": courses_by_uid[m["course_uid"]]["title"]}
                                               for m in ref_members[:10]],
                        "reference_member_count": len(ref_members)})
        elif "REFERENCE" not in c["source_roles"]:
            out.append({"concept_uid": c["concept_uid"], "status": "TARGET_ONLY",
                        "evidence_status": "INSUFFICIENT_EVIDENCE",
                        "explanation": {"reason": "NO_REFERENCE_TOPIC_CLUSTERED_WITH_THIS_CONCEPT",
                                        "suggested_action": "NEW_CONCEPT_CANDIDATE or HUMAN_REVIEW"}})
    return out


def course_correspondence(topic_mappings, target_courses, courses_by_uid):
    """For each target course: counts of its mapped topics per reference course."""
    per_course = defaultdict(Counter)
    totals = Counter()
    for m in topic_mappings:
        totals[m["source_course_uid"]] += 1
        if m.get("reference_course_uid"):
            per_course[m["source_course_uid"]][m["reference_course_uid"]] += 1
    rows = []
    for course in target_courses:
        cu = course["course_uid"]
        dist = per_course.get(cu, Counter())
        mapped = sum(dist.values())
        top = dist.most_common(3)
        rows.append({
            "course_uid": cu, "course_code": course["course_code"], "title": course["title"],
            "semester": course.get("semester"), "clean_topics": totals.get(cu, 0), "mapped_topics": mapped,
            "reference_courses": [{"reference_course_uid": r, "reference_course": courses_by_uid[r]["title"],
                                   "mapped_topics": n} for r, n in top],
            "evidence_status": "MODEL_SUGGESTED" if mapped else "INSUFFICIENT_EVIDENCE",
            "note": "counts of lexically-similar topic mappings; not an alignment score",
        })
    return rows
