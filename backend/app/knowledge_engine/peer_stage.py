"""
Semantic peer benchmarking (intelligence improvement release).

PEER documents are official curricula of other institutions, listed in the source manifest with role PEER
and full provenance (source URL, SHA-256, academic year, retrieval date, licence note). They pass through
the SAME generic decoder as every other curriculum (RAW -> BRONZE -> SILVER -> health gate) and are kept
OUT of every TARGET / PREVIOUS_VERSION / REFERENCE analytic: a peer never changes the target's concepts,
mappings, drift, demand, gaps or recommendations.

This stage compares the TARGET with every comparison curriculum -- each PEER, and the REFERENCE document
(labelled REFERENCE, never presented as a peer) -- at five SEPARATE levels. Nothing is collapsed into one
score and nothing is ranked:

  1 exact lexical coverage     share of target topics whose text occurs verbatim (case/space-insensitive)
  2 normalized coverage        share equal after the project's normaliser (normalize_skill_text)
  3 semantic concept coverage  target concepts vs comparison concepts: candidate -> evidence -> relationship
  4 skill coverage             ESCO skills with an established DIRECT/PARTIAL mention in each curriculum
  5 coverage depth             per industry-demand skill: ABSENT .. ADVANCED in each curriculum, computed by the
                               same coverage_depth function (with each curriculum's own prerequisite edges)

Concepts on BOTH sides come from the same discovery algorithm (course families -> agglomerative topic
clustering; concepts.py). The target side uses the run's own concepts (TARGET members only); each
comparison curriculum is clustered on its own, so no peer topic can alter a target concept.

Relationship evidence. A relationship needs curriculum CONTEXT plus SEMANTIC evidence. Shared words,
title similarity, an ESCO alias hit, lexical containment and abbreviations are never sufficient alone:
  NORMALIZED_EQUAL       the two concept names are equal after normalisation (specific names only: >= 2
                         content words; equal one-word names such as "systems" are never equality evidence)
  SHARED_MEMBER_TOPICS   specific member topics equal after normalisation (share of the smaller concept)
  SHARED_ESCO_SKILL      an ESCO skill that is the DIRECT subject of a member topic on both sides
                         (established sense) -- catches different terminology for the same skill
  ESCO_HIERARCHY         an ESCO skill of one side is an ESCO-broader skill of a skill of the other
  COURSE_CONTEXT         the courses that carry the two concepts are similar as whole courses (cosine of their
                         topic text, titles excluded), threshold calibrated on course pairs of known identity
                         (scripts/evaluation/calibrate_peer_context.py: lowest threshold with <= 0.1 % false
                         positives on title-disjoint pairs)
  SIMILARITY             cosine of the concept representations -- generates candidates, decides nothing alone
Decision (first rule that holds; "context" = COURSE_CONTEXT >= the calibrated threshold):
  SAME_CONCEPT / SUPPORTED        context AND (specific names equal OR specific member share >= same_member_share
                                  OR the same ESCO skill is the DIRECT subject on both sides)
  PARENT | CHILD / SUPPORTED      context AND ESCO hierarchy (direction from ESCO, never from word containment)
  PARTIAL_OVERLAP / SUPPORTED     context AND at least one specific member topic equal
  RELATED / SUPPORTED             context AND topic similarity >= related_min_similarity AND specific wording
  SAME_CONCEPT / REVIEW_REQUIRED  the equality evidence above WITHOUT comparable course context (the same term is
                                  taught in unrelated courses) -- shown, never counted as coverage
  AMBIGUOUS / REVIEW_REQUIRED     lexical or taxonomy overlap without context ("Network Security" vs "Computer
                                  Networks": a shared word, different courses) -- never counted as coverage
  INSUFFICIENT_EVIDENCE           a candidate (shared skill only) with none of the above
Candidates come from TOPIC-level similarity (best member-topic pair) and shared DIRECT ESCO skills. Comparison
units are the comparison curriculum's concepts AND its single topics. Only SUPPORTED relationships count toward
semantic concept coverage. The semantic model is not consulted while the semantic promotion gate is FAILED
(SAFE_MODE); REVIEW_REQUIRED pairs are exported (peers/peer_review_candidates.jsonl) and have no effect.

No function names a university, programme, discipline, course or subject.
"""
from collections import Counter, defaultdict

import numpy as np

