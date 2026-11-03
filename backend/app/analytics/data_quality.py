"""
Data-quality metric computation (spec Section 9 / new Phase Section 9).

`compute_job_posting_quality_metrics` is a pure function: give it the records
you actually processed (including which were rejected/duplicate/near-duplicate)
and it returns the exact metric set the spec asks for. Deliberately has no
SQLAlchemy import so it can be unit-tested with plain dicts and reused by both
the ingestion pipeline (which then persists the results as DataQualityMetric
rows) and, later, a "recompute quality for an existing dataset" endpoint.
"""
from statistics import mean


def compute_job_posting_quality_metrics(
    total_input_records: int,
    accepted_records: list[dict],
    rejected_records: list[dict],
    duplicate_count: int,
    near_duplicate_count: int,
    already_ingested_count: int = 0,
) -> dict:
    """
    accepted_records: list of {"clean_description": str, ...} for records that
        passed validation AND were newly inserted (already-ingested rows are
        counted separately, not included here).
    rejected_records: list of {"reason": str, ...} for records that failed
        validation and were excluded entirely.
    already_ingested_count: rows that were valid but skipped because they were
        already present for this source (Phase-1 idempotency, item 1) --
        tracked distinctly from "invalid" since they are not a data-quality
        problem, they're expected behavior on a re-run.
    """
    valid_count = len(accepted_records)
    invalid_count = len(rejected_records)

    lengths = [len(r.get("clean_description") or "") for r in accepted_records]
    missing_descriptions = sum(1 for r in accepted_records if not (r.get("clean_description") or "").strip())

    reasons: dict[str, int] = {}
    for r in rejected_records:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1

    return {
        "total_records": total_input_records,
        "valid_records": valid_count,
        "invalid_records": invalid_count,
        "already_ingested_records": already_ingested_count,
        "exact_duplicates": duplicate_count,
        "near_duplicates": near_duplicate_count,
        "missing_descriptions": missing_descriptions,
        "avg_text_length": round(mean(lengths), 1) if lengths else None,
        "min_text_length": min(lengths) if lengths else None,
        "max_text_length": max(lengths) if lengths else None,
        "removed_reasons": reasons,  # e.g. {"empty_description": 12, "description_too_short": 3}
    }


def compute_curriculum_quality_metrics(documents: list[dict]) -> dict:
    """
    documents: list of {"page_count": int, "extraction_confidence": float|None,
                         "flagged_for_review": bool, "courses_found": int}
    """
    total = len(documents)
    flagged = sum(1 for d in documents if d.get("flagged_for_review"))
    confidences = [d["extraction_confidence"] for d in documents if d.get("extraction_confidence") is not None]
    courses_found = sum(d.get("courses_found", 0) for d in documents)

    return {
        "total_documents": total,
        "flagged_for_review": flagged,
        "avg_extraction_confidence": round(mean(confidences), 2) if confidences else None,
        "total_courses_extracted": courses_found,
        "documents_with_zero_courses": sum(1 for d in documents if d.get("courses_found", 0) == 0),
    }


def metrics_to_rows(metrics: dict, analysis_run_id: int, source_id: int | None) -> list[dict]:
    """
    Flattens a metrics dict (which may contain a nested dict like
    removed_reasons) into a list of {metric_name, metric_value} rows suitable
    for bulk-inserting as DataQualityMetric records.
    """
    rows = []
    for key, value in metrics.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                rows.append(
                    {
                        "analysis_run_id": analysis_run_id,
                        "source_id": source_id,
                        "metric_name": f"{key}:{sub_key}",
                        "metric_value": str(sub_value),
                    }
                )
        else:
            rows.append(
                {
                    "analysis_run_id": analysis_run_id,
                    "source_id": source_id,
                    "metric_name": key,
                    "metric_value": str(value),
                }
            )
    return rows


