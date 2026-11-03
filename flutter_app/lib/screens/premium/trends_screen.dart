import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../shell/navigation.dart';
import '../../theme/design_system.dart';
import '../../theme/plain_language.dart';
import '../../widgets/ui_kit.dart';
import 'pages.dart';

/// Temporal intelligence. A trend is shown only with both periods, both denominators, both posting counts and the
/// population; with too few periods the page says what is missing instead of drawing a line.
class TrendsScreen extends StatelessWidget {
  const TrendsScreen({super.key, required this.api, required this.navigate});
  final ApiClient api;
  final Navigate navigate;

  static const _stateTabs = [null, 'EMERGING', 'DECLINING', 'PERSISTENT'];

  @override
  Widget build(BuildContext context) {
    return TabbedPage(
      labels: const ['Skill trends', 'Emerging', 'Declining', 'Persistent', 'Trend table'],
      builder: (context, i) {
        if (i == 4) return specView(api, 'Industry Trends');
        final state = _stateTabs[i];
        return ApiView(
          api: api,
          path: '/api/v1/industry/temporal-trends',
          query: {'limit': '2000', if (state != null) 'state': state},
          what: 'the industry trends',
          builder: (context, d, reload) => _page(context, d, state),
        );
      },
    );
  }

  Widget _page(BuildContext context, Map<String, dynamic> d, String? state) {
    final pops = asList(d['populations']);
    final rows = asList(d['items']);
    final classified = rows.where((r) => at(r, 'trend_state') != 'INSUFFICIENT_DATA').toList();
    return PageFrame(children: [
      for (final p in pops) _populationBanner(asMap(p)),
      for (final p in pops)
        if (at(p, 'trend_status') != 'COMPUTED') _temporalEvidenceRequired(asMap(p)),
      if (pops.any((p) => at(p, 'trend_status') == 'COMPUTED')) ...[
        SectionCard(
          title: state == null ? 'Skill trends' : '${StatusStyle.label(state)} skills',
          subtitle: 'States across all skills: ${fmt(d['states'])}',
          child: classified.isEmpty
              ? Text(
                  state == null
                      ? 'No skill passes the per-skill trend thresholds.'
                      : 'No skill is ${StatusStyle.label(state)} in this population.',
                  style: AppTypography.muted)
              : Column(children: [for (final r in classified.take(60)) _trendRow(asMap(r))]),
        ),
      ],
      SectionCard(
        title: 'Segments',
        subtitle: 'Trends by occupation group, region, seniority and industry domain; each segment needs enough postings of its own',
        child: Column(children: [
          for (final s in asList(d['segments']).take(20))
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(children: [
                Expanded(child: Text(fmt(at(s, 'segment')), style: AppTypography.body, overflow: TextOverflow.ellipsis)),
                Text('${fmt(at(s, 'eligible_postings'))} postings  ', style: AppTypography.caption),
                StatusBadge(fmt(at(s, 'trend_status')), dense: true),
              ]),
            ),
        ]),
      ),
    ]);
  }

  Widget _populationBanner(Map<String, dynamic> p) {
    final range = asMap(p['date_range']);
    return ScopeBanner(
      title: 'Population ${fmt(p['population_id'])}',
      status: fmt(p['trend_status']),
      facts: [
        asMap(p['geographic_scope']).keys.join(', '),
        '${fmt(p['eligible_postings'])} postings',
        range['earliest'] == range['latest'] ? fmt(range['earliest']) : '${fmt(range['earliest'])} – ${fmt(range['latest'])}',
        'granularity ${fmt(p['granularity'])}',
        '${asList(p['source_files']).length} source files',
      ],
      note: 'Denominator: distinct eligible postings of this population only; populations are never merged.',
    );
  }

  Widget _temporalEvidenceRequired(Map<String, dynamic> p) {
    final missing = asMap(p['missing']);
    final have = asMap(missing['have']);
    return SectionCard(
      title: 'Temporal evidence required',
      subtitle: 'Temporal Intelligence',
      trailing: const StatusBadge('INSUFFICIENT_DATA'),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('More time periods are required to calculate a reliable trend.', style: AppTypography.section),
        const SizedBox(height: AppSpacing.md),
        KeyValueList([
          MapEntry('current', '${fmt(have['qualifying_periods'])} period(s) · ${fmt(have['granularity'])}'),
          MapEntry('postings by period', have['postings_by_period']),
          MapEntry('required', missing['required']),
          MapEntry('why it matters', missing['why_it_matters']),
          MapEntry('what can provide it', missing['sources_that_can_provide_it']),
        ]),
        const SizedBox(height: AppSpacing.md),
        OutlinedButton.icon(
          onPressed: () => navigate(Dest.evidenceStatus),
          icon: const Icon(Icons.inventory_2_outlined, size: 16),
          label: const Text('View data sources'),
        ),
      ]),
    );
  }

  Widget _trendRow(Map<String, dynamic> r) {
    final periods = asList(r['periods']);
    return EvidencePanel(
      title: '${fmt(r['skill_label'])} · ${StatusStyle.label(fmt(r['trend_state']))}',
      summary: Plain.sentence(fmt(r['statement'])),
      children: [
        Row(children: [StatusBadge(fmt(r['trend_state']), dense: true), const SizedBox(width: 8), Text(Plain.sentence(fmt(r['reason'])))]),
        const SizedBox(height: AppSpacing.sm),
        for (final p in periods)
          KeyValueList([
            MapEntry(fmt(at(p, 'period')),
                '${fmt(at(p, 'posting_count'))} of ${fmt(at(p, 'eligible_postings'))} postings = ${fmt(at(p, 'demand_pct'))}%'
                '${at(p, 'pp_change_from_previous') == null ? '' : ' (${fmt(at(p, 'pp_change_from_previous'))} pp)'}'),
          ]),
        KeyValueList([
          MapEntry('population', r['population_id']),
          MapEntry('segment', r['segment']),
          MapEntry('percentage-point change', r['pp_change']),
          MapEntry('relative change', r['relative_change']),
        ]),
      ],
    );
  }
}
