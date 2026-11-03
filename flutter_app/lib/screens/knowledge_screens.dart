import 'dart:convert';

import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../theme/design_system.dart';
import '../theme/plain_language.dart';
import '../widgets/ui_kit.dart';
import 'screen_specs.dart';

export 'screen_specs.dart';

/// Engine knowledge screens. Every screen reads one real backend endpoint and renders exactly what it returns:
///   * the evidence state (AVAILABLE / NOT_PRODUCED / BLOCKED) and its reason,
///   * the scope (run, documents, job-posting population + representativeness warning),
///   * a summary block (as returned), and the rows of the list under [KnowledgeScreenSpec.listKey].
/// No value is computed, estimated or filled in on the client; the row filter and column sort only reorder or hide
/// rows that the API returned. When the backend is unreachable the screen says so; an empty list is shown as empty.
class KnowledgeScreen extends StatefulWidget {
  const KnowledgeScreen(
      {super.key, required this.apiClient, required this.spec, this.onMenu, this.showHeader = true, this.initialInput, this.label});
  final ApiClient apiClient;
  final KnowledgeScreenSpec spec;
  final VoidCallback? onMenu; // standalone narrow layouts: opens the navigation drawer
  final bool showHeader; // false when embedded in the app shell (the shell's top bar carries the title)
  final String? initialInput; // pre-filled input (e.g. a skill key chosen in global search)
  final String? label; // the name the reader knows this view by (navigation label); defaults to the spec title

  @override
  State<KnowledgeScreen> createState() => _KnowledgeScreenState();
}

class _KnowledgeScreenState extends State<KnowledgeScreen> {
  Future<dynamic>? _future;
  final _input = TextEditingController();
  final _filter = TextEditingController();
  String _filterText = '';
  int? _sortColumn;
  bool _sortAscending = true;

  @override
  void initState() {
    super.initState();
    if (widget.initialInput != null) _input.text = widget.initialInput!;
    _future = _request();
  }

