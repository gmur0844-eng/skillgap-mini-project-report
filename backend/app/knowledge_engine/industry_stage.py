"""
Pipeline stage functions for the industry/ESCO layer (called from pipeline.run).

  industry.raw      verify job files + ESCO ZIP (hash vs manifest, source-evidence guard)
  industry.silver   postings RAW -> BRONZE -> SILVER (jobs.ingest_postings)
  industry.extract  skill mentions in postings and in curriculum topic text; ESCO mapping (the rule-based part --
                    mentions, mapping and sense checks -- is cached by the hash of all of its inputs; see
                    ExtractionCache)
  (health gate)     industry_health on the counts above
  industry.gold     demand, segments, temporal scope, coverage, gaps, recommendations,
                    suppression reasons, evidence traces, review queue
"""
import gzip
import hashlib
import pickle
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from app.knowledge_engine import esco_full
from app.knowledge_engine import industry as ind
from app.knowledge_engine.esco_delta import build_skill_vocabulary, read_delta_rows
from app.knowledge_engine.evidence_guard import require_source_path, require_source_records
from app.knowledge_engine.exports import file_sha256
from app.knowledge_engine.jobs import ingest_postings, population_scope
from app.knowledge_engine.silver import uid
from app.pipelines.preprocessing.skill_extraction import IndexedVocabulary


def verify_sources(manifest, repo, quarantine):
    jobs, taxonomies = [], []
    for kind, bucket in (("industry_sources", jobs), ("taxonomy_sources", taxonomies)):
        for entry in manifest.get(kind, []):
            require_source_path(entry["path"], repo)
            path = Path(repo) / entry["path"]
            if not path.exists():
                quarantine.add("industry.raw", entry, f"MISSING_FILE: {entry['path']}")
                continue
            sha = file_sha256(path)
            bucket.append({**entry, "abs_path": str(path), "sha256": sha,
                           "hash_verified": sha == entry.get("expected_sha256")})
    return jobs, taxonomies


_ESCO_LOADED = {}  # (sources, mode) -> pickled (vocabulary, audit): one load per process


def load_esco(taxonomies, mode="full_with_delta"):
    """Loads ESCO (see _load_esco). Within one process the same verified files are read once: later calls get a
    fresh, independent copy of the first result (unpickled), so no caller can change what another one receives."""
    key = (mode, tuple(sorted((t.get("kind"), t.get("sha256"), str(t.get("abs_path")), bool(t.get("hash_verified")))
                              for t in taxonomies)))
    if key not in _ESCO_LOADED:
        _ESCO_LOADED[key] = pickle.dumps(_load_esco(taxonomies, mode), protocol=pickle.HIGHEST_PROTOCOL)
    return pickle.loads(_ESCO_LOADED[key])


def _load_esco(taxonomies, mode="full_with_delta"):
    """
    mode "full_with_delta" (default): the FULL classification is the taxonomy; the delta annotates
    label changes and supplies retired labels. Falls back to the delta alone (PARTIAL_DELTA_SUBSET)
    when no hash-verified full classification is supplied -- stated in the audit.
    mode "delta_only": the previous behaviour, kept for comparison runs.
    The returned vocabulary carries the full store under "_store" (not serialised).
    """
    delta = next((t for t in taxonomies if t.get("kind") == "esco_delta" and t["hash_verified"]), None)
    full = next((t for t in taxonomies if t.get("kind") == "esco_full" and t["hash_verified"]), None)
    if delta is None and full is None:
        return None, {"status": "NOT_LOADED", "reason": "no hash-verified ESCO source in the manifest"}
    delta_vocab, delta_audit = (build_skill_vocabulary(read_delta_rows(delta["abs_path"])) if delta else (None, None))
    if delta_audit is not None:
        delta_audit["source"] = {k: delta[k] for k in ("source_id", "path", "version", "sha256")}
    if full is None or mode == "delta_only":
        delta_audit["taxonomy_mode"] = "delta_only" if mode == "delta_only" else "delta_only (no full classification supplied)"
        delta_vocab["scope"] = "PARTIAL_DELTA_SUBSET"
        return delta_vocab, delta_audit
    tables, members = esco_full.read_classification(full["abs_path"])
    store, store_audit = esco_full.build_store(tables, members)
    vocab, vocab_audit = esco_full.skill_vocabulary(store, delta_vocab)
    vocab["_store"] = store
    audit = {"taxonomy_mode": "full_with_delta" if delta else "full_only",
             "reconstruction_scope": "FULL_TAXONOMY", "skill_concepts_reconstructed": len(vocab["concepts"]),
             "full_source": {k: full[k] for k in ("source_id", "path", "version", "sha256")},
             "full_classification": store_audit, "matching_vocabulary": vocab_audit,
             "delta_change_information": delta_audit,
             "delta_vs_full": esco_full.delta_vs_full(store, delta_vocab) if delta_vocab else None}
    return vocab, audit


