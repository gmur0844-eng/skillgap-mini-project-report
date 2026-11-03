// Widget tests for the redesigned screens. A FakeApi answers the real endpoint paths with small fixed payloads shaped
// like the backend's responses; these are TEST FIXTURES that exercise rendering states (never shown in the app).
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:skillgap_dashboard/main.dart';
import 'package:skillgap_dashboard/screens/premium/data_quality_screen.dart';
import 'package:skillgap_dashboard/screens/premium/drift_screen.dart';
import 'package:skillgap_dashboard/screens/premium/lineage_screen.dart';
import 'package:skillgap_dashboard/screens/premium/pages.dart';
import 'package:skillgap_dashboard/screens/premium/skill_gaps_screen.dart';
import 'package:skillgap_dashboard/screens/premium/peer_screen.dart';
import 'package:skillgap_dashboard/screens/premium/recommendations_screen.dart';
import 'package:skillgap_dashboard/screens/premium/semantic_screen.dart';
import 'package:skillgap_dashboard/screens/premium/system_health_screen.dart';
import 'package:skillgap_dashboard/screens/premium/trends_screen.dart';
import 'package:skillgap_dashboard/services/api_client.dart';
import 'package:skillgap_dashboard/shell/navigation.dart';
import 'package:skillgap_dashboard/theme/design_system.dart';

class FakeApi extends ApiClient {
  FakeApi(this.routes, {this.hang = false});
  final Map<String, dynamic> routes;
  final bool hang;
  final List<String> calls = [];

  @override
  Future<dynamic> getJson(String path, {Map<String, String>? query}) {
    calls.add(path);
    if (hang) return Completer<dynamic>().future; // stays loading
    if (routes.containsKey(path)) return Future.value(routes[path]);
    return Future.error(ApiException('no route in test', statusCode: 404));
  }
}

const _scope = {'run_id': 'testrun0000000001'};

final _overview = <String, dynamic>{
  'evidence_state': 'AVAILABLE',
  'scope': _scope,
  'run': {'run_id': 'testrun0000000001', 'generated_at': '2026-09-27T00:00:00Z', 'content_digest': 'abc'},
  'target': {'institution': 'Target Institute', 'curriculum_version': 'R22', 'academic_year': '2022-23'},
  'kpis': [
    {'key': 'courses', 'label': 'Target-curriculum courses', 'value': 42, 'context': 'target curriculum', 'source': 'courses.jsonl'},
    {'key': 'postings', 'label': 'Industry postings', 'value': 7, 'context': 'eligible', 'source': 'postings'},
  ],
  'findings': [
    {
      'kind': 'GAPS',
      'tone': 'neutral',
      'value': 0,
      'title': 'No evidence-supported curriculum gap yet',
      'statement': '1 skill is missing, but the industry signal is thin: a gap is only stated with supported demand.',
      'target': 'skillGaps'
    },
    {
      'kind': 'TRUST',
      'tone': 'neutral',
      'value': null,
      'title': 'AI interpretation is advisory',
      'statement': 'AI-assisted semantic interpretation is advisory.',
      'target': 'aiEvaluation'
    },
  ],
  'attention': [
    {
      'skill_key': 'sql',
      'skill_label': 'SQL',
      'classification': 'MISSING',
      'posting_count': 2,
      'eligible_postings': 7,
      'evidence_supported': false
    }
  ],
  'flow': [
    {'step': 'industry', 'stage': 'Industry', 'label': 'Industry postings', 'value': 7, 'headline': '7 postings',
     'evidence': ['7 postings from IN', 'dated 2026-09-01 to 2026-09-03']},
    {'step': 'skills', 'stage': 'Skills', 'label': 'Skills with demand', 'value': 3, 'headline': '3 assessed',
     'evidence': ['3 observed in a few postings']},
    {'step': 'gaps', 'stage': 'Gaps', 'label': 'Evidence-supported gaps', 'value': 0, 'headline': '0 confirmed',
     'evidence': ['no skill meets both conditions']},
  ],
  'gap_line': {'confirmed': 0, 'partial': 13, 'missing': 0, 'covered': 10, 'insufficient': 92},
  'actions': {
    'issued': [],
    'withheld': [
      {'skill_key': 'sql', 'skill_label': 'SQL', 'statement': 'Current evidence supports reviewing existing coverage.',
       'posting_count': 5, 'curriculum_courses': 4}
    ],
    'not_recommended': 114,
  },
  'data_scope': {
    'industry': {
      'eligible_postings': 7,
      'date_range': {'earliest': '2026-09-01', 'latest': '2026-09-03'},
      'geographic_scope': {'India': 7},
    }
  },
  'gap_summary': {'COVERED': 2, 'MISSING': 1},
  'drift_summary': {'UNCHANGED': 3},
  'trend_status': {
    'POP_A': {'status': 'INSUFFICIENT_DATA', 'missing': {'qualifying_periods': 1, 'granularity': 'week'}}
  },
  'evidence_status': {'TEMPORAL': 'PARTIAL'},
  'semantic': {'mode': 'SAFE_MODE', 'mode_label': 'AI interpretation is advisory', 'decisions': 3, 'effects_blocked': 1, 'independent_evaluation': 'PENDING_INDEPENDENT_LABELS'},
  'peer_status': 'PEER_DATA_PARTIAL',
  'peers_available': ['Peer A'],
  'occupations': {'established': 2, 'by_state': {'EXACT': 2, 'UNMAPPED': 5}},
};

