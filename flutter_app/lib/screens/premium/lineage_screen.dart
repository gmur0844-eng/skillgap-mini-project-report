import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../theme/design_system.dart';
import '../../theme/plain_language.dart';
import '../../widgets/ui_kit.dart';
import 'pages.dart';

/// Data lineage: SOURCE → RAW → BRONZE → SILVER → GOLD → ANALYTICS built from the stages the run actually executed
/// (GET /api/v1/intelligence/lineage), the source documents with their hashes, the run fingerprints, and the
/// recomputation record against the parent run (GET /api/v1/lineage/recompute).
class LineageScreen extends StatelessWidget {
  const LineageScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return TabbedPage(
      labels: const ['Flow', 'Recomputation', 'Lineage table'],
      builder: (context, i) {
        if (i == 2) return specView(api, 'Data Lineage');
        if (i == 1) {
          return ApiView(
            api: api,
            path: '/api/v1/lineage/recompute',
            what: 'the recomputation record',
            builder: (context, d, reload) => _Recompute(record: asMap(d['lineage'])),
          );
        }
        return ApiView(
          api: api,
          path: '/api/v1/intelligence/lineage',
          what: 'the data lineage',
          builder: (context, d, reload) => _Flow(data: d),
        );
      },
    );
  }
}

const _layers = ['SOURCE', 'RAW', 'BRONZE', 'SILVER', 'GOLD', 'ANALYTICS'];

/// The processing layers in words (the layer codes stay internal).
const layerNames = {
  'SOURCE': 'Sources',
  'RAW': 'Original source',
  'BRONZE': 'Processed source',
  'SILVER': 'Prepared evidence',
  'GOLD': 'Analysis results',
  'ANALYTICS': 'Findings',
};

/// Layer of an executed stage, from its own name ("silver.structure" → SILVER, "industry.gold" → GOLD).
String layerOf(String stage) {
  final parts = stage.toLowerCase().split('.');
  for (final p in parts) {
    final up = p.toUpperCase();
    if (up == 'RAW' || up == 'BRONZE' || up == 'SILVER' || up == 'GOLD') return up;
  }
  if (parts.first == 'health') return 'SILVER';
  if (parts.first == 'industry' && parts.length > 1 && (parts[1] == 'esco' || parts[1] == 'extract')) return 'SILVER';
  return 'ANALYTICS';
}

class _Flow extends StatelessWidget {
  const _Flow({required this.data});
  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final sources = asList(data['sources']);
    final stages = asList(data['stages']).map(fmt).toList();
    final byLayer = <String, List<String>>{for (final l in _layers) l: []};
    for (final s in stages) {
      byLayer[layerOf(s)]!.add(s);
    }
    final counts = <String, String>{
      'SOURCE': '${sources.length} source document(s)',
      for (final l in _layers.skip(1)) l: '${byLayer[l]!.length} processing step(s)',
    };
    return PageFrame(children: [
      const PageHeader(title: 'Data lineage', subtitle: 'Every number in this analysis traces back to these sources.'),
      LayoutBuilder(builder: (context, box) {
        final vertical = box.maxWidth < 900;
        final tiles = [
          for (var i = 0; i < _layers.length; i++) ...[
            _LayerTile(name: layerNames[_layers[i]]!, detail: counts[_layers[i]]!),
            if (i < _layers.length - 1)
              Padding(
                padding: const EdgeInsets.all(AppSpacing.xs),
                child: Icon(vertical ? Icons.arrow_downward : Icons.arrow_forward, size: 18, color: AppColors.textFaint),
              ),
          ],
        ];
        return vertical
            ? Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: tiles)
            : Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                for (final t in tiles) t is _LayerTile ? Expanded(child: t) : t,
              ]);
      }),
      EvidencePanel(title: 'Technical details: every processing step', children: [
        for (final l in _layers.skip(1))
          if (byLayer[l]!.isNotEmpty)
            Text('${layerNames[l]}: ${byLayer[l]!.toSet().join(', ')}', style: AppTypography.mono),
      ]),
      const SizedBox(height: AppSpacing.xl),
      SectionCard(
        title: 'Reproducibility',
        subtitle: 'The same method, settings and sources always produce the same results; these fingerprints show it',
        child: KeyValueList([
          for (final k in const ['run_id', 'code_fingerprint', 'config_hash', 'content_digest'])
            MapEntry(Plain.field(k), data[k]),
        ]),
      ),
      SectionCard(
        title: 'Sources',
        subtitle: '${sources.length} document(s) with their role, version and file fingerprint',
        child: sources.isEmpty
            ? Text('This analysis lists no sources.', style: AppTypography.muted)
            : Column(children: [
                for (final s in sources)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: StatusBadge(fmt(at(s, 'role')), dense: true),
                    title: Text('${fmt(at(s, 'institution'))} · ${fmt(at(s, 'programme'))}',
                        maxLines: 2, overflow: TextOverflow.ellipsis),
                    subtitle: Text(
                        '${fmt(at(s, 'curriculum_version'))} · ${fmt(at(s, 'academic_year'))} · '
                        'fingerprint ${_short(fmt(at(s, 'sha256')))}',
                        style: AppTypography.caption),
                  ),
              ]),
      ),
    ]);
  }
}

