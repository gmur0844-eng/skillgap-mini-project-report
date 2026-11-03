// Upload -> analysis -> dashboard workflow, ingestion result states, stale-run protection and contrast.
// A FakeApi answers the real endpoint paths with small fixed payloads shaped like the backend's responses; these are
// TEST FIXTURES that exercise rendering states (never shown in the app).
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:skillgap_dashboard/main.dart';
import 'package:skillgap_dashboard/screens/ingestion_screen.dart';
import 'package:skillgap_dashboard/services/api_client.dart';
import 'package:skillgap_dashboard/shell/run_context.dart';
import 'package:skillgap_dashboard/theme/design_system.dart';

class FakeApi extends ApiClient {
  FakeApi(this.routes);
  final Map<String, dynamic> routes;

  /// Every GET as actually sent: path plus the run-scoped query.
  final List<(String, Map<String, String>?)> gets = [];
  final List<String> posts = [];
  Object? postError;
  Object? jobError;
  Map<String, dynamic> job = {'job_id': 'job-1', 'status': 'ANALYSIS_PENDING'};
  Map<String, dynamic> ingestion = _usable;

  @override
  Future<dynamic> getJson(String path, {Map<String, String>? query}) {
    gets.add((path, scopedQuery(path, query)));
    if (path.startsWith('/api/v1/analysis/jobs/')) {
      if (jobError != null) return Future.error(jobError!);
      return Future.value(job);
    }
    if (routes.containsKey(path)) return Future.value(routes[path]);
    return Future.error(ApiException('no route in test', statusCode: 404));
  }

  @override
  Future<dynamic> postJson(String path, Map<String, dynamic> body) {
    posts.add(path);
    if (postError != null) return Future.error(postError!);
    return Future.value(job);
  }

  @override
  Future<Map<String, dynamic>> ingestCurriculum({
    required List<int> fileBytes,
    required String fileName,
    String? institution,
    String? programme,
    Map<String, String>? fields,
  }) =>
      Future.value(ingestion);

  @override
  Future<Map<String, dynamic>> inspectCurriculum({required List<int> fileBytes, required String fileName}) =>
      Future.value(const {'suggestions': <String, dynamic>{}});

  /// Overview requests sent after index [from].
  List<(String, Map<String, String>?)> overviewCallsSince(int from) =>
      gets.sublist(from).where((g) => g.$1 == '/api/v1/overview').toList();
}

Map<String, dynamic> _outcome(String outcome, Map<String, int> counts, {double conf = 0.8, List<String> reasons = const []}) => {
      'outcome': outcome,
      'execution_status': outcome == 'EXECUTION_FAILED' ? 'FAILED' : 'SUCCEEDED',
      'extraction_status': outcome == 'SUCCESSFUL_AND_USABLE'
          ? 'EXTRACTED'
          : outcome == 'EXECUTION_FAILED'
              ? 'EXTRACTION_FAILED'
              : outcome == 'NEEDS_REVIEW'
                  ? 'PARTIAL_EXTRACTION'
                  : 'NO_USABLE_CONTENT',
      'quality_status': 'OK',
      'review_status': outcome == 'SUCCESSFUL_AND_USABLE' ? 'NOT_REQUIRED' : 'REVIEW_REQUIRED',
      'usable_for_analysis': outcome == 'SUCCESSFUL_AND_USABLE',
      'counts': counts,
      'extraction_confidence': conf,
      'reasons': reasons,
      'next_action': 'test next action',
    };

final Map<String, dynamic> _usable = {
  'status': 'succeeded',
  'document_id': 'doc-7f3a9e',
  'upload_id': 'upl-abc123',
  'outcome': _outcome('SUCCESSFUL_AND_USABLE', {'courses': 12, 'modules': 40, 'topics': 300, 'outcomes': 60}),
  'metadata': {
    'values': {'institution': 'Test University', 'programme': 'B.Sc. Test', 'curriculum_version': 'v2'}
  },
};

final _overview = <String, dynamic>{
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
};

