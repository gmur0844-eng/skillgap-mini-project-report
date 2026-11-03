// Add evidence draft, document suggestions, analysis options, live progress, reconnecting and page guides.
// The fake API answers real endpoint paths with small payloads shaped like the backend's (TEST FIXTURES only).
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:skillgap_dashboard/main.dart';
import 'package:skillgap_dashboard/screens/ingestion_screen.dart';
import 'package:skillgap_dashboard/services/api_client.dart';
import 'package:skillgap_dashboard/shell/navigation.dart';
import 'package:skillgap_dashboard/shell/page_guides.dart';
import 'package:skillgap_dashboard/shell/run_context.dart';
import 'package:skillgap_dashboard/theme/design_system.dart';
import 'package:skillgap_dashboard/widgets/analysis_progress.dart';

class _Api extends ApiClient {
  _Api({this.routes = const {}, this.suggestions = const {}});
  final Map<String, dynamic> routes;
  final Map<String, dynamic> suggestions;
  final List<(String, Map<String, dynamic>)> posts = [];
  Map<String, dynamic> job = {'job_id': 'job-1', 'status': 'ANALYSIS_PENDING'};
  int inspections = 0;

  @override
  Future<dynamic> getJson(String path, {Map<String, String>? query}) {
    if (path == '/api/v1/analysis/jobs/active') return Future.value(routes[path] ?? {'job': null});
    if (path.startsWith('/api/v1/analysis/jobs/')) return Future.value(job);
    if (routes.containsKey(path)) return Future.value(routes[path]);
    return Future.error(ApiException('no route in test', statusCode: 404));
  }

  @override
  Future<dynamic> postJson(String path, Map<String, dynamic> body) {
    posts.add((path, body));
    return Future.value(job);
  }

  @override
  Future<Map<String, dynamic>> inspectCurriculum({required List<int> fileBytes, required String fileName}) {
    inspections++;
    return Future.value({'suggestions': suggestions});
  }

  @override
  Future<Map<String, dynamic>> ingestCurriculum({
    required List<int> fileBytes,
    required String fileName,
    String? institution,
    String? programme,
    Map<String, String>? fields,
  }) =>
      Future.value({
        'status': 'succeeded',
        'upload_id': 'upl-abc123',
        'outcome': {
          'outcome': 'SUCCESSFUL_AND_USABLE',
          'counts': {'courses': 25, 'modules': 60, 'topics': 1299, 'outcomes': 480},
          'reasons': <String>[],
        },
        'metadata': {
          'values': {'institution': institution, 'programme': programme}
        },
      });
}

const _roles = {
  'roles': [
    {
      'role': 'TARGET',
      'required': ['institution', 'programme', 'discipline', 'curriculum_version'],
      'recommended': ['academic_year', 'degree_level', 'specialization'],
      'description': 'A programme curriculum of an institution.',
    }
  ],
  'fields': {
    'institution': 'Institution',
    'programme': 'Programme',
    'discipline': 'Discipline',
    'curriculum_version': 'Curriculum version',
    'academic_year': 'Academic year',
    'degree_level': 'Degree level',
    'specialization': 'Specialisation',
  },
};

const _found = {
  'institution': {
    'field': 'institution',
    'value': 'VASAVI COLLEGE OF ENGINEERING',
    'status': 'FOUND',
    'evidence': {'page': 1, 'text': 'VASAVI COLLEGE OF ENGINEERING (AUTONOMOUS)'},
  },
  'curriculum_version': {
    'field': 'curriculum_version',
    'value': null,
    'status': 'UNCERTAIN',
    'evidence': {'page': 1, 'text': '(R-26)'},
    'candidates': [
      {'value': 'R26', 'page': 1, 'text': '(R-26)'},
      {'value': 'R22', 'page': 2, 'text': 'superseding R22'},
    ],
  },
};

