import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../theme/design_system.dart';
import '../../widgets/curriculum_scope_notice.dart';
import '../../widgets/evidence_thread.dart';
import '../../widgets/ui_kit.dart';
import 'pages.dart';

/// Skill gaps (v2): one card per industry-demand skill with its demand support, curriculum coverage, gap state and
/// the reason; "Why?" opens the evidence chain (GET /api/v1/intelligence/evidence-trace).
class SkillGapsScreen extends StatelessWidget {
  const SkillGapsScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return TabbedPage(
      labels: const ['Skills', 'Table'],
      builder: (context, i) => i == 1
          ? specView(api, 'Skill Gap (v2)')
          : ApiView(
              api: api,
              path: '/api/v1/intelligence/gaps',
              query: const {'limit': '500'},
              what: 'the skill gaps',
              builder: (context, d, reload) => _GapCards(api: api, data: d),
            ),
    );
  }
}

class _GapCards extends StatefulWidget {
  const _GapCards({required this.api, required this.data});
  final ApiClient api;
  final Map<String, dynamic> data;

  @override
  State<_GapCards> createState() => _GapCardsState();
}

class _GapCardsState extends State<_GapCards> {
  int _tab = 2; // PARTIAL first (index 0 is All, 1 Covered): where attention is needed
  String _q = '';
  String? _open; // skill key whose evidence thread is open
  int _sort = 0; // 0 most postings, 1 least coverage, 2 A–Z
  bool _confirmedOnly = false;

  static const _sorts = ['Most postings', 'Least coverage', 'A–Z'];
  static const _depth = {'ABSENT': 0, 'MENTION': 1, 'INTRODUCTORY': 2, 'SUBSTANTIAL': 3, 'ADVANCED': 4};

  static bool confirmed(Map<String, dynamic> g) => status(g) == 'Confirmed gap';

  static int Function(Map<String, dynamic>, Map<String, dynamic>) comparator(int sort) {
    int postings(Map<String, dynamic> a, Map<String, dynamic> b) =>
        ((b['posting_count'] ?? 0) as num).compareTo((a['posting_count'] ?? 0) as num);
    return switch (sort) {
      1 => (a, b) {
          final c = (_depth[a['coverage_level']] ?? 9).compareTo(_depth[b['coverage_level']] ?? 9);
          return c != 0 ? c : postings(a, b);
        },
      2 => (a, b) => fmt(a['skill_label']).toLowerCase().compareTo(fmt(b['skill_label']).toLowerCase()),
      _ => postings,
    };
  }

  static const _order = ['COVERED', 'PARTIAL', 'MISSING', 'INSUFFICIENT_EVIDENCE'];
  static const _names = {
    'COVERED': 'Covered',
    'PARTIAL': 'Partial coverage',
    'MISSING': 'Not covered',
    'INSUFFICIENT_EVIDENCE': 'Not enough evidence',
  };

  static const _supported = {'SUPPORTED', 'HIGH_SUPPORT'};

  /// Gap status, kept apart from the coverage classification: confirmed (actionable), marked for review (and why),
  /// or not a gap. Rows from runs that predate `actionable` use the same confirmed-gap rule.
  static String status(Map<String, dynamic> g) {
    final review = asMap(g['review']);
    if (review['code'] == 'CURRICULUM_SCOPE_INCOMPLETE') return 'Marked for review: curriculum incomplete';
    if (review.isNotEmpty) return 'Marked for review: the evidence disagrees';
    final actionable = g['actionable'] ??
        ((g['classification_v2'] == 'PARTIAL' || g['classification_v2'] == 'MISSING') &&
            _supported.contains(g['support_state']) &&
            g['evidence_status'] != 'REVIEW_REQUIRED');
    return actionable == true ? 'Confirmed gap' : 'Not a confirmed gap';
  }

  /// The reading of one row, from its own fields only.
  static String interpretation(Map<String, dynamic> g) {
    final c = fmt(g['classification_v2']);
    final supported = _supported.contains(g['support_state']);
    final review = asMap(g['review']);
    if (review['code'] == 'CURRICULUM_SCOPE_INCOMPLETE') {
      return '${c == 'MISSING' ? 'Not covered' : 'Partial coverage'} in the supplied semesters, but the curriculum supplied '
          'lacks semesters ${CurriculumScopeNotice.semesters(asList(review['missing_semesters']))}, where it may be '
          'taught: marked for review, not a confirmed gap.';
    }
    if (review.isNotEmpty) {
      return 'Topic coverage is limited, but ${asList(review['courses']).map(fmt).join(', ')} '
          '${asList(review['courses']).length == 1 ? 'is' : 'are'} named after it: the evidence disagrees and needs review.';
    }
    switch (c) {
      case 'MISSING':
        return supported
            ? 'Not covered while industry demand is supported: a confirmed gap.'
            : 'Not covered, but the industry signal is too limited to confirm a gap.';
      case 'PARTIAL':
        return supported
            ? 'Partial coverage with supported demand: a confirmed gap to review.'
            : 'Partial coverage; the industry signal is too limited to confirm a gap.';
      case 'COVERED':
        return 'Covered in the curriculum; no gap.';
      default:
        return 'Too little evidence on one side to classify; nothing is concluded.';
    }
  }

