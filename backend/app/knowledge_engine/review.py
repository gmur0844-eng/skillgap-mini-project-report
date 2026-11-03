"""
Prioritised human review + concept versioning.

Review priority (thresholds in config["review"]):
  HIGH    support >= high_min_support, members from >= 2 source roles
          (e.g. target AND reference), >= 2 courses, and a specific name
          (>= 2 words, or one word of >= 8 letters). Capped at
          max_high_items; overflow is demoted to MEDIUM with a note.
  MEDIUM  support >= medium_min_support, or cross-role evidence
  LOW     everything else, plus generic / low-specificity names

Human decisions live in data/metadata/review_decisions.json and are applied
on every run: ACCEPT -> HUMAN_VALIDATED, REJECT -> excluded from GOLD
concepts (kept in the review file), RENAME -> validated with a new display
name (the discovered name is kept too). With no decisions the queue stays
review_decision = null; approval is never fabricated.

Concept versioning: data/gold/knowledge/concept_registry.json keeps every
concept uid ever produced with first_seen_run, last_seen_run and
absent_since_run. Run directories are immutable, so historical results stay
reproducible; a concept that disappears is marked, not deleted.
"""
import json
from pathlib import Path


def _specific(name):
    words = [w for w in name.split() if w.isalpha() or any(ch.isalpha() for ch in w)]
    return len(words) >= 2 or (len(words) == 1 and len(words[0]) >= 8)


def assign_priority(concepts, cfg):
    r = cfg["review"]
    for c in concepts:
        cross = len(c["source_roles"]) >= 2
        if (c["support"] >= r["high_min_support"] and cross and len(c["course_uids"]) >= 2 and _specific(c["name"])):
            c["review_priority"] = "HIGH"
        elif (c["support"] >= r["medium_min_support"] or cross) and _specific(c["name"]):
            c["review_priority"] = "MEDIUM"
        else:
            c["review_priority"] = "LOW"
            if not _specific(c["name"]):
                c.setdefault("review_flags", []).append("GENERIC_NAME: low-specificity label; may merge unrelated senses")
    high = sorted((c for c in concepts if c["review_priority"] == "HIGH"),
                  key=lambda c: (-len(c["source_roles"]), -c["support"], c["name"]))
    for c in high[r["max_high_items"]:]:
        c["review_priority"] = "MEDIUM"
        c.setdefault("review_flags", []).append("DEMOTED: HIGH list capped to keep human review small")
    return concepts


def related_in_order(pairs, names):
    """Related concepts in a documented order -- relation, concept name, concept uid (unnamed ones last) -- so the
    six shown do not depend on the order in which the clustering happened to emit edges."""
    return sorted(pairs, key=lambda p: (p[0], p[1] not in names, names.get(p[1], ""), p[1]))


def build_review_queue(concepts, families_by_uid, topics_by_uid, courses_by_uid, edges, ref_status_by_concept):
    related = {}
    for e in edges:
        if e["relationship"] in ("PARENT", "CO_OCCURS_IN_UNIT"):
            related.setdefault(e["source_uid"], []).append((e["relationship"], e["target_uid"]))
            related.setdefault(e["target_uid"], []).append((e["relationship"] + "_OF" if e["relationship"] == "PARENT" else e["relationship"], e["source_uid"]))
    names = {c["concept_uid"]: c["name"] for c in concepts}
    items = []
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    for c in sorted(concepts, key=lambda c: (order[c["review_priority"]], -c["support"], c["name"])):
        members = [topics_by_uid[u] for u in c["member_topic_uids"]]

        def evidence(role):
            return [{"text": m["clean_text"], "course": courses_by_uid[m["course_uid"]]["title"],
                     "course_code": m["course_code"], "unit": m["unit_label"], "page": m["page_number"], "doc_id": m["doc_id"]}
                    for m in members if m["role"] == role][:5]  # noqa: B023 -- called within this iteration
        items.append({
            "review_item_uid": c["concept_uid"], "priority": c["review_priority"],
            "proposed_concept": c["name"], "discipline": c["discipline"],
            "concept_family": families_by_uid[c["family_uid"]]["name"],
            "support": c["support"], "courses": len(c["course_uids"]), "source_roles": c["source_roles"],
            "target_evidence": evidence("TARGET"), "reference_evidence": evidence("REFERENCE"),
            "previous_version_evidence": evidence("PREVIOUS_VERSION"),
            "reference_status": ref_status_by_concept.get(c["concept_uid"], {}).get("status"),
            "candidate_related_concepts": [{"relation": rel, "concept": names.get(other)}
                                           for rel, other in related_in_order(related.get(c["concept_uid"], []), names)[:6]
                                           if other in names],
            "potential_conflicts": c.get("review_flags", []),
            "mean_member_similarity_to_centroid": c["mean_member_similarity_to_centroid"],
            "review_decision": None, "reviewer": None, "decided_at": None, "notes": None,
        })
    return items


def load_decisions(path):
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {d["review_item_uid"]: d for d in data.get("decisions", []) if d.get("review_decision")}


def apply_decisions(concepts, decisions):
    applied, kept = [], []
    for c in concepts:
        d = decisions.get(c["concept_uid"])
        if d is None:
            kept.append(c)
            continue
        applied.append({"concept_uid": c["concept_uid"], **d})
        if d["review_decision"] == "REJECT":
            continue
        c["evidence_status"] = "HUMAN_VALIDATED"
        c["validation"] = {k: d.get(k) for k in ("review_decision", "reviewer", "decided_at", "notes")}
        if d["review_decision"] == "RENAME" and d.get("new_name"):
            c["discovered_name"], c["name"] = c["name"], d["new_name"]
        kept.append(c)
    return kept, applied


def update_registry(path, run_id, concepts):
    p = Path(path)
    registry = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"concepts": {}}
    present = set()
    for c in concepts:
        present.add(c["concept_uid"])
        entry = registry["concepts"].setdefault(c["concept_uid"], {"first_seen_run": run_id, "discipline": c["discipline"]})
        entry.update({"name": c["name"], "last_seen_run": run_id, "absent_since_run": None})
    for concept_uid, entry in registry["concepts"].items():
        if concept_uid not in present and entry.get("absent_since_run") is None and entry.get("last_seen_run") != run_id:
            entry["absent_since_run"] = run_id
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(registry, indent=1, sort_keys=True), encoding="utf-8")
    return {"total_known": len(registry["concepts"]), "present_in_run": len(present),
            "absent": sum(1 for e in registry["concepts"].values() if e.get("absent_since_run"))}
