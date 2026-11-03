import 'package:flutter/material.dart';
import '../services/api_client.dart';

class DataSourcesScreen extends StatefulWidget {
  const DataSourcesScreen({super.key, required this.apiClient, this.embedded = false});
  final ApiClient apiClient;
  final bool embedded; // inside the app shell: the shell/page header carries the title

  @override
  State<DataSourcesScreen> createState() => _DataSourcesScreenState();
}

class _DataSourcesScreenState extends State<DataSourcesScreen> {
  late Future<List<dynamic>> _future;

  @override
  void initState() {
    super.initState();
    _future = widget.apiClient.getDataSources();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: widget.embedded ? null : AppBar(title: const Text('Data Sources')),
      body: FutureBuilder<List<dynamic>>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text('${snapshot.error}'));
          }
          final sources = snapshot.data!;
          if (sources.isEmpty) {
            return const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'No data sources registered yet.\n\n'
                  'Run the ingestion scripts in scripts/ingestion/ against real '
                  'ESCO / O*NET / job-posting data to populate this view.',
                  textAlign: TextAlign.center,
                ),
              ),
            );
          }
          return ListView.separated(
            itemCount: sources.length,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (context, i) {
              final s = sources[i] as Map<String, dynamic>;
              return ListTile(
                title: Text(s['source_name'] ?? 'Unknown source'),
                subtitle: Text(
                  '${s['source_type'] ?? ''} · version ${s['version'] ?? '-'} · '
                  'retrieved ${s['retrieval_date'] ?? '-'}',
                ),
                trailing: s['license'] != null ? Chip(label: Text(s['license'])) : null,
              );
            },
          );
        },
      ),
    );
  }
}
