import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../services/api_client.dart';
import '../theme/design_system.dart';
import '../widgets/ui_kit.dart';

class SearchHit {
  const SearchHit(this.type, this.id, this.label, this.subtitle, this.target);
  final String type;
  final String id;
  final String label;
  final String? subtitle;
  final Map<String, dynamic> target;
}

/// Opens the search surface: it unfolds from the top of the page rather than popping up as a modal box.
Future<SearchHit?> showSearchSurface(BuildContext context, ApiClient api, {String initialQuery = ''}) {
  final reduce = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
  return showGeneralDialog<SearchHit>(
    context: context,
    barrierDismissible: true,
    barrierLabel: 'Close search',
    barrierColor: AppColors.bg0.withValues(alpha: 0.72),
    transitionDuration: reduce ? Duration.zero : AppMotion.normal,
    pageBuilder: (context, _, __) => SearchDialog(api: api, initialQuery: initialQuery),
    transitionBuilder: (context, anim, _, child) {
      final t = CurvedAnimation(parent: anim, curve: AppMotion.curve);
      return FadeTransition(
        opacity: t,
        child: SlideTransition(position: Tween(begin: const Offset(0, -0.03), end: Offset.zero).animate(t), child: child),
      );
    },
  );
}

/// Global search over the run in view (GET /api/v1/search), as a research command surface: results grouped by kind,
/// arrow keys move through them, Enter opens the selected one, Escape closes. Results are whatever the API returns;
/// nothing is suggested locally.
class SearchDialog extends StatefulWidget {
  const SearchDialog({super.key, required this.api, this.initialQuery = ''});
  final ApiClient api;
  final String initialQuery;

  @override
  State<SearchDialog> createState() => _SearchDialogState();
}

class _SearchDialogState extends State<SearchDialog> {
  late final TextEditingController _q = TextEditingController(text: widget.initialQuery);
  late final FocusNode _field = FocusNode(onKeyEvent: _onKey);
  Timer? _debounce;
  bool _loading = false;
  Object? _error;
  Map<String, dynamic>? _data;
  List<Map<String, dynamic>> _flat = const [];
  int _sel = 0;
  int _seq = 0;

  /// Result groups in reading order, with human names (the API's type codes stay in tooltips).
  static const groups = [
    ('COURSE', 'Courses'),
    ('TOPIC', 'Topics'),
    ('CONCEPT', 'Concepts'),
    ('SKILL', 'Skills'),
    ('ESCO', 'Skills reference'),
    ('OCCUPATION', 'Occupations'),
    ('JOB', 'Jobs'),
    ('COMPANY', 'Companies'),
  ];

  @override
  void initState() {
    super.initState();
    if (widget.initialQuery.trim().length >= 2) _run(widget.initialQuery);
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _q.dispose();
    _field.dispose();
    super.dispose();
  }

