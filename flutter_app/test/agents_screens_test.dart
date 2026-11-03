// The analysis-agents and experimental gap-review screens: real API shapes, plain words, the experimental label.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:skillgap_dashboard/screens/knowledge_screens.dart';
import 'package:skillgap_dashboard/services/api_client.dart';
import 'package:skillgap_dashboard/shell/navigation.dart';

class _Api extends ApiClient {
  _Api(this.routes);
  final Map<String, dynamic> routes;

  @override
  Future<dynamic> getJson(String path, {Map<String, String>? query}) =>
      routes.containsKey(path) ? Future.value(routes[path]) : Future.error(ApiException('no route', statusCode: 404));
}

final _routes = <String, dynamic>{
  '/api/v1/agents': {
    'run_id': 'testrun0000000001',
    'coordination': 'Curriculum Understanding -> Discipline-to-Industry Relevance -> Skill Intelligence -> '
        'Skill-Gap Reasoning -> Curriculum Recommendation',
    'semantic_model': 'advisory under Safe Mode in every agent',
    'note': 'Agents are pipeline components with defined inputs and outputs.',
    'items': [
      {'order': 1, 'name': 'Curriculum Understanding', 'responsibility': 'Reads each curriculum.',
        'status': 'AVAILABLE', 'experimental_status': 'AVAILABLE'},
      {'order': 5, 'name': 'Curriculum Recommendation', 'responsibility': 'Turns gaps into changes.',
        'status': 'PARTIAL', 'experimental_status': 'NONE'},
    ],
  },
  '/api/v1/agents/gap-review': {
    'evidence_state': 'AVAILABLE',
    'authority': 'EXPERIMENTAL',
    'label': 'Experimental gap review: awaiting human review before it replaces the authoritative skill gaps',
    'states': {'STRUCTURAL_GAP': 1, 'LIMITED_COVERAGE': 1},
    'note': 'Other curricula are shown as context and never decide a state.',
    'total': 2,
    'items': [
      {'skill_label': 'TypeScript', 'gap_state': 'STRUCTURAL_GAP', 'authoritative_classification': 'INSUFFICIENT_EVIDENCE',
        'coverage_level': 'ABSENT', 'access': 'NONE', 'practice': 'NONE', 'other_curricula': 'peer: 1 of 3 teach it',
        'reason': 'no syllabus topic, course title or outcome teaches it'},
      {'skill_label': 'kubernetes', 'gap_state': 'LIMITED_COVERAGE', 'authoritative_classification': 'COVERED',
        'coverage_level': 'SUBSTANTIAL', 'access': 'ELECTIVE_ONLY', 'practice': 'PAIRED_PRACTICAL',
        'other_curricula': 'peer: 2 of 3 teach it', 'reason': 'taught only in elective option(s) 22ITE11'},
    ],
  },
};

Future<void> _open(WidgetTester tester, String title) async {
  tester.view.physicalSize = const Size(1500, 1400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(home: Scaffold(body: KnowledgeScreen(apiClient: _Api(_routes), spec: specNamed(title)))));
  await tester.pumpAndSettle();
}

void main() {
  test('both screens are reachable from the navigation', () {
    expect(allEntries.where((e) => e.spec == 'Analysis Agents'), hasLength(1));
    expect(allEntries.where((e) => e.spec == 'Gap Review (experimental)'), hasLength(1));
    expect(groupOf(Dest.gapReview), 'Evidence & quality'); // not among the main results
  });

  testWidgets('analysis agents: the five-part order and their status in words', (tester) async {
    await _open(tester, 'Analysis Agents');
    expect(find.textContaining('Curriculum Understanding'), findsWidgets);
    expect(find.textContaining('Available'), findsWidgets);
    expect(find.textContaining('AVAILABLE'), findsNothing);
  });

  testWidgets('gap review: experimental, states in plain words beside the main analysis', (tester) async {
    await _open(tester, 'Gap Review (experimental)');
    expect(find.textContaining('Experimental gap review'), findsWidgets);
    expect(find.textContaining('Not taught'), findsWidgets);
    expect(find.textContaining('Electives only'), findsWidgets);
    expect(find.textContaining('STRUCTURAL_GAP'), findsNothing);
    expect(find.textContaining('ELECTIVE_ONLY'), findsNothing);
  });
}
