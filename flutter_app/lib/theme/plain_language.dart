/// The user-facing language layer (UserFacingLabels).
///
/// The backend keeps its own vocabulary -- document roles (TARGET, PREVIOUS_VERSION, REFERENCE, PEER), analysis
/// requirement keys (concept_drift, industry_gap, ...), status enums and snake_case field names. This file is the one
/// place where that vocabulary is turned into words a curriculum committee reads. Screens never show a backend code
/// directly: they call [Plain.value] for a status or role value, [Plain.field] for a field name, [Plain.sentence] for
/// free text the backend wrote, and [Plain.analysisOutcome] / [Plain.error] for something that went wrong.
///
/// Rules:
///   * nothing is hidden: a reason is reworded, never dropped; the original text stays in "Technical details";
///   * nothing names a discipline or an institution -- the wording works for any programme;
///   * the backend contract is unchanged; this layer only reads it.
library;

/// What happened, why, and what the reader can do about it.
class Explanation {
  const Explanation({required this.what, this.why = const [], this.actions = const [], this.technical});
  final String what;
  final List<String> why;
  final List<String> actions;

  /// The original backend text, for the technical-details section only.
  final String? technical;
}

class _Analysis {
  const _Analysis(this.name, this.task, this.why, this.actions);
  final String name;
  final String task; // completes "We couldn't ... yet."
  final String why;
  final List<String> actions;
}

class Plain {
  Plain._();

  static const _upload = 'New analysis';

  /// Analysis requirements (the backend's "analytics gates"), by key.
  static const _analyses = <String, _Analysis>{
    'concept_discovery': _Analysis('Finding concepts in the curriculum', 'find concepts in the curriculum',
        'None of the documents passed the extraction quality checks.',
        ['Review the extraction', 'Upload a clearer copy of the curriculum (a text-based PDF works best)']),
    'reference_mapping': _Analysis('Matching with the reference curriculum', 'match the curriculum with the reference curriculum',
        'This needs the current curriculum and a reference curriculum that both pass the quality checks.',
        ['Add a reference curriculum under $_upload', 'Review the current extraction']),
    'concept_drift': _Analysis('Curriculum changes', 'compare this curriculum with an earlier version',
        'An earlier curriculum for the same programme is required, sharing at least one semester with the current one.',
        ['Upload an earlier curriculum for the same programme', 'Review the current extraction']),
    'skill_taxonomy': _Analysis('Skill standardisation', 'match skills to standardised skills',
        'No skills reference is loaded, so skills cannot be matched to standardised skills.',
        ['Add the skills reference under $_upload']),
    'industry_demand': _Analysis('Industry demand', 'measure industry demand', 'There are not enough suitable job postings.',
        ['Add job postings you are permitted to use under $_upload']),
    'industry_gap': _Analysis('Skill-gap analysis', 'measure skill gaps', 'There are not enough suitable job postings.',
        ['Add job postings you are permitted to use under $_upload']),
    'recommendations': _Analysis('Recommendations', 'prepare recommendations',
        'Recommendations need the skill-gap analysis, which could not run.', []),
    'peer_benchmark': _Analysis('Peer comparison', 'compare the curriculum with peer curricula', 'No peer curriculum that passes the quality checks is available.',
        ['Add an official peer curriculum under $_upload']),
    'programme_comparison': _Analysis('Programme comparison', 'compare the two programmes', 'The two programmes share no comparable semester.', []),
  };

  /// The name of an analysis requirement ("concept_drift" -> "Curriculum changes").
  static String analysis(String key) => _analyses[key]?.name ?? words(key);

