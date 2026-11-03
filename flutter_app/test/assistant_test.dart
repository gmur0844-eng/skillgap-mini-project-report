// The assistant screen: a conversation turn with what it looked up, a pending action that runs only on Confirm, a
// draft shown with its evidence and model suggestions marked, and a clear notice when the local model is not running.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:skillgap_dashboard/screens/premium/assistant_screen.dart';
import 'package:skillgap_dashboard/services/api_client.dart';
import 'package:skillgap_dashboard/theme/design_system.dart';

const _turn = {
  'user': 'What are the confirmed gaps?',
  'reply': 'Docker is a confirmed gap: 31 of 200 postings ask for it.',
  'tool_trace': [
    {'tool': 'analysis_overview', 'arguments': {}, 'kind': 'read'}
  ],
  'sources': ['analysis aaaaaaaaaaaaaaaa: skill gaps, industry demand'],
  'warnings': [],
  'draft_ids': ['draft-000000000001'],
  'pending_action': null,
};

const _actionTurn = {
  'user': 'Analyse my upload',
  'reply': 'I need your confirmation to: Start an analysis of Test College · s.pdf.',
  'tool_trace': [
    {'tool': 'start_analysis', 'arguments': {'upload_id': 'upl-000000000001'}, 'kind': 'action'}
  ],
  'sources': [],
  'warnings': ['figures not found in the analysis data: 45'],
  'draft_ids': [],
  'pending_action': {'id': 'act-000000000001', 'description': 'Start an analysis of Test College · s.pdf'},
};

const _draft = {
  'id': 'draft-000000000001',
  'kind': 'course',
  'title': 'Cloud and Containers',
  'label': 'AI-generated draft. It must be reviewed and approved by faculty before any use.',
  'run_id': 'aaaaaaaaaaaaaaaa',
  'model': {'model': 'test-model'},
  'content': {
    'title': 'Cloud and Containers',
    'objectives': ['Deploy services with containers'],
    'units': [
      {
        'title': 'Containers',
        'hours': 9,
        'topics': [
          {'text': 'Docker images', 'evidence': ['D1'], 'basis': 'EVIDENCE'},
          {'text': 'A made-up topic', 'evidence': [], 'basis': 'MODEL_SUGGESTION'},
        ]
      }
    ],
    'outcomes': ['Build a containerised service'],
    'reading': [
      {'title': 'Some Book', 'authors': 'Someone', 'status': 'unverified'}
    ],
  },
  'checks': {'total_hours': 9, 'topics': 2, 'topics_with_evidence': 1, 'unknown_evidence_ids_removed': ['Z9']},
  'evidence': {
    'D1': {'type': 'industry_demand', 'skill': 'docker', 'posting_count': 31, 'eligible_postings': 200, 'gap': 'MISSING'}
  },
};

class _Api extends ApiClient {
  _Api({this.ready = true, this.turns = const [_turn]});
  final bool ready;
  final List<Map<String, dynamic>> turns;
  final posts = <(String, Map<String, dynamic>)>[];

  Map<String, dynamic> get _conv => {'id': 'conv-000000000001', 'title': 't', 'turns': turns,
        'pending_action': turns.last['pending_action']};

  @override
  Future<dynamic> getJson(String path, {Map<String, String>? query}) async {
    if (path.endsWith('/status')) {
      return {'ready': ready, 'model': 'qwen-test', 'tools': true,
          'how_to_fix': 'Install Ollama and run `ollama pull qwen-test`.'};
    }
    if (path.endsWith('/conversations')) return {'items': [{'id': 'conv-000000000001', 'title': 'Gaps'}]};
    if (path.endsWith('/drafts')) return {'items': [{'id': 'draft-000000000001', 'kind': 'course', 'title': 'Cloud and Containers'}]};
    if (path.contains('/drafts/')) return _draft;
    if (path.contains('/conversations/')) return _conv;
    throw StateError('unexpected $path');
  }

  @override
  Future<dynamic> postJson(String path, Map<String, dynamic> body) async {
    posts.add((path, body));
    if (path.endsWith('/conversations')) return _conv;
    final decided = {..._actionTurn, 'pending_action': null};
    return {'turn': decided, 'conversation': {..._conv, 'turns': [decided], 'pending_action': null}};
  }
}

