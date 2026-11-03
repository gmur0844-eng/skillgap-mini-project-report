"""
Build the FROZEN human-review set (semantic validation v1) from one GOLD run.

    python3 scripts/review/build_review_set.py [--run-id RUN] [--version v1]

Writes data/human_validation/<version>/:
  review_items.json      every item with its full original evidence (read-only reference)
  review_file.csv/.xlsx  the file a person fills in (human_* columns empty)
  freeze_manifest.json   run id, content digest, code / parser fingerprints, config hash and a
                         hash of every item's model fields -- the ingest script refuses a returned
                         file if any of these changed

Selection is deterministic (fixed sort keys, no randomness) and targets the smallest set
that can change conclusions: recommendation-affecting evidence, parent/child links,
ambiguous and low-context mappings, drift that drives conclusions, missed-match candidates,
concept coherence, and the industry/ESCO sense questions. human_label is NEVER filled here.
"""
import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.knowledge_engine.semantic_backend import TfidfBackend  # noqa: E402

OPTIONS = ["SAME_CONCEPT", "PARENT", "CHILD", "RELATED", "PARTIAL_OVERLAP", "UNRELATED", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE"]
LETTERS = dict(zip("ABCDEFGH", OPTIONS))
HUMAN_FIELDS = ["human_label", "human_note", "human_error_category", "reviewer", "review_timestamp"]
CSV_COLUMNS = ["review_id", "priority", "item_kind", "source", "question", "left_text", "left_context", "right_text",
               "right_context", "model_relationship", "model_similarity", "lexical_similarity", "context_similarity",
               "mapping_method", "split"] + HUMAN_FIELDS
SPLITS = (("DEVELOPMENT", 0.4), ("VALIDATION", 0.3), ("FINAL_TEST", 0.3))


def jl(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()] if Path(path).exists() else []


def split_for(review_id):
    x = int(hashlib.sha256(review_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    acc = 0.0
    for name, share in SPLITS:
        acc += share
        if x <= acc:
            return name
    return SPLITS[-1][0]


def build(run_id, version):
    gold = REPO / "data/gold/knowledge" / run_id
    report = json.loads((gold / "run_report.json").read_text())
    courses = {c["course_uid"]: c for c in jl(gold / "courses.jsonl")}
    topics = {}
    for doc in report["documents"]:
        for t in jl(REPO / "data/silver/curricula" / doc["doc_id"] / doc["sha256"][:16] / "topics.jsonl"):
            topics[t["topic_uid"]] = t
    mappings = jl(gold / "topic_mappings.jsonl")
    concepts = {c["concept_uid"]: c for c in jl(gold / "concepts.jsonl")}
    drift = jl(gold / "concept_drift.jsonl")
    concept_review = jl(gold / "review_queue.jsonl")
    ind = gold / "industry"
    skills = {s["skill_key"]: s for s in jl(ind / "skills.jsonl")}
    mentions = jl(ind / "skill_mentions.jsonl")
    coverage = jl(ind / "curriculum_skill_coverage.jsonl")
    demand = {d["skill_key"]: d for d in jl(ind / "industry_demand.jsonl")}
    ind_review = jl(ind / "industry_review_queue.jsonl")
    recs = jl(ind / "recommendations.jsonl")
    postings = {p["posting_uid"]: p for p in jl(ind / "postings.jsonl")}

    def tctx(t):
        c = courses.get(t["course_uid"], {})
        return f"{t['doc_id']} | {c.get('course_code')} {c.get('title')} | {t.get('unit_label') or '-'} | p.{t['page_number']}"

    items = []

    def add(kind, priority, source, question, left, left_ctx, right, right_ctx, model_rel, model_sim=None,
            lexical=None, context=None, method=None, evidence=None):
        rid = f"{version}-{len(items) + 1:03d}"
        items.append({"review_id": rid, "priority": priority, "item_kind": kind, "source": source, "question": question,
                      "left_text": left, "left_context": left_ctx, "right_text": right, "right_context": right_ctx,
                      "model_relationship": model_rel, "model_similarity": model_sim, "lexical_similarity": lexical,
                      "context_similarity": context, "mapping_method": method, "split": split_for(rid),
                      "options": OPTIONS, "original_evidence": evidence or {}, **{f: None for f in HUMAN_FIELDS}})

    # ---- curriculum (40) ------------------------------------------------------------------------
    # A. recommendation-affecting: every target topic that makes SQL "covered" (drives the only recommendation)
    for r in recs:
        cov = next((c for c in coverage if c["skill_key"] == r["skill_key"] and c["role"] == "target_doc"), None)
        for e in (cov or {}).get("topic_evidence", [])[:4]:
            add("TOPIC_TO_SKILL", "HIGH", "recommendation evidence", f"Does this curriculum topic teach the skill '{r['skill_label']}'?",
                e["text"], f"{e['course_code']} {e['course_title']} | {e.get('unit') or '-'} | p.{e['page']}",
                r["skill_label"], f"ESCO {r['skill_key']} | recommendation {r['action_type']} {r['target_course_codes']}",
                "SAME_CONCEPT (counted as coverage)", None, None, None, "exact label in topic text",
                {"topic_uid": e["topic_uid"], "recommendation_uid": r["recommendation_uid"], "raw_mention": e["raw_mention"]})
    linked = [m for m in mappings if m.get("target_uid")]

    def mapping_item(m, kind, priority, source):
        t, ref = topics.get(m["source_uid"]), topics.get(m["target_uid"])
        sig = m.get("signals") or {}
        add(kind, priority, source, "What is the relationship of the LEFT (CBIT R22A) topic to the RIGHT (AICTE) topic?",
            m["source_text"], tctx(t) if t else "", ref["clean_text"] if ref else "", tctx(ref) if ref else "",
            m["relationship"], m.get("similarity_score"), sig.get("lexical_similarity"), sig.get("context_similarity"),
            m.get("method"), {"mapping_uid": m["mapping_uid"], "evidence_status": m["evidence_status"]})

    def low_ctx(rows):
        return sorted(rows, key=lambda m: ((m.get("signals") or {}).get("context_similarity") or 0.0, m["mapping_uid"]))
    # B. parent/child links with the least shared unit context (most likely wrong)
    for rel in ("PARENT", "CHILD"):
        for m in low_ctx([m for m in linked if m["relationship"] == rel])[:4]:
            mapping_item(m, "TOPIC_TO_REFERENCE_TOPIC", "HIGH", f"parent/child mapping ({rel})")
    # C. ambiguous mappings (two reference candidates too close)
    for m in sorted([m for m in mappings if m["relationship"] == "AMBIGUOUS"], key=lambda m: -(m["similarity_score"] or 0))[:4]:
        t = topics.get(m["source_uid"])
        cands = (m.get("explanation") or {}).get("candidates_considered", [])[:2]
        add("TOPIC_TO_REFERENCE_TOPIC", "HIGH", "ambiguous mapping", "Which relationship holds between LEFT and the FIRST candidate on the right?",
            m["source_text"], tctx(t) if t else "", " || ".join(c["reference_text"] for c in cands),
            " || ".join(f"p.{c['reference_page']} sim {c['similarity_score']}" for c in cands), "AMBIGUOUS",
            m["similarity_score"], None, None, m.get("method"), {"mapping_uid": m["mapping_uid"]})
    # D. drift conclusions: largest ADDED / REMOVED concepts vs the most similar topic of the other version
    prev_doc = next(d["doc_id"] for d in report["documents"] if d["role"] == "PREVIOUS_VERSION")
    target_doc = next(d["doc_id"] for d in report["documents"] if d["role"] == "TARGET")
    semesters = set(report.get("comparable_semesters_for_drift") or [])
    pool = {doc: [t for t in topics.values() if t["doc_id"] == doc and t["noise_label"] == "TOPIC"
                  and courses.get(t["course_uid"], {}).get("semester") in semesters] for doc in (prev_doc, target_doc)}
    backend = TfidfBackend()
    backend.fit([t["clean_text"] for doc in pool for t in pool[doc]])
    for status, other in (("REMOVED", target_doc), ("ADDED", prev_doc)):
        rows = sorted([d for d in drift if d["status"] == status], key=lambda d: (-(d["previous_support"] + d["target_support"]), d["concept"]))[:3]
        for d in rows:
            ex = (d["previous_examples"] or d["target_examples"])[0]
            family = concepts.get(d["concept_uid"], {}).get("family_uid")
            candidates = [t for t in pool[other] if courses.get(t["course_uid"], {}).get("family_uid") == family] or pool[other]
            sims = backend.similarity(backend.embed([ex["text"]]), backend.embed([t["clean_text"] for t in candidates]))[0]
            j = int(sims.argmax())
            pool_other = candidates
            add("DRIFT_CONCEPT", "HIGH", f"concept drift {status}",
                f"The model says concept '{d['concept']}' was {status}. What is the relationship of LEFT to the closest topic of the other version (RIGHT)?",
                ex["text"], f"{ex['course']} p.{ex['page']} (concept '{d['concept']}', prev {d['previous_support']} / target {d['target_support']})",
                pool_other[j]["clean_text"], tctx(pool_other[j]) + " (closest topic in the same course family)",
                f"drift {status}: no same-concept match", round(float(sims[j]), 4),
                round(float(sims[j]), 4), None, "concept membership (TF-IDF clustering)", {"concept_uid": d["concept_uid"]})
    # E, F. linked mappings with the least shared context
    for m in low_ctx([m for m in linked if m["relationship"] == "SAME_CONCEPT"])[:4]:
        mapping_item(m, "TOPIC_TO_REFERENCE_TOPIC", "MEDIUM", "same-concept mapping, low shared context")
    for m in low_ctx([m for m in linked if m["relationship"] in ("RELATED", "PARTIAL_OVERLAP")])[:4]:
        mapping_item(m, "TOPIC_TO_REFERENCE_TOPIC", "MEDIUM", "related/partial mapping, low shared context")
    # G. possible missed matches: unmapped topics whose best in-scope candidate was just below the threshold
    near = []
    for m in mappings:
        cands = (m.get("explanation") or {}).get("candidates_considered") or []
        if not m.get("target_uid") and cands and m["relationship"] != "AMBIGUOUS":  # ambiguous ones are section C
            near.append((cands[0]["similarity_score"], m, cands[0]))
    for sim, m, c in sorted(near, key=lambda x: (-x[0], x[1]["mapping_uid"]))[:4]:
        t, ref = topics.get(m["source_uid"]), topics.get(c["reference_topic_uid"])
        add("TOPIC_TO_REFERENCE_TOPIC", "MEDIUM", "unmapped: best candidate below threshold",
            "What is the relationship of LEFT to the best rejected candidate RIGHT?", m["source_text"], tctx(t) if t else "",
            c["reference_text"], tctx(ref) if ref else "", m["relationship"] + " (unmapped)", sim, sim, None, m.get("method"),
            {"mapping_uid": m["mapping_uid"]})
    # H. concept coherence: HIGH-priority discovered concepts, one member vs the concept name
    for r in [i for i in concept_review if i["priority"] == "HIGH"][:6]:
        c = concepts.get(r["review_item_uid"])
        member = topics.get(c["member_topic_uids"][-1]) if c else None
        add("TOPIC_TO_CONCEPT", "MEDIUM", "discovered concept", f"Is the LEFT topic an instance of the discovered concept '{r['proposed_concept']}'?",
            member["clean_text"] if member else "", tctx(member) if member else "", r["proposed_concept"],
            f"{r['support']} member topics, {r['courses']} courses, family '{r['concept_family']}'", "SAME_CONCEPT (member)",
            r.get("mean_member_similarity_to_centroid"), None, None, "agglomerative clustering (TF-IDF)", {"concept_uid": r["review_item_uid"]})

    # ---- industry / ESCO (14) -------------------------------------------------------------------
    def posting_ctx(m):
        p = postings.get(m["source_uid"], {})
        return f"{p.get('job_title')} ({p.get('company_name')}) | {p.get('source_file')} row {p.get('row_number')} | …{m['context'].strip()[:160]}…"
    order = {"HIGH": 0, "MEDIUM": 1}
    used_subjects = set()
    wanted = [("ALIAS_SENSE_CHECK", 4), ("ACRONYM_SENSE_CHECK", 2), ("AMBIGUOUS_ESCO_MAPPING", 1),
              ("DISCIPLINE_RELEVANCE_UNESTABLISHED", 2), ("HIGH_FREQUENCY_CONTEXT_DEPENDENT_LABEL", 2),
              ("HIGH_DEMAND_UNMAPPED_SKILL", 2)]
    for kind, n in wanted:
        chosen = sorted([i for i in ind_review if i["kind"] == kind], key=lambda i: (order.get(i["priority"], 2), i["subject"]))
        chosen = sorted(chosen, key=lambda i: -(i["detail"].get("postings") or i["detail"].get("postings_with_raw_mention") or 0))
        chosen = [i for i in chosen if i["subject"] not in used_subjects][:n]
        for i in chosen:
            if i["subject"] in used_subjects:
                continue
            used_subjects.add(i["subject"])
            s = skills.get(i["subject"])
            ms = [m for m in mentions if (m["skill_key"] == i["subject"] or m["normalized_text"] == i["subject"])
                  and m["mention_role"] == "SKILL"]
            if kind == "AMBIGUOUS_ESCO_MAPPING":
                cands = i["detail"]["candidates"]
                right, rctx, rel = " || ".join(c["label"] for c in cands), " || ".join(c["uri"] for c in cands), "AMBIGUOUS"
            elif kind in ("ALIAS_SENSE_CHECK",):
                right, rctx = i["detail"]["esco_candidate"], f"{i['detail']['esco_uri']} | {i['detail']['esco_evidence']}"
                rel = "TAXONOMY_ALIAS_MATCH (meaning not established)"
            elif kind == "ACRONYM_SENSE_CHECK":
                right, rctx, rel = (s or {}).get("label", i["subject"]), "curated technical-token list (no ESCO label in the delta subset)", \
                    "CURATED_TOKEN (sense not established)"
            else:
                right = (s or {}).get("esco_pref_label") or (s or {}).get("label") or i["subject"]
                rctx = f"ESCO {(s or {}).get('esco_uri') or (s or {}).get('taxonomy_candidate_uri') or '-'} | status {(s or {}).get('esco_status')}"
                rel = {"DISCIPLINE_RELEVANCE_UNESTABLISHED": "SAME_CONCEPT (counted; programme relevance unestablished)",
                       "HIGH_DEMAND_UNMAPPED_SKILL": "UNMAPPED (not in the ESCO delta subset)"}.get(
                    kind, "INSUFFICIENT_EVIDENCE (single ordinary word)")
            question = i["detail"].get("question") or ("Does the posting text mean this ESCO skill?" if kind != "DISCIPLINE_RELEVANCE_UNESTABLISHED"
                                                       else "Does the posting text mean this skill (and is it a job requirement)?")
            m0 = ms[0] if ms else None
            add("JOB_MENTION_TO_ESCO", "HIGH" if i["priority"] == "HIGH" else "MEDIUM", kind.lower(), question,
                m0["raw_mention"] if m0 else i["subject"], posting_ctx(m0) if m0 else "", right, rctx, rel, None, None, None,
                (s or {}).get("mapping_method"), {"review_item_uid": i["review_item_uid"], "skill_key": i["subject"],
                                                  "postings": len({m["source_uid"] for m in ms}),
                                                  "other_contexts": [posting_ctx(m) for m in ms[1:6]]})
    # recommendation-affecting ESCO link (the SQL recommendation)
    for r in recs:
        s = skills[r["skill_key"]]
        m0 = next(m for m in mentions if m["skill_key"] == r["skill_key"] and m["sense_established"])
        add("JOB_MENTION_TO_ESCO", "HIGH", "recommendation evidence", f"Does this posting text mean the ESCO skill '{s['esco_pref_label']}'?",
            m0["raw_mention"], posting_ctx(m0), s["esco_pref_label"], f"ESCO {s['esco_uri']} | {s['mapping_method']}",
            f"SAME_CONCEPT ({s['esco_status']})", None, None, None, s["mapping_method"],
            {"skill_key": r["skill_key"], "postings": demand[r["skill_key"]]["posting_count"], "recommendation_uid": r["recommendation_uid"]})
    return items, report


def model_fields_hash(item):
    frozen = {k: v for k, v in item.items() if k not in HUMAN_FIELDS}
    return hashlib.sha256(json.dumps(frozen, sort_keys=True, default=str).encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id")
    ap.add_argument("--version", default="v1")
    args = ap.parse_args()
    run_id = args.run_id or json.loads((REPO / "data/gold/knowledge/latest_run.json").read_text())["run_id"]
    items, report = build(run_id, args.version)
    out = REPO / "data/human_validation" / args.version
    if (out / "freeze_manifest.json").exists():
        sys.exit(f"{out} already frozen; create a new version instead of overwriting a review set")
    out.mkdir(parents=True, exist_ok=True)
    (out / "review_items.json").write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
    with (out / "review_file.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for it in items:
            w.writerow({**it, **{f: "" for f in HUMAN_FIELDS}})
    try:
        import pandas as pd
        frame = pd.DataFrame([{c: it.get(c) for c in CSV_COLUMNS} for it in items])
        with pd.ExcelWriter(out / "review_file.xlsx") as xw:
            frame.to_excel(xw, sheet_name="review", index=False)
            pd.DataFrame({"letter": list(LETTERS), "human_label": list(LETTERS.values())}).to_excel(xw, sheet_name="options", index=False)
    except Exception as exc:  # the CSV is the canonical file
        print("xlsx not written:", exc)
    manifest = {
        "dataset_version": args.version, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": run_id, "content_digest": report["content_digest"], "pipeline_version": report["pipeline_version"],
        "parser_fingerprint": report["parser_fingerprint"], "code_fingerprint": report.get("code_fingerprint"),
        "config_hash": report["config_hash"], "semantic_backend": report["backend_resolution"],
        "items": len(items), "items_by_kind": {k: sum(1 for i in items if i["item_kind"] == k) for k in sorted({i["item_kind"] for i in items})},
        "items_by_split": {s: sum(1 for i in items if i["split"] == s) for s, _ in SPLITS},
        "allowed_labels": OPTIONS, "allowed_letters": LETTERS,
        "item_model_hashes": {i["review_id"]: model_fields_hash(i) for i in items},
        "review_file_sha256": hashlib.sha256((out / "review_file.csv").read_bytes()).hexdigest(),
        "freeze_rule": "model, configuration, thresholds, candidate generation and this dataset stay unchanged until the "
                       "returned review is ingested; the ingest script refuses a file if any recorded hash differs",
        "split_note": "deterministic hash split 40/30/30; with this few items the splits are too small for significance testing",
    }
    (out / "freeze_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("run_id", "items", "items_by_kind", "items_by_split")}, indent=1))


if __name__ == "__main__":
    main()