  /// Status, role and category values that can reach the screen. [StatusStyle.human] holds the curated wording for
  /// statuses; these complete it. Anything not listed is written in sentence case, never as a code.
  static const terms = <String, String>{
    // document roles and curriculum relations
    'TARGET': 'Current curriculum',
    'CURRENT_VERSION': 'Current curriculum',
    'PREVIOUS_VERSION': 'Earlier curriculum',
    'REFERENCE': 'Reference curriculum',
    'GENERAL_REFERENCE': 'Reference document',
    'PEER': 'Peer curriculum',
    'INDUSTRY': 'Job postings',
    'SAME_PROGRAMME': 'Same programme',
    'SAME_INSTITUTION_OTHER_PROGRAMME': 'Another programme of the same institution',
    'DIFFERENT_INSTITUTION': 'Another institution',
    // requirement and check results
    'ALLOWED': 'Can run',
    'BLOCKED': 'Cannot run yet',
    'NOT_APPLICABLE': 'Not applicable',
    'NOT_REQUESTED': 'Not requested',
    'PASS': 'Passed',
    'WARN': 'Warning',
    'FAIL': 'Failed',
    'NOT_LOADED': 'Not loaded',
    'SAFE_MODE': 'AI interpretation is advisory',
    'INSUFFICIENT_EVIDENCE': 'Not enough evidence',
    'INSUFFICIENT_DATA': 'Not enough data',
    'REVIEW_REQUIRED': 'Needs review',
    // curriculum scope (does the supplied curriculum cover the whole programme?)
    'INCOMPLETE': 'Part of the programme only',
    'UNDETERMINED': 'Could not be checked',
    'NOT_ASSESSED': 'Not assessed in this run',
    'CURRICULUM_SCOPE_INCOMPLETE': 'Curriculum supplied is incomplete',
    'CURRICULUM_SCOPE_REVIEW_REQUIRED': 'Curriculum supplied is incomplete; needs review',
    'NO_MATCH': 'No comparable match found',
    'MATCHED': 'Matched',
    'REPLAY_VERIFIED_RUN': 'Reproduced from recorded AI decisions',
    'AI_PROVIDER_REPLAYED': 'Reproduced from recorded AI decisions',
    // trends
    'TRENDING_UP': 'Rising',
    'TRENDING_DOWN': 'Falling',
    // how a skill is covered
    'DIRECT': 'Taught directly',
    'INCIDENTAL': 'In passing',
    // curriculum changes
    'EVOLVED': 'Evolved',
    'RENAMED': 'Renamed',
    'MERGED': 'Merged',
    'SPLIT': 'Split',
    // experimental gap review (Skill-Gap Reasoning agent)
    'NO_GAP': 'No gap',
    'LIMITED_COVERAGE': 'Taught only in electives or a narrower topic',
    'DEPTH_GAP': 'Taught too briefly',
    'STRUCTURAL_GAP': 'Not taught',
    'OUTDATED_COVERAGE': 'Taught, but demand is falling',
    'NOT_IN_RELEASE_GAPS': 'Not assessed by the main analysis',
    'ELECTIVE_ONLY': 'Electives only',
    'COMPULSORY': 'Compulsory course',
    'PAIRED_PRACTICAL': 'Has a matching lab',
    'THEORY_ONLY': 'No lab or project',
    'PRACTISED': 'Practised in a lab or project',
    'UNCERTAIN': 'Named, but depth unclear',
    'ANALYTICALLY_ELIGIBLE': 'Eligible for gap analysis',
    'NOT_PRODUCED': 'Not produced for this analysis',
    'AVAILABLE': 'Available',
  };

