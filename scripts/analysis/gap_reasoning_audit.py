"""Phases 4-6: curriculum understanding, skill intelligence stages and gap reasoning over a release run
(EXPERIMENTAL; writes only to data/experiments/gap_reasoning/<run>/; the release, the API and the screens are
unchanged).

    python3 scripts/analysis/gap_reasoning_audit.py

Inputs are declared in INPUT_CONTRACT and every one is checked BEFORE any work (preflight), each with its class:
RELEASE (protected GOLD, read only), SOURCE (raw documents, manifest, ESCO), WORKING_TREE (SILVER and job SILVER
written by the pipeline run; never packaged), REGENERABLE_CACHE (BRONZE page text; never packaged, see below),
EXPERIMENT (the Phase 3C outputs of the same run, which must be the validated baseline: their scorecard hash is
checked) and EVALUATION / CONFIG. A path outside the contract cannot be opened (InputContractError).

BRONZE page text is a cache keyed by (source sha256, parser fingerprint) and is excluded from every package
(scripts/audit/package_integrity.py). When a working tree lacks it, the audit rebuilds it with the pipeline's own
function (pipeline.bronze_pages) ONLY if the raw source is present with the recorded sha256 and the installed parser
fingerprint equals the run's recorded one; otherwise it stops and says why. Whatever its origin, the page text must
rebuild SILVER records identical in content to data/silver and courses identical to the release GOLD, and the run's
curriculum mentions must be reproduced exactly; the page-text content hash of every document is written to the
scorecard (it is identical on every machine; the cache timestamps are not part of it). Where each cache came from
(present or rebuilt) is machine-local and goes to provenance.json, not to the scorecard. Curriculum-side mentions are extracted afresh with the release extractor over syllabus topics, course
titles and outcomes of every document, peers included; the run's own mappings and core-topic mentions are checked to
be reproduced exactly before anything is reported.

Outputs:
  curriculum_profiles.json   CurriculumProfile per document (level, scope, course kind / status / pairing)
  skill_coverage.jsonl       coverage record per (document, skill) with the evidence hierarchy
  skill_stages.jsonl         skill intelligence stage per skill (Phase 5)
  gap_states.jsonl           gap state per skill against the TARGET curriculum (Phase 6)
  synthetic_results.json     the cross-discipline synthetic suite (AUTHOR_LABELLED)
  scorecard.json             counts, release comparison with gap v2, regression checks, input content hashes
  provenance.json            machine-local: which caches were present and which were rebuilt
"""
from __future__ import annotations

import argparse
import fnmatch
import glob
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts/analysis"))

from app.knowledge_engine import curriculum_understanding as cu  # noqa: E402
from app.knowledge_engine import gap_reasoning as gr  # noqa: E402
from app.knowledge_engine import industry_stage  # noqa: E402
from app.knowledge_engine import skill_intelligence as si  # noqa: E402

# the Phase 3C outputs Phases 4-6 build on (validated on the owner's Mac, 2026-10-08)
BASELINE_SCORECARD = {"c066b227857f9eaf": "6ea0f53be1b2cba98156d50179f7e26855e2556f06ec17ea074d26d32d1f0823"}
SUITE = REPO / "data/evaluation/gap_reasoning_suite_v1/suite.json"
CONVENTION_KEY = REPO / "data/evaluation/course_status_convention_key_v1.json"

# ------------------------------------------------------------------ input contract

INPUT_CONTRACT = [   # (pattern relative to the repository, class); {run} = the run id
    ("data/gold/knowledge/{run}/*", "RELEASE"),
    ("data/gold/knowledge/latest_run.json", "RELEASE"),
    ("data/metadata/curriculum_sources.json", "SOURCE"),
    ("data/raw/*", "SOURCE"),
    ("data/silver/curricula/*", "WORKING_TREE"),
    ("data/silver/jobs/*", "WORKING_TREE"),
    ("data/bronze/curricula/*/pages.*.json", "REGENERABLE_CACHE"),
    ("data/experiments/skill_evidence/{run}/*", "EXPERIMENT"),
    ("data/evaluation/gap_reasoning_suite_v1/*", "EVALUATION"),
    ("data/evaluation/course_status_convention_key_v1.json", "EVALUATION"),
    ("backend/app/knowledge_engine/engine_config.json", "CONFIG"),
]
NOT_PACKAGED = ("WORKING_TREE", "REGENERABLE_CACHE")
# SILVER files are keyed by (document, source sha256), not by run: every pipeline run that processes a document
# rewrites them, and the pipeline stamps each topic with the role the document has IN THAT RUN
# (pipeline.run: `t["role"] = doc["role"]`). A later run in which the document has another role (e.g. a trial upload
# where the target becomes the previous version) therefore leaves SILVER with that run's role. Such run-assigned
# fields are compared against the run being audited, never against the SILVER file.
RUN_ASSIGNED_SILVER_FIELDS = {"topics": ("role",)}
_ACCESS = []        # (relative path, class, how) for provenance.json


