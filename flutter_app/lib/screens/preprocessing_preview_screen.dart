import 'package:flutter/material.dart';

import '../theme/design_system.dart';
import '../services/api_client.dart';

/// Demonstrates RAW -> CLEAN -> STRUCTURED for a real, selected job posting,
/// reading everything from the backend. This is the screen meant for showing
/// preprocessing "live" during a demo, per the project's explicit requirement.
class PreprocessingPreviewScreen extends StatefulWidget {
  const PreprocessingPreviewScreen({super.key, required this.apiClient, this.embedded = false});
  final ApiClient apiClient;
  final bool embedded; // inside the app shell: the shell/page header carries the title

  @override
  State<PreprocessingPreviewScreen> createState() => _PreprocessingPreviewScreenState();
}

class _PreprocessingPreviewScreenState extends State<PreprocessingPreviewScreen> {
  late Future<Map<String, dynamic>> _jobsFuture;
  int? _selectedJobId;
  Map<String, dynamic>? _preview;
  String? _error;
  bool _loadingPreview = false;

  @override
  void initState() {
    super.initState();
    _jobsFuture = widget.apiClient.getJobs(limit: 100);
  }

  Future<void> _loadPreview(int jobId) async {
    setState(() {
      _selectedJobId = jobId;
      _loadingPreview = true;
      _error = null;
      _preview = null;
    });
    try {
      final preview = await widget.apiClient.getJobPreview(jobId);
      setState(() => _preview = preview);
    } catch (e) {
      setState(() => _error = '$e');
    } finally {
      setState(() => _loadingPreview = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: widget.embedded ? null : AppBar(title: const Text('Preprocessing Preview')),
      body: Row(
        children: [
          SizedBox(
            width: 280,
            child: FutureBuilder<Map<String, dynamic>>(
              future: _jobsFuture,
              builder: (context, snapshot) {
                if (snapshot.connectionState == ConnectionState.waiting) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snapshot.hasError) {
                  return Center(child: Text('${snapshot.error}'));
                }
                final items = (snapshot.data!['items'] as List<dynamic>);
                if (items.isEmpty) {
                  return const Padding(
                    padding: EdgeInsets.all(16),
                    child: Text('No job postings have been added yet. Add them under New analysis.'),
                  );
                }
                return ListView.builder(
                  itemCount: items.length,
                  itemBuilder: (context, i) {
                    final job = items[i] as Map<String, dynamic>;
                    final selected = job['id'] == _selectedJobId;
                    return ListTile(
                      selected: selected,
                      title: Text(job['job_title'] ?? '(no title)', maxLines: 1, overflow: TextOverflow.ellipsis),
                      subtitle: Text(job['company_name'] ?? ''),
                      trailing: job['is_duplicate'] == true ? const Icon(Icons.content_copy, size: 16) : null,
                      onTap: () => _loadPreview(job['id']),
                    );
                  },
                );
              },
            ),
          ),
          const VerticalDivider(width: 1),
          Expanded(
            child: _loadingPreview
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                    ? Center(child: Text(_error!))
                    : _preview == null
                        ? const Center(child: Text('Select a job posting on the left.'))
                        : _buildPreview(_preview!),
          ),
        ],
      ),
    );
  }

  Widget _buildPreview(Map<String, dynamic> preview) {
    final structured = preview['structured_record'] as Map<String, dynamic>;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _stageCard('Original text', preview['raw_text'] ?? '', AppColors.surface),
        const Icon(Icons.arrow_downward),
        _stageCard('CLEANED TEXT', preview['clean_text'] ?? '', AppColors.surface),
        const Icon(Icons.arrow_downward),
        Card(
          color: AppColors.surface,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Structured posting', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                ...structured.entries.map((e) => Text('${e.key}: ${e.value}')),
              ],
            ),
          ),
        ),
        const SizedBox(height: 8),
        if (preview['extracted_skills'] == null)
          Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text(
              'Skill extraction has not been run for this posting yet.',
              style: TextStyle(color: AppColors.textMuted, fontStyle: FontStyle.italic),
            ),
          )
        else
          Card(
            color: AppColors.surface,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('EXTRACTED SKILLS', style: TextStyle(fontWeight: FontWeight.bold)),
                  const SizedBox(height: 8),
                  ...(preview['extracted_skills'] as List<dynamic>).map((s) {
                    final m = s as Map<String, dynamic>;
                    final mapped = m['mapping_status'] == 'mapped';
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Row(
                        children: [
                          Icon(mapped ? Icons.check_circle : Icons.help_outline,
                              size: 16, color: mapped ? AppColors.success : AppColors.warning),
                          const SizedBox(width: 6),
                          Expanded(
                            child: Text(
                              '${m['original_text']}  (${m['extraction_method']}, '
                              '${mapped ? "mapped" : "unmapped"})',
                            ),
                          ),
                        ],
                      ),
                    );
                  }),
                ],
              ),
            ),
          ),
      ],
    );
  }

  Widget _stageCard(String label, String text, Color color) {
    return Card(
      color: color,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: const TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Text(text),
          ],
        ),
      ),
    );
  }
}
