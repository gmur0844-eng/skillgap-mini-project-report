-- Knowledge-engine GOLD schema (PostgreSQL). Idempotent: safe to run repeatedly.
-- The CHECK constraints mirror app/knowledge_engine/contracts.py so the database
-- independently enforces the same invariants the pipeline validates.
CREATE SCHEMA IF NOT EXISTS knowledge;

CREATE TABLE IF NOT EXISTS knowledge.pipeline_run (
  run_id text PRIMARY KEY, pipeline_version text NOT NULL, config_hash text NOT NULL CHECK (config_hash ~ '^[0-9a-f]{64}$'),
  semantic_backend text NOT NULL, content_digest text NOT NULL CHECK (content_digest ~ '^[0-9a-f]{64}$'),
  published_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS knowledge.document (
  sha256 text PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'), doc_id text NOT NULL UNIQUE,
  role text NOT NULL CHECK (role IN ('TARGET','PREVIOUS_VERSION','REFERENCE')),
  institution text NOT NULL, programme text NOT NULL, discipline text NOT NULL,
  curriculum_version text NOT NULL, page_count int NOT NULL CHECK (page_count > 0));

CREATE TABLE IF NOT EXISTS knowledge.course (
  course_uid text PRIMARY KEY, doc_sha256 text NOT NULL REFERENCES knowledge.document(sha256),
  course_code text NOT NULL, title text NOT NULL, title_raw text NOT NULL, semester text,
  first_page int NOT NULL CHECK (first_page > 0), title_page int NOT NULL CHECK (title_page > 0),
  occurrences int NOT NULL CHECK (occurrences >= 1), evidence_status text NOT NULL,
  UNIQUE (doc_sha256, course_code));

CREATE TABLE IF NOT EXISTS knowledge.unit (
  unit_uid text PRIMARY KEY, course_uid text NOT NULL REFERENCES knowledge.course(course_uid),
  label text NOT NULL, title text, page_number int NOT NULL CHECK (page_number > 0), UNIQUE (course_uid, label));

CREATE TABLE IF NOT EXISTS knowledge.topic (
  topic_uid text PRIMARY KEY, course_uid text NOT NULL REFERENCES knowledge.course(course_uid),
  unit_label text, raw_text text NOT NULL, clean_text text NOT NULL, page_number int NOT NULL CHECK (page_number > 0),
  extraction_method text NOT NULL, noise_label text NOT NULL,
  evidence_status text NOT NULL CHECK (evidence_status IN ('EXTRACTED','NORMALIZED','DISCOVERED','MODEL_SUGGESTED',
     'REFERENCE_MAPPED','HUMAN_VALIDATED','INSUFFICIENT_EVIDENCE','REVIEW_REQUIRED')));

CREATE TABLE IF NOT EXISTS knowledge.concept_family (
  family_uid text PRIMARY KEY, discipline text NOT NULL, name text NOT NULL, evidence_status text NOT NULL);

CREATE TABLE IF NOT EXISTS knowledge.concept (
  concept_uid text PRIMARY KEY, family_uid text NOT NULL REFERENCES knowledge.concept_family(family_uid),
  discipline text NOT NULL, name text NOT NULL, support int NOT NULL CHECK (support >= 1),
  evidence_status text NOT NULL CHECK (evidence_status IN ('DISCOVERED','HUMAN_VALIDATED')),
  review_priority text NOT NULL CHECK (review_priority IN ('HIGH','MEDIUM','LOW')));

CREATE TABLE IF NOT EXISTS knowledge.concept_member (
  concept_uid text NOT NULL REFERENCES knowledge.concept(concept_uid),
  topic_uid text NOT NULL REFERENCES knowledge.topic(topic_uid), PRIMARY KEY (concept_uid, topic_uid));

CREATE TABLE IF NOT EXISTS knowledge.concept_run (
  run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  concept_uid text NOT NULL REFERENCES knowledge.concept(concept_uid), PRIMARY KEY (run_id, concept_uid));

CREATE TABLE IF NOT EXISTS knowledge.edge (
  edge_uid text PRIMARY KEY, source_uid text NOT NULL, target_uid text NOT NULL,
  relationship text NOT NULL CHECK (relationship IN ('BELONGS_TO_FAMILY','PARENT','CO_OCCURS_IN_UNIT','PREREQUISITE_OF')),
  method text NOT NULL, evidence_status text NOT NULL);

CREATE TABLE IF NOT EXISTS knowledge.topic_mapping (
  mapping_uid text PRIMARY KEY, source_topic_uid text NOT NULL REFERENCES knowledge.topic(topic_uid),
  target_topic_uid text REFERENCES knowledge.topic(topic_uid),
  relationship text NOT NULL CHECK (relationship IN ('SAME_CONCEPT','RELATED','PARENT','CHILD','PARTIAL_OVERLAP',
     'AMBIGUOUS','INSUFFICIENT_EVIDENCE','NEW_DISCOVERED_UNMAPPED')),
  similarity_score double precision CHECK (similarity_score IS NULL OR (similarity_score >= 0 AND similarity_score <= 1)),
  score_is_calibrated boolean NOT NULL CHECK (score_is_calibrated = false),
  method text NOT NULL, evidence_status text NOT NULL,
  CHECK ((target_topic_uid IS NULL) = (relationship IN ('AMBIGUOUS','INSUFFICIENT_EVIDENCE','NEW_DISCOVERED_UNMAPPED'))));

CREATE TABLE IF NOT EXISTS knowledge.concept_drift (
  run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  concept_uid text NOT NULL REFERENCES knowledge.concept(concept_uid),
  status text NOT NULL CHECK (status IN ('ADDED','REMOVED','EXPANDED','REDUCED','RETAINED','RETAINED_REWORDED','UNCERTAIN')),
  previous_support int NOT NULL, target_support int NOT NULL, PRIMARY KEY (run_id, concept_uid));

CREATE TABLE IF NOT EXISTS knowledge.review_item (
  review_item_uid text PRIMARY KEY REFERENCES knowledge.concept(concept_uid),
  priority text NOT NULL CHECK (priority IN ('HIGH','MEDIUM','LOW')),
  review_decision text CHECK (review_decision IS NULL OR review_decision IN ('ACCEPT','REJECT','RENAME')),
  reviewer text, decided_at timestamptz);

-- ---------------------------------------------------------------- industry / ESCO layer
CREATE TABLE IF NOT EXISTS knowledge.population_scope (
  scope_uid text PRIMARY KEY, run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  segment text NOT NULL, eligible_postings int NOT NULL CHECK (eligible_postings >= 0),
  distinct_companies int NOT NULL, date_earliest date, date_latest date,
  geographic_scope jsonb NOT NULL, source_files jsonb NOT NULL,
  representativeness_warning text NOT NULL CHECK (length(representativeness_warning) > 0));

CREATE TABLE IF NOT EXISTS knowledge.job_posting (
  posting_uid text PRIMARY KEY, identity text NOT NULL UNIQUE, platform text NOT NULL, external_id text NOT NULL,
  url text NOT NULL, source_id text NOT NULL, source_file text NOT NULL,
  source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'), row_number int NOT NULL CHECK (row_number > 0),
  job_title text, company_name text, company_key text, location text, country_code text, posted_date date,
  raw_description_sha256 text NOT NULL, evidence_status text NOT NULL CHECK (evidence_status = 'EXTRACTED'),
  UNIQUE (source_sha256, row_number));

CREATE TABLE IF NOT EXISTS knowledge.esco_concept (
  esco_uri text PRIMARY KEY CHECK (esco_uri LIKE 'http://data.europa.eu/esco/skill/%'),
  pref_label text NOT NULL, taxonomy_scope text NOT NULL);

CREATE TABLE IF NOT EXISTS knowledge.skill (
  skill_uid text PRIMARY KEY, skill_key text NOT NULL UNIQUE, label text NOT NULL,
  esco_status text NOT NULL CHECK (esco_status IN ('EXACT','NORMALIZED','SEMANTIC_MATCH','AMBIGUOUS','UNMAPPED','INSUFFICIENT_EVIDENCE',
     'ALIAS_SENSE_REVIEW_REQUIRED')),
  esco_uri text REFERENCES knowledge.esco_concept(esco_uri), mapping_method text, skill_category text NOT NULL,
  CHECK ((esco_uri IS NOT NULL) = (esco_status IN ('EXACT','NORMALIZED','SEMANTIC_MATCH'))));

CREATE TABLE IF NOT EXISTS knowledge.skill_mention (
  mention_uid text PRIMARY KEY, posting_uid text NOT NULL REFERENCES knowledge.job_posting(posting_uid),
  skill_uid text NOT NULL REFERENCES knowledge.skill(skill_uid), raw_mention text NOT NULL,
  span_start int NOT NULL, span_end int NOT NULL CHECK (span_end > span_start), extraction_method text NOT NULL,
  run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id));

