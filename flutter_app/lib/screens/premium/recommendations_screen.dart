import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../theme/design_system.dart';
import '../../theme/plain_language.dart';
import '../../widgets/ui_kit.dart';
import 'pages.dart';

/// Recommendations as an intelligence report: action, evidence strength (states, never a confidence %), target
/// courses, industry and curriculum evidence, reasons, and the full evidence chain on demand.
class RecommendationsScreen extends StatelessWidget {
  const RecommendationsScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return TabbedPage(
      labels: const ['Recommendations', 'Table'],
      builder: (context, i) => i == 1
          ? specView(api, 'Recommendations')
          : ApiView(
              api: api,
              path: '/api/v1/intelligence/recommendations',
              what: 'the recommendations',
              builder: (context, d, reload) {
                final recs = asList(d['v1']);
                final withheld = asList(d['withheld_for_review']).map(asMap).toList();
                final reasons = asMap(d['suppressed_by_reason']);
                final notRec = reasons.entries
                    .where((e) => !_withheldForReview.contains(e.key))
                    .toList();
                final notRecTotal = notRec.fold<num>(0, (a, e) => a + (e.value is num ? e.value as num : 0));
                final warning = at(d, 'scope.population_scope.representativeness_warning');
                return PageFrame(children: [
                  ResearchHeader(
                    eyebrow: 'Decisions',
                    title: recs.isEmpty
                        ? 'No recommendation issued'
                        : '${recs.length} recommendation${recs.length == 1 ? '' : 's'} issued',
                    sentence: 'A recommendation is issued only when coverage is partial or missing, industry demand is '
                        'supported and nothing in the evidence needs review. ${withheld.length} more are held for review and '
                        '${fmtCount(notRecTotal)} are not recommended, each with its reason. Recommendations are '
                        'inferences from the evidence, never source facts.',
                  ),
                  if (warning != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: AppSpacing.block),
                      child: ConstrainedBox(
                          constraints: const BoxConstraints(maxWidth: AppLayout.measure),
                          child: Text(
                              '$warning Demand is counted in the job postings analysed; a recommendation that rests on '
                              'non-engineering roles in this population is not a general requirement of the discipline.',
                              style: AppTypography.caption)),
                    ),
                  EditorialSection(
                    label: 'Issued',
                    aside: Text('${recs.length}', style: AppTypography.metric),
                    wide: true,
                    child: recs.isEmpty
                        ? const EmptyState(
                            icon: Icons.lightbulb_outline,
                            title: 'No recommendations',
                            body: 'No skill met every evidence rule for a recommendation in this analysis.',
                          )
                        : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            for (var i = 0; i < recs.length; i++) _RecommendationCard(index: i + 1, rec: asMap(recs[i])),
                          ]),
                  ),
                  if (withheld.isNotEmpty)
                    EditorialSection(
                      label: 'Withheld for review',
                      aside: Text('${withheld.length}', style: AppTypography.metric),
                      intro: 'Withheld when two coverage measures disagree about the same skill, or when the curriculum '
                          'supplied lacks semesters of the programme. It becomes a decision only after a reviewer '
                          'resolves it.',
                      wide: true,
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        for (final w in withheld) _WithheldRow(w),
                      ]),
                    ),
                  if (notRec.isNotEmpty)
                    EditorialSection(
                      label: 'Not recommended',
                      aside: Text(fmtCount(notRecTotal), style: AppTypography.metric),
                      spacing: 0,
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        for (final e in notRec)
                          Padding(
                            padding: const EdgeInsets.only(bottom: AppSpacing.md),
                            child: Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
                              SizedBox(width: 64, child: Text(fmtCount(e.value), style: AppTypography.metricSmall)),
                              Expanded(child: Text(_reasonText(e.key), style: AppTypography.muted)),
                            ]),
                          ),
                      ]),
                    ),
                ]);
              },
            ),
    );
  }
}

/// Reasons that mean "withheld until a reviewer decides" (the API lists them under withheld_for_review).
const _withheldForReview = {
  'CLASSIFICATION_CONFLICT_REVIEW_REQUIRED',
  'COURSE_TITLE_CONFLICT_REVIEW_REQUIRED',
  'CURRICULUM_SCOPE_REVIEW_REQUIRED',
};

