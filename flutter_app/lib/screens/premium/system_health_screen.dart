import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../theme/design_system.dart';
import '../../theme/plain_language.dart';
import '../../widgets/ui_kit.dart';
import 'pages.dart';

/// System health as an answer, not a component grid: is the analysis ready, is the evidence sufficient, what is
/// limited, is AI authoritative or advisory, can results be traced. Every state comes from GET /api/v1/readiness
/// (derived from the run's GOLD). Implementation details -- run, pipeline, database, model, semantic gate -- are kept,
/// collapsed, under "Technical details".
class SystemHealthScreen extends StatelessWidget {
  const SystemHealthScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return TabbedPage(
      labels: const ['Status', 'Run details'],
      builder: (context, i) => i == 1
          ? specView(api, 'System Health')
          : ApiView(
              api: api,
              path: '/api/v1/readiness',
              what: 'the analysis status',
              builder: (context, d, reload) => PageFrame(children: _page(d)),
            ),
    );
  }

  List<Widget> _page(Map<String, dynamic> d) {
    final ai = asMap(d['ai_interpretation']);
    final trace = asMap(d['traceability']);
    final sec = asMap(d['secondary']);
    final range = asMap(sec['industry_evidence_dates']);
    return [
      ResearchHeader(
        eyebrow: 'Is the current analysis ready to use?',
        title: fmt(d['headline']),
        sentence: fmt(d['summary']),
      ),
      _PrimaryStates(asList(d['primary']).map(asMap).toList()),
      const SizedBox(height: AppSpacing.section),
      EditorialSection(
        label: 'Evidence coverage',
        intro: 'What the analysis rests on, and where it is limited. A limited area opens to what would resolve it.',
        wide: true,
        child: Column(children: [for (final c in asList(d['coverage']).map(asMap)) _CoverageRow(c)]),
      ),
      EditorialSection(
        label: 'What to know',
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final t in asList(d['what_to_know']))
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.lg),
              child: Text(fmt(t), style: AppTypography.lede.copyWith(color: AppColors.text)),
            ),
        ]),
      ),
      EditorialSection(
        label: 'AI interpretation',
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(fmt(ai['human']), style: AppTypography.headline),
          const SizedBox(height: AppSpacing.sm),
          Text(fmt(ai['explanation']), style: AppTypography.body),
          const SizedBox(height: AppSpacing.lg),
          KeyValueList([
            if (ai['why'] != null) MapEntry('Why', ai['why']),
            MapEntry('What it affects', ai['affects']),
            MapEntry('What remains authoritative', ai['authoritative']),
          ], labelWidth: 200),
        ]),
      ),
      EditorialSection(
        label: 'Traceability',
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(fmt(trace['state']) == 'COMPLETE' ? 'Complete' : 'Incomplete', style: AppTypography.headline),
          const SizedBox(height: AppSpacing.sm),
          Text(
              asList(d['primary']).map(asMap).firstWhere((p) => p['key'] == 'traceability', orElse: () => const {})['statement']
                      ?.toString() ??
                  '',
              style: AppTypography.body),
          EvidencePanel(title: 'What was checked', children: [
            for (final e in asMap(trace['checks']).entries)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 3),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Icon(e.value == true ? Icons.check : Icons.close,
                        size: 14, color: e.value == true ? AppColors.success : AppColors.danger,
                        semanticLabel: e.value == true ? 'passed' : 'failed'),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(child: Text(_checkLabel(e.key), style: AppTypography.muted)),
                ]),
              ),
          ]),
        ]),
      ),
      EditorialSection(
        label: 'Freshness',
        child: KeyValueList([
          MapEntry('Last successful analysis', _when(sec['last_successful_analysis'])),
          MapEntry('Curriculum analysed', sec['curriculum_version']),
          MapEntry('Industry evidence dated',
              range.isEmpty ? null : (range['earliest'] == range['latest'] ? range['earliest'] : '${fmt(range['earliest'])} – ${fmt(range['latest'])}')),
        ], labelWidth: 200),
      ),
      EditorialSection(
        label: 'For technical review',
        spacing: 0,
        child: EvidencePanel(
          title: 'Technical details',
          summary: 'analysis reference, method version, database, AI model and its state',
          children: [
            KeyValueList([
              for (final e in asMap(d['technical']).entries)
                if (e.value is! Map) MapEntry(Plain.field(e.key), e.value is List ? (e.value as List).join(', ') : e.value),
            ], labelWidth: 220),
            for (final e in asMap(d['technical']).entries)
              if (e.value is Map && (e.value as Map).isNotEmpty) ...[
                const SizedBox(height: AppSpacing.md),
                Text(Plain.field(e.key), style: AppTypography.overline),
                KeyValueList([for (final x in asMap(e.value).entries) MapEntry(Plain.field(x.key), x.value)],
                    labelWidth: 320),
              ],
            const SizedBox(height: AppSpacing.md),
            Text('Service components', style: AppTypography.overline),
            _Components(api: api),
          ],
        ),
      ),
    ];
  }

  static const _checks = {
    'source_documents_hash_verified': 'Every source document is identified by its content fingerprint',
    'postings_with_source_file_and_row': 'Every job posting points to its source file and row',
    'source_files_hash_verified': 'Every job-posting file matches its recorded fingerprint',
    'demand_rows_with_postings': 'Every demand figure lists the postings it counts',
    'withheld_and_suppressed_with_reasons': 'Every withheld or suppressed recommendation states its reason',
    'graph_edges_with_provenance': 'Every knowledge-graph relationship carries its method and evidence',
    'graph_without_dangling_edges': 'No relationship points to a missing item',
    'run_content_digest': 'The analysis is fingerprinted, so it can be reproduced',
  };

  static String _checkLabel(String k) => _checks[k] ?? Plain.field(k);

  static String _when(dynamic iso) {
    final s = fmt(iso);
    return s.length >= 16 ? '${s.substring(0, 10)} ${s.substring(11, 16)} UTC' : s;
  }
}

