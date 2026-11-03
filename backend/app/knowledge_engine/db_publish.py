"""
PUBLISH: load a GOLD run into PostgreSQL through the `psql` client.

Why psql and not SQLAlchemy: SQLAlchemy and every Python PostgreSQL driver are
unavailable in this environment (package index blocked by egress policy),
but the PostgreSQL server and its `psql` client are installed. The load is
therefore plain SQL: CSVs are \\copy-ed into temporary staging tables and
inserted with ON CONFLICT DO NOTHING ... RETURNING, so the report shows
exactly how many rows each run inserted (a rerun of an identical run must
insert 0). Integrity is then verified with SQL queries against the loaded
data -- the database, not the pipeline, confirms the invariants.

Connection: pass dsn="postgresql://..." for any server; with dsn=None and
local=True the local cluster is used via `su postgres`.
"""
import json
import os
import shlex
import subprocess
from pathlib import Path

from app.knowledge_engine.exports import write_csv

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "knowledge_schema.sql"
IMPROVEMENT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "knowledge_schema_improvement.sql"
CONSISTENCY_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "knowledge_schema_consistency.sql"

TABLES = [
    ("pipeline_run", ["run_id", "pipeline_version", "config_hash", "semantic_backend", "content_digest"]),
    ("document", ["sha256", "doc_id", "role", "institution", "programme", "discipline", "curriculum_version", "page_count"]),
    ("course", ["course_uid", "doc_sha256", "course_code", "title", "title_raw", "semester", "first_page", "title_page",
                "occurrences", "evidence_status"]),
    ("unit", ["unit_uid", "course_uid", "label", "title", "page_number"]),
    ("topic", ["topic_uid", "course_uid", "unit_label", "raw_text", "clean_text", "page_number", "extraction_method",
               "noise_label", "evidence_status"]),
    ("concept_family", ["family_uid", "discipline", "name", "evidence_status"]),
    ("concept", ["concept_uid", "family_uid", "discipline", "name", "support", "evidence_status", "review_priority"]),
    ("concept_member", ["concept_uid", "topic_uid"]),
    ("concept_run", ["run_id", "concept_uid"]),
    ("edge", ["edge_uid", "source_uid", "target_uid", "relationship", "method", "evidence_status"]),
    ("topic_mapping", ["mapping_uid", "source_topic_uid", "target_topic_uid", "relationship", "similarity_score",
                       "score_is_calibrated", "method", "evidence_status"]),
    ("concept_drift", ["run_id", "concept_uid", "status", "previous_support", "target_support"]),
    ("review_item", ["review_item_uid", "priority", "review_decision", "reviewer", "decided_at"]),
    ("population_scope", ["scope_uid", "run_id", "segment", "eligible_postings", "distinct_companies", "date_earliest",
                          "date_latest", "geographic_scope", "source_files", "representativeness_warning"]),
    ("job_posting", ["posting_uid", "identity", "platform", "external_id", "url", "source_id", "source_file", "source_sha256",
                     "row_number", "job_title", "company_name", "company_key", "location", "country_code", "posted_date",
                     "raw_description_sha256", "evidence_status"]),
    ("esco_concept", ["esco_uri", "pref_label", "taxonomy_scope"]),
    ("skill", ["skill_uid", "skill_key", "label", "esco_status", "esco_uri", "mapping_method", "skill_category",
               "taxonomy_candidate_uri"]),
    ("skill_mention", ["mention_uid", "posting_uid", "skill_uid", "raw_mention", "span_start", "span_end",
                       "extraction_method", "run_id", "mention_role", "sense_state"]),
    ("industry_demand", ["run_id", "scope_uid", "skill_uid", "posting_count", "eligible_postings", "posting_prevalence_pct",
                         "company_count", "eligible_companies", "company_prevalence_pct", "support_state"]),
    ("skill_gap", ["gap_uid", "run_id", "scope_uid", "skill_uid", "classification", "evidence_state", "industry_count",
                   "industry_population", "industry_prevalence_pct", "curriculum_count", "curriculum_population",
                   "curriculum_coverage_pct", "support_state"]),
    ("recommendation", ["recommendation_uid", "gap_uid", "run_id", "state", "action_type", "target_course_codes",
                        "evidence_status", "is_source_evidence"]),
    # engine 2.0 (additive)
    ("skill_run", ["run_id", "skill_uid", "esco_status", "esco_uri", "mapping_method", "skill_category", "taxonomy_candidate_uri"]),
    ("skill_mention_run", ["run_id", "mention_uid", "posting_uid", "skill_uid", "mention_role", "sense_state"]),
    ("esco_occupation", ["occupation_uri", "pref_label", "isco_code"]),
    ("posting_occupation", ["run_id", "posting_uid", "status", "established", "occupation_uri", "matched_label", "isco_major_code"]),
    ("topic_hierarchy", ["hierarchy_uid", "course_uid", "parent_node_uid", "parent_text", "child_text", "position",
                         "child_topic_uid", "method", "page_number"]),
    ("concept_coverage", ["run_id", "skill_uid", "doc_role", "coverage_level", "coverage_relation", "courses_direct_or_partial",
                          "units_direct_or_partial", "outcome_mentions", "level_reason"]),
    ("skill_gap_v2", ["gap_uid", "run_id", "classification_v1", "classification_v2", "coverage_level", "industry_trend",
                      "reason_v2", "is_source_evidence"]),
    ("semantic_model_run", ["run_id", "provider_status", "provider", "model", "prompt_version", "candidates", "cache_hits"]),
    ("semantic_decision", ["run_id", "decision_id", "candidate_kind", "source_entity", "candidate_entity", "left_text", "right_text",
                           "relationship", "decision_state", "provider", "model", "prompt_version", "input_hash",
                           "context_hash", "output_hash", "is_human_validated", "validated_state",
                           "validation_findings", "effect"]),
    ("concept_relationship", ["edge_id", "run_id", "source", "relationship", "target", "method", "evidence_status",
                              "mapping_kind"]),
    ("semantic_contradiction", ["run_id", "source", "target", "kind", "relationships"]),
    # intelligence improvement release (additive)
    ("peer_comparison", ["run_id", "comparison_doc_sha256", "comparison_role", "peer_status", "exact_lexical_pct",
                         "normalized_pct", "semantic_concept_pct", "semantic_related_pct", "target_concepts",
                         "comparison_concepts", "course_context_min"]),
    ("peer_relation", ["relation_uid", "run_id", "comparison_doc_sha256", "target_concept_uid", "comparison_unit_uid",
                       "target_concept", "comparison_concept", "relationship", "evidence_state", "similarity",
                       "course_context", "model_consulted"]),
    ("temporal_population", ["run_id", "population_id", "eligible_postings", "granularity", "trend_status", "date_earliest",
                             "date_latest"]),
    ("skill_trend", ["run_id", "population_id", "segment", "skill_uid", "trend_state", "periods", "pp_change",
                     "relative_change", "total_postings"]),
    ("occupation_resolution", ["run_id", "posting_uid", "state", "established", "established_by", "occupation_uri",
                               "context_support", "posting_context_skills"]),
]

