import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../shell/appearance_panel.dart';
import '../../shell/run_context.dart';
import '../../theme/design_system.dart';
import '../../widgets/ui_kit.dart';
import 'pages.dart';

/// Settings: what this workspace supports and how it is connected. Discipline support comes from
/// GET /api/v1/metadata/discipline-profiles, which computes each discipline's capabilities from the evidence actually
/// present (job-posting populations listed for it, reference and peer curricula of the same discipline). A
/// discipline is never shown as validated unless its profile says so.
class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key, required this.api, required this.navigate});
  final ApiClient api;
  final Navigate navigate;

  @override
  Widget build(BuildContext context) {
    return ApiView(
      api: api,
      path: '/api/v1/metadata/discipline-profiles',
      what: 'the discipline support',
      builder: (context, d, reload) {
        final profiles = asList(d['profiles']).map(asMap).toList();
        return PageFrame(children: [
          const PageHeader(
            eyebrow: 'Workspace',
            title: 'Settings',
            subtitle: 'Which disciplines this workspace can analyse, and with what evidence. Support follows the '
                'evidence that has been supplied; nothing is assumed.',
          ),
          EditorialSection(
            label: 'Discipline support',
            intro: 'Every curriculum is analysed on its own. Industry demand, reference mapping and comparisons are '
                'added only when evidence of the same discipline exists, and never borrowed from another discipline.',
            wide: true,
            child: profiles.isEmpty
                ? Text('No discipline profiles are configured.', style: AppTypography.muted)
                : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    for (final p in profiles) DisciplineSupport(profile: p),
                  ]),
          ),
          EditorialSection(
            label: 'Appearance',
            intro: 'Two designs show the same pages: Version 1, a research report, and Version 2, an atelier in ink, ivory and coral. Each has '
                'a dark and a light mode.',
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              KeyValueList([
                MapEntry('In use', '${Design.label(Design.current.version)}, ${Design.current.isDark ? 'dark' : 'light'} mode'),
                MapEntry('Final design',
                    Design.current.finalised == null ? 'Not finalised yet' : Design.label(Design.current.finalised!)),
              ], labelWidth: 230),
              const SizedBox(height: AppSpacing.md),
              OutlinedButton.icon(
                onPressed: () => showAppearancePanel(context, api),
                icon: const Icon(Icons.palette_outlined, size: 16),
                label: const Text('Open the appearance panel'),
              ),
            ]),
          ),
          EditorialSection(
            label: 'This session',
            child: _Session(api: api),
          ),
        ]);
      },
    );
  }
}

/// One discipline: what the analysis can do for it, in words, and how far it has been validated.
class DisciplineSupport extends StatelessWidget {
  const DisciplineSupport({super.key, required this.profile});
  final Map<String, dynamic> profile;

  static const capabilityNames = {
    'curriculum_analysis': 'Curriculum analysis',
    'industry_analysis': 'Industry demand and skill gaps',
    'reference_mapping': 'Reference curriculum mapping',
    'peer_comparison': 'Peer comparison',
  };

  /// A capability state in words, with the evidence behind it.
  static String describe(String key, String state, Map<String, dynamic> evidence) {
    switch (state) {
      case 'AVAILABLE':
        if (key == 'industry_analysis') {
          final n = evidence['industry_sources'];
          return 'Available (${fmtCount(n)} job-posting ${n == 1 ? 'source' : 'sources'})';
        }
        if (key == 'reference_mapping') {
          final n = asList(evidence['reference_curricula']).length;
          return 'Available ($n reference ${n == 1 ? 'curriculum' : 'curricula'})';
        }
        if (key == 'peer_comparison') {
          final n = asList(evidence['peer_curricula']).length;
          return 'Available ($n peer ${n == 1 ? 'curriculum' : 'curricula'})';
        }
        return 'Available';
      case 'NO_RELEVANT_EVIDENCE':
        return 'Not available: no job postings relevant to this discipline have been supplied';
      case 'NO_REFERENCE_CURRICULUM':
        return 'Not available: no reference curriculum of this discipline has been supplied';
      case 'NO_PEER_CURRICULUM':
        return 'Not available: no peer curriculum of this discipline has been supplied';
      default:
        return StatusStyle.label(state);
    }
  }

  @override
  Widget build(BuildContext context) {
    final caps = asMap(profile['capabilities']);
    final evidence = asMap(profile['evidence']);
    final areas = asList(profile['knowledge_areas']).map(fmt).toList();
    final roles = asList(profile['occupation_examples']).map(fmt).toList();
    final validation = fmt(profile['validation']);
    final validated = validation.startsWith('Validated');
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xxl),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: AppSpacing.md, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Text(fmt(profile['name']), style: AppTypography.title),
          if (profile['short'] != null) Text(fmt(profile['short']), style: AppTypography.caption),
          Text(validated ? 'Validated with real data' : 'Not yet validated',
              style: AppTypography.caption.copyWith(color: validated ? AppColors.success : AppColors.warning)),
        ]),
        const SizedBox(height: AppSpacing.xs),
        ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: AppLayout.measure),
          child: Text(validation, style: AppTypography.muted),
        ),
        const SizedBox(height: AppSpacing.sm),
        KeyValueList([
          for (final e in capabilityNames.entries)
            if (caps[e.key] != null) MapEntry(e.value, describe(e.key, fmt(caps[e.key]), evidence)),
        ], labelWidth: 230),
        if (areas.isNotEmpty || roles.isNotEmpty)
          EvidenceDisclosure(
            title: 'What the discipline covers',
            summary: 'For orientation only: these describe the discipline and are not evidence of industry demand',
            children: [
              if (areas.isNotEmpty) Text('Knowledge areas: ${areas.join(', ')}', style: AppTypography.muted),
              if (roles.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: AppSpacing.xs),
                  child: Text('Example occupations: ${roles.join(', ')}', style: AppTypography.muted),
                ),
            ],
          ),
      ]),
    );
  }
}

class _Session extends StatelessWidget {
  const _Session({required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    final run = RunScope.of(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      KeyValueList([
        MapEntry('Analysis service', api.baseUrl),
        MapEntry('Results in view', run == null || run.status == 'LATEST' ? 'The published analysis' : 'An analysis started here'),
      ], labelWidth: 230),
      if (run != null) ...[
        const SizedBox(height: AppSpacing.md),
        OutlinedButton(
          onPressed: run.draft.isEmpty
              ? null
              : () async {
                  final ok = await showDialog<bool>(
                    context: context,
                    builder: (c) => AlertDialog(
                      title: const Text('Clear the New analysis form?'),
                      content: const Text('The chosen file, the details typed and the analysis options are removed.'),
                      actions: [
                        TextButton(onPressed: () => Navigator.of(c).pop(false), child: const Text('Keep')),
                        FilledButton(onPressed: () => Navigator.of(c).pop(true), child: const Text('Clear form')),
                      ],
                    ),
                  );
                  if (ok == true) {
                    run.draft.clear();
                    if (context.mounted) {
                      ScaffoldMessenger.maybeOf(context)
                          ?.showSnackBar(const SnackBar(content: Text('The New analysis form was cleared.')));
                    }
                  }
                },
          child: const Text('Clear the New analysis form'),
        ),
      ],
    ]);
  }
}