def ingest(jobs, repo, settings, boilerplate=None):
    verified = [j for j in jobs if j["hash_verified"]]
    return ingest_postings(verified, Path(repo) / "data/bronze/jobs", Path(repo) / "data/silver/jobs",
                           settings["near_duplicate_similarity_threshold"], boilerplate)


class ExtractionCache:
    """Cache of the rule-based extraction (mentions, ESCO mapping, sense checks) -- the slowest part of a run, and
    identical whenever its inputs are. The key hashes every input: the postings and curriculum topics themselves (as
    read by this run), the taxonomy file hashes and mode, the analysis code fingerprint, the configuration hash, the
    semantic backend and the numeric library versions. Anything else misses. The model-based sense resolver is never
    cached: it runs on every run, after the cached part, exactly as before. INDUSTRY_EXTRACTION_CACHE=off disables
    it. A cache that cannot be read or written only costs time; the run never fails because of it."""

    VERSION = "industry-extraction-v1"

    def __init__(self, directory, identity):
        self.directory = Path(directory)
        self.identity = identity
        self.enabled = os.environ.get("INDUSTRY_EXTRACTION_CACHE", "").strip().lower() not in ("off", "0", "false")

    def key(self, postings, topics):
        h = hashlib.sha256(self.VERSION.encode())
        h.update(json.dumps(self.identity, sort_keys=True, default=str).encode())
        for rec in postings:
            h.update(json.dumps(rec, sort_keys=True, default=str).encode())
        h.update(b"|topics|")
        for rec in topics:
            h.update(json.dumps(rec, sort_keys=True, default=str).encode())
        return h.hexdigest()[:32]

    def load(self, key):
        if not self.enabled:
            return None
        try:
            with gzip.open(self.directory / f"{key}.json.gz", "rt", encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("version") != self.VERSION or data.get("key") != key:
                return None
            return data["result"]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def store(self, key, result):
        if not self.enabled:
            return False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            payload = json.dumps({"version": self.VERSION, "key": key, "identity": self.identity, "result": result},
                                 sort_keys=True)
            tmp = self.directory / f".{key}.{os.getpid()}.tmp"
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.directory / f"{key}.json.gz")
            return True
        except (OSError, TypeError, ValueError):
            return False


def _rule_based_extraction(postings, curriculum_topics, esco_vocab, cfg, backend_factory, index, label_index):
    """Mentions in postings and topics, their ESCO mapping and the rule-based sense checks (no model involved)."""
    posting_mentions = ind.extract(postings, "clean_description", "posting_uid", index, "job_posting")
    curriculum_mentions = ind.extract(curriculum_topics, "clean_text", "topic_uid", index, "curriculum_topic")
    for m in posting_mentions + curriculum_mentions:
        m["mention_uid"] = uid("mention", m["source_type"], m["source_uid"], m["span"][0], m["normalized_text"])
    mappings = ind.map_skills(posting_mentions + curriculum_mentions, esco_vocab, label_index, backend_factory, cfg["industry"])
    for m in posting_mentions + curriculum_mentions:
        mp = mappings[m["normalized_text"]]
        m.update(skill_key=mp["skill_key"], esco_status=mp["status"])
    # ---- sense validation (context = the whole posting incl. title; for topics: the other topics of the same unit)
    labels_by_uri = ind.concept_labels(esco_vocab)
    posting_text = {p["posting_uid"]: f"{p.get('job_title') or ''}\n{p['clean_description']}" for p in postings}
    unit_text = defaultdict(list)
    for t in curriculum_topics:
        unit_text[(t["course_uid"], t.get("unit_label"))].append(t["clean_text"])
    topic_unit = {t["topic_uid"]: (t["course_uid"], t.get("unit_label")) for t in curriculum_topics}
    by_source = defaultdict(list)
    for m in posting_mentions + curriculum_mentions:
        by_source[(m["source_type"], m["source_uid"])].append(m)
    for m in posting_mentions + curriculum_mentions:
        context = (posting_text[m["source_uid"]] if m["source_type"] == "job_posting"
                   else "\n".join(unit_text[topic_unit[m["source_uid"]]]))
        state, relationship, evidence = ind.sense_check(m, mappings[m["normalized_text"]], context, labels_by_uri,
                                                        by_source[(m["source_type"], m["source_uid"])],
                                                        cfg["industry"]["alias_orthographic_min_ratio"])
        m.update(sense_state=state, taxonomy_relationship=relationship, sense_evidence=evidence,
                 sense_established=state in ind.SENSE_ESTABLISHED)
    return posting_mentions, curriculum_mentions, mappings


