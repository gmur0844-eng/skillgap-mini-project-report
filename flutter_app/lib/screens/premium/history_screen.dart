import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../shell/navigation.dart';
import '../../shell/run_context.dart';
import '../../theme/design_system.dart';
import '../../theme/plain_language.dart';
import '../../widgets/ui_kit.dart';
import 'pages.dart';

/// History: every analysis started in this workspace, newest first, from GET /api/v1/analysis/jobs (the persisted job
/// records). A ready analysis can be opened (every page is then scoped to its run); a failed one, or one that needs
/// review, shows its reason and can be run again. The published analysis is always one step away. Nothing here is
/// computed: status, times, options and reasons are the job records' own.
class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key, required this.api, required this.navigate});
  final ApiClient api;
  final Navigate navigate;

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

enum HistoryFilter { all, ready, attention, running }

class _HistoryScreenState extends State<HistoryScreen> {
  HistoryFilter _filter = HistoryFilter.all;

  static const _filterLabels = {
    HistoryFilter.all: 'All',
    HistoryFilter.ready: 'Ready',
    HistoryFilter.attention: 'Needs attention',
    HistoryFilter.running: 'Running',
  };

  bool _matches(Map<String, dynamic> j) {
    final s = fmt(j['status']);
    return switch (_filter) {
      HistoryFilter.all => true,
      HistoryFilter.ready => s == 'ANALYSIS_READY',
      HistoryFilter.attention => s == 'ANALYSIS_FAILED' || s == 'NEEDS_REVIEW',
      HistoryFilter.running => s == 'ANALYSIS_PENDING',
    };
  }

  @override
  Widget build(BuildContext context) {
    final run = RunScope.of(context);
    return ApiView(
      api: widget.api,
      path: '/api/v1/analysis/jobs',
      query: const {'limit': '100'},
      what: 'the analysis history',
      builder: (context, d, reload) {
        final jobs = asList(d['items']).map(asMap).toList();
        final shown = jobs.where(_matches).toList();
        return PageFrame(children: [
          PageHeader(
            eyebrow: 'Workspace',
            title: 'History',
            subtitle: 'Every analysis started here, newest first. Open a ready one to see its results; the published '
                'analysis stays available.',
            trailing: FilledButton.icon(
              onPressed: () => widget.navigate(Dest.ingestion),
              icon: const Icon(Icons.add, size: 16),
              label: const Text('New analysis'),
            ),
          ),
          _published(run),
          const SizedBox(height: AppSpacing.xl),
          if (jobs.isEmpty)
            EmptyState(
              title: 'No analyses have been started yet',
              body: 'Upload a curriculum under New analysis. It is analysed on its own; comparisons are added only '
                  'when you choose them.',
              action: OutlinedButton(onPressed: () => widget.navigate(Dest.ingestion), child: const Text('Start an analysis')),
            )
          else ...[
            Wrap(spacing: AppSpacing.md, runSpacing: AppSpacing.sm, crossAxisAlignment: WrapCrossAlignment.center, children: [
              Semantics(
                label: 'Filter analyses by status',
                child: SegmentTabs(
                  labels: [for (final f in HistoryFilter.values) _filterLabels[f]!],
                  selected: _filter.index,
                  onSelect: (i) => setState(() => _filter = HistoryFilter.values[i]),
                ),
              ),
              Text('${shown.length} of ${jobs.length} shown', style: AppTypography.caption),
              TextButton.icon(onPressed: reload, icon: const Icon(Icons.refresh, size: 16), label: const Text('Refresh')),
            ]),
            const SizedBox(height: AppSpacing.lg),
            if (shown.isEmpty)
              Text('No analysis matches this filter.', style: AppTypography.muted)
            else
              for (final j in shown) HistoryItem(job: j, run: run, navigate: widget.navigate, onChanged: reload),
          ],
        ]);
      },
    );
  }

  Widget _published(AnalysisContext? run) {
    final current = run == null || run.status == 'LATEST';
    return Row(children: [
      Icon(Icons.public, size: 16, color: AppColors.textFaint),
      const SizedBox(width: AppSpacing.sm),
      Expanded(
        child: Text(
            current
                ? 'You are viewing the published analysis.'
                : 'You are viewing an analysis started here. The published analysis is unchanged.',
            style: AppTypography.muted),
      ),
      if (!current) TextButton(onPressed: run.showLatest, child: const Text('Show the published analysis')),
    ]);
  }
}

/// One analysis: what was analysed, its state in words, when, what it included, and what can be done next.
class HistoryItem extends StatelessWidget {
  const HistoryItem({super.key, required this.job, required this.run, required this.navigate, this.onChanged, this.compact = false});
  final Map<String, dynamic> job;
  final AnalysisContext? run;
  final Navigate navigate;
  final VoidCallback? onChanged;
  final bool compact;

