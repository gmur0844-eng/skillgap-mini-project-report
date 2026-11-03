-- Consistency / hardening release (applied after knowledge_schema.sql and knowledge_schema_improvement.sql; idempotent).
--
-- 1. concept_relationship was keyed by edge_id alone, but edge ids are run-invariant (hash of source, relationship,
--    target) while the table is run-scoped. Publishing a second run silently skipped every edge the first run already
--    had (ON CONFLICT DO NOTHING), so a later run held only its new edges (e.g. 115 of 15,689). The key becomes
--    (run_id, edge_id); existing rows are kept.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace
             WHERE n.nspname = 'knowledge' AND t.relname = 'concept_relationship' AND c.contype = 'p'
               AND array_length(c.conkey, 1) = 1) THEN
    ALTER TABLE knowledge.concept_relationship DROP CONSTRAINT concept_relationship_pkey;
    ALTER TABLE knowledge.concept_relationship ADD CONSTRAINT concept_relationship_pkey PRIMARY KEY (run_id, edge_id);
  END IF;
END $$;

-- 2. The graph keeps the different mapping problems apart: every edge records which kind of relationship it is.
ALTER TABLE knowledge.concept_relationship ADD COLUMN IF NOT EXISTS mapping_kind text;
ALTER TABLE knowledge.concept_relationship DROP CONSTRAINT IF EXISTS concept_relationship_mapping_kind_check;
ALTER TABLE knowledge.concept_relationship ADD CONSTRAINT concept_relationship_mapping_kind_check CHECK (mapping_kind IS NULL OR
  mapping_kind IN ('DOCUMENT_STRUCTURE','TOPIC_HIERARCHY','TOPIC_TO_CONCEPT','CURRICULUM_TO_REFERENCE','PREREQUISITE',
                   'SKILL_TO_TAXONOMY','TAXONOMY_HIERARCHY','INDUSTRY_DEMAND','OCCUPATION','CURRICULUM_SKILL_MENTION',
                   'SEMANTIC_DECISION'));