/// Analysis · Evidence · AI interpretation · Traceability: four statements, one per line -- the state in the serif with
/// a small dot of its tone, then what it means. Not four cards.
class _PrimaryStates extends StatelessWidget {
  const _PrimaryStates(this.states);
  final List<Map<String, dynamic>> states;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, box) {
      final wide = box.maxWidth >= AppLayout.stack;
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final s in states)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.xl),
            child: wide
                ? Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    SizedBox(
                        width: AppLayout.margin,
                        child: Padding(
                            padding: const EdgeInsets.only(top: 6), child: Text(fmt(s['label']), style: AppTypography.overline))),
                    const SizedBox(width: AppLayout.gutter),
                    SizedBox(width: 300, child: _state(s)),
                    Expanded(
                        child: Padding(
                            padding: const EdgeInsets.only(top: 4), child: Text(fmt(s['statement']), style: AppTypography.muted))),
                  ])
                : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(fmt(s['label']), style: AppTypography.overline),
                    _state(s),
                    Text(fmt(s['statement']), style: AppTypography.muted),
                  ]),
          ),
      ]);
    });
  }

  Widget _state(Map<String, dynamic> s) => Row(mainAxisSize: MainAxisSize.min, children: [
        Container(
          width: 7,
          height: 7,
          margin: const EdgeInsets.only(right: 10),
          decoration: BoxDecoration(color: _tone(fmt(s['state'])), shape: BoxShape.circle),
        ),
        Flexible(child: Text(fmt(s['human']), style: AppTypography.title)),
      ]);

  static Color _tone(String state) => switch (state) {
        'READY' || 'AVAILABLE' || 'COMPLETE' || 'VALIDATED' => AppColors.success,
        'AVAILABLE_WITH_LIMITATIONS' || 'ADVISORY' || 'PARTIAL' => AppColors.warning,
        _ => AppColors.danger,
      };
}