_INTEGRITY_TEMPLATE = """
SELECT json_build_object(
 'edges_with_unknown_endpoints', (SELECT count(*) FROM knowledge.edge e WHERE
     e.source_uid NOT IN (SELECT concept_uid FROM knowledge.concept UNION ALL SELECT family_uid FROM knowledge.concept_family UNION ALL SELECT course_uid FROM knowledge.course)
  OR e.target_uid NOT IN (SELECT concept_uid FROM knowledge.concept UNION ALL SELECT family_uid FROM knowledge.concept_family UNION ALL SELECT course_uid FROM knowledge.course)),
 'topics_without_page', (SELECT count(*) FROM knowledge.topic WHERE page_number IS NULL),
 'concepts_without_members', (SELECT count(*) FROM knowledge.concept c WHERE NOT EXISTS (SELECT 1 FROM knowledge.concept_member m WHERE m.concept_uid = c.concept_uid)),
 'concept_support_mismatch', (SELECT count(*) FROM knowledge.concept c WHERE c.support <> (SELECT count(*) FROM knowledge.concept_member m WHERE m.concept_uid = c.concept_uid)),
 'mapped_to_non_reference_topic', (SELECT count(*) FROM knowledge.topic_mapping tm JOIN knowledge.topic t ON t.topic_uid = tm.target_topic_uid
      JOIN knowledge.course c ON c.course_uid = t.course_uid JOIN knowledge.document d ON d.sha256 = c.doc_sha256 WHERE d.role <> 'REFERENCE'),
 'mapping_source_not_target_role', (SELECT count(*) FROM knowledge.topic_mapping tm JOIN knowledge.topic t ON t.topic_uid = tm.source_topic_uid
      JOIN knowledge.course c ON c.course_uid = t.course_uid JOIN knowledge.document d ON d.sha256 = c.doc_sha256 WHERE d.role <> 'TARGET'),
 'calibrated_scores_claimed', (SELECT count(*) FROM knowledge.topic_mapping WHERE score_is_calibrated),
 'human_validated_without_decision', (SELECT count(*) FROM knowledge.concept c LEFT JOIN knowledge.review_item r ON r.review_item_uid = c.concept_uid
      WHERE c.evidence_status = 'HUMAN_VALIDATED' AND r.review_decision IS NULL),
 'duplicate_postings_by_url', (SELECT count(*) FROM (SELECT url FROM knowledge.job_posting GROUP BY url HAVING count(*) > 1) x),
 'duplicate_skill_labels_per_key', (SELECT count(*) FROM (SELECT skill_key FROM knowledge.skill GROUP BY skill_key HAVING count(*) > 1) x),
 'mentions_without_posting', (SELECT count(*) FROM knowledge.skill_mention m WHERE NOT EXISTS (SELECT 1 FROM knowledge.job_posting p WHERE p.posting_uid = m.posting_uid)),
 'demand_count_mismatch', (SELECT count(*) FROM knowledge.industry_demand d WHERE d.posting_count >
      (SELECT count(DISTINCT m.posting_uid) FROM (SELECT m.posting_uid, m.skill_uid, m.run_id, m.mention_role, m.sense_state FROM knowledge.skill_mention_run m
        UNION ALL SELECT m.posting_uid, m.skill_uid, d2.run_id, m.mention_role, m.sense_state FROM knowledge.skill_mention m
        CROSS JOIN (SELECT DISTINCT run_id FROM knowledge.industry_demand) d2
        WHERE NOT EXISTS (SELECT 1 FROM knowledge.skill_mention_run r WHERE r.run_id = d2.run_id)) m WHERE m.skill_uid = d.skill_uid AND m.run_id = d.run_id)),
 'demand_without_scope_warning', (SELECT count(*) FROM knowledge.industry_demand d JOIN knowledge.population_scope s USING (scope_uid)
      WHERE s.representativeness_warning IS NULL OR s.representativeness_warning = ''),
 'demand_exceeds_established_mentions', (SELECT count(*) FROM knowledge.industry_demand d WHERE d.posting_count >
      (SELECT count(DISTINCT m.posting_uid) FROM (SELECT m.posting_uid, m.skill_uid, m.run_id, m.mention_role, m.sense_state FROM knowledge.skill_mention_run m
        UNION ALL SELECT m.posting_uid, m.skill_uid, d2.run_id, m.mention_role, m.sense_state FROM knowledge.skill_mention m
        CROSS JOIN (SELECT DISTINCT run_id FROM knowledge.industry_demand) d2
        WHERE NOT EXISTS (SELECT 1 FROM knowledge.skill_mention_run r WHERE r.run_id = d2.run_id)) m WHERE m.skill_uid = d.skill_uid AND m.run_id = d.run_id
       AND m.mention_role = 'SKILL' AND m.sense_state IN ('ESTABLISHED','ESTABLISHED_BY_CONTEXT','ESTABLISHED_BY_MODEL'))),
 'demand_for_alias_review_skills', (SELECT count(*) FROM knowledge.industry_demand d JOIN knowledge.skill_run s USING (run_id, skill_uid)
      WHERE s.esco_status = 'ALIAS_SENSE_REVIEW_REQUIRED'),
 'recommendations_without_gap', (SELECT count(*) FROM knowledge.recommendation r WHERE NOT EXISTS (SELECT 1 FROM knowledge.skill_gap g WHERE g.gap_uid = r.gap_uid)),
 'recommendations_on_insufficient_gap', (SELECT count(*) FROM knowledge.recommendation r JOIN knowledge.skill_gap g USING (gap_uid)
      WHERE r.state = 'RECOMMENDATION_SUPPORTED' AND g.classification = 'INSUFFICIENT_EVIDENCE'),
 'recommendations_marked_as_source_evidence', (SELECT count(*) FROM knowledge.recommendation WHERE is_source_evidence),
 'mapped_skill_without_esco_concept', (SELECT count(*) FROM knowledge.skill s WHERE s.esco_status IN ('EXACT','NORMALIZED','SEMANTIC_MATCH')
      AND NOT EXISTS (SELECT 1 FROM knowledge.esco_concept e WHERE e.esco_uri = s.esco_uri)),
 'semantic_decisions_claiming_human_validation', (SELECT count(*) FROM knowledge.semantic_decision WHERE is_human_validated),
 'model_decisions_without_provider', (SELECT count(*) FROM knowledge.semantic_decision d JOIN knowledge.semantic_model_run r USING (run_id)
      WHERE d.decision_state = 'MODEL_SUGGESTED' AND r.provider_status = 'AI_PROVIDER_UNAVAILABLE'),
 'model_effect_without_validated_support', (SELECT count(*) FROM knowledge.semantic_decision
      WHERE effect IS NOT NULL AND validated_state IS DISTINCT FROM 'MODEL_SUPPORTED'),
 'model_established_mention_without_decision', (SELECT count(*) FROM knowledge.skill_mention_run m
      WHERE m.sense_state = 'ESTABLISHED_BY_MODEL' AND NOT EXISTS (SELECT 1 FROM knowledge.semantic_decision d
        WHERE d.run_id = m.run_id AND d.source_entity = m.mention_uid AND d.effect = 'ESTABLISHED_BY_MODEL')),
 'graph_self_edges', (SELECT count(*) FROM knowledge.concept_relationship WHERE source = target),
 'graph_invalid_relationship', (SELECT count(*) FROM knowledge.concept_relationship WHERE relationship NOT IN
      ('PARENT_OF','CHILD_OF','RELATED_TO','SAME_AS','MAPS_TO','CONTAINS','MENTIONS','DEMANDED_BY','APPEARS_IN','PREREQUISITE_OF')),
 'graph_edges_without_method', (SELECT count(*) FROM knowledge.concept_relationship WHERE coalesce(method, '') = ''),
 'recommendation_below_support_threshold', (SELECT count(*) FROM knowledge.recommendation r JOIN knowledge.skill_gap g USING (gap_uid)
      WHERE r.state = 'RECOMMENDATION_SUPPORTED' AND g.support_state NOT IN ('SUPPORTED','HIGH_SUPPORT')),
 'graph_self_parent', (SELECT count(*) FROM knowledge.concept_relationship WHERE source = target AND relationship IN ('PARENT_OF','CHILD_OF','PREREQUISITE_OF')),
 'graph_duplicate_edges', (SELECT count(*) FROM (SELECT source, relationship, target, run_id FROM knowledge.concept_relationship
      GROUP BY 1,2,3,4 HAVING count(*) > 1) x),
 'established_occupation_without_uri', (SELECT count(*) FROM knowledge.posting_occupation WHERE established AND occupation_uri IS NULL),
{improvement_checks} 'row_counts', (SELECT json_object_agg(t, n) FROM (
     SELECT 'document' t, count(*) n FROM knowledge.document UNION ALL SELECT 'course', count(*) FROM knowledge.course
     UNION ALL SELECT 'unit', count(*) FROM knowledge.unit UNION ALL SELECT 'topic', count(*) FROM knowledge.topic
     UNION ALL SELECT 'concept_family', count(*) FROM knowledge.concept_family UNION ALL SELECT 'concept', count(*) FROM knowledge.concept
     UNION ALL SELECT 'concept_member', count(*) FROM knowledge.concept_member UNION ALL SELECT 'edge', count(*) FROM knowledge.edge
     UNION ALL SELECT 'topic_mapping', count(*) FROM knowledge.topic_mapping UNION ALL SELECT 'concept_drift', count(*) FROM knowledge.concept_drift
     UNION ALL SELECT 'review_item', count(*) FROM knowledge.review_item UNION ALL SELECT 'pipeline_run', count(*) FROM knowledge.pipeline_run
     UNION ALL SELECT 'population_scope', count(*) FROM knowledge.population_scope UNION ALL SELECT 'job_posting', count(*) FROM knowledge.job_posting
     UNION ALL SELECT 'esco_concept', count(*) FROM knowledge.esco_concept UNION ALL SELECT 'skill', count(*) FROM knowledge.skill
     UNION ALL SELECT 'skill_mention', count(*) FROM knowledge.skill_mention UNION ALL SELECT 'industry_demand', count(*) FROM knowledge.industry_demand
     UNION ALL SELECT 'skill_gap', count(*) FROM knowledge.skill_gap UNION ALL SELECT 'recommendation', count(*) FROM knowledge.recommendation
     UNION ALL SELECT 'esco_occupation', count(*) FROM knowledge.esco_occupation UNION ALL SELECT 'posting_occupation', count(*) FROM knowledge.posting_occupation
     UNION ALL SELECT 'topic_hierarchy', count(*) FROM knowledge.topic_hierarchy UNION ALL SELECT 'concept_coverage', count(*) FROM knowledge.concept_coverage
     UNION ALL SELECT 'skill_gap_v2', count(*) FROM knowledge.skill_gap_v2 UNION ALL SELECT 'semantic_model_run', count(*) FROM knowledge.semantic_model_run
     UNION ALL SELECT 'semantic_decision', count(*) FROM knowledge.semantic_decision UNION ALL SELECT 'concept_relationship', count(*) FROM knowledge.concept_relationship
     UNION ALL SELECT 'semantic_contradiction', count(*) FROM knowledge.semantic_contradiction
     UNION ALL SELECT 'skill_run', count(*) FROM knowledge.skill_run UNION ALL SELECT 'skill_mention_run', count(*) FROM knowledge.skill_mention_run
{improvement_counts}) s)
);
"""