Future<void> _wide(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1400, 1000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

/// Opens New analysis, picks a file and uploads it (the result is the FakeApi's [FakeApi.ingestion]).
Future<int> _upload(WidgetTester tester, FakeApi api) async {
  IngestionScreen.debugPicker = (ext) async => const PickedUpload('curriculum.pdf', [1, 2, 3]);
  addTearDown(() => IngestionScreen.debugPicker = null);
  await tester.pumpWidget(SkillGapApp(apiClient: api));
  await tester.pumpAndSettle();
  expect(find.text('Old run finding'), findsWidgets); // the latest published run before the upload
  final nav = find.widgetWithText(ListTile, 'New analysis');
  await tester.scrollUntilVisible(nav, 200, scrollable: find.byType(Scrollable).first);
  await tester.tap(nav);
  await tester.pumpAndSettle();
  expect(find.text('What are you adding?'), findsOneWidget);
  await tester.ensureVisible(find.text('Choose file'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Choose file'));
  await tester.pumpAndSettle();
  expect(find.text('curriculum.pdf'), findsOneWidget);
  final mark = api.gets.length;
  await tester.ensureVisible(find.text('Upload and extract'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Upload and extract'));
  await tester.pump(); // ingestion result
  await tester.pump(); // analysis job posted
  await tester.pump(const Duration(milliseconds: 400)); // page transition
  return mark;
}

/// Unmounts the app so the analysis poll timer and snack bar are disposed before the test ends.
Future<void> _finish(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox());
  await tester.pump(const Duration(seconds: 5));
}

void main() {
  group('upload -> dashboard', () {
    testWidgets('a usable upload opens Overview in the pending state and never shows the old run', (tester) async {
      await _wide(tester);
      final api = FakeApi({'/api/v1/overview': _overview});
      final mark = await _upload(tester, api);
      expect(api.posts, contains('/api/v1/analysis/jobs'));
      expect(find.text('Curriculum added'), findsOneWidget);
      expect(find.text('Analysis is being prepared'), findsOneWidget);
      expect(find.textContaining('Curriculum uploaded successfully — 12 courses'), findsOneWidget); // notification
      expect(find.text('Old run finding'), findsNothing);
      expect(find.text('99'), findsNothing);
      expect(api.overviewCallsSince(mark), isEmpty); // no stale GOLD requested
      expect(find.textContaining('analysis being prepared'), findsOneWidget); // top-bar context line
      await _finish(tester);
    });

    testWidgets('when the analysis is ready, every request is scoped to the new run', (tester) async {
      await _wide(tester);
      final api = FakeApi({'/api/v1/overview': _overview});
      final mark = await _upload(tester, api);
      api.job = {'job_id': 'job-1', 'status': 'ANALYSIS_READY', 'run_id': 'newrun0000000002'};
      await tester.pump(const Duration(seconds: 4)); // next poll
      await tester.pump(const Duration(milliseconds: 400));
      final calls = api.overviewCallsSince(mark);
      expect(calls, isNotEmpty);
      for (final c in calls) {
        expect(c.$2?['run_id'], 'newrun0000000002');
      }
      expect(find.textContaining('Showing the analysis of B.Sc. Test'), findsOneWidget);
      await _finish(tester);
    });

    testWidgets('analysis endpoint unavailable: no stale data, "not yet run" with Run analysis', (tester) async {
      await _wide(tester);
      final api = FakeApi({'/api/v1/overview': _overview})
        ..postError = ApiException('analysis service unavailable', statusCode: 503);
      final mark = await _upload(tester, api);
      expect(find.text('Curriculum added'), findsOneWidget);
      expect(find.text('The curriculum has been read. Its analysis has not been run yet.'), findsOneWidget);
      expect(find.text('The analysis could not be started.'), findsOneWidget); // what happened
      expect(find.text('Analysis service unavailable'), findsOneWidget); // why, in words
      expect(find.text('What you can do'), findsOneWidget);
      expect(find.text('Run analysis'), findsOneWidget);
      expect(find.text('Old run finding'), findsNothing);
      expect(api.overviewCallsSince(mark), isEmpty);
      // retry once the service is back
      api.postError = null;
      await tester.tap(find.text('Run analysis'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('Analysis is being prepared'), findsOneWidget);
      await _finish(tester);
    });

    testWidgets('job status unavailable keeps the pending state and says so', (tester) async {
      await _wide(tester);
      final api = FakeApi({'/api/v1/overview': _overview})..jobError = ApiException('timeout', statusCode: 504);
      final mark = await _upload(tester, api);
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.text('Analysis is being prepared'), findsOneWidget);
      expect(find.textContaining('analysis status unavailable'), findsOneWidget);
      expect(api.overviewCallsSince(mark), isEmpty);
      await _finish(tester);
    });

    testWidgets('a failed analysis offers retry and the explicit way back to the latest run', (tester) async {
      await _wide(tester);
      final api = FakeApi({'/api/v1/overview': _overview});
      await _upload(tester, api);
      api.job = {'job_id': 'job-1', 'status': 'ANALYSIS_FAILED', 'reason': 'pipeline error'};
      await tester.pump(const Duration(seconds: 4));
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('The analysis did not finish'), findsOneWidget);
      expect(find.text('The analysis stopped before it produced results.'), findsOneWidget);
      expect(find.text('Analysis error'), findsOneWidget); // the reason, in words
      expect(find.text('Run analysis again'), findsOneWidget);
      await tester.tap(find.text('Show the published analysis instead'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('Old run finding'), findsWidgets);
      await _finish(tester);
    });
    testWidgets('an analysis that needs review explains what, why and what to do -- never in backend terms',
        (tester) async {
      await _wide(tester);
      final api = FakeApi({'/api/v1/overview': _overview});
      await _upload(tester, api);
      const raw = 'analytics gates blocked: concept_drift: needs healthy TARGET + PREVIOUS_VERSION documents of the same '
          'programme with at least one comparable semester';
      api.job = {'job_id': 'job-1', 'status': 'NEEDS_REVIEW', 'run_id': 'newrun0000000003', 'reason': raw};
      await tester.pump(const Duration(seconds: 4));
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('The analysis needs review'), findsOneWidget);
      expect(find.text('We couldn\'t compare this curriculum with an earlier version yet.'), findsOneWidget); // what
      expect(find.textContaining('An earlier curriculum for the same programme is required'), findsOneWidget); // why
      expect(find.text('What you can do'), findsOneWidget);
      expect(find.text('• Upload an earlier curriculum for the same programme'), findsOneWidget);
      expect(find.text('• Run the analysis again'), findsOneWidget);
      expect(find.text('Review extraction'), findsOneWidget);
      expect(find.text('Run analysis again'), findsOneWidget);
      for (final w in tester.widgetList<Text>(find.byType(Text))) {
        final t = w.data ?? w.textSpan?.toPlainText() ?? '';
        for (final term in const ['TARGET', 'PREVIOUS_VERSION', 'concept_drift', 'analytics gate', 'NEEDS_REVIEW']) {
          expect(t.contains(term), isFalse, reason: 'normal view shows "$term" in "$t"');
        }
      }
      // the backend's own words stay available, intentionally, in the technical details
      await tester.ensureVisible(find.text('Technical details'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Technical details'));
      await tester.pumpAndSettle();
      expect(find.text(raw), findsOneWidget);
      await _finish(tester);
    });
  });

  group('ingestion result states', () {
    Future<void> show(WidgetTester tester, Map<String, dynamic> result, {String kind = 'TARGET'}) async {
      await _wide(tester);
      await tester.pumpWidget(MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: IngestionResultView(
              result: result,
              kind: kind,
              onAnalyse: ({String? reviewedBy}) {},
              onReview: () {},
              onDashboard: () {},
              onAnother: () {},
              reviewer: TextEditingController(),
            ),
          ),
        ),
      ));
      await tester.pumpAndSettle();
    }

    testWidgets('successful and usable', (tester) async {
      await show(tester, _usable);
      expect(find.text('Curriculum evidence added'), findsOneWidget);
      expect(find.text('Open curriculum intelligence →'), findsOneWidget);
      expect(find.text('300'), findsOneWidget); // topics
      expect(find.textContaining('doc-7f3a9e'), findsNothing); // ids are never the primary result
      expect(find.text('Technical details'), findsOneWidget);
    });

    for (final c in [
      ('zero courses', {'courses': 0, 'modules': 0, 'topics': 0, 'outcomes': 0}, 0.6),
      ('zero topics', {'courses': 3, 'modules': 2, 'topics': 0, 'outcomes': 4}, 0.6),
      ('confidence 0', {'courses': 3, 'modules': 2, 'topics': 9, 'outcomes': 4}, 0.0),
    ]) {
      testWidgets('succeeded but no usable content: ${c.$1}', (tester) async {
        await show(tester, {
          'status': 'succeeded',
          'outcome': _outcome('EXECUTION_SUCCEEDED_BUT_NO_USABLE_CONTENT', c.$2, conf: c.$3, reasons: ['nothing usable']),
        });
        expect(find.text('Processing completed, but no usable curriculum content was extracted — review required'),
            findsOneWidget);
        expect(find.text('Review extraction'), findsOneWidget);
        expect(find.text('View preprocessing'), findsOneWidget);
        expect(find.text('Return to dashboard'), findsOneWidget);
        expect(find.text('Open curriculum intelligence →'), findsNothing); // never flows downstream
        expect(find.textContaining('Successfully'), findsNothing);
      });
    }

    testWidgets('flagged extraction needs review and offers accept-after-review', (tester) async {
      await show(tester, {
        'status': 'succeeded',
        'outcome': _outcome('NEEDS_REVIEW', {'courses': 3, 'modules': 2, 'topics': 9, 'outcomes': 4},
            reasons: ['flagged for review by the extractor']),
      });
      expect(find.text('Extracted, but it needs review before analysis'), findsOneWidget);
      expect(find.text('Accept after review'), findsOneWidget);
      expect(find.text('Open curriculum intelligence →'), findsNothing);
    });

    testWidgets('execution failed', (tester) async {
      await show(tester, {
        'status': 'failed',
        'outcome': _outcome('EXECUTION_FAILED', {'courses': 0, 'modules': 0, 'topics': 0, 'outcomes': 0}),
      });
      expect(find.text('Processing failed — review error details'), findsOneWidget);
      expect(find.text('Open curriculum intelligence →'), findsNothing);
    });

    testWidgets('upload failure says "Upload failed" with retry and collapsed technical details', (tester) async {
      await _wide(tester);
      var retried = false;
      await tester.pumpWidget(MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: UploadFailedView(
              error: ApiException('institution is required', statusCode: 422, code: 'METADATA_INCOMPLETE'),
              onRetry: () => retried = true,
            ),
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Upload failed'), findsOneWidget);
      expect(find.textContaining('Some required information'), findsOneWidget);
      expect(find.text('Technical details'), findsOneWidget);
      expect(find.textContaining('422'), findsNothing); // collapsed
      await tester.tap(find.text('Retry'));
      expect(retried, isTrue);
    });
  });

  group('run context', () {
    test('a ready analysis scopes analytics requests; ingestion and metadata stay unscoped', () async {
      final api = FakeApi(const {})..job = {'job_id': 'j', 'status': 'ANALYSIS_READY', 'run_id': 'r-new'};
      final ctx = AnalysisContext(api, pollInterval: const Duration(milliseconds: 1));
      await ctx.analyseUpload(_usable);
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(ctx.status, 'ANALYSIS_READY');
      expect(api.scopedQuery('/api/v1/overview', null), {'run_id': 'r-new'});
      expect(api.scopedQuery('/api/v1/skills', {'q': 'x'}), {'q': 'x', 'run_id': 'r-new'});
      expect(api.scopedQuery('/api/v1/metadata/disciplines', null), isNull);
      expect(api.scopedQuery('/api/v1/analysis/jobs/j', null), isNull);
      ctx.showLatest();
      expect(api.runId, isNull);
      expect(ctx.blocksOldResults, isFalse);
      ctx.dispose();
    });

    test('pending, not-run, failed and needs-review all block older results', () {
      final ctx = AnalysisContext(FakeApi(const {}));
      for (final s in ['ANALYSIS_PENDING', 'ANALYSIS_NOT_RUN', 'ANALYSIS_FAILED', 'NEEDS_REVIEW']) {
        ctx.status = s;
        expect(ctx.blocksOldResults, isTrue, reason: s);
      }
      ctx.status = 'ANALYSIS_READY';
      expect(ctx.blocksOldResults, isFalse);
      ctx.dispose();
    });

    test('an upload without a staged id is not analysed and says why', () async {
      final api = FakeApi(const {});
      final ctx = AnalysisContext(api);
      await ctx.analyseUpload({'status': 'succeeded'});
      expect(ctx.status, 'ANALYSIS_NOT_RUN');
      expect(api.posts, isEmpty);
      ctx.dispose();
    });
  });

  group('accessibility', () {
    test('text and status colours meet WCAG AA (4.5:1) on every background, in both designs and both modes', () {
      for (final palette in const [Palette.v1Dark, Palette.v1Light, Palette.v2Dark, Palette.v2Light]) {
        final fgs = {
          'text': palette.text,
          'textMuted': palette.textMuted,
          'textFaint': palette.textFaint,
          'primary': palette.primary,
          'secondary': palette.secondary,
          'success': palette.success,
          'warning': palette.warning,
          'danger': palette.danger,
          'info': palette.info,
          'neutral': palette.neutral,
        };
        final bgs = {
          'bg0': palette.bg0,
          'bg1': palette.bg1,
          'surface': palette.surface,
          'surfaceRaised': palette.surfaceRaised,
          'surfaceSunken': palette.surfaceSunken,
        };
        for (final f in fgs.entries) {
          for (final b in bgs.entries) {
            expect(AppColors.contrast(f.value, b.value), greaterThanOrEqualTo(4.5),
                reason: '${palette.brightness} ${f.key} on ${b.key}');
          }
        }
        // text on the accent, and on the primary button
        expect(AppColors.contrast(palette.onPrimary, palette.primary), greaterThanOrEqualTo(4.5));
        expect(AppColors.contrast(palette.onFill, palette.fill), greaterThanOrEqualTo(4.5));
        // the navigation column (Version 2: stone text on bordeaux)
        for (final f in [palette.navText, palette.navMuted, palette.navFaint, palette.navAccent]) {
          for (final b in [palette.navBg, palette.navSelected]) {
            expect(AppColors.contrast(f, b), greaterThanOrEqualTo(4.5), reason: '${palette.brightness} navigation');
          }
        }
        // never pure black with pure white
        expect([palette.bg0, palette.text].contains(const Color(0xFF000000)) &&
            [palette.bg0, palette.text].contains(const Color(0xFFFFFFFF)), isFalse);
      }
    });
  });
}
