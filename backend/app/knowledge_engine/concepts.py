"""
Subject-agnostic concept discovery.

Scoping (so unrelated subjects never mix because they share a word):
  1. DISCIPLINE -- hard boundary from source metadata. Each discipline is
     processed on its own; nothing from another discipline is visible.
  2. COURSE FAMILY -- discovered, not configured. Every course is represented
     by its title plus all of its clean topics; courses of ALL documents in
     the discipline (target, previous version, reference) are clustered
     together (KMeans, k chosen by silhouette in a configured range), so a
     target course and the reference course teaching similar content land
     in the same family. Families are the "concept family" level.
  3. CONCEPT -- topics are clustered only WITHIN their course's family
     (agglomerative, cosine distance, average linkage, distance threshold
     from config). A cluster with at least `min_support` topics is a
     candidate concept; singletons stay plain topics.

Concept names are derived from the member topics' own wording (the most
specific n-gram shared by at least half the members), never from a list.

Relationships emitted here (all MODEL_SUGGESTED, i.e. inferred):
  BELONGS_TO_FAMILY  concept -> family
  PARENT             concept whose name tokens are a strict subset of another
                     concept's name tokens in the same family (source is the
                     broader concept)
  CO_OCCURS_IN_UNIT  two concepts that share a unit in at least two distinct
                     courses (the co-occurrence itself is extracted fact; the
                     relatedness it suggests is an inference)
"""
import re
from collections import Counter, defaultdict

import numpy as np
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import silhouette_score

from app.analytics.concept_semantic_matching import _STOPWORDS, _stemming_tokenizer
from app.knowledge_engine.silver import uid

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#\-']*")


def _content_words(text):
    return [w for w in _WORD_RE.findall(text) if w.lower() not in _STOPWORDS and len(w) > 1]


def course_families(discipline, courses, topics_by_course, backend, cfg):
    """
    Returns (families, course_to_family, selection) where selection records
    the silhouette score of every k tried (for reproducibility / audit).
    """
    course_list = sorted(courses, key=lambda c: c["course_uid"])
    texts = [c["title"] + " . " + " . ".join(t["clean_text"] for t in topics_by_course.get(c["course_uid"], []))
             for c in course_list]
    matrix = backend.embed(texts)
    n = len(course_list)
    k_hi = min(cfg["k_max"], n - 1)
    selection = []
    best = None
    for k in range(max(2, cfg["k_min"]), k_hi + 1):
        labels = KMeans(n_clusters=k, random_state=cfg["random_state"], n_init=10).fit_predict(matrix)
        if len(set(labels)) < 2:
            continue
        score = float(silhouette_score(matrix, labels, metric="cosine"))
        selection.append({"k": k, "silhouette_cosine": round(score, 4)})
        if best is None or score > best[0] + 1e-9:
            best = (score, k, labels)
    if best is None:
        labels = np.zeros(n, dtype=int)
        chosen = {"k": 1, "silhouette_cosine": None}
    else:
        labels = best[2]
        chosen = {"k": best[1], "silhouette_cosine": round(best[0], 4)}

    families, course_to_family = [], {}
    for label in sorted(set(labels)):
        member_idx = [i for i, lab in enumerate(labels) if lab == label]
        member_courses = [course_list[i] for i in member_idx]
        fam_uid = uid("family", discipline, *sorted(c["course_uid"] for c in member_courses))
        terms = backend.top_terms(matrix[member_idx], n=4)
        families.append({
            "family_uid": fam_uid, "discipline": discipline,
            "name": " / ".join(terms) if terms else "(unnamed)",
            "name_method": "top TF-IDF terms of member courses (descriptive label, not a curated name)",
            "course_uids": [c["course_uid"] for c in member_courses],
            "course_titles": [f"{c['course_code']} {c['title']}" for c in member_courses],
            "documents": sorted({c["doc_id"] for c in member_courses}),
            "evidence_status": "DISCOVERED",
        })
        for c in member_courses:
            course_to_family[c["course_uid"]] = fam_uid
    return families, course_to_family, {"tried": selection, "chosen": chosen, "method": "KMeans + cosine silhouette"}


def _concept_name(member_texts):
    """Most specific n-gram (3 -> 1 words) present in at least half of the
    members; falls back to the most frequent content word. Surface form is
    the most common original casing."""
    token_lists = [_content_words(t) for t in member_texts]
    need = max(1, int(np.ceil(0.5 * len(member_texts))))
    for n in (3, 2, 1):
        df = Counter()
        surface = defaultdict(Counter)
        for tokens in token_lists:
            seen = set()
            for i in range(len(tokens) - n + 1):
                gram = tokens[i:i + n]
                key = " ".join(w.lower() for w in gram)
                if key not in seen:
                    df[key] += 1
                    seen.add(key)
                surface[key][" ".join(gram)] += 1
        winners = [(count, key) for key, count in df.items() if count >= need]
        if winners:
            winners.sort(key=lambda x: (-x[0], x[1]))
            key = winners[0][1]
            form = surface[key].most_common(1)[0][0]
            return form if not form.isupper() else form.title()
    words = Counter(w.lower() for tokens in token_lists for w in tokens)
    return words.most_common(1)[0][0].title() if words else "(unnamed)"