def extract_and_map(postings, curriculum_topics, esco_vocab, cfg, backend_factory, sense_resolver=None, cache=None):
    """cache: an ExtractionCache (or None). Its status is returned in result["cache"], outside the summary, so a run's
    analytical outputs never record whether the cache was used."""
    require_source_records(postings, "job posting")
    require_source_records(curriculum_topics, "curriculum topic")
    terms, label_index = ind.build_vocabulary(esco_vocab)
    index = IndexedVocabulary(terms)
    cache_status, key, cached = "OFF", None, None
    if cache is not None and cache.enabled:
        key = cache.key(postings, curriculum_topics)
        cached = cache.load(key)
        cache_status = "HIT" if cached is not None else "MISS"
    if cached is not None:
        posting_mentions, curriculum_mentions, mappings = (cached["posting_mentions"], cached["curriculum_mentions"],
                                                           cached["mappings"])
    else:
        posting_mentions, curriculum_mentions, mappings = _rule_based_extraction(
            postings, curriculum_topics, esco_vocab, cfg, backend_factory, index, label_index)
        if cache_status == "MISS":
            # stored before the model-based resolver touches the mentions, so the cache never holds a model decision
            stored = cache.store(key, {"posting_mentions": posting_mentions, "curriculum_mentions": curriculum_mentions,
                                       "mappings": mappings})
            if stored:
                # use the stored form from here on, so a cold run and a warm run continue from identical values
                rt = json.loads(json.dumps({"p": posting_mentions, "c": curriculum_mentions, "m": mappings}, sort_keys=True))
                posting_mentions, curriculum_mentions, mappings = rt["p"], rt["c"], rt["m"]
            else:
                cache_status = "MISS_NOT_STORED"
    semantic_report = None
    if sense_resolver is not None:  # model decisions may settle alias senses the rules left open (gated, audited)
        resolved, semantic_report = sense_resolver(posting_mentions, curriculum_mentions, mappings, postings)
        for m in posting_mentions:
            if m["mention_uid"] in resolved:
                state, decision = resolved[m["mention_uid"]]
                m.update(sense_state=state, sense_established=state in ind.SENSE_ESTABLISHED,
                         sense_evidence={**(m.get("sense_evidence") or {}), "semantic_decision": decision})
    posting_surfaces = {m["normalized_text"] for m in posting_mentions}
    skills = ind.normalized_skills({s: mp for s, mp in mappings.items() if s in posting_surfaces})
    for key, sk in skills.items():
        ms = [m for m in posting_mentions if m["skill_key"] == key]
        states = Counter(m["sense_state"] for m in ms)
        sk["sense_states"] = dict(states)
        sk["established_mentions"] = sum(states[x] for x in ind.SENSE_ESTABLISHED)
        if sk["established_mentions"] == 0 and states.get("ALIAS_SENSE_REVIEW_REQUIRED"):
            sk.update(esco_status="ALIAS_SENSE_REVIEW_REQUIRED", taxonomy_candidate_uri=sk["esco_uri"],
                      taxonomy_candidate_label=sk["esco_pref_label"], esco_uri=None, esco_pref_label=None,
                      label=sk["surfaces"][0], taxonomy_relationship="TAXONOMY_ALIAS_MATCH",
                      evidence_status="REVIEW_REQUIRED")
        if sk["established_mentions"] == 0:
            sk["eligible_for_analytics"] = False
    eligible = {k for k, s in skills.items() if s["eligible_for_analytics"]}
    counted = [m for m in posting_mentions if m["skill_key"] in eligible and m["mention_role"] == "SKILL" and m["sense_established"]]
    summary = {
        "mentions": len(counted),
        "mentions_sense_review_required": sum(1 for m in posting_mentions if m["sense_state"].endswith("REVIEW_REQUIRED")),
        "mentions_by_sense_state": dict(Counter(m["sense_state"] for m in posting_mentions)),
        "qualification_mentions": sum(1 for m in posting_mentions if m["mention_role"] == "QUALIFICATION_REQUIREMENT"),
        "mentions_all": len(posting_mentions),
        "postings_with_skill": len({m["source_uid"] for m in counted}),
        "unique_normalized_skills": len(skills), "unique_skills_eligible": len(eligible),
        "esco_mapped_skills": sum(1 for k in eligible if skills[k]["esco_status"] in ind.MAPPED_STATUSES),
        "ambiguous_skills": sum(1 for s in skills.values() if s["esco_status"] == "AMBIGUOUS"),
        "skills_by_esco_status": dict(Counter(s["esco_status"] for s in skills.values())),
        "skills_by_category": dict(Counter(s["skill_category"] for s in skills.values())),
        "curriculum_mentions": len(curriculum_mentions),
    }
    return {"posting_mentions": posting_mentions, "curriculum_mentions": curriculum_mentions, "mappings": mappings,
            "skills": skills, "summary": summary, "_index": index, "semantic": semantic_report,
            "cache": {"status": cache_status, "key": key}}


