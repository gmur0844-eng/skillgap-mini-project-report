import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../theme/design_system.dart';
import '../../theme/plain_language.dart';
import '../../widgets/ui_kit.dart';
import 'pages.dart';

/// Occupation resolution v2: every posting's decision (EXACT, VARIANT, CANDIDATE, AMBIGUOUS, UNMAPPED,
/// INSUFFICIENT_EVIDENCE) with its context support, and occupation-aware analysis per group.
class OccupationsScreen extends StatelessWidget {
  const OccupationsScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return TabbedPage(
      labels: const ['Resolution', 'By occupation', 'By occupation group'],
      builder: (context, i) {
        if (i == 0) {
          return ApiView(
              api: api,
              path: '/api/v1/occupations/resolution',
              query: const {'limit': '1000'},
              what: 'the occupations',
              builder: (context, d, reload) => _Resolution(data: d));
        }
        return ApiView(
          api: api,
          path: '/api/v1/occupations/analysis',
          query: {'level': i == 1 ? 'occupation' : 'occupation_group'},
          what: 'occupation analysis',
          builder: (context, d, reload) => PageFrame(children: [
            PageHeader(title: i == 1 ? 'Occupations' : 'Occupation groups (ISCO)', subtitle: fmt(d['note'])),
            if (asList(d['items']).isEmpty)
              const EmptyState(title: 'No established occupation', body: 'No posting has an established occupation.'),
            for (final g in asList(d['items']))
              SectionCard(
                title: fmt(at(g, 'name')),
                subtitle: '${fmt(at(g, 'postings'))} posting(s)',
                trailing: StatusBadge(fmt(at(g, 'evidence_state')), dense: true),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  if (at(g, 'reason') != null) Text(Plain.sentence(fmt(at(g, 'reason'))), style: AppTypography.muted),
                  KeyValueList([
                    MapEntry('Essential skills (skills reference)', at(g, 'esco_profile_alignment.essential_skills')),
                    MapEntry('Mentioned in the current curriculum', at(g, 'esco_profile_alignment.mentioned_in_target_curriculum')),
                    MapEntry('Share', at(g, 'esco_profile_alignment.pct') == null ? null : '${fmt(at(g, 'esco_profile_alignment.pct'))}%'),
                    MapEntry('Basis', at(g, 'esco_profile_alignment.basis')),
                  ], labelWidth: 220),
                  if (asList(at(g, 'top_skills')).isNotEmpty)
                    Wrap(spacing: AppSpacing.lg, runSpacing: AppSpacing.xs, children: [
                      for (final s in asList(at(g, 'top_skills')))
                        Text('${fmt(at(s, 'skill_label'))} · ${fmt(at(s, 'postings'))}', style: AppTypography.muted),
                    ]),
                ]),
              ),
          ]),
        );
      },
    );
  }
}

class _Resolution extends StatefulWidget {
  const _Resolution({required this.data});
  final Map<String, dynamic> data;

  @override
  State<_Resolution> createState() => _ResolutionState();
}

class _ResolutionState extends State<_Resolution> {
  String? _state;

  @override
  Widget build(BuildContext context) {
    final summary = asMap(widget.data['summary']);
    final byState = asMap(summary['by_state']);
    final items = asList(widget.data['items']).where((r) => _state == null || at(r, 'state') == _state).toList();
    return PageFrame(children: [
      const PageHeader(
          title: 'From job title to occupation',
          subtitle: 'Title labels are checked against each posting\'s own skills (occupation profiles in the skills reference); '
              'context can confirm a candidate or contradict a title, and no single occupation is forced.'),
      Wrap(spacing: AppSpacing.xxl, runSpacing: AppSpacing.xl, children: [
        KpiCard(value: summary['established'], label: 'Established', caption: 'of ${fmt(summary['postings'])} postings'),
        KpiCard(value: summary['established_by_title'], label: 'By title', icon: Icons.title),
        KpiCard(value: summary['established_by_context'], label: 'By context', icon: Icons.hub_outlined),
        KpiCard(
            value: summary['title_contradicted_by_context'],
            label: 'Title contradicted',
            caption: 'title match rejected by the posting\'s skills',
            icon: Icons.report_gmailerrorred),
      ]),
      const SizedBox(height: AppSpacing.lg),
      SectionCard(title: 'Decision states', child: DistributionBar(counts: byState)),
      QuietFilter(
        labels: ['All', for (final k in byState.keys) '${StatusStyle.label(k)} ${byState[k]}'],
        selected: _state == null ? 0 : byState.keys.toList().indexOf(_state!) + 1,
        onSelect: (i) => setState(() => _state = i == 0 ? null : byState.keys.toList()[i - 1]),
      ),
      const SizedBox(height: AppSpacing.md),
      for (final r in items.take(150))
        Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.xl),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(fmt(at(r, 'job_title')), style: AppTypography.title),
            Wrap(spacing: AppSpacing.lg, children: [
              StatusBadge(fmt(at(r, 'state')), dense: true),
              StatusBadge(fmt(at(r, 'context_support')), dense: true),
            ]),
            const SizedBox(height: 4),
            Text(
                at(r, 'occupation_label') == null
                    ? 'no established occupation'
                    : '${fmt(at(r, 'occupation_label'))} · ${fmt(at(r, 'occupation_group'))}',
                style: AppTypography.body),
            Text(Plain.sentence(fmt(at(r, 'reason'))), style: AppTypography.caption),
            if (asList(at(r, 'skill_profile_candidates')).isNotEmpty)
              Text(
                  'profile candidates: ${asList(at(r, 'skill_profile_candidates')).map((c) => '${fmt(at(c, 'label'))} (${fmt(at(c, 'overlap'))})').join(', ')}',
                  style: AppTypography.caption),
          ]),
        ),
    ]);
  }
}
