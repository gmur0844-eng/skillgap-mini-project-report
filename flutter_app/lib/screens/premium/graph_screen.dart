import 'dart:async';

import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../theme/design_system.dart';
import '../../widgets/ui_kit.dart';
import 'pages.dart';

/// Knowledge graph explorer. Only real edges of the run's graph are shown (GET /api/v1/semantic/evidence): pick a
/// node through search, filter by relationship, and click a neighbour to recentre. Nothing is drawn when no node is
/// selected -- there is no decorative or invented graph.
class GraphScreen extends StatelessWidget {
  const GraphScreen({super.key, required this.api, this.initialNode});
  final ApiClient api;
  final String? initialNode;

  @override
  Widget build(BuildContext context) {
    return TabbedPage(
      labels: const ['Explorer', 'Graph table'],
      builder: (context, i) => i == 1 ? specView(api, 'Knowledge Graph') : _Explorer(api: api, initialNode: initialNode),
    );
  }
}

class _Explorer extends StatefulWidget {
  const _Explorer({required this.api, this.initialNode});
  final ApiClient api;
  final String? initialNode;

  @override
  State<_Explorer> createState() => _ExplorerState();
}

class _ExplorerState extends State<_Explorer> {
  final _query = TextEditingController();
  Timer? _debounce;
  List<dynamic> _hits = const [];
  String? _searchError;
  String? _node;
  String? _nodeLabel;
  final List<String> _trail = [];
  String? _relationship;

  @override
  void initState() {
    super.initState();
    _node = widget.initialNode;
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _query.dispose();
    super.dispose();
  }