from app.analytics.core_knowledge_mapping import load_scoped_vocabulary
from app.knowledge_engine import industry as ind
from app.knowledge_engine import intelligence as intel
from app.knowledge_engine.concepts import _content_words, course_families, discover_concepts
from app.knowledge_engine.prerequisites import resolve_prerequisites
from app.knowledge_engine.silver import uid
from app.pipelines.preprocessing.skill_normalization import normalize_skill_text as norm

PEER_DATA_AVAILABLE = "PEER_DATA_AVAILABLE"
PEER_DATA_PARTIAL = "PEER_DATA_PARTIAL"
PEER_DATA_NOT_AVAILABLE = "PEER_DATA_NOT_AVAILABLE"
RELATIONSHIPS = ("SAME_CONCEPT", "PARENT", "CHILD", "RELATED", "PARTIAL_OVERLAP", "UNRELATED", "AMBIGUOUS",
                 "INSUFFICIENT_EVIDENCE")
EVIDENCE_STATES = ("SUPPORTED", "MODEL_SUPPORTED", "MODEL_SUGGESTED", "REVIEW_REQUIRED", "AMBIGUOUS",
                   "INSUFFICIENT_EVIDENCE")
COVERING = ("SAME_CONCEPT", "PARENT", "CHILD")  # relationships that count toward semantic concept coverage
_PRIORITY = {"SAME_CONCEPT": 0, "PARENT": 1, "CHILD": 1, "PARTIAL_OVERLAP": 2, "RELATED": 3, "AMBIGUOUS": 4,
             "INSUFFICIENT_EVIDENCE": 5}
LEVEL_ORDER = ("ABSENT", "MENTION", "INTRODUCTORY", "SUBSTANTIAL", "ADVANCED")
COVERED_LEVELS = ("INTRODUCTORY", "SUBSTANTIAL", "ADVANCED")


def _specific(text):
    """Equality evidence counts only for specific wording: at least two content words ("binary search trees"),
    never a single generic word ("systems", "analysis", "protocols") that many unrelated concepts share."""
    return len(_content_words(text or "")) >= 2


def _space(text):
    return " ".join((text or "").lower().split())


# ------------------------------------------------------------------ status

def peer_status(requested, peer_docs, health):
    """AVAILABLE when every requested peer is supplied and healthy, PARTIAL when some are, NOT_AVAILABLE when none."""
    healthy = [d for d in peer_docs if health.get(d["doc_id"]) != "FAIL"]
    failed = [d for d in peer_docs if health.get(d["doc_id"]) == "FAIL"]
    missing = [r for r in (requested or []) if r.get("status") != "SUPPLIED"]
    if not healthy:
        status = PEER_DATA_NOT_AVAILABLE
    elif missing:
        status = PEER_DATA_PARTIAL
    else:
        status = PEER_DATA_AVAILABLE
    return {
        "status": status,
        "available": [{k: d.get(k) for k in ("doc_id", "institution", "programme", "curriculum_version", "academic_year",
                                             "source_url", "sha256", "retrieved_at", "licence_note", "page_count")}
                      for d in healthy],
        "failed_health_gate": [d["doc_id"] for d in failed],
        "missing": [{k: r.get(k) for k in ("name", "status", "reason", "candidate_source")} for r in missing],
        "why_not_calculable": (None if healthy else
                               "no official curriculum of a peer institution with topic-level content is loaded; "
                               "peer comparisons need the peer's own courses and topics"),
        "how_to_add": ("download the official curriculum PDF, place it in data/raw/curricula/peers/ and add a manifest "
                       "entry with role PEER (institution, programme, curriculum_version, academic_year, source_url, "
                       "expected_sha256, retrieved_at, licence_note); the next pipeline run decodes it with the same "
                       "generic decoder and benchmarks it"),
    }


# ------------------------------------------------------------------ skills in a comparison curriculum

