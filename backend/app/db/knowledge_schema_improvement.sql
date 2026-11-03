-- Intelligence improvement release (applied after knowledge_schema.sql; idempotent).
-- PEER curricula: decoded like every document, used only by the peer benchmark.
ALTER TABLE knowledge.document DROP CONSTRAINT IF EXISTS document_role_check;
ALTER TABLE knowledge.document ADD CONSTRAINT document_role_check
  CHECK (role IN ('TARGET','PREVIOUS_VERSION','REFERENCE','PEER'));

CREATE TABLE IF NOT EXISTS knowledge.peer_comparison (
  run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  comparison_doc_sha256 text NOT NULL REFERENCES knowledge.document(sha256),
  comparison_role text NOT NULL CHECK (comparison_role IN ('PEER','REFERENCE')),
  peer_status text NOT NULL CHECK (peer_status IN ('PEER_DATA_AVAILABLE','PEER_DATA_PARTIAL','PEER_DATA_NOT_AVAILABLE')),
  exact_lexical_pct numeric, normalized_pct numeric, semantic_concept_pct numeric, semantic_related_pct numeric,
  target_concepts int NOT NULL, comparison_concepts int NOT NULL, course_context_min numeric NOT NULL,
  PRIMARY KEY (run_id, comparison_doc_sha256));

CREATE TABLE IF NOT EXISTS knowledge.peer_relation (
  relation_uid text PRIMARY KEY, run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  comparison_doc_sha256 text NOT NULL REFERENCES knowledge.document(sha256),
  target_concept_uid text NOT NULL, comparison_unit_uid text NOT NULL, target_concept text, comparison_concept text,
  relationship text NOT NULL CHECK (relationship IN ('SAME_CONCEPT','PARENT','CHILD','RELATED','PARTIAL_OVERLAP','UNRELATED',
     'AMBIGUOUS','INSUFFICIENT_EVIDENCE')),
  evidence_state text NOT NULL CHECK (evidence_state IN ('SUPPORTED','MODEL_SUPPORTED','MODEL_SUGGESTED','REVIEW_REQUIRED',
     'AMBIGUOUS','INSUFFICIENT_EVIDENCE')),
  similarity numeric NOT NULL, course_context numeric NOT NULL, model_consulted boolean NOT NULL,
  -- a model never produces a deterministic SUPPORTED relationship
  CHECK (NOT (model_consulted AND evidence_state = 'SUPPORTED')));

CREATE TABLE IF NOT EXISTS knowledge.temporal_population (
  run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id), population_id text NOT NULL,
  eligible_postings int NOT NULL, granularity text, trend_status text NOT NULL CHECK (trend_status IN ('COMPUTED','INSUFFICIENT_DATA')),
  date_earliest text, date_latest text, PRIMARY KEY (run_id, population_id));

CREATE TABLE IF NOT EXISTS knowledge.skill_trend (
  run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id), population_id text NOT NULL, segment text NOT NULL,
  skill_uid text NOT NULL REFERENCES knowledge.skill(skill_uid),
  trend_state text NOT NULL CHECK (trend_state IN ('TRENDING_UP','TRENDING_DOWN','STABLE','EMERGING','DECLINING','PERSISTENT',
     'INSUFFICIENT_DATA')),
  periods jsonb NOT NULL, pp_change numeric, relative_change numeric, total_postings int NOT NULL,
  PRIMARY KEY (run_id, population_id, segment, skill_uid));

CREATE TABLE IF NOT EXISTS knowledge.occupation_resolution (
  run_id text NOT NULL REFERENCES knowledge.pipeline_run(run_id),
  posting_uid text NOT NULL REFERENCES knowledge.job_posting(posting_uid),
  state text NOT NULL CHECK (state IN ('EXACT','VARIANT','CANDIDATE','AMBIGUOUS','UNMAPPED','INSUFFICIENT_EVIDENCE')),
  established boolean NOT NULL, established_by text CHECK (established_by IS NULL OR established_by IN ('title','context')),
  occupation_uri text REFERENCES knowledge.esco_occupation(occupation_uri), context_support text NOT NULL,
  posting_context_skills int NOT NULL,
  CHECK (established = (occupation_uri IS NOT NULL)), CHECK (established = (established_by IS NOT NULL)),
  PRIMARY KEY (run_id, posting_uid));