  static String title(Map<String, dynamic> job) {
    final doc = asMap(job['document']);
    final parts = [
      for (final k in ['institution', 'programme', 'curriculum_version'])
        if (doc[k] != null && fmt(doc[k]).trim().isNotEmpty && fmt(doc[k]) != '—') fmt(doc[k]),
    ];
    return parts.isEmpty ? fmt(doc['file_name'] ?? 'Uploaded curriculum') : parts.join(' · ');
  }

  static String when(dynamic iso) {
    final t = DateTime.tryParse(fmt(iso));
    if (t == null) return 'time not recorded';
    final u = t.toUtc();
    String two(int v) => v.toString().padLeft(2, '0');
    return '${u.year}-${two(u.month)}-${two(u.day)} ${two(u.hour)}:${two(u.minute)} UTC';
  }

  static String? took(Map<String, dynamic> job) {
    final a = DateTime.tryParse(fmt(job['created_at']));
    final b = DateTime.tryParse(fmt(job['finished_at']));
    if (a == null || b == null) return null;
    final s = b.difference(a).inSeconds;
    if (s < 0) return null;
    return s < 90 ? 'took $s s' : 'took ${(s / 60).round()} min';
  }

  /// The options in words: what the analysis included, as recorded with the job.
  static String scope(Map<String, dynamic> job) {
    final o = asMap(job['options']);
    final peers = asList(o['peer_ids']).map(fmt).toList();
    final parts = <String>[
      o['industry'] == false ? 'curriculum only (no industry evidence)' : 'with industry evidence',
      if (o['peers'] == false) 'no peer comparison'
      else if (peers.isNotEmpty) 'compared with ${peers.length == 1 ? '1 chosen peer' : '${peers.length} chosen peers'}'
      else 'compared with the supplied peers',
    ];
    return parts.join(', ');
  }

  @override
  Widget build(BuildContext context) {
    final status = fmt(job['status']);
    final profile = asMap(job['discipline_profile']);
    final discipline = profile['name'] ?? asMap(job['document'])['discipline'];
    final reason = job['reason'];
    final viewing = run?.status == 'ANALYSIS_READY' && run?.runId != null && run?.runId == job['run_id']?.toString();
    return Semantics(
      container: true,
      label: 'analysis ${title(job)}, ${StatusStyle.label(status)}',
      child: Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.xl),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Wrap(spacing: AppSpacing.md, runSpacing: AppSpacing.xs, crossAxisAlignment: WrapCrossAlignment.center, children: [
            Text(title(job), style: compact ? AppTypography.body.copyWith(color: AppColors.text) : AppTypography.title),
            StatusBadge(status, dense: true),
            if (viewing) Text('(in view)', style: AppTypography.caption.copyWith(color: AppColors.primary)),
          ]),
          const SizedBox(height: AppSpacing.xs),
          Text(
              [
                'Started ${when(job['created_at'])}',
                if (took(job) != null) took(job)!,
                if (discipline != null && fmt(discipline).trim().isNotEmpty) fmt(discipline),
                if (!compact) scope(job),
              ].join('   '),
              style: AppTypography.caption),
          if (reason != null && status != 'ANALYSIS_READY')
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.xs),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: AppLayout.measure),
                child: Text(Plain.sentence(fmt(reason)), style: AppTypography.muted),
              ),
            ),
          if (run != null)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.xs),
              child: Wrap(spacing: AppSpacing.sm, children: [
                if (status == 'ANALYSIS_READY' && job['run_id'] != null && !viewing)
                  OutlinedButton(
                    onPressed: () {
                      if (run!.openJob(job)) navigate(Dest.overview);
                    },
                    child: const Text('Open results'),
                  ),
                if (status == 'ANALYSIS_FAILED' || status == 'NEEDS_REVIEW')
                  OutlinedButton.icon(
                    onPressed: run!.status == 'ANALYSIS_PENDING'
                        ? null
                        : () async {
                            await run!.retryJob(job);
                            onChanged?.call();
                          },
                    icon: const Icon(Icons.refresh, size: 16),
                    label: const Text('Run again'),
                  ),
                if (status == 'ANALYSIS_PENDING')
                  TextButton(onPressed: () => navigate(Dest.overview), child: const Text('Follow progress')),
                if (status == 'ANALYSIS_READY' && job['run_id'] != null && !compact)
                  TextButton(
                    onPressed: () => showRunComparison(context, run!.api, job['run_id'].toString()),
                    child: const Text('Compare with the published analysis'),
                  ),
              ]),
            ),
        ]),
      ),
    );
  }
}