CREATE TABLE IF NOT EXISTS knowledge.industry_demand (
  run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  scope_uid text NOT NULL REFERENCES knowledge.population_scope(scope_uid),
  skill_uid text NOT NULL REFERENCES knowledge.skill(skill_uid),
  posting_count int NOT NULL CHECK (posting_count > 0), eligible_postings int NOT NULL CHECK (eligible_postings >= posting_count),
  posting_prevalence_pct double precision NOT NULL, company_count int NOT NULL, eligible_companies int NOT NULL,
  company_prevalence_pct double precision,
  support_state text NOT NULL CHECK (support_state IN ('INSUFFICIENT_EVIDENCE','OBSERVED','SUPPORTED','HIGH_SUPPORT')),
  PRIMARY KEY (run_id, scope_uid, skill_uid));

CREATE TABLE IF NOT EXISTS knowledge.skill_gap (
  gap_uid text PRIMARY KEY, run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  scope_uid text NOT NULL REFERENCES knowledge.population_scope(scope_uid),
  skill_uid text NOT NULL REFERENCES knowledge.skill(skill_uid),
  classification text NOT NULL CHECK (classification IN ('MISSING','PARTIAL','COVERED','INSUFFICIENT_EVIDENCE')),
  evidence_state text NOT NULL, industry_count int NOT NULL, industry_population int NOT NULL,
  industry_prevalence_pct double precision, curriculum_count int NOT NULL, curriculum_population int NOT NULL,
  curriculum_coverage_pct double precision, support_state text NOT NULL, UNIQUE (run_id, scope_uid, skill_uid));