def curriculum_skill_mentions(topics, extraction, esco_vocab, cfg, backend_factory, label_index=None):
    """The same extractor, mapping and sense check the industry stage applies to curriculum topics.
    Surfaces already mapped in this run keep their mapping; new surfaces are mapped on their own (they can
    never change a mapping of the run's postings or target topics)."""
    raw = ind.extract(topics, "clean_text", "topic_uid", extraction["_index"], "curriculum_topic")
    for m in raw:
        m["mention_uid"] = uid("mention", m["source_type"], m["source_uid"], m["span"][0], m["normalized_text"])
    mappings = dict(extraction["mappings"])
    new = [m for m in raw if m["normalized_text"] not in mappings]
    if new:
        if label_index is None:
            _, label_index = ind.build_vocabulary(esco_vocab)
        mappings.update(ind.map_skills(new, esco_vocab, label_index, backend_factory, cfg["industry"]))
    labels_by_uri = ind.concept_labels(esco_vocab)
    unit_text = defaultdict(list)
    for t in topics:
        unit_text[(t["course_uid"], t.get("unit_label"))].append(t["clean_text"])
    topic_by_uid = {t["topic_uid"]: t for t in topics}
    by_source = defaultdict(list)
    for m in raw:
        by_source[m["source_uid"]].append(m)
    for m in raw:
        mp = mappings[m["normalized_text"]]
        m.update(skill_key=mp["skill_key"], esco_status=mp["status"],
                 esco_uri=mp.get("esco_uri") if mp["status"] in ind.MAPPED_STATUSES else None)
        t = topic_by_uid[m["source_uid"]]
        state, relationship, evidence = ind.sense_check(m, mp, "\n".join(unit_text[(t["course_uid"], t.get("unit_label"))]),
                                                        labels_by_uri, by_source[m["source_uid"]],
                                                        cfg["industry"]["alias_orthographic_min_ratio"])
        m.update(sense_state=state, taxonomy_relationship=relationship, sense_evidence=evidence,
                 sense_established=state in ind.SENSE_ESTABLISHED)
    return raw


# ------------------------------------------------------------------ concepts of a comparison curriculum

def comparison_concepts(doc, courses, topics, backend_factory, cfg):
    """Concept discovery on ONE comparison curriculum, with the engine's own algorithm and settings."""
    backend = backend_factory()
    if len(topics) < cfg["concepts"]["min_support"] or not courses:
        return [], {}
    backend.fit([t["clean_text"] for t in topics] + [c["title"] for c in courses])
    by_course = defaultdict(list)
    for t in topics:
        by_course[t["course_uid"]].append(t)
    fams, c2f, _ = course_families(doc["discipline"], courses, by_course, backend, cfg["families"])
    concepts, t2c = [], {}
    for fam in fams:
        found, t2 = discover_concepts(doc["discipline"], fam, [t for t in topics if c2f.get(t["course_uid"]) == fam["family_uid"]],
                                      backend, cfg["concepts"], {doc["doc_id"]: doc["role"]})
        concepts += found
        t2c.update(t2)
    return concepts, t2c


# ------------------------------------------------------------------ evidence helpers

def _skill_subjects(mentions, topics_by_uid, max_item_words):
    """topic_uid -> {esco_uri: relation} for established, ESCO-mapped mentions."""
    out = defaultdict(dict)
    for m in mentions:
        uri = m.get("esco_uri") or (m["skill_key"] if m.get("esco_status") in ind.MAPPED_STATUSES
                                    and str(m.get("skill_key", "")).startswith("http") else None)
        t = topics_by_uid.get(m["source_uid"])
        if not uri or not m.get("sense_established") or t is None:
            continue
        rel = intel.mention_relation(t["clean_text"], m["span"], max_item_words)
        best = out[m["source_uid"]].get(uri)
        if best is None or intel.COVERAGE_RELATIONS.index(rel) < intel.COVERAGE_RELATIONS.index(best):
            out[m["source_uid"]][uri] = rel
    return out


def _broader_closure(store, uri, max_depth=6):
    """ESCO skill ancestors (skills only, not skill groups) up to max_depth."""
    out, frontier, seen = set(), [(b, 1) for b in store["skills"].get(uri, {}).get("broader", [])], set()
    while frontier:
        u, d = frontier.pop(0)
        if u in seen or d > max_depth:
            continue
        seen.add(u)
        if u in store["skills"]:
            out.add(u)
            frontier.extend((b, d + 1) for b in store["skills"][u]["broader"])
    return out


