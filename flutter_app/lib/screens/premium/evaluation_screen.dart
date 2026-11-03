import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../theme/design_system.dart';
import '../../theme/plain_language.dart';
import '../../widgets/ui_kit.dart';

/// Independent semantic AI evaluation. Until independent human labels exist the status is
/// PENDING_INDEPENDENT_LABELS and the model stays in SAFE MODE; an internal development preview is shown only with an
/// explicit "not independent" label.
class EvaluationScreen extends StatelessWidget {
  const EvaluationScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return ApiView(
      api: api,
      path: '/api/v1/evaluation/semantic',
      what: 'the AI evaluation',
      builder: (context, d, reload) {
        final gate = asMap(d['gate_declaration']);
        final criteria = asMap(gate['criteria']);
        final preview = asMap(d['internal_development_preview']);
        final systems = asMap(d['systems'] ?? preview['systems']);
        final independent = d['status'] == 'INDEPENDENTLY_EVALUATED';
        return PageFrame(children: [
          StatusBanner(
            status: fmt(d['status']),
            title: independent ? 'Independently evaluated' : 'Independent evaluation pending',
            body: independent
                ? 'Metrics below are computed against the independent benchmark (independent reviewers, rules for disagreements fixed in advance).'
                : '${Plain.sentence(fmt(d['reason']))}. Next: ${Plain.sentence(fmt(d['next_action']))}',
            children: [
              const SizedBox(height: AppSpacing.md),
              Wrap(spacing: AppSpacing.sm, children: [
                StatusBadge(fmt(d['mode'] ?? at(d, 'gate_result.mode'))),
                Text('${fmt(d['cases_in_benchmark'])} frozen cases', style: AppTypography.muted),
                Text('${asList(d['reviewers']).length} independent reviewer(s)', style: AppTypography.muted),
              ]),
            ],
          ),
          const SizedBox(height: AppSpacing.xl),
          SectionCard(
            title: 'Criteria the AI must meet before it is used (${fmt(gate['version'])})',
            subtitle: 'Declared ${fmt(gate['declared_at'])} — ${fmt(gate['declared_before'])}',
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              KeyValueList([for (final e in criteria.entries) MapEntry(Plain.field(e.key), e.value)],
                  labelWidth: 280),
              const SizedBox(height: AppSpacing.sm),
              Text('If it fails: ${fmt(gate['if_failed'])}', style: AppTypography.muted),
              Text('If it passes: ${fmt(gate['if_passed'])}', style: AppTypography.muted),
            ]),
          ),
          if (systems.isNotEmpty)
            SectionCard(
              title: independent ? 'AI compared with the fixed rules' : 'Internal development preview, not an independent evaluation',
              subtitle: independent
                  ? 'All cases of the frozen benchmark'
                  : fmt(preview['label_source']),
              trailing: independent ? null : const StatusBadge('REVIEW_REQUIRED', dense: true),
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(columns: const [
                  DataColumn(label: Text('system')),
                  DataColumn(label: Text('accuracy')),
                  DataColumn(label: Text('macro F1')),
                  DataColumn(label: Text('definite predictions')),
                  DataColumn(label: Text('precision on definite')),
                  DataColumn(label: Text('critical-error rate')),
                  DataColumn(label: Text('critical errors')),
                ], rows: [
                  for (final e in systems.entries)
                    DataRow(cells: [
                      DataCell(Text(e.key)),
                      DataCell(Text(fmt(at(e.value, 'accuracy')))),
                      DataCell(Text(fmt(at(e.value, 'macro_f1')))),
                      DataCell(Text(fmt(at(e.value, 'definite_predictions')))),
                      DataCell(Text(fmt(at(e.value, 'precision_on_definite')))),
                      DataCell(Text(fmt(at(e.value, 'critical_error_rate')))),
                      DataCell(ConstrainedBox(
                          constraints: const BoxConstraints(maxWidth: 420),
                          child: Text(fmt(at(e.value, 'critical_errors')), maxLines: 3, overflow: TextOverflow.ellipsis))),
                    ]),
                ]),
              ),
            ),
          if (asMap(d['baseline_vs_model'] ?? preview['baseline_vs_model']).isNotEmpty)
            SectionCard(
              title: 'Baseline vs model (per case)',
              subtitle: independent ? null : 'development labels — not independent',
              child: Column(children: [
                for (final e in asMap(d['baseline_vs_model'] ?? preview['baseline_vs_model']).entries)
                  KeyValueList([
                    MapEntry('${e.key}: both correct', at(e.value, 'both_correct')),
                    MapEntry('baseline correct / model incorrect', at(e.value, 'baseline_correct_model_incorrect')),
                    MapEntry('baseline incorrect / model correct', at(e.value, 'baseline_incorrect_model_correct')),
                    MapEntry('both incorrect', at(e.value, 'both_incorrect')),
                  ], labelWidth: 300),
              ]),
            ),
        ]);
      },
    );
  }
}
