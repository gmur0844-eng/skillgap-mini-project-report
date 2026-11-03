import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../services/api_client.dart';
import '../../theme/design_system.dart';
import '../../widgets/ui_kit.dart';

/// Reviewer responses of the semantic validation form: two reviewers side by side on every question, their
/// disagreements, what is still missing, and the figures with their definitions. The responses are research records,
/// not independent labels: the page says how they were produced and never presents them as the gold standard.
/// The assistant's own label of a case is shown apart, as an AI reference, and never in any figure.
class ReviewerValidationView extends StatelessWidget {
  const ReviewerValidationView({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return ApiView(
      api: api,
      path: '/api/v1/semantic-validation/packages',
      what: 'the validation packages',
      builder: (context, d, reload) {
        final pkg = asList(d['items']).isEmpty ? null : asMap(asList(d['items']).first);
        final reviewers = pkg == null ? <String>[] : asList(pkg['reviewers']).map((e) => '$e').toList();
        if (pkg == null || reviewers.length < 2) {
          return PageFrame(children: [
            EmptyState(
              title: 'No reviewer responses imported',
              body: 'Import the validation form responses (.xlsx or .csv) to compare reviewers: '
                  'python3 scripts/evaluation/semantic_validation.py import-responses --package '
                  'data/evaluation/semantic_gold/<discipline>/v1 --file <responses> --source <how they were produced>',
            ),
          ]);
        }
        return _Comparison(api: api, package: pkg, reviewers: reviewers, sources: asMap(d['reviewer_sources']));
      },
    );
  }
}

class _Comparison extends StatefulWidget {
  const _Comparison({required this.api, required this.package, required this.reviewers, required this.sources});
  final ApiClient api;
  final Map<String, dynamic> package;
  final List<String> reviewers;
  final Map<String, dynamic> sources;

  @override
  State<_Comparison> createState() => _ComparisonState();
}

class _ComparisonState extends State<_Comparison> {
  late String _a;
  late String _b;

  @override
  void initState() {
    super.initState();
    final r = widget.reviewers;
    _a = r.contains('R02') ? 'R02' : r[0];
    _b = r.contains('R03') && _a != 'R03' ? 'R03' : r.firstWhere((x) => x != _a);
  }

  /// Picking the reviewer already on the other side swaps the two, so the pair always holds two reviewers.
  void _choose({String? first, String? second}) {
    if (first != null) {
      if (first == _b) _b = _a;
      _a = first;
    }
    if (second != null) {
      if (second == _a) _a = _b;
      _b = second;
    }
  }

  Widget _picker(String label, String value, ValueChanged<String> onChanged) => Row(mainAxisSize: MainAxisSize.min, children: [
        Text(label, style: AppTypography.muted),
        const SizedBox(width: AppSpacing.sm),
        DropdownButton<String>(
          value: value,
          items: [for (final r in widget.reviewers) DropdownMenuItem(value: r, child: Text(r))],
          onChanged: (v) => v == null ? null : onChanged(v),
        ),
      ]);

  @override
  Widget build(BuildContext context) {
    final choices = <String, String>{
      for (final l in asList(widget.package['label_schema'])) '${at(l, 'code')}': '${at(l, 'form_choice') ?? at(l, 'code')}'
    };
    return ApiView(
      key: ValueKey('$_a|$_b'),
      api: widget.api,
      path: '/api/v1/semantic-validation/compare',
      query: {'a': _a, 'b': _b},
      what: 'the reviewer comparison',
      builder: (context, d, reload) => _ComparisonBody(
        data: d,
        a: _a,
        b: _b,
        choices: choices,
        sources: widget.sources,
        pickers: Wrap(spacing: AppSpacing.xl, runSpacing: AppSpacing.sm, children: [
          _picker('Reviewer', _a, (v) => setState(() => _choose(first: v))),
          _picker('compared with', _b, (v) => setState(() => _choose(second: v))),
        ]),
      ),
    );
  }
}

/// The comparison as CSV: one row per question with both reviewers' relationship, confidence and the outcome.
String comparisonCsv(Map<String, dynamic> data) {
  final rv = asList(data['reviewers']).map((e) => '$e').toList();
  String q(dynamic v) => '"${(v ?? '').toString().replaceAll('"', '""')}"';
  final lines = <String>[
    [
      'question_id', 'concept_a', 'concept_b', '${rv[0]}_relationship', '${rv[0]}_confidence', '${rv[0]}_status',
      '${rv[1]}_relationship', '${rv[1]}_confidence', '${rv[1]}_status', 'comparison'
    ].join(',')
  ];
  for (final r in asList(data['items'])) {
    final a = asMap(at(r, rv[0])), b = asMap(at(r, rv[1]));
    lines.add([
      q(at(r, 'question_id')), q(at(r, 'question.concept_a')), q(at(r, 'question.concept_b')),
      q(a['label']), q(a['confidence']), q(a['status']), q(b['label']), q(b['confidence']), q(b['status']),
      q(at(r, 'comparison')),
    ].join(','));
  }
  return '${lines.join('\n')}\n';
}

class _ComparisonBody extends StatefulWidget {
  const _ComparisonBody(
      {required this.data, required this.a, required this.b, required this.choices, required this.sources, required this.pickers});
  final Map<String, dynamic> data;
  final String a;
  final String b;
  final Map<String, String> choices;
  final Map<String, dynamic> sources;
  final Widget pickers;