def compute_skill_mention_quality_metrics(
    source_records_processed: int,
    total_mentions: int,
    persisted_mentions: list,
    already_ingested_count: int = 0,
    records_with_no_mentions=None,
) -> dict:
    """
    persisted_mentions: list of {"mapping_status": "mapped"|"unmapped",
    "method": str, "normalized_text": str, ...} for mentions actually written
    this run (post-dedup). Mirrors compute_job_posting_quality_metrics'
    shape/spirit for the skill extraction phase: every number here is counted
    from what was actually processed, never hardcoded.
    """
    unique_normalized = {m["normalized_text"] for m in persisted_mentions}
    mapped = [m for m in persisted_mentions if m.get("mapping_status") == "mapped"]
    unmapped = [m for m in persisted_mentions if m.get("mapping_status") == "unmapped"]

    method_counts = {}
    for m in persisted_mentions:
        method_counts[m["method"]] = method_counts.get(m["method"], 0) + 1

    mapping_rate = round(len(mapped) / len(persisted_mentions), 4) if persisted_mentions else None

    return {
        "source_records_processed": source_records_processed,
        "total_mentions_found": total_mentions,
        "unique_normalized_mentions": len(unique_normalized),
        "mentions_persisted": len(persisted_mentions),
        "mapped_to_esco": len(mapped),
        "unmapped": len(unmapped),
        "mapping_rate": mapping_rate,
        "already_ingested_records": already_ingested_count,
        "duplicate_mentions_removed": max(total_mentions - len(persisted_mentions) - already_ingested_count, 0),
        "records_with_no_mentions": records_with_no_mentions,
        "extraction_method_counts": method_counts,
    }


def compute_industry_analysis_quality_metrics(
    eligible_job_postings: int,
    postings_with_extracted_skills: int,
    unique_canonical_skills: int,
    mapped_mentions_count: int,
    unmapped_mentions_count: int,
) -> dict:
    """Section 11 INDUSTRY block. Every count here is expected to come from an
    actual query result, never a hardcoded/estimated number."""
    return {
        "eligible_job_postings": eligible_job_postings,
        "postings_with_extracted_skills": postings_with_extracted_skills,
        "postings_without_extracted_skills": max(eligible_job_postings - postings_with_extracted_skills, 0),
        "unique_canonical_skills_in_postings": unique_canonical_skills,
        "mapped_mentions": mapped_mentions_count,
        "unmapped_mentions": unmapped_mentions_count,
    }


def compute_curriculum_analysis_quality_metrics(
    eligible_courses: int,
    courses_with_extracted_skills: int,
    unique_canonical_skills: int,
) -> dict:
    """Section 11 CURRICULUM block."""
    return {
        "eligible_courses": eligible_courses,
        "courses_with_extracted_skills": courses_with_extracted_skills,
        "courses_without_extracted_skills": max(eligible_courses - courses_with_extracted_skills, 0),
        "unique_canonical_skills_in_curriculum": unique_canonical_skills,
    }


def compute_cross_coverage_quality_metrics(industry_skill_ids: set, curriculum_skill_ids: set) -> dict:
    """Section 11 ANALYSIS block -- reuses the same set logic as
    skill_set_alignment.compute_skill_set_alignment but reported as explicit
    quality-metric counts rather than an alignment score."""
    both = industry_skill_ids & curriculum_skill_ids
    industry_only = industry_skill_ids - curriculum_skill_ids
    curriculum_only = curriculum_skill_ids - industry_skill_ids
    return {
        "skills_with_industry_evidence": len(industry_skill_ids),
        "skills_with_curriculum_evidence": len(curriculum_skill_ids),
        "skills_in_both": len(both),
        "skills_industry_only": len(industry_only),
        "skills_curriculum_only": len(curriculum_only),
    }


def compute_temporal_industry_quality_metrics(
    total_postings: int,
    dated_postings: int,
    postings_per_period: dict,
    skills_with_sufficient_evidence: int,
    skills_with_insufficient_evidence: int,
) -> dict:
    """Section 17 INDUSTRY (temporal) block."""
    return {
        "total_postings": total_postings,
        "dated_postings": dated_postings,
        "undated_postings": max(total_postings - dated_postings, 0),
        "periods_observed": len(postings_per_period),
        "postings_per_period": postings_per_period,
        "skills_with_sufficient_evidence": skills_with_sufficient_evidence,
        "skills_with_insufficient_evidence": skills_with_insufficient_evidence,
    }


def compute_temporal_curriculum_quality_metrics(
    curriculum_versions: int,
    comparable_version_pairs: int,
    courses_per_version: dict,
    versions_with_missing_temporal_metadata: int,
) -> dict:
    """Section 17 CURRICULUM (temporal) block."""
    return {
        "curriculum_versions": curriculum_versions,
        "comparable_version_pairs": comparable_version_pairs,
        "courses_per_version": courses_per_version,
        "versions_with_missing_temporal_metadata": versions_with_missing_temporal_metadata,
    }