# Checks and row counts of the improvement schema (knowledge_schema_improvement.sql / migration 0003). A database
# published before that schema existed has none of these tables; verifying it uses the base checks only.
_IMPROVEMENT_CHECKS = """ 'peer_supported_without_context', (SELECT count(*) FROM knowledge.peer_relation r JOIN knowledge.peer_comparison c
      ON c.run_id = r.run_id AND c.comparison_doc_sha256 = r.comparison_doc_sha256
      WHERE r.evidence_state = 'SUPPORTED' AND r.course_context < c.course_context_min),
 'peer_relation_on_non_comparison_document', (SELECT count(*) FROM knowledge.peer_relation r JOIN knowledge.document d
      ON d.sha256 = r.comparison_doc_sha256 WHERE d.role NOT IN ('PEER','REFERENCE')),
 'trend_classified_without_temporal_evidence', (SELECT count(*) FROM knowledge.skill_trend t JOIN knowledge.temporal_population p
      ON p.run_id = t.run_id AND p.population_id = t.population_id
      WHERE t.trend_state <> 'INSUFFICIENT_DATA' AND p.trend_status <> 'COMPUTED'),
 'peer_topics_in_target_analytics', (SELECT count(*) FROM knowledge.topic t JOIN knowledge.course c ON c.course_uid = t.course_uid
      JOIN knowledge.document d ON d.sha256 = c.doc_sha256 WHERE d.role = 'PEER'),
"""
_IMPROVEMENT_COUNTS = """     UNION ALL SELECT 'peer_comparison', count(*) FROM knowledge.peer_comparison UNION ALL SELECT 'peer_relation', count(*) FROM knowledge.peer_relation
     UNION ALL SELECT 'temporal_population', count(*) FROM knowledge.temporal_population UNION ALL SELECT 'skill_trend', count(*) FROM knowledge.skill_trend
     UNION ALL SELECT 'occupation_resolution', count(*) FROM knowledge.occupation_resolution"""
