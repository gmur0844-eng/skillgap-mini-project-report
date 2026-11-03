import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../theme/design_system.dart';
import '../../theme/plain_language.dart';
import '../../widgets/ui_kit.dart';
import 'pages.dart';

/// Semantic peer benchmarking. The peer-data status is the first thing on the page (never inside an expansion).
/// Every comparison shows its scope, five separate coverage levels (never one score, never a ranking) and the
/// evidence of every relationship.
class PeerScreen extends StatelessWidget {
  const PeerScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return TabbedPage(
      labels: const ['Semantic benchmark', 'Reference comparison (v1)'],
      builder: (context, i) => i == 1
          ? specView(api, 'Peer Benchmarking')
          : ApiView(
              api: api,
              path: '/api/v1/peers/status',
              what: 'the peer comparison',
              builder: (context, st, reload) => ApiView(
                api: api,
                path: '/api/v1/peers/benchmark',
                what: 'the peer comparison',
                builder: (context, b, reload2) => _PeerBody(api: api, status: st, benchmark: b),
              ),
            ),
    );
  }
}

class _PeerBody extends StatefulWidget {
  const _PeerBody({required this.api, required this.status, required this.benchmark});
  final ApiClient api;
  final Map<String, dynamic> status;
  final Map<String, dynamic> benchmark;

  @override
  State<_PeerBody> createState() => _PeerBodyState();
}

class _PeerBodyState extends State<_PeerBody> {
  int _selected = 0;
  int _view = 0;

  static const _title = {
    'PEER_DATA_AVAILABLE': 'Peer comparison available',
    'PEER_DATA_PARTIAL': 'Peer comparison is partial',
    'PEER_DATA_NOT_AVAILABLE': 'No peer curriculum yet',
  };

