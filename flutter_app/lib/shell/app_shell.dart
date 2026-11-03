import 'package:flutter/material.dart';

import '../screens/premium/pages.dart';
import '../services/api_client.dart';
import '../theme/design_system.dart';
import '../widgets/ui_kit.dart';
import 'appearance_panel.dart';
import 'navigation.dart';
import 'page_guides.dart';
import 'run_context.dart';
import 'search_dialog.dart';

/// Application shell: a quiet typographic sidebar (collapsible on wide screens, a drawer on narrow ones), a top bar
/// with the breadcrumb, global search and the analysis context (run, target curriculum, source, time, evidence), and
/// the page area. Pages carry their own title, so the top bar never repeats it.
class HomeShell extends StatefulWidget {
  const HomeShell({super.key, this.apiClient});
  final ApiClient? apiClient;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  late final ApiClient _api = widget.apiClient ?? ApiClient();
  late final AnalysisContext _ctx = AnalysisContext(_api);
  final _scaffoldKey = GlobalKey<ScaffoldState>();
  Dest _dest = Dest.overview;
  String? _arg;
  bool _collapsed = false;
  bool _moreOpen = false;
  bool _guideOpen = false; // "About this page", kept open or closed for the session
  Map<String, dynamic>? _context; // /api/v1/overview of the run in view (top-bar facts); null when unavailable
  bool _contextLoading = true;
  String _lastStatus = 'LATEST';

  @override
  void initState() {
    super.initState();
    _ctx.addListener(_onContextChanged);
    _loadContext();
    _ctx.recover(); // a page reload while an analysis runs: follow it again
    Appearance.load(_api); // the design and mode chosen in the Appearance panel
  }

  @override
  void dispose() {
    _ctx.removeListener(_onContextChanged);
    _ctx.dispose();
    super.dispose();
  }

  void _onContextChanged() {
    if (_ctx.status != _lastStatus) {
      _lastStatus = _ctx.status;
      _loadContext();
    }
    if (mounted) setState(() {});
  }

  Future<void> _loadContext() async {
    if (_ctx.blocksOldResults) {
      if (mounted) setState(() => _context = null);
      return;
    }
    _contextLoading = true;
    try {
      final d = await _api.getJson('/api/v1/overview');
      if (mounted) {
        setState(() {
          _context = d is Map<String, dynamic> ? d : null;
          _contextLoading = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _context = null;
          _contextLoading = false;
        });
      }
    }
  }

  void _go(Dest d, {String? arg, bool closeDrawer = false}) {
    setState(() {
      _dest = d;
      _arg = arg;
    });
    if (closeDrawer) Navigator.of(context).pop();
  }

  Future<void> _openSearch([String initial = '']) async {
    final hit = await showSearchSurface(context, _api, initialQuery: initial);
    if (hit == null) return;
    switch (hit.type) {
      case 'SKILL':
      case 'ESCO':
        _go(Dest.evidenceTrace, arg: (hit.target['skill_key'] ?? hit.id).toString());
        break;
      case 'CONCEPT':
      case 'COURSE':
      case 'TOPIC':
        _go(Dest.graph, arg: hit.id);
        break;
      case 'OCCUPATION':
        _go(Dest.occupations);
        break;
      default:
        _go(Dest.industryIntelligence);
    }
  }

  // ---------------------------------------------------------------- sidebar

