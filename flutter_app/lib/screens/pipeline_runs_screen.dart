import 'package:flutter/material.dart';

import '../theme/design_system.dart';
import '../services/api_client.dart';

class PipelineRunsScreen extends StatefulWidget {
  const PipelineRunsScreen({super.key, required this.apiClient, this.embedded = false});
  final ApiClient apiClient;
  final bool embedded; // inside the app shell: the page header carries the title

  @override
  State<PipelineRunsScreen> createState() => _PipelineRunsScreenState();
}

class _PipelineRunsScreenState extends State<PipelineRunsScreen> {
  late Future<List<dynamic>> _future;

  @override
  void initState() {
    super.initState();
    _future = widget.apiClient.getPipelineRuns();
  }

  void _refresh() => setState(() => _future = widget.apiClient.getPipelineRuns());

  Color _statusColor(String status) {
    switch (status) {
      case 'succeeded':
        return AppColors.success;
      case 'failed':
        return AppColors.danger;
      case 'running':
        return AppColors.info;
      default:
        return AppColors.neutral;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: widget.embedded
          ? null
          : AppBar(
              title: const Text('Pipeline Run Status'),
              actions: [IconButton(icon: const Icon(Icons.refresh), onPressed: _refresh)],
            ),
      body: FutureBuilder<List<dynamic>>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text('${snapshot.error}'));
          }
          final runs = snapshot.data!;
          if (runs.isEmpty) {
            return const Center(
              child: Text('No imports yet. Start one under New analysis.'),
            );
          }
          return ListView.separated(
            itemCount: runs.length,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (context, i) {
              final r = runs[i] as Map<String, dynamic>;
              return ListTile(
                leading: CircleAvatar(
                  backgroundColor: _statusColor(r['status'] ?? ''),
                  child: Text('${r['id']}', style: const TextStyle(color: Colors.white, fontSize: 12)),
                ),
                title: Text('${r['dataset_name'] ?? 'unknown'} — ${r['status']}'),
                subtitle: Text(
                  'processed: ${r['records_processed'] ?? '-'}  failed: ${r['records_failed'] ?? '-'}  '
                  'started: ${r['started_at'] ?? '-'}',
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => PipelineRunDetailScreen(apiClient: widget.apiClient, runId: r['id']),
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}

class PipelineRunDetailScreen extends StatefulWidget {
  const PipelineRunDetailScreen({super.key, required this.apiClient, required this.runId});
  final ApiClient apiClient;
  final int runId;

  @override
  State<PipelineRunDetailScreen> createState() => _PipelineRunDetailScreenState();
}

class _PipelineRunDetailScreenState extends State<PipelineRunDetailScreen> {
  late Future<Map<String, dynamic>> _future;

  @override
  void initState() {
    super.initState();
    _future = widget.apiClient.getPipelineRunDetail(widget.runId);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Run #${widget.runId}')),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text('${snapshot.error}'));
          }
          final run = snapshot.data!;
          final rejections = (run['rejections'] as List<dynamic>? ?? []);
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text('Status: ${run['status']}', style: Theme.of(context).textTheme.titleMedium),
              Text('Dataset: ${run['dataset_name']}'),
              Text('Processed: ${run['records_processed']}   Failed: ${run['records_failed']}'),
              if (run['error_log'] != null) ...[
                const SizedBox(height: 8),
                Text('Error: ${run['error_log']}', style: TextStyle(color: AppColors.danger)),
              ],
              const SizedBox(height: 16),
              Text('Rejected records (why they were removed)', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              if (rejections.isEmpty) const Text('No rejections recorded for this run.'),
              ...rejections.map((r) {
                final m = r as Map<String, dynamic>;
                return Card(
                  child: ListTile(
                    title: Text('Reason: ${m['reason']}'),
                    subtitle: Text('${m['detail'] ?? ''}\n${m['raw_snippet'] ?? ''}'),
                    isThreeLine: true,
                  ),
                );
              }),
            ],
          );
        },
      ),
    );
  }
}