/// "Industry trends — Not established — current job evidence covers 1 qualifying period…"; a limited area opens to
/// what is missing, why it matters and what would resolve it.
class _CoverageRow extends StatefulWidget {
  const _CoverageRow(this.c);
  final Map<String, dynamic> c;

  @override
  State<_CoverageRow> createState() => _CoverageRowState();
}

class _CoverageRowState extends State<_CoverageRow> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final c = widget.c;
    final state = fmt(c['state']);
    final limited = c['missing'] != null;
    final tone = state == 'AVAILABLE' || state == 'ESTABLISHED'
        ? AppColors.success
        : state == 'PARTIAL'
            ? AppColors.warning
            : AppColors.danger;
    final stateText = Text.rich(TextSpan(children: [
      WidgetSpan(
          alignment: PlaceholderAlignment.middle,
          child: Container(
              width: 7, height: 7, margin: const EdgeInsets.only(right: 8),
              decoration: BoxDecoration(color: tone, shape: BoxShape.circle))),
      TextSpan(text: fmt(c['human'])),
    ]), style: AppTypography.body.copyWith(color: tone));
    final chevron = limited
        ? AnimatedRotation(
            turns: _open ? 0.5 : 0,
            duration: AppMotion.normal,
            child: Icon(Icons.expand_more, size: 18, color: AppColors.textFaint),
          )
        : const SizedBox.shrink();
    final row = LayoutBuilder(builder: (context, box) {
      if (box.maxWidth < 560) {
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [Expanded(child: Text(fmt(c['label']), style: AppTypography.section)), stateText, chevron]),
            const SizedBox(height: AppSpacing.xs),
            Text(fmt(c['statement']), style: AppTypography.muted),
          ]),
        );
      }
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 170, child: Text(fmt(c['label']), style: AppTypography.section)),
          SizedBox(width: 170, child: stateText),
          Expanded(child: Text(fmt(c['statement']), style: AppTypography.muted)),
          chevron,
        ]),
      );
    });
    return Container(
      padding: const EdgeInsets.only(bottom: AppSpacing.xs),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (limited)
          Semantics(
            button: true,
            label: '${fmt(c['label'])}: ${fmt(c['human'])}. ${_open ? 'Hide' : 'Show'} what is missing',
            child: InkWell(onTap: () => setState(() => _open = !_open), child: row),
          )
        else
          row,
        AnimatedSize(
          duration: AppMotion.normal,
          curve: AppMotion.curve,
          alignment: Alignment.topCenter,
          child: !_open
              ? const SizedBox(width: double.infinity)
              : Padding(
                  padding: EdgeInsets.only(left: MediaQuery.sizeOf(context).width < 700 ? 0 : 170, bottom: AppSpacing.md),
                  child: KeyValueList([
                    MapEntry('What is missing', c['missing']),
                    MapEntry('Why it matters', c['why_it_matters']),
                    MapEntry('What would resolve it', c['resolve']),
                  ], labelWidth: 170),
                ),
        ),
      ]),
    );
  }
}

/// Live service components (GET /health), shown only inside Technical details.
class _Components extends StatelessWidget {
  const _Components({required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 360,
      child: ApiView(
        api: api,
        path: '/health',
        what: 'the service components',
        builder: (context, d, reload) => ListView(children: [
          for (final e in asMap(d['components']).entries)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.sm),
              child: KeyValueList([
                MapEntry(Plain.field(e.key), fmt(at(e.value, 'status'))),
                for (final x in asMap(e.value).entries)
                  if (x.key != 'status' && x.value is! Map && x.value is! List) MapEntry('  ${Plain.field(x.key)}', x.value),
              ], labelWidth: 220),
            ),
        ]),
      ),
    );
  }
}