const _reasons = {
  'GAP_INSUFFICIENT_EVIDENCE': 'Not enough evidence to classify the gap',
  'INDUSTRY_SUPPORT_BELOW_THRESHOLD': 'Too few postings to support a curriculum change',
  'ESCO_MAPPING_AMBIGUOUS': 'The skill could not be identified unambiguously in the skills reference',
  'GAP_COVERED': 'Already covered by the curriculum',
  'GAP_NOT_ESTABLISHED': 'No gap once coverage depth and skill identity are checked',
  'COURSE_TITLE_CONFLICT_REVIEW_REQUIRED': 'A course is named after the skill; needs review',
  'CURRICULUM_SCOPE_REVIEW_REQUIRED': 'The curriculum supplied lacks semesters of the programme; needs review',
};

String _reasonText(String code) => _reasons[code] ?? StatusStyle.label(code);

class _RecommendationCard extends StatefulWidget {
  const _RecommendationCard({required this.index, required this.rec});
  final int index;
  final Map<String, dynamic> rec;

  @override
  State<_RecommendationCard> createState() => _RecommendationCardState();
}

/// One decision in the sequence: index, action, skill, why, evidence, affected curriculum, quiet state -- and the
/// complete evidence chain unfolding in place.
class _RecommendationCardState extends State<_RecommendationCard> {
  bool _open = false;


  @override
  Widget build(BuildContext context) {
    final rec = widget.rec;
    final ev = asMap(rec['evidence']);
    final industry = asMap(ev['industry_evidence']);
    final curriculum = asMap(ev['curriculum_evidence']);
    final depth = asList(curriculum['coverage_depth']);
    final target = depth.where((x) => at(x, 'doc_id') == at(ev, 'target_programme.doc_id')).toList();
    final courses = asList(rec['target_course_codes']).map(fmt).toList();
    final reasons = asList(rec['rule_reasons']).map(fmt).toList();
    // the least disruptive intervention the curriculum evidence supports (existing-course-first reasoning); runs
    // produced before it existed show the rule engine's action in "consider" wording
    final reasoned = asMap(rec['reasoning']);
    final why = asList(reasoned['why']).map(fmt).toList();
    final existing = [
      for (final c in [...asList(at(reasoned, 'evidence.courses_teaching_it')),
                       ...asList(at(reasoned, 'evidence.courses_mentioning_it')),
                       ...asList(at(reasoned, 'evidence.institution_courses_teaching_it'))])
        [fmt(at(c, 'course_code')), if (at(c, 'title') != null) fmt(at(c, 'title'))].join(' ')
    ];
    final states = [
      StatusStyle.label(fmt(rec['recommendation_state'])),
      StatusStyle.label(fmt(rec['support_state'])).toLowerCase(),
      StatusStyle.label(fmt(rec['evidence_status'])).toLowerCase(),
    ];
    return InsightItem(
      index: widget.index,
      kicker: StatusStyle.label(fmt(reasoned['action'] ?? rec['action_type'])),
      title: fmt(rec['skill_label']),
      reading: why.isNotEmpty ? why.first : (reasons.isEmpty ? null : reasons.first),
      evidence: [
        if (industry['statement'] != null) MapEntry('Evidence', Plain.sentence(fmt(industry['statement']))),
        if (target.isNotEmpty)
          MapEntry('Curriculum', '${StatusStyle.label(fmt(at(target.first, 'coverage_level'))).toLowerCase()}: '
              '${fmt(at(target.first, 'level_reason'))}'),
        if (existing.isNotEmpty)
          MapEntry('Existing courses', existing.toSet().join('; '))
        else
          MapEntry('Affected', courses.isEmpty ? 'no existing course identified' : courses.join(', ')),
        if (reasoned.isNotEmpty && reasoned['action'] != rec['action_type'])
          MapEntry('Rule engine', '${StatusStyle.label(fmt(rec['action_type']))} (from coverage percentages alone)'),
        MapEntry('State', states.join(', ')),
        for (final u in asList(rec['uncertainty'])) MapEntry('Note', _uncertainty(fmt(u))),
      ],
      action: _open ? 'Hide evidence' : 'View evidence →',
      open: _open,
      onToggle: () => setState(() => _open = !_open),
      openContent: _open ? _evidence(rec, ev, industry, curriculum, depth, reasons, reasoned) : null,
    );
  }

  static String _uncertainty(String u) {
    final i = u.indexOf(':');
    return i < 0 ? StatusStyle.label(u) : u.substring(i + 1).trim();
  }