class _Side:
    """One curriculum's concepts with their evidence, ready for comparison."""

    def __init__(self, doc_id, role, concepts, topics_by_uid, courses_by_uid, subjects, store):
        self.doc_id, self.role = doc_id, role
        self.concepts = concepts
        self.topics_by_uid, self.courses_by_uid = topics_by_uid, courses_by_uid
        self.members = {c["concept_uid"]: [topics_by_uid[u] for u in c["member_topic_uids"] if u in topics_by_uid]
                        for c in concepts}
        self.norm_members = {cu: {norm(t["clean_text"]) for t in ts if _specific(t["clean_text"])} for cu, ts in self.members.items()}
        self.direct_skills, self.all_skills = {}, {}
        for c in concepts:
            rels = [subjects.get(t["topic_uid"], {}) for t in self.members[c["concept_uid"]]]
            self.direct_skills[c["concept_uid"]] = {u for r in rels for u, rel in r.items() if rel == "DIRECT"}
            self.all_skills[c["concept_uid"]] = {u for r in rels for u, rel in r.items() if rel in ("DIRECT", "PARTIAL")}
        self.ancestors = {}
        for uris in self.all_skills.values():
            for u in uris:
                if u not in self.ancestors:
                    self.ancestors[u] = _broader_closure(store, u)
        self.course_uids = {c["concept_uid"]: sorted({t["course_uid"] for t in self.members[c["concept_uid"]]}) for c in concepts}

    def text(self, c):
        return " ; ".join([c["name"]] + [t["clean_text"] for t in self.members[c["concept_uid"]]])

    def evidence(self, c, limit=4):
        ts = self.members[c["concept_uid"]]
        return {"doc_id": self.doc_id, "role": self.role, "concept_uid": c["concept_uid"], "concept": c["name"],
                "support_topics": len(ts), "units": len({(t["course_uid"], t.get("unit_label")) for t in ts}),
                "courses": [{"course_uid": cu, "course_code": self.courses_by_uid[cu]["course_code"],
                             "title": self.courses_by_uid[cu]["title"]} for cu in self.course_uids[c["concept_uid"]]],
                "topics": [{"topic_uid": t["topic_uid"], "text": t["clean_text"], "unit": t.get("unit_label"),
                            "page": t.get("page_number"),
                            "course_code": self.courses_by_uid[t["course_uid"]]["course_code"]} for t in ts[:limit]]}


def _course_context(side_a, side_b, backend_factory):
    """Cosine similarity between every course of side A and side B, as whole courses (title + topics)."""
    def course_texts(side):
        texts = defaultdict(list)
        for t in side.topics_by_uid.values():
            texts[t["course_uid"]].append(t["clean_text"])
        uids = sorted(texts)
        # topic text only: the calibration (scripts/evaluation/calibrate_peer_context.py) scores whole courses
        # without their titles, so equal titles never make their own context
        return uids, [" ; ".join(texts[u]) for u in uids]
    ua, ta = course_texts(side_a)
    ub, tb = course_texts(side_b)
    backend = backend_factory()
    backend.fit(ta + tb)
    sims = backend.similarity(backend.embed(ta), backend.embed(tb))
    return {(a, b): float(sims[i, j]) for i, a in enumerate(ua) for j, b in enumerate(ub)}


def decide(ev, cfg):
    """Relationship + evidence state from an evidence dict (pure function; see module docstring)."""
    context = ev["course_context"] >= cfg["course_context_min_similarity"]
    same_name = ev["normalized_name_equal"]
    member_share = ev["shared_member_share"]
    shared_direct = bool(ev["shared_direct_skills"])
    hierarchy = ev["esco_hierarchy"]
    strong_equality = same_name or member_share >= cfg["same_member_share"] or shared_direct
    if context and strong_equality:
        why = ("names equal after normalisation" if same_name else
               f"{member_share:.0%} of specific member topics equal" if member_share >= cfg["same_member_share"] else
               "the same ESCO skill is the direct subject on both sides")
        return "SAME_CONCEPT", "SUPPORTED", f"{why}, in comparable course context"
    if context and hierarchy:
        rel = "PARENT" if hierarchy == "TARGET_BROADER" else "CHILD"
        return rel, "SUPPORTED", (f"ESCO hierarchy: the target concept's skill is {'broader' if rel == 'PARENT' else 'narrower'}, "
                                  "in comparable course context")
    if context and member_share > 0:
        return "PARTIAL_OVERLAP", "SUPPORTED", f"{ev['shared_member_topics']} specific member topic(s) equal, concepts otherwise differ"
    if context and ev["similarity"] >= cfg["related_min_similarity"] and ev.get("specific_wording", True):
        return "RELATED", "SUPPORTED", "similar specific content in comparable course context, no equality or hierarchy evidence"
    if strong_equality:
        return "SAME_CONCEPT", "REVIEW_REQUIRED", (f"equal specific wording or the same ESCO skill, but the courses differ "
                                                   f"(course context {ev['course_context']:.2f}); not counted until reviewed")
    if (member_share > 0 or hierarchy or ev.get("generic_name_equal") or ev["similarity"] >= cfg["related_min_similarity"]):
        return "AMBIGUOUS", "REVIEW_REQUIRED", ("lexical or taxonomy overlap without comparable course context "
                                                f"(course context {ev['course_context']:.2f}); shared words are not enough")
    return "INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE", "candidate from a shared skill only; no relationship evidence"


