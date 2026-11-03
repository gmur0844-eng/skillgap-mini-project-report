"""
Pipeline-health gate: blocks analytics when extraction or evidence quality
is not good enough, instead of producing plausible-looking wrong results.

Per-document checks (thresholds from engine_config.json -> "health"):
  raw_hash_verified            computed SHA-256 == manifest (FAIL on mismatch)
  ocr_required_page_ratio      pages that carry image content but no text layer
                               (content that would need OCR) / all pages. Measured
                               on the RAW text layer: an earlier version measured
                               after running-header removal and wrongly counted
                               35 header-only divider pages of a real document as
                               extraction failures
  valid_courses                count of courses passing structural validation
  titled_course_ratio          valid / (valid + UNRESOLVED_TITLE)
  topic_noise_ratio            noise-labelled fragments / all fragments
  contract_quarantine_ratio    records failing stage contracts / records
  provenance_completeness      topics carrying document + course + page
  baseline_regression          for the SAME document hash, counts may not fall
                               more than max_baseline_drop_ratio below the
                               recorded baseline (e.g. a parser change that
                               silently drops 349 units to 31 is caught here)

Analytics gates (derived):
  concept_discovery   needs >= 1 document that is not FAIL
  reference_mapping   needs a TARGET and a REFERENCE document that are not FAIL
  concept_drift       needs PREVIOUS_VERSION + TARGET not FAIL and >= 1 comparable semester
  skill_taxonomy      needs a skill taxonomy -- otherwise only tool CANDIDATES are produced
                      (scope recorded, e.g. PARTIAL_DELTA_SUBSET for the supplied ESCO delta)
  industry_demand     needs >= min_industry_postings eligible postings and industry health not FAIL
  industry_gap        same as industry_demand (plus curriculum gates for coverage)
  recommendations     needs industry_gap

A BLOCKED output is written as an explicit BLOCKED record with its reasons;
no numbers are produced for it.
"""

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def _check(name, value, threshold, ok, detail="", warn=False):
    return {"check": name, "value": value, "threshold": threshold,
            "status": PASS if ok else (WARN if warn else FAIL), "detail": detail}


def document_health(summary, cfg, baseline=None):
    h = cfg["health"]
    checks = []
    expected = summary.get("expected_sha256")
    if expected:
        checks.append(_check("raw_hash_verified", summary["sha256"], expected, summary["sha256"] == expected,
                             "computed SHA-256 must equal the manifest's expected hash"))
    else:
        checks.append(_check("raw_hash_verified", summary["sha256"], None, False,
                             "manifest has no expected hash; recorded but not verified", warn=True))
    ocr_ratio = summary["ocr_required_pages"] / max(1, summary["page_count"])
    checks.append(_check("ocr_required_page_ratio", round(ocr_ratio, 4), h["max_ocr_required_page_ratio"],
                         ocr_ratio <= h["max_ocr_required_page_ratio"] and summary["text_layer_pages"] > 0,
                         f"pages with image content but no text layer (would need OCR); "
                         f"{summary['blank_pages']} blank/divider pages and {summary['text_layer_pages']} text pages are not failures"))
    checks.append(_check("valid_courses", summary["valid_courses"], h["min_valid_courses"],
                         summary["valid_courses"] >= h["min_valid_courses"]))
    titled_denominator = summary["valid_courses"] + summary["unresolved_title_courses"]
    titled = summary["valid_courses"] / titled_denominator if titled_denominator else 0.0
    checks.append(_check("titled_course_ratio", round(titled, 4), h["min_titled_course_ratio"],
                         titled >= h["min_titled_course_ratio"]))
    noise = summary["noise_topics"] / max(1, summary["all_topics"])
    checks.append(_check("topic_noise_ratio", round(noise, 4), h["max_topic_noise_ratio"], noise <= h["max_topic_noise_ratio"]))
    q = summary["contract_violations"] / max(1, summary["contract_checked"])
    checks.append(_check("contract_quarantine_ratio", round(q, 4), h["max_quarantine_ratio"], q <= h["max_quarantine_ratio"]))
    prov = summary["topics_with_provenance"] / max(1, summary["all_topics"])
    checks.append(_check("provenance_completeness", round(prov, 4), h["min_provenance_completeness"],
                         prov >= h["min_provenance_completeness"]))
    if baseline:
        drops = {}
        for key in ("valid_courses", "units", "clean_topics", "outcomes"):
            base = baseline.get(key)
            if base:
                drops[key] = round(1 - summary[key] / base, 4)
        worst = max(drops.values()) if drops else 0.0
        checks.append(_check("baseline_regression", drops, h["max_baseline_drop_ratio"], worst <= h["max_baseline_drop_ratio"],
                             f"relative drop vs baseline recorded at {baseline.get('recorded_at')} "
                             f"(pipeline {baseline.get('pipeline_version')})"))
    else:
        checks.append(_check("baseline_regression", None, h["max_baseline_drop_ratio"], False,
                             "no baseline recorded for this document hash yet", warn=True))
    status = FAIL if any(c["status"] == FAIL for c in checks) else (WARN if any(c["status"] == WARN for c in checks) else PASS)
    return {"doc_id": summary["doc_id"], "status": status, "checks": checks}


