// Live check of every knowledge screen against a running backend, using the app's own screen specs and API client.
//   dart run tool/live_api_check.dart [http://localhost:8000]  > ../artifacts/flutter_live_api_check.json
// For each screen: the request succeeds, the response is a JSON object, the list the screen renders exists, every
// column the screen shows is present in at least one row and every summary block the screen shows exists. Exit code 1
// on any failure. Input-driven screens are called with a real key read from the Industry Demand endpoint.
import 'dart:convert';
import 'dart:io';

import 'package:skillgap_dashboard/screens/screen_specs.dart';
import 'package:skillgap_dashboard/services/api_client.dart';

dynamic at(dynamic row, String dotted) {
  dynamic cur = row;
  for (final part in dotted.split('.')) {
    if (cur is Map && cur.containsKey(part)) {
      cur = cur[part];
    } else {
      return _missing;
    }
  }
  return cur;
}

const _missing = Object();

Future<void> main(List<String> args) async {
  final api = ApiClient(baseUrl: args.isNotEmpty ? args.first : 'http://localhost:8000');
  final results = <Map<String, dynamic>>[];
  String? skillKey;
  try {
    final d = await api.getJson('/api/v1/industry/demand', query: {'limit': '1'});
    skillKey = ((d['items'] as List).first as Map)['skill_key'] as String;
  } catch (_) {}
  for (final spec in knowledgeScreens) {
    final sw = Stopwatch()..start();
    final r = <String, dynamic>{'screen': spec.title, 'path': spec.path};
    try {
      final q = <String, String>{...?spec.query};
      if (spec.inputParam != null) q[spec.inputParam!] = skillKey ?? '';
      final data = await api.getJson(spec.path, query: q.isEmpty ? null : q);
      r['ms'] = sw.elapsedMilliseconds;
      if (data is! Map<String, dynamic>) throw StateError('not a JSON object');
      r['state'] = data['evidence_state'] ?? data['status'] ?? 'AVAILABLE';
      final problems = <String>[];
      if (spec.listKey != '_none') {
        final rows = data[spec.listKey];
        if (rows is! List) {
          problems.add('list "${spec.listKey}" missing');
        } else {
          r['rows'] = rows.length;
          for (final c in spec.columns) {
            if (rows.isNotEmpty && !rows.any((x) => !identical(at(x, c), _missing))) problems.add('column "$c" absent');
          }
        }
      }
      for (final k in spec.summaryKeys) {
        if (!data.containsKey(k)) problems.add('summary "$k" absent');
      }
      if (spec.componentsKey != null && data[spec.componentsKey] is! Map) problems.add('components absent');
      r['problems'] = problems;
      r['passed'] = problems.isEmpty;
    } catch (e) {
      r['passed'] = false;
      r['error'] = e.toString();
    }
    results.add(r);
  }
  // Redesigned (premium) screens: every endpoint they read answers with the keys they render.
  final premium = <List<dynamic>>[
    ['Overview (premium)', '/api/v1/overview', null, ['run', 'kpis', 'findings', 'attention', 'flow', 'data_scope', 'semantic', 'peer_status']],
    ['Upload: document roles', '/api/v1/metadata/document-roles', null, ['roles', 'fields']],
    ['Upload: disciplines', '/api/v1/metadata/disciplines', null, ['items']],
    ['Upload: sources', '/api/v1/metadata/sources', null, ['sources']],
    ['Upload: posting formats', '/api/v1/metadata/upload-formats', null, ['formats']],
    ['Analysis jobs', '/api/v1/analysis/jobs', null, ['items']],
    ['Global search', '/api/v1/search', {'q': 'network'}, ['items', 'by_type']],
    ['Industry Intelligence', '/api/v1/industry/intelligence', null, ['evidence_state']],
    ['Industry dimensions', '/api/v1/industry/dimensions', null, ['evidence_state']],
    ['Skill clusters', '/api/v1/industry/clusters', null, ['evidence_state']],
    ['Industry Trends (temporal)', '/api/v1/industry/temporal-trends', {'limit': '50'}, ['populations', 'items']],
    ['Peer status', '/api/v1/peers/status', null, ['peer_status', 'status']],
    ['Peer benchmark', '/api/v1/peers/benchmark', null, ['comparisons']],
    ['Occupation resolution', '/api/v1/occupations/resolution', {'limit': '5'}, ['summary', 'items']],
    ['Occupation analysis', '/api/v1/occupations/analysis', null, ['items']],
    ['AI Evaluation', '/api/v1/evaluation/semantic', null, ['status', 'gate_declaration']],
    ['Semantic decisions', '/api/v1/semantic/decisions', {'limit': '5'}, ['items']],
    ['Recommendations', '/api/v1/intelligence/recommendations', null, ['v1', 'withheld_for_review']],
    ['Skill gaps', '/api/v1/intelligence/gaps', {'limit': '5'}, ['items']],
    ['Data lineage', '/api/v1/intelligence/lineage', null, ['run_id', 'sources', 'stages']],
    ['Recompute lineage', '/api/v1/lineage/recompute', null, ['evidence_state']],
    ['System health', '/health', null, ['status', 'components']],
  ];
  for (final p in premium) {
    final sw = Stopwatch()..start();
    final r = <String, dynamic>{'screen': p[0], 'path': p[1]};
    try {
      final data = await api.getJson(p[1] as String, query: (p[2] as Map<String, String>?));
      r['ms'] = sw.elapsedMilliseconds;
      if (data is! Map<String, dynamic>) throw StateError('not a JSON object');
      r['state'] = data['evidence_state'] ?? data['status'] ?? 'AVAILABLE';
      final problems = [
        for (final k in p[3] as List<String>)
          if (!data.containsKey(k)) 'key "$k" absent'
      ];
      r['problems'] = problems;
      r['passed'] = problems.isEmpty;
    } catch (e) {
      r['passed'] = false;
      r['error'] = e.toString();
    }
    results.add(r);
  }
  // Peer differences: called with the first real comparison document of the benchmark.
  {
    final r = <String, dynamic>{'screen': 'Peer differences', 'path': '/api/v1/peers/differences'};
    try {
      final b = await api.getJson('/api/v1/peers/benchmark') as Map<String, dynamic>;
      final comps = (b['comparisons'] as List?) ?? const [];
      if (comps.isEmpty) {
        r['state'] = b['evidence_state'] ?? 'NO_COMPARISON';
        r['problems'] = <String>[];
        r['passed'] = true;
      } else {
        final doc = (comps.first as Map)['comparison_doc_id'] as String;
        final d = await api.getJson('/api/v1/peers/differences', query: {'comparison_doc_id': doc});
        final problems = [if (d is! Map<String, dynamic>) 'not a JSON object'];
        r['comparison_doc_id'] = doc;
        r['problems'] = problems;
        r['passed'] = problems.isEmpty;
      }
    } catch (e) {
      r['passed'] = false;
      r['error'] = e.toString();
    }
    results.add(r);
  }
  // Graph explorer: the evidence of a real node (first concept found by search) returns edges and node labels.
  {
    final r = <String, dynamic>{'screen': 'Knowledge Graph explorer', 'path': '/api/v1/semantic/evidence'};
    try {
      final s = await api.getJson('/api/v1/search', query: {'q': 'network', 'types': 'CONCEPT', 'limit': '1'});
      final node = ((s['items'] as List).first as Map)['id'] as String;
      final d = await api.getJson('/api/v1/semantic/evidence', query: {'node_id': node}) as Map<String, dynamic>;
      final problems = [
        if (d['edges'] is! List) 'edges absent',
        if (d['nodes'] is! Map) 'node labels absent',
      ];
      r['node'] = node;
      r['edges'] = (d['edges'] as List?)?.length;
      r['problems'] = problems;
      r['passed'] = problems.isEmpty;
    } catch (e) {
      r['passed'] = false;
      r['error'] = e.toString();
    }
    results.add(r);
  }
  final passed = results.where((r) => r['passed'] == true).length;
  stdout.writeln(const JsonEncoder.withIndent(' ').convert(
      {'base_url': api.baseUrl, 'screens': results.length, 'passed': passed, 'results': results}));
  exit(passed == results.length ? 0 : 1);
}