  Widget _statusBanner() {
    final st = asMap(widget.status['status']);
    final status = fmt(widget.status['peer_status']);
    final available = asList(st['available']);
    final missing = asList(st['missing']);
    return StatusBanner(
      status: status,
      title: _title[status] ?? status,
      body: status == 'PEER_DATA_NOT_AVAILABLE'
          ? fmt(st['why_not_calculable'])
          : '${available.length} official peer curriculum/curricula decoded; ${missing.length} requested peer(s) not yet available.',
      children: [
        if (available.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.md),
          Text('Available', style: AppTypography.overline),
          for (final a in available)
            Text(
                '• ${fmt(at(a, 'institution'))} — ${fmt(at(a, 'programme'))}, ${fmt(at(a, 'curriculum_version'))} '
                '(${fmt(at(a, 'academic_year'))}); retrieved ${fmt(at(a, 'retrieved_at'))}',
                style: AppTypography.body),
        ],
        if (missing.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.md),
          Text('Not yet available', style: AppTypography.overline),
          for (final m in missing)
            Text('• ${fmt(at(m, 'name'))}: ${Plain.sentence(fmt(at(m, 'reason')))}', style: AppTypography.muted),
        ],
        const SizedBox(height: AppSpacing.md),
        Text('How to add a peer', style: AppTypography.overline),
        Text(fmt(st['how_to_add']), style: AppTypography.caption),
      ],
    );
  }

  static String _pct(dynamic level) {
    final m = asMap(level);
    return m['pct'] == null ? '—' : '${fmt(m['pct'])}%';
  }

  static String _short(dynamic institution) {
    final s = fmt(institution);
    const known = {
      'All India Council for Technical Education (AICTE)': 'AICTE',
      'Indian Institute of Technology Kanpur': 'IIT Kanpur',
      'National Institute of Technology Warangal': 'NIT Warangal',
      'National Institute of Technology Tiruchirappalli': 'NIT Tiruchirappalli',
    };
    return known[s] ?? s;
  }

  @override
  Widget build(BuildContext context) {
    final comps = asList(widget.benchmark['comparisons']).map(asMap).toList();
    final target = asMap(widget.benchmark['target']);
    if (comps.isEmpty) {
      return PageFrame(children: [_statusBanner()]);
    }
    final c = comps[_selected < comps.length ? _selected : 0];
    final levels = asMap(c['coverage_levels']);
    final concept = asMap(levels['semantic_concept']);
    final related = asMap(levels['semantic_related']);
    final docId = fmt(c['comparison_doc_id']);
    final peers = comps.where((x) => x['comparison_role'] == 'PEER').length;
    final references = comps.where((x) => x['comparison_role'] != 'PEER').map((x) => _short(x['institution'])).toList();
    return PageFrame(children: [
      ResearchHeader(
        eyebrow: 'Peer comparison',
        title: '$peers peer curricul${peers == 1 ? 'um' : 'a'} currently provide comparable topic evidence',
        sentence: '${fmt(target['institution'])} is compared with each of them on its own terms'
            '${references.isEmpty ? '' : ', and with the reference curriculum of ${references.join(', ')}'}. '
            'There is no overall score and no ranking of institutions.',
      ),
      _statusBanner(),
      const SizedBox(height: AppSpacing.block),
      EditorialSection(
        label: 'Side by side',
        intro: 'Share of the current curriculum\'s concepts found in each curriculum, measured four separate ways. '
            'Curricula are listed in the order their documents were registered; the measures are never combined.',
        wide: true,
        child: _sideBySide(comps),
      ),
      EditorialSection(
        label: 'One comparison',
        wide: true,
        spacing: 0,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          QuietFilter(
            labels: [for (final x in comps) _short(x['institution'])],
            selected: _selected,
            onSelect: (i) => setState(() => _selected = i),
          ),
          const SizedBox(height: AppSpacing.xl),
          AnimatedSwitcher(
            duration: AppMotion.normal,
            child: KeyedSubtree(
              key: ValueKey('summary:$_selected'),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: AppLayout.measure),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(
                      'Of the ${fmt(concept['of'])} concepts of the current curriculum, ${fmt(concept['count'])} (${_pct(concept)}) have an '
                      'equivalent concept in the ${_short(c['institution'])} curriculum, and ${fmt(related['count'])} '
                      '(${_pct(related)}) a related one.',
                      style: AppTypography.title),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                      '${fmt(c['programme'])}, ${fmt(c['curriculum_version'])}'
                      '${c['academic_year'] == null ? '' : ' (${fmt(c['academic_year'])})'}; '
                      '${StatusStyle.label(fmt(c['comparison_role'])).toLowerCase()}.',
                      style: AppTypography.muted),
                ]),
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.block),
          QuietFilter(
            labels: const ['Shared concepts', 'Different terminology', 'Related, not equivalent', 'Current curriculum only',
                'Comparison only', 'Needs review', 'Industry alignment'],
            selected: _view,
            onSelect: (i) => setState(() => _view = i),
          ),
          const SizedBox(height: AppSpacing.xl),
          _differences(docId),
        ]),
      ),
    ]);
  }

  Widget _sideBySide(List<Map<String, dynamic>> comps) {
    const measures = [
      ('semantic_concept', 'Equivalent concept'),
      ('semantic_related', 'Related concept'),
      ('exact_lexical', 'Same wording'),
      ('review_required', 'Needs review'),
    ];
    return LayoutBuilder(builder: (context, box) {
      if (box.maxWidth < 640) {
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final x in comps)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.xl),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(_short(x['institution']), style: AppTypography.title),
                for (final m in measures)
                  Text('${m.$2}: ${_pct(at(x, 'coverage_levels.${m.$1}'))}', style: AppTypography.muted),
              ]),
            ),
        ]);
      }
      return Table(
        columnWidths: const {0: FlexColumnWidth(2.4)},
        children: [
          TableRow(children: [
            Padding(padding: EdgeInsets.only(bottom: AppSpacing.md), child: Text('Curriculum', style: AppTypography.caption)),
            for (final m in measures)
              Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.md),
                  child: Text(m.$2, style: AppTypography.caption, textAlign: TextAlign.right)),
          ]),
          for (final x in comps)
            TableRow(children: [
              Padding(
                padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
                child: Text.rich(TextSpan(children: [
                  TextSpan(text: _short(x['institution']), style: AppTypography.title),
                  TextSpan(text: x['comparison_role'] == 'PEER' ? '' : '   reference', style: AppTypography.caption),
                ])),
              ),
              for (final m in measures)
                Padding(
                  padding: const EdgeInsets.only(top: AppSpacing.md + 6, bottom: AppSpacing.md),
                  child: Text(_pct(at(x, 'coverage_levels.${m.$1}')),
                      style: AppTypography.metricSmall, textAlign: TextAlign.right),
                ),
            ]),
        ],
      );
    });
  }

  static const _kinds = [
    'shared_concepts',
    'different_terminology',
    'related_not_equivalent',
    'target_concepts_absent_from_comparison',
    'comparison_concepts_absent_from_target',
    'ambiguous',
  ];

  Widget _differences(String docId) {
    if (_view == 6) {
      return ApiView(
        key: ValueKey('align:$docId'),
        api: widget.api,
        path: '/api/v1/peers/differences',
        query: {'comparison_doc_id': docId, 'kind': 'shared_concepts', 'limit': '1'},
        what: 'industry alignment',
        builder: (context, d, reload) => _alignment(asMap(d['industry_alignment'])),
      );
    }
    final kind = _kinds[_view];
    return ApiView(
      key: ValueKey('$kind:$docId'),
      api: widget.api,
      path: '/api/v1/peers/differences',
      query: {'comparison_doc_id': docId, 'kind': kind, 'limit': '25'},
      what: 'the peer differences',
      builder: (context, d, reload) {
        final page = asMap(at(d, 'differences.$kind'));
        final items = asList(page['items']);
        if (items.isEmpty) {
          return const EmptyState(title: 'Nothing in this category', body: 'The comparison produced no item of this kind.');
        }
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('showing ${items.length} of ${fmt(page['total'])}', style: AppTypography.caption),
          const SizedBox(height: AppSpacing.sm),
          for (final it in items) it is Map && it.containsKey('relationship') ? _relation(asMap(it)) : _concept(asMap(it)),
        ]);
      },
    );
  }

  Widget _conceptSide(String label, Map<String, dynamic> side) {
    final courses = asList(side['courses']);
    return Expanded(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: AppTypography.overline),
        Text(fmt(side['concept']), style: AppTypography.title),
        Text(courses.map((x) => '${fmt(at(x, 'course_code'))} ${fmt(at(x, 'title'))}').join(' · '),
            style: AppTypography.caption, maxLines: 2, overflow: TextOverflow.ellipsis),
        for (final t in asList(side['topics']).take(2))
          Text('p.${fmt(at(t, 'page'))}: ${fmt(at(t, 'text'))}',
              style: AppTypography.caption, maxLines: 2, overflow: TextOverflow.ellipsis),
      ]),
    );
  }

  Widget _relation(Map<String, dynamic> r) {
    final ev = asMap(r['evidence']);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xl),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        LayoutBuilder(builder: (context, box) {
          final link = Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
            child: Column(children: [
              Text(StatusStyle.label(fmt(r['relationship'])).toLowerCase(), style: AppTypography.caption),
              Container(width: 96, height: 1, margin: const EdgeInsets.only(top: 4), color: AppColors.primary.withValues(alpha: 0.5)),
            ]),
          );
          if (box.maxWidth < 640) {
            return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [_conceptSide('Current curriculum', asMap(r['target']))]),
              Padding(padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs), child: link),
              Row(children: [_conceptSide('Comparison', asMap(r['comparison']))]),
            ]);
          }
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _conceptSide('Current curriculum', asMap(r['target'])),
            Padding(padding: const EdgeInsets.only(top: 18), child: link),
            _conceptSide('Comparison', asMap(r['comparison'])),
          ]);
        }),
        EvidencePanel(
          title: 'Why these are linked',
          summary: Plain.sentence(fmt(r['reason'])),
          children: [
            KeyValueList([
              MapEntry('Evidence', r['evidence_state']),
              MapEntry('Topic similarity', ev['similarity']),
              MapEntry('Course context', ev['course_context']),
              MapEntry('Same specific name', ev['normalized_name_equal']),
              MapEntry('Shared topics', ev['shared_member_topics']),
              MapEntry('Shared standardised skills', asList(ev['shared_direct_skills']).length),
              MapEntry('Skills reference hierarchy', ev['esco_hierarchy']),
              MapEntry('Compared as', ev['comparison_unit']),
              MapEntry('AI suggestion', at(r, 'semantic_decision.reason')),
              MapEntry('Analysis reference', r['run_id']),
            ]),
          ],
        ),
      ]),
    );
  }

  Widget _concept(Map<String, dynamic> c) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _conceptSide(StatusStyle.label(fmt(c['role'])), c),
        Text('${fmt(c['support_topics'])} topics', style: AppTypography.caption),
      ]),
    );
  }

  Widget _alignment(Map<String, dynamic> a) {
    Widget list(String title, String key) {
      final rows = asList(a[key]);
      return SectionCard(
        title: title,
        subtitle: '${rows.length} industry-demand skill(s)',
        child: rows.isEmpty
            ? Text('None.', style: AppTypography.muted)
            : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                for (final r in rows)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(children: [
                      Expanded(child: Text(fmt(at(r, 'skill_label')), style: AppTypography.body)),
                      Text('demand ${fmt(at(r, 'industry.posting_count'))} postings  ', style: AppTypography.caption),
                      StatusBadge(fmt(at(r, 'target_level')), dense: true),
                      Text('  vs  ', style: AppTypography.caption),
                      StatusBadge(fmt(at(r, 'comparison_level')), dense: true),
                    ]),
                  ),
              ]),
      );
    }

    return Column(children: [
      Text(fmt(a['population_note']), style: AppTypography.caption),
      const SizedBox(height: AppSpacing.md),
      list('Covered substantially by the current curriculum, only superficially by the comparison', 'target_substantial_comparison_superficial'),
      list('In the comparison curriculum but not the current one', 'in_comparison_not_target'),
      list('In the current curriculum but not the comparison curriculum', 'in_target_not_comparison'),
      list('Covered at different depths', 'different_depth'),
    ]);
  }
}