Future<void> _size(WidgetTester tester, Size s) async {
  tester.view.physicalSize = s;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

/// Scrolls a widget to the middle of its page, so a tap lands on it and not on the top bar above the page.
Future<void> _reveal(WidgetTester tester, Finder finder) async {
  await Scrollable.ensureVisible(tester.element(finder), alignment: 0.5);
  await tester.pumpAndSettle();
}

Widget _host(Widget child) => MaterialApp(theme: buildAppTheme(), home: Scaffold(body: child));

void main() {
  test('an inferred result is never attributed to AI by its status wording', () {
    // recommendations, concept clusters, drift and mappings carry MODEL_SUGGESTED although no AI produced them
    final wording = StatusStyle.label('MODEL_SUGGESTED');
    expect(wording, 'Inferred, not independently validated');
    expect(wording.contains('AI'), isFalse);
  });

  testWidgets('overview is a briefing: key finding first, findings, scoped counts, advisory AI', (tester) async {
    await _size(tester, const Size(1400, 1000));
    await tester.pumpWidget(SkillGapApp(apiClient: FakeApi({'/api/v1/overview': _overview})));
    await tester.pumpAndSettle();
    // the page eyebrow (Version 2 sets it in tracked capitals, so its case is not part of the check)
    expect(find.textContaining(RegExp('Curriculum intelligence ·', caseSensitive: false)), findsOneWidget);
    expect(find.text('No evidence-supported curriculum gap yet'), findsWidgets); // the key finding
    expect(find.text('confirmed gaps'), findsOneWidget); // the gap line is one typographic line, not KPI cards
    expect(find.text('partial coverage'), findsOneWidget);
    expect(find.text('Current-curriculum courses'), findsOneWidget); // every raw count names its scope, in words
    expect(find.text('42'), findsOneWidget);
    expect(find.text('AI interpretation is advisory'), findsWidgets);
    expect(find.text('SAFE_MODE'), findsNothing); // codes stay out of the primary UI
    expect(find.textContaining('Published analysis'), findsOneWidget); // analysis context in the top bar
    expect(find.textContaining('Run testrun0'), findsNothing); // the analysis reference is a technical detail
  });

  testWidgets('a section opens the screen that holds its evidence', (tester) async {
    await _size(tester, const Size(1400, 1000));
    await tester.pumpWidget(SkillGapApp(apiClient: FakeApi({'/api/v1/overview': _overview})));
    await tester.pumpAndSettle();
    await _reveal(tester, find.text('All skill gaps →'));
    await tester.tap(find.text('All skill gaps →'));
    await tester.pumpAndSettle();
    expect(find.textContaining('/ Skill-gap analysis'), findsOneWidget);
  });

  testWidgets('a flow stage opens to its evidence', (tester) async {
    await _size(tester, const Size(1400, 1000));
    await tester.pumpWidget(SkillGapApp(apiClient: FakeApi({'/api/v1/overview': _overview})));
    await tester.pumpAndSettle();
    expect(find.textContaining('7 postings from IN'), findsNothing);
    await tester.ensureVisible(find.text('7 postings'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('7 postings'));
    await tester.pumpAndSettle();
    expect(find.textContaining('7 postings from IN'), findsOneWidget);
  });

  testWidgets('a withheld candidate is a review decision, never a recommendation; its evidence thread is real',
      (tester) async {
    await _size(tester, const Size(1400, 1000));
    final api = FakeApi({
      '/api/v1/overview': _overview,
      '/api/v1/intelligence/evidence-trace': {
        'evidence_state': 'AVAILABLE',
        'trace': {
          'job_postings': [
            {'job_title': 'Backend Developer', 'company': 'Acme', 'context': 'SQL and APIs'}
          ],
          'industry_demand': {'posting_count': 5, 'eligible_postings': 7, 'support_state': 'SUPPORTED'},
          'normalized_skill': {'label': 'SQL'},
          'esco': {'pref_label': 'SQL', 'status': 'EXACT'},
          'gap': {'classification': 'PARTIAL', 'evidence_status': 'REVIEW_REQUIRED',
                  'reasons': [{'code': 'CLASSIFICATION_CONFLICT_REVIEW_REQUIRED', 'detail': 'the measures disagree'}]},
        },
        'coverage_depth': [
          {'role': 'TARGET', 'coverage_level': 'SUBSTANTIAL', 'level_reason': '2 topics in 2 units',
           'evidence': [{'course_code': 'CS-1', 'page': 7, 'text': 'SQL queries'}]}
        ],
      },
    });
    await tester.pumpWidget(SkillGapApp(apiClient: api));
    await tester.pumpAndSettle();
    expect(find.text('Review'), findsOneWidget);
    expect(find.text('SQL'), findsWidgets);
    expect(find.textContaining('Recommendation: add'), findsNothing);
    await _reveal(tester, find.text('Trace the evidence →'));
    await tester.tap(find.text('Trace the evidence →'));
    await tester.pumpAndSettle();
    expect(find.text('Evidence thread · SQL'), findsOneWidget);
    expect(find.text('Withheld for review'), findsOneWidget);
    expect(find.textContaining('CS-1 p.7: SQL queries'), findsOneWidget);
  });

  testWidgets('system health answers "is the analysis ready" and keeps internals in technical details', (tester) async {
    await _size(tester, const Size(1400, 1200));
    final api = FakeApi({
      '/api/v1/readiness': {
        'evidence_state': 'AVAILABLE',
        'headline': 'Curriculum intelligence is ready',
        'summary': 'The current analysis is available and traceable.',
        'primary': [
          {'key': 'analysis', 'label': 'Analysis', 'state': 'READY', 'human': 'Ready', 'statement': 'Available.'},
          {'key': 'evidence', 'label': 'Evidence', 'state': 'AVAILABLE_WITH_LIMITATIONS', 'human': 'Available with limitations',
           'statement': 'Core evidence is available.'},
          {'key': 'ai', 'label': 'AI interpretation', 'state': 'ADVISORY', 'human': 'Advisory', 'statement': 'Advisory.'},
          {'key': 'traceability', 'label': 'Traceability', 'state': 'COMPLETE', 'human': 'Complete', 'statement': 'Traceable.'},
        ],
        'coverage': [
          {'key': 'trends', 'label': 'Industry trends', 'state': 'NOT_ESTABLISHED', 'human': 'Not established',
           'statement': 'one qualifying period', 'missing': 'postings from more periods', 'why_it_matters': 'a trend needs two',
           'resolve': 'add dated postings'},
        ],
        'what_to_know': ['Core curriculum analysis is available.', 'Some peer evidence is incomplete.', 'No trend yet.'],
        'ai_interpretation': {'state': 'ADVISORY', 'human': 'Advisory', 'explanation': 'AI is advisory.',
                              'why': 'Independent validation is pending.', 'affects': 'AI-suggested relationships only.',
                              'authoritative': 'Evidence-derived analytics.'},
        'traceability': {'state': 'COMPLETE', 'checks': {'run_content_digest': true}},
        'secondary': {'last_successful_analysis': '2026-10-01T04:03:57+00:00'},
        'technical': {'run_id': 'testrun0000000001', 'semantic_mode': 'SAFE_MODE'},
      }
    });
    await tester.pumpWidget(_host(SystemHealthScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('Curriculum intelligence is ready'), findsOneWidget);
    for (final s in ['Ready', 'Available with limitations', 'Advisory', 'Complete']) {
      expect(find.text(s), findsWidgets, reason: s);
    }
    expect(find.textContaining('Not established'), findsOneWidget);
    expect(find.text('SAFE_MODE'), findsNothing); // internals only inside the collapsed technical details
    expect(find.text('testrun0000000001'), findsNothing);
    await tester.tap(find.text('Industry trends'));
    await tester.pumpAndSettle();
    expect(find.text('add dated postings'), findsOneWidget);
    await tester.ensureVisible(find.text('Technical details'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Technical details'));
    await tester.pumpAndSettle();
    expect(find.text('testrun0000000001'), findsOneWidget);
  });

  testWidgets('loading state shows a skeleton, not numbers', (tester) async {
    await _size(tester, const Size(1400, 1000));
    await tester.pumpWidget(SkillGapApp(apiClient: FakeApi(const {}, hang: true)));
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.bySemanticsLabel('Loading'), findsOneWidget);
    expect(find.text('42'), findsNothing);
  });

  testWidgets('navigation reaches every group and changes the breadcrumb', (tester) async {
    await _size(tester, const Size(1400, 1000));
    await tester.pumpWidget(SkillGapApp(apiClient: FakeApi({'/api/v1/overview': _overview})));
    await tester.pumpAndSettle();
    final item = find.widgetWithText(ListTile, 'System health');
    await tester.scrollUntilVisible(item, 200, scrollable: find.byType(Scrollable).first);
    await tester.tap(item);
    await tester.pumpAndSettle();
    expect(find.textContaining('/ System health'), findsOneWidget);
    expect(find.textContaining('Could not load'), findsOneWidget); // /health has no route in this fake
  });

  testWidgets('collapsing the sidebar keeps every destination reachable by icon', (tester) async {
    await _size(tester, const Size(1400, 1000));
    await tester.pumpWidget(SkillGapApp(apiClient: FakeApi({'/api/v1/overview': _overview})));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Collapse navigation'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(ListTile, 'Overview'), findsNothing); // the sidebar shows icons only
    expect(find.byTooltip('Knowledge graph'), findsOneWidget);
    expect(find.byTooltip('Expand navigation'), findsOneWidget);
  });

  testWidgets('responsive: overview renders without overflow at phone width', (tester) async {
    await _size(tester, const Size(390, 900));
    await tester.pumpWidget(SkillGapApp(apiClient: FakeApi({'/api/v1/overview': _overview})));
    await tester.pumpAndSettle();
    expect(find.byTooltip('Menu'), findsOneWidget);
    expect(find.byTooltip('Search'), findsOneWidget);
    expect(find.text('No evidence-supported curriculum gap yet'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('semantic decisions: blocked effects are shown as advisory, not failure', (tester) async {
    await _size(tester, const Size(1400, 1000));
    final api = FakeApi({
      '/api/v1/semantic/decisions': {
        'evidence_state': 'AVAILABLE',
        'scope': _scope,
        'total': 1,
        'items': [
          {
            'decision_id': 'sdec:1',
            'left': 'AWS',
            'right': 'cloud technologies',
            'candidate_kind': 'ALIAS_SENSE',
            'relationship': 'RELATED',
            'decision_state': 'MODEL_SUGGESTED',
            'validated_state': 'MODEL_SUPPORTED',
            'effect': null,
            'effect_blocked_reason': 'promotion gate did not pass',
            'model': 'test-model',
            'is_human_validated': false,
            'evidence': [],
          }
        ],
      }
    });
    await tester.pumpWidget(_host(SemanticScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.textContaining('AI interpretation is advisory — it does not change results'), findsOneWidget);
    expect(find.textContaining('Not applied — promotion gate did not pass'), findsOneWidget);
    expect(find.text('not human-validated'), findsOneWidget);
  });

  testWidgets('peer status banner is at the top and names what is missing', (tester) async {
    await _size(tester, const Size(1400, 1000));
    final api = FakeApi({
      '/api/v1/peers/status': {
        'evidence_state': 'AVAILABLE',
        'peer_status': 'PEER_DATA_NOT_AVAILABLE',
        'status': {
          'available': [],
          'missing': [
            {'name': 'Peer X', 'reason': 'no official curriculum supplied'}
          ],
          'why_not_calculable': 'No peer curriculum was decoded.',
          'how_to_add': 'Register the official PDF with role PEER.',
        },
      },
      '/api/v1/peers/benchmark': {'evidence_state': 'AVAILABLE', 'comparisons': []},
    });
    await tester.pumpWidget(_host(PeerScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('No peer curriculum yet'), findsWidgets);
    expect(find.textContaining('No peer data yet'), findsWidgets); // the status tag, in words
    expect(find.textContaining('Peer X'), findsOneWidget);
    expect(find.text('How to add a peer'), findsOneWidget);
    final banner = tester.getTopLeft(find.text('How to add a peer'));
    expect(banner.dy, lessThan(500));
  });

  testWidgets('trends with one period show "Temporal evidence required", never a trend arrow', (tester) async {
    await _size(tester, const Size(1400, 1200));
    final api = FakeApi({
      '/api/v1/industry/temporal-trends': {
        'evidence_state': 'AVAILABLE',
        'populations': [
          {
            'population_id': 'POP_A',
            'trend_status': 'INSUFFICIENT_DATA',
            'eligible_postings': 7,
            'date_range': {'earliest': '2026-09-01', 'latest': '2026-09-03'},
            'geographic_scope': {'India': 7},
            'granularity': 'week',
            'source_files': ['a.csv'],
            'missing': {
              'have': {'qualifying_periods': 1, 'granularity': 'week'},
              'required': 'at least 3 qualifying periods'
            },
          }
        ],
        'items': [],
        'segments': [],
      }
    });
    await tester.pumpWidget(_host(TrendsScreen(api: api, navigate: (d, {arg}) {})));
    await tester.pumpAndSettle();
    expect(find.text('Temporal evidence required'), findsOneWidget);
    expect(find.text('View data sources'), findsOneWidget);
    expect(find.byIcon(Icons.trending_up), findsNothing);
    expect(find.byIcon(Icons.trending_down), findsNothing);
  });

  final recs = {
    'evidence_state': 'AVAILABLE',
    'scope': _scope,
    'suppressed': 4,
    'note': 'test',
    'v1': [
      {
        'action_type': 'ADD_TOPIC',
        'skill_label': 'Docker',
        'recommendation_state': 'RECOMMENDATION_SUPPORTED',
        'support_state': 'HIGH_SUPPORT',
        'evidence_status': 'SUPPORTED',
        'target_course_codes': ['CS-601'],
        'rule_reasons': ['demanded by 3 of 7 postings'],
        'uncertainty': [],
        'evidence': {
          'run_id': 'testrun0000000001',
          'target_programme': {'doc_id': 't', 'institution': 'Target Institute', 'programme': 'B.E. CSE'},
          'industry_evidence': {'statement': '3 of 7 postings', 'posting_count': 3, 'eligible_postings': 7},
          'curriculum_evidence': {'coverage_depth': [], 'gap': {'classification': 'MISSING'}},
          'skill': {'label': 'Docker'},
          'thresholds': {'min_postings': 3},
          'source_ids': ['s1'],
        },
      }
    ],
  };

  testWidgets('a recommendation shows the least disruptive intervention the curriculum supports, never "Add elective"',
      (tester) async {
    await _size(tester, const Size(1400, 1400));
    final r = Map<String, dynamic>.from((recs['v1'] as List).first as Map);
    r['action_type'] = 'ADD_ELECTIVE';
    r['reasoning'] = {
      'action': 'REVIEW_BEFORE_CHANGE',
      'why': ['The analysed document covers semester(s) 1, 2 only; the institution teaches it in later semesters.'],
      'evidence': {
        'institution_courses_teaching_it': [
          {'course_code': 'CS-15', 'title': 'Operating Systems'}
        ],
      },
      'alternatives_considered': [
        {'action': 'CONSIDER_STANDALONE_COURSE', 'why_not': 'not inferred'}
      ],
      'limitations': ['The rule engine proposed ADD_ELECTIVE from coverage percentages alone.'],
    };
    final api = FakeApi({'/api/v1/intelligence/recommendations': {...recs, 'v1': [r]}});
    await tester.pumpWidget(_host(RecommendationsScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('Review the curriculum before recommending a change'), findsOneWidget);
    expect(find.textContaining('CS-15 Operating Systems'), findsOneWidget); // the existing course is named
    expect(find.textContaining('Consider a new elective'), findsOneWidget); // the rule engine's view, as a consideration
    expect(find.text('Add elective'), findsNothing);
    expect(find.textContaining('Add new subject'), findsNothing);
    await _reveal(tester, find.text('View evidence →'));
    await tester.tap(find.text('View evidence →'));
    await tester.pumpAndSettle();
    expect(find.text('Recommended intervention'), findsOneWidget);
    expect(find.textContaining('Not chosen: consider a new standalone course'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('recommendation card shows states (no confidence %) and expands its evidence', (tester) async {
    await _size(tester, const Size(1400, 1400));
    await tester.pumpWidget(_host(RecommendationsScreen(api: FakeApi({'/api/v1/intelligence/recommendations': recs}))));
    await tester.pumpAndSettle();
    expect(find.text('Add topic'), findsOneWidget); // the decision: action above the skill
    expect(find.text('Docker'), findsOneWidget);
    expect(find.textContaining('Recommendation supported'), findsOneWidget);
    expect(find.text('01'), findsOneWidget);
    expect(find.textContaining('%)'), findsNothing); // no confidence percentage before expansion
    expect(find.text('Thresholds and sources'), findsNothing);
    expect(find.textContaining('AI-suggested'), findsNothing); // a rule-based inference is never attributed to AI
    await tester.ensureVisible(find.text('View evidence →'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('View evidence →'));
    await tester.pumpAndSettle();
    expect(find.text('Thresholds and sources'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('a candidate withheld for review is listed apart from issued recommendations', (tester) async {
    await _size(tester, const Size(1400, 1400));
    final api = FakeApi({
      '/api/v1/intelligence/recommendations': {
        'evidence_state': 'AVAILABLE',
        'v1': [],
        'suppressed': 3,
        'withheld_for_review': [
          {
            'skill_key': 'sql',
            'skill_label': 'SQL',
            'reasons': [
              {'code': 'CLASSIFICATION_CONFLICT_REVIEW_REQUIRED', 'detail': 'the two coverage measures disagree'}
            ],
            'withheld_recommendation': {'action_type': 'EXPAND_EXISTING_TOPIC'},
            'gap_v2': {'classification': 'COVERED', 'coverage_level': 'SUBSTANTIAL'},
          }
        ],
      }
    });
    await tester.pumpWidget(_host(RecommendationsScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('No recommendations'), findsOneWidget);
    expect(find.text('Withheld for review'), findsOneWidget);
    expect(find.text('SQL'), findsOneWidget);
    expect(find.text('the two coverage measures disagree'), findsOneWidget);
  });

  testWidgets('empty recommendations explain why instead of showing blanks', (tester) async {
    await _size(tester, const Size(1400, 1000));
    final api = FakeApi({
      '/api/v1/intelligence/recommendations': {'evidence_state': 'AVAILABLE', 'v1': [], 'suppressed': 9}
    });
    await tester.pumpWidget(_host(RecommendationsScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('No recommendations'), findsOneWidget);
  });

  testWidgets('a not-produced analysis says DATA NOT AVAILABLE with the reason', (tester) async {
    await _size(tester, const Size(1400, 1000));
    final api = FakeApi({
      '/api/v1/intelligence/lineage': {'evidence_state': 'AVAILABLE', 'run_id': 'r', 'sources': [], 'stages': []},
      '/api/v1/lineage/recompute': {'evidence_state': 'NOT_PRODUCED', 'reason': 'no recomputation lineage', 'items': []},
    });
    await tester.pumpWidget(_host(LineageScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('Sources'), findsWidgets);
    expect(find.text('Analysis results'), findsOneWidget); // GOLD in words, never the layer code
    expect(find.text('GOLD'), findsNothing);
    await tester.tap(find.text('Recomputation'));
    await tester.pumpAndSettle();
    expect(find.text('Not available for this analysis'), findsOneWidget);
    expect(find.text('no recomputation lineage'), findsOneWidget);
  });

  test('stage names map to lineage layers', () {
    expect(layerOf('raw.verify'), 'RAW');
    expect(layerOf('silver.structure'), 'SILVER');
    expect(layerOf('industry.gold'), 'GOLD');
    expect(layerOf('intelligence'), 'ANALYTICS');
    expect(layerOf('health.gate'), 'SILVER');
  });

  test('status styles never rely on colour alone', () {
    for (final v in ['SAFE_MODE', 'PEER_DATA_PARTIAL', 'INSUFFICIENT_DATA', 'SUPPORTED', 'BLOCKED']) {
      expect(StatusStyle.isKnown(v), isTrue, reason: v);
      expect(StatusStyle.label(v).contains('_'), isFalse);
    }
  });

  testWidgets('skill gaps open on partial coverage, not on covered skills', (tester) async {
    await _size(tester, const Size(1400, 1200));
    final api = FakeApi({
      '/api/v1/intelligence/gaps': {
        'evidence_state': 'AVAILABLE',
        'scope': _scope,
        'items': [
          {'skill_key': 'sql', 'skill_label': 'SQL', 'classification_v2': 'COVERED', 'support_state': 'HIGH_SUPPORT',
           'posting_count': 9, 'eligible_postings': 20, 'coverage_level': 'SUBSTANTIAL'},
          {'skill_key': 'docker', 'skill_label': 'Docker', 'classification_v2': 'PARTIAL', 'support_state': 'SUPPORTED',
           'posting_count': 6, 'eligible_postings': 20, 'coverage_level': 'INTRODUCTORY'},
        ],
      }
    });
    await tester.pumpWidget(_host(SkillGapsScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('Docker'), findsOneWidget);
    expect(find.text('SQL'), findsNothing); // covered skills are one filter away, not the first thing shown
    expect(find.text('1 confirmed skill gap'), findsOneWidget);
  });

  testWidgets("data quality reports the run's own validation checks, never an empty legacy table", (tester) async {
    await _size(tester, const Size(1400, 1200));
    final api = FakeApi({
      '/api/v1/curriculum/knowledge-health': {
        'documents': {
          'doc-a': {
            'doc_id': 'doc-a',
            'status': 'PASS',
            'checks': [
              {'check': 'raw_hash_verified', 'status': 'PASS', 'value': 'x', 'threshold': 'x', 'detail': ''},
            ]
          },
        },
        'industry': {
          'status': 'WARN',
          'summary': {
            'eligible_postings': 498,
            'records_read': 516,
            'files_verified': 15,
            'files_expected': 15,
            'duplicates': 18,
            'postings_with_skill': 448
          },
          'checks': [
            {'check': 'posting_count', 'status': 'PASS', 'value': 516, 'threshold': 30, 'detail': ''},
            {'check': 'baseline_regression', 'status': 'WARN', 'value': null, 'threshold': 0.2, 'detail': 'no baseline yet'},
          ]
        },
        'analytics_gates': {
          'industry_demand': {'status': 'ALLOWED', 'reasons': []}
        },
      }
    });
    await tester.pumpWidget(_host(DataQualityReport(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('The current analysis passed its validation checks'), findsOneWidget);
    expect(find.textContaining('2 of 3 checks passed, 1 carry a warning'), findsOneWidget);
    expect(find.textContaining('Insufficient real data'), findsNothing);
    // a warning is shown as a warning, with the check named in words (baseline_regression)
    expect(find.textContaining('Warning: Consistent with the accepted analysis (no baseline yet)'), findsOneWidget);
    expect(find.textContaining('baseline_regression'), findsNothing);
  });

  testWidgets('curriculum drift shows only the versions that exist, as a timeline', (tester) async {
    await _size(tester, const Size(1400, 1400));
    final api = FakeApi({
      '/api/v1/intelligence/lineage': {
        'evidence_state': 'AVAILABLE',
        'sources': [
          {'role': 'PREVIOUS_VERSION', 'curriculum_version': 'R22', 'academic_year': '2022-23', 'programme': 'B.E. CSE'},
          {'role': 'TARGET', 'curriculum_version': 'R22A', 'academic_year': '2024-25', 'programme': 'B.E. CSE'},
        ],
      },
      '/api/v1/curriculum/course-drift': {
        'evidence_state': 'AVAILABLE',
        'statuses': {'ADDED': 1, 'REMOVED': 1},
        'excluded': {'target_outside_comparable_semesters': 0},
        'note': 'course lineage is shared-concept correspondence',
        'items': [
          {'status': 'ADDED', 'target_code': 'CS-9', 'target_semester': 'I', 'title': 'Cloud Computing'},
          {'status': 'REMOVED', 'previous_code': 'CS-1', 'previous_semester': 'I', 'title': 'Old Course'},
        ],
      },
    });
    await tester.pumpWidget(_host(CurriculumDriftScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('R22 (2022-23)'), findsOneWidget);
    expect(find.text('R22A (2024-25)'), findsOneWidget);
    expect(find.text('Cloud Computing'), findsOneWidget);
    expect(find.text('Old Course'), findsOneWidget);
    expect(find.textContaining('2023-24'), findsNothing); // nothing is interpolated between the two versions
  });

  testWidgets('another programme of the same institution is a programme comparison, never curriculum changes',
      (tester) async {
    await _size(tester, const Size(1400, 1400));
    final api = FakeApi({
      '/api/v1/intelligence/lineage': {'evidence_state': 'AVAILABLE', 'sources': []},
      '/api/v1/curriculum/course-drift': {'evidence_state': 'AVAILABLE', 'statuses': {}, 'items': []},
      '/api/v1/curriculum/programme-comparison': {
        'evidence_state': 'AVAILABLE',
        'comparison': {
          'status': 'ALLOWED',
          'relation': {'relation': 'SAME_INSTITUTION_OTHER_PROGRAMME', 'reasons': ['different specialisations']},
          'current': {'institution': 'Inst', 'programme': 'B.E.', 'specialization': 'AIML', 'curriculum_version': 'R26'},
          'comparison': {'institution': 'Inst', 'programme': 'B.E. Mechanical', 'curriculum_version': 'R22'},
          'comparable_semesters': ['I', 'II'],
        },
        'items': [
          {'status': 'ADDED', 'target_code': 'X-1', 'target_semester': 'I', 'title': 'Neural Networks'},
          {'status': 'REMOVED', 'previous_code': 'Y-1', 'previous_semester': 'II', 'title': 'Thermodynamics'},
          {'status': 'RENAMED', 'previous_code': 'E-1', 'target_code': 'E-2', 'target_semester': 'I',
           'title': 'Communicative English', 'previous_title': 'English'},
        ],
      },
    });
    await tester.pumpWidget(_host(CurriculumDriftScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('How B.E. (AIML) R26 compares with B.E. Mechanical R22'), findsOneWidget);
    expect(find.textContaining('not changes over time'), findsOneWidget);
    expect(find.text('Only in B.E. (AIML) R26'), findsOneWidget);
    expect(find.text('Neural Networks'), findsOneWidget);
    expect(find.text('Thermodynamics'), findsOneWidget);
    expect(find.text('English → Communicative English'), findsOneWidget); // a renamed course is shown, not dropped
    expect(find.textContaining('changed from'), findsNothing); // never presented as changes over time
  });

  testWidgets('without an earlier version of the programme, curriculum changes say what is needed', (tester) async {
    await _size(tester, const Size(1400, 1000));
    final api = FakeApi({
      '/api/v1/intelligence/lineage': {'evidence_state': 'AVAILABLE', 'sources': []},
      '/api/v1/curriculum/course-drift': {'evidence_state': 'AVAILABLE', 'statuses': {}, 'items': []},
      '/api/v1/curriculum/programme-comparison': {
        'evidence_state': 'AVAILABLE',
        'comparison': {'status': 'NOT_APPLICABLE', 'relation': null},
        'items': [],
      },
    });
    await tester.pumpWidget(_host(CurriculumDriftScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('No earlier version of this programme to compare with'), findsOneWidget);
    expect(find.textContaining('New analysis'), findsOneWidget);
    expect(find.textContaining('PREVIOUS_VERSION'), findsNothing);
  });

  testWidgets('an evidence link the data cannot establish says so', (tester) async {
    await _size(tester, const Size(1400, 1400));
    final api = FakeApi({
      '/api/v1/overview': _overview,
      '/api/v1/intelligence/evidence-trace': {
        'evidence_state': 'AVAILABLE',
        'trace': {
          'job_postings': [
            {'job_title': 'Data Engineer', 'company': 'Acme', 'context': 'Spark pipelines'}
          ],
          'industry_demand': {'posting_count': 2, 'eligible_postings': 7, 'support_state': 'OBSERVED'},
          'gap': {'classification': 'MISSING'},
        },
        'coverage_depth': [],
      },
    });
    await tester.pumpWidget(SkillGapApp(apiClient: api));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('View evidence →'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('View evidence →'));
    await tester.pumpAndSettle();
    expect(find.text('No course found'), findsOneWidget);
    expect(find.text('Evidence is insufficient to establish this relationship.'), findsWidgets);
    expect(find.textContaining('Spark pipelines'), findsOneWidget); // the posting excerpt is quoted, not paraphrased
  });

  testWidgets('no screen shows a backend code or internal term in its normal view', (tester) async {
    // fixtures deliberately full of backend vocabulary: roles, requirement keys, enum states and snake_case names
    const blockedDrift = 'needs healthy TARGET + PREVIOUS_VERSION documents of the same programme with at least one '
        'comparable semester';
    final api = FakeApi({
      '/api/v1/curriculum/knowledge-health': {
        'documents': {
          'doc-a': {
            'doc_id': 'doc-a',
            'status': 'PASS',
            'checks': [
              {'check': 'raw_hash_verified', 'status': 'PASS', 'value': 1, 'threshold': 1},
              {'check': 'topic_noise_ratio', 'status': 'WARN', 'value': 0.3, 'threshold': 0.2, 'detail': 'above baseline'},
            ],
          },
        },
        'industry': {
          'status': 'PASS',
          'summary': {'eligible_postings': 7, 'records_read': 9, 'files_verified': 1, 'files_expected': 1},
          'checks': [
            {'check': 'eligible_postings', 'status': 'PASS', 'value': 7, 'threshold': 5},
          ],
        },
        'analytics_gates': {
          'concept_drift': {'status': 'BLOCKED', 'reasons': [blockedDrift]},
          'industry_gap': {
            'status': 'BLOCKED',
            'reasons': ['industry population: 7 real job postings (minimum 50); demand cannot be computed without it'],
          },
          'peer_benchmark': {'status': 'NOT_APPLICABLE', 'reasons': ['needs a healthy TARGET and at least one healthy PEER curriculum']},
          'reference_mapping': {'status': 'ALLOWED', 'reasons': []},
        },
      },
      '/api/v1/curriculum/coverage': {
        'evidence_state': 'AVAILABLE',
        'items': [
          {'role': 'TARGET', 'skill_label': 'SQL', 'coverage_level': 'MENTION', 'coverage_relation': 'INCIDENTAL',
            'level_reason': 'mentioned once in the TARGET curriculum'},
        ],
      },
      '/api/v1/semantic/concepts': {
        'evidence_state': 'AVAILABLE',
        'note': 'clustered from TARGET and PEER topics',
        'items': [
          {'name': 'databases', 'support': 3, 'source_roles': ['TARGET', 'PREVIOUS_VERSION', 'PEER'],
            'evidence_status': 'MODEL_SUGGESTED'},
        ],
      },
      '/api/v1/metadata/sources': {
        'sources': [
          {'source_id': 'ncs', 'source_type': 'JOB_BOARD', 'access_method': 'MANUAL_EXPORT',
            'configuration_status': 'CONFIGURED', 'geographic_scope': 'India', 'licence': 'permitted use'},
        ],
      },
      '/api/v1/intelligence/evidence-status': {
        'evidence_state': 'AVAILABLE',
        'items': [
          {'requirement_id': 'industry_gap', 'status': 'INSUFFICIENT_EVIDENCE', 'measured': 7, 'required': 50,
            'what_is_missing': 'more postings aligned with the TARGET curriculum', 'next_action': 'add postings'},
        ],
      },
    });
    final internal = RegExp(r'\bTARGET\b|PREVIOUS_VERSION|concept_drift|analytics gate|pipeline run|source_id|'
        r'\b[A-Z]{2,}(?:_[A-Z0-9]+)+\b|\b[a-z]+(?:_[a-z0-9]+)+\b');
    final offences = <String>[];
    for (final wide in [true, false]) {
      // wide: tables; narrow: one labelled card per row
      await _size(tester, wide ? const Size(1500, 1400) : const Size(700, 1400));
      for (final e in allEntries) {
        await tester.pumpWidget(_host(KeyedSubtree(
            key: ValueKey('${e.dest}:$wide'), child: buildPage(e.dest, api, navigate: (d, {arg}) {}))));
        await tester.pumpAndSettle();
        final texts = [
          for (final w in tester.widgetList<Text>(find.byType(Text)))
            if (w.style?.fontFamily != AppTypography.mono.fontFamily) w.data ?? w.textSpan?.toPlainText() ?? '',
          for (final w in tester.widgetList<SelectableText>(find.byType(SelectableText)))
            if (w.style?.fontFamily != AppTypography.mono.fontFamily) w.data ?? '',
        ];
        for (final t in texts) {
          if (internal.hasMatch(t)) offences.add('${e.label}: "$t"');
        }
      }
    }
    expect(offences.toSet(), isEmpty, reason: offences.toSet().join('\n'));
    // and the evidence behind the words is still there
    await _size(tester, const Size(1500, 1400));
    await tester.pumpWidget(_host(buildPage(Dest.dataQuality, api, navigate: (d, {arg}) {})));
    await tester.pumpAndSettle();
    expect(find.text('Curriculum changes'), findsOneWidget);
    expect(find.textContaining('An earlier curriculum for the same programme is required'), findsOneWidget);
    expect(find.text('Only 7 job postings are available; at least 50 are needed.'), findsOneWidget);
    // status badges are rich text (a coloured dot, then the words)
    expect(find.textContaining('Cannot run yet'), findsNWidgets(2));
    expect(find.textContaining('Not applicable'), findsOneWidget);
  });
}