  /// Field names that appear as table headings, detail labels and summary titles.
  static const fields = <String, String>{
    // identifiers: readable names; the raw identifiers stay in technical details
    'run_id': 'Analysis reference',
    'parent_run': 'Based on analysis',
    'job_id': 'Analysis request',
    'upload_id': 'Upload reference',
    'source_id': 'Source',
    'doc_id': 'Document',
    'provenance.doc_id': 'Document',
    'programme_id': 'Programme',
    'course_id': 'Course',
    'course_code': 'Course code',
    'provenance.course_code': 'Course code',
    'provenance.unit': 'Unit',
    'provenance.page': 'Page',
    'concept_uid': 'Concept',
    'posting_id': 'Job posting',
    'requirement_id': 'Requirement',
    'record_counts_json': 'Evidence checked',
    // sources
    'source_type': 'Kind of source',
    'access_method': 'How it is accessed',
    'configuration_status': 'Set-up',
    'geographic_scope': 'Region',
    'licence': 'Licence',
    // agents and the experimental gap review
    'gap_state': 'Gap review',
    'authoritative_classification': 'Main analysis',
    'access': 'Who is taught it',
    'practice': 'Practical work',
    'other_curricula': 'Other curricula',
    'responsibility': 'Responsibility',
    'experimental_status': 'Experimental layer',
    'coordination': 'Order of work',
    'semantic_model': 'AI model',
    // curriculum
    'text': 'Topic',
    'parent_text': 'Broader topic',
    'child_text': 'Narrower topic',
    'page_number': 'Page',
    'source_roles': 'Found in',
    'role': 'Curriculum',
    'evidence_status': 'Evidence',
    'evidence_state': 'Evidence',
    'coverage_level': 'Coverage',
    'coverage_relation': 'How it is covered',
    'level_reason': 'Why',
    'previous_code': 'Earlier course code',
    'target_code': 'Current course code',
    'previous_title': 'Earlier title',
    'lineage_status': 'Link between versions',
    'engine_status': 'Change',
    'semantic_drift_category': 'Kind of change',
    'target_course_codes': 'Courses',
    'action_type': 'Action',
    // industry
    'job_title': 'Job title',
    'occupation_label': 'Occupation',
    'matched_label': 'Matched title',
    'uncovered_title_words': 'Title words not matched',
    'skill_label': 'Skill',
    'skill_key': 'Skill',
    'label': 'Skill',
    'skill_type': 'Kind of skill',
    'reuse_level': 'Reuse level',
    'top_skill_groups': 'Skill groups',
    'used_by_occupations': 'Occupations',
    'posting_count': 'Job postings',
    'posting_prevalence_pct': 'Share of job postings (%)',
    'company_count': 'Companies',
    'esco_status': 'Standardised skill',
    'support_state': 'Industry support',
    'eligible_postings': 'Job postings included in the analysis',
    'temporal_population': 'Time-period evidence',
    'trend_state': 'Trend',
    'classification_v1': 'Gap (first rule set)',
    'classification_v2': 'Gap (second rule set)',
    'reason_v2': 'Why',
    // semantic review and graph
    'candidate_kind': 'Kind',
    'left': 'First',
    'right': 'Second',
    'decision_state': 'Decision',
    'provider': 'Decided by',
    'relationship': 'Relationship',
    'relationships': 'Relationships',
    'source': 'From',
    'target': 'To',
    // requirements and run metadata
    'analytics_gates': 'Analysis requirements',
    'gates': 'Analysis requirements',
    'documents': 'Documents',
    'document_health': 'Document checks',
    'industry': 'Job postings',
    'funnel': 'Evidence funnel',
    'semantic_backend': 'AI interpretation',
    'ai_provider': 'AI model',
    'graph_checks': 'Graph checks',
    'pipeline_version': 'Analysis method version',
    'generated_at': 'Produced',
    'started_at': 'Started',
    'finished_at': 'Finished',
    'created_at': 'Created',
    'content_digest': 'Content fingerprint',
    'code_fingerprint': 'Method fingerprint',
    'config_hash': 'Settings fingerprint',
    'lineage': 'Change record',
    'lineage_error': 'Change record problem',
    'context_notes': 'Notes',
    'reviewed_by': 'Reviewed by',
    'measure_note': 'How demand is measured',
    'what_is_missing': 'What is missing',
    'next_action': 'What you can do',
    'last_successful_acquisition': 'Last obtained',
    'v1_to_v2': 'First to second rule set',
    'taxonomy': 'Skills reference',
    'taxonomy_mode': 'Skills reference mode',
    'adjudication': 'How decisions were made',
    'not_detected': 'Not detected',
    // validation checks (Data quality)
    'raw_hash_verified': 'Original file matches its recorded fingerprint',
    'ocr_required_page_ratio': 'Pages that needed text recognition',
    'valid_courses': 'Courses found',
    'titled_course_ratio': 'Courses with a title',
    'topic_noise_ratio': 'Lines that are not topics',
    'contract_quarantine_ratio': 'Items set aside as malformed',
    'provenance_completeness': 'Items traced to their source',
    'baseline_regression': 'Consistent with the accepted analysis',
    'source_hashes_verified': 'Source files match their recorded fingerprints',
    'duplicate_rate': 'Duplicate postings',
    'missing_description_ratio': 'Postings without a description',
    'skill_extraction_yield': 'Postings with a recognised skill',
    'unique_normalized_skills': 'Distinct standardised skills',
    'esco_mapping_yield': 'Skills matched to the skills reference',
    'ambiguous_skill_ratio': 'Ambiguous skills',
    'esco_skill_concepts': 'Standardised skills available',
  };

