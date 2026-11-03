import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../theme/design_system.dart';
import '../../theme/plain_language.dart';
import '../../widgets/ui_kit.dart';
import 'pages.dart';

/// Curriculum drift as movement through time: the two curriculum versions on a trail, then the changes that matter
/// (added, removed, evolved, recoded), with the unchanged courses folded away. Only the versions that exist are shown
/// -- nothing is interpolated between them. Data: GET /api/v1/curriculum/course-drift and the run's documents
/// (GET /api/v1/intelligence/lineage) for the version names.
class CurriculumDriftScreen extends StatelessWidget {
  const CurriculumDriftScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return TabbedPage(
      labels: const ['Timeline', 'Table'],
      builder: (context, i) => i == 1
          ? specView(api, 'Course Drift & Lineage')
          : ApiView(
              api: api,
              path: '/api/v1/intelligence/lineage',
              what: 'the curriculum versions',
              builder: (context, lineage, _) => ApiView(
                api: api,
                path: '/api/v1/curriculum/course-drift',
                query: const {'limit': '500'},
                what: 'curriculum changes',
                builder: (context, d, reload) => asList(d['items']).isNotEmpty
                    ? _Timeline(lineage: lineage, d: d)
                    // no versions of one programme: another programme of the same institution may still be compared,
                    // and is presented as such -- never as changes over time
                    : ApiView(
                        api: api,
                        path: '/api/v1/curriculum/programme-comparison',
                        query: const {'limit': '500'},
                        what: 'the programme comparison',
                        builder: (context, pc, _) => asMap(pc['comparison'])['status'] == 'ALLOWED'
                            ? _ProgrammeComparison(pc)
                            : _Timeline(lineage: lineage, d: d),
                      ),
              ),
            ),
    );
  }
}

/// Course matches made by shared content under a different title (course lineage).
const _related = {'EVOLVED', 'RENAMED', 'MERGED', 'SPLIT'};

class _Timeline extends StatelessWidget {
  const _Timeline({required this.lineage, required this.d});
  final Map<String, dynamic> lineage;
  final Map<String, dynamic> d;

  Map<String, dynamic> _doc(String role) =>
      asList(lineage['sources']).map(asMap).firstWhere((s) => s['role'] == role, orElse: () => const <String, dynamic>{});

  static String _version(Map<String, dynamic> doc, String fallback) => doc.isEmpty
      ? fallback
      : [doc['curriculum_version'], if (doc['academic_year'] != null) '(${fmt(doc['academic_year'])})'].map(fmt).join(' ');

  static String _sentence(dynamic note) {
    final t = note == null ? '' : fmt(note).trim().replaceAll(RegExp(r'\.+$'), '');
    return t.isEmpty ? '' : ' ${t[0].toUpperCase()}${t.substring(1)}.';
  }