def industry_health(summary, cfg, baseline=None):
    """
    Industry-layer checks (thresholds in config["industry"]["health"]).
    summary keys: files_verified, files_expected, records_read, duplicates, missing_description,
    eligible_postings, postings_with_skill, unique_normalized_skills, unique_skills_eligible,
    esco_mapped_skills, ambiguous_skills, postings_with_provenance, esco_skill_concepts, mentions.
    """
    h = cfg["industry"]["health"]
    checks = []
    checks.append(_check("source_hashes_verified", summary["files_verified"], summary["files_expected"],
                         summary["files_verified"] == summary["files_expected"] and summary["files_expected"] > 0))
    checks.append(_check("posting_count", summary["records_read"], h["min_postings"], summary["records_read"] >= h["min_postings"]))
    # A posting still open in a later snapshot is one posting seen twice, not a duplicate in the data: those repeats
    # are left out of both counts (and reported), so collecting snapshots on more dates cannot fail this check.
    repeats = summary.get("snapshot_repeats", 0)
    distinct = summary["records_read"] - repeats
    dup = (summary["duplicates"] - repeats) / distinct if distinct else 1.0
    checks.append(_check("duplicate_rate", round(dup, 4), h["max_duplicate_rate"], dup <= h["max_duplicate_rate"],
                         (f"{summary['duplicates'] - repeats} duplicates / {distinct} records; {repeats} postings still "
                          "open in a later snapshot are counted once and left out") if repeats else ""))
    miss = summary["missing_description"] / summary["records_read"] if summary["records_read"] else 1.0
    checks.append(_check("missing_description_ratio", round(miss, 4), h["max_missing_description_ratio"],
                         miss <= h["max_missing_description_ratio"]))
    checks.append(_check("eligible_postings", summary["eligible_postings"], h["min_eligible_postings"],
                         summary["eligible_postings"] >= h["min_eligible_postings"]))
    yld = summary["postings_with_skill"] / summary["eligible_postings"] if summary["eligible_postings"] else 0.0
    checks.append(_check("skill_extraction_yield", round(yld, 4), h["min_skill_extraction_yield"],
                         yld >= h["min_skill_extraction_yield"],
                         "eligible postings with >= 1 analytics-eligible skill mention / eligible postings"))
    checks.append(_check("unique_normalized_skills", summary["unique_skills_eligible"], h["min_unique_normalized_skills"],
                         summary["unique_skills_eligible"] >= h["min_unique_normalized_skills"]))
    esco = summary["esco_mapped_skills"] / summary["unique_skills_eligible"] if summary["unique_skills_eligible"] else 0.0
    checks.append(_check("esco_mapping_yield", round(esco, 4), h["min_esco_mapping_yield"], esco >= h["min_esco_mapping_yield"],
                         "EXACT/NORMALIZED/SEMANTIC_MATCH skills / analytics-eligible posting skills"))
    amb = summary["ambiguous_skills"] / summary["unique_normalized_skills"] if summary["unique_normalized_skills"] else 0.0
    checks.append(_check("ambiguous_skill_ratio", round(amb, 4), h["max_ambiguous_skill_ratio"], amb <= h["max_ambiguous_skill_ratio"]))
    prov = summary["postings_with_provenance"] / summary["eligible_postings"] if summary["eligible_postings"] else 0.0
    checks.append(_check("provenance_completeness", round(prov, 4), h["min_provenance_completeness"],
                         prov >= h["min_provenance_completeness"], "source file + row + URL + posted date + SHA-256"))
    checks.append(_check("esco_skill_concepts", summary["esco_skill_concepts"], h["min_esco_skill_concepts"],
                         summary["esco_skill_concepts"] >= h["min_esco_skill_concepts"]))
    if baseline:
        drops = {k: round(1 - summary[k] / baseline[k], 4) for k in ("eligible_postings", "mentions", "unique_skills_eligible",
                                                                    "esco_mapped_skills") if baseline.get(k)}
        worst = max(drops.values()) if drops else 0.0
        checks.append(_check("baseline_regression", drops, h["max_baseline_drop_ratio"], worst <= h["max_baseline_drop_ratio"],
                             f"relative drop vs industry baseline recorded at {baseline.get('recorded_at')}"))
    else:
        checks.append(_check("baseline_regression", None, h["max_baseline_drop_ratio"], False,
                             "no industry baseline recorded for these inputs yet", warn=True))
    status = FAIL if any(c["status"] == FAIL for c in checks) else (WARN if any(c["status"] == WARN for c in checks) else PASS)
    return {"scope": "industry", "status": status, "checks": checks}


