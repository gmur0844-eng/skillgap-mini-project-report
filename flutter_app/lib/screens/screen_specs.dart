/// Screen definitions (pure Dart, no Flutter import) so the same specs drive the app and the live API check
/// (tool/live_api_check.dart). Every screen reads one real backend endpoint; nothing is computed on the client.
class KnowledgeScreenSpec {
  const KnowledgeScreenSpec({
    required this.title,
    required this.path,
    this.listKey = 'items',
    this.columns = const [],
    this.summaryKeys = const [],
    this.query,
    this.help,
    this.inputParam,
    this.inputHint,
    this.componentsKey,
  });

  final String title;
  final String path;
  final String listKey;
  final List<String> columns; // dotted paths into each row, e.g. 'left_esco.status'
  final List<String> summaryKeys; // top-level keys shown as a JSON summary block
  final Map<String, String>? query;
  final String? help;
  final String? inputParam; // when set, the screen asks for this query parameter before loading
  final String? inputHint;
  final String? componentsKey; // a map of component -> {status, ...} rendered as status cards
}

const knowledgeScreens = <KnowledgeScreenSpec>[
  KnowledgeScreenSpec(
      title: 'Analysis Agents',
      path: '/api/v1/agents',
      columns: ['order', 'name', 'responsibility', 'status', 'experimental_status'],
      summaryKeys: ['coordination', 'semantic_model', 'note'],
      help: 'The five parts of the analysis, in the order they work: each reads what the previous one stored. '
          'The main results come from the tested pipeline; an experimental layer is shown only where it is labelled.'),
  KnowledgeScreenSpec(
      title: 'Gap Review (experimental)',
      path: '/api/v1/agents/gap-review',
      columns: ['skill_label', 'gap_state', 'authoritative_classification', 'coverage_level', 'access', 'practice',
          'other_curricula', 'reason'],
      summaryKeys: ['label', 'states', 'note'],
      help: 'A stricter gap review that also reads elective status, labs, incomplete documents and other curricula. '
          'It is experimental: the Skill-gap analysis screen still shows the main analysis until people have reviewed this one.'),
  KnowledgeScreenSpec(
      title: 'Data Quality',
      path: '/api/v1/curriculum/knowledge-health',
      listKey: '_none',
      summaryKeys: ['documents', 'industry', 'analytics_gates'],
      help: 'The checks behind the current analysis: every source document, the job postings and the analysis '
          'requirements, each with its measured value, its threshold and its result.'),
  KnowledgeScreenSpec(
      title: 'Source Registry',
      path: '/api/v1/metadata/sources',
      listKey: 'sources',
      columns: ['source_id', 'source_type', 'access_method', 'configuration_status', 'geographic_scope', 'licence'],
      summaryKeys: ['note'],
      help: 'Where evidence can come from and how each source is accessed. The documents and files used by the '
          'current analysis are listed under Data lineage.'),
  KnowledgeScreenSpec(
      title: 'Overview',
      path: '/api/v1/curriculum/knowledge-runs/latest',
      listKey: '_none',
      summaryKeys: ['run_id', 'pipeline_version', 'generated_at', 'content_digest', 'document_health',
          'analytics_gates', 'funnel', 'semantic_backend']),
  KnowledgeScreenSpec(
      title: 'System Health',
      path: '/api/v1/intelligence/system-health',
      listKey: '_none',
      summaryKeys: ['gates', 'graph_checks', 'ai_provider'],
      componentsKey: 'components'),
  KnowledgeScreenSpec(
      title: 'Curriculum Explorer',
      path: '/api/v1/curriculum/topics',
      columns: ['provenance.doc_id', 'provenance.course_code', 'provenance.unit', 'provenance.page', 'text', 'concept_uid']),
  KnowledgeScreenSpec(
      title: 'Topic Explorer (hierarchy)',
      path: '/api/v1/curriculum/topic-hierarchy',
      columns: ['parent_text', 'child_text', 'position', 'page_number', 'method'],
      summaryKeys: ['stats']),
  KnowledgeScreenSpec(
      title: 'Concept Explorer',
      path: '/api/v1/semantic/concepts',
      columns: ['name', 'support', 'source_roles', 'evidence_status'],
      summaryKeys: ['note']),
  KnowledgeScreenSpec(
      title: 'Knowledge Graph',
      path: '/api/v1/semantic/relationships',
      columns: ['source', 'relationship', 'target', 'method', 'evidence_status']),
  KnowledgeScreenSpec(
      title: 'Industry Explorer (occupations)',
      path: '/api/v1/industry/occupations',
      columns: ['job_title', 'status', 'occupation_label', 'matched_label', 'uncovered_title_words'],
      summaryKeys: ['summary']),
  KnowledgeScreenSpec(
      title: 'Industry Demand',
      path: '/api/v1/industry/demand',
      columns: ['skill_label', 'posting_count', 'posting_prevalence_pct', 'company_count', 'esco_status', 'support_state'],
      summaryKeys: ['measure_note']),
  KnowledgeScreenSpec(
      title: 'ESCO Audit',
      path: '/api/v1/industry/esco-audit',
      listKey: '_none',
      summaryKeys: ['taxonomy_mode', 'reconstruction_scope', 'skill_concepts_reconstructed', 'full_source',
          'full_classification', 'matching_vocabulary', 'delta_vs_full', 'delta_change_information']),
  KnowledgeScreenSpec(
      title: 'Skill Intelligence (ESCO context)',
      path: '/api/v1/industry/skill-taxonomy',
      columns: ['label', 'skill_type', 'reuse_level', 'top_skill_groups', 'used_by_occupations']),
  KnowledgeScreenSpec(
      title: 'Coverage Depth',
      path: '/api/v1/curriculum/coverage',
      columns: ['role', 'skill_label', 'coverage_level', 'coverage_relation', 'level_reason'],
      summaryKeys: ['levels']),
  KnowledgeScreenSpec(
      title: 'Skill Gap (v2)',
      path: '/api/v1/intelligence/gaps',
      columns: ['skill_label', 'classification_v1', 'classification_v2', 'coverage_level', 'support_state', 'reason_v2'],
      summaryKeys: ['v1_to_v2']),
  KnowledgeScreenSpec(
      title: 'Curriculum Drift',
      path: '/api/v1/curriculum/drift',
      columns: ['concept', 'engine_status', 'semantic_drift_category'],
      summaryKeys: ['categories', 'not_detected']),
  KnowledgeScreenSpec(
      title: 'Course Drift & Lineage',
      path: '/api/v1/curriculum/course-drift',
      columns: ['status', 'previous_code', 'target_code', 'title', 'previous_title', 'lineage_status', 'method'],
      summaryKeys: ['statuses', 'excluded', 'note']),
  KnowledgeScreenSpec(
      title: 'Peer Benchmarking',
      path: '/api/v1/curriculum/benchmark',
      listKey: '_none',
      summaryKeys: ['benchmark']),
  KnowledgeScreenSpec(
      title: 'Recommendations',
      path: '/api/v1/intelligence/recommendations',
      listKey: 'v1',
      columns: ['skill_label', 'action_type', 'target_course_codes', 'evidence_status', 'uncertainty'],
      summaryKeys: ['prerequisite', 'rules', 'note']),
  KnowledgeScreenSpec(
      title: 'Semantic Decisions',
      path: '/api/v1/semantic/decisions',
      columns: ['candidate_kind', 'left', 'right', 'relationship', 'decision_state', 'provider'],
      summaryKeys: ['adjudication']),
  KnowledgeScreenSpec(
      title: 'Contradictions / Graph Checks',
      path: '/api/v1/semantic/contradictions',
      columns: ['source', 'target', 'kind', 'relationships'],
      summaryKeys: ['checks', 'examples']),
  KnowledgeScreenSpec(
      title: 'Optional Human Review',
      path: '/api/v1/semantic/review',
      columns: ['candidate_kind', 'left', 'right', 'relationship', 'decision_state'],
      summaryKeys: ['review_state', 'human_labels'],
      help: 'Human review is optional. Reviewers record their judgements in the review workbook, which is then '
          'imported; this screen never records a judgement itself.'),
  KnowledgeScreenSpec(
      title: 'Evidence Trace',
      path: '/api/v1/intelligence/evidence-trace',
      listKey: '_none',
      inputParam: 'skill_key',
      inputHint: 'a skill as listed under Industry Demand (its standardised-skill link, or surface:<skill name>)',
      summaryKeys: ['skill_key', 'trace', 'coverage_depth', 'taxonomy', 'lag']),
  KnowledgeScreenSpec(
      title: 'Evidence Status',
      path: '/api/v1/intelligence/evidence-status',
      columns: ['requirement_id', 'status', 'measured', 'required', 'what_is_missing', 'next_action',
          'last_successful_acquisition'],
      summaryKeys: ['statuses', 'note'],
      help: 'What evidence each analysis needs, which sources were tried (with licence and result) and the next '
          'available action. Nothing is filled in when a source cannot supply real, licensed records.'),
  KnowledgeScreenSpec(
      title: 'Data Lineage',
      path: '/api/v1/intelligence/lineage',
      listKey: '_none',
      summaryKeys: ['run_id', 'code_fingerprint', 'config_hash', 'content_digest', 'sources', 'stages']),
  KnowledgeScreenSpec(
      title: 'Industry Trends',
      path: '/api/v1/industry/trends',
      columns: ['skill_label', 'trend_state', 'posting_count', 'reason'],
      summaryKeys: ['states']),
];