class InputContractError(SystemExit):
    """An input the audit needs is missing, undeclared, or cannot be reproduced; never a bare FileNotFoundError."""


def contract_class(path, run_id):
    rel = Path(path).resolve().relative_to(REPO).as_posix() if Path(path).is_absolute() else str(path)
    for pattern, cls in INPUT_CONTRACT:
        if fnmatch.fnmatch(rel, pattern.replace("{run}", run_id)):
            return rel, cls
    raise InputContractError(f"undeclared input {rel}: every file the audit reads must be listed in INPUT_CONTRACT")


def need(path, run_id, how="read"):
    """The one way the audit opens an input: declared, present, recorded."""
    rel, cls = contract_class(path, run_id)
    if not Path(path).exists():
        remedy = {"RELEASE": "the protected release is incomplete in this working tree; restore it from the release "
                             "package (never regenerate it)",
                  "WORKING_TREE": "run the pipeline for this run in this working tree "
                                  "(python -m app.knowledge_engine.pipeline) so SILVER exists",
                  "EXPERIMENT": "run scripts/analysis/skill_evidence_audit.py --final-holdout first",
                  "SOURCE": "the raw source is not in this working tree; add it (peer PDFs are never packaged)"}
        raise InputContractError(f"missing {cls} input {rel}: " + remedy.get(cls, "restore it"))
    _ACCESS.append((rel, cls, how))
    return Path(path)


def page_text(doc, fingerprint, run_id):
    """BRONZE page text of one document: the cache when present; otherwise rebuilt with the pipeline's own function,
    only when the source and the parser are exactly the run's."""
    cache = REPO / f"data/bronze/curricula/{doc['sha256'][:16]}/pages.{fingerprint}.json"
    contract_class(cache, run_id)
    if cache.exists():
        _ACCESS.append((str(cache.relative_to(REPO)), "REGENERABLE_CACHE", "present"))
        return json.loads(cache.read_text())
    src = need(REPO / doc["path"], run_id, "source for a cache rebuild")
    if sha(src) != doc["sha256"]:
        raise InputContractError(f"{doc['doc_id']}: {doc['path']} does not have the run's sha256; the page text cannot "
                                 "be rebuilt for this run")
    from app.knowledge_engine import pipeline
    installed = pipeline.parser_fingerprint()
    if installed != fingerprint:
        raise InputContractError(f"{doc['doc_id']}: BRONZE cache pages.{fingerprint}.json is absent and the installed "
                                 f"parser fingerprint is {installed}: rebuilding would not reproduce the run")
    data, _ = pipeline.bronze_pages(doc, fingerprint)
    _ACCESS.append((str(cache.relative_to(REPO)), "REGENERABLE_CACHE", "rebuilt from source"))
    return data


def page_text_sha(bronze):
    """Machine-independent content hash of page text (pages, extraction methods, image pages): no timestamp."""
    return hashlib.sha256(json.dumps({k: bronze[k] for k in ("pages", "methods", "image_pages", "raw_alpha_per_page")},
                                     sort_keys=True).encode()).hexdigest()


