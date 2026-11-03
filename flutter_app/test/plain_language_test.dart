// The user-facing language layer and a static terminology audit of the frontend source. No widgets: the rendered
// audit is in premium_ui_test.dart ("no screen shows a backend code ...").
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:skillgap_dashboard/theme/design_system.dart';
import 'package:skillgap_dashboard/theme/plain_language.dart';

/// Terms that must never reach the normal view (the completion directive's list, plus any code shape).
final _internal = RegExp(r'\bTARGET\b|PREVIOUS_VERSION|CURRENT_VERSION|concept_drift|analytics gate|pipeline run|'
    r'record_counts_json|source_id|programme_id|course_id|INSUFFICIENT_EVIDENCE|REVIEW_REQUIRED|SAFE_MODE|'
    r'SAME_CONCEPT|PARTIAL_OVERLAP|\b[A-Z]{2,}(?:_[A-Z0-9]+)+\b');

void _clean(String s) => expect(_internal.hasMatch(s), isFalse, reason: 'internal term in "$s"');

/// The reasons the backend actually writes (backend/app/knowledge_engine/health.py, pipeline.py, analysis_jobs.py).
const _backendReasons = {
  'concept_discovery': 'every document failed the health gate: [doc-a]',
  'reference_mapping': 'needs a healthy TARGET and REFERENCE document (failed: [])',
  'concept_drift': 'needs healthy TARGET + PREVIOUS_VERSION documents of the same programme with at least one '
      'comparable semester',
  'skill_taxonomy': 'no skill taxonomy (ESCO) is loaded; tool/technology CANDIDATES are produced instead, no taxonomy '
      'skills',
  'industry_gap': 'industry population: 12 real job postings (minimum 50); demand, gap classification and alignment '
      'cannot be computed without it',
  'industry_demand': 'industry health gate FAILED; demand, gaps and recommendations are not produced',
  'recommendations': 'recommendations require an industry-evidenced gap classification, which is blocked',
  'peer_benchmark': 'needs a healthy TARGET and at least one healthy PEER curriculum',
  'programme_comparison': 'the two programmes share no comparable semester',
};