def compute_drift_quality_metrics(drift_results: list) -> dict:
    """
    Section 17 DRIFT block. drift_results: list of {"status": str, ...} as
    produced by app.analytics.curriculum_drift.compare_curriculum_versions.
    """
    counts = {}
    for r in drift_results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "added_skills": counts.get("SKILL_ADDED", 0),
        "removed_skills": counts.get("SKILL_REMOVED", 0),
        "increased_coverage": counts.get("COVERAGE_INCREASED", 0),
        "decreased_coverage": counts.get("COVERAGE_DECREASED", 0),
        "unchanged": counts.get("UNCHANGED", 0),
        "insufficient_evidence": counts.get("INSUFFICIENT_DATA", 0),
    }


def compute_recommendation_quality_metrics(recommendation_records: list) -> dict:
    """
    Section 16. recommendation_records: list of dicts as returned by
    generate_recommendation. Every count here is a direct filter over the
    underlying records -- no percentages are reported when a denominator
    would be misleading (e.g. no "success rate" against a fabricated total).
    """
    total = len(recommendation_records)
    by_state = {}
    by_action = {}
    by_target_level = {}
    with_complete_provenance = 0

    for r in recommendation_records:
        state = r.get("recommendation_state")
        by_state[state] = by_state.get(state, 0) + 1

        action = r.get("action_type")
        if action:
            by_action[action] = by_action.get(action, 0) + 1

        level = r.get("target_level")
        if level:
            by_target_level[level] = by_target_level.get(level, 0) + 1

        if r.get("source_demand_run_id") and r.get("source_coverage_run_id"):
            with_complete_provenance += 1

    return {
        "total_candidate_gaps": total,
        "recommendation_supported_count": by_state.get("RECOMMENDATION_SUPPORTED", 0),
        "insufficient_evidence_count": by_state.get("INSUFFICIENT_EVIDENCE", 0),
        "no_action_indicated_count": by_state.get("NO_ACTION_INDICATED", 0),
        "recommendations_by_action_type": by_action,
        "recommendations_by_target_level": by_target_level,
        "recommendations_with_complete_provenance": with_complete_provenance,
    }


def compute_core_knowledge_quality_metrics(
    domains: list, topics: list, subtopics: list, skill_mappings: list, curriculum_mappings: list
) -> dict:
    """
    Section 7 of the core-knowledge phase. Each input is a list of plain
    dicts (e.g. {"id":, "source_id":, "is_active":, "confidence":}) -- the
    DB orchestration is responsible for building these from real rows;
    this function never queries anything itself. NULL confidence is
    reported as "unassessed", never silently treated as zero or as a
    passing/failing score.
    """
    def _provenance_counts(rows):
        with_prov = sum(1 for r in rows if r.get("source_id") is not None)
        return with_prov, len(rows) - with_prov

    def _active_counts(rows):
        active = sum(1 for r in rows if r.get("is_active", 1) == 1)
        return active, len(rows) - active

    domains_with_prov, domains_missing_prov = _provenance_counts(domains)
    topics_with_prov, topics_missing_prov = _provenance_counts(topics)
    subtopics_with_prov, subtopics_missing_prov = _provenance_counts(subtopics)

    active_domains, inactive_domains = _active_counts(domains)
    active_topics, inactive_topics = _active_counts(topics)
    active_subtopics, inactive_subtopics = _active_counts(subtopics)

    mappings_with_confidence = sum(1 for m in skill_mappings if m.get("confidence") is not None)
    mappings_without_confidence = len(skill_mappings) - mappings_with_confidence

    return {
        "total_domains": len(domains),
        "domains_with_provenance": domains_with_prov,
        "domains_missing_provenance": domains_missing_prov,
        "active_domains": active_domains,
        "inactive_domains": inactive_domains,
        "total_topics": len(topics),
        "topics_with_provenance": topics_with_prov,
        "topics_missing_provenance": topics_missing_prov,
        "active_topics": active_topics,
        "inactive_topics": inactive_topics,
        "total_subtopics": len(subtopics),
        "subtopics_with_provenance": subtopics_with_prov,
        "subtopics_missing_provenance": subtopics_missing_prov,
        "active_subtopics": active_subtopics,
        "inactive_subtopics": inactive_subtopics,
        "total_skill_mappings": len(skill_mappings),
        "skill_mappings_with_confidence": mappings_with_confidence,
        "skill_mappings_unassessed": mappings_without_confidence,
        "total_curriculum_topic_mappings": len(curriculum_mappings),
    }