IMPROVEMENT_PROBE_SQL = "SELECT to_json(to_regclass('knowledge.peer_relation') IS NOT NULL)"


def integrity_sql(improvement_schema=True):
    """The integrity query; improvement_schema=False for a database published before migration 0003."""
    return _INTEGRITY_TEMPLATE.replace("{improvement_checks}", _IMPROVEMENT_CHECKS if improvement_schema else "") \
        .replace("{improvement_counts}", _IMPROVEMENT_COUNTS if improvement_schema else "")


INTEGRITY_SQL = integrity_sql(True)


def _psql(args_sql_file, dsn, local, database):
    if dsn:
        cmd = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-q", "-tA", "-f", str(args_sql_file)]
    elif local:
        cmd = ["su", "postgres", "-c",
               f"psql -v ON_ERROR_STOP=1 -q -tA -d {shlex.quote(database)} -f {shlex.quote(str(args_sql_file))}"]
    else:
        raise ValueError("publish needs a dsn or local=True")
    return subprocess.run(cmd, capture_output=True, text=True)


def ensure_local_database(database):
    probe = subprocess.run(["su", "postgres", "-c", f"psql -tAc \"SELECT 1 FROM pg_database WHERE datname='{database}'\""],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        raise RuntimeError(f"PostgreSQL not reachable: {probe.stderr.strip()}")
    if probe.stdout.strip() != "1":
        subprocess.run(["su", "postgres", "-c", f"createdb {shlex.quote(database)}"], check=True, capture_output=True)


def publish(bundle, work_dir, dsn=None, local=True, database="skillgap_knowledge"):
    """bundle: {table_name: [row dicts with the TABLES columns]}. Returns a report dict."""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    os.chmod(work, 0o755)
    if dsn is None and local:
        ensure_local_database(database)
    lines = [SCHEMA_PATH.read_text(encoding="utf-8"), IMPROVEMENT_SCHEMA_PATH.read_text(encoding="utf-8"),
             CONSISTENCY_SCHEMA_PATH.read_text(encoding="utf-8"), "BEGIN;"]
    for table, cols in TABLES:
        csv_path = write_csv(work / f"{table}.csv", bundle.get(table, []), cols, null_marker="\\N")
        os.chmod(csv_path, 0o644)
        col_list = ", ".join(cols)
        lines.append(f"CREATE TEMP TABLE stg_{table} AS SELECT {col_list} FROM knowledge.{table} WITH NO DATA;")
        lines.append(f"\\copy stg_{table} ({col_list}) FROM '{csv_path}' WITH (FORMAT csv, HEADER true, NULL '\\N')")
        lines.append(f"WITH ins AS (INSERT INTO knowledge.{table} ({col_list}) SELECT {col_list} FROM stg_{table} "
                     f"ON CONFLICT DO NOTHING RETURNING 1) SELECT 'INSERTED {table} ' || count(*) FROM ins;")
    lines.append("COMMIT;")
    lines.append("SELECT 'INTEGRITY ' || (" + INTEGRITY_SQL.strip().rstrip(";") + ")::text;")
    script = work / "publish.sql"
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(script, 0o644)
    result = _psql(script, dsn, local, database)
    report = {"database": database if dsn is None else "dsn", "returncode": result.returncode,
              "inserted": {}, "integrity": None,
              "errors": "\n".join(l for l in result.stderr.splitlines() if "NOTICE:" not in l).strip()[-2000:] or None}
    for line in result.stdout.splitlines():
        if line.startswith("INSERTED "):
            _, table, n = line.split(" ")
            report["inserted"][table] = int(n)
        elif line.startswith("INTEGRITY "):
            report["integrity"] = json.loads(line[len("INTEGRITY "):])
    violations = {k: v for k, v in (report["integrity"] or {}).items() if k != "row_counts" and v}
    report["status"] = "PASS" if result.returncode == 0 and report["integrity"] is not None and not violations else "FAIL"
    report["integrity_violations"] = violations
    return report