def _unit_topic_index(side):
    """(topic texts, owning unit index) for every member topic of every unit of a side."""
    texts, owner = [], []
    for j, c in enumerate(side.concepts):
        for t in side.members[c["concept_uid"]]:
            texts.append(t["clean_text"])
            owner.append(j)
    return texts, owner


def compare_concepts(target, other, backend_factory, cfg, run_id, chunk=400):
    """
    Candidates come from TOPIC-level similarity (a target concept's member topics against the comparison unit's
    member topics, top_k per target topic, >= candidate_min_similarity) plus shared DIRECT ESCO skills; a concept's
    evidence similarity is its best member-topic pair. Comparison units = comparison concepts AND the comparison
    curriculum's single topics (a topic taught once is still taught).
    """
    if not target.concepts or not other.concepts:
        return [], {}
    t_texts, t_owner = _unit_topic_index(target)
    o_texts, o_owner = _unit_topic_index(other)
    backend = backend_factory()
    backend.fit(t_texts + o_texts)
    te, oe = backend.embed(t_texts), backend.embed(o_texts)
    pair_sim = {}
    for start in range(0, len(t_texts), chunk):
        sims = backend.similarity(te[start:start + chunk], oe)
        for r in range(sims.shape[0]):
            row = sims[r]
            # stable: equal similarities (repeated topic texts) keep topic order instead of the sort
            # implementation's unspecified tie order, which differs between NumPy builds and CPUs
            top = np.argsort(-row, kind="stable")[: cfg["top_k"]]
            for j in top:
                if row[j] < cfg["candidate_min_similarity"]:
                    break
                key = (t_owner[start + r], o_owner[j])
                if row[j] > pair_sim.get(key, 0.0):
                    pair_sim[key] = float(row[j])
    skill_index = defaultdict(set)
    for j, c in enumerate(other.concepts):
        for u in other.direct_skills[c["concept_uid"]]:
            skill_index[u].add(j)
    for i, tc in enumerate(target.concepts):
        for u in target.direct_skills[tc["concept_uid"]]:
            for j in skill_index.get(u, ()):
                pair_sim.setdefault((i, j), 0.0)
    ctx = _course_context(target, other, backend_factory)
    rows, best = [], {}
    for (i, j), sim in sorted(pair_sim.items()):
        tc, oc = target.concepts[i], other.concepts[j]
        tcu, ocu = tc["concept_uid"], oc["concept_uid"]
        shared = target.norm_members[tcu] & other.norm_members[ocu]
        smaller = min(len(target.norm_members[tcu]), len(other.norm_members[ocu])) or 1
        hierarchy = None
        for a in target.all_skills[tcu]:
            for b in other.all_skills[ocu]:
                if a != b and a in other.ancestors.get(b, ()):
                    hierarchy = "TARGET_BROADER"
                elif a != b and b in target.ancestors.get(a, ()):
                    hierarchy = hierarchy or "TARGET_NARROWER"
        ev = {
            "similarity": round(sim, 4),
            "similarity_basis": "best member-topic pair (TF-IDF cosine; lexical, candidates only)",
            "normalized_name_equal": _specific(tc["name"]) and norm(tc["name"]) == norm(oc["name"]),
            "generic_name_equal": (not _specific(tc["name"])) and bool(norm(tc["name"])) and norm(tc["name"]) == norm(oc["name"]),
            "specific_wording": _specific(tc["name"]) or _specific(oc["name"]),
            "shared_member_topics": len(shared), "shared_member_share": round(len(shared) / smaller, 4),
            "shared_direct_skills": sorted(target.direct_skills[tcu] & other.direct_skills[ocu]),
            "esco_hierarchy": hierarchy,
            "course_context": round(max((ctx.get((a, b), 0.0) for a in target.course_uids[tcu]
                                         for b in other.course_uids[ocu]), default=0.0), 4),
            "comparison_unit": "single_topic" if oc.get("singleton") else "concept",
        }
        rel, state, why = decide(ev, cfg)
        row = {"relation_uid": uid("peerrel", run_id, tcu, ocu), "run_id": run_id,
               "target": target.evidence(tc), "comparison": other.evidence(oc),
               "relationship": rel, "evidence_state": state, "reason": why, "evidence": ev,
               "semantic_decision": {"model_consulted": False,
                                     "reason": "semantic promotion gate FAILED (SAFE_MODE): model output has no effect"},
               "comparison_role": other.role, "comparison_doc_id": other.doc_id}
        rows.append(row)
        cur = best.get(tcu)
        rank = (0 if state == "SUPPORTED" else 1, _PRIORITY[rel], -ev["similarity"])
        if cur is None or rank < (0 if cur["evidence_state"] == "SUPPORTED" else 1, _PRIORITY[cur["relationship"]],
                                  -cur["evidence"]["similarity"]):
            best[tcu] = row
    return rows, best