  Widget _evidence(Map<String, dynamic> rec, Map<String, dynamic> ev, Map<String, dynamic> industry,
      Map<String, dynamic> curriculum, List<dynamic> depth, List<String> reasons, Map<String, dynamic> reasoned) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Evidence chain · ${fmt(rec['skill_label'])}', style: AppTypography.overline),
      const SizedBox(height: AppSpacing.md),
      EvidenceStep(
          label: 'Industry',
          child: Text(
              '${fmt(industry['posting_count'])} of ${fmt(industry['eligible_postings'])} postings '
              '(${fmt(industry['posting_prevalence_pct'])}%), ${fmt(industry['company_count'])} companies, '
              '${StatusStyle.label(fmt(industry['support_state'])).toLowerCase()}',
              style: AppTypography.muted)),
      EvidenceStep(
          label: 'Skills reference',
          child: Text('${fmt(at(ev, 'skill.label'))}, ${StatusStyle.label(fmt(at(ev, 'skill.esco_status'))).toLowerCase()}',
              style: AppTypography.muted)),
      EvidenceStep(
        label: 'Curriculum',
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (depth.isEmpty) Text('No curriculum topic names this skill.', style: AppTypography.muted),
          for (final row in depth)
            for (final t in asList(at(row, 'evidence')).take(3))
              Text('${fmt(at(row, 'doc_id'))} · ${fmt(at(t, 'course_code'))} p.${fmt(at(t, 'page'))}: ${fmt(at(t, 'text'))}',
                  style: AppTypography.muted),
        ]),
      ),
      EvidenceStep(
          label: 'Gap',
          child: Text(
              '${StatusStyle.label(fmt(at(curriculum, 'gap.classification')))}: coverage '
              '${fmt(at(curriculum, 'gap.curriculum_coverage_pct'))}% of ${fmt(at(curriculum, 'gap.curriculum_population'))} courses',
              style: AppTypography.muted)),
      EvidenceStep(
          label: 'Why',
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final r in reasons) Text(r, style: AppTypography.muted),
          ])),
      if (reasoned.isNotEmpty)
        EvidenceStep(
            label: 'Recommended intervention',
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(StatusStyle.label(fmt(reasoned['action'])), style: AppTypography.body),
              for (final w in asList(reasoned['why'])) Text(fmt(w), style: AppTypography.muted),
              for (final a in asList(reasoned['alternatives_considered']))
                Text('Not chosen: ${StatusStyle.label(fmt(at(a, 'action'))).toLowerCase()} — ${fmt(at(a, 'why_not'))}',
                    style: AppTypography.caption),
              for (final l in asList(reasoned['limitations'])) Text('Limitation: ${fmt(l)}', style: AppTypography.caption),
              Text('Existing-course-first reasoning; the institution decides any curriculum change.',
                  style: AppTypography.caption),
            ])),
      if (asList(rec['verification']).isNotEmpty)
        EvidenceStep(
            label: 'How to check it worked',
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              for (final v in asList(rec['verification'])) Text('• ${fmt(v)}', style: AppTypography.muted),
            ])),
      EvidenceStep(
          label: 'Thresholds and sources',
          last: true,
          child: Text('${fmt(ev['thresholds'])}\nsources: ${fmt(ev['source_ids'])}', style: AppTypography.mono)),
    ]);
  }
}

/// A candidate withheld for review: which measures disagree, and what would have been recommended.
class _WithheldRow extends StatelessWidget {
  const _WithheldRow(this.w);
  final Map<String, dynamic> w;

  @override
  Widget build(BuildContext context) {
    final reasons = asList(w['reasons']).map(asMap).toList();
    final gap = asMap(w['gap_v2']);
    final rec = asMap(w['withheld_recommendation']);
    return InsightItem(
      kicker: 'Review',
      title: fmt(w['skill_label']),
      reading: w['statement'] == null ? null : Plain.sentence(fmt(w['statement'])),
      evidence: [
        if (w['posting_count'] != null) MapEntry('Industry', '${fmtCount(w['posting_count'])} postings'),
        if (w['curriculum_courses'] != null) MapEntry('Curriculum', '${fmtCount(w['curriculum_courses'])} courses name it'),
        const MapEntry('State', 'awaiting a reviewer'),
      ],
      footer: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const SizedBox(height: AppSpacing.sm),
        for (final r in reasons)
          Text(Plain.sentence(fmt(r['message'] ?? r['detail'] ?? StatusStyle.label(fmt(r['code'])))), style: AppTypography.caption),
        if (rec.isNotEmpty || gap.isNotEmpty)
          EvidencePanel(title: 'What the two measures say', children: [
            KeyValueList([
              if (rec.isNotEmpty) MapEntry('Withheld action', StatusStyle.label(fmt(rec['action_type']))),
              for (final e in gap.entries)
                if (e.value is! Map && e.value is! List) MapEntry(e.key.replaceAll('_', ' '), e.value),
            ]),
          ]),
      ]),
    );
  }
}