String _short(String s) => s.length > 16 ? '${s.substring(0, 16)}…' : s;

class _LayerTile extends StatelessWidget {
  const _LayerTile({required this.name, required this.detail});
  final String name;
  final String detail;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(right: AppSpacing.md, bottom: AppSpacing.md),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(name, style: AppTypography.title),
        const SizedBox(height: AppSpacing.xs),
        Text(detail, style: AppTypography.body),
      ]),
    );
  }
}

class _Recompute extends StatelessWidget {
  const _Recompute({required this.record});
  final Map<String, dynamic> record;

  @override
  Widget build(BuildContext context) {
    final changes = asMap(record['source_changes']);
    final planned = asMap(record['planned_recomputation']);
    final outputs = asMap(record['changed_outputs']);
    final counts = asMap(outputs['counts']);
    return PageFrame(children: [
      PageHeader(
        title: 'Recomputation',
        subtitle: 'What changed when this analysis was recomputed from the earlier one, on ${fmt(record['recorded_at'])}',
      ),
      Wrap(spacing: AppSpacing.md, runSpacing: AppSpacing.md, children: [
        KpiCard(value: asList(changes['added']).length, label: 'Sources added', icon: Icons.add_circle_outline),
        KpiCard(value: asList(changes['removed']).length, label: 'Sources removed', icon: Icons.remove_circle_outline),
        KpiCard(value: asList(changes['changed']).length, label: 'Sources changed', icon: Icons.change_circle_outlined),
        KpiCard(
            value: at(record, 'code_fingerprint.changed') == true ? 'yes' : 'no',
            label: 'Method changed',
            caption: '${fmt(at(record, 'code_fingerprint.parent'))} → ${fmt(at(record, 'code_fingerprint.new'))}',
            icon: Icons.code),
      ]),
      const SizedBox(height: AppSpacing.lg),
      SectionCard(
        title: 'Results compared with the earlier analysis',
        subtitle: Plain.sentence(fmt(record['note'])),
        child: DistributionBar(counts: counts, order: const ['unchanged', 'changed', 'added', 'removed']),
      ),
      SectionCard(
        title: 'Affected analyses',
        subtitle: 'Kinds of source that changed: ${asList(planned['source_types']).map((x) => Plain.value(x, fallback: fmt)).join(', ')}',
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final a in asList(planned['affected_analytics'])) Text('• ${Plain.value(a, fallback: fmt)}', style: AppTypography.muted),
        ]),
      ),
      for (final part in const ['added', 'changed', 'removed'])
        if (asList(outputs[part]).isNotEmpty)
          EvidencePanel(
            title: 'Technical details: $part outputs (${asList(outputs[part]).length})',
            children: [
              for (final f in asList(outputs[part])) Text(fmt(f), style: AppTypography.mono),
            ],
          ),
      EvidencePanel(title: 'Technical details: analysis references', children: [
        KeyValueList([
          MapEntry(Plain.field('run_id'), record['new_run']),
          MapEntry(Plain.field('parent_run'), record['parent_run']),
        ]),
      ]),
      if (asList(changes['added']).isNotEmpty)
        EvidencePanel(
          title: 'Added sources',
          children: [
            for (final s in asList(changes['added']))
              Text('${fmt(at(s, 'source'))} · ${fmt(at(s, 'type'))} · ${_short(fmt(at(s, 'sha256')))}',
                  style: AppTypography.mono),
          ],
        ),
    ]);
  }
}