def jl(p):
    with open(p, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ------------------------------------------------------------------ loading

def load(run_id):
    run = REPO / "data/gold/knowledge" / run_id
    r = lambda rel: need(run / rel, run_id)
    report = json.loads(r("run_report.json").read_text())
    docs = report["documents"]
    gold_courses = jl(r("courses.jsonl"))
    silver = {d["doc_id"]: rebuild_silver(d, report["parser_fingerprint"], run_id, gold_courses) for d in docs}
    se_dir = REPO / "data/experiments/skill_evidence" / run_id
    return {"run": run, "run_id": run_id, "report": report, "docs": docs, "silver": silver,
            "prereq_edges": [e for e in jl(r("concept_edges.jsonl")) if e.get("relationship") == "PREREQUISITE_OF"],
            "release_mappings": {m["normalized_label"]: m for m in jl(r("industry/esco_mappings.jsonl"))},
            "release_curriculum_mentions": jl(r("industry/curriculum_skill_mentions.jsonl")),
            "release_coverage": jl(r("intelligence/coverage_depth.jsonl")),
            "gaps_v2": {g["skill_key"]: g for g in jl(r("intelligence/skill_gaps_v2.jsonl"))},
            "recommendations": jl(r("industry/recommendations.jsonl")),
            "trends": {t["skill_key"]: t for t in jl(r("industry_v2/skill_trends.jsonl"))},
            "se_dir": se_dir,
            "skill_rows": {x["skill_key"]: x for x in jl(need(se_dir / "skill_evidence.jsonl", run_id))},
            "mention_rows": jl(need(se_dir / "mention_evidence.jsonl", run_id))}


def rebuild_silver(doc, fingerprint, run_id, gold_courses=()):
    """SILVER records of one document in the pipeline's own order (record order is part of the extractor's sense
    context), rebuilt from the BRONZE page text with the pipeline's functions. The rebuilt records must equal the
    SILVER files in CONTENT (except the run-assigned fields, which come from this run's report), and the courses must
    equal the release GOLD courses on every shared field."""
    from app.knowledge_engine.contracts import enforce
    from app.knowledge_engine.quarantine import Quarantine
    from app.knowledge_engine.silver import build_silver
    from app.pipelines.preprocessing.curriculum_structuring import structure_curriculum_pages
    cfg = json.loads(need(REPO / "backend/app/knowledge_engine/engine_config.json", run_id).read_text())
    bronze = page_text(doc, fingerprint, run_id)
    q = Quarantine()
    rec = build_silver({**doc, "_page_methods": {i + 1: m for i, m in enumerate(bronze["methods"])}},
                       structure_curriculum_pages(bronze["pages"]), q, cfg["topics"])
    for kind, contract in (("courses", "course"), ("units", "unit"), ("topics", "topic")):
        rec[kind] = enforce(rec[kind], contract, q, "silver.contract")
    for t in rec["topics"]:
        t["role"] = doc["role"]
    canon = lambda x, keys: json.dumps({k: x.get(k) for k in sorted(keys)}, sort_keys=True)
    for kind, key in (("courses", "course_uid"), ("topics", "topic_uid"), ("outcomes", "outcome_uid")):
        files = sorted(glob.glob(str(REPO / f"data/silver/curricula/{doc['doc_id']}/*/{kind}.jsonl")))
        if not files:
            need(REPO / f"data/silver/curricula/{doc['doc_id']}/{doc['sha256'][:16]}/{kind}.jsonl", run_id)
        shipped = {x[key]: x for f in files for x in jl(need(f, run_id))}
        fields = lambda x: set(x) - set(RUN_ASSIGNED_SILVER_FIELDS.get(kind, ()))  # noqa: B023 -- called within this iteration
        if {x[key] for x in rec[kind]} != set(shipped) or any(
                canon(x, fields(shipped[x[key]])) != canon(shipped[x[key]], fields(shipped[x[key]])) for x in rec[kind]):
            raise InputContractError(f"{doc['doc_id']}: SILVER {kind} rebuilt from the page text differ from "
                                     "data/silver; the page text does not reproduce this run")
    gold = {c["course_uid"]: c for c in gold_courses if c.get("doc_id") == doc["doc_id"]}
    for c in rec["courses"]:
        if c["course_uid"] in gold and canon(c, set(c) & set(gold[c["course_uid"]])) != \
                canon(gold[c["course_uid"]], set(c) & set(gold[c["course_uid"]])):
            raise InputContractError(f"{doc['doc_id']}: course {c['course_uid']} rebuilt from the page text differs "
                                     "from the release GOLD")
    rec["pages"] = bronze["pages"]
    rec["page_text_sha256"] = page_text_sha(bronze)
    return rec


def check_baseline(d):
    f = need(d["se_dir"] / "scorecard.json", d["run_id"])
    got, want = sha(f), BASELINE_SCORECARD.get(d["run_id"])
    if want and got != want:
        raise SystemExit(f"Phase 3C scorecard {got[:12]} is not the validated baseline {want[:12]}; re-run "
                         "skill_evidence_audit.py --final-holdout on unchanged code")
    return {"scorecard_sha256": got, "validated_baseline": bool(want and got == want)}


def esco(run_id):
    manifest = json.loads(need(REPO / "data/metadata/curriculum_sources.json", run_id).read_text())
    for t in manifest.get("taxonomy_sources", []):
        need(REPO / t["path"], run_id)
    import relevance_audit as ra
    _, taxonomies = industry_stage.verify_sources(manifest, REPO, ra._Quarantine())
    vocab, _ = industry_stage.load_esco(taxonomies)
    cfg = json.loads(need(REPO / "backend/app/knowledge_engine/engine_config.json", run_id).read_text())
    from app.knowledge_engine.semantic_backend import get_backend
    return vocab, cfg, (lambda: get_backend(cfg["semantic_backend"])[0])


# ------------------------------------------------------------------ curriculum-side extraction

def curriculum_records(d):
    """Syllabus topics (noise-free) of every document, plus course titles and outcomes as their own records."""
    topics, titles, outcomes, outcome_course = [], [], [], {}
    for doc_id, s in d["silver"].items():
        topics += [t for t in s["topics"] if t["noise_label"] == "TOPIC"]
        for c in s["courses"]:
            titles.append({"topic_uid": c["course_uid"], "clean_text": c.get("title") or "", "course_uid": c["course_uid"],
                           "unit_label": "__course_title__", "doc_id": doc_id,
                           "evidence_status": c.get("evidence_status")})
        known = {c["course_uid"] for c in s["courses"]}
        for o in s["outcomes"]:
            if o["course_uid"] in known and (o.get("text") or "").strip():
                outcomes.append({"topic_uid": o["outcome_uid"], "clean_text": o["text"], "course_uid": o["course_uid"],
                                 "unit_label": "__course_outcomes__", "doc_id": doc_id,
                                 "evidence_status": o.get("evidence_status")})
                outcome_course[o["outcome_uid"]] = o["course_uid"]
    return topics, titles, outcomes, outcome_course


def extract(d, vocab, cfg, backend):
    """Core pass: the release extraction exactly (postings + the core documents' topics), which must reproduce the
    run. Extra pass: course titles, outcomes and peer topics, mapped with the core mappings for every surface the
    core pass knows (so nothing extra can change the run's mappings) and with their own mapping otherwise; senses
    are checked with the same rule and context."""
    from app.knowledge_engine import industry as ind
    from app.knowledge_engine.silver import uid
    from app.pipelines.preprocessing.skill_extraction import IndexedVocabulary
    import relevance_audit as ra
    topics, titles, outcomes, outcome_course = curriculum_records(d)
    core_docs = {doc["doc_id"] for doc in d["docs"] if doc["role"] != "PEER"}
    core_topics = [t for t in topics if t["doc_id"] in core_docs]
    extra = [t for t in topics if t["doc_id"] not in core_docs] + titles + outcomes
    for f in glob.glob(str(REPO / "data/silver/jobs/*/postings.jsonl")) or [str(REPO / "data/silver/jobs/-/postings.jsonl")]:
        need(f, d["run_id"])
    postings = ra.load(d["run_id"])["postings"]
    ex = industry_stage.extract_and_map(postings, core_topics, vocab, cfg, backend)
    terms, label_index = ind.build_vocabulary(vocab)
    index = IndexedVocabulary(terms)
    mentions = ind.extract(extra, "clean_text", "topic_uid", index, "curriculum_topic")
    for m in mentions:
        m["mention_uid"] = uid("mention", m["source_type"], m["source_uid"], m["span"][0], m["normalized_text"])
    new = ind.map_skills([m for m in mentions if m["normalized_text"] not in ex["mappings"]], vocab, label_index,
                         backend, cfg["industry"])
    mappings = {**new, **ex["mappings"]}
    labels_by_uri = ind.concept_labels(vocab)
    unit_text, by_source = defaultdict(list), defaultdict(list)
    for t in extra:
        unit_text[(t["course_uid"], t.get("unit_label"))].append(t["clean_text"])
    unit_of = {t["topic_uid"]: (t["course_uid"], t.get("unit_label")) for t in extra}
    for m in mentions:
        mp = mappings[m["normalized_text"]]
        m.update(skill_key=mp["skill_key"], esco_status=mp["status"])
        by_source[m["source_uid"]].append(m)
    for m in mentions:
        state, relationship, evidence = ind.sense_check(m, mappings[m["normalized_text"]],
                                                        "\n".join(unit_text[unit_of[m["source_uid"]]]), labels_by_uri,
                                                        by_source[m["source_uid"]],
                                                        cfg["industry"]["alias_orthographic_min_ratio"])
        m.update(sense_state=state, taxonomy_relationship=relationship, sense_evidence=evidence,
                 sense_established=state in ind.SENSE_ESTABLISHED)
    kind_of = {**{t["topic_uid"]: "topic" for t in topics}, **{t["topic_uid"]: "title" for t in titles},
               **{t["topic_uid"]: "outcome" for t in outcomes}}
    by_kind = defaultdict(list)
    for m in ex["curriculum_mentions"] + mentions:
        by_kind[kind_of[m["source_uid"]]].append(m)
    ex = {**ex, "mappings": mappings, "core_mappings": ex["mappings"], "extra_mentions": len(mentions)}
    return ex, by_kind, outcome_course, topics


def regression(d, ex, by_kind):
    """The run's own mappings and core-topic mentions must be reproduced exactly."""
    core_docs = {doc["doc_id"] for doc in d["docs"] if doc["role"] != "PEER"}
    topic_doc = {t["topic_uid"]: t["doc_id"] for s in d["silver"].values() for t in s["topics"]}
    fields = ("mention_uid", "skill_key", "sense_state", "span", "normalized_text")
    mine = sorted(tuple(json.dumps(m[f]) for f in fields) for m in by_kind["topic"]
                  if topic_doc.get(m["source_uid"]) in core_docs)
    rel = sorted(tuple(json.dumps(m[f]) for f in fields) for m in d["release_curriculum_mentions"])
    maps = ex["core_mappings"]
    changed = [s for s, m in d["release_mappings"].items()
               if s in maps and (maps[s]["skill_key"], maps[s]["status"]) != (m["skill_key"], m["status"])]
    return {"core_topic_mentions_identical": mine == rel, "core_topic_mentions": len(mine),
            "release_curriculum_mentions": len(rel), "release_mappings_changed": len(changed),
            "release_mappings_missing": sum(1 for s in d["release_mappings"] if s not in maps),
            "extra_mentions_titles_outcomes_peers": ex["extra_mentions"]}


# ------------------------------------------------------------------ phases 4-6 over the release

def run(d, vocab, cfg, backend):
    store = vocab["_store"]["skills"]
    ex, by_kind, outcome_course, topics = extract(d, vocab, cfg, backend)
    reg = regression(d, ex, by_kind)
    if not (reg["core_topic_mentions_identical"] and reg["release_mappings_changed"] == 0):
        raise SystemExit(f"the release extraction is not reproduced: {reg}")
    topics_by_uid = {t["topic_uid"]: t for t in topics}
    courses = [c for s in d["silver"].values() for c in s["courses"]]
    ccfg = cfg["intelligence"]["coverage"]
    profiles, coverage, related = {}, {}, {}
    for doc in d["docs"]:
        p = cu.build_profile(doc, d["docs"], courses, d["silver"][doc["doc_id"]]["pages"])
        profiles[doc["doc_id"]] = p
        coverage[doc["doc_id"]] = cu.skill_coverage(p, topics_by_uid, by_kind["topic"], by_kind["title"],
                                                    by_kind["outcome"], outcome_course, ex["mappings"],
                                                    d["prereq_edges"], ccfg)
        related[doc["doc_id"]] = cu.taxonomy_related(coverage[doc["doc_id"]], store)
    target = next(doc for doc in d["docs"] if doc["role"] == "TARGET")
    tid = target["doc_id"]
    # skills with no evidence in the target still need a record (ABSENT), and taxonomy context
    keys = set(d["skill_rows"])
    for k in keys - set(coverage[tid]):
        coverage[tid][k] = cu.absent_record(k, tid)
    related[tid] = cu.taxonomy_related(coverage[tid], store)
    occ = defaultdict(list)
    for m in d["mention_rows"]:
        occ[m["evidence_key"]].append(m)
    stages = {k: si.stage(r, occ.get(k, [])) for k, r in d["skill_rows"].items()}
    others = {doc["doc_id"]: (doc["role"], coverage[doc["doc_id"]]) for doc in d["docs"] if doc["doc_id"] != tid}
    trend = {k: (t.get("trend_state") if t.get("trend_state") not in (None, "INSUFFICIENT_DATA") else "INSUFFICIENT_EVIDENCE")
             for k, t in d["trends"].items()}
    # a job-side wording that stayed unconfirmed may be a word the syllabus genre resolves (a one-word subject name):
    # its coverage is read under the curriculum's concept and the link is stated; the skill itself stays ineligible
    topic_doc = {t["topic_uid"]: t["doc_id"] for t in topics}
    resolves = defaultdict(set)
    for m in by_kind["topic"]:
        if topic_doc.get(m["source_uid"]) == tid:
            k = cu.syllabus_concept(m, ex["mappings"])
            if k and k.startswith("http"):
                resolves["surface:" + m["normalized_text"]].add(k)
    gaps = {}
    for k in sorted(keys):
        cov, via = coverage[tid].get(k), None
        if k.startswith("surface:") and cov["coverage_level"] == "ABSENT" and len(resolves.get(k, ())) == 1:
            via = next(iter(resolves[k]))
            cov = coverage[tid].get(via, cov)
        gaps[k] = gr.reason(stages[k], cov, profiles[tid]["scope"], target.get("discipline"),
                            trend.get(k, "INSUFFICIENT_EVIDENCE"), related[tid].get(k), others)
        if via:
            gaps[k]["coverage_read_via"] = {"concept": via, "label": store.get(via, {}).get("pref_label"),
                                            "why": "the curriculum's own wording resolves to this concept"}
    release_keys = {m["skill_key"] for m in by_kind["topic"] if topic_doc.get(m["source_uid"]) == tid
                    and m.get("sense_established")}
    return {"profiles": profiles, "coverage": coverage, "related": related, "stages": stages, "gaps": gaps,
            "target": tid, "regression": reg, "store": store, "release_keys_in_target": release_keys}


def compare_release(d, out):
    """Gap v2 (authoritative) -> gap reasoning v0.1, every changed skill with both reasons."""
    tid = out["target"]
    rows, trans = [], Counter()
    for k, g2 in sorted(d["gaps_v2"].items()):
        new = out["gaps"].get(k)
        state = new["gap_state"] if new else "NOT_IN_PHASE_3C_EVIDENCE"
        trans[(g2["classification_v2"], state)] += 1
        confirmed = g2["classification_v2"] in ("PARTIAL", "MISSING") and g2.get("support_state") in ("SUPPORTED", "HIGH_SUPPORT") \
            and g2.get("evidence_status") != "REVIEW_REQUIRED"
        rows.append({"skill_key": k, "skill_label": g2.get("skill_label"), "v2": g2["classification_v2"],
                     "v2_confirmed_gap": confirmed, "v2_reason": g2.get("reason_v2"), "new": state,
                     "new_reasons": (new or {}).get("reasons"), "coverage_level": (new or {}).get("coverage_level"),
                     "access": (new or {}).get("access")})
    release_cov = {r["skill_key"]: r["coverage_level"] for r in d["release_coverage"] if r["role"] == "TARGET"}
    agree, differ = 0, []
    for k, lvl in release_cov.items():
        mine = out["coverage"][tid].get(k)
        mlvl = mine["coverage_level"] if mine else "ABSENT"
        topic_only = mlvl if mlvl != "UNCERTAIN" else "ABSENT"
        if topic_only == lvl or (lvl == "MENTION" and mlvl == "UNCERTAIN"):
            agree += 1
        else:
            differ.append({"skill_key": k, "release": lvl, "phase4": mlvl,
                           "evidence_types": (mine or {}).get("evidence_types"),
                           "cause": ("the release counted only mentions mapped to this key; Phase 4 also resolves "
                                     "syllabus wordings to it (the Phase 3C syllabus-genre rule)"
                                     if k not in out["release_keys_in_target"] or mlvl != "UNCERTAIN" else
                                     "course title / outcome evidence (UNCERTAIN)")})
    recs = []
    for r in d["recommendations"]:
        g = out["gaps"].get(r["skill_key"])
        recs.append({"skill": r.get("skill_label"), "action": r.get("action_type"),
                     "gap_state": g["gap_state"] if g else None, "access": g["access"] if g else None,
                     "still_a_gap": bool(g and g["gap_state"] in gr.GAP_STATES)})
    return {"transitions_v2_to_new": {f"{a} -> {b}": n for (a, b), n in sorted(trans.items())},
            "confirmed_v2_gaps": [r for r in rows if r["v2_confirmed_gap"]],
            "changed": [r for r in rows if r["v2"] != gr.TO_V2.get(r["new"], r["new"])],
            "coverage_level_agreement_with_release": {"skills": len(release_cov), "agree": agree,
                                                      "differ": differ},
            "recommendations": recs}


def status_check(profiles, run_id):
    """Course status read from layout vs the institutions' own code conventions (evaluation key; never read by the
    reader). Decided = COMPULSORY / ELECTIVE_OPTION; UNKNOWN and CONFLICTING are abstentions."""
    import re
    key = json.loads(need(CONVENTION_KEY, run_id).read_text())
    out = {}
    for doc_id, patterns in key["documents"].items():
        if doc_id not in profiles:
            continue
        c, wrong = Counter(), []
        for x in profiles[doc_id]["courses"].values():
            exp = next((st for pat, st in patterns if re.match(pat, x["course_code"] or "")), None)
            if exp is None:
                c["not_scored"] += 1
            elif x["status"] in ("UNKNOWN", "CONFLICTING"):
                c["abstained"] += 1
            elif x["status"] == exp:
                c["agree"] += 1
            else:
                c["disagree"] += 1
                wrong.append({"code": x["course_code"], "title": x["title"], "read": x["status"], "convention": exp})
        decided = c["agree"] + c["disagree"]
        out[doc_id] = {**dict(c), "precision_of_decided": round(c["agree"] / decided, 3) if decided else None,
                       "decided_share": round(decided / (decided + c["abstained"]), 3) if decided + c["abstained"] else None,
                       "disagreements": wrong}
    tot = Counter()
    for v in out.values():
        for k in ("agree", "disagree", "abstained"):
            tot[k] += v.get(k, 0)
    out["_all"] = {**dict(tot), "precision_of_decided": round(tot["agree"] / (tot["agree"] + tot["disagree"]), 3),
                   "label_source": key["label_source"]}
    return out


# ------------------------------------------------------------------ synthetic cross-discipline suite

def run_suite(suite):
    """Programmes built from invented documents; mentions are given resolved (this suite tests understanding and
    reasoning, not extraction, which Phase 3C evaluated)."""
    store = suite["taxonomy"]
    results = {"course_kind": [], "course_status": [], "level": [], "scope": [], "coverage": [], "gap": []}
    for prog in suite["programmes"]:
        docs = prog["documents"]
        courses = [c for doc in docs for c in doc["courses"]]
        topics_by_uid, mentions, titles, outs, outcome_course = {}, [], [], [], {}
        for doc in docs:
            for c in doc["courses"]:
                c.setdefault("doc_id", doc["doc_id"])
                for i, t in enumerate(c.get("topics", [])):
                    uid = f"{c['course_uid']}#t{i}"
                    topics_by_uid[uid] = {"topic_uid": uid, "clean_text": t["text"], "course_uid": c["course_uid"],
                                          "unit_label": t.get("unit", "U1"), "doc_id": doc["doc_id"]}
                    for k, phrase in t.get("skills", {}).items():
                        s = t["text"].lower().index(phrase.lower())
                        mentions.append({"source_uid": uid, "skill_key": k, "sense_state": "ESTABLISHED",
                                         "span": [s, s + len(phrase)], "normalized_text": phrase.lower()})
                for k, phrase in c.get("title_skills", {}).items():
                    titles.append({"source_uid": c["course_uid"], "skill_key": k, "sense_state": "ESTABLISHED",
                                   "normalized_text": phrase.lower(), "span": [0, 0]})
                for i, o in enumerate(c.get("outcomes", [])):
                    ouid = f"{c['course_uid']}#o{i}"
                    outcome_course[ouid] = c["course_uid"]
                    for k in o.get("skills", []):
                        outs.append({"source_uid": ouid, "skill_key": k, "sense_state": "ESTABLISHED",
                                     "normalized_text": k, "span": [0, 0], "context": o["text"]})
        profiles = {doc["doc_id"]: cu.build_profile(doc, docs, courses, doc.get("pages")) for doc in docs}
        cov = {doc_id: cu.skill_coverage(p, topics_by_uid, mentions, titles, outs, outcome_course, {},
                                         prog.get("prereq_edges", []), suite["coverage_cfg"])
               for doc_id, p in profiles.items()}
        for exp in prog["expect"].get("course_kind", []):
            got = cu.course_kind(exp["title"])[0]
            results["course_kind"].append({**exp, "got": got, "ok": got == exp["kind"]})
        for exp in prog["expect"].get("course_status", []):
            p = profiles[exp["doc_id"]]
            got = next(c["status"] for c in p["courses"].values() if c["course_code"] == exp["code"])
            results["course_status"].append({**exp, "got": got, "ok": got == exp["status"]})
        for exp in prog["expect"].get("level", []):
            got = profiles[exp["doc_id"]]["level"]
            results["level"].append({**exp, "got": got, "ok": got == exp["level"]})
        for exp in prog["expect"].get("scope", []):
            got = profiles[exp["doc_id"]]["scope"]["state"]
            results["scope"].append({**exp, "got": got, "ok": got == exp["state"]})
        for exp in prog["expect"].get("coverage", []):
            r = cov[exp["doc_id"]].get(exp["skill"]) or cu.absent_record(exp["skill"], exp["doc_id"])
            got = {f: r[f] for f in ("coverage_level", "access", "practice") if f in exp}
            want = {f: exp[f] for f in ("coverage_level", "access", "practice") if f in exp}
            results["coverage"].append({**exp, "got": got, "ok": got == want})
        target = next(doc for doc in docs if doc["role"] == "TARGET")
        tcov = cov[target["doc_id"]]
        for exp in prog["expect"].get("gap", []):
            k = exp["skill"]
            row = {"skill_key": k, "skill_label": store.get(k, {}).get("pref_label", k), **exp.get("skill_row", {})}
            row.setdefault("decisions", {"QUALIFIED_TECHNICAL": 1})
            row.setdefault("decision", "QUALIFIED_TECHNICAL")
            row.setdefault("normalized_concept", True)
            row.setdefault("programme_relevance", "IN_PROGRAMME_PROFILE")
            row.setdefault("new", {"support_state": "SUPPORTED", "postings": 12, "companies": 6})
            row.setdefault("gap_eligible", True)
            st = si.stage(row)
            rel = cu.taxonomy_related({**{kk: vv for kk, vv in tcov.items()},
                                       **({k: cu.absent_record(k, target["doc_id"])} if k not in tcov else {})}, store)
            g = gr.reason(st, tcov.get(k), profiles[target["doc_id"]]["scope"], target.get("discipline"),
                          exp.get("trend", "INSUFFICIENT_EVIDENCE"), rel.get(k))
            results["gap"].append({"programme": prog["name"], "skill": k, "expected": exp["state"],
                                   "got": g["gap_state"], "ok": g["gap_state"] == exp["state"], "reasons": g["reasons"],
                                   "case": exp.get("case")})
    summary = {name: {"n": len(rs), "correct": sum(r["ok"] for r in rs),
                      "accuracy": round(sum(r["ok"] for r in rs) / len(rs), 3) if rs else None}
               for name, rs in results.items()}
    gap_conf = Counter((r["expected"], r["got"]) for r in results["gap"])
    summary["gap_confusion"] = {f"{a} -> {b}": n for (a, b), n in sorted(gap_conf.items())}
    summary["gap_per_state"] = {}
    for s in gr.STATES:
        tp = sum(1 for r in results["gap"] if r["expected"] == s and r["got"] == s)
        fp = sum(1 for r in results["gap"] if r["expected"] != s and r["got"] == s)
        fn = sum(1 for r in results["gap"] if r["expected"] == s and r["got"] != s)
        if tp + fp + fn:
            p = tp / (tp + fp) if tp + fp else 0.0
            rc = tp / (tp + fn) if tp + fn else 0.0
            summary["gap_per_state"][s] = {"precision": round(p, 3), "recall": round(rc, 3),
                                           "f1": round(2 * p * rc / (p + rc), 3) if p + rc else 0.0, "support": tp + fn}
    return results, summary


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run")
    args = ap.parse_args()
    if not args.run:
        args.run = json.loads(need(REPO / "data/gold/knowledge/latest_run.json", "-").read_text())["run_id"]
    _ACCESS.clear()
    d = load(args.run)           # preflight: every declared input is checked before any analysis
    baseline = check_baseline(d)
    vocab, cfg, backend = esco(args.run)
    out = run(d, vocab, cfg, backend)
    cmp_ = compare_release(d, out)
    suite = json.loads(need(SUITE, args.run).read_text())
    s_results, s_summary = run_suite(suite)
    dest = REPO / "data/experiments/gap_reasoning" / args.run
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "curriculum_profiles.json").write_text(json.dumps(out["profiles"], indent=1, sort_keys=True))
    with open(dest / "skill_coverage.jsonl", "w") as fh:
        for doc_id in sorted(out["coverage"]):
            for k in sorted(out["coverage"][doc_id]):
                r = out["coverage"][doc_id][k]
                if r["coverage_level"] != "ABSENT":
                    fh.write(json.dumps(r, sort_keys=True) + "\n")
    with open(dest / "skill_stages.jsonl", "w") as fh:
        for k in sorted(out["stages"]):
            fh.write(json.dumps(out["stages"][k], sort_keys=True) + "\n")
    with open(dest / "gap_states.jsonl", "w") as fh:
        for k in sorted(out["gaps"]):
            fh.write(json.dumps(out["gaps"][k], sort_keys=True) + "\n")
    (dest / "synthetic_results.json").write_text(json.dumps({"summary": s_summary, "results": s_results},
                                                            indent=1, sort_keys=True))
    tid = out["target"]
    eligible = [g for g in out["gaps"].values() if out["stages"][g["skill_key"]]["eligible"]]
    scorecard = {
        "methods": {"curriculum": cu.METHOD, "stages": si.METHOD, "gaps": gr.METHOD},
        "run_id": args.run, "phase_3c_baseline": baseline, "extraction_regression": out["regression"],
        "suite_sha256": sha(SUITE), "label_source": "synthetic suite: AUTHOR_LABELLED (no human labels)",
        "profiles": {doc_id: {k: p[k] for k in ("role", "level", "course_kinds", "course_status")}
                     | {"scope": p["scope"]["state"]} for doc_id, p in out["profiles"].items()},
        "target_coverage_levels": dict(Counter(r["coverage_level"] for r in out["coverage"][tid].values())),
        "target_access": dict(Counter(r["access"] for r in out["coverage"][tid].values() if r["coverage_level"] != "ABSENT")),
        "target_practice": dict(Counter(r["practice"] for r in out["coverage"][tid].values() if r["coverage_level"] != "ABSENT")),
        "skill_stages": dict(Counter(s["stage_reached"] or "-" for s in out["stages"].values())),
        "stopped_at": dict(Counter((s["stopped_at"] or {}).get("stage", "ELIGIBLE") for s in out["stages"].values())),
        "gap_states_all": dict(Counter(g["gap_state"] for g in out["gaps"].values())),
        "gap_states_eligible": dict(Counter(g["gap_state"] for g in eligible)),
        "eligible_skills": sorted((g["skill_label"], g["gap_state"], g["coverage_level"], g["access"]) for g in eligible),
        "release_comparison": cmp_,
        "course_status_vs_code_conventions": status_check(out["profiles"], args.run),
        "inputs": {"parser_fingerprint": d["report"]["parser_fingerprint"],
                   "documents": {doc["doc_id"]: {"source_sha256": doc["sha256"],
                                                 "page_text_sha256": d["silver"][doc["doc_id"]]["page_text_sha256"]}
                                 for doc in d["docs"]},
                   "note": "page text content hashes (no timestamps): identical on every machine that reproduces the run"},
        "synthetic": s_summary,
    }
    (dest / "scorecard.json").write_text(json.dumps(scorecard, indent=2, sort_keys=True, default=str))
    rebuilt = sorted({p for p, _, how in _ACCESS if how == "rebuilt from source"})
    (dest / "provenance.json").write_text(json.dumps({
        "note": "machine-local: how this working tree supplied each declared input (not part of the scorecard)",
        "inputs_by_class": dict(Counter(cls for _, cls, _ in {(p, c, h) for p, c, h in _ACCESS})),
        "caches_rebuilt_from_source": rebuilt,
        "caches_present": sorted({p for p, c, how in _ACCESS if how == "present"})}, indent=1, sort_keys=True))
    if rebuilt:
        print("rebuilt from source with the recorded parser fingerprint (then verified against SILVER, GOLD and the "
              "run's mentions):", ", ".join(rebuilt))
    show = {k: scorecard[k] for k in ("phase_3c_baseline", "extraction_regression", "target_coverage_levels",
                                      "target_access", "target_practice", "stopped_at", "gap_states_eligible")}
    show["synthetic"] = {k: v for k, v in s_summary.items() if k != "gap_confusion"}
    show["v2_to_new"] = cmp_["transitions_v2_to_new"]
    show["course_status_check"] = scorecard["course_status_vs_code_conventions"]["_all"]
    print(json.dumps(show, indent=1))
    print("written", dest)


if __name__ == "__main__":
    main()