  Widget _sidebar({required bool drawer}) {
    final collapsed = _collapsed && !drawer;
    final v2 = Design.current.isV2;
    final panel = AnimatedContainer(
      duration: AppMotion.normal,
      curve: AppMotion.curve,
      width: v2 ? (collapsed ? 68 : 252) : (collapsed ? 64 : 232),
      // Version 2: the navigation is set off from the page by a single hairline
      decoration: BoxDecoration(
          color: AppColors.navBg, border: v2 ? Border(right: BorderSide(color: AppColors.borderSubtle)) : null),
      child: Material(
        type: MaterialType.transparency,
        child: Column(children: [
          _brand(collapsed),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.only(bottom: AppSpacing.lg),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                for (final g in navGroups) ...[
                  if (g.collapsible && !collapsed)
                    _moreToggle(g)
                  else if (!collapsed)
                    Padding(
                      padding: Design.current.isV2
                          ? const EdgeInsets.fromLTRB(AppSpacing.lg + 4, AppSpacing.xl, AppSpacing.lg, AppSpacing.xs + 2)
                          : const EdgeInsets.fromLTRB(AppSpacing.xl, AppSpacing.xxl, AppSpacing.lg, AppSpacing.sm),
                      child: Text(g.title, style: AppTypography.overline.copyWith(color: AppColors.navFaint)),
                    )
                  else
                    const SizedBox(height: AppSpacing.lg),
                  // a folded group shows its entries only when opened (or when one of them is the current page);
                  // the icon-only sidebar has no group to open, so it lists every destination
                  if (!g.collapsible || collapsed || _moreOpen || g.entries.any((e) => e.dest == _dest))
                    for (final e in g.entries)
                      _navItem(e, collapsed: collapsed, drawer: drawer, level: _levelOf(g)),
                ],
              ]),
            ),
          ),
          if (!drawer)
            Padding(
              padding: const EdgeInsets.all(AppSpacing.sm),
              child: IconButton(
                tooltip: collapsed ? 'Expand navigation' : 'Collapse navigation',
                icon: Icon(collapsed ? Icons.chevron_right : Icons.chevron_left, color: AppColors.navFaint, size: 18),
                onPressed: () => setState(() => _collapsed = !_collapsed),
              ),
            ),
        ]),
      ),
    );
    return panel;
  }

  Widget _moreToggle(NavGroup g) {
    final open = _moreOpen || g.entries.any((e) => e.dest == _dest);
    return InkWell(
      onTap: () => setState(() => _moreOpen = !_moreOpen),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(AppSpacing.xl, AppSpacing.xxl, AppSpacing.lg, AppSpacing.sm),
        child: Row(children: [
          Expanded(child: Text(g.title, style: AppTypography.overline.copyWith(color: AppColors.navFaint))),
          AnimatedRotation(
            turns: open ? 0.5 : 0,
            duration: AppMotion.normal,
            curve: AppMotion.curve,
            child: Icon(Icons.expand_more, size: 16, color: AppColors.navFaint),
          ),
        ]),
      ),
    );
  }

  Widget _brand(bool collapsed) {
    if (Design.current.isV2) {
      // a monogram in a 1px gold frame
      final mark = Container(
        width: 30,
        height: 30,
        alignment: Alignment.center,
        decoration: BoxDecoration(border: Border.all(color: AppColors.accent), borderRadius: BorderRadius.circular(8)),
        child: Text('Ci',
            style: TextStyle(
                fontFamily: AppFonts.display, fontSize: 16, fontWeight: FontWeight.w600, color: AppColors.navText, height: 1)),
      );
      return Padding(
        padding: EdgeInsets.fromLTRB(collapsed ? 19 : AppSpacing.xl, AppSpacing.xl, AppSpacing.md, AppSpacing.sm),
        child: collapsed
            ? mark
            : Row(children: [
                mark,
                const SizedBox(width: AppSpacing.sm + 2),
                Expanded(
                  child: Text('Curriculum intelligence',
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                          fontFamily: AppFonts.display,
                          fontSize: 19,
                          fontWeight: FontWeight.w500,
                          height: 1.1,
                          color: AppColors.navText)),
                ),
              ]),
      );
    }
    return Padding(
      padding: EdgeInsets.fromLTRB(collapsed ? AppSpacing.md : AppSpacing.xl, AppSpacing.xl + 4, AppSpacing.md, AppSpacing.sm),
      child: Text(collapsed ? 'Ci' : 'Curriculum\nintelligence',
          style: TextStyle(
              fontFamily: AppFonts.display,
              fontFamilyFallback: AppFonts.displayFallback,
              fontSize: 22,
              height: 1.1,
              color: AppColors.navText)),
    );
  }

  /// The quieter the group, the lower its place in the hierarchy: the work (0), evidence and workspace (1), more views (2).
  static int _levelOf(NavGroup g) => switch (g.title) {
        'Start' || 'Intelligence' || 'Decisions' => 0,
        'Evidence & quality' || 'Workspace' => 1,
        _ => 2,
      };

  Widget _navItem(NavEntry e, {required bool collapsed, required bool drawer, int level = 0}) {
    final selected = e.dest == _dest;
    if (Design.current.isV2) return _studioNavItem(e, selected: selected, collapsed: collapsed, drawer: drawer, level: level);
    if (collapsed) {
      return Tooltip(
        message: e.label,
        child: InkWell(
          onTap: () => _go(e.dest),
          child: SizedBox(
            width: 64,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
              child: Icon(e.icon, size: 18, color: selected ? AppColors.navAccent : AppColors.navFaint),
            ),
          ),
        ),
      );
    }
    final size = level == 0 ? 14.5 : level == 1 ? 13.5 : 13.0;
    final rest = level == 2 ? AppColors.navFaint : AppColors.navMuted;
    return ListTile(
      dense: true,
      visualDensity: const VisualDensity(vertical: -3.5),
      contentPadding: const EdgeInsets.only(left: AppSpacing.lg, right: AppSpacing.md),
      minLeadingWidth: 6,
      horizontalTitleGap: AppSpacing.sm,
      hoverColor: Colors.transparent,
      selectedTileColor: Colors.transparent,
      leading: AnimatedContainer(
        duration: AppMotion.normal,
        curve: AppMotion.emphasized,
        width: 5,
        height: selected ? 5 : 0,
        decoration: BoxDecoration(color: AppColors.navAccent, shape: BoxShape.circle),
      ),
      selected: selected,
      title: AnimatedDefaultTextStyle(
        duration: AppMotion.fast,
        style: TextStyle(
            fontFamily: AppFonts.body,
            fontSize: size,
            height: 1.4,
            fontWeight: FontWeight.w400,
            color: selected ? AppColors.navText : rest),
        child: Text(e.label, overflow: TextOverflow.ellipsis),
      ),
      onTap: () => _go(e.dest, closeDrawer: drawer),
    );
  }

  /// Version 2 navigation item: an icon and the label; the current page sits on the card tone, marked with a coral dot.
  Widget _studioNavItem(NavEntry e, {required bool selected, required bool collapsed, required bool drawer, int level = 0}) {
    final color = selected ? AppColors.navText : (level == 2 ? AppColors.navFaint : AppColors.navMuted);
    if (collapsed) {
      return Tooltip(
        message: e.label,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
          child: InkWell(
            onTap: () => _go(e.dest),
            child: AnimatedContainer(
              duration: AppMotion.fast,
              height: 38,
              decoration: BoxDecoration(
                  color: selected ? AppColors.navSelected : Colors.transparent, borderRadius: BorderRadius.circular(2)),
              child: Center(child: Icon(e.icon, size: 18, color: color)),
            ),
          ),
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm, vertical: 1),
      child: ListTile(
        dense: true,
        visualDensity: const VisualDensity(vertical: -3),
        contentPadding: const EdgeInsets.only(left: AppSpacing.md, right: AppSpacing.sm),
        minLeadingWidth: 18,
        horizontalTitleGap: AppSpacing.md - 2,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(2)),
        hoverColor: AppColors.navSelected,
        selectedTileColor: AppColors.navSelected,
        tileColor: Colors.transparent,
        leading: Icon(e.icon, size: 17, color: color),
        selected: selected,
        title: Text(e.label,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
                fontFamily: AppFonts.body,
                fontSize: level == 2 ? 13 : 13.5,
                height: 1.4,
                fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                color: selected ? AppColors.navText : color)),
        trailing: selected ? AccentDot(color: AppColors.navAccent) : null,
        onTap: () => _go(e.dest, closeDrawer: drawer),
      ),
    );
  }

  // ---------------------------------------------------------------- top bar

  String _contextLine() {
    final c = _context;
    if (_ctx.status == 'ANALYSIS_PENDING') return 'New curriculum uploaded · analysis being prepared';
    if (_ctx.status == 'ANALYSIS_NOT_RUN') return 'New curriculum uploaded · analysis not yet run';
    if (_ctx.status == 'ANALYSIS_FAILED' || _ctx.status == 'NEEDS_REVIEW') return 'New curriculum uploaded · analysis needs attention';
    if (c == null) return _contextLoading ? 'Checking status…' : 'Status unavailable';
    final run = asMap(c['run']);
    final target = asMap(c['target']);
    final ev = asMap(c['evidence_status']);
    final partial = ev.values.where((v) => v != 'AVAILABLE' && v != 'SUFFICIENT').length;
    return [
      _ctx.status == 'ANALYSIS_READY' ? 'New analysis' : 'Published analysis',
      if (target.isNotEmpty) '${fmt(target['institution'])} ${fmt(target['curriculum_version'])}',
      fmt(run['generated_at']).replaceFirst('T', ' ').replaceFirst('+00:00', ' UTC'),
      ev.isEmpty ? 'evidence status unknown' : partial == 0 ? 'all evidence requirements met' : '$partial of ${ev.length} evidence requirements limited',
    ].join('   ');
  }

  /// The analysis reference stays available on hover (technical detail), never in the line itself.
  String _runTooltip() {
    final id = fmt(asMap(_context?['run'])['run_id']);
    return 'The analysis every number on this page belongs to (analysis reference ${id.length > 8 ? id.substring(0, 8) : id})';
  }

  /// Day / dark mode and the Appearance panel, in both designs.
  List<Widget> _appearanceButtons() => [
        IconButton(
          tooltip: Design.current.isDark ? 'Switch to light mode' : 'Switch to dark mode',
          icon: Icon(Design.current.isDark ? Icons.light_mode_outlined : Icons.dark_mode_outlined, size: 19),
          onPressed: () => Appearance.toggleMode(_api),
        ),
        IconButton(
          tooltip: 'Appearance',
          icon: const Icon(Icons.palette_outlined, size: 19),
          onPressed: () => showAppearancePanel(context, _api),
        ),
      ];

  Widget _topBar({required bool narrow}) {
    final crumb = '${groupOf(_dest)} / ${entryOf(_dest).label}';
    final v2 = Design.current.isV2;
    return Container(
      padding: EdgeInsets.fromLTRB(narrow ? AppSpacing.sm : (v2 ? AppSpacing.xxl : AppSpacing.page), AppSpacing.lg,
          narrow ? AppSpacing.sm : (v2 ? AppSpacing.xl : AppSpacing.page), AppSpacing.sm),
      color: v2 ? Colors.transparent : AppColors.bg0,
      child: Row(children: [
        if (narrow)
          IconButton(
              tooltip: 'Menu', icon: const Icon(Icons.menu), onPressed: () => _scaffoldKey.currentState?.openDrawer()),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Text(crumb, style: v2 ? AppTypography.overline : AppTypography.caption, overflow: TextOverflow.ellipsis),
            Tooltip(
              message: _runTooltip(),
              child: Text(_contextLine(), style: AppTypography.caption, overflow: TextOverflow.ellipsis),
            ),
          ]),
        ),
        if (!narrow)
          SizedBox(
            width: 260,
            child: TextField(
              style: AppTypography.muted.copyWith(color: AppColors.text),
              decoration: v2
                  ? InputDecoration(
                      prefixIcon: const Icon(Icons.search, size: 16),
                      prefixIconConstraints: const BoxConstraints(minWidth: 36, minHeight: 20),
                      hintText: 'Search skills, courses, concepts',
                      border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(AppRadius.pill), borderSide: BorderSide(color: AppColors.border)),
                      enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(AppRadius.pill), borderSide: BorderSide(color: AppColors.border)),
                      focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(AppRadius.pill),
                          borderSide: BorderSide(color: AppColors.primary)),
                      contentPadding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: 10))
                  : const InputDecoration(
                      prefixIcon: Icon(Icons.search, size: 16),
                      prefixIconConstraints: BoxConstraints(minWidth: 28, minHeight: 20),
                      hintText: 'Search skills, courses, concepts'),
              onSubmitted: _openSearch,
            ),
          )
        else
          IconButton(tooltip: 'Search', icon: const Icon(Icons.search), onPressed: () => _openSearch()),
        const SizedBox(width: AppSpacing.xs),
        ..._appearanceButtons(),
      ]),
    );
  }

  Widget _contextBanner() {
    if (_ctx.status == 'LATEST') return const SizedBox.shrink();
    final ready = _ctx.status == 'ANALYSIS_READY';
    final name = fmt(at(_ctx.upload, 'metadata.values.programme') ?? at(_ctx.upload, 'metadata.values.institution') ??
        'the uploaded curriculum');
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.page, vertical: AppSpacing.xs),
      child: Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: AppSpacing.md, children: [
        StatusBadge(ready ? 'ANALYSIS_READY' : _ctx.status == 'ANALYSIS_NOT_RUN' ? 'NEEDS_REVIEW' : _ctx.status, dense: true),
        Text(ready ? 'Showing the analysis of $name' : 'Scoped to $name', style: AppTypography.muted),
        if (_ctx.options?['industry'] == false || _ctx.options?['peers'] == false)
          Text(
              _ctx.options?['industry'] == false
                  ? '(curriculum only: industry evidence was not requested)'
                  : '(peer comparison was not requested)',
              style: AppTypography.caption),
        TextButton(onPressed: _ctx.showLatest, child: const Text('Show the published analysis')),
      ]),
    );
  }

  /// "About this page": one sentence on what the page shows; opened, why it matters, the evidence behind it and the
  /// next step. The page's own headline says what was found.
  Widget _pageGuide({required bool narrow}) {
    final g = pageGuides[_dest];
    if (g == null) return const SizedBox.shrink();
    final pad = narrow ? AppSpacing.sm : AppSpacing.page;
    return Container(
      key: const ValueKey('page-guide'),
      width: double.infinity,
      padding: EdgeInsets.fromLTRB(pad, 0, pad, AppSpacing.xs),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Semantics(
          button: true,
          expanded: _guideOpen,
          child: InkWell(
            onTap: () => setState(() => _guideOpen = !_guideOpen),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Padding(
                    padding: EdgeInsets.only(top: 2, right: AppSpacing.sm),
                    child: Icon(Icons.info_outline, size: 15, color: AppColors.textFaint)),
                Expanded(
                  child: Text.rich(TextSpan(children: [
                    TextSpan(text: 'About this page: ', style: TextStyle(color: AppColors.textMuted)),
                    TextSpan(text: g.shows),
                  ]), style: AppTypography.caption),
                ),
                Text(_guideOpen ? 'Less' : 'More', style: AppTypography.caption.copyWith(color: AppColors.primary)),
              ]),
            ),
          ),
        ),
        AnimatedSize(
          duration: AppMotion.reduced(context) ? Duration.zero : AppMotion.normal,
          alignment: Alignment.topLeft,
          child: !_guideOpen
              ? const SizedBox(width: double.infinity)
              : Padding(
                  padding: const EdgeInsets.only(left: 23, bottom: AppSpacing.sm),
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: AppLayout.measure + 120),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      _guideLine('Why it matters', g.why),
                      _guideLine('Evidence behind it', g.evidence),
                      _guideLine('What you can do', g.next),
                      if (g.nextDest != null && g.nextDest != _dest)
                        TextButton(
                            onPressed: () => _go(g.nextDest!),
                            child: Text('Go to ${entryOf(g.nextDest!).label}')),
                    ]),
                  ),
                ),
        ),
      ]),
    );
  }

  Widget _guideLine(String label, String text) => Padding(
        padding: const EdgeInsets.only(top: AppSpacing.xs),
        child: Text.rich(TextSpan(children: [
          TextSpan(text: '$label. ', style: TextStyle(color: AppColors.text, fontWeight: FontWeight.w600)),
          TextSpan(text: text),
        ]), style: AppTypography.muted),
      );

  Widget _page() => AnimatedSwitcher(
        duration: AppMotion.reduced(context) ? Duration.zero : AppMotion.normal,
        switchInCurve: AppMotion.emphasized,
        switchOutCurve: Curves.easeOut,
        transitionBuilder: (child, anim) => FadeTransition(
          opacity: anim,
          child: AnimatedBuilder(
            animation: anim,
            child: child,
            builder: (context, c) => Transform.translate(offset: Offset(0, 10 * (1 - anim.value)), child: c),
          ),
        ),
        child: KeyedSubtree(
          key: ValueKey('${_dest.name}:${_arg ?? ''}:${_api.runId ?? 'latest'}:${_ctx.status}'),
          child: buildPage(_dest, _api, arg: _arg, navigate: (d, {arg}) => _go(d, arg: arg)),
        ),
      );

  @override
  Widget build(BuildContext context) {
    return RunScope(
      context: _ctx,
      child: LayoutBuilder(builder: (context, box) {
        final wide = box.maxWidth >= 1000;
        final body = Column(children: [
          _topBar(narrow: !wide),
          _contextBanner(),
          _pageGuide(narrow: !wide),
          Expanded(child: _page()),
        ]);
        // both designs keep the ground clear: no pattern, no glow
        Widget ground(Widget child) => child;
        if (wide) {
          return Scaffold(
            body: ground(Row(children: [
              _sidebar(drawer: false),
              Expanded(child: body),
            ])),
          );
        }
        return Scaffold(
          key: _scaffoldKey,
          drawer: Drawer(child: SafeArea(child: _sidebar(drawer: true))),
          body: ground(SafeArea(child: body)),
        );
      }),
    );
  }
}