def health_summary(jobs, ingest_result, extraction, esco_vocab):
    postings = ingest_result["postings"]
    s = ingest_result["summary"]
    return {
        "files_expected": len(jobs), "files_verified": sum(1 for j in jobs if j["hash_verified"]),
        "records_read": s["records_read"], "duplicates": s["status_counts"].get("DUPLICATE", 0),
        "snapshot_repeats": s.get("snapshot_repeats", 0),
        "missing_description": s["missing_description"], "eligible_postings": len(postings),
        "postings_with_provenance": sum(1 for p in postings if p["source_file"] and p["row_number"] and p["url"]
                                        and p["posted_date"] and p["source_sha256"]),
        "esco_skill_concepts": len(esco_vocab["concepts"]) if esco_vocab else 0,
        **{k: extraction["summary"][k] for k in ("mentions", "postings_with_skill", "unique_normalized_skills",
                                                 "unique_skills_eligible", "esco_mapped_skills", "ambiguous_skills")},
    }


def gold(postings, sources, extraction, curriculum, cfg, settings, run_id, backend_factory):
    """curriculum = {"topics_by_uid", "courses_by_uid", "roles", "topic_to_concept", "target_doc", "reference_doc", "previous_doc"}"""
    skills, mappings = extraction["skills"], extraction["mappings"]
    eligible_keys = {k for k, s in skills.items() if s["eligible_for_analytics"]}
    pairs = {(m["skill_key"], m["source_uid"]) for m in extraction["posting_mentions"]
             if m["skill_key"] in eligible_keys and m["mention_role"] == "SKILL" and m["sense_established"]}
    qualification_pairs = {(m["skill_key"], m["source_uid"]) for m in extraction["posting_mentions"]
                           if m["skill_key"] in eligible_keys and m["mention_role"] == "QUALIFICATION_REQUIREMENT"}
    scope = population_scope(postings, sources)
    scope["scope_uid"] = uid("scope", run_id, "ALL_POSTINGS")
    demand_rows = ind.demand(sorted(pairs), postings, scope, cfg["industry"])
    for d in demand_rows:
        d["qualification_only_postings"] = len({pid for k, pid in qualification_pairs if k == d["skill_key"]} - set(d["posting_uids"]))
        d["population_scope_ref"] = scope["scope_uid"]
        d["skill_label"] = skills[d["skill_key"]]["label"]
        d["esco_status"] = skills[d["skill_key"]]["esco_status"]
    src_by_id = {s.get("source_id"): s for s in sources} if isinstance(sources, list) else (sources or {})
    temporal = ind.temporal_demand(pairs, postings, settings,
                                   population_ids=[(src_by_id.get(p.get("source_id")) or {}).get("population_id")
                                                   or f"SOURCE:{p.get('source_id')}" for p in postings])
    seg = ind.segment_postings(postings, backend_factory, cfg["industry"])
    segment_rows = []
    for sgm in seg["segments"]:
        members = [p for p in postings if p["posting_uid"] in set(sgm["posting_uids"])]
        rows = ind.demand(sorted(p for p in pairs if p[1] in set(sgm["posting_uids"])), members, scope, cfg["industry"],
                          segment=sgm["segment_uid"])
        sgm["gap_classification"] = ("PERMITTED" if sgm["size"] >= cfg["industry"]["segments"]["min_segment_postings_for_gaps"]
                                     else "INSUFFICIENT_EVIDENCE")
        sgm["gap_reason"] = (None if sgm["gap_classification"] == "PERMITTED" else
                             f"segment has {sgm['size']} postings; gap classification needs >= "
                             f"{cfg['industry']['segments']['min_segment_postings_for_gaps']}")
        for r in rows:
            r["skill_label"] = skills[r["skill_key"]]["label"]
        sgm["top_skills"] = sorted(rows, key=lambda r: (-r["posting_count"], r["skill_label"]))[:10]
        segment_rows += rows
    topics_by_uid, courses_by_uid = curriculum["topics_by_uid"], curriculum["courses_by_uid"]
    cov = {}
    for role_key in ("target_doc", "reference_doc", "previous_doc"):
        doc_id = curriculum.get(role_key)
        cov[role_key] = ind.curriculum_coverage(extraction["curriculum_mentions"], topics_by_uid, courses_by_uid, doc_id,
                                                mappings, curriculum["topic_to_concept"]) if doc_id else ({}, 0)
    target_cov, target_pop = cov["target_doc"]
    gaps = ind.classify_gaps(skills, demand_rows, target_cov, target_pop, cov["reference_doc"][0], cov["previous_doc"][0],
                             len(postings), settings, scope["scope_uid"], run_id)
    recs, suppressed = ind.recommend(gaps, target_cov, cfg["industry"])
    coverage_rows = []
    for role_key, (rows, population) in cov.items():
        for key, v in sorted(rows.items()):
            if key in {d["skill_key"] for d in demand_rows}:
                coverage_rows.append({"skill_key": key, "skill_label": skills[key]["label"], "role": role_key,
                                      "curriculum_population": population, **v,
                                      "evidence_classes": {"direct_textual_courses": v["courses_with_direct_textual_evidence"],
                                                           "normalized_only_courses": v["courses_with_normalized_evidence_only"],
                                                           "semantic_inference": "concept membership of matching topics (concept_uids), not counted as coverage",
                                                           "reference_mapping": "reference document coverage is reported separately, never as target coverage",
                                                           "human_validated": 0}})
    traces = build_traces(recs, gaps, demand_rows, skills, mappings, extraction, postings, target_cov, cov["reference_doc"][0],
                          scope, cfg, suppressed)
    review = review_queue(skills, mappings, demand_rows, gaps, recs, suppressed, cfg, extraction["posting_mentions"], postings)
    qual = defaultdict(set)
    for k, pid in qualification_pairs:
        qual[k].add(pid)
    qualification_rows = [{"skill_key": k, "skill_label": skills[k]["label"], "postings_with_qualification_mention": len(v),
                           "postings_with_skill_mention": next((d["posting_count"] for d in demand_rows if d["skill_key"] == k), 0),
                           "note": "mentions inside education requirements (e.g. 'degree in ...') are not counted as skill demand"}
                          for k, v in sorted(qual.items())]
    return {"scope": scope, "demand": demand_rows, "qualification_mentions": qualification_rows, "temporal": temporal, "segments": seg, "segment_demand": segment_rows,
            "coverage": coverage_rows, "gaps": gaps, "recommendations": recs, "suppressions": suppressed,
            "traces": traces, "review_queue": review,
            "coverage_populations": {k: v[1] for k, v in cov.items()}}


