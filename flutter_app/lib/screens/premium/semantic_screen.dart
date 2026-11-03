import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../theme/design_system.dart';
import '../../theme/plain_language.dart';
import '../../widgets/ui_kit.dart';
import 'pages.dart';
import 'reviewer_validation.dart';

/// Semantic decisions as trust information: which pairs a model looked at, what it suggested, what the validator
/// accepted, and whether the result was allowed to change analytics. A blocked effect is SAFE MODE working as
/// designed, not a failure.
class SemanticScreen extends StatelessWidget {
  const SemanticScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return TabbedPage(
      labels: const ['Decisions', 'Decision table', 'Reviewer validation'],
      builder: (context, i) => i == 2
          ? ReviewerValidationView(api: api)
          : i == 1
          ? specView(api, 'Semantic Decisions')
          : ApiView(
              api: api,
              path: '/api/v1/semantic/decisions',
              query: const {'limit': '1000'},
              what: 'the AI decisions',
              builder: (context, d, reload) => _Decisions(data: d),
            ),
    );
  }
}

class _Decisions extends StatefulWidget {
  const _Decisions({required this.data});
  final Map<String, dynamic> data;

  @override
  State<_Decisions> createState() => _DecisionsState();
}

class _DecisionsState extends State<_Decisions> {
  String? _kind;
  String? _validated;
  static const _pageSize = 50;
  int _page = 0;

  static Map<String, int> _count(Iterable<dynamic> rows, String key) {
    final out = <String, int>{};
    for (final r in rows) {
      final v = fmt(at(r, key));
      out[v] = (out[v] ?? 0) + 1;
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    final all = asList(widget.data['items']);
    final applied = all.where((r) => at(r, 'effect') != null).length;
    final blocked = all.where((r) => at(r, 'effect_blocked_reason') != null).length;
    final modelled = all.where((r) => at(r, 'model') != null).length;
    final human = all.where((r) => at(r, 'is_human_validated') == true).length;
    final safeMode = applied == 0;
    final kinds = _count(all, 'candidate_kind');
    final validated = _count(all, 'validated_state');
    final rows = all
        .where((r) => (_kind == null || at(r, 'candidate_kind') == _kind) &&
            (_validated == null || at(r, 'validated_state') == _validated))
        .toList();
    final pages = rows.isEmpty ? 1 : (rows.length + _pageSize - 1) ~/ _pageSize;
    final page = _page < pages ? _page : pages - 1;
    final visible = rows.skip(page * _pageSize).take(_pageSize).toList();

    return PageFrame(children: [
      StatusBanner(
        status: safeMode ? 'SAFE_MODE' : 'PARTIAL',
        title: safeMode ? 'AI interpretation is advisory — it does not change results' : 'Validated AI decisions are applied',
        body: safeMode
            ? 'Every decision below is recorded with its evidence, but none was applied: the AI has not yet passed its '
                'independent evaluation. Fixed, documented rules decide what the analysis uses.'
            : '$applied decision(s) changed the analysis; the rest stay recorded only.',
      ),
      const SizedBox(height: AppSpacing.xl),
      Wrap(spacing: AppSpacing.md, runSpacing: AppSpacing.md, children: [
        KpiCard(value: widget.data['total'] ?? all.length, label: 'Decisions', icon: Icons.psychology_outlined),
        KpiCard(value: modelled, label: 'Seen by a model', caption: 'the rest are rule verdicts'),
        KpiCard(value: applied, label: 'Applied to the analysis', icon: Icons.check_circle_outline),
        KpiCard(value: blocked, label: 'Not applied', caption: 'kept as suggestions', icon: Icons.shield_outlined),
        KpiCard(value: human, label: 'Human-validated', icon: Icons.how_to_reg_outlined),
      ]),
      const SizedBox(height: AppSpacing.lg),
      SectionCard(
        title: 'Validator outcome',
        subtitle: 'What the evidence validator accepted for each model answer',
        child: DistributionBar(counts: validated),
      ),
      Wrap(spacing: AppSpacing.sm, runSpacing: AppSpacing.sm, children: [
        for (final k in [null, ...kinds.keys])
          ChoiceChip(
            label: Text(k == null ? 'All kinds' : '${k.replaceAll('_', ' ').toLowerCase()} (${kinds[k]})'),
            selected: _kind == k,
            onSelected: (_) => setState(() {
              _kind = k;
              _page = 0;
            }),
          ),
      ]),
      const SizedBox(height: AppSpacing.sm),
      Wrap(spacing: AppSpacing.sm, runSpacing: AppSpacing.sm, children: [
        for (final v in [null, ...validated.keys])
          ChoiceChip(
            label: Text(v == null ? 'All outcomes' : '${StatusStyle.label(v)} (${validated[v]})'),
            selected: _validated == v,
            onSelected: (_) => setState(() {
              _validated = v;
              _page = 0;
            }),
          ),
      ]),
      const SizedBox(height: AppSpacing.md),
      if (rows.isEmpty)
        const EmptyState(title: 'No decisions', body: 'No AI decision matches these filters in this analysis.')
      else ...[
        for (final r in visible) _DecisionCard(d: asMap(r)),
        Row(mainAxisAlignment: MainAxisAlignment.end, children: [
          Text('${page * _pageSize + 1}–${page * _pageSize + visible.length} of ${rows.length}',
              style: AppTypography.caption),
          IconButton(
              tooltip: 'Previous page',
              onPressed: page == 0 ? null : () => setState(() => _page = page - 1),
              icon: const Icon(Icons.chevron_left)),
          IconButton(
              tooltip: 'Next page',
              onPressed: page >= pages - 1 ? null : () => setState(() => _page = page + 1),
              icon: const Icon(Icons.chevron_right)),
        ]),
      ],
    ]);
  }
}

class _DecisionCard extends StatelessWidget {
  const _DecisionCard({required this.d});
  final Map<String, dynamic> d;