def compute_curriculum_ingestion_quality_gates(structure_summary: dict) -> dict:
    """
    Pre-GOLD quality gates for one curriculum ingestion (spec: "a badly
    parsed PDF must not silently become a valid curriculum"). Pure --
    operates on plain counts/lists the caller extracts from a
    CurriculumStructure (app.pipelines.preprocessing.curriculum_structuring),
    never on the DB or the PDF itself.

    structure_summary: {
        "course_count": int, "topic_count": int, "outcome_count": int,
        "page_count": int,
        "course_codes": [str, ...],          # as extracted, may contain duplicates
        "courses_with_zero_topics": [str, ...],  # course_codes
        "empty_topic_texts": int,             # topics whose text was blank after cleaning
        "malformed_course_codes": [str, ...], # codes that don't match the expected pattern
        "has_semester_info": bool,
        "expected_outcomes": bool,            # True if an outcomes label was ever seen
    }

    Returns explicit quality states, never silently passing a bad parse:
    each check is either PASS, WARN, or FAIL, plus a human-readable reason.
    "Reasonable" thresholds below are documented DEFAULTS, not calibrated
    against real curricula (none exist in this repo yet) -- see
    docs/curriculum_normalization_methodology.md.
    """
    checks = {}

    course_count = structure_summary.get("course_count", 0)
    if course_count == 0:
        checks["course_count"] = ("FAIL", "No courses were extracted at all.")
    elif course_count < 3:
        checks["course_count"] = ("WARN", f"Only {course_count} course(s) extracted -- unusually low for a full programme curriculum.")
    else:
        checks["course_count"] = ("PASS", f"{course_count} courses extracted.")

    topic_count = structure_summary.get("topic_count", 0)
    if topic_count == 0:
        checks["topic_count"] = ("FAIL", "No topics were extracted at all.")
    elif course_count and topic_count < course_count:
        checks["topic_count"] = ("WARN", f"Fewer topics ({topic_count}) than courses ({course_count}) -- most courses likely have no extracted content.")
    else:
        checks["topic_count"] = ("PASS", f"{topic_count} topics extracted.")

    codes = structure_summary.get("course_codes", [])
    duplicate_codes = sorted({c for c in codes if codes.count(c) > 1})
    checks["duplicate_courses"] = (
        ("WARN", f"Duplicate course codes found: {duplicate_codes}") if duplicate_codes
        else ("PASS", "No duplicate course codes.")
    )

    empty_courses = structure_summary.get("courses_with_zero_topics", [])
    checks["empty_courses"] = (
        ("WARN", f"{len(empty_courses)} course(s) have zero extracted topics: {empty_courses}") if empty_courses
        else ("PASS", "Every course has at least one extracted topic.")
    )

    empty_topics = structure_summary.get("empty_topic_texts", 0)
    checks["empty_topics"] = (
        ("WARN", f"{empty_topics} topic entries were blank after cleaning.") if empty_topics
        else ("PASS", "No blank topic entries.")
    )

    malformed = structure_summary.get("malformed_course_codes", [])
    checks["malformed_course_codes"] = (
        ("WARN", f"{len(malformed)} course code(s) did not match the expected pattern: {malformed}") if malformed
        else ("PASS", "All course codes matched the expected pattern.")
    )

    checks["semester_information"] = (
        ("PASS", "Semester/term information present.") if structure_summary.get("has_semester_info")
        else ("WARN", "No semester/term information was found.")
    )

    outcome_count = structure_summary.get("outcome_count", 0)
    if structure_summary.get("expected_outcomes") and outcome_count == 0:
        checks["learning_outcomes"] = ("WARN", "An outcomes section heading was found but no individual outcomes were extracted.")
    else:
        checks["learning_outcomes"] = ("PASS", f"{outcome_count} learning outcome(s) extracted.")

    page_count = structure_summary.get("page_count", 0)
    if page_count and (topic_count + course_count) / page_count < 0.2:
        checks["extraction_volume"] = ("WARN", f"Suspiciously low extraction volume: {topic_count + course_count} structural entities across {page_count} pages -- possible OCR/extraction failure.")
    else:
        checks["extraction_volume"] = ("PASS", "Extraction volume is within the expected range for the page count.")

    fail_count = sum(1 for state, _ in checks.values() if state == "FAIL")
    warn_count = sum(1 for state, _ in checks.values() if state == "WARN")
    overall = "FAIL" if fail_count else ("WARN" if warn_count else "PASS")

    return {"overall": overall, "fail_count": fail_count, "warn_count": warn_count, "checks": checks}