def reverse_absent(target, other, rows):
    """Comparison concepts with no SUPPORTED covering/overlap relation to any target concept."""
    linked = {r["comparison"]["concept_uid"] for r in rows
              if r["evidence_state"] == "SUPPORTED" and r["relationship"] in COVERING + ("PARTIAL_OVERLAP", "RELATED")}
    return [other.evidence(c, limit=3) for c in other.concepts if c["concept_uid"] not in linked and not c.get("singleton")]


# ------------------------------------------------------------------ the stage

def run(target_doc, comparison_docs, requested_peers, health, silver, target_concepts, target_topics_by_uid,
        courses_by_uid, extraction, esco_vocab, store, demand, cfg, backend_factory, run_id, outcomes_by_doc,
        target_prereq_edges, target_mentions):
    pcfg = cfg["peers"]
    icfg = cfg["intelligence"]
    peer_docs = [d for d in comparison_docs if d["role"] == "PEER"]
    status = peer_status(requested_peers, peer_docs, health)
    skills = extraction["skills"]
    demand_by_key = {d["skill_key"]: d for d in demand}
    demand_skills = {k: skills[k] for k in demand_by_key}
    max_item_words = icfg["coverage"]["max_item_words"]

    # target side
    t_topics = {u: t for u, t in target_topics_by_uid.items() if t["doc_id"] == target_doc["doc_id"]}
    t_concepts = [{**c, "member_topic_uids": [u for u in c["member_topic_uids"] if u in t_topics]}
                  for c in target_concepts if "TARGET" in c["source_roles"]]
    t_concepts = [c for c in t_concepts if c["member_topic_uids"]]
    t_subjects = _skill_subjects(target_mentions, t_topics, max_item_words)
    target = _Side(target_doc["doc_id"], "TARGET", t_concepts, t_topics, courses_by_uid, t_subjects, store)
    t_depth = {r["skill_key"]: r for r in intel.coverage_depth(target_mentions, t_topics, courses_by_uid, target_doc["doc_id"],
                                                               demand_skills, [], target_prereq_edges, icfg["coverage"])}
    t_exact = {_space(t["clean_text"]) for t in t_topics.values()}
    t_norm = {norm(t["clean_text"]) for t in t_topics.values() if norm(t["clean_text"])}
    t_skill_set = {u for rels in t_subjects.values() for u, rel in rels.items() if rel in ("DIRECT", "PARTIAL")}

    _, label_index = ind.build_vocabulary(esco_vocab)
    comparisons, relations, pending_review = [], [], []
    for doc in comparison_docs:
        rec = silver[doc["doc_id"]]
        c_courses = {c["course_uid"]: c for c in rec["courses"]}
        c_topics = {t["topic_uid"]: t for t in rec["topics"] if t["noise_label"] == "TOPIC" and t["course_uid"] in c_courses}
        if doc["role"] == "REFERENCE":
            mentions = [m for m in extraction["curriculum_mentions"] if m["source_uid"] in c_topics]
        else:
            mentions = curriculum_skill_mentions(list(c_topics.values()), extraction, esco_vocab, cfg, backend_factory, label_index)
        concepts, t2c = comparison_concepts(doc, list(c_courses.values()), list(c_topics.values()), backend_factory, cfg)
        singles = [{"concept_uid": uid("peerunit", doc["doc_id"], t["topic_uid"]), "name": t["clean_text"],
                    "member_topic_uids": [t["topic_uid"]], "singleton": True}
                   for t in sorted(c_topics.values(), key=lambda t: t["topic_uid"]) if t["topic_uid"] not in t2c]
        subjects = _skill_subjects(mentions, c_topics, max_item_words)
        other = _Side(doc["doc_id"], doc["role"], concepts + singles, c_topics, c_courses, subjects, store)
        rows, best = compare_concepts(target, other, backend_factory, pcfg, run_id)
        relations += rows
        pending_review += [r for r in rows if r["evidence_state"] == "REVIEW_REQUIRED"]

        # level 1 + 2: topic coverage
        o_exact = {_space(t["clean_text"]) for t in c_topics.values()}
        o_norm = {norm(t["clean_text"]) for t in c_topics.values() if norm(t["clean_text"])}
        # level 4: skills (ESCO skills that are the DIRECT/PARTIAL subject of a topic)
        o_skill_set = {u for rels in subjects.values() for u, rel in rels.items() if rel in ("DIRECT", "PARTIAL")}
        # level 5: depth with the comparison curriculum's own prerequisite edges and outcomes
        prereqs = [dict(p, doc_id=doc["doc_id"]) for p in rec["prerequisites"]]
        abbr, syn, _ = load_scoped_vocabulary(doc["discipline"])
        edges, _ = resolve_prerequisites(prereqs, {doc["doc_id"]: list(c_courses.values())}, (abbr, syn))
        o_depth = {r["skill_key"]: r for r in intel.coverage_depth(mentions, c_topics, c_courses, doc["doc_id"], demand_skills,
                                                                   [], edges, icfg["coverage"])}
        concept_cov = Counter()
        for c in target.concepts:
            r = best.get(c["concept_uid"])
            if r is None:
                concept_cov["ABSENT_IN_COMPARISON"] += 1
            elif r["evidence_state"] == "SUPPORTED":
                concept_cov[r["relationship"]] += 1
            else:
                concept_cov[r["relationship"] + "_" + r["evidence_state"]] += 1  # shown, never counted as coverage
        covered = sum(concept_cov[r] for r in COVERING)
        related_cov = sum(concept_cov[r] for r in COVERING + ("PARTIAL_OVERLAP", "RELATED"))
        review_cov = sum(v for k, v in concept_cov.items() if k.endswith("_REVIEW_REQUIRED"))
        skill_rows = []
        for key in sorted(demand_by_key):
            tl = t_depth[key]["coverage_level"]
            ol = o_depth[key]["coverage_level"]
            d = demand_by_key[key]
            skill_rows.append({
                "skill_key": key, "skill_label": skills[key]["label"], "esco_uri": skills[key].get("esco_uri"),
                "industry": {"posting_count": d["posting_count"], "eligible_postings": d["eligible_postings"],
                             "posting_prevalence_pct": d["posting_prevalence_pct"], "support_state": d["support_state"],
                             "population_scope_ref": d.get("population_scope_ref")},
                "target_level": tl, "comparison_level": ol,
                "target_evidence": t_depth[key]["evidence"][:3], "comparison_evidence": o_depth[key]["evidence"][:3],
                "difference": _depth_difference(tl, ol),
            })
        supported_demand = [r for r in skill_rows if r["industry"]["support_state"] in ("SUPPORTED", "HIGH_SUPPORT")]
        comparisons.append({
            "comparison_doc_id": doc["doc_id"], "comparison_role": doc["role"],
            "institution": doc.get("institution"), "programme": doc.get("programme"),
            "curriculum_version": doc.get("curriculum_version"), "academic_year": doc.get("academic_year"),
            "source_url": doc.get("source_url"), "sha256": doc.get("sha256"), "retrieved_at": doc.get("retrieved_at"),
            "scope": {"courses": len(c_courses), "clean_topics": len(c_topics), "concepts": len(concepts),
                      "single_topic_units": len(singles),
                      "target_courses": len({t["course_uid"] for t in t_topics.values()}), "target_clean_topics": len(t_topics),
                      "target_concepts": len(target.concepts)},
            "coverage_levels": {
                "exact_lexical": _share(len(t_exact & o_exact), len(t_exact),
                                        "target topics whose text occurs verbatim (case/space-insensitive) in the comparison curriculum"),
                "normalized": _share(len(t_norm & o_norm), len(t_norm), "target topics equal after normalisation"),
                "semantic_concept": {**_share(covered, len(target.concepts),
                                              "target concepts with a SUPPORTED SAME_CONCEPT / PARENT / CHILD relation"),
                                     "by_relationship": dict(sorted(concept_cov.items()))},
                "semantic_related": _share(related_cov, len(target.concepts),
                                           "target concepts with ANY SUPPORTED relation (SAME_CONCEPT, PARENT, CHILD, "
                                           "PARTIAL_OVERLAP or RELATED) -- related content, not equivalence"),
                "review_required": _share(review_cov, len(target.concepts),
                                          "target concepts whose best candidate needs review (never counted as coverage)"),
                "skill": {"target_skills": len(t_skill_set), "comparison_skills": len(o_skill_set),
                          "shared": len(t_skill_set & o_skill_set), "target_only": len(t_skill_set - o_skill_set),
                          "comparison_only": len(o_skill_set - t_skill_set),
                          "definition": "ESCO skills that are the DIRECT/PARTIAL subject of an established topic mention"},
                "depth": {"demand_skills_compared": len(skill_rows),
                          "target_levels": dict(Counter(r["target_level"] for r in skill_rows)),
                          "comparison_levels": dict(Counter(r["comparison_level"] for r in skill_rows)),
                          "differences": dict(Counter(r["difference"] for r in skill_rows))},
            },
            "differences": {
                "target_concepts_absent_from_comparison": [target.evidence(c, 2) for c in target.concepts
                                                           if c["concept_uid"] not in best][: pcfg["list_limit"]],
                "comparison_concepts_absent_from_target": reverse_absent(target, other, rows)[: pcfg["list_limit"]],
                "shared_concepts": _pick(best, "SAME_CONCEPT", pcfg["list_limit"]),
                "different_terminology": [r for r in _pick(best, "SAME_CONCEPT", 10 ** 6)
                                          if not r["evidence"]["normalized_name_equal"]][: pcfg["list_limit"]],
                "related_not_equivalent": (_pick(best, "RELATED", pcfg["list_limit"]) + _pick(best, "PARTIAL_OVERLAP", pcfg["list_limit"])),
                "ambiguous": [r for r in best.values() if r["relationship"] == "AMBIGUOUS"][: pcfg["list_limit"]],
                "same_concept_review_required": [r for r in best.values() if r["relationship"] == "SAME_CONCEPT"
                                                 and r["evidence_state"] == "REVIEW_REQUIRED"][: pcfg["list_limit"]],
            },
            "industry_alignment": {
                "population_note": "industry demand is the run's supplied job-posting population; see population scope",
                "demand_skills_supported": len(supported_demand),
                "target_substantial_comparison_superficial": [_short(r) for r in skill_rows if r["difference"] == "TARGET_DEEPER"
                                                              and r["target_level"] in ("SUBSTANTIAL", "ADVANCED")],
                "in_comparison_not_target": [_short(r) for r in skill_rows if r["difference"] == "COMPARISON_ONLY"],
                "in_target_not_comparison": [_short(r) for r in skill_rows if r["difference"] == "TARGET_ONLY"],
                "different_depth": [_short(r) for r in skill_rows if r["difference"] in ("TARGET_DEEPER", "COMPARISON_DEEPER")],
            },
            "skill_rows": skill_rows,
            "note": "factual differences only; no institution is described as better or worse and no score is computed",
        })
    return {"status": status, "comparisons": comparisons, "relations": relations, "pending_review": pending_review,
            "config": pcfg, "method": __doc__.strip().splitlines()[0]}


