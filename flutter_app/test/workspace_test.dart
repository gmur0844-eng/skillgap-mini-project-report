// Information architecture, History, Settings (discipline support) and the peer chooser of New analysis.
// The fake API answers real endpoint paths with small payloads shaped like the backend's (TEST FIXTURES only).
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:skillgap_dashboard/screens/ingestion_screen.dart';
import 'package:skillgap_dashboard/screens/premium/history_screen.dart';
import 'package:skillgap_dashboard/screens/premium/settings_screen.dart';
import 'package:skillgap_dashboard/screens/premium/skill_gaps_screen.dart';
import 'package:skillgap_dashboard/services/api_client.dart';
import 'package:skillgap_dashboard/shell/evidence_draft.dart';
import 'package:skillgap_dashboard/shell/navigation.dart';
import 'package:skillgap_dashboard/shell/page_guides.dart';
import 'package:skillgap_dashboard/shell/run_context.dart';
import 'package:skillgap_dashboard/theme/design_system.dart';

class _Api extends ApiClient {
  _Api(this.routes);
  final Map<String, dynamic> routes;
  final List<(String, Map<String, dynamic>)> posts = [];
  final List<(String, Map<String, String>?)> gets = [];

  @override
  Future<dynamic> getJson(String path, {Map<String, String>? query}) {
    gets.add((path, query));
    if (routes.containsKey(path)) return Future.value(routes[path]);
    return Future.error(ApiException('no route in test', statusCode: 404));
  }

  @override
  Future<dynamic> postJson(String path, Map<String, dynamic> body) {
    posts.add((path, body));
    return Future.value({'job_id': 'job-new', 'status': 'ANALYSIS_PENDING'});
  }