void main() {
  group('the screenshot case', () {
    const raw = 'analytics gates blocked: concept_drift: needs healthy TARGET + PREVIOUS_VERSION documents of the '
        'same programme with at least one comparable semester';

    test('says what happened, why, and what to do, in words', () {
      final e = Plain.analysisOutcome('NEEDS_REVIEW', raw);
      expect(e.what, 'We couldn\'t compare this curriculum with an earlier version yet.');
      expect(e.why.single, contains('An earlier curriculum for the same programme is required'));
      expect(e.actions, contains('Upload an earlier curriculum for the same programme'));
      expect(e.actions, contains('Review the current extraction'));
      expect(e.actions.last, 'Run the analysis again');
      for (final s in [e.what, ...e.why, ...e.actions]) {
        _clean(s);
      }
    });

    test('keeps the original text for the technical details', () {
      expect(Plain.analysisOutcome('NEEDS_REVIEW', raw).technical, raw);
    });
  });

  test('every requirement the backend can block is explained without backend terms, with a next step', () {
    for (final e in _backendReasons.entries) {
      final ex = Plain.analysisOutcome('NEEDS_REVIEW', 'analytics gates blocked: ${e.key}: ${e.value}');
      expect(ex.why, isNotEmpty, reason: e.key);
      expect(ex.actions, isNotEmpty, reason: e.key); // at least "Run the analysis again"
      for (final s in [ex.what, ...ex.why, ...ex.actions]) {
        _clean(s);
      }
      _clean(Plain.sentence(e.value)); // the same reason shown as prose elsewhere
    }
  });

  test('several blocked requirements are each named and explained; reasons containing ";" are not split', () {
    final reason = 'analytics gates blocked: ${_backendReasons.entries.map((e) => '${e.key}: ${e.value}').join('; ')}';
    final blocked = Plain.blockedRequirements(reason);
    expect(blocked.keys.toSet(), _backendReasons.keys.toSet());
    expect(blocked['skill_taxonomy'], _backendReasons['skill_taxonomy']); // contains its own "; "
    final ex = Plain.analysisOutcome('NEEDS_REVIEW', reason);
    expect(ex.why.length, _backendReasons.length);
    expect(ex.why.any((w) => w.startsWith('Skill-gap analysis: Only 12 job postings are available; at least 50 are needed.')),
        isTrue);
    expect(ex.actions.toSet().length, ex.actions.length); // no repeated advice
  });

  test('a failure or an unreachable service is explained, with the original kept as technical detail', () {
    final failed = Plain.analysisOutcome('ANALYSIS_FAILED', 'KeyError: \'courses\'');
    expect(failed.what, 'The analysis stopped before it produced results.');
    expect(failed.why.single, isNot(contains('KeyError')));
    expect(failed.technical, contains('KeyError'));
    final offline = Plain.error(Exception('socket'), 'the overview');
    expect(offline.what, 'Could not load the overview.');
    expect(offline.why.single, 'The analysis service could not be reached.');
    expect(offline.actions, isNotEmpty);
    final notFound = Plain.error(null, 'the peer comparison', statusCode: 404, code: 'NOT_FOUND', message: 'no run');
    expect(notFound.why.single, 'This information is not available for the selected analysis.');
    expect(notFound.technical, contains('HTTP 404'));
  });

  test('internal terms are translated (completion directive examples)', () {
    const expected = {
      'TARGET': 'Current curriculum',
      'PREVIOUS_VERSION': 'Earlier curriculum',
      'CURRENT_VERSION': 'Current curriculum',
      'SAME_CONCEPT': 'Equivalent concept',
      'RELATED': 'Related concept',
      'PARTIAL_OVERLAP': 'Partial overlap',
      'INSUFFICIENT_EVIDENCE': 'Not enough evidence',
      'REVIEW_REQUIRED': 'Needs review',
      'NO_MATCH': 'No comparable match found',
    };
    expected.forEach((code, words) => expect(StatusStyle.label(code), words, reason: code));
    expect(Plain.analysis('concept_drift'), 'Curriculum changes');
    expect(Plain.field('run_id'), 'Analysis reference');
    expect(Plain.field('source_id'), 'Source');
    expect(Plain.field('eligible_postings'), 'Job postings included in the analysis');
    expect(Plain.field('temporal_population'), 'Time-period evidence');
    expect(Plain.field('record_counts_json'), 'Evidence checked');
    expect(Plain.field('provenance.course_code'), 'Course code');
    expect(Plain.field('files_verified'), 'Files verified'); // unknown names: words, never underscores
  });

  test('values: codes become words; acronyms, names and identifiers are left as they are', () {
    expect(Plain.value('TARGET'), 'Current curriculum');
    expect(Plain.value(['TARGET', 'PEER']), 'Current curriculum, Peer curriculum');
    expect(Plain.value('JOB_BOARD'), 'Job board');
    expect(Plain.value('CSE'), 'CSE');
    expect(Plain.value('22CSC15N'), '22CSC15N');
    expect(Plain.value('Operating Systems'), 'Operating Systems');
    expect(Plain.prose('TARGET'), 'TARGET'); // a single token is a value, not prose: comparisons stay intact
    expect(Plain.prose('Target-curriculum courses'), 'Current-curriculum courses');
    expect(Plain.prose('every course extracted from Some Institute'), 'every course extracted from Some Institute');
  });

  test('every status the UI styles has a label without underscores', () {
    for (final v in [...StatusStyle.human.keys, ...Plain.terms.keys]) {
      expect(StatusStyle.label(v).contains('_'), isFalse, reason: v);
    }
  });

  group('static terminology audit of lib/', () {
    final files = Directory('lib').listSync(recursive: true).whereType<File>().where((f) => f.path.endsWith('.dart'));
    // a string literal that is prose (has a space and a letter); codes used for comparisons and map keys have no
    // space and are not shown
    final literal = RegExp(r"'((?:[^'\\\n]|\\.)*)'" '|' r'"((?:[^"\\\n]|\\.)*)"');

    test('no prose string in the frontend uses an internal term', () {
      final offences = <String>[];
      for (final f in files) {
        if (f.path.endsWith('plain_language.dart')) continue; // the mapping itself
        final lines = f.readAsLinesSync();
        for (var i = 0; i < lines.length; i++) {
          final line = lines[i].trim();
          if (line.startsWith('//') || line.startsWith('///') || line.startsWith('import ')) continue;
          for (final m in literal.allMatches(line)) {
            final s = m[1] ?? m[2] ?? '';
            if (!s.contains(' ') || s.startsWith('/api/') || s.contains('\$baseUrl')) continue;
            if (_internal.hasMatch(s)) offences.add('${f.path}:${i + 1}: $s');
          }
        }
      }
      expect(offences, isEmpty, reason: offences.join('\n'));
    });

    test('no backend code is put on screen as a literal', () {
      final shown = RegExp(r"""(?:Text|Eyebrow|StatusBanner\(.*title:|title:|label:|subtitle:)\s*\(?\s*'([A-Z]{2,}(?:_[A-Z0-9]+)*)'""");
      final offences = <String>[];
      for (final f in files) {
        final lines = f.readAsLinesSync();
        for (var i = 0; i < lines.length; i++) {
          for (final m in shown.allMatches(lines[i])) {
            if (Plain.isCode(m[1]!)) offences.add('${f.path}:${i + 1}: ${m[1]}');
          }
        }
      }
      expect(offences, isEmpty, reason: offences.join('\n'));
    });

    test('the language layer names no institution, programme or branch', () {
      final src = File('lib/theme/plain_language.dart').readAsStringSync();
      final code = src.split('\n').where((l) => !l.trim().startsWith('//')).join('\n');
      for (final w in ['CBIT', 'Chaitanya', 'IIT', 'CSE', 'Computer Science', 'Mechanical', 'Civil', 'Electrical',
        'AI & DS', 'R22', 'R26']) {
        expect(code.contains(w), isFalse, reason: w);
      }
    });
  });

  test('a fresh installation says there is no analysis yet and how to start, not that loading failed', () {
    final e = Plain.error(Exception('404'), 'the overview', statusCode: 404, code: 'NO_ANALYSIS_YET',
        message: 'no analysis has been run on this machine yet');
    expect(e.what, 'No analysis yet.');
    expect(e.why.single, contains('Open New analysis'));
    expect(e.what, isNot(contains('Could not load')));
    final other = Plain.error(Exception('404'), 'the overview', statusCode: 404, code: 'RUN_NOT_FOUND');
    expect(other.what, 'Could not load the overview.');
  });
}