  Future<void> _run(String q) async {
    final seq = ++_seq;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final d = asMap(await widget.api.getJson('/api/v1/search', query: {'q': q.trim(), 'limit': '40'}));
      if (!mounted || seq != _seq) return;
      setState(() {
        _data = d;
        _flat = _ordered(d);
        _sel = 0;
        _loading = false;
      });
    } catch (e) {
      if (!mounted || seq != _seq) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  List<Map<String, dynamic>> _ordered(Map<String, dynamic> d) {
    final items = asList(d['items']).map(asMap).toList();
    final known = groups.map((g) => g.$1).toList();
    int rank(Map<String, dynamic> m) {
      final i = known.indexOf(fmt(m['type']));
      return i < 0 ? known.length : i;
    }

    final indexed = [for (var i = 0; i < items.length; i++) (i, items[i])];
    indexed.sort((a, b) => rank(a.$2) != rank(b.$2) ? rank(a.$2).compareTo(rank(b.$2)) : a.$1.compareTo(b.$1));
    return [for (final e in indexed) e.$2];
  }

  void _changed(String v) {
    _debounce?.cancel();
    _debounce = Timer(AppMotion.normal, () {
      if (!mounted) return;
      if (v.trim().length >= 2) {
        _run(v);
      } else {
        setState(() {
          _data = null;
          _flat = const [];
        });
      }
    });
  }

  void _open(Map<String, dynamic> m) {
    Navigator.of(context).pop(SearchHit(m['type'].toString(), m['id'].toString(), fmt(m['label']),
        m['subtitle']?.toString(), asMap(m['target'])));
  }

  KeyEventResult _onKey(FocusNode node, KeyEvent e) {
    if (e is! KeyDownEvent && e is! KeyRepeatEvent) return KeyEventResult.ignored;
    if (e.logicalKey == LogicalKeyboardKey.arrowDown && _flat.isNotEmpty) {
      setState(() => _sel = (_sel + 1) % _flat.length);
      return KeyEventResult.handled;
    }
    if (e.logicalKey == LogicalKeyboardKey.arrowUp && _flat.isNotEmpty) {
      setState(() => _sel = (_sel - 1 + _flat.length) % _flat.length);
      return KeyEventResult.handled;
    }
    if (e.logicalKey == LogicalKeyboardKey.enter && _flat.isNotEmpty) {
      _open(_flat[_sel]);
      return KeyEventResult.handled;
    }
    if (e.logicalKey == LogicalKeyboardKey.escape) {
      Navigator.of(context).maybePop();
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  Widget _results() {
    if (_loading && _data == null) {
      return const Padding(padding: EdgeInsets.all(AppSpacing.xl), child: SkeletonBlock(height: 18));
    }
    if (_error != null) {
      final e = _error;
      return Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Text('Search is unavailable: ${e is ApiException ? e.describe() : 'the analysis service cannot be reached'}',
              style: AppTypography.muted));
    }
    if (_data == null) {
      return Padding(
          padding: EdgeInsets.all(AppSpacing.xl),
          child: Text('Type at least two characters. Use ↑ ↓ to move, Enter to open, Esc to close.',
              style: AppTypography.muted));
    }
    if (_flat.isEmpty) {
      return Padding(
          padding: EdgeInsets.all(AppSpacing.xl), child: Text('Nothing in this analysis matches that.', style: AppTypography.muted));
    }
    final names = {for (final g in groups) g.$1: g.$2};
    final children = <Widget>[
      Padding(
        padding: const EdgeInsets.fromLTRB(AppSpacing.xl, AppSpacing.md, AppSpacing.xl, 0),
        child: Text('${fmtCount(_data!['total'])} results', style: AppTypography.caption),
      ),
    ];
    String? last;
    for (var i = 0; i < _flat.length; i++) {
      final m = _flat[i];
      final type = fmt(m['type']);
      if (type != last) {
        last = type;
        final n = _flat.where((x) => fmt(x['type']) == type).length;
        children.add(Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.xl, AppSpacing.lg, AppSpacing.xl, AppSpacing.xs),
          child: Text('${names[type] ?? StatusStyle.label(type)} · $n', style: AppTypography.overline),
        ));
      }
      final selected = i == _sel;
      children.add(MouseRegion(
        onEnter: (_) => setState(() => _sel = i),
        child: InkWell(
          onTap: () => _open(m),
          child: AnimatedContainer(
            duration: AppMotion.fast,
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xl, vertical: AppSpacing.sm),
            decoration: BoxDecoration(
              color: selected ? AppColors.surfaceRaised : Colors.transparent,
              border: Border(left: BorderSide(color: selected ? AppColors.primary : Colors.transparent, width: 2)),
            ),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(fmt(m['label']), style: AppTypography.body, maxLines: 1, overflow: TextOverflow.ellipsis),
              if (m['subtitle'] != null)
                Text(fmt(m['subtitle']), style: AppTypography.caption, maxLines: 1, overflow: TextOverflow.ellipsis),
            ]),
          ),
        ),
      ));
    }
    children.add(const SizedBox(height: AppSpacing.lg));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: children);
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    return SafeArea(
      child: Align(
        alignment: Alignment.topCenter,
        child: Padding(
          padding: EdgeInsets.only(top: width < 600 ? AppSpacing.sm : 72, left: AppSpacing.sm, right: AppSpacing.sm),
          child: Material(
            color: AppColors.bg1,
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppRadius.lg), side: BorderSide(color: AppColors.border)),
            clipBehavior: Clip.antiAlias,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 720, maxHeight: 620),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.lg, AppSpacing.lg, AppSpacing.sm),
                  child: TextField(
                    controller: _q,
                    focusNode: _field,
                    autofocus: true,
                    style: AppTypography.lede,
                    decoration: const InputDecoration(
                        prefixIcon: Icon(Icons.search),
                        hintText: 'Search the curriculum, skills, concepts, occupations or evidence…'),
                    onChanged: _changed,
                  ),
                ),
                if (_loading && _data != null) const LinearProgressIndicator(minHeight: 1),
                const Divider(height: 1),
                Flexible(child: SingleChildScrollView(child: _results())),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}