  /// A field name in words: "posting_count" -> "Job postings", "provenance.page" -> "Page"; unknown names are written
  /// in sentence case without underscores ("files_verified" -> "Files verified").
  static String field(String key) {
    final known = fields[key];
    if (known != null) return known;
    final last = key.contains('.') ? key.split('.').last : key;
    final k2 = fields[last];
    if (k2 != null) return k2;
    var w = last;
    if (w.endsWith('_id')) w = '${w.substring(0, w.length - 3)} reference';
    if (w.endsWith('_pct')) w = '${w.substring(0, w.length - 4)} (%)';
    return words(w);
  }

  /// "eligible_postings" / "PEER_DATA_PARTIAL" -> "Eligible postings" / "Peer data partial".
  static String words(String code) {
    final w = code.replaceAll(RegExp(r'[_.]+'), ' ').replaceAll(RegExp(r'\s+'), ' ').trim();
    if (w.isEmpty) return w;
    final lower = w == w.toUpperCase() ? w.toLowerCase() : w;
    return lower[0].toUpperCase() + lower.substring(1);
  }

  static final _code = RegExp(r'^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$');
  static final _snake = RegExp(r'^[a-z][a-z0-9]*(_[a-z0-9]+)+$');

  /// True for a value that is a backend code rather than text ("TARGET", "concept_drift").
  /// Single upper-case words count only when they are known terms, so acronyms (CSE, NCS) stay as written.
  static bool isCode(String v) =>
      terms.containsKey(v) || (_code.hasMatch(v) && v.contains('_')) || _snake.hasMatch(v);

  /// A value for display: codes become words, prose has its codes rewritten ([prose]), lists are joined, everything
  /// else goes to [fallback].
  static String value(dynamic v, {String Function(dynamic)? fallback}) {
    if (v is String) return isCode(v) ? termOrWords(v) : prose(v);
    if (v is List && v.every((x) => x == null || x is String || x is num || x is bool)) {
      return v.map((x) => value(x)).join(', ');
    }
    return fallback == null ? (v?.toString() ?? '—') : fallback(v);
  }

  /// Curated wording for a code, else sentence case of its words.
  static String termOrWords(String code) => terms[code] ?? (_analyses[code]?.name) ?? words(code);

  // ------------------------------------------------------------------------------------------------- free text

  static final List<(RegExp, String)> _rewrites = [
    (RegExp(r'\bTARGET \+ PREVIOUS_VERSION documents\b'), 'current and earlier curricula'),
    (RegExp(r'\bTARGET and REFERENCE documents?\b'), 'current curriculum and reference curriculum'),
    (RegExp(r'\b(?:analytics|quality) gates? blocked\b:?'), 'some analysis requirements were not met:'),
    (RegExp(r'\banalytics gates?\b'), 'analysis requirements'),
    (RegExp(r'\bhealth gate\b'), 'quality checks'),
    (RegExp(r'\bquality gates?\b'), 'evidence requirements'),
    (RegExp(r'\bPREVIOUS_VERSION(?: curriculum| document)?\b'), 'earlier curriculum'),
    (RegExp(r'\bTARGET(?: curriculum| document)?\b'), 'current curriculum'),
    (RegExp(r'\bGENERAL_REFERENCE(?: document)?\b'), 'reference document'),
    (RegExp(r'\bREFERENCE(?: curriculum| document)?\b'), 'reference curriculum'),
    (RegExp(r'\bPEER(?: curriculum| curricula| document)?\b'), 'peer curriculum'),
    (RegExp(r'\bpipeline runs?\b'), 'analysis'),
    (RegExp(r'\bthe pipeline\b'), 'the analysis'),
    (RegExp(r'\bpipeline\b'), 'analysis'),
    (RegExp(r'\bTarget([- ])curricul'), r'Current$1curricul'),
    (RegExp(r'\btarget([- ])curricul'), r'current$1curricul'),
    (RegExp(r'\btarget concepts\b'), 'concepts of the current curriculum'),
    (RegExp(r'\bskills? taxonomy\b'), 'skills reference'),
    (RegExp(r'\btaxonomy skills\b'), 'standardised skills'),
    (RegExp(r'\btaxonomy\b'), 'skills reference'),
    (RegExp(r'\bCANDIDATES\b'), 'candidates'),
    (RegExp(r'\bGOLD\b'), 'analysis results'),
    (RegExp(r'\bSILVER\b'), 'prepared evidence'),
    (RegExp(r'\bBRONZE\b'), 'processed source'),
    (RegExp(r'\bFAILED\b'), 'failed'),
    (RegExp(r'\bNONE\b'), 'no'),
  ];