CREATE TABLE IF NOT EXISTS knowledge.recommendation (
  recommendation_uid text PRIMARY KEY, gap_uid text NOT NULL REFERENCES knowledge.skill_gap(gap_uid),
  run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  state text NOT NULL CHECK (state IN ('RECOMMENDATION_SUPPORTED','SUPPRESSED')),
  action_type text CHECK (action_type IS NULL OR action_type IN ('ADD_NEW_SUBJECT','ADD_ELECTIVE','ADD_MODULE',
     'UPDATE_EXISTING_TOPIC','EXPAND_EXISTING_TOPIC','REVIEW_EXISTING_COURSE')),
  target_course_codes jsonb NOT NULL, evidence_status text NOT NULL,
  is_source_evidence boolean NOT NULL CHECK (is_source_evidence = false),
  CHECK ((action_type IS NULL) = (state = 'SUPPRESSED')));

-- alias-sense validation (additive, idempotent): the taxonomy fact (label -> ESCO concept) is kept in
-- taxonomy_candidate_uri even when the text's meaning is not established (esco_uri stays NULL then)
ALTER TABLE knowledge.skill ADD COLUMN IF NOT EXISTS taxonomy_candidate_uri text REFERENCES knowledge.esco_concept(esco_uri);
ALTER TABLE knowledge.skill DROP CONSTRAINT IF EXISTS skill_esco_status_check;
ALTER TABLE knowledge.skill ADD CONSTRAINT skill_esco_status_check CHECK (esco_status IN ('EXACT','NORMALIZED','SEMANTIC_MATCH',
  'AMBIGUOUS','UNMAPPED','INSUFFICIENT_EVIDENCE','ALIAS_SENSE_REVIEW_REQUIRED'));
ALTER TABLE knowledge.skill_mention ADD COLUMN IF NOT EXISTS mention_role text;
ALTER TABLE knowledge.skill_mention ADD COLUMN IF NOT EXISTS sense_state text;