def build_traces(recs, gaps, demand_rows, skills, mappings, extraction, postings, target_cov, reference_cov, scope, cfg,
                 suppressed):
    """Full evidence chain for every recommendation and every high-demand gap."""
    posting_by_uid = {p["posting_uid"]: p for p in postings}
    demand_by = {d["skill_key"]: d for d in demand_rows}
    gap_by = {g["skill_key"]: g for g in gaps}
    rec_by = {r["skill_key"]: r for r in recs}
    sup_by = {s["skill_key"]: s for s in suppressed}
    mentions_by_skill = defaultdict(list)
    for m in extraction["posting_mentions"]:
        mentions_by_skill[m["skill_key"]].append(m)
    keys = sorted(set(rec_by) | {g["skill_key"] for g in gaps if g["high_demand"]})
    traces = []
    for key in keys:
        s, d, g = skills[key], demand_by[key], gap_by[key]
        ms = sorted(mentions_by_skill[key], key=lambda m: (m["source_uid"], m["span"][0]))
        cov = target_cov.get(key)
        traces.append({
            "trace_uid": uid("trace", g["gap_uid"]), "skill_key": key,
            "job_postings": [{"posting_uid": m["source_uid"], "url": posting_by_uid[m["source_uid"]]["url"],
                              "source_file": posting_by_uid[m["source_uid"]]["source_file"],
                              "row_number": posting_by_uid[m["source_uid"]]["row_number"],
                              "job_title": posting_by_uid[m["source_uid"]]["job_title"],
                              "company": posting_by_uid[m["source_uid"]]["company_name"],
                              "raw_mention": m["raw_mention"], "span": m["span"], "context": m["context"],
                              "extraction_method": m["method"], "mention_uid": m["mention_uid"]} for m in ms][:20],
            "normalized_skill": {"skill_uid": s["skill_uid"], "label": s["label"], "surfaces": s["surfaces"],
                                 "category": s["skill_category"]},
            "esco": {"status": s["esco_status"], "uri": s["esco_uri"], "pref_label": s["esco_pref_label"],
                     "mapping_method": s["mapping_method"],
                     # the scope the mapping was actually made in (a fixed "delta only" label used to be written
                     # here even when the full classification was loaded -- corrected in the improvement release)
                     "taxonomy_scope": next((mappings[x].get("taxonomy_scope") for x in s["surfaces"] if x in mappings),
                                            None)},
            "industry_demand": {k: d[k] for k in ("posting_count", "eligible_postings", "posting_prevalence_pct", "company_count",
                                                   "eligible_companies", "company_prevalence_pct", "support_state", "statement")},
            "population_scope": {k: scope[k] for k in ("eligible_postings", "source_files", "geographic_scope", "date_range",
                                                       "distinct_companies", "representativeness_warning")},
            "curriculum": {"target_courses_with_skill": cov["courses_with_skill"] if cov else 0,
                           "target_course_codes": cov["course_codes"] if cov else [],
                           "target_topic_evidence": cov["topic_evidence"] if cov else [],
                           "concept_uids": cov["concept_uids"] if cov else [],
                           "reference_courses_with_skill": reference_cov[key]["courses_with_skill"] if key in reference_cov else 0,
                           "reference_topic_evidence": reference_cov[key]["topic_evidence"][:5] if key in reference_cov else []},
            "curriculum_coverage": {"coverage_pct": g["curriculum_coverage_pct"], "population": g["curriculum_population"],
                                    "count": g["curriculum_count"]},
            "gap": {k: g[k] for k in ("gap_uid", "classification", "evidence_state", "reasons", "high_demand")},
            "recommendation": rec_by.get(key),
            "no_recommendation": sup_by.get(key),
            "uncertain_links": ([] if s["esco_status"] in ("EXACT", "NORMALIZED") else [f"ESCO status {s['esco_status']}"])
                               + (rec_by[key]["uncertainty"] if key in rec_by else []),
            "run_id": g["run_id"],
        })
    return traces