  @override
  Widget build(BuildContext context) {
    final items = asList(widget.data['items']).map(asMap).toList();
    final counts = <String, int>{};
    for (final g in items) {
      final c = fmt(g['classification_v2']);
      counts[c] = (counts[c] ?? 0) + 1;
    }
    final state = _tab == 0 ? null : _order[_tab - 1];
    final shown = items
        .where((g) => state == null || g['classification_v2'] == state)
        .where((g) => _q.isEmpty || fmt(g['skill_label']).toLowerCase().contains(_q.toLowerCase()))
        .where((g) => !_confirmedOnly || confirmed(g))
        .toList()
      ..sort(comparator(_sort));
    final confirmedCount = items
        .where((g) => (g['classification_v2'] == 'PARTIAL' || g['classification_v2'] == 'MISSING') &&
            _supported.contains(g['support_state']) &&
            g['evidence_status'] != 'REVIEW_REQUIRED')
        .length;
    final warning = at(widget.data, 'scope.population_scope.representativeness_warning');
    final scope = asMap(at(widget.data, 'scope.curriculum_scope'));
    final reviewed = items.where((g) => g['evidence_status'] == 'REVIEW_REQUIRED').length;
    final scopeLimited = items.where((g) => g['scope_limited'] == true).length;
    return PageFrame(children: [
      ResearchHeader(
        eyebrow: 'Skill gaps',
        title: confirmedCount == 0 ? 'No confirmed skill gaps' : '$confirmedCount confirmed skill gap${confirmedCount == 1 ? '' : 's'}',
        sentence: '${items.length} skills with industry demand were compared with the curriculum. A gap is confirmed only '
            'when coverage is partial or missing, the industry demand is supported by enough postings, and nothing in '
            'the evidence needs review${reviewed == 0 ? '' : ' ($reviewed marked for review)'}.',
      ),
      CurriculumScopeNotice(scope, scopeLimited: scopeLimited),
      if (warning != null)
        Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.xxl),
          child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: AppLayout.measure),
              child: Text(warning.toString(), style: AppTypography.caption)),
        ),
      Wrap(spacing: AppSpacing.xxl, runSpacing: AppSpacing.md, crossAxisAlignment: WrapCrossAlignment.end, children: [
        QuietFilter(
          labels: ['All ${items.length}', for (final s in _order) '${_names[s]} ${counts[s] ?? 0}'],
          selected: _tab,
          onSelect: (i) => setState(() {
            _tab = i;
            _open = null;
          }),
        ),
        SizedBox(
          width: 220,
          child: TextField(
            style: AppTypography.muted.copyWith(color: AppColors.text),
            decoration: const InputDecoration(
                prefixIcon: Icon(Icons.search, size: 16),
                prefixIconConstraints: BoxConstraints(minWidth: 28, minHeight: 20),
                hintText: 'Find a skill'),
            onChanged: (v) => setState(() => _q = v),
          ),
        ),
        Row(mainAxisSize: MainAxisSize.min, children: [
          Text('Sort', style: AppTypography.caption),
          const SizedBox(width: AppSpacing.sm),
          SegmentTabs(labels: _sorts, selected: _sort, onSelect: (i) => setState(() => _sort = i)),
        ]),
        FilterChip(
          label: const Text('Confirmed gaps only'),
          selected: _confirmedOnly,
          onSelected: (v) => setState(() {
            _confirmedOnly = v;
            _open = null;
          }),
        ),
      ]),
      const SizedBox(height: AppSpacing.block),
      AnimatedSwitcher(
        duration: AppMotion.normal,
        switchInCurve: AppMotion.curve,
        layoutBuilder: (current, previous) =>
            Stack(alignment: Alignment.topLeft, children: [...previous, if (current != null) current]),
        child: KeyedSubtree(
          key: ValueKey('$_tab:$_q:$_sort:$_confirmedOnly'),
          child: shown.isEmpty
              ? const EmptyState(title: 'No skill here', body: 'Choose another state or clear the search.')
              : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  for (final (i, g) in shown.take(120).indexed) _item(i + 1, g),
                  if (shown.length > 120)
                    Text('Showing 120 of ${shown.length}; search to narrow the list.', style: AppTypography.caption),
                ]),
        ),
      ),
    ]);
  }

  Widget _item(int index, Map<String, dynamic> g) {
    final open = _open == g['skill_key'];
    final cls = fmt(g['classification_v2']);
    final relation = fmt(g['coverage_relation']);
    return InsightItem(
      index: index,
      kicker: _names[cls] ?? StatusStyle.label(cls),
      title: fmt(g['skill_label']),
      reading: interpretation(g),
      evidence: [
        MapEntry('Industry', '${fmtCount(g['posting_count'])} of ${fmtCount(g['eligible_postings'])} postings, '
            '${StatusStyle.label(fmt(g['support_state'])).toLowerCase()}'),
        MapEntry('Curriculum', '${StatusStyle.label(fmt(g['coverage_level'])).toLowerCase()}'
            '${relation == 'NONE' ? ', no matching topic' : relation == '—' ? '' : ', matching topics found'}'),
        MapEntry('Status', status(g)),
      ],
      action: open ? 'Hide evidence' : 'View evidence →',
      open: open,
      onToggle: () => setState(() => _open = open ? null : fmt(g['skill_key'])),
      openContent: open
          ? EvidenceThread(api: widget.api, skillKey: fmt(g['skill_key']), skillLabel: fmt(g['skill_label']))
          : null,
    );
  }
}