/// The few most recent analyses (Overview). Quietly says so when the history cannot be read; never invents entries.
class RecentAnalyses extends StatefulWidget {
  const RecentAnalyses({super.key, required this.api, required this.navigate, this.limit = 4});
  final ApiClient api;
  final Navigate navigate;
  final int limit;

  @override
  State<RecentAnalyses> createState() => _RecentAnalysesState();
}

class _RecentAnalysesState extends State<RecentAnalyses> {
  // read once per visit to the page (a rebuild of the briefing does not request it again)
  late final Future<dynamic> _jobs = widget.api.getJson('/api/v1/analysis/jobs', query: {'limit': '${widget.limit}'});

  @override
  Widget build(BuildContext context) {
    final run = RunScope.of(context);
    return FutureBuilder<dynamic>(
      future: _jobs,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const SkeletonBlock(width: 320);
        }
        if (snap.hasError || snap.data is! Map) {
          return Text('The list of recent analyses is unavailable right now.', style: AppTypography.muted);
        }
        final jobs = asList((snap.data as Map)['items']).map(asMap).toList();
        if (jobs.isEmpty) {
          return Text('No analysis has been started here yet. Upload a curriculum under New analysis.',
              style: AppTypography.muted);
        }
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final j in jobs) HistoryItem(job: j, run: run, navigate: widget.navigate, compact: true),
          QuietLink('All analyses →', onTap: () => widget.navigate(Dest.history)),
        ]);
      },
    );
  }
}


/// What differs between an analysis and the published one: curriculum, industry evidence or method
/// (GET /api/v1/analysis/run-comparison). Says what a difference in results can be attributed to.
Future<void> showRunComparison(BuildContext context, ApiClient api, String runId) {
  return showDialog<void>(
    context: context,
    builder: (context) => Dialog(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 640, maxHeight: 640),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: FutureBuilder<dynamic>(
            future: api.getJson('/api/v1/analysis/run-comparison', query: {'a': runId}),
            builder: (context, snap) {
              final close = Align(
                alignment: Alignment.centerRight,
                child: TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Close')),
              );
              if (snap.connectionState == ConnectionState.waiting) {
                return const SizedBox(height: 120, child: Center(child: CircularProgressIndicator()));
              }
              if (snap.hasError || snap.data is! Map) {
                return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('The comparison is unavailable', style: AppTypography.title),
                  const SizedBox(height: AppSpacing.sm),
                  Text('The two analyses could not be read from the analysis service.', style: AppTypography.muted),
                  close,
                ]);
              }
              return RunComparisonView(data: asMap(snap.data), footer: close);
            },
          ),
        ),
      ),
    ),
  );
}

class RunComparisonView extends StatelessWidget {
  const RunComparisonView({super.key, required this.data, this.footer});
  final Map<String, dynamic> data;
  final Widget? footer;

  Widget _row(String label, bool changed, List<String> details) => Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.md),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(label, style: AppTypography.section)),
            Text(changed ? 'Different' : 'Same',
                style: AppTypography.caption.copyWith(color: changed ? AppColors.warning : AppColors.success)),
          ]),
          for (final d in details)
            Padding(padding: const EdgeInsets.only(top: 2), child: Text(d, style: AppTypography.caption)),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final cur = asMap(data['curriculum']);
    final ind = asMap(data['industry_evidence']);
    final method = asMap(data['method']);
    final docs = asList(cur['documents']).map(asMap).where((d) => d['status'] != 'SAME').toList();
    String side(dynamic s) => s == 'REMOVED' ? 'only in this analysis' : 'only in the published analysis';
    return SingleChildScrollView(
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Compared with the published analysis', style: AppTypography.title),
        const SizedBox(height: AppSpacing.lg),
        _row('Curriculum', cur['changed'] == true || cur['comparison_curricula_changed'] == true, [
          for (final d in docs)
            '${StatusStyle.label(fmt(d['role']))}: ${fmt(d['institution'] ?? d['doc_id'])} '
                '${d['curriculum_version'] == null ? '' : fmt(d['curriculum_version'])} (${side(d['status'])})',
        ]),
        _row('Industry evidence', ind['changed'] == true, [
          if (asList(ind['posting_files_added']).isNotEmpty)
            '${asList(ind['posting_files_added']).length} posting file(s) only in the published analysis',
          if (asList(ind['posting_files_removed']).isNotEmpty)
            '${asList(ind['posting_files_removed']).length} posting file(s) only in this analysis',
        ]),
        _row('Method', method['changed'] == true,
            [for (final m in asList(method['differences']).map(asMap)) 'The ${fmt(m['label'])} differs']),
        const SizedBox(height: AppSpacing.sm),
        for (final a in asList(data['attribution']))
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
            child: Text(fmt(a), style: AppTypography.body),
          ),
        if (footer != null) footer!,
      ]),
    );
  }
}