Future<void> _pump(WidgetTester tester, ApiClient api) async {
  tester.view.physicalSize = const Size(1400, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(theme: buildAppTheme(), home: Scaffold(body: AssistantScreen(api: api))));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('a turn shows the answer, what was looked up and its sources', (tester) async {
    final api = _Api();
    await _pump(tester, api);
    await tester.tap(find.text('Gaps'));
    await tester.pumpAndSettle();
    expect(find.text('Docker is a confirmed gap: 31 of 200 postings ask for it.'), findsOneWidget);
    expect(find.text('Looked up: analysis overview'), findsOneWidget);
    expect(find.textContaining('Sources: analysis aaaaaaaaaaaaaaaa'), findsOneWidget);
    expect(find.text('Open the draft'), findsOneWidget);
  });

  testWidgets('an action runs only when confirmed', (tester) async {
    final api = _Api(turns: const [_actionTurn]);
    await _pump(tester, api);
    await tester.tap(find.text('Gaps'));
    await tester.pumpAndSettle();
    expect(find.text('Confirm this action'), findsOneWidget);
    expect(find.text('Check: figures not found in the analysis data: 45'), findsOneWidget);
    expect(api.posts, isEmpty);
    await tester.tap(find.text('Confirm'));
    await tester.pumpAndSettle();
    expect(api.posts.single.$1, '/api/v1/assistant/conversations/conv-000000000001/actions/act-000000000001');
    expect(api.posts.single.$2, {'approve': true});
    expect(find.text('Confirm this action'), findsNothing);
  });

  testWidgets('a draft marks model suggestions, shows its checks and copies as Markdown', (tester) async {
    await _pump(tester, _Api());
    await tester.tap(find.text('Drafts (1)'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cloud and Containers'));
    await tester.pumpAndSettle();
    expect(find.textContaining('must be reviewed and approved by faculty'), findsOneWidget);
    expect(find.textContaining('model suggestion'), findsWidgets);
    expect(find.text('Reading (unverified)'), findsOneWidget);
    expect(find.text('Citations removed (not in the evidence)'), findsOneWidget);
    final md = markdownOf(_draft);
    expect(md, contains('- A made-up topic *(model suggestion)*'));
    expect(md, contains('- Docker images [D1]'));
    expect(md, contains('**D1**'));
  });

  test('resource status in words, and lesson plans and resource lists in Markdown', () {
    expect(resourceStatus({'status': 'LISTED_IN_CURRICULUM', 'where': 'cbit 22CSC15N p.96'}),
        'listed in the curriculum (cbit 22CSC15N p.96)');
    expect(resourceStatus({'status': 'MODEL_SUGGESTION', 'check': {'check': 'NOT_FOUND_IN_OPEN_LIBRARY'}}),
        'suggested by the model · not found in Open Library: verify before use');
    expect(resourceStatus({'status': 'CURATED', 'check': {'check': 'LINK_OK'}}), 'curated · link checked');
    final md = markdownOf({
      'title': 'Lesson plan', 'label': 'AI-generated draft.', 'evidence': {},
      'content': {
        'sessions': [
          {'number': 1, 'title': 'Intro', 'minutes': 50, 'topics': ['relational model'], 'activities': ['lecture'],
           'assessment': 'quiz'}
        ],
        'items': [
          {'title': 'OSTEP', 'url': 'https://pages.cs.wisc.edu/~remzi/OSTEP/', 'status': 'LISTED_IN_CURRICULUM'}
        ],
      },
    });
    expect(md, contains('## Session 1: Intro (50 min)'));
    expect(md, contains('- Topics: relational model'));
    expect(md, contains('- OSTEP <https://pages.cs.wisc.edu/~remzi/OSTEP/> *(listed in the curriculum)*'));
  });

  testWidgets('when the local model is not running the page says how to fix it', (tester) async {
    await _pump(tester, _Api(ready: false));
    expect(find.text('The local AI model is not running'), findsOneWidget);
    expect(find.textContaining('ollama pull qwen-test'), findsOneWidget);
  });
}