-- ---------------- engine 2.0 (additive; nothing above is altered) ----------------
CREATE TABLE IF NOT EXISTS knowledge.esco_occupation (
  occupation_uri text PRIMARY KEY CHECK (occupation_uri LIKE 'http://data.europa.eu/esco/occupation/%'),
  pref_label text NOT NULL, isco_code text);

CREATE TABLE IF NOT EXISTS knowledge.posting_occupation (
  run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  posting_uid text NOT NULL REFERENCES knowledge.job_posting(posting_uid),
  status text NOT NULL CHECK (status IN ('OCCUPATION_EXACT','OCCUPATION_VARIANT','OCCUPATION_CANDIDATE','OCCUPATION_AMBIGUOUS','OCCUPATION_UNMAPPED')),
  established boolean NOT NULL, occupation_uri text REFERENCES knowledge.esco_occupation(occupation_uri),
  matched_label text, isco_major_code text,
  CHECK (NOT established OR occupation_uri IS NOT NULL),
  PRIMARY KEY (run_id, posting_uid));

CREATE TABLE IF NOT EXISTS knowledge.topic_hierarchy (
  hierarchy_uid text PRIMARY KEY, course_uid text NOT NULL REFERENCES knowledge.course(course_uid),
  parent_node_uid text NOT NULL, parent_text text NOT NULL, child_text text NOT NULL, position int NOT NULL,
  child_topic_uid text REFERENCES knowledge.topic(topic_uid), method text NOT NULL, page_number int);

CREATE TABLE IF NOT EXISTS knowledge.concept_coverage (
  run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  skill_uid text NOT NULL REFERENCES knowledge.skill(skill_uid), doc_role text NOT NULL,
  coverage_level text NOT NULL CHECK (coverage_level IN ('ABSENT','MENTION','INTRODUCTORY','SUBSTANTIAL','ADVANCED','INSUFFICIENT_EVIDENCE')),
  coverage_relation text NOT NULL CHECK (coverage_relation IN ('DIRECT','PARTIAL','RELATED','INCIDENTAL','NONE')),
  courses_direct_or_partial int NOT NULL, units_direct_or_partial int NOT NULL, outcome_mentions int NOT NULL,
  level_reason text NOT NULL, PRIMARY KEY (run_id, skill_uid, doc_role));

CREATE TABLE IF NOT EXISTS knowledge.skill_gap_v2 (
  gap_uid text PRIMARY KEY REFERENCES knowledge.skill_gap(gap_uid), run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  classification_v1 text NOT NULL,
  classification_v2 text NOT NULL CHECK (classification_v2 IN ('MISSING','PARTIAL','COVERED','OUTDATED','EMERGING','MISALIGNED','INSUFFICIENT_EVIDENCE')),
  coverage_level text NOT NULL, industry_trend text NOT NULL, reason_v2 text NOT NULL,
  is_source_evidence boolean NOT NULL CHECK (is_source_evidence = false));

CREATE TABLE IF NOT EXISTS knowledge.semantic_model_run (
  run_id text PRIMARY KEY REFERENCES knowledge.pipeline_run(run_id),
  provider_status text NOT NULL CHECK (provider_status IN ('AI_PROVIDER_AVAILABLE','AI_PROVIDER_UNAVAILABLE')),
  provider text NOT NULL, model text, prompt_version text NOT NULL, candidates int NOT NULL, cache_hits int NOT NULL);

CREATE TABLE IF NOT EXISTS knowledge.semantic_decision (
  run_id text NOT NULL REFERENCES knowledge.semantic_model_run(run_id), decision_id text NOT NULL,
  candidate_kind text NOT NULL, source_entity text, candidate_entity text, left_text text NOT NULL, right_text text,
  relationship text NOT NULL CHECK (relationship IN ('SAME_CONCEPT','PARENT','CHILD','RELATED','PARTIAL_OVERLAP','UNRELATED',
     'AMBIGUOUS','INSUFFICIENT_EVIDENCE')),
  decision_state text NOT NULL CHECK (decision_state IN ('MODEL_SUGGESTED','REVIEW_REQUIRED','RULE_VERDICT_NO_MODEL','MODEL_FAILURE')),
  provider text NOT NULL, model text, prompt_version text NOT NULL, input_hash text NOT NULL, context_hash text NOT NULL,
  output_hash text NOT NULL, is_human_validated boolean NOT NULL, PRIMARY KEY (run_id, decision_id));

