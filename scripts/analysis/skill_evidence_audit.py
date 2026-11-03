"""Skill evidence v0.2: generalization audit and scorecard (EXPERIMENTAL; writes only to data/experiments/).

    python3 scripts/analysis/skill_evidence_audit.py                 # release 498 + development + validation + synthetic
    python3 scripts/analysis/skill_evidence_audit.py --final-holdout # also the sealed final holdout (run once, frozen code)

Evaluation sets (labels kept strictly apart by source):
  development  data/evaluation/skill_qualification_benchmark_v1   AUTHOR_LABELLED   used while designing v0.1/v0.2
  validation   data/evaluation/skill_qualification_validation_v1  INDEPENDENT_MODEL_LABELLED (not human)
  holdout      data/evaluation/skill_qualification_holdout_v1     INDEPENDENT_MODEL_LABELLED (not human); sealed
  synthetic    data/evaluation/skill_generalization_suite_v1      AUTHOR_LABELLED, written before v0.2; unseen phrases,
                                                                   disciplines, writing styles, adversarial cases
  No set has independent human labels yet (labels_human.* are empty templates).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts/analysis"))

import relevance_audit as ra  # noqa: E402
from app.knowledge_engine import industry, industry_stage  # noqa: E402
from app.knowledge_engine import relevance as rel  # noqa: E402
from app.knowledge_engine import skill_evidence as se  # noqa: E402

EVAL = REPO / "data/evaluation"
SETS = {"development": ("skill_qualification_benchmark_v1", "labels_assistant.jsonl", "AUTHOR_LABELLED"),
        "validation": ("skill_qualification_validation_v1", "labels_independent_model.jsonl",
                       "INDEPENDENT_MODEL_LABELLED (not human)"),
        "holdout": ("skill_qualification_holdout_v1", "labels_independent_model.jsonl",
                    "INDEPENDENT_MODEL_LABELLED (not human)")}
ERROR_CLASSES = {
    "E1": "BOILERPLATE", "E2": "GENERIC_ACTION", "E3": "INSUFFICIENT_CONTEXT", "E4": "WRONG_ENTITY",
    "E5": "WRONG_SENSE", "E6": "LIST_EXTRACTION", "E7": "VERB_FORM_EXTRACTION", "E8": "SECTION_MISCLASSIFICATION",
    "E9": "DOMAIN_RELEVANCE_ERROR", "E10": "PROGRAMME_RELEVANCE_ERROR", "E11": "TAXONOMY_MAPPING_ERROR",
    "E12": "OVER_ABSTENTION"}


def jl(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]


def lit(v):
    return ra.lit(v)


# ------------------------------------------------------------------ shared qualification over a set of postings

def concepts_by_sentence(postings, mentions, mappings):
    out = defaultdict(set)
    by = {p["posting_uid"]: p for p in postings}
    for m in mentions:
        text = by[m["source_uid"]]["clean_description"]
        s0, s1 = se.sentence_bounds(text, tuple(lit(m["span"])))
        cands = lit((mappings.get(m["normalized_text"]) or {}).get("candidates")) or []
        uri = m["skill_key"] if str(m["skill_key"]).startswith("http") else (cands[0]["uri"] if len(cands) == 1 else None)
        out[(m["source_uid"], s0)].add(uri)
    return out


def qualify_all(postings, mentions, mappings, store_skills, profile, near, boiler=None):
    by = {p["posting_uid"]: p for p in postings}
    boiler = boiler or rel.boilerplate(postings)
    verbs = se.verb_lexicon(store_skills)
    sent = concepts_by_sentence(postings, mentions, mappings)
    structure = {u: se.parse_posting(p["clean_description"]) for u, p in by.items()}
    job_text = {}
    for u, p in by.items():
        t = p["clean_description"]
        job_text[u] = " ".join(t[a:b] for a, b, k, _ in boiler[u] if k != "EMPLOYER_BOILERPLATE")
    mentions = se.expand_occurrences(mentions, {u: p["clean_description"] for u, p in by.items()})
    sent = concepts_by_sentence(postings, mentions, mappings)
    out = []
    for m in sorted(mentions, key=lambda x: (x["source_uid"], x.get("mention_uid") or "", lit(x["span"])[0])):
        p = by[m["source_uid"]]
        text = p["clean_description"]
        span = tuple(lit(m["span"]))
        s0, _ = se.sentence_bounds(text, span)
        q = se.qualify(m, mappings.get(m["normalized_text"]), store_skills, text,
                       rel.segment_state(boiler[m["source_uid"]], span), structure[m["source_uid"]], verbs, profile,
                       near, sent[(m["source_uid"], s0)], job_text[m["source_uid"]], p.get("company_name"),
                       p.get("job_title"))
        q["job_title"], q["company"] = p.get("job_title"), p.get("company_name")
        out.append(q)
    return out


# ------------------------------------------------------------------ error taxonomy

def error_class(gold, q):
    """Classify a disagreement by its general cause (never by the phrase)."""
    g = gold["label"] == "DEMAND_EVIDENCE"
    role = gold.get("evidence_role") or gold.get("role")
    if g and not q["eligible_for_demand"]:
        d = q["decision"]
        if d in ("AMBIGUOUS", "EXCLUDED_INSUFFICIENT_CONTEXT"):
            if q.get("list_head") is not None or role in ("SKILLS_LIST",):
                return "E6"
            return "E12" if q.get("concept") is None and (q.get("abstention_reason") or "").startswith(("ordinary", "alias", "several")) or "candidate" in (q.get("abstention_reason") or "") else "E3"
        if d == "EXCLUDED_GENERIC_CAPABILITY":
            return "E7"
        if d == "EXCLUDED_BOILERPLATE":
            return "E1"
        if d == "EXCLUDED_ENTITY_NAME":
            return "E4"
        if d == "EXCLUDED_NON_JOB_TEXT":
            return "E8"
        return "E3"
    if (not g) and q["eligible_for_demand"]:
        if gold.get("is_skill_sense") is False or gold.get("skill_sense") is False:
            return "E5"
        if role in ("COMPANY_DESCRIPTION",):
            return "E8"
        if role in ("LEGAL_EEO", "SOCIAL_LINKS", "BENEFITS"):
            return "E1"
        if q.get("intrinsic_type") in ("COMPETENCE", "TRANSVERSAL"):
            return "E2"
        return "E8"
    return None


def prf(rows):
    tp = sum(1 for g, p in rows if g and p)
    fp = sum(1 for g, p in rows if not g and p)
    fn = sum(1 for g, p in rows if g and not p)
    tn = sum(1 for g, p in rows if not g and not p)
    P = tp / (tp + fp) if tp + fp else None
    R = tp / (tp + fn) if tp + fn else None
    F = 2 * P * R / (P + R) if P and R else None
    r3 = lambda x: round(x, 3) if x is not None else None
    return {"n": len(rows), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": r3(P), "recall": r3(R), "f1": r3(F),
            "accuracy": r3((tp + tn) / len(rows)) if rows else None}


def evaluate_set(name, quals_by_mention, v01_by_mention):
    folder, label_file, source = SETS[name]
    items = jl(EVAL / folder / "benchmark.jsonl")
    labels = {x["item_id"]: x for x in jl(EVAL / folder / label_file)}
    rows, rows01, errors, strength = [], [], Counter(), Counter()
    abst = 0
    examples = defaultdict(list)
    for it in items:
        lab = labels.get(it["item_id"])
        q = quals_by_mention.get(it["mention_uid"])
        if not lab or not q:
            continue
        g = lab["label"] == "DEMAND_EVIDENCE"
        rows.append((g, q["eligible_for_demand"]))
        if v01_by_mention.get(it["mention_uid"]) is not None:
            rows01.append((g, v01_by_mention[it["mention_uid"]]["eligible_for_demand"]))
        abst += q["abstained"]
        e = error_class(lab, q)
        if e:
            errors[e] += 1
            if len(examples[e]) < 3 and name != "holdout":
                examples[e].append({"phrase": it["phrase"], "decision": q["decision"], "role": q["sentence_role"]})
        if lab.get("strength"):
            strength[(lab["strength"], q["evidence_strength"])] += 1
    agree = sum(v for (a, b), v in strength.items() if a == b)
    return {"set": name, "label_source": source, "v0.2": prf(rows), "v0.1": prf(rows01),
            "abstention_rate": round(abst / max(1, len(rows)), 3), "error_classes": dict(sorted(errors.items())),
            "error_examples": dict(examples) if name != "holdout" else "withheld (sealed holdout)",
            "strength_agreement": round(agree / max(1, sum(strength.values())), 3) if strength else None,
            "strength_confusion": {f"{a}->{b}": v for (a, b), v in sorted(strength.items())}}


# ------------------------------------------------------------------ synthetic generalization suite

_ESCO = {}


def esco():
    if not _ESCO:
        manifest = json.loads((REPO / "data/metadata/curriculum_sources.json").read_text())
        _, taxonomies = industry_stage.verify_sources(manifest, REPO, ra._Quarantine())
        vocab, _ = industry_stage.load_esco(taxonomies)
        cfg = json.loads((REPO / "backend/app/knowledge_engine/engine_config.json").read_text())
        from app.knowledge_engine.semantic_backend import get_backend
        _ESCO.update(vocab=vocab, cfg=cfg, backend=lambda: get_backend(cfg["semantic_backend"])[0])
    return _ESCO


def run_synthetic(suite):
    e = esco()
    store = e["vocab"]["_store"]["skills"]
    # synthetic evaluation text is treated as source text for the extractor (it is never written to GOLD)
    postings = [{**p, "evidence_status": "EXTRACTED", "synthetic_evaluation_record": True} for p in suite["postings"]]
    topics = []
    for prog, lines in suite["programmes"].items():
        for i, t in enumerate(lines):
            topics.append({"topic_uid": f"topic:{prog}:{i}", "clean_text": t, "course_uid": f"course:{prog}",
                           "unit_label": "u1", "doc_id": prog, "evidence_status": "EXTRACTED",
                           "synthetic_evaluation_record": True})
    ext = industry_stage.extract_and_map(postings, topics, e["vocab"], e["cfg"], e["backend"])
    mentions = ext["posting_mentions"]
    mappings = ext["mappings"]
    topic_doc = {t["topic_uid"]: t["doc_id"] for t in topics}
    broader = {u: lit(s.get("broader")) or [] for u, s in store.items()}
    profiles = {}
    for prog in suite["programmes"]:
        prof = se.curriculum_profile(ext["curriculum_mentions"], topic_doc, {prog}, (), mappings)
        profiles[prog] = (prof, rel.neighbourhood(prof, broader))
    by_posting = defaultdict(list)
    for m in mentions:
        by_posting[m["source_uid"]].append(m)
    # one programme per posting for the qualification fields; programme relevance is evaluated separately
    quals = qualify_all(postings, mentions, mappings, store, set(), set())
    return ext, quals, profiles, store


def evaluate_synthetic(suite, quals, profiles, store, v01_quals=None):
    by = {p["posting_uid"]: p for p in suite["postings"]}
    rows, per_tag, per_disc, errors, examples = [], defaultdict(list), defaultdict(list), Counter(), []
    extraction = []
    strength = Counter()
    seen_dev = {x["normalized_phrase"].lower() for x in jl(EVAL / "skill_qualification_benchmark_v1/benchmark.jsonl")}
    unseen_rows = []
    for c in suite["cases"]:
        text = by[c["posting"]]["clean_description"]
        idx, start = -1, -1
        for _ in range(c["occurrence"]):
            idx = text.lower().find(c["phrase"].lower(), idx + 1)
        start = idx
        span = (start, start + len(c["phrase"]))
        q = next((x for x in quals if x["posting_uid"] == c["posting"] and x["span"][0] <= span[0] < x["span"][1] + 1
                  and x["span"][1] >= span[1] - 1), None)
        extracted = q is not None
        if c["skill_sense"]:
            extraction.append(extracted)
        gold = c["label"] == "DEMAND_EVIDENCE"
        pred = bool(q and q["eligible_for_demand"])
        rows.append((gold, pred))
        for t in c["tags"]:
            per_tag[t].append((gold, pred))
        per_disc[c["discipline"]].append((gold, pred))
        if c["phrase"].lower() not in seen_dev:
            unseen_rows.append((gold, pred))
        if q is not None:
            strength[(c["strength"], q["evidence_strength"])] += 1
        if gold != pred:
            e = ("E6" if "list" in " ".join(c["tags"]) else "E7" if "verb_form" in c["tags"] else "E11") if q is None \
                else error_class({"label": c["label"], "role": c["role"], "skill_sense": c["skill_sense"]}, q)
            errors[e] += 1
            examples.append({"case": c["id"], "phrase": c["phrase"], "expected": c["label"], "tags": c["tags"],
                             "decision": q["decision"] if q else "NOT_EXTRACTED",
                             "role": q["sentence_role"] if q else None, "reason": q["reason"] if q else None,
                             "error_class": e})
    # programme relevance
    by_label = {}
    for u, s in store.items():
        by_label.setdefault((s.get("pref_label") or "").lower(), u)
    rel_rows, rel_errors = [], []
    for r in suite["programme_relevance"]:
        uri = by_label.get(r["concept_label"].lower())
        prof, near = profiles[r["programme"]]
        got = uri in prof if uri else False
        rel_rows.append((r["expected_in_programme"], got))
        if got != r["expected_in_programme"]:
            rel_errors.append({"case": r["id"], "concept": r["concept_label"], "programme": r["programme"],
                               "expected": r["expected_in_programme"], "got": got,
                               "error_class": "E10" if uri else "E11"})
    disc_ok = sum(1 for g, p in rel_rows if g == p)
    agree = sum(v for (a, b), v in strength.items() if a == b)
    tag_groups = {
        "generic_action_rejection": ["generic_action"],
        "boilerplate_rejection": ["company_description", "legal", "boilerplate", "technical_looking_boilerplate"],
        "list_extraction": ["list", "list_after_colon", "required_colon_list"],
        "verb_form": ["verb_form"],
        "adversarial": ["adversarial"],
        "ambiguous_abbreviation": ["ambiguous_abbreviation"],
        "ordinary_word_in_technical_context": ["ordinary_word_in_technical_context"],
    }
    styles = [t for t in per_tag if t.endswith("_style") or t.endswith("_section")]
    return {
        "label_source": "AUTHOR_LABELLED (synthetic, written before v0.2)",
        "cases": len(rows), "qualification": prf(rows),
        "extraction_recall_of_skill_phrases": round(sum(extraction) / max(1, len(extraction)), 3),
        "by_capability": {k: prf([x for t in v for x in per_tag.get(t, [])]) for k, v in tag_groups.items()},
        "unseen_phrases": prf(unseen_rows),
        "by_discipline": {k: prf(v) for k, v in sorted(per_disc.items())},
        "unseen_disciplines": prf([x for d, v in per_disc.items() if d != "computing" for x in v]),
        "writing_styles": prf([x for t in styles for x in per_tag[t]]),
        "per_style": {t: prf(per_tag[t]) for t in sorted(styles)},
        "programme_relevance_accuracy": round(disc_ok / max(1, len(rel_rows)), 3),
        "programme_relevance_cases": len(rel_rows), "programme_relevance_errors": rel_errors,
        "strength_agreement": round(agree / max(1, sum(strength.values())), 3),
        "error_classes": dict(sorted(errors.items())), "disagreements": examples,
    }


# ------------------------------------------------------------------ release run (498 postings)

def release(run_id):
    d = ra.load(run_id)
    a = ra.audit(d)
    store = d["store"]["skills"]
    maps = {}
    for line in (d["run"] / "industry/esco_mappings.jsonl").read_text().splitlines():
        if line.strip():
            m = json.loads(line)
            maps[m["normalized_label"]] = m
    programme = {doc for doc, r in d["roles"].items() if r in ("TARGET", "PREVIOUS_VERSION", "REFERENCE")}
    coverage = [c for c in d["coverage"] if c["doc_id"] in programme]
    cur_maps = dict(maps)
    profile = se.curriculum_profile(d["curriculum_mentions"], d["topic_doc"], programme, coverage, cur_maps)
    broader = {u: lit(s.get("broader")) or [] for u, s in store.items()}
    near = rel.neighbourhood(profile, broader)
    by = {p["posting_uid"]: p for p in d["postings"]}
    jobs = [m for m in d["skill_mentions"] if m.get("source_type") == "job_posting" and m["source_uid"] in by]
    quals = qualify_all(d["postings"], jobs, maps, store, profile, near, a["boiler"])
    v01 = {}
    import skill_qualification_audit as sqa
    for q in sqa.qualify_run(d, a):
        v01[q["mention_uid"]] = q
    return d, a, quals, v01, profile, near


def demand_table(d, a, quals):
    company = {p["posting_uid"]: p.get("company_key") for p in d["postings"]}
    state = {u: j["relevance"] for u, j in a["jobs"].items()}
    reuse = {u: s.get("reuse_level") for u, s in d["store"]["skills"].items()}
    by_skill = defaultdict(list)
    for q in quals:
        by_skill[q["evidence_key"]].append(q)
    rows = {}
    for k in set(by_skill) | set(d["demand"]):
        qs = by_skill.get(k, [])
        cur = set(lit((d["demand"].get(k) or {}).get("posting_uids")) or [])
        ev = {q["posting_uid"] for q in qs if q["eligible_for_demand"]}
        new = {u for u in ev if u in a["eligible"]}
        strong = {q["posting_uid"] for q in qs if q["eligible_for_demand"] and q["evidence_strength"] in ("STRONG", "MEDIUM")
                  and q["posting_uid"] in a["eligible"]}
        pr = se.skill_level_relevance([q["programme_relevance"] for q in qs],
                                      rel.skill_relevance(k, set(), reuse, ev, state))
        decisions = Counter(q["decision"] for q in qs)
        top = max((x for x in decisions if x in se.DEMAND_ELIGIBLE), key=lambda x: (decisions[x], x), default=None) \
            or (max(decisions, key=lambda x: (decisions[x], x)) if decisions else None)
        label = ((d["demand"].get(k) or {}).get("skill_label") or (d["store"]["skills"].get(k) or {}).get("pref_label")
                 or (qs[0]["normalized_phrase"] if qs else k))
        gap_eligible = se.skill_gap_eligible(top, pr, qs)
        normalized = any(q["normalization_state"] == "CONFIRMED" for q in qs)
        rows[k] = {"skill_key": k, "skill_label": label, "decision": top, "decisions": dict(decisions),
                   "normalized_concept": normalized,
                   "programme_relevance": pr, "gap_eligible": gap_eligible, "in_release_demand": k in d["demand"],
                   "release": {"postings": len(cur), "support_state": (d["demand"].get(k) or {}).get("support_state", "NOT_IN_DEMAND")},
                   "new": {"postings": len(new), "companies": len({company[u] for u in new}),
                           "support_state": industry.support_state(len(new), len({company[u] for u in new}), d["cfg"])},
                   "strong_or_medium_postings": len(strong),
                   "release_gap": (d["gaps"].get(k) or {}).get("classification")}
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=json.loads((REPO / "data/gold/knowledge/latest_run.json").read_text())["run_id"])
    ap.add_argument("--final-holdout", action="store_true")
    args = ap.parse_args()
    out = REPO / "data/experiments/skill_evidence" / args.run
    out.mkdir(parents=True, exist_ok=True)
    d, a, quals, v01, profile, near = release(args.run)
    qm = {q["mention_uid"]: q for q in quals}
    with open(out / "mention_evidence.jsonl", "w") as fh:
        for q in quals:
            fh.write(json.dumps(q, sort_keys=True) + "\n")
    skills = demand_table(d, a, quals)
    with open(out / "skill_evidence.jsonl", "w") as fh:
        for k in sorted(skills):
            fh.write(json.dumps(skills[k], sort_keys=True) + "\n")
    names = ["development", "validation"] + (["holdout"] if args.final_holdout else [])
    evals = {n: evaluate_set(n, qm, v01) for n in names}
    suite = json.loads((EVAL / "skill_generalization_suite_v1/suite.json").read_text())
    _, squals, profiles, store = run_synthetic(suite)
    synth = evaluate_synthetic(suite, squals, profiles, store)
    with open(out / "synthetic_evidence.jsonl", "w") as fh:
        for q in squals:
            fh.write(json.dumps(q, sort_keys=True) + "\n")
    dem = [r for r in skills.values() if r["in_release_demand"]]
    rec_rows = []
    for rec in d["recommendations"]:
        r = skills.get(rec["skill_key"])
        if r:
            rec_rows.append({"skill": r["skill_label"], "action": rec.get("action_type"), "decision": r["decision"],
                             "programme_relevance": r["programme_relevance"], "new_support": r["new"]["support_state"],
                             "still_a_basis": r["gap_eligible"] and r["new"]["support_state"] in ("SUPPORTED", "HIGH_SUPPORT")})
    release_summary = {
        "mentions": len(quals), "decisions": dict(Counter(q["decision"] for q in quals)),
        "evidence_strength": dict(Counter(q["evidence_strength"] for q in quals)),
        "sentence_roles": dict(Counter(q["sentence_role"] for q in quals)),
        "abstention_rate": round(sum(q["abstained"] for q in quals) / len(quals), 3),
        "abstention_reasons": dict(Counter((q["abstention_reason"] or "").split(";")[0] for q in quals if q["abstained"])),
        "abstentions_resolvable_with": dict(Counter(q["resolvable_with"] or "-" for q in quals if q["abstained"])),
        "programme_profile_skills": len(profile),
        "release_demand_skills": len(dem),
        "release_skill_decisions": dict(Counter(r["decision"] or "-" for r in dem)),
        "release_skill_programme_relevance": dict(Counter(r["programme_relevance"] for r in dem)),
        "support_release": dict(Counter(r["release"]["support_state"] for r in dem)),
        "support_new": dict(Counter(r["new"]["support_state"] for r in dem)),
        "new_supported_concepts": sorted((r["skill_label"], r["new"]["postings"]) for r in skills.values()
                                         if not r["in_release_demand"] and r["normalized_concept"]
                                         and r["new"]["support_state"] in ("SUPPORTED", "HIGH_SUPPORT")),
        "new_supported_unnormalized_wordings": len([r for r in skills.values() if not r["in_release_demand"]
                                                    and not r["normalized_concept"]
                                                    and r["new"]["support_state"] in ("SUPPORTED", "HIGH_SUPPORT")]),
        "gap_eligible_skills": sorted(r["skill_label"] for r in skills.values() if r["gap_eligible"]),
        "leaving_supported": sorted(r["skill_label"] for r in dem if r["release"]["support_state"] in ("SUPPORTED", "HIGH_SUPPORT")
                                    and r["new"]["support_state"] not in ("SUPPORTED", "HIGH_SUPPORT")),
        "release_gaps_no_longer_candidates": sorted((r["skill_label"], r["release_gap"], r["decision"], r["programme_relevance"])
                                                    for r in dem if r["release_gap"] in ("MISSING", "PARTIAL") and not r["gap_eligible"]),
        "recommendations": rec_rows,
    }
    scorecard = {"method": se.METHOD, "run_id": args.run, "evaluation_sets": evals, "synthetic": synth,
                 "release": release_summary, "error_class_names": ERROR_CLASSES,
                 "human_labels": "none yet: no evaluation here is independently human-validated"}
    (out / "scorecard.json").write_text(json.dumps(scorecard, indent=2, sort_keys=True, default=str))
    show = {n: {"v0.2": e["v0.2"], "v0.1": e["v0.1"], "abstention": e["abstention_rate"], "errors": e["error_classes"],
                "strength_agreement": e["strength_agreement"]} for n, e in evals.items()}
    print(json.dumps(show, indent=1))
    print(json.dumps({k: synth[k] for k in ("qualification", "extraction_recall_of_skill_phrases", "unseen_phrases",
                                             "unseen_disciplines", "writing_styles", "programme_relevance_accuracy",
                                             "strength_agreement", "error_classes")}, indent=1))
    print("written", out)


if __name__ == "__main__":
    main()