  @override
  Widget build(BuildContext context) {
    final items = asList(d['items']).map(asMap).toList();
    final statuses = asMap(d['statuses']);
    final excluded = asMap(d['excluded']);
    final prev = _doc('PREVIOUS_VERSION');
    final target = _doc('TARGET');
    final prevName = fmt(prev['curriculum_version'] ?? 'previous version');
    final targetName = fmt(target['curriculum_version'] ?? 'current version');
    List<Map<String, dynamic>> of(String s) => items.where((i) => i['status'] == s).toList();
    final related = items.where((i) => _related.contains(i['status'])).toList();
    final prevCount = items.where((i) => i['previous_code'] != null).length;
    final targetCount = items.where((i) => i['target_code'] != null).length;
    final outside = excluded['target_outside_comparable_semesters'];
    String count(String s) => fmtCount(statuses[s] ?? of(s).length);

    if (items.isEmpty) {
      return const PageFrame(children: [
        ResearchHeader(
          eyebrow: 'Curriculum changes',
          title: 'No earlier version of this programme to compare with',
          sentence: 'Changes over time are measured between two versions of the same programme. Add an earlier '
              'curriculum of this programme under New analysis to see what changed.',
        ),
      ]);
    }
    return PageFrame(children: [
      ResearchHeader(
        eyebrow: 'Curriculum changes',
        title: 'How the curriculum changed from $prevName to $targetName',
        sentence: '${fmtCount(items.length)} courses in the semesters both versions share were matched by title and by '
            'shared concepts.${_sentence(d['note'])}',
      ),
      EditorialSection(
        label: 'Two versions',
        child: Trail(steps: [
          TrailStepData(
            label: fmt(prev['academic_year'] ?? 'earlier'),
            headline: _version(prev, prevName),
            caption: '${fmtCount(prevCount)} courses in the compared semesters',
            lines: [
              if (prev['programme'] != null) fmt(prev['programme']),
            ],
          ),
          TrailStepData(
            label: fmt(target['academic_year'] ?? 'current'),
            headline: _version(target, targetName),
            caption: '${fmtCount(targetCount)} courses in the compared semesters',
            lines: [
              '${count('ADDED')} added, ${count('REMOVED')} removed, ${fmtCount(related.length)} evolved or renamed, '
                  '${count('RETAINED_RECODED')} recoded and ${count('RETAINED')} retained.',
              if (outside is num && outside > 0)
                '${fmtCount(outside)} courses of later semesters have no counterpart in the earlier document and are not compared.',
            ],
          ),
        ]),
      ),
      if (related.isNotEmpty)
        EditorialSection(
          label: 'Evolved or renamed',
          aside: Text(fmtCount(related.length), style: AppTypography.metric),
          intro: 'A course replaced by a differently named one that carries much of the same content.',
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final c in related) _Change.evolved(c),
          ]),
        ),
      if (of('ADDED').isNotEmpty)
        EditorialSection(
          label: 'Added',
          aside: Text(count('ADDED'), style: AppTypography.metric),
          intro: 'In $targetName, with no course of the same title in $prevName.',
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final c in of('ADDED')) _Change(code: fmt(c['target_code']), title: fmt(c['title']), semester: c['target_semester']),
          ]),
        ),
      if (of('REMOVED').isNotEmpty)
        EditorialSection(
          label: 'Removed',
          aside: Text(count('REMOVED'), style: AppTypography.metric),
          intro: 'In $prevName, with no course of the same title in $targetName.',
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final c in of('REMOVED'))
              _Change(code: fmt(c['previous_code']), title: fmt(c['title']), semester: c['previous_semester']),
          ]),
        ),
      if (of('RETAINED_RECODED').isNotEmpty)
        EditorialSection(
          label: 'Recoded',
          aside: Text(count('RETAINED_RECODED'), style: AppTypography.metric),
          intro: 'The same course under a new code.',
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final c in of('RETAINED_RECODED'))
              _Change(
                  code: '${fmt(c['previous_code'])} → ${fmt(c['target_code'])}',
                  title: fmt(c['title']),
                  semester: c['target_semester']),
          ]),
        ),
      if (of('RETAINED').isNotEmpty)
        EditorialSection(
          label: 'Unchanged',
          aside: Text(count('RETAINED'), style: AppTypography.metric),
          spacing: 0,
          child: EvidenceDisclosure(
            title: 'Show the ${count('RETAINED')} retained courses',
            openTitle: 'Hide the retained courses',
            children: [
              for (final c in of('RETAINED')) _Change(code: fmt(c['target_code']), title: fmt(c['title']), semester: c['target_semester']),
            ],
          ),
        ),
    ]);
  }
}

/// One change, as a line of text: code, title, semester, and (for an evolved course) what it became and why.
class _Change extends StatelessWidget {
  const _Change({required this.code, required this.title, this.semester, this.note});
  final String code;
  final String title;
  final dynamic semester;
  final String? note;

  factory _Change.evolved(Map<String, dynamic> c) {
    final l = asList(c['lineage']).map(asMap).toList();
    final first = l.isEmpty ? const <String, dynamic>{} : l.first;
    final share = first['share_of_previous'];
    return _Change(
      code: '${fmt(c['previous_code'])} → ${fmt(c['target_code'])}',
      title: '${fmt(c['previous_title'] ?? first['previous_title'] ?? c['title'])} → '
          '${fmt(c['target_title'] ?? first['target_title'] ?? c['title'])}',
      semester: c['target_semester'],
      note: first.isEmpty
          ? null
          : '${fmt(first['matched_previous_topics'])} topics in common'
              '${share is num ? ', ${(share * 100).round()}% of the earlier course' : ''}',
    );
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: AppTypography.body),
        Text(
            [code, if (semester != null) 'semester ${fmt(semester)}', if (note != null) note!].join(', '),
            style: AppTypography.caption),
      ]),
    );
  }
}


