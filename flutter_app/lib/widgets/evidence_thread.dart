import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../theme/design_system.dart';
import '../theme/plain_language.dart';
import 'ui_kit.dart';

/// The evidence thread: for one skill, the real chain the analysis rests on, drawn as a research trail --
///   job postings → skill → industry demand → curriculum → coverage → gap → decision
/// read from GET /api/v1/intelligence/evidence-trace (stored trace or one assembled from GOLD). The trail draws itself
/// stage by stage; a stage the evidence cannot establish is drawn hollow and says so -- it is never filled in.
class EvidenceThread extends StatefulWidget {
  const EvidenceThread({super.key, required this.api, required this.skillKey, required this.skillLabel, this.onClose});
  final ApiClient api;
  final String skillKey;
  final String skillLabel;
  final VoidCallback? onClose;

  @override
  State<EvidenceThread> createState() => _EvidenceThreadState();
}

class _EvidenceThreadState extends State<EvidenceThread> {
  Future<dynamic>? _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant EvidenceThread old) {
    super.didUpdateWidget(old);
    if (old.skillKey != widget.skillKey) _load();
  }

  void _load() {
    _future = widget.api.getJson('/api/v1/intelligence/evidence-trace', query: {'skill_key': widget.skillKey});
  }

  static String _clip(String s, int n) => s.length <= n ? s : '${s.substring(0, n).trimRight()}…';

  List<TrailStepData> _steps(Map<String, dynamic> d) {
    final t = asMap(d['trace']);
    final posts = asList(t['job_postings']).map(asMap).toList();
    final demand = asMap(t['industry_demand']);
    final esco = asMap(t['esco']);
    final target = asList(d['coverage_depth']).map(asMap).where((r) => r['role'] == 'TARGET').toList();
    final courseEv = target.isEmpty ? <Map<String, dynamic>>[] : asList(target.first['evidence']).map(asMap).toList();
    final courses = {for (final e in courseEv) fmt(e['course_code'])}.toList();
    final gap = asMap(t['gap']);
    final rec = asMap(t['recommendation']);
    final no = asMap(t['no_recommendation']);
    final review = gap['evidence_status'] == 'REVIEW_REQUIRED';
    final firstReason = asMap(asList(gap['reasons']).isNotEmpty && review
        ? asList(gap['reasons']).first
        : (asList(no['reasons']).isNotEmpty ? asList(no['reasons']).first : null));
    final postingCount = demand['posting_count'] ?? posts.length;
    return [
      TrailStepData(
        label: 'Job postings',
        headline: posts.isEmpty ? 'No posting' : '${fmtCount(postingCount)} postings mention it',
        caption: posts.isEmpty
            ? null
            : [for (final p in posts.take(3)) '${fmt(p['job_title'])}, ${fmt(p['company'])}'].join('; '),
        // verbatim: a quote is never reworded
        quotes: [for (final p in posts.take(2)) '…${_clip('${p['context'] ?? '—'}'.trim(), 180)}…'],
        established: posts.isNotEmpty,
      ),
      TrailStepData(
        label: 'Skill',
        headline: fmt(asMap(t['normalized_skill'])['label'] ?? widget.skillLabel),
        lines: [
          if (esco['pref_label'] != null)
            'In the skills reference as “${fmt(esco['pref_label'])}” (${StatusStyle.label(fmt(esco['status'])).toLowerCase()})',
        ],
      ),
      TrailStepData(
        label: 'Industry demand',
        headline: demand.isEmpty
            ? 'Not measured'
            : '${fmtCount(postingCount)} of ${fmtCount(demand['eligible_postings'])} postings',
        lines: [
          if (demand['support_state'] != null) 'Demand support: ${StatusStyle.label(fmt(demand['support_state'])).toLowerCase()}',
          if (demand['statement'] != null) fmt(demand['statement']),
        ],
        established: demand.isNotEmpty,
      ),
      TrailStepData(
        label: 'Curriculum',
        headline: courses.isEmpty ? 'No course found' : '${courses.length} course${courses.length == 1 ? '' : 's'}',
        lines: [for (final e in courseEv.take(4)) '${fmt(e['course_code'])} p.${fmt(e['page'])}: ${e['text'] ?? '—'}'],
        established: courseEv.isNotEmpty,
      ),
      TrailStepData(
        label: 'Coverage',
        headline: target.isEmpty ? 'Not assessed' : StatusStyle.label(fmt(target.first['coverage_level'])),
        lines: [if (target.isNotEmpty && target.first['level_reason'] != null) fmt(target.first['level_reason'])],
        established: target.isNotEmpty,
      ),
      TrailStepData(
        label: 'Gap',
        headline: gap['classification'] == null ? 'Not classified' : _gapWords(fmt(gap['classification'])),
        lines: [
          if (review) 'The coverage measures disagree; a reviewer decides.',
          for (final r in asList(gap['reasons']).take(2))
            if (r is String) Plain.sentence(r),
        ],
        established: gap['classification'] != null,
      ),
      TrailStepData(
        label: 'Decision',
        headline: rec.isNotEmpty
            ? 'Recommendation issued'
            : review
                ? 'Withheld for review'
                : 'No recommendation',
        lines: [
          if (rec.isNotEmpty) StatusStyle.label(fmt(rec['action_type'])),
          if (firstReason.isNotEmpty) Plain.sentence(fmt(firstReason['detail'] ?? StatusStyle.label(fmt(firstReason['code'])))),
        ],
      ),
    ];
  }

  static String _gapWords(String c) => switch (c) {
        'PARTIAL' => 'Partial coverage',
        'MISSING' => 'Not covered',
        'COVERED' => 'Covered',
        _ => StatusStyle.label(c),
      };

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<dynamic>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Padding(
              padding: EdgeInsets.symmetric(vertical: AppSpacing.lg), child: SkeletonBlock(width: 420, height: 14));
        }
        if (snap.hasError || asMap(snap.data)['trace'] == null) {
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: AppSpacing.lg),
            child: Text('Evidence is insufficient to establish this relationship for ${widget.skillLabel}.',
                style: AppTypography.muted),
          );
        }
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
            Expanded(child: Text('Evidence thread · ${widget.skillLabel}', style: AppTypography.overline)),
            if (widget.onClose != null)
              IconButton(
                  tooltip: 'Close the evidence thread',
                  icon: const Icon(Icons.close, size: 16),
                  onPressed: widget.onClose),
          ]),
          const SizedBox(height: AppSpacing.md),
          Trail(steps: _steps(asMap(snap.data)), compact: true),
        ]);
      },
    );
  }
}