def analytics_gates(doc_health, roles, comparable_semesters, taxonomy_loaded, industry_postings, cfg,
                    industry_health_status=None, taxonomy_scope=None):
    usable = {d: r for d, r in roles.items() if doc_health[d]["status"] != FAIL}
    by_role = {}
    for d, r in usable.items():
        by_role.setdefault(r, []).append(d)
    failed = sorted(d for d in roles if doc_health[d]["status"] == FAIL)
    gates = {}

    def gate(name, ok, reason_if_blocked):
        gates[name] = {"status": "ALLOWED" if ok else "BLOCKED", "reasons": [] if ok else [reason_if_blocked]}

    gate("concept_discovery", bool(usable), f"every document failed the health gate: {failed}")
    gate("reference_mapping", "TARGET" in by_role and "REFERENCE" in by_role,
         f"needs a healthy TARGET and REFERENCE document (failed: {failed})")
    gate("concept_drift", "TARGET" in by_role and "PREVIOUS_VERSION" in by_role and bool(comparable_semesters),
         "needs healthy TARGET + PREVIOUS_VERSION documents of the same programme with at least one comparable semester")
    gate("skill_taxonomy", taxonomy_loaded,
         "no skill taxonomy (ESCO) is loaded; tool/technology CANDIDATES are produced instead, no taxonomy skills")
    if taxonomy_loaded and taxonomy_scope:
        gates["skill_taxonomy"]["scope"] = taxonomy_scope
    minimum = cfg["health"]["min_industry_postings"]
    gate("industry_gap", industry_postings is not None and industry_postings >= minimum and industry_health_status != FAIL,
         ("industry health gate FAILED; demand, gaps and recommendations are not produced"
          if industry_health_status == FAIL and industry_postings is not None and industry_postings >= minimum else
          f"industry population: {industry_postings if industry_postings is not None else 'NONE'} real job postings "
          f"(minimum {minimum}); demand, gap classification and alignment cannot be computed without it"))
    gate("industry_demand", industry_postings is not None and industry_postings >= minimum and industry_health_status != FAIL,
         gates["industry_gap"]["reasons"][0] if gates["industry_gap"]["reasons"] else "")
    gate("recommendations", gates["industry_gap"]["status"] == "ALLOWED",
         "recommendations require an industry-evidenced gap classification, which is blocked")
    for name in gates:
        if failed and gates[name]["status"] == "ALLOWED":
            gates[name]["excluded_documents"] = failed
    return gates