  /// Backend free text (a reason, a note, an outcome) in plain words. Codes are rewritten in place; the meaning is
  /// kept. The original belongs in technical details.
  ///
  /// [knownOnly]: rewrite only snake_case names this layer knows (requirement keys, field names). Used for text that
  /// may contain the reader's own words (titles, topics), where an unknown underscore name is left as written.
  static String sentence(dynamic text, {bool knownOnly = false}) {
    if (text == null) return '';
    if (text is List) return text.map((t) => sentence(t, knownOnly: knownOnly)).where((s) => s.isNotEmpty).join(' ');
    var s = text.toString();
    for (final (re, to) in _rewrites) {
      s = to.contains(r'$1') ? s.replaceAllMapped(re, (m) => to.replaceAll(r'$1', m[1] ?? '')) : s.replaceAll(re, to);
    }
    // analysis requirement keys, then any remaining code
    s = s.replaceAllMapped(RegExp(r'\b[a-z]+(?:_[a-z0-9]+)+\b'),
        (m) =>
            _analyses[m[0]]?.name.toLowerCase() ??
            (fields[m[0]!]?.toLowerCase()) ??
            (knownOnly ? m[0]! : m[0]!.replaceAll('_', ' ')));
    s = s.replaceAllMapped(RegExp(r'\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b'), (m) => termOrWords(m[0]!).toLowerCase());
    return s;
  }

  static final _hint = RegExp(
      r'_|\b(?:TARGET|PREVIOUS_VERSION|REFERENCE|PEER|GOLD|SILVER|BRONZE|FAILED|NONE|CANDIDATES)\b|[Tt]arget[- ]curricul|target concepts|\bpipeline\b|taxonomy|\bgates?\b');

  /// Text from the API as it is displayed: prose (text with a space) has its backend codes rewritten; a single token
  /// -- a code, an identifier, a name -- is returned unchanged, so values compared or looked up stay intact. Only
  /// names this layer knows are rewritten, so the reader's own words (a topic, a title) keep their spelling. Verbatim
  /// evidence (a quoted job posting, a quoted syllabus line) is not passed through here at all.
  static String prose(String v) => v.contains(' ') && _hint.hasMatch(v) ? sentence(v, knownOnly: true) : v;

  // ------------------------------------------------------------------------------------------ analysis outcome

  static final _gateSplit = RegExp('(?:^|;\\s*)(${_analyses.keys.join('|')}):\\s*');

  /// The requirements a "needs review" reason names, with their own reasons:
  /// "analytics gates blocked: concept_drift: needs ...; industry_gap: ..." -> {concept_drift: needs ..., ...}.
  static Map<String, String> blockedRequirements(String? reason) {
    final out = <String, String>{};
    if (reason == null) return out;
    final body = reason.replaceFirst(RegExp(r'^\s*analytics gates blocked:\s*'), '');
    final marks = _gateSplit.allMatches(body).toList();
    for (var i = 0; i < marks.length; i++) {
      final end = i + 1 < marks.length ? marks[i + 1].start : body.length;
      out[marks[i][1]!] = body.substring(marks[i].end, end).trim();
    }
    return out;
  }

  static String _industryWhy(String reason, String fallback) {
    final m = RegExp(r'industry population: (\S+) real job postings \(minimum (\d+)\)').firstMatch(reason);
    if (m != null) {
      final n = m[1] == 'NONE' ? 'No' : 'Only ${m[1]}';
      return '$n job postings are available; at least ${m[2]} are needed.';
    }
    if (reason.contains('health gate FAILED')) return 'The job postings did not pass their quality checks.';
    if (reason.contains('TARGET')) return 'This needs a current curriculum matched to a reference curriculum.';
    return fallback;
  }

  /// Why one requirement could not run, in words.
  static String requirementWhy(String key, String reason) {
    final a = _analyses[key];
    if (key == 'industry_demand' || key == 'industry_gap') return _industryWhy(reason, a!.why);
    if (key == 'concept_drift' && reason.startsWith('the earlier curriculum')) return sentence(reason);
    if (a == null) return sentence(reason);
    return a.why;
  }

