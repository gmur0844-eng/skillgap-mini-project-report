import 'package:flutter/material.dart';

import '../theme/design_system.dart';
import '../services/api_client.dart';

class DataQualityScreen extends StatefulWidget {
  const DataQualityScreen({super.key, required this.apiClient, this.embedded = false});
  final ApiClient apiClient;
  final bool embedded; // inside the app shell: the shell/page header carries the title

  @override
  State<DataQualityScreen> createState() => _DataQualityScreenState();
}

class _DataQualityScreenState extends State<DataQualityScreen> {
  late Future<Map<String, dynamic>> _future;

  @override
  void initState() {
    super.initState();
    _future = widget.apiClient.getDataQuality();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: widget.embedded ? null : AppBar(title: const Text('Data Quality')),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  'Could not reach the backend at the configured URL.\n\n'
                  '${snapshot.error}\n\n'
                  'Make sure the FastAPI server is running (see backend/README '
                  'instructions) before expecting real data here.',
                  textAlign: TextAlign.center,
                ),
              ),
            );
          }

          final data = snapshot.data!;
          final reliable = data['reliable_for_analysis'] == true;
          final jobPostings = data['job_postings'] as Map<String, dynamic>;
          final curriculum = data['curriculum'] as Map<String, dynamic>;

          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (!reliable)
                Card(
                  color: AppColors.surfaceRaised,
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text(
                      data['note'] ?? 'Insufficient data loaded for reliable analysis.',
                    ),
                  ),
                ),
              const SizedBox(height: 12),
              _MetricCard(
                title: 'Job Postings',
                rows: {
                  'Total': '${jobPostings['total']}',
                  'Missing clean description': '${jobPostings['missing_clean_description']} '
                      '(${jobPostings['missing_pct'] ?? '-'}%)',
                  'Duplicates flagged': '${jobPostings['duplicate_count']} '
                      '(${jobPostings['duplicate_pct'] ?? '-'}%)',
                },
              ),
              const SizedBox(height: 12),
              _MetricCard(
                title: 'Curriculum Data',
                rows: {
                  'Institutions': '${curriculum['institutions']}',
                  'Programmes': '${curriculum['programmes']}',
                  'Courses': '${curriculum['courses']}',
                },
              ),
            ],
          );
        },
      ),
    );
  }
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({required this.title, required this.rows});
  final String title;
  final Map<String, String> rows;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            ...rows.entries.map(
              (e) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [Text(e.key), Text(e.value)],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