  @override
  State<_ComparisonBody> createState() => _ComparisonBodyState();
}

class _ComparisonBodyState extends State<_ComparisonBody> {
  String? _outcome;
  String? _label;

  @override
  Widget build(BuildContext context) {
    final d = widget.data;
    final m = asMap(d['metrics']);
    final per = asMap(m['per_reviewer']);
    final items = asList(d['items']);
    final n = m['questions_in_package'] ?? items.length;
    final notDone = [for (final r in [widget.a, widget.b]) (n is int ? n : 0) - ((at(per, '$r.assessments_present') ?? 0) as int)];
    final complete = notDone.every((x) => x == 0);
    final imports = asList(d['imports']);
    final notes = {for (final f in imports) ...asList(at(f, 'source_notes')).map((e) => '$e')};
    final labels = <String>{
      for (final r in items) ...[at(r, '${widget.a}.label'), at(r, '${widget.b}.label')].whereType<String>()
    }.toList()
      ..sort();
    final rows = items
        .where((r) =>
            (_outcome == null || at(r, 'comparison') == _outcome) &&
            (_label == null || at(r, '${widget.a}.label') == _label || at(r, '${widget.b}.label') == _label))
        .toList();
    String pct(dynamic v) => v == null ? '—' : '${((v as num) * 100).toStringAsFixed(1)}%';

    return PageFrame(children: [
      StatusBanner(
        status: complete ? 'PARTIAL' : 'PENDING',
        title: complete
            ? 'Reviewer responses — shown and compared, not independent labels'
            : 'Validation incomplete: ${notDone[0] + notDone[1]} answer(s) not completed',
        body: 'These responses do not count towards the gold labels or the AI promotion gate. '
            '${[
          for (final f in imports)
            '${at(f, 'reviewer_id')}: ${widget.sources['${at(f, 'reviewer_source')}'] ?? at(f, 'reviewer_source')}'
        ].join('; ')}.',
        children: [for (final note in notes) Text('Source note: $note', style: AppTypography.caption)],
      ),
      widget.pickers,
      const SizedBox(height: AppSpacing.lg),
      Wrap(spacing: AppSpacing.md, runSpacing: AppSpacing.md, children: [
        KpiCard(value: n, label: 'Questions'),
        KpiCard(value: at(per, '${widget.a}.assessments_present') ?? 0, label: '${widget.a} answered'),
        KpiCard(value: at(per, '${widget.b}.assessments_present') ?? 0, label: '${widget.b} answered'),
        KpiCard(value: m['both_completed'] ?? 0, label: 'Answered by both'),
        KpiCard(value: m['agreements'] ?? 0, label: 'Same relationship'),
        KpiCard(value: m['disagreements'] ?? 0, label: 'Different relationship'),
        KpiCard(value: pct(m['agreement_rate']), label: 'Agreement', caption: 'of questions answered by both'),
        KpiCard(value: m['cohen_kappa'] == null ? '—' : '${m['cohen_kappa']}', label: "Cohen's kappa",
            caption: 'agreement beyond chance'),
      ]),
      const SizedBox(height: AppSpacing.lg),
      Row(children: [
        Expanded(
          child: Wrap(spacing: AppSpacing.sm, runSpacing: AppSpacing.sm, children: [
            for (final o in const [null, 'DISAGREE', 'AGREE', 'NOT_COMPARABLE'])
              ChoiceChip(
                label: Text(o == null
                    ? 'All (${items.length})'
                    : '${_OutcomeTag.words[o]} (${items.where((r) => at(r, 'comparison') == o).length})'),
                selected: _outcome == o,
                onSelected: (_) => setState(() => _outcome = o),
              ),
          ]),
        ),
        TextButton.icon(
          icon: const Icon(Icons.copy_outlined, size: 16),
          label: const Text('Copy as CSV'),
          onPressed: () => Clipboard.setData(ClipboardData(text: comparisonCsv(d))),
        ),
      ]),
      const SizedBox(height: AppSpacing.sm),
      Wrap(spacing: AppSpacing.sm, runSpacing: AppSpacing.sm, children: [
        for (final l in [null, ...labels])
          ChoiceChip(
            label: Text(l == null ? 'Any relationship' : (widget.choices[l] ?? l)),
            selected: _label == l,
            onSelected: (_) => setState(() => _label = l),
          ),
      ]),
      const SizedBox(height: AppSpacing.md),
      if (rows.isEmpty)
        const EmptyState(title: 'No question matches', body: 'No question matches these filters.')
      else
        for (final r in rows) _QuestionCard(row: asMap(r), a: widget.a, b: widget.b, choices: widget.choices),
      const SizedBox(height: AppSpacing.lg),
      EvidenceDisclosure(
        title: 'How these figures are calculated',
        children: [
          KeyValueList([
            for (final e in asMap(m['definitions']).entries) MapEntry(e.key.replaceAll('_', ' '), e.value),
            for (final e in asMap(m['unavailable']).entries) MapEntry('${e.key.replaceAll('_', ' ')} unavailable', e.value),
          ]),
        ],
      ),
    ]);
  }
}

