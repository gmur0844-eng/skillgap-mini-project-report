import 'package:flutter/material.dart';

import '../theme/design_system.dart';
import '../theme/plain_language.dart';
import 'ui_kit.dart';

/// Live progress of an analysis job, as recorded by the backend from the pipeline's own stage events
/// (services/analysis_progress.py). Each phase shows what it does, its state, the step running now ("document 2 of
/// 5") and, once done, what it produced and how long it took. Nothing is estimated: there is no percentage and no
/// phase is shown complete before the backend recorded it complete.
class AnalysisProgress extends StatelessWidget {
  const AnalysisProgress({super.key, required this.job});
  final Map<String, dynamic> job;

  /// Pipeline steps in words (the step code stays available as a tooltip).
  static const stepNames = {
    'raw.verify': 'Checking the files',
    'bronze.extract': 'Reading the pages',
    'silver.structure': 'Recognising courses, units and topics',
    'industry.esco': 'Loading the skills reference (ESCO)',
    'industry.silver': 'Reading the job postings',
    'industry.extract': 'Finding skills in postings and curricula',
    'health.gate': 'Checking each document',
    'gold.concepts': 'Discovering concepts',
    'gold.reference_mapping': 'Matching with the reference curriculum',
    'gold.prerequisites': 'Linking prerequisites',
    'gold.skills': 'Collecting curriculum skills',
    'gold.drift': 'Comparing with the earlier version',
    'gold.programme_comparison': 'Comparing programmes',
    'industry.gold': 'Measuring demand and classifying gaps',
    'intelligence': 'Reasoning over gaps and recommendations',
    'peers.semantic_benchmark': 'Comparing with peer curricula',
    'industry.v2': 'Resolving occupations and relevance',
    'gold.review_and_versioning': 'Preparing the review queue',
    'evaluation': 'Running evaluation checks',
    'gold.write': 'Saving the analysis',
    'publish.postgres': 'Publishing to the database',
    'lineage': 'Linking to the previous analysis',
  };

  static const _countWords = {
    'documents': 'documents',
    'pages': 'pages',
    'valid_courses': 'courses',
    'units': 'units',
    'clean_topics': 'topics',
    'records_read': 'job postings',
    'mentions_all': 'skill mentions',
    'unique_normalized_skills': 'skills',
    'esco_mapped_skills': 'skills matched to ESCO',
    'skill_concepts': 'ESCO skills',
    'demand_rows': 'skills in demand',
    'recommendations': 'recommendations',
  };

  static const _statusWords = {
    'PENDING': 'Waiting',
    'RUNNING': 'In progress',
    'COMPLETED': 'Done',
    'FAILED': 'Failed',
    'NEEDS_REVIEW': 'Needs review',
    'NOT_RUN': 'Not run',
    'NOT_REQUESTED': 'Not requested',
  };

  static String _seconds(dynamic v) {
    final s = v is num ? v.toDouble() : 0.0;
    if (s < 1) return 'under a second';
    if (s < 90) return '${s.round()} s';
    return '${(s / 60).toStringAsFixed(1)} min';
  }

  /// What a finished phase produced: the counts of its steps, summed per kind, in words.
  static String? _produced(Map<String, dynamic> phase) {
    final totals = <String, num>{};
    for (final step in asList(phase['steps'])) {
      final counts = asMap(at(step, 'counts'));
      for (final e in counts.entries) {
        if (e.value is num && _countWords.containsKey(e.key) && e.key != 'documents') {
          totals[e.key] = (totals[e.key] ?? 0) + (e.value as num);
        }
      }
    }
    if (totals.isEmpty) return null;
    return totals.entries.take(3).map((e) => '${fmtCount(e.value)} ${_countWords[e.key]}').join(' · ');
  }

  @override
  Widget build(BuildContext context) {
    final phases = asList(job['phases']).map(asMap).where((p) => p.isNotEmpty).toList();
    if (phases.isEmpty) return const SizedBox.shrink();
    final shown = phases.where((p) => p['status'] != 'NOT_REQUESTED').toList();
    final left = phases.where((p) => p['status'] == 'NOT_REQUESTED').toList();
    return Semantics(
      container: true,
      label: 'Analysis progress',
      liveRegion: true,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (var i = 0; i < shown.length; i++) _PhaseRow(index: i + 1, total: shown.length, phase: shown[i]),
        if (left.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.sm),
          Text('Not part of this analysis (as you chose): ${left.map((p) => fmt(p['label']).toLowerCase()).join(', ')}.',
              style: AppTypography.caption),
        ],
      ]),
    );
  }
}

class _PhaseRow extends StatelessWidget {
  const _PhaseRow({required this.index, required this.total, required this.phase});
  final int index;
  final int total;
  final Map<String, dynamic> phase;

  @override
  Widget build(BuildContext context) {
    final status = fmt(phase['status']);
    final running = status == 'RUNNING';
    final steps = asList(phase['steps']).map(asMap).toList();
    final Map<String, dynamic> current = running
        ? steps.lastWhere((s) => s['status'] == 'RUNNING', orElse: () => const <String, dynamic>{})
        : const <String, dynamic>{};
    final Map<String, dynamic> failed =
        steps.lastWhere((s) => s['status'] == 'FAILED', orElse: () => const <String, dynamic>{});
    final color = switch (status) {
      'COMPLETED' => AppColors.success,
      'RUNNING' => AppColors.primary,
      'FAILED' => AppColors.danger,
      'NEEDS_REVIEW' => AppColors.warning,
      _ => AppColors.textFaint,
    };
    final produced = status == 'COMPLETED' || status == 'NEEDS_REVIEW' ? AnalysisProgress._produced(phase) : null;
    final agent = phase['agent'];
    final detail = <String>[
      if (running && current.isNotEmpty)
        [
          AnalysisProgress.stepNames[current['stage']] ?? Plain.words(fmt(current['stage'])),
          if (current['detail'] != null) fmt(current['detail']),
        ].join(' — '),
      if (produced != null) produced,
      if ((status == 'COMPLETED' || status == 'NEEDS_REVIEW') && phase['duration_s'] is num)
        'took ${AnalysisProgress._seconds(phase['duration_s'])}',
    ];
    final why = phase['reason'] ?? failed['error'];
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(
          padding: const EdgeInsets.only(top: 5, right: AppSpacing.md),
          child: running
              ? const SizedBox(width: 10, height: 10, child: CircularProgressIndicator(strokeWidth: 1.5))
              : Container(width: 8, height: 8, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
        ),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Wrap(spacing: AppSpacing.sm, crossAxisAlignment: WrapCrossAlignment.center, children: [
              Text('$index. ${fmt(phase['label'])}',
                  style: AppTypography.section.copyWith(color: running ? AppColors.text : AppColors.textMuted)),
              Text(AnalysisProgress._statusWords[status] ?? Plain.words(status), style: AppTypography.caption.copyWith(color: color)),
              if (agent != null) Text('agent: $agent', style: AppTypography.caption),
            ]),
            Text(fmt(phase['explains']), style: AppTypography.caption),
            if (detail.isNotEmpty) Text(detail.join(' · '), style: AppTypography.muted),
            if (why != null && status != 'COMPLETED' && status != 'RUNNING')
              Text(Plain.sentence(why), style: AppTypography.muted.copyWith(color: status == 'FAILED' ? AppColors.danger : null)),
          ]),
        ),
      ]),
    );
  }
}