def _share(n, d, definition):
    return {"count": n, "of": d, "pct": round(100.0 * n / d, 2) if d else None, "definition": definition}


def _pick(best, relationship, limit):
    return sorted((r for r in best.values() if r["relationship"] == relationship and r["evidence_state"] == "SUPPORTED"),
                  key=lambda r: (-r["evidence"]["similarity"], r["relation_uid"]))[:limit]


def _depth_difference(tl, ol):
    t_cov, o_cov = tl in COVERED_LEVELS, ol in COVERED_LEVELS
    if not t_cov and not o_cov:
        return "NEITHER"
    if t_cov and not o_cov:
        return "TARGET_ONLY"
    if o_cov and not t_cov:
        return "COMPARISON_ONLY"
    ti, oi = LEVEL_ORDER.index(tl), LEVEL_ORDER.index(ol)
    return "SAME_DEPTH" if ti == oi else ("TARGET_DEEPER" if ti > oi else "COMPARISON_DEEPER")


def _short(r):
    return {"skill_key": r["skill_key"], "skill_label": r["skill_label"], "target_level": r["target_level"],
            "comparison_level": r["comparison_level"], "industry": r["industry"],
            "target_evidence": r["target_evidence"][:2], "comparison_evidence": r["comparison_evidence"][:2]}