  void _onQuery(String q) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () async {
      if (q.trim().length < 2) {
        if (mounted) setState(() => _hits = const []);
        return;
      }
      try {
        final d = asMap(await widget.api.getJson('/api/v1/search', query: {'q': q, 'types': 'CONCEPT,COURSE,TOPIC', 'limit': '12'}));
        if (mounted) {
          setState(() {
            _hits = asList(d['items']);
            _searchError = null;
          });
        }
      } catch (e) {
        if (mounted) setState(() => _searchError = 'Search is unavailable');
      }
    });
  }

  void _open(String id, String? label) {
    setState(() {
      if (_node != null && _node != id) _trail.add(_node!);
      _node = id;
      _nodeLabel = label;
      _relationship = null;
      _hits = const [];
    });
  }

  @override
  Widget build(BuildContext context) {
    return PageFrame(children: [
      const PageHeader(
        title: 'Knowledge graph',
        subtitle: 'Courses, topics, concepts, standardised skills and job postings, connected by links that were '
            'extracted or suggested. Each link carries its method and evidence status.',
      ),
      TextField(
        controller: _query,
        onChanged: _onQuery,
        decoration: const InputDecoration(
          prefixIcon: Icon(Icons.search),
          hintText: 'Find a concept, course or topic…',
        ),
      ),
      if (_searchError != null)
        Padding(
          padding: const EdgeInsets.only(top: AppSpacing.sm),
          child: Text(_searchError!, style: AppTypography.muted),
        ),
      if (_hits.isNotEmpty)
        Card(
          margin: const EdgeInsets.only(top: AppSpacing.sm),
          child: Column(children: [
            for (final h in _hits)
              ListTile(
                dense: true,
                leading: StatusBadge(fmt(at(h, 'type')), dense: true),
                title: Text(fmt(at(h, 'label')), maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Text(fmt(at(h, 'subtitle')), maxLines: 1, overflow: TextOverflow.ellipsis),
                onTap: () => _open(fmt(at(h, 'id')), fmt(at(h, 'label'))),
              ),
          ]),
        ),
      const SizedBox(height: AppSpacing.lg),
      if (_node == null)
        const EmptyState(
          icon: Icons.device_hub,
          title: 'Select a node',
          body: 'Search for a concept, course or topic to see its connections in this analysis.',
        )
      else
        ApiView(
          key: ValueKey('graph:$_node'),
          api: widget.api,
          path: '/api/v1/semantic/evidence',
          query: {'node_id': _node!},
          what: 'the connections',
          builder: (context, d, reload) => _neighbourhood(d),
        ),
    ]);
  }

  Widget _neighbourhood(Map<String, dynamic> d) {
    final nodes = asMap(d['nodes']);
    final edges = asList(d['edges']);
    final rels = <String, int>{};
    for (final e in edges) {
      final r = fmt(at(e, 'relationship'));
      rels[r] = (rels[r] ?? 0) + 1;
    }
    final shown = edges.where((e) => _relationship == null || at(e, 'relationship') == _relationship).toList();
    final self = asMap(nodes[_node]);
    final title = fmt(self['label'] ?? _nodeLabel ?? _node);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SectionCard(
        title: title,
        subtitle: '${fmt(self['node_type'])} · $_node · ${edges.length} edge(s)',
        trailing: _trail.isEmpty
            ? null
            : TextButton.icon(
                onPressed: () => setState(() {
                  _node = _trail.removeLast();
                  _nodeLabel = null;
                  _relationship = null;
                }),
                icon: const Icon(Icons.arrow_back),
                label: const Text('Back'),
              ),
        child: edges.isEmpty
            ? Text('This item has no connections in this analysis.', style: AppTypography.muted)
            : Wrap(spacing: AppSpacing.sm, runSpacing: AppSpacing.sm, children: [
                ChoiceChip(
                  label: Text('All (${edges.length})'),
                  selected: _relationship == null,
                  onSelected: (_) => setState(() => _relationship = null),
                ),
                for (final r in rels.entries)
                  ChoiceChip(
                    label: Text('${r.key} (${r.value})'),
                    selected: _relationship == r.key,
                    onSelected: (_) => setState(() => _relationship = r.key),
                  ),
              ]),
      ),
      for (final e in shown.take(200)) _edge(asMap(e), nodes),
      if (shown.length > 200)
        Text('Showing 200 of ${shown.length} edges; filter by relationship to narrow.', style: AppTypography.caption),
    ]);
  }

  /// The graph keeps three different mapping problems apart; each edge says which one it belongs to.
  static const _kinds = {
    'DOCUMENT_STRUCTURE': 'document structure',
    'TOPIC_HIERARCHY': 'topic hierarchy',
    'TOPIC_TO_CONCEPT': 'topic → concept',
    'CURRICULUM_TO_REFERENCE': 'curriculum → reference curriculum',
    'PREREQUISITE': 'prerequisite',
    'SKILL_TO_TAXONOMY': 'industry skill → standardised skill',
    'INDUSTRY_DEMAND': 'industry demand',
    'CURRICULUM_SKILL_MENTION': 'curriculum mentions skill',
    'OCCUPATION': 'occupation',
    'TAXONOMY_HIERARCHY': 'skills reference hierarchy',
    'SEMANTIC_DECISION': 'AI interpretation (advisory)',
  };

  static String _kind(String k) => _kinds[k] ?? k.toLowerCase().replaceAll('_', ' ');

  Widget _edge(Map<String, dynamic> e, Map<String, dynamic> nodes) {
    final outgoing = e['source'] == _node;
    final other = fmt(outgoing ? e['target'] : e['source']);
    final info = asMap(nodes[other]);
    final label = info['label'] == null ? other : fmt(info['label']);
    final evidence = asMap(e['evidence']);
    return Container(
      decoration: BoxDecoration(border: Border(top: BorderSide(color: AppColors.borderSubtle))),
      child: ListTile(
        contentPadding: EdgeInsets.zero,
        leading: Icon(outgoing ? Icons.arrow_forward : Icons.arrow_back, color: AppColors.textMuted,
            semanticLabel: outgoing ? 'outgoing' : 'incoming'),
        title: Text('${StatusStyle.label(fmt(e['relationship']))} · $label', maxLines: 2, overflow: TextOverflow.ellipsis),
        subtitle: Text(
          [
            fmt(info['node_type'] ?? other.split(':').first),
            if (e['mapping_kind'] != null) _kind(fmt(e['mapping_kind'])),
            StatusStyle.method(fmt(e['method'])),
            if (evidence.isNotEmpty) evidence.entries.map((x) => '${x.key} ${fmt(x.value)}').join(', '),
          ].join(' · '),
          style: AppTypography.caption,
        ),
        trailing: StatusBadge(fmt(e['evidence_status']), dense: true),
        onTap: () => _open(other, info['label'] == null ? null : fmt(info['label'])),
      ),
    );
  }
}