def review_queue(skills, mappings, demand_rows, gaps, recs, suppressed, cfg, posting_mentions=(), postings=()):
    observed = cfg["industry"]["support"]["observed_min_postings"]
    demand_by = {d["skill_key"]: d for d in demand_rows}
    items = []

    def add(kind, priority, key, detail):
        items.append({"review_item_uid": uid("indreview", kind, key), "kind": kind, "priority": priority, "subject": key,
                      "detail": detail, "review_decision": None, "reviewer": None, "decided_at": None,
                      "evidence_status": "REVIEW_REQUIRED"})
    # sense-validation items: one per (skill, sense state), with every posting context
    title_of = {p["posting_uid"]: p.get("job_title") for p in postings}
    grouped = defaultdict(list)
    for m in posting_mentions:
        if m.get("sense_state", "").endswith("REVIEW_REQUIRED") and m["mention_role"] == "SKILL":
            grouped[(m["skill_key"], m["sense_state"])].append(m)
    for (key, state), ms in sorted(grouped.items(), key=lambda kv: (-len({m["source_uid"] for m in kv[1]}), kv[0])):
        n_postings = len({m["source_uid"] for m in ms})
        ev = ms[0]["sense_evidence"] or {}
        add("ALIAS_SENSE_CHECK" if state.startswith("ALIAS") else "ACRONYM_SENSE_CHECK",
            "HIGH" if n_postings >= observed else "MEDIUM", key, {
                "observed_text": sorted({m["raw_mention"] for m in ms}), "esco_candidate": ev.get("esco_candidate"),
                "esco_uri": ev.get("esco_uri"), "esco_evidence": ev.get("esco_evidence"), "question": ev.get("question"),
                "postings": n_postings, "excluded_from_demand_until_reviewed": True,
                "contexts": [{"posting_uid": m["source_uid"], "job_title": title_of.get(m["source_uid"]),
                              "context": m["context"], "span": m["span"]} for m in ms][:10]})
    for surface, m in sorted(mappings.items()):
        if m["status"] == "AMBIGUOUS":
            add("AMBIGUOUS_ESCO_MAPPING", "HIGH", surface, {"candidates": m["candidates"], "reason": m["reason"]})
        if m["status"] == "SEMANTIC_MATCH":
            add("UNCERTAIN_ESCO_MAPPING", "MEDIUM", surface, {"esco_uri": m["esco_uri"], "similarity_score": m["similarity_score"]})
    mention_postings = defaultdict(set)
    for m in posting_mentions:
        if m["mention_role"] == "SKILL":
            mention_postings[m["skill_key"]].add(m["source_uid"])
    for key, s in sorted(skills.items()):
        d = demand_by.get(key)
        if s["esco_status"] == "INSUFFICIENT_EVIDENCE" and len(mention_postings[key]) >= observed:
            # these never have a demand row (excluded), so their frequency comes from the raw mentions
            add("HIGH_FREQUENCY_CONTEXT_DEPENDENT_LABEL", "MEDIUM", key, {"postings_with_raw_mention": len(mention_postings[key]),
                "surfaces": s["surfaces"], "question": "does the text use this word as the ESCO skill?"})
        elif s["esco_status"] == "UNMAPPED" and d and d["posting_count"] >= observed:
            add("HIGH_DEMAND_UNMAPPED_SKILL", "MEDIUM", key, {"postings": d["posting_count"]})
    for g in gaps:
        if g["high_demand"] and g["classification"] in ("MISSING", "PARTIAL"):
            add("HIGH_IMPACT_GAP", "HIGH", g["skill_key"], {"classification": g["classification"],
                "industry_prevalence_pct": g["industry_prevalence_pct"], "curriculum_coverage_pct": g["curriculum_coverage_pct"]})
        if g["evidence_state"] == "DISCIPLINE_RELEVANCE_UNESTABLISHED" and g["support_state"] in ("SUPPORTED", "HIGH_SUPPORT"):
            add("DISCIPLINE_RELEVANCE_UNESTABLISHED", "HIGH", g["skill_key"], {"postings": g["industry_count"],
                "question": "is this skill within the programme's scope?"})
    for r in recs:
        if r["support_state"] == "SUPPORTED":
            add("BORDERLINE_RECOMMENDATION", "MEDIUM", r["skill_key"], {"action": r["action_type"], "uncertainty": r["uncertainty"]})
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted(items, key=lambda i: (order[i["priority"]], i["kind"], i["subject"]))
