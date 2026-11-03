// Reviewer validation: two reviewers compared question by question; disagreements and missing answers are visible;
// the page never presents the responses as independent labels or says validation is complete while answers are
// missing; the assistant's label appears only as a separate AI reference.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:skillgap_dashboard/screens/premium/reviewer_validation.dart';
import 'package:skillgap_dashboard/services/api_client.dart';
import 'package:skillgap_dashboard/theme/design_system.dart';

const _schema = [
  {'code': 'CHILD', 'form_choice': 'C — Child / more specific concept'},
  {'code': 'PARENT', 'form_choice': 'B — Parent / broader concept'},
  {'code': 'SAME_CONCEPT', 'form_choice': 'A — Same concept'},
];

Map<String, dynamic> _packages(List<String> reviewers) => {
      'items': [
        {'package': 'test/v1', 'reviewers': reviewers, 'label_schema': _schema}
      ],
      'reviewer_sources': {'HUMAN_AI_ASSISTED': 'a person answered after reading about the topics with an AI assistant'},
    };

Map<String, dynamic> _answer(String? label, {String status = 'COMPLETED', String? reasoning}) =>
    {'status': status, 'label': label, 'confidence': label == null ? null : 'HIGH', 'reasoning': reasoning};

Map<String, dynamic> _q(int n, String id, {String? ai}) => {
      'question_number': n, 'concept_a': 'A$n', 'concept_b': 'B$n', 'context_a': ['line $n'],
      'question': 'What is the relationship of Concept A (A$n) to Concept B (B$n)?',
      'ai_reference': ai == null ? null : {'label': ai, 'is_human_judgment': false},
    };

Map<String, dynamic> _compare({bool pending = false}) => {
      'reviewers': ['R02', 'R03'],
      'imports': [
        {'reviewer_id': 'R02', 'reviewer_source': 'HUMAN_AI_ASSISTED', 'source_notes': ['all 5 submissions share one timestamp']},
        {'reviewer_id': 'R03', 'reviewer_source': 'HUMAN_AI_ASSISTED', 'source_notes': []},
      ],
      'items': [
        {'question_id': 'bm1-001', 'R02': _answer('CHILD', reasoning: 'AWS is a provider'), 'R03': _answer('CHILD'),
         'comparison': 'AGREE', 'question': _q(1, 'bm1-001', ai: 'SAME_CONCEPT')},
        {'question_id': 'bm1-002', 'R02': _answer('PARENT'), 'R03': _answer('CHILD'), 'comparison': 'DISAGREE',
         'question': _q(2, 'bm1-002')},
        {'question_id': 'bm1-003', 'R02': _answer('CHILD'),
         'R03': pending ? _answer(null, status: 'PENDING') : _answer('CHILD'),
         'comparison': pending ? 'NOT_COMPARABLE' : 'AGREE', 'question': _q(3, 'bm1-003')},
      ],
      'metrics': {
        'questions_in_package': 3,
        'per_reviewer': {
          'R02': {'assessments_present': 3},
          'R03': {'assessments_present': pending ? 2 : 3},
        },
        'both_completed': pending ? 2 : 3, 'agreements': pending ? 1 : 2, 'disagreements': 1,
        'agreement_rate': pending ? 0.5 : 0.6667, 'cohen_kappa': 0.4,
        'definitions': {'agreement_rate': 'agreements / both_completed'}, 'unavailable': {},
      },
    };

class _Api extends ApiClient {
  _Api({this.reviewers = const ['R01', 'R02', 'R03'], this.pending = false});
  final List<String> reviewers;
  final bool pending;
  final calls = <String>[];

  @override
  Future<dynamic> getJson(String path, {Map<String, String>? query}) async {
    calls.add('$path ${query ?? {}}');
    if (path.endsWith('/packages')) return _packages(reviewers);
    if (path.endsWith('/compare')) return _compare(pending: pending);
    throw StateError('unexpected $path');
  }
}

Future<void> _pump(WidgetTester tester, ApiClient api) async {
  tester.view.physicalSize = const Size(1400, 5000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(theme: buildAppTheme(), home: Scaffold(body: ReviewerValidationView(api: api))));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('no imported responses: says how to import, shows no figures', (tester) async {
    await _pump(tester, _Api(reviewers: const []));
    expect(find.text('No reviewer responses imported'), findsOneWidget);
    expect(find.text('Agreement'), findsNothing);
  });

  testWidgets('R02 and R03 by default; disagreements and the source of the answers are shown', (tester) async {
    final api = _Api();
    await _pump(tester, api);
    expect(api.calls.last, contains('{a: R02, b: R03}'));
    expect(find.textContaining('not independent labels'), findsOneWidget);
    expect(find.textContaining('reading about the topics with an AI assistant'), findsOneWidget);
    expect(find.textContaining('Source note: all 5 submissions share one timestamp'), findsOneWidget);
    expect(find.text('Different'), findsOneWidget);
    expect(find.text('B — Parent / broader concept'), findsNWidgets(2)); // R02's answer, and its filter chip
    await tester.tap(find.text('Different (1)'));
    await tester.pumpAndSettle();
    expect(find.text('Case 2 · bm1-002'), findsOneWidget);
    expect(find.text('Case 1 · bm1-001'), findsNothing);
  });

  testWidgets('missing answers: never called complete, shown as not answered', (tester) async {
    await _pump(tester, _Api(pending: true));
    expect(find.text('Validation incomplete: 1 answer(s) not completed'), findsOneWidget);
    expect(find.text('Not answered yet'), findsOneWidget);
    expect(find.text('Not comparable'), findsOneWidget);
  });

  testWidgets('the AI reference is separate and labelled as not a reviewer answer', (tester) async {
    await _pump(tester, _Api());
    expect(find.textContaining('AI reference'), findsNothing); // only inside the opened evidence
    await tester.tap(find.text('Question and evidence').first);
    await tester.pumpAndSettle();
    expect(find.textContaining('not a reviewer answer and not in any figure): A — Same concept'), findsOneWidget);
  });

  test('comparison as CSV', () {
    final csv = comparisonCsv(_compare());
    final lines = csv.trim().split('\n');
    expect(lines.first, startsWith('question_id,concept_a,concept_b,R02_relationship'));
    expect(lines[2], '"bm1-002","A2","B2","PARENT","HIGH","COMPLETED","CHILD","HIGH","COMPLETED","DISAGREE"');
  });
}