  /// A finished analysis job that needs review or failed, as what happened / why / what to do.
  static Explanation analysisOutcome(String status, String? reason) {
    if (status == 'NEEDS_REVIEW' && reason != null && reason.startsWith('the uploaded curriculum failed')) {
      // the curriculum itself did not pass the document checks: that is the cause, not what it blocked downstream
      final detail = reason.contains(':') ? reason.substring(reason.indexOf(':') + 1).split(';').first.trim() : '';
      return Explanation(
          what: 'The uploaded curriculum did not pass the analysis\'s document checks.',
          why: [
            if (detail.isNotEmpty) 'Check failed: ${sentence(detail)}.',
            'Without a readable curriculum no gap, comparison or recommendation can be trusted, so none is shown.',
          ],
          actions: const ['Review the extraction', 'Upload a clearer or complete copy of the curriculum', 'Run the analysis again'],
          technical: reason);
    }
    if (status == 'NEEDS_REVIEW') {
      final blocked = blockedRequirements(reason);
      if (blocked.isEmpty) {
        return Explanation(
            what: 'Some parts of the analysis could not be completed.',
            why: [if (reason != null && reason.isNotEmpty) sentence(reason)],
            actions: const ['Review the extraction', 'Run the analysis again'],
            technical: reason);
      }
      final names = blocked.keys.map(analysis).toList();
      final what = names.length == 1
          ? 'We couldn\'t ${_analyses[blocked.keys.first]?.task ?? 'complete ${names.first.toLowerCase()}'} yet.'
          : 'We couldn\'t complete these parts of the analysis yet: ${names.map((n) => n.toLowerCase()).join(', ')}.';
      final actions = <String>[];
      for (final k in blocked.keys) {
        for (final a in _analyses[k]?.actions ?? const <String>[]) {
          if (!actions.contains(a)) actions.add(a);
        }
      }
      actions.add('Run the analysis again');
      return Explanation(
        what: what,
        why: [
          for (final e in blocked.entries)
            names.length == 1 ? requirementWhy(e.key, e.value) : '${analysis(e.key)}: ${requirementWhy(e.key, e.value)}',
        ],
        actions: actions,
        technical: reason,
      );
    }
    if (status == 'ANALYSIS_NOT_RUN') {
      return Explanation(
          what: 'The analysis could not be started.',
          why: [if (reason != null && reason.isNotEmpty) _capital(sentence(reason))],
          actions: const ['Check that the analysis service is running', 'Run the analysis'],
          technical: reason);
    }
    // ANALYSIS_FAILED
    final internal = reason != null && RegExp(r'^[A-Z][A-Za-z]*(Error|Exception)\b').hasMatch(reason);
    return Explanation(
      what: 'The analysis stopped before it produced results.',
      why: [
        if (internal) 'An unexpected problem occurred while the curriculum was being analysed.'
        else if (reason == 'the pipeline produced no run') 'The analysis finished without producing any results.'
        else if (reason != null && reason.isNotEmpty) _capital(sentence(reason)),
      ],
      actions: const [
        'Run the analysis again',
        'If it happens again, share the technical details with whoever maintains this installation',
      ],
      technical: reason,
    );
  }

  /// A request that failed, in words. [what] names the information that was being loaded.
  static Explanation error(Object? e, String what, {int? statusCode, String? code, String? message}) {
    final status = statusCode;
    if (status == null) {
      return Explanation(
          what: 'Could not load $what.',
          why: const ['The analysis service could not be reached.'],
          actions: const ['Check that the server is running', 'Retry'],
          technical: e?.toString());
    }
    if (code == 'NO_ANALYSIS_YET') {
      // a fresh installation: nothing is wrong, nothing has been analysed yet
      return const Explanation(
          what: 'No analysis yet.',
          why: ['Nothing has been analysed on this computer yet. Open New analysis and upload a curriculum PDF to '
              'start; the results appear here when it finishes.'],
          actions: ['Open New analysis'],
          technical: 'HTTP 404 · NO_ANALYSIS_YET');
    }
    final why = status == 404
        ? 'This information is not available for the selected analysis.'
        : status >= 500
            ? 'The server ran into a problem while preparing it.'
            : (message == null || message.isEmpty ? 'The request was not accepted.' : _capital(sentence(message)));
    return Explanation(
        what: 'Could not load $what.',
        why: [why],
        actions: const ['Retry'],
        technical: ['HTTP $status', if (code != null) code, if (message != null) message].join(' · '));
  }

  static String _capital(String s) => s.isEmpty ? s : s[0].toUpperCase() + s.substring(1);
}
