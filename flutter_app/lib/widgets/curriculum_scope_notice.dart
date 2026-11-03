import 'package:flutter/material.dart';

import '../theme/design_system.dart';
import 'ui_kit.dart';

/// The run's curriculum scope (pipeline: curriculum_scope.py), shown before any gap figure.
///
/// INCOMPLETE    a prominent warning: the supplied curriculum lacks semesters of the programme, so skills absent from
///               it may be taught in the semesters that were not provided; its gaps are marked for review.
/// UNDETERMINED  a quiet note: the programme span could not be established, so scope was not checked.
/// COMPLETE / NOT_ASSESSED / missing   nothing is shown.
class CurriculumScopeNotice extends StatelessWidget {
  const CurriculumScopeNotice(this.scope, {super.key, this.scopeLimited});
  final Map<String, dynamic> scope;
  final int? scopeLimited;

  static String semesters(List<dynamic> s) {
    const roman = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII'];
    final n = s.whereType<num>().map((e) => e.toInt()).toList()..sort();
    String r(int v) => v >= 1 && v <= roman.length ? roman[v - 1] : '$v';
    final parts = <String>[];
    for (var i = 0; i < n.length; i++) {
      var j = i;
      while (j + 1 < n.length && n[j + 1] == n[j] + 1) {
        j++;
      }
      parts.add(i == j ? r(n[i]) : '${r(n[i])}–${r(n[j])}');
      i = j;
    }
    return parts.join(', ');
  }

  @override
  Widget build(BuildContext context) {
    final status = scope['status'];
    if (status == 'INCOMPLETE') {
      final supplied = semesters(asList(scope['target_semesters']));
      final missing = semesters(asList(scope['missing_semesters']));
      return Container(
        key: const ValueKey('curriculum-scope-incomplete'),
        margin: const EdgeInsets.only(bottom: AppSpacing.xxl),
        padding: const EdgeInsets.all(AppSpacing.xl),
        constraints: const BoxConstraints(maxWidth: AppLayout.measure + 80),
        decoration: BoxDecoration(
          border: Border(left: BorderSide(color: AppColors.warning, width: 3)),
          color: AppColors.warning.withValues(alpha: 0.08),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Incomplete curriculum: semesters $supplied only', style: AppTypography.title),
          const SizedBox(height: AppSpacing.sm),
          Text(
              'Skills absent from the supplied semesters may be taught in semesters $missing, which were not provided. '
              'Missing or partial coverage here is not a whole-programme deficiency: '
              '${scopeLimited == null ? 'these gaps are' : '$scopeLimited gap${scopeLimited == 1 ? ' is' : 's are'}'} '
              'marked for review and not counted as confirmed. Analyse the full curriculum to confirm them.',
              style: AppTypography.muted),
        ]),
      );
    }
    if (status == 'UNDETERMINED') {
      return Padding(
        key: const ValueKey('curriculum-scope-undetermined'),
        padding: const EdgeInsets.only(bottom: AppSpacing.xxl),
        child: Text('Curriculum scope could not be checked: ${fmt(scope['reason'])}.', style: AppTypography.caption),
      );
    }
    return const SizedBox.shrink();
  }
}