  @override
  Widget build(BuildContext context) {
    final evidence = asList(d['evidence']);
    final effect = d['effect'];
    final blocked = d['effect_blocked_reason'];
    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      padding: const EdgeInsets.only(top: AppSpacing.lg),
      decoration: BoxDecoration(border: Border(top: BorderSide(color: AppColors.border))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: AppSpacing.sm, runSpacing: AppSpacing.xs, children: [
          Text(fmt(d['left']), style: AppTypography.section),
          Icon(Icons.swap_horiz, size: 18, color: AppColors.textMuted, semanticLabel: 'compared with'),
          Text(fmt(d['right']), style: AppTypography.section),
        ]),
        const SizedBox(height: AppSpacing.sm),
        Wrap(spacing: AppSpacing.sm, runSpacing: AppSpacing.xs, children: [
          Text(fmt(d['candidate_kind']).replaceAll('_', ' ').toLowerCase(), style: AppTypography.caption),
          Text('relationship: ${StatusStyle.label(fmt(d['relationship']))}', style: AppTypography.caption),
          StatusBadge(fmt(d['decision_state']), dense: true),
          StatusBadge(fmt(d['validated_state']), dense: true),
          if (d['is_human_validated'] != true) Text('not human-validated', style: AppTypography.caption),
        ]),
        const SizedBox(height: AppSpacing.sm),
        Text(
          effect != null
              ? 'Applied to analytics: ${fmt(effect)}'
              : blocked != null
                  ? 'Not applied — ${fmt(blocked)} (advisory only)'
                  : 'Not applied — recorded for audit only',
          style: AppTypography.muted,
        ),
        EvidencePanel(
          title: 'Evidence and provenance',
          summary: '${fmt(d['provider'])} · ${fmt(d['model'] ?? 'no model')} · ${fmt(d['prompt_version'])}',
          children: [
            EvidenceStep(label: 'Reason', child: Text(Plain.sentence(fmt(d['reason'])), style: AppTypography.muted)),
            if (d['uncertainty'] != null)
              EvidenceStep(label: 'Uncertainty', child: Text(fmt(d['uncertainty']), style: AppTypography.muted)),
            EvidenceStep(
              label: 'Cited evidence',
              child: evidence.isEmpty
                  ? Text('none cited', style: AppTypography.caption)
                  : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      for (final e in evidence)
                        Text('${fmt(at(e, 'ref'))} · ${Plain.value(at(e, 'source_type'), fallback: fmt)}: ${at(e, 'quote') ?? '—'}',
                            style: AppTypography.caption),
                    ]),
            ),
            if (asList(d['validation_errors']).isNotEmpty)
              EvidenceStep(
                  label: 'Validator',
                  child: Text(asList(d['validation_errors']).map(fmt).join('\n'), style: AppTypography.caption)),
            EvidenceStep(
              label: 'Technical record',
              last: true,
              child: Text('${fmt(d['decision_id'])} · ${fmt(d['timestamp'])} · ${fmt(d['schema_version'])}',
                  style: AppTypography.mono),
            ),
          ],
        ),
      ]),
    );
  }
}