/// Two different programmes of one institution compared on the semesters both documents cover. The page says so in its
/// title and first sentence: these are differences between programmes, not changes over time.
class _ProgrammeComparison extends StatelessWidget {
  const _ProgrammeComparison(this.pc);
  final Map<String, dynamic> pc;

  /// "B.E. Computer Science and Engineering R22A", "BE. (AIML) R26": the programme as the metadata names it.
  static String _name(Map<String, dynamic> m) {
    final programme = (m['programme'] ?? m['discipline'] ?? '').toString().trim();
    final spec = (m['specialization'] ?? '').toString().trim();
    final version = (m['curriculum_version'] ?? '').toString().trim();
    return [
      if (programme.isNotEmpty) programme,
      if (spec.isNotEmpty) '($spec)',
      if (version.isNotEmpty) version,
    ].join(' ');
  }

  @override
  Widget build(BuildContext context) {
    final c = asMap(pc['comparison']);
    final current = asMap(c['current']);
    final other = asMap(c['comparison']);
    final items = asList(pc['items']).map(asMap).toList();
    List<Map<String, dynamic>> of(String s) => items.where((i) => i['status'] == s).toList();
    final cur = _name(current);
    final oth = _name(other);
    final semesters = asList(c['comparable_semesters']).map(fmt).join(', ');
    final reasons = Plain.sentence(asList(asMap(c['relation'])['reasons']).map(fmt).join('; '));
    Widget list(List<Map<String, dynamic>> rows, {bool inCurrent = true}) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final r in rows)
              _Change(
                  code: fmt(inCurrent ? r['target_code'] : r['previous_code']),
                  title: fmt(r['title']),
                  semester: inCurrent ? r['target_semester'] : r['previous_semester']),
          ],
        );
    return PageFrame(children: [
      ResearchHeader(
        eyebrow: 'Programme comparison',
        title: 'How $cur compares with $oth',
        sentence: 'These are two different programmes of ${fmt(current['institution'] ?? other['institution'])}'
            '${reasons.isEmpty ? '' : ' ($reasons)'}. They are compared on the semesters both documents cover'
            '${semesters.isEmpty ? '' : ' ($semesters)'}; the differences are between programmes, not changes over time.',
      ),
      if (of('ADDED').isNotEmpty)
        EditorialSection(
          label: 'Only in $cur',
          aside: Text(fmtCount(of('ADDED').length), style: AppTypography.metric),
          child: list(of('ADDED')),
        ),
      if (of('REMOVED').isNotEmpty)
        EditorialSection(
          label: 'Only in $oth',
          aside: Text(fmtCount(of('REMOVED').length), style: AppTypography.metric),
          child: list(of('REMOVED'), inCurrent: false),
        ),
      if (items.any((i) => _related.contains(i['status'])))
        EditorialSection(
          label: 'Related courses',
          aside: Text(fmtCount(items.where((i) => _related.contains(i['status'])).length), style: AppTypography.metric),
          intro: 'Differently named courses that share much of their content.',
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final r in items.where((i) => _related.contains(i['status']))) _Change.evolved(r),
          ]),
        ),
      if (of('RETAINED').isNotEmpty || of('RETAINED_RECODED').isNotEmpty)
        EditorialSection(
          label: 'In both',
          aside: Text(fmtCount(of('RETAINED').length + of('RETAINED_RECODED').length), style: AppTypography.metric),
          spacing: 0,
          child: EvidenceDisclosure(
            title: 'Show the courses both programmes share',
            openTitle: 'Hide the shared courses',
            children: [
              for (final r in [...of('RETAINED'), ...of('RETAINED_RECODED')])
                _Change(code: fmt(r['target_code']), title: fmt(r['title']), semester: r['target_semester']),
            ],
          ),
        ),
    ]);
  }
}
