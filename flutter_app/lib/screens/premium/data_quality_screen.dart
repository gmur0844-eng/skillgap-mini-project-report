import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../theme/design_system.dart';
import '../../theme/plain_language.dart';
import '../../widgets/ui_kit.dart';
import 'pages.dart';

/// Data quality as a short report on the current run's own validation checks (GET /api/v1/curriculum/knowledge-health):
/// the overall state, then source documents, industry postings and the analysis requirements; every check with its value,
/// threshold and result, folded until asked for. Nothing here is estimated: a warning is shown as a warning.
class DataQualityReport extends StatelessWidget {
  const DataQualityReport({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return TabbedPage(
      labels: const ['Report', 'All checks'],
      builder: (context, i) => i == 1
          ? specView(api, 'Data Quality')
          : ApiView(
              api: api,
              path: '/api/v1/curriculum/knowledge-health',
              what: 'the validation checks',
              builder: (context, d, reload) => _Report(d),
            ),
    );
  }
}

class _Report extends StatelessWidget {
  const _Report(this.d);
  final Map<String, dynamic> d;

  static String _words(String code) => Plain.field(code);

  @override
  Widget build(BuildContext context) {
    final docs = asMap(d['documents']).values.map(asMap).toList();
    final industry = asMap(d['industry']);
    final gates = asMap(d['analytics_gates']);
    final checks = [
      for (final doc in docs) ...asList(doc['checks']).map(asMap),
      ...asList(industry['checks']).map(asMap),
    ];
    int n(String s) => checks.where((c) => c['status'] == s).length;
    final fails = n('FAIL');
    final warns = n('WARN');
    final passes = n('PASS');
    final blocked = gates.values.map(asMap).where((g) => g['status'] == 'BLOCKED').length;
    final notApplicable = gates.values.map(asMap).where((g) => g['status'] == 'NOT_APPLICABLE').length;
    final notRequested = gates.values.map(asMap).where((g) => g['status'] == 'NOT_REQUESTED').length;
    final summary = asMap(industry['summary']);
    return PageFrame(children: [
      ResearchHeader(
        eyebrow: 'Data quality',
        title: fails == 0
            ? 'The current analysis passed its validation checks'
            : '$fails validation check${fails == 1 ? '' : 's'} failed',
        sentence: '$passes of ${checks.length} checks passed'
            '${warns == 0 ? '' : ', $warns carry a warning'}'
            '${fails == 0 ? '' : ' and $fails failed'}. '
            '${blocked == 0 ? 'Every analysis has the evidence it needs' : '$blocked of ${gates.length} analyses cannot run yet'}'
            '${notApplicable == 0 ? '' : '; $notApplicable do not apply to this curriculum'}'
            '${notRequested == 0 ? '' : '; $notRequested were left out of this analysis by choice'}.',
      ),
      EditorialSection(
        label: 'Source documents',
        aside: Text('${docs.length}', style: AppTypography.metric),
        intro: 'Each curriculum document is hash-verified and checked for extractable text, courses and topics before '
            'it is analysed.',
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final doc in docs) _group(fmt(doc['doc_id']), fmt(doc['status']), asList(doc['checks']).map(asMap).toList()),
        ]),
      ),
      EditorialSection(
        label: 'Job postings',
        aside: Text(fmtCount(summary['eligible_postings']), style: AppTypography.metric),
        intro: '${fmtCount(summary['records_read'])} postings read from ${fmtCount(summary['files_verified'])} of '
            '${fmtCount(summary['files_expected'])} verified files; ${fmtCount(summary['duplicates'])} duplicates removed; '
            '${fmtCount(summary['postings_with_skill'])} postings contain an analysable skill.',
        child: _group('Postings and skills', fmt(industry['status']), asList(industry['checks']).map(asMap).toList()),
      ),
      EditorialSection(
        label: 'Analyses',
        intro: 'Each analysis runs only when the evidence it requires is present; when it cannot run, the reason is given.',
        spacing: 0,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final e in gates.entries)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.md),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SizedBox(width: 220, child: Text(Plain.analysis(e.key), style: AppTypography.body)),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    StatusBadge(fmt(at(e.value, 'status')), dense: true),
                    if (at(e.value, 'status') == 'BLOCKED' && asList(at(e.value, 'reasons')).isNotEmpty)
                      Text(Plain.requirementWhy(e.key, '${asList(at(e.value, 'reasons')).first}'), style: AppTypography.caption)
                    else
                      for (final r in asList(at(e.value, 'reasons'))) Text(Plain.sentence(fmt(r)), style: AppTypography.caption),
                  ]),
                ),
              ]),
            ),
        ]),
      ),
    ]);
  }

  Widget _group(String name, String status, List<Map<String, dynamic>> checks) {
    final passed = checks.where((c) => c['status'] == 'PASS').length;
    final notes = checks.where((c) => c['status'] != 'PASS').toList();
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xl),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(name, style: AppTypography.title),
        Text('$passed of ${checks.length} checks passed', style: AppTypography.muted),
        for (final c in notes)
          Padding(
            padding: const EdgeInsets.only(top: AppSpacing.xs),
            child: Text(
                '${StatusStyle.label(fmt(c['status']))}: ${_words(fmt(c['check']))}'
                '${c['detail'] == null || c['detail'] == '' ? '' : ' (${fmt(c['detail'])})'}',
                style: AppTypography.caption.copyWith(color: AppColors.warning)),
          ),
        EvidenceDisclosure(
          title: 'Every check',
          openTitle: 'Hide the checks',
          children: [
            for (final c in checks)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  SizedBox(width: 120, child: StatusBadge(fmt(c['status']), dense: true)),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(_words(fmt(c['check'])), style: AppTypography.muted.copyWith(color: AppColors.text)),
                      Text('value ${_short(c['value'])}, threshold ${_short(c['threshold'])}', style: AppTypography.caption),
                    ]),
                  ),
                ]),
              ),
          ],
        ),
      ]),
    );
  }

  static String _short(dynamic v) {
    final s = fmt(v);
    return s.length > 24 ? '${s.substring(0, 12)}…' : s;
  }
}
