import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../theme/design_system.dart';
import '../../theme/plain_language.dart';
import '../../widgets/ui_kit.dart';
import 'pages.dart';

/// Industry intelligence as a research report: the evidence base, what can and cannot be concluded from it, the most
/// requested skills, and where the postings come from. Dimensions and co-occurrence clusters follow as views.
class IndustryScreen extends StatelessWidget {
  const IndustryScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return TabbedPage(
      labels: const ['Overview', 'Dimensions', 'Skill clusters', 'Demand table'],
      builder: (context, i) {
        switch (i) {
          case 0:
            return ApiView(api: api, path: '/api/v1/industry/intelligence', what: 'the industry evidence', builder: _overview);
          case 1:
            return ApiView(api: api, path: '/api/v1/industry/dimensions', what: 'industry dimensions', builder: _dimensions);
          case 2:
            return ApiView(api: api, path: '/api/v1/industry/clusters', what: 'skill clusters', builder: _clusters);
          default:
            return specView(api, 'Industry Demand');
        }
      },
    );
  }

  Widget _overview(BuildContext context, Map<String, dynamic> d, VoidCallback reload) {
    final dist = asMap(d['distributions']);
    final occ = asMap(d['occupation_summary']);
    final p = asMap(at(d, 'scope.population_scope'));
    final range = asMap(p['date_range']);
    final geo = asMap(p['geographic_scope']).keys.join(', ');
    // presentation order only: most requested first (the values are the API's distinct-posting counts)
    final skills = asList(d['skills_by_demand']).map(asMap).toList()
      ..sort((a, b) => ((b['distinct_postings'] ?? 0) as num).compareTo((a['distinct_postings'] ?? 0) as num));
    final warning = at(d, 'scope.population_scope.representativeness_warning');
    return PageFrame(children: [
      ResearchHeader(
        eyebrow: 'Industry signal',
        title: '${fmtCount(dist['postings'])} job postings provide the current evidence base.',
        sentence: '${[
          if (geo.isNotEmpty) 'Postings from $geo',
          '${fmtCount(dist['distinct_companies'])} companies and ${fmtCount(dist['distinct_titles'])} distinct job titles',
          if (range.isNotEmpty)
            range['earliest'] == range['latest']
                ? 'dated ${fmt(range['earliest'])}'
                : 'dated ${fmt(range['earliest'])} to ${fmt(range['latest'])}',
        ].join(', ')}. ${fmtCount(occ['established'])} postings are matched to an established occupation.',
      ),
      EditorialSection(
        label: 'What can be concluded',
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Which skills these postings ask for', style: AppTypography.title),
          const SizedBox(height: AppSpacing.xs),
          Text('Each figure counts distinct postings that mention a skill: observed prevalence in this population, '
              'not importance. ${fmt(d['denominator'])}.', style: AppTypography.muted),
          const SizedBox(height: AppSpacing.xxl),
          _TrendNote(api: api),
          if (warning != null) ...[
            const SizedBox(height: AppSpacing.xxl),
            Text('How far it generalises', style: AppTypography.title),
            const SizedBox(height: AppSpacing.xs),
            Text(warning.toString(), style: AppTypography.muted),
          ],
        ]),
      ),
      EditorialSection(
        label: 'Most requested skills',
        intro: 'Distinct postings per skill, most requested first. Mention counts are in the tooltip and are not demand.',
        wide: true,
        child: BarList(
          unit: 'postings',
          rows: [
            for (final r in skills.take(20))
              BarRow(fmt(r['skill_label']), (r['distinct_postings'] as num?) ?? 0, detail: '${fmt(r['mention_count'])} mentions'),
          ],
        ),
      ),
      EditorialSection(
        label: 'Where the postings come from',
        wide: true,
        spacing: 0,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Companies', style: AppTypography.title),
          const SizedBox(height: AppSpacing.md),
          BarList(unit: 'postings', rows: [
            for (final c in asList(dist['top_companies']).take(10))
              BarRow(fmt(at(c, 'company')), (at(c, 'postings') as num?) ?? 0),
          ]),
          const SizedBox(height: AppSpacing.block),
          Text('Locations', style: AppTypography.title),
          const SizedBox(height: AppSpacing.md),
          BarList(unit: 'postings', rows: [
            for (final c in asList(dist['top_locations']).take(10))
              BarRow(fmt(at(c, 'location')), (at(c, 'postings') as num?) ?? 0),
          ]),
          const SizedBox(height: AppSpacing.block),
          Text('Sources', style: AppTypography.title),
          const SizedBox(height: AppSpacing.md),
          DistributionBar(counts: asMap(dist['platforms'])),
        ]),
      ),
    ]);
  }

  Widget _dimensions(BuildContext context, Map<String, dynamic> d, VoidCallback reload) {
    return PageFrame(children: [
      const PageHeader(
          title: 'Demand by dimension',
          subtitle: 'Each group is its own population; groups below the minimum size are not ranked.'),
      for (final dim in asList(d['items']))
        SectionCard(
          title: StatusStyle.label(fmt(at(dim, 'dimension'))),
          subtitle: '${fmt(at(dim, 'postings_with_value'))} postings carry this field · '
              '${fmt(at(dim, 'postings_without_value'))} do not',
          trailing: StatusBadge(fmt(at(dim, 'status')), dense: true),
          child: at(dim, 'status') == 'DATA_NOT_AVAILABLE'
              ? Text(Plain.sentence(fmt(at(dim, 'reason'))), style: AppTypography.muted)
              : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  for (final g in asList(at(dim, 'groups')).take(8))
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Row(children: [
                          Expanded(child: Text(fmt(at(g, 'value')), style: AppTypography.body)),
                          Text('${fmt(at(g, 'postings'))} postings  ', style: AppTypography.caption),
                          StatusBadge(fmt(at(g, 'evidence_state')), dense: true),
                        ]),
                        if (at(g, 'top_skills') != null)
                          Padding(
                            padding: const EdgeInsets.only(top: AppSpacing.xs),
                            child: Wrap(spacing: AppSpacing.xs, runSpacing: AppSpacing.xs, children: [
                              for (final s in asList(at(g, 'top_skills')).take(6))
                                Text('${fmt(at(s, 'skill_label'))} · ${fmt(at(s, 'postings'))} '
                                    '(${fmt(at(s, 'demand_pct'))}%)', style: AppTypography.muted),
                            ]),
                          )
                        else
                          Text(Plain.sentence(fmt(at(g, 'reason'))), style: AppTypography.caption),
                      ]),
                    ),
                ]),
        ),
    ]);
  }

  Widget _clusters(BuildContext context, Map<String, dynamic> d, VoidCallback reload) {
    final clusters = asList(d['clusters']);
    return PageFrame(children: [
      PageHeader(title: 'Skill clusters', subtitle: fmt(d['note'])),
      if (clusters.isEmpty)
        EmptyState(
          icon: Icons.scatter_plot_outlined,
          title: 'No skill cluster meets the evidence threshold',
          body: 'Clusters need skills with ≥ ${fmt(at(d, 'config.min_skill_postings'))} postings that co-occur in ≥ '
              '${fmt(at(d, 'config.min_cooccurring_postings'))} postings with lift ≥ ${fmt(at(d, 'config.min_lift'))}. '
              '${fmt(d['eligible_skills'])} skills are frequent enough; more postings would reveal more structure.',
        ),
      for (final c in clusters)
        SectionCard(
          title: asList(at(c, 'members')).map((m) => fmt(at(m, 'skill_label'))).join(' · '),
          subtitle: Plain.sentence(fmt(at(c, 'statement'))),
          trailing: StatusBadge(fmt(at(c, 'relationship')), dense: true),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final e in asList(at(c, 'edges')))
              Text(
                  '${fmt(at(e, 'label_a'))} + ${fmt(at(e, 'label_b'))}: ${fmt(at(e, 'cooccurring_postings'))} postings '
                  'together (lift ${fmt(at(e, 'lift'))})',
                  style: AppTypography.muted),
          ]),
        ),
    ]);
  }
}