def discover_concepts(discipline, family, family_topics, backend, cfg, doc_roles):
    """Cluster one family's clean topics into candidate concepts."""
    if len(family_topics) < cfg["min_support"]:
        return [], {}
    matrix = backend.embed([t["clean_text"] for t in family_topics])
    sims = backend.similarity(matrix, matrix)
    distances = np.clip(1.0 - sims, 0.0, 2.0)
    np.fill_diagonal(distances, 0.0)
    labels = AgglomerativeClustering(metric="precomputed", linkage="average", n_clusters=None,
                                     distance_threshold=cfg["distance_threshold"]).fit_predict(distances)
    concepts, topic_to_concept = [], {}
    members_of = defaultdict(list)   # one pass instead of one scan of every label per cluster (quadratic)
    for i, lab in enumerate(labels):
        members_of[lab].append(i)
    for label in sorted(members_of):
        idx = members_of[label]
        if len(idx) < cfg["min_support"]:
            continue
        members = sorted((family_topics[i] for i in idx), key=lambda t: t["topic_uid"])
        member_uids = [m["topic_uid"] for m in members]
        centroid = np.asarray(matrix[idx].mean(axis=0)).ravel()
        norm = np.linalg.norm(centroid) or 1.0
        member_sims = np.asarray(matrix[idx] @ centroid).ravel() / norm
        concept_uid = uid("concept", discipline, *member_uids)
        docs = sorted({m["doc_id"] for m in members})
        roles = sorted({doc_roles[d] for d in docs})
        concept = {
            "concept_uid": concept_uid, "discipline": discipline, "family_uid": family["family_uid"],
            "name": _concept_name([m["clean_text"] for m in members]),
            "name_method": "most specific n-gram shared by >= half the member topics",
            "support": len(members), "member_topic_uids": member_uids,
            "source_documents": docs, "source_roles": roles,
            "course_uids": sorted({m["course_uid"] for m in members}),
            "pages": sorted({(m["doc_id"], m["page_number"]) for m in members}),
            "mean_member_similarity_to_centroid": round(float(np.mean(member_sims)), 4),
            "evidence_status": "DISCOVERED",
        }
        concepts.append(concept)
        for m in members:
            topic_to_concept[m["topic_uid"]] = concept_uid
    return concepts, topic_to_concept


def concept_edges(concepts, topics_by_uid):
    edges = []
    by_family = defaultdict(list)
    for c in concepts:
        by_family[c["family_uid"]].append(c)
        edges.append({"edge_uid": uid("edge", c["concept_uid"], c["family_uid"], "BELONGS_TO_FAMILY"),
                      "source_uid": c["concept_uid"], "target_uid": c["family_uid"], "relationship": "BELONGS_TO_FAMILY",
                      "method": "course_family_membership", "evidence_status": "DISCOVERED"})
    # PARENT by strict name-token containment inside a family
    for fam_concepts in by_family.values():
        stems = {c["concept_uid"]: set(_stemming_tokenizer(c["name"])) for c in fam_concepts}
        for broad in fam_concepts:
            for narrow in fam_concepts:
                sb, sn = stems[broad["concept_uid"]], stems[narrow["concept_uid"]]
                if broad is not narrow and sb and sb < sn:
                    edges.append({"edge_uid": uid("edge", broad["concept_uid"], narrow["concept_uid"], "PARENT"),
                                  "source_uid": broad["concept_uid"], "target_uid": narrow["concept_uid"],
                                  "relationship": "PARENT", "method": "name_token_containment_within_family",
                                  "evidence_status": "MODEL_SUGGESTED",
                                  "evidence": {"broader": broad["name"], "narrower": narrow["name"]}})
    # CO_OCCURS_IN_UNIT across >= 2 distinct courses
    unit_concepts = defaultdict(set)
    for c in concepts:
        for t_uid in c["member_topic_uids"]:
            t = topics_by_uid[t_uid]
            unit_concepts[(t["course_uid"], t["unit_label"])].add(c["concept_uid"])
    pair_courses = defaultdict(set)
    for (course_uid, _), cset in unit_concepts.items():
        ordered = sorted(cset)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                pair_courses[(ordered[i], ordered[j])].add(course_uid)
    for (a, b), course_set in sorted(pair_courses.items()):
        if len(course_set) >= 2:
            edges.append({"edge_uid": uid("edge", a, b, "CO_OCCURS_IN_UNIT"), "source_uid": a, "target_uid": b,
                          "relationship": "CO_OCCURS_IN_UNIT", "method": "same_unit_in_multiple_courses",
                          "evidence_status": "MODEL_SUGGESTED",
                          "evidence": {"distinct_courses": len(course_set), "course_uids": sorted(course_set)}})
    return edges
