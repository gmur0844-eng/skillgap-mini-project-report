// Curriculum scope on the overview and skill-gap pages: an incomplete curriculum is announced before any gap figure,
// its gaps read as "marked for review", and a complete or older run shows no warning.
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:skillgap_dashboard/screens/premium/skill_gaps_screen.dart';
import 'package:skillgap_dashboard/services/api_client.dart';
import 'package:skillgap_dashboard/widgets/curriculum_scope_notice.dart';

class _Api extends ApiClient {
  _Api(this.routes);
  final Map<String, dynamic> routes;

  @override
  Future<dynamic> getJson(String path, {Map<String, String>? query}) =>
      routes.containsKey(path) ? Future.value(routes[path]) : Future.error(ApiException('no route', statusCode: 404));
}

Map<String, dynamic> _gaps(Map<String, dynamic>? scope, {bool limited = false}) => {
      'evidence_state': 'AVAILABLE',
      'scope': {'run_id': 'r', if (scope != null) 'curriculum_scope': scope},
      'items': [
        {
          'skill_key': 'sql', 'skill_label': 'SQL', 'classification_v2': 'PARTIAL', 'support_state': 'HIGH_SUPPORT',
          'posting_count': 40, 'eligible_postings': 498, 'coverage_level': 'INTRODUCTORY',
          'evidence_status': limited ? 'REVIEW_REQUIRED' : 'INFERRED', 'scope_limited': limited,
          'actionable': !limited,
          if (limited)
            'review': {'code': 'CURRICULUM_SCOPE_INCOMPLETE', 'missing_semesters': [3, 4, 5, 6, 7, 8], 'detail': 'd'},
        },
      ],
    };

const _incomplete = {
  'status': 'INCOMPLETE', 'target_semesters': [1, 2], 'missing_semesters': [3, 4, 5, 6, 7, 8],
  'note': 'The target curriculum covers semesters I–II', 'expected_last_semester': 8,
};

Future<void> _open(WidgetTester tester, Map<String, dynamic> gaps) async {
  tester.view.physicalSize = const Size(1500, 1600);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: SkillGapsScreen(api: _Api({'/api/v1/intelligence/gaps': gaps})))));
  await tester.pumpAndSettle();
}

void main() {
  test('semester spans read as roman ranges', () {
    expect(CurriculumScopeNotice.semesters([1, 2]), 'I–II');
    expect(CurriculumScopeNotice.semesters([3, 4, 5, 6, 7, 8]), 'III–VIII');
    expect(CurriculumScopeNotice.semesters([1, 2, 3, 5]), 'I–III, V');
  });

  testWidgets('an incomplete curriculum is announced and its gaps are marked for review, not confirmed', (tester) async {
    await _open(tester, _gaps(_incomplete, limited: true));
    expect(find.byKey(const ValueKey('curriculum-scope-incomplete')), findsOneWidget);
    expect(find.text('Incomplete curriculum: semesters I–II only'), findsOneWidget);
    expect(find.textContaining('may be taught in semesters III–VIII'), findsOneWidget);
    expect(find.text('No confirmed skill gaps'), findsOneWidget);
    expect(find.textContaining('Marked for review: curriculum incomplete'), findsOneWidget);
    expect(find.textContaining('marked for review, not a confirmed gap'), findsOneWidget);
    expect(find.textContaining('a confirmed gap to review'), findsNothing);
  });

  testWidgets('a complete curriculum shows no scope warning and keeps its confirmed gap', (tester) async {
    await _open(tester, _gaps({'status': 'COMPLETE'}));
    expect(find.byKey(const ValueKey('curriculum-scope-incomplete')), findsNothing);
    expect(find.text('1 confirmed skill gap'), findsOneWidget);
    expect(find.textContaining(RegExp(r'Status\s+Confirmed gap$')), findsOneWidget);
  });

  testWidgets('a run made before the assessment shows no warning', (tester) async {
    await _open(tester, _gaps(null));
    expect(find.byKey(const ValueKey('curriculum-scope-incomplete')), findsNothing);
    expect(find.byKey(const ValueKey('curriculum-scope-undetermined')), findsNothing);
  });

  testWidgets('an undetermined scope is stated quietly', (tester) async {
    await _open(tester, _gaps({'status': 'UNDETERMINED', 'reason': 'the target curriculum carries no semester labels'}));
    expect(find.byKey(const ValueKey('curriculum-scope-undetermined')), findsOneWidget);
    expect(find.text('1 confirmed skill gap'), findsOneWidget);
  });

  test('the overview shows the same notice before its gap figures', () {
    final src = File('lib/screens/premium/overview_screen.dart').readAsStringSync();
    final notice = src.indexOf("CurriculumScopeNotice(asMap(d['curriculum_scope'])");
    expect(notice, greaterThan(0));
    expect(notice, lessThan(src.indexOf("_GapLine(asMap(d['gap_line'])),")));
  });
}