/// Industry trends in one sentence: established, or "Not established yet" with the reason -- never an invented trend line.
class _TrendNote extends StatelessWidget {
  const _TrendNote({required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return ApiView(
      api: api,
      path: '/api/v1/industry/temporal-trends',
      query: const {'limit': '1'},
      what: 'industry trends',
      builder: (context, d, reload) {
        final pops = asList(d['populations']).map(asMap).toList();
        final computed = pops.where((p) => p['trend_status'] == 'COMPUTED').toList();
        final have = pops.isEmpty ? const <String, dynamic>{} : asMap(at(pops.first, 'missing.have'));
        final n = have['qualifying_periods'];
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(computed.isNotEmpty ? 'How demand changes over time' : 'Whether demand is rising or falling: not established yet',
              style: AppTypography.title),
          const SizedBox(height: AppSpacing.xs),
          Text(
              computed.isNotEmpty
                  ? 'Trends are computed for ${computed.length} job-posting population${computed.length == 1 ? '' : 's'}; '
                      'each compares the same population across periods.'
                  : 'Current evidence covers ${n ?? 'one'} qualifying time period${n == 1 ? '' : 's'}. Additional dated '
                      'evidence is required to establish a trend: the same population observed in several periods.',
              style: AppTypography.muted),
        ]);
      },
    );
  }
}