Future<void> _wide(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1400, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

Future<void> _openForm(WidgetTester tester, _Api api, AnalysisContext ctx) async {
  await tester.pumpWidget(MaterialApp(
    theme: buildAppTheme(),
    home: Scaffold(body: RunScope(context: ctx, child: IngestionScreen(apiClient: api))),
  ));
  await tester.pumpAndSettle();
}

Future<void> _pickFile(WidgetTester tester) async {
  IngestionScreen.debugPicker = (ext) async => const PickedUpload('01-syllabus-2026-27.pdf', [1, 2, 3]);
  addTearDown(() => IngestionScreen.debugPicker = null);
  await tester.tap(find.text('Choose file'));
  await tester.pumpAndSettle();
}

Finder _field(String label) => find.widgetWithText(TextField, label);

/// Unmounts the widgets before the context they listen to is disposed (and lets pending timers, such as a
/// notification's, finish), so no test leaves state behind for the next one.
Future<void> _close(WidgetTester tester, AnalysisContext ctx) async {
  await tester.pumpWidget(const SizedBox());
  await tester.pump(const Duration(seconds: 5));
  ctx.dispose();
}

void main() {
  group('draft', () {
    testWidgets('what was chosen and typed survives leaving the page and coming back', (tester) async {
      await _wide(tester);
      final api = _Api(routes: const {'/api/v1/metadata/document-roles': _roles});
      final ctx = AnalysisContext(api);
      await _openForm(tester, api, ctx);
      await _pickFile(tester);
      await tester.enterText(_field('Programme (required)'), 'B.E. CSE (AIML)');
      await tester.tap(find.text('Peer comparison'));
      await tester.pump();

      // navigate away inside the same themed app, as the shell does: the page is disposed, the session's context stays.
      // (Swapping in an unthemed MaterialApp would animate between two different themes, which the app never does.)
      await tester.pumpWidget(MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(body: RunScope(context: ctx, child: const Text('another page'))),
      ));
      await tester.pumpAndSettle();
      expect(find.byType(IngestionScreen), findsNothing); // the page really is gone
      await _openForm(tester, api, ctx); // and back

      expect(find.text('01-syllabus-2026-27.pdf'), findsOneWidget); // the file, kept in memory
      expect(find.text('B.E. CSE (AIML)'), findsOneWidget);
      final peers = tester.widget<CheckboxListTile>(find.widgetWithText(CheckboxListTile, 'Peer comparison'));
      expect(peers.value, isFalse);
      expect(find.textContaining('a browser reload clears the form'), findsOneWidget); // the honest limit
      await _close(tester, ctx);
    });

    testWidgets('clearing asks first; "Keep editing" keeps everything', (tester) async {
      await _wide(tester);
      final api = _Api(routes: const {'/api/v1/metadata/document-roles': _roles});
      final ctx = AnalysisContext(api);
      await _openForm(tester, api, ctx);
      await tester.enterText(_field('Programme (required)'), 'B.Tech CSE');
      await tester.pump();
      await tester.tap(find.text('Clear form'));
      await tester.pumpAndSettle();
      expect(find.text('Clear this form?'), findsOneWidget);
      await tester.tap(find.text('Keep editing'));
      await tester.pumpAndSettle();
      expect(find.text('B.Tech CSE'), findsOneWidget);

      await tester.tap(find.text('Clear form'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Clear form'));
      await tester.pumpAndSettle();
      expect(find.text('B.Tech CSE'), findsNothing);
      expect(ctx.draft.isEmpty, isTrue);
      await _close(tester, ctx);
    });
  });

  group('simplified form', () {
    testWidgets('required fields come first with their reason; the rest is folded away', (tester) async {
      await _wide(tester);
      final api = _Api(routes: const {'/api/v1/metadata/document-roles': _roles});
      final ctx = AnalysisContext(api);
      await _openForm(tester, api, ctx);
      for (final f in ['Institution', 'Programme', 'Discipline', 'Curriculum version']) {
        expect(_field('$f (required)'), findsOneWidget, reason: f);
      }
      expect(find.textContaining('so no other institution\'s results are ever mixed in'), findsOneWidget);
      expect(find.text('More details (optional)'), findsOneWidget);
      expect(_field('Academic year'), findsNothing); // folded
      await tester.tap(find.text('More details (optional)'));
      await tester.pumpAndSettle();
      expect(_field('Academic year'), findsOneWidget);
      // upload needs a file and the required fields
      expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Upload and extract')).onPressed, isNull);
      await _close(tester, ctx);
    });

    testWidgets('values found in the document are filled in with their evidence; a disagreement is a choice',
        (tester) async {
      await _wide(tester);
      final api = _Api(routes: const {'/api/v1/metadata/document-roles': _roles}, suggestions: _found);
      final ctx = AnalysisContext(api);
      await _openForm(tester, api, ctx);
      await _pickFile(tester);
      expect(api.inspections, 1);
      expect(find.text('VASAVI COLLEGE OF ENGINEERING'), findsOneWidget);
      expect(find.textContaining('Found in the document (page 1: “VASAVI COLLEGE OF ENGINEERING (AUTONOMOUS)”)'),
          findsOneWidget);
      // the regulation was read two ways: nothing is chosen, both are offered
      expect(find.textContaining('more than one reading'), findsOneWidget);
      expect(find.widgetWithText(ActionChip, 'R26'), findsOneWidget);
      expect(find.widgetWithText(ActionChip, 'R22'), findsOneWidget);
      await tester.tap(find.widgetWithText(ActionChip, 'R26'));
      await tester.pumpAndSettle();
      expect(ctx.draft.values['curriculum_version'], 'R26');
      // editing a suggested value makes it the person's own
      await tester.enterText(_field('Institution (required)'), 'Vasavi College of Engineering');
      await tester.pump();
      expect(ctx.draft.suggested.contains('institution'), isFalse);
      expect(find.textContaining('Found in the document'), findsNothing);
      await _close(tester, ctx);
    });

    testWidgets('leaving peers and industry out is sent with the analysis request', (tester) async {
      await _wide(tester);
      final api = _Api(routes: const {'/api/v1/metadata/document-roles': _roles});
      final ctx = AnalysisContext(api, pollInterval: const Duration(hours: 1));
      await _openForm(tester, api, ctx);
      await _pickFile(tester);
      for (final e in {'Institution': 'Vasavi', 'Programme': 'B.E.', 'Discipline': 'CSE', 'Curriculum version': 'R26'}.entries) {
        await tester.enterText(_field('${e.key} (required)'), e.value);
      }
      await tester.tap(find.text('Industry evidence'));
      await tester.tap(find.text('Peer comparison'));
      await tester.pump();
      await tester.tap(find.text('Upload and extract'));
      await tester.pump();
      await tester.pump();
      final start = api.posts.firstWhere((p) => p.$1 == '/api/v1/analysis/jobs');
      expect(start.$2['options'], {'peers': false, 'industry': false});
      expect(ctx.options, {'peers': false, 'industry': false});
      await _close(tester, ctx); // also lets the upload notification's timer finish
    });
  });

  group('progress', () {
    Map<String, dynamic> phase(String id, String label, String status, {List<Map<String, dynamic>> steps = const [],
            String? reason, double duration = 0}) =>
        {'id': id, 'label': label, 'agent': null, 'explains': 'explains $id', 'status': status, 'steps': steps,
          'reason': reason, 'duration_s': duration};

    testWidgets('phases show their real state, the running step, what was produced, and no percentage', (tester) async {
      await _wide(tester);
      final job = {
        'job_id': 'job-1',
        'status': 'ANALYSIS_PENDING',
        'phases': [
          phase('extraction', 'Reading the documents', 'COMPLETED', duration: 2.6, steps: [
            {'stage': 'bronze.extract', 'status': 'COMPLETED', 'counts': {'pages': 214}},
            {'stage': 'silver.structure', 'status': 'COMPLETED', 'counts': {'valid_courses': 25}},
          ]),
          phase('skill_intelligence', 'Skill intelligence', 'RUNNING', steps: [
            {'stage': 'industry.extract', 'status': 'RUNNING', 'detail': null},
          ]),
          phase('peer_comparison', 'Peer comparison', 'NOT_REQUESTED', reason: 'peer comparison was not requested'),
          phase('finalisation', 'Finalising', 'PENDING'),
        ],
      };
      await tester.pumpWidget(MaterialApp(theme: buildAppTheme(), home: Scaffold(body: AnalysisProgress(job: job))));
      await tester.pump();
      expect(find.text('1. Reading the documents'), findsOneWidget);
      expect(find.text('Done'), findsOneWidget);
      expect(find.textContaining('214 pages · 25 courses'), findsOneWidget);
      expect(find.textContaining('took 3 s'), findsOneWidget);
      expect(find.text('In progress'), findsOneWidget);
      expect(find.text('Finding skills in postings and curricula'), findsOneWidget);
      expect(find.text('Waiting'), findsOneWidget);
      // a capability left out by choice is listed once, not as a step that failed
      expect(find.textContaining('Not part of this analysis (as you chose): peer comparison'), findsOneWidget);
      expect(find.textContaining('%'), findsNothing);
    });

    testWidgets('a failed phase shows its error and a phase that did not run says why, in words', (tester) async {
      await _wide(tester);
      final job = {
        'phases': [
          phase('extraction', 'Reading the documents', 'FAILED', steps: [
            {'stage': 'bronze.extract', 'status': 'FAILED', 'error': 'RuntimeError: pdftotext crashed'},
          ]),
          phase('recommendations', 'Recommendations', 'NOT_RUN', reason: 'the analysis stopped before this step'),
        ],
      };
      await tester.pumpWidget(MaterialApp(theme: buildAppTheme(), home: Scaffold(body: AnalysisProgress(job: job))));
      await tester.pump();
      expect(find.text('Failed'), findsOneWidget);
      expect(find.textContaining('pdftotext crashed'), findsOneWidget);
      expect(find.text('Not run'), findsOneWidget);
      expect(find.text('the analysis stopped before this step'), findsOneWidget);
    });
  });

  group('reconnecting', () {
    test('after a reload the running analysis is found and followed again', () async {
      final api = _Api(routes: {
        '/api/v1/analysis/jobs/active': {
          'job': {'job_id': 'job-9', 'upload_id': 'upl-abc123', 'status': 'ANALYSIS_PENDING', 'options': {'peers': false}}
        },
        '/api/v1/uploads/upl-abc123': {
          'metadata': {'institution': 'Vasavi', 'programme': 'B.E.'},
          'outcome': {'outcome': 'SUCCESSFUL_AND_USABLE'}
        },
      })
        ..job = {'job_id': 'job-9', 'status': 'ANALYSIS_PENDING', 'phases': []};
      final ctx = AnalysisContext(api, pollInterval: const Duration(hours: 1));
      await ctx.recover();
      expect(ctx.status, 'ANALYSIS_PENDING');
      expect(ctx.job?['job_id'], 'job-9');
      expect(ctx.options, {'peers': false});
      expect((ctx.upload?['metadata'] as Map)['values'], {'institution': 'Vasavi', 'programme': 'B.E.'});
      ctx.dispose();
    });

    test('nothing running: the published analysis stays in view', () async {
      final ctx = AnalysisContext(_Api());
      await ctx.recover();
      expect(ctx.status, 'LATEST');
      ctx.dispose();
    });

    test('a failed job is retried by the server with its own options', () async {
      final api = _Api()..job = {'job_id': 'job-3', 'status': 'ANALYSIS_FAILED', 'reason': 'interrupted'};
      final ctx = AnalysisContext(api, pollInterval: const Duration(hours: 1));
      ctx.job = api.job;
      api.job = {'job_id': 'job-4', 'status': 'ANALYSIS_PENDING'};
      await ctx.retry();
      expect(api.posts.single.$1, '/api/v1/analysis/jobs/job-3/retry');
      expect(ctx.status, 'ANALYSIS_PENDING');
      ctx.dispose();
    });
  });

  group('page guides', () {
    test('every page has a guide written in plain words', () {
      for (final e in allEntries) {
        final g = pageGuides[e.dest];
        expect(g, isNotNull, reason: e.label);
        for (final text in [g!.shows, g.why, g.evidence, g.next]) {
          expect(text.trim(), isNotEmpty, reason: e.label);
          for (final term in const ['TARGET', 'PREVIOUS_VERSION', 'GOLD', 'SILVER', 'BRONZE', 'gate', '_']) {
            expect(text.contains(term), isFalse, reason: '${e.label}: "$term" in "$text"');
          }
        }
        expect(g.nextDest == e.dest, isFalse, reason: '${e.label} points to itself');
      }
    });

    testWidgets('the guide opens to why it matters, the evidence and the next step', (tester) async {
      await _wide(tester);
      final api = _Api(routes: const {
        '/api/v1/overview': {
          'evidence_state': 'AVAILABLE',
          'run': {'run_id': 'oldrun0000000001', 'generated_at': '2026-09-27T00:00:00Z'},
          'target': {'institution': 'Old Institute', 'curriculum_version': 'R1'},
          'kpis': [
            {'key': 'courses', 'label': 'Target-curriculum courses', 'value': 99, 'context': 'target', 'source': 's'}
          ],
          'findings': [
            {'kind': 'GAPS', 'title': 'Old run finding', 'statement': 'from the old run', 'target': 'skillGaps'}
          ],
          'evidence_status': {},
          'semantic': {'mode': 'SAFE_MODE', 'mode_label': 'AI interpretation is advisory'},
        }
      });
      await tester.pumpWidget(SkillGapApp(apiClient: api));
      await tester.pumpAndSettle();
      expect(find.textContaining('About this page: ${pageGuides[Dest.overview]!.shows}'), findsOneWidget);
      expect(find.textContaining('Why it matters.'), findsNothing);
      await tester.tap(find.text('More'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Why it matters.'), findsOneWidget);
      expect(find.textContaining('Evidence behind it.'), findsOneWidget);
      expect(find.text('Go to Skill-gap analysis'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });
  });
}