  @override
  Future<Map<String, dynamic>> inspectCurriculum({required List<int> fileBytes, required String fileName}) =>
      Future.value({'suggestions': <String, dynamic>{}});

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

Future<void> _wide(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1400, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

Widget _host(AnalysisContext ctx, Widget child) =>
    MaterialApp(theme: buildAppTheme(), home: Scaffold(body: RunScope(context: ctx, child: child)));

Future<void> _close(WidgetTester tester, AnalysisContext ctx) async {
  await tester.pumpWidget(const SizedBox());
  await tester.pump(const Duration(seconds: 5));
  ctx.dispose();
}

const _jobs = {
  'evidence_state': 'AVAILABLE',
  'items': [
    {
      'job_id': 'job-000000000001',
      'upload_id': 'upl-1',
      'status': 'ANALYSIS_READY',
      'run_id': 'run0000000000001',
      'created_at': '2026-10-14T09:00:00+00:00',
      'finished_at': '2026-10-14T09:01:10+00:00',
      'options': {'peers': true, 'industry': true, 'peer_ids': ['nitw']},
      'document': {'institution': 'Vasavi College of Engineering', 'programme': 'B.E. CSE', 'curriculum_version': 'R26'},
      'discipline_profile': {'id': 'cse', 'name': 'Computer Science and Engineering'},
      'reason': null,
    },
    {
      'job_id': 'job-000000000002',
      'upload_id': 'upl-2',
      'status': 'ANALYSIS_FAILED',
      'run_id': null,
      'created_at': '2026-10-13T08:00:00+00:00',
      'finished_at': '2026-10-13T08:00:30+00:00',
      'options': {'peers': false, 'industry': false},
      'document': {'institution': 'Example Institute', 'programme': 'B.Tech Civil', 'curriculum_version': 'R24'},
      'reason': 'the analysis was interrupted (the service stopped); run it again',
    },
  ],
};

const _profiles = {
  'evidence_state': 'AVAILABLE',
  'version': 'discipline-profiles-v1',
  'profiles': [
    {
      'id': 'cse',
      'name': 'Computer Science and Engineering',
      'short': 'CSE',
      'capabilities': {
        'curriculum_analysis': 'AVAILABLE',
        'industry_analysis': 'AVAILABLE',
        'reference_mapping': 'AVAILABLE',
        'peer_comparison': 'AVAILABLE',
      },
      'evidence': {'industry_sources': 15, 'reference_curricula': ['aicte'], 'peer_curricula': ['iitk', 'nitw', 'nitt']},
      'knowledge_areas': ['Algorithms and data structures'],
      'occupation_examples': ['Software developer'],
      'validation': 'Validated with real data: the published release analyses a CSE curriculum.',
    },
    {
      'id': 'civil',
      'name': 'Civil Engineering',
      'short': 'Civil',
      'capabilities': {
        'curriculum_analysis': 'AVAILABLE',
        'industry_analysis': 'NO_RELEVANT_EVIDENCE',
        'reference_mapping': 'NO_REFERENCE_CURRICULUM',
        'peer_comparison': 'NO_PEER_CURRICULUM',
      },
      'evidence': {'industry_sources': 0, 'reference_curricula': <String>[], 'peer_curricula': <String>[]},
      'knowledge_areas': ['Structural engineering'],
      'occupation_examples': ['Civil engineer'],
      'validation': 'Curriculum analysis only: no job-posting evidence for civil-engineering roles has been supplied.',
    },
  ],
};

const _roles = {
  'roles': [
    {
      'role': 'TARGET',
      'required': ['institution', 'programme', 'discipline', 'curriculum_version'],
      'recommended': <String>[],
      'description': 'A programme curriculum of an institution.',
    }
  ],
  'fields': {
    'institution': 'Institution',
    'programme': 'Programme',
    'discipline': 'Discipline',
    'curriculum_version': 'Curriculum version',
  },
};

const _targets = {
  'evidence_state': 'AVAILABLE',
  'discipline_profile': {'id': 'cse', 'name': 'Computer Science and Engineering'},
  'peers': [
    {'doc_id': 'iitk', 'institution': 'IIT Kanpur', 'programme': 'B.Tech CSE',
      'discipline': 'Computer Science and Engineering', 'comparable': true},
    {'doc_id': 'nitw', 'institution': 'NIT Warangal', 'programme': 'B.Tech CSE',
      'discipline': 'Computer Science and Engineering', 'comparable': true},
    {'doc_id': 'mech', 'institution': 'Some College', 'programme': 'B.Tech Mechanical',
      'discipline': 'Mechanical Engineering', 'comparable': false, 'reason': 'another discipline'},
  ],
};

void main() {
  group('navigation', () {
    test('the requested information architecture, in order', () {
      expect([for (final g in navGroups) g.title],
          ['Start', 'Intelligence', 'Decisions', 'Evidence & quality', 'Workspace', 'More views']);
      expect([for (final e in navGroups[0].entries) e.label], ['Overview', 'Curricula', 'New analysis', 'Assistant']);
      expect([for (final e in navGroups[1].entries) e.label], ['Skill-gap analysis', 'Industry demand', 'Curriculum drift']);
      expect([for (final e in navGroups[2].entries) e.label], ['Comparisons', 'Recommendations']);
      expect([for (final e in navGroups[4].entries) e.label], ['History', 'Settings', 'System health']);
      expect(navGroups.last.collapsible, isTrue);
    });

    test('every destination is reachable once, and every label is unique', () {
      final dests = [for (final e in allEntries) e.dest];
      expect(dests.toSet().length, dests.length);
      for (final d in Dest.values.where((d) => d != Dest.pipelineRuns)) {
        expect(dests.contains(d), isTrue, reason: '$d is not in the navigation');
      }
      final labels = [for (final e in allEntries) e.label.toLowerCase()];
      expect(labels.toSet().length, labels.length);
      expect(pageGuides[Dest.history], isNotNull);
      expect(pageGuides[Dest.settings], isNotNull);
    });
  });

  group('history', () {
    testWidgets('lists analyses with their state, scope and reason; filters; opens a ready one', (tester) async {
      await _wide(tester);
      final api = _Api({'/api/v1/analysis/jobs': _jobs});
      final ctx = AnalysisContext(api, pollInterval: const Duration(hours: 1));
      Dest? went;
      await tester.pumpWidget(_host(ctx, HistoryScreen(api: api, navigate: (d, {arg}) => went = d)));
      await tester.pumpAndSettle();
      expect(find.text('Vasavi College of Engineering · B.E. CSE · R26'), findsOneWidget);
      expect(find.text('Example Institute · B.Tech Civil · R24'), findsOneWidget);
      expect(find.textContaining('Analysis ready'), findsOneWidget);
      expect(find.textContaining('Analysis failed'), findsOneWidget);
      expect(find.textContaining('compared with 1 chosen peer'), findsOneWidget);
      expect(find.textContaining('curriculum only (no industry evidence)'), findsOneWidget);
      expect(find.textContaining('took 70 s'), findsOneWidget);
      expect(find.textContaining('interrupted'), findsOneWidget);
      expect(find.text('Run again'), findsOneWidget);
      expect(find.textContaining('%'), findsNothing);

      await tester.tap(find.text('Needs attention'));
      await tester.pumpAndSettle();
      expect(find.text('Vasavi College of Engineering · B.E. CSE · R26'), findsNothing);
      expect(find.text('Example Institute · B.Tech Civil · R24'), findsOneWidget);
      await tester.tap(find.text('All'));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Open results'));
      await tester.pump();
      expect(ctx.status, 'ANALYSIS_READY');
      expect(api.runId, 'run0000000000001');
      expect(ctx.options, {'peers': true, 'industry': true, 'peer_ids': ['nitw']});
      expect(went, Dest.overview);
      await _close(tester, ctx);
    });

    testWidgets('no analyses yet: says how to start one', (tester) async {
      await _wide(tester);
      final api = _Api({'/api/v1/analysis/jobs': {'evidence_state': 'AVAILABLE', 'items': <dynamic>[]}});
      final ctx = AnalysisContext(api);
      await tester.pumpWidget(_host(ctx, HistoryScreen(api: api, navigate: (d, {arg}) {})));
      await tester.pumpAndSettle();
      expect(find.text('No analyses have been started yet'), findsOneWidget);
      expect(find.text('Start an analysis'), findsOneWidget);
      await _close(tester, ctx);
    });

    test('a job that is not ready cannot be opened as results', () {
      final api = _Api(const {});
      final ctx = AnalysisContext(api);
      final failed = Map<String, dynamic>.from((_jobs['items'] as List)[1] as Map);
      expect(ctx.openJob(failed), isFalse);
      expect(ctx.status, 'LATEST');
      expect(api.runId, isNull);
      ctx.dispose();
    });
  });

  group('settings', () {
    testWidgets('discipline support follows the evidence, and only a validated profile says so', (tester) async {
      await _wide(tester);
      final api = _Api({'/api/v1/metadata/discipline-profiles': _profiles});
      final ctx = AnalysisContext(api);
      await tester.pumpWidget(_host(ctx, SettingsScreen(api: api, navigate: (d, {arg}) {})));
      await tester.pumpAndSettle();
      expect(find.text('Validated with real data'), findsOneWidget);
      expect(find.text('Not yet validated'), findsOneWidget);
      expect(find.textContaining('Available (15 job-posting sources)'), findsOneWidget);
      expect(find.textContaining('no job postings relevant to this discipline have been supplied'), findsOneWidget);
      expect(find.textContaining('no reference curriculum of this discipline'), findsOneWidget);
      expect(find.textContaining('NO_RELEVANT_EVIDENCE'), findsNothing);
      await _close(tester, ctx);
    });

    testWidgets('profiles unavailable: an error with a retry, no invented support', (tester) async {
      await _wide(tester);
      final api = _Api(const {});
      final ctx = AnalysisContext(api);
      await tester.pumpWidget(_host(ctx, SettingsScreen(api: api, navigate: (d, {arg}) {})));
      await tester.pumpAndSettle();
      expect(find.text('Retry'), findsOneWidget);
      expect(find.textContaining('Validated'), findsNothing);
      await _close(tester, ctx);
    });
  });

  group('skill gaps', () {
    Map<String, dynamic> gap(String label, String cls, int postings, String level, String support) => {
          'skill_key': label, 'skill_label': label, 'classification_v2': cls, 'posting_count': postings,
          'eligible_postings': 100, 'coverage_level': level, 'support_state': support, 'coverage_relation': 'NONE',
          'evidence_status': 'MODEL_SUGGESTED',
        };

    testWidgets('sorting and the confirmed-only filter work on the listed skills', (tester) async {
      await _wide(tester);
      final api = _Api({
        '/api/v1/intelligence/gaps': {
          'evidence_state': 'AVAILABLE',
          'items': [
            gap('SQL', 'PARTIAL', 30, 'INTRODUCTORY', 'HIGH_SUPPORT'),
            gap('Kafka', 'MISSING', 5, 'ABSENT', 'INSUFFICIENT_EVIDENCE'),
            gap('Docker', 'MISSING', 12, 'ABSENT', 'SUPPORTED'),
          ],
        },
      });
      final ctx = AnalysisContext(api);
      await tester.pumpWidget(_host(ctx, SkillGapsScreen(api: api)));
      await tester.pumpAndSettle();
      await tester.tap(find.textContaining('All 3'));
      await tester.pumpAndSettle();
      double y(String t) => tester.getTopLeft(find.text(t).first).dy;
      expect(y('SQL') < y('Docker') && y('Docker') < y('Kafka'), isTrue); // most postings first
      await tester.tap(find.text('A–Z'));
      await tester.pumpAndSettle();
      expect(y('Docker') < y('Kafka') && y('Kafka') < y('SQL'), isTrue);
      await tester.tap(find.text('Confirmed gaps only'));
      await tester.pumpAndSettle();
      expect(find.text('Kafka'), findsNothing); // demand not supported: not a confirmed gap
      expect(find.text('Docker'), findsOneWidget);
      expect(find.text('SQL'), findsOneWidget);
      await _close(tester, ctx);
    });
  });

  group('peer chooser', () {
    testWidgets('only chosen peers of the same discipline are sent; another discipline cannot be chosen',
        (tester) async {
      await _wide(tester);
      final api = _Api({
        '/api/v1/metadata/document-roles': _roles,
        '/api/v1/metadata/discipline-profiles': _profiles,
        '/api/v1/analysis/comparison-targets': _targets,
      });
      final ctx = AnalysisContext(api, pollInterval: const Duration(hours: 1));
      await tester.pumpWidget(_host(ctx, IngestionScreen(apiClient: api)));
      await tester.pumpAndSettle();
      IngestionScreen.debugPicker = (ext) async => const PickedUpload('syllabus.pdf', [1, 2, 3]);
      addTearDown(() => IngestionScreen.debugPicker = null);
      await tester.tap(find.text('Choose file'));
      await tester.pumpAndSettle();
      expect(find.text('Enter the discipline above to choose which peers to compare with.'), findsOneWidget);
      for (final e in {'Institution': 'Vasavi', 'Programme': 'B.E. CSE', 'Discipline': 'CSE', 'Curriculum version': 'R26'}.entries) {
        await tester.enterText(find.widgetWithText(TextField, '${e.key} (required)'), e.value);
      }
      await tester.pumpAndSettle();
      // the typed discipline is recognised, and every comparable peer starts chosen
      expect(find.textContaining('Recognised as Computer Science and Engineering.'), findsOneWidget);
      expect(find.text('Compare with (2 of 2 chosen):'), findsOneWidget);
      // another discipline is listed with the reason, but is not a control at all
      expect(find.textContaining('Some College · B.Tech Mechanical (Mechanical Engineering): not comparable, another discipline'),
          findsOneWidget);
      expect(find.widgetWithText(CheckboxListTile, 'Some College · B.Tech Mechanical'), findsNothing);
      await tester.ensureVisible(find.text('IIT Kanpur · B.Tech CSE'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('IIT Kanpur · B.Tech CSE'));
      await tester.pump();
      expect(ctx.draft.peerIds, {'nitw'});
      await tester.ensureVisible(find.text('Upload and extract'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Upload and extract'));
      await tester.pump();
      await tester.pump();
      final start = api.posts.firstWhere((p) => p.$1 == '/api/v1/analysis/jobs');
      expect(start.$2['options'], {'peers': true, 'industry': true, 'peer_ids': ['nitw']});
      // the discipline was sent with the request for comparison targets
      expect(api.gets.any((g) => g.$1 == '/api/v1/analysis/comparison-targets' && g.$2?['discipline'] == 'CSE'), isTrue);
      await _close(tester, ctx);
    });

    testWidgets('with no peer of the discipline, peer comparison is off and explained, and nothing looks clickable',
        (tester) async {
      await _wide(tester);
      tester.view.physicalSize = const Size(1400, 6000); // tall enough that the whole form is built (no lazy rows)
      final none = {
        ..._targets,
        'discipline_profile': {'id': 'aids', 'name': 'Artificial Intelligence and Data Science'},
        'peers': [
          for (final p in _targets['peers'] as List)
            // typed as decoded JSON is: asMap() reads only Map<String, dynamic>
            <String, dynamic>{...(p as Map<String, dynamic>), 'comparable': false, 'reason': 'another discipline'},
        ],
      };
      final api = _Api({
        '/api/v1/metadata/document-roles': _roles,
        '/api/v1/metadata/discipline-profiles': _profiles,
        '/api/v1/analysis/comparison-targets': none,
      });
      final ctx = AnalysisContext(api, pollInterval: const Duration(hours: 1));
      await tester.pumpWidget(_host(ctx, IngestionScreen(apiClient: api)));
      await tester.pumpAndSettle();
      IngestionScreen.debugPicker = (ext) async => const PickedUpload('syllabus.pdf', [1, 2, 3]);
      addTearDown(() => IngestionScreen.debugPicker = null);
      await tester.tap(find.text('Choose file'));
      await tester.pumpAndSettle();
      for (final e in {'Institution': 'CBIT', 'Programme': 'B.E. AI&DS', 'Discipline': 'AI & DS', 'Curriculum version': 'R22'}.entries) {
        await tester.enterText(find.widgetWithText(TextField, '${e.key} (required)'), e.value);
      }
      await tester.pumpAndSettle();
      final peers = tester.widget<CheckboxListTile>(find.widgetWithText(CheckboxListTile, 'Peer comparison'));
      expect((peers.value, peers.onChanged), (false, null));
      expect(find.textContaining('Not available for this discipline'), findsOneWidget);
      expect(find.text('Supplied peer curricula, none of this discipline:'), findsOneWidget);
      expect(find.widgetWithText(CheckboxListTile, 'IIT Kanpur · B.Tech CSE'), findsNothing);
      expect(find.textContaining('IIT Kanpur · B.Tech CSE (Computer Science and Engineering): not comparable'), findsOneWidget);
      await tester.ensureVisible(find.text('Upload and extract'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Upload and extract'));
      await tester.pump();
      await tester.pump();
      final start = api.posts.firstWhere((p) => p.$1 == '/api/v1/analysis/jobs');
      expect(start.$2['options'], {'peers': false, 'industry': true});
      await _close(tester, ctx);
    });

    test('an empty choice is no peer comparison, never "all peers"', () {
      final d = EvidenceDraft()..peerIds = <String>{};
      expect(d.options, {'peers': false, 'industry': true});
      d.peerIds = null;
      expect(d.options, {'peers': true, 'industry': true});
    });
  });
}