CREATE TABLE IF NOT EXISTS knowledge.concept_relationship (
  edge_id text PRIMARY KEY, run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  source text NOT NULL, relationship text NOT NULL, target text NOT NULL, method text NOT NULL, evidence_status text);

CREATE TABLE IF NOT EXISTS knowledge.semantic_contradiction (
  run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id), source text NOT NULL, target text NOT NULL,
  kind text NOT NULL, relationships jsonb NOT NULL, PRIMARY KEY (run_id, source, target, kind));

-- Run-scoped skill state. skill / skill_mention rows are keyed by run-invariant ids (first-seen facts: text,
-- span, posting); a skill's ESCO status and a mention's sense state can differ between runs (e.g. a taxonomy
-- change), so they are recorded per run here and the integrity checks use these tables.
CREATE TABLE IF NOT EXISTS knowledge.skill_run (
  run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  skill_uid text NOT NULL REFERENCES knowledge.skill(skill_uid),
  esco_status text NOT NULL, esco_uri text REFERENCES knowledge.esco_concept(esco_uri), mapping_method text,
  skill_category text NOT NULL, taxonomy_candidate_uri text,
  CHECK ((esco_uri IS NOT NULL) = (esco_status IN ('EXACT','NORMALIZED','SEMANTIC_MATCH'))),
  PRIMARY KEY (run_id, skill_uid));

CREATE TABLE IF NOT EXISTS knowledge.skill_mention_run (
  run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  mention_uid text NOT NULL REFERENCES knowledge.skill_mention(mention_uid),
  posting_uid text NOT NULL REFERENCES knowledge.job_posting(posting_uid),
  skill_uid text NOT NULL REFERENCES knowledge.skill(skill_uid),
  mention_role text NOT NULL, sense_state text NOT NULL, PRIMARY KEY (run_id, mention_uid));

-- MODEL_FAILURE (the model produced no text at all) is distinct from REVIEW_REQUIRED (invalid text)
ALTER TABLE knowledge.semantic_decision DROP CONSTRAINT IF EXISTS semantic_decision_decision_state_check;
ALTER TABLE knowledge.semantic_decision ADD CONSTRAINT semantic_decision_decision_state_check
  CHECK (decision_state IN ('MODEL_SUGGESTED','REVIEW_REQUIRED','RULE_VERDICT_NO_MODEL','MODEL_FAILURE'));

-- Engine V3: recorded-decision replay is its own provider status; the deterministic evidence
-- validator's verdict and the (gated) promotion effect are stored beside the model's answer.
ALTER TABLE knowledge.semantic_model_run DROP CONSTRAINT IF EXISTS semantic_model_run_provider_status_check;
ALTER TABLE knowledge.semantic_model_run ADD CONSTRAINT semantic_model_run_provider_status_check
  CHECK (provider_status IN ('AI_PROVIDER_AVAILABLE','AI_PROVIDER_UNAVAILABLE','AI_PROVIDER_REPLAYED'));
ALTER TABLE knowledge.semantic_decision ADD COLUMN IF NOT EXISTS validated_state text;
ALTER TABLE knowledge.semantic_decision ADD COLUMN IF NOT EXISTS validation_findings jsonb;
ALTER TABLE knowledge.semantic_decision ADD COLUMN IF NOT EXISTS effect text;
ALTER TABLE knowledge.semantic_decision DROP CONSTRAINT IF EXISTS semantic_decision_validated_state_check;
ALTER TABLE knowledge.semantic_decision ADD CONSTRAINT semantic_decision_validated_state_check
  CHECK (validated_state IS NULL OR validated_state IN ('MODEL_SUPPORTED','MODEL_SUGGESTED','INSUFFICIENT_EVIDENCE','REVIEW_REQUIRED',
                                                        'MODEL_FAILURE','RULE_VERDICT_NO_MODEL'));
ALTER TABLE knowledge.semantic_decision DROP CONSTRAINT IF EXISTS semantic_decision_effect_requires_support;
ALTER TABLE knowledge.semantic_decision ADD CONSTRAINT semantic_decision_effect_requires_support
  CHECK (effect IS NULL OR validated_state = 'MODEL_SUPPORTED');