class _OutcomeTag extends StatelessWidget {
  const _OutcomeTag(this.outcome);
  final String outcome;
  static const words = {'AGREE': 'Same', 'DISAGREE': 'Different', 'NOT_COMPARABLE': 'Not comparable'};

  @override
  Widget build(BuildContext context) {
    final color = outcome == 'DISAGREE'
        ? AppColors.warning
        : outcome == 'AGREE'
            ? AppColors.success
            : AppColors.neutral;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm, vertical: AppSpacing.xxs),
      decoration: BoxDecoration(border: Border.all(color: color), borderRadius: BorderRadius.circular(4)),
      child: Text(words[outcome] ?? outcome, style: AppTypography.caption.copyWith(color: color)),
    );
  }
}

class _QuestionCard extends StatelessWidget {
  const _QuestionCard({required this.row, required this.a, required this.b, required this.choices});
  final Map<String, dynamic> row;
  final String a;
  final String b;
  final Map<String, String> choices;

  Widget _answer(String reviewer) {
    final s = asMap(row[reviewer]);
    final status = '${s['status']}';
    final label = s['label'];
    return Expanded(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(reviewer, style: AppTypography.caption),
        Text(
          label != null
              ? (choices['$label'] ?? '$label')
              : status == 'PENDING'
                  ? 'Not answered yet'
                  : status == 'NOT_IMPORTED'
                      ? 'No response imported'
                      : 'Needs review (${status.toLowerCase().replaceAll('_', ' ')})',
          style: AppTypography.section,
        ),
        if (s['confidence'] != null) Text('Confidence: ${'${s['confidence']}'.toLowerCase()}', style: AppTypography.muted),
        if (s['reasoning'] != null) Text('${s['reasoning']}', style: AppTypography.muted),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final q = asMap(row['question']);
    final ai = asMap(q['ai_reference']);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: SectionCard(
        title: 'Case ${q['question_number'] ?? ''} · ${row['question_id']}',
        subtitle: '${q['concept_a']}  →  ${q['concept_b']}',
        trailing: _OutcomeTag('${row['comparison']}'),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _answer(a),
            const SizedBox(width: AppSpacing.lg),
            _answer(b),
          ]),
          EvidenceDisclosure(
            title: 'Question and evidence',
            children: [
              if (q['question'] != null) Text('${q['question']}', style: AppTypography.body),
              Text('Concept A: ${q['concept_a']}', style: AppTypography.section),
              for (final line in asList(q['context_a'])) Text('· $line', style: AppTypography.muted),
              Text('Concept B: ${q['concept_b']}', style: AppTypography.section),
              if (q['description_b'] != null) Text('${q['description_b']}', style: AppTypography.muted),
              if (ai['label'] != null)
                Container(
                  margin: const EdgeInsets.only(top: AppSpacing.sm),
                  padding: const EdgeInsets.all(AppSpacing.sm),
                  color: AppColors.surfaceSunken,
                  child: Text(
                      'AI reference (assistant development label, not a reviewer answer and not in any figure): '
                      '${choices['${ai['label']}'] ?? ai['label']}',
                      style: AppTypography.caption),
                ),
            ],
          ),
        ]),
      ),
    );
  }
}