  @override
  void didUpdateWidget(covariant KnowledgeScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.initialInput != null && widget.initialInput != oldWidget.initialInput) {
      _input.text = widget.initialInput!;
      _future = _request();
    } else if (oldWidget.spec.path != widget.spec.path) {
      _future = _request();
    }
  }

  @override
  void dispose() {
    _input.dispose();
    _filter.dispose();
    super.dispose();
  }

  /// The request for the current spec and input, or null while a required input is still empty.
  Future<dynamic>? _request() {
    final spec = widget.spec;
    if (spec.inputParam != null && _input.text.trim().isEmpty) return null;
    final query = <String, String>{...?spec.query};
    if (spec.inputParam != null) query[spec.inputParam!] = _input.text.trim();
    return widget.apiClient.getJson(spec.path, query: query.isEmpty ? null : query);
  }

  void _load() {
    setState(() {
      _future = _request();
    });
  }

  /// "Industry Demand" -> "industry demand", for "Could not load industry demand."
  static String _what(String title) => title.replaceAll(RegExp(r'\s*\(.*\)'), '').toLowerCase();

  static bool _isStatusColumn(String c) =>
      c == 'status' || c.endsWith('_state') || c.endsWith('status') || c.startsWith('classification') ||
      c == 'relationship' || c == 'coverage_level' || c == 'trend_state';

  Widget _cell(String column, dynamic v) => _isStatusColumn(column) && v is String && StatusStyle.isKnown(v)
      ? StatusBadge(v, dense: true)
      : Text(Plain.value(v, fallback: fmt), overflow: TextOverflow.ellipsis, maxLines: 3, style: AppTypography.body);

  Widget _components(Map<String, dynamic> comps) {
    return Wrap(spacing: AppSpacing.xxl, runSpacing: AppSpacing.xl, children: [
      for (final e in comps.entries)
        SizedBox(
          width: 300,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(child: Text(Plain.field(e.key), style: AppTypography.title)),
              StatusBadge(fmt(at(e.value, 'status')), dense: true),
            ]),
            const SizedBox(height: AppSpacing.sm),
            for (final k in (e.value is Map ? (e.value as Map).keys : const <String>[]))
              if (k != 'status' && (e.value as Map)[k] != null && (e.value as Map)[k] is! Map && (e.value as Map)[k] is! List)
                Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text('${Plain.field(k.toString())}: ${Plain.value((e.value as Map)[k], fallback: fmt)}',
                        style: AppTypography.caption, maxLines: 4, overflow: TextOverflow.ellipsis)),
          ]),
        ),
    ]);
  }

  static bool _scalar(dynamic v) => v == null || v is String || v is num || v is bool;

  /// A summary block: scalars inline, a flat map as labelled chips, anything nested as expandable JSON.
  Widget _summary(String key, dynamic value, {bool expanded = false}) {
    final title = Plain.field(key);
    if (_scalar(value)) {
      return KeyValueList([MapEntry(title, value)]);
    }
    if (value is Map && value.values.every(_scalar)) {
      return SectionCard(
        title: title,
        child: Wrap(spacing: AppSpacing.xl, runSpacing: AppSpacing.sm, children: [
          for (final e in value.entries)
            e.value is String && StatusStyle.isKnown(e.value as String)
                ? Row(mainAxisSize: MainAxisSize.min, children: [
                    Text('${Plain.field(e.key.toString())}  ', style: AppTypography.muted),
                    StatusBadge(e.value as String, dense: true),
                  ])
                : Text('${Plain.field(e.key.toString())}: ${Plain.value(e.value, fallback: fmt)}', style: AppTypography.muted),
        ]),
      );
    }
    return EvidencePanel(title: title, initiallyExpanded: expanded, children: [
      SelectableText(const JsonEncoder.withIndent('  ').convert(value), style: AppTypography.mono),
    ]);
  }

  List<dynamic> _visibleRows(List<dynamic> rows, List<String> columns) {
    var out = rows;
    final f = _filterText.trim().toLowerCase();
    if (f.isNotEmpty) {
      out = out.where((r) => columns.any((c) => fmt(at(r, c)).toLowerCase().contains(f))).toList();
    }
    if (_sortColumn != null && _sortColumn! < columns.length) {
      final c = columns[_sortColumn!];
      out = [...out]..sort((a, b) {
          final x = at(a, c), y = at(b, c);
          int cmp;
          if (x is num && y is num) {
            cmp = x.compareTo(y);
          } else {
            cmp = fmt(x).compareTo(fmt(y));
          }
          return _sortAscending ? cmp : -cmp;
        });
    }
    return out;
  }

  Widget _table(List rows, List<String> columns) => Align(
        alignment: Alignment.topLeft,
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: DataTable(
            sortColumnIndex: _sortColumn,
            sortAscending: _sortAscending,
            columns: [
              for (var i = 0; i < columns.length; i++)
                DataColumn(
                    label: Text(Plain.field(columns[i])),
                    onSort: (index, ascending) => setState(() {
                          _sortColumn = index;
                          _sortAscending = ascending;
                        })),
            ],
            rows: [
              for (final r in rows)
                DataRow(cells: [
                  for (final c in columns)
                    DataCell(ConstrainedBox(constraints: const BoxConstraints(maxWidth: 360), child: _cell(c, at(r, c)))),
                ]),
            ],
          ),
        ),
      );

  /// Narrow screens: one card per row, every column as a labelled line (nothing hidden off-screen).
  Widget _rowCards(List rows, List<String> columns) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final r in rows)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.xl),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              for (final c in columns)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    SizedBox(width: 130, child: Text(Plain.field(c), style: AppTypography.caption)),
                    Expanded(child: _cell(c, at(r, c))),
                  ]),
                ),
            ]),
          ),
      ]);

  Widget _body(BuildContext context, AsyncSnapshot<dynamic> snap) {
    final spec = widget.spec;
    if (snap.connectionState == ConnectionState.waiting) {
      return const SkeletonPage();
    }
    if (snap.hasError) {
      return ErrorState(what: _what(widget.label ?? spec.title), error: snap.error, onRetry: _load);
    }
    final data = snap.data;
    if (data is! Map<String, dynamic>) {
      return const EmptyState(
          title: 'This view could not be read',
          body: 'The server answered, but not with the information this view expects. Retry, or open another view.');
    }
    final state = (data['evidence_state'] ?? data['status'] ?? 'AVAILABLE').toString();
    if (state == 'NOT_PRODUCED' || state == 'BLOCKED' || state == 'NOT_LOADED') {
      final why = data['reason'] ?? data['reasons'] ?? at(data, 'gate.reasons');
      return DataNotAvailable(state: state, reason: why == null ? null : Plain.sentence(why is List ? why : fmt(why)), onReload: _load);
    }
    final scope = data['scope'] ?? data['population_scope'];
    final warning = at(scope, 'population_scope.representativeness_warning') ?? at(scope, 'representativeness_warning');
    final raw = spec.listKey == '_none' ? null : data[spec.listKey];
    final rows = raw is List ? raw : const [];
    final visible = _visibleRows(rows, spec.columns);
    final total = data['total'];
    final reasons = data['reasons'] ?? at(data, 'gate.reasons');
    final comps = spec.componentsKey == null ? null : data[spec.componentsKey];
    final facts = [
      if (total != null) rows.length < (total as num) ? 'Showing ${fmtCount(rows.length)} of ${fmtCount(total)}' : '${fmtCount(total)} rows',
      if (state != 'AVAILABLE') StatusStyle.label(state),
    ];
    return PageFrame(children: [
      if (spec.help != null)
        Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.lg),
          child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: AppLayout.measure),
              child: Text(spec.help!, style: AppTypography.lede)),
        ),
      Row(children: [
        Expanded(child: Text(facts.join(', '), style: AppTypography.caption)),
        if (!widget.showHeader)
          IconButton(tooltip: 'Reload', icon: const Icon(Icons.refresh, size: 16), onPressed: _load),
      ]),
      if (warning != null)
        Padding(
          padding: const EdgeInsets.only(top: AppSpacing.xs),
          child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: AppLayout.measure),
              child: Text(warning.toString(), style: AppTypography.caption)),
        ),
      const SizedBox(height: AppSpacing.xl),
      if (data['reason'] != null) Text(Plain.sentence(data['reason']), style: AppTypography.muted),
      if (reasons != null && !(reasons is List && reasons.isEmpty))
        Text(Plain.sentence(reasons is List ? reasons : fmt(reasons)), style: AppTypography.muted),
      if (comps is Map<String, dynamic>) ...[_components(comps), const SizedBox(height: AppSpacing.md)],
      for (final key in spec.summaryKeys)
        if (data.containsKey(key)) _summary(key, data[key], expanded: spec.listKey == '_none' && comps == null),
      if (spec.listKey != '_none' && rows.isEmpty)
        const EmptyState(title: 'Nothing to show', body: 'This analysis has nothing for this view. That is an empty result, not an error.'),
      if (rows.isNotEmpty) ...[
        const SizedBox(height: AppSpacing.sm),
        Row(children: [
          Expanded(
            child: TextField(
              controller: _filter,
              style: AppTypography.muted.copyWith(color: AppColors.text),
              decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.search, size: 16),
                  prefixIconConstraints: BoxConstraints(minWidth: 28, minHeight: 20),
                  hintText: 'Filter these rows'),
              onChanged: (v) => setState(() => _filterText = v),
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Text('${visible.length} of ${rows.length} loaded rows', style: AppTypography.caption),
        ]),
        const SizedBox(height: AppSpacing.md),
        LayoutBuilder(
            builder: (context, box) =>
                box.maxWidth < 720 ? _rowCards(visible, spec.columns) : _table(visible, spec.columns)),
      ],
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final spec = widget.spec;
    final content = Column(children: [
      if (spec.inputParam != null)
        Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.md, AppSpacing.lg, 0),
          child: Row(children: [
            Expanded(
                child: TextField(
                    controller: _input,
                    decoration: InputDecoration(labelText: Plain.field(spec.inputParam!), hintText: spec.inputHint),
                    onSubmitted: (_) => _load())),
            const SizedBox(width: AppSpacing.sm),
            FilledButton(onPressed: _load, child: const Text('Trace')),
          ]),
        ),
      Expanded(
        child: _future == null
            ? EmptyState(
                icon: Icons.manage_search,
                title: 'Enter a ${Plain.field(spec.inputParam!).toLowerCase()} to load this view.',
                body: spec.inputHint ?? 'This view needs an input before it can load.')
            : FutureBuilder<dynamic>(future: _future, builder: _body),
      ),
    ]);
    if (!widget.showHeader) return content;
    return Scaffold(
      appBar: AppBar(
          leading: widget.onMenu == null
              ? null
              : IconButton(tooltip: 'Menu', icon: const Icon(Icons.menu), onPressed: widget.onMenu),
          title: Text(spec.title),
          actions: [
            IconButton(tooltip: 'Reload', icon: const Icon(Icons.refresh), onPressed: _load),
          ]),
      body: content,
    );
  }
}
