import 'dart:convert';

import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../theme/design_system.dart';
import '../theme/plain_language.dart';
import 'motion.dart';

/// The editorial primitives. Pages read like an annotated research report: a margin column carries labels, indices
/// and the evidence trail; a reading column carries sentences; whitespace -- not boxes -- separates the stages.
/// None of these widgets computes or invents a value: they render what the API returned, and `null` is always shown
/// as "—" (no value), never as 0.

/// Version 2 ("Atelier") surface: a rounded card on a hairline ring that warms to the accent under the pointer.
/// Version 1 never draws it (whitespace, not boxes); callers branch on [Design.current.isV2].
class StudioCard extends StatefulWidget {
  const StudioCard({super.key, required this.child, this.padding = const EdgeInsets.all(32), this.sunken = false});
  final Widget child;
  final EdgeInsets padding;
  final bool sunken; // a well inside a card (disclosed evidence, code)

  @override
  State<StudioCard> createState() => _StudioCardState();
}

class _StudioCardState extends State<StudioCard> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) {
    final sunken = widget.sunken;
    final card = AnimatedContainer(
      duration: AppMotion.normal,
      curve: AppMotion.curve,
      width: double.infinity,
      padding: widget.padding,
      decoration: BoxDecoration(
        color: sunken ? AppColors.surfaceSunken : AppColors.surface,
        borderRadius: sunken ? BorderRadius.circular(AppRadius.md) : AppRadius.card,
        border: Border.all(
            color: sunken
                ? AppColors.borderSubtle
                : _hover
                    ? AppColors.primary.withValues(alpha: 0.45)
                    : AppColors.border),
        boxShadow: AppShadows.card,
      ),
      child: widget.child,
    );
    if (sunken) return card;
    return MouseRegion(onEnter: (_) => setState(() => _hover = true), onExit: (_) => setState(() => _hover = false), child: card);
  }
}

/// A short accent rule before a Version 2 label.
class AccentRule extends StatelessWidget {
  const AccentRule({super.key, this.width = 22});
  final double width;

  @override
  Widget build(BuildContext context) => DrawnRule(width: width);
}

/// A small accent dot (the active navigation item).
class AccentDot extends StatelessWidget {
  const AccentDot({super.key, this.size = 6, this.color});
  final double size;
  final Color? color;

  @override
  Widget build(BuildContext context) => Container(
      width: size, height: size, decoration: BoxDecoration(color: color ?? AppColors.accent, shape: BoxShape.circle));
}

String fmt(dynamic v) {
  if (v == null) return '—';
  if (v is String) return Plain.prose(v); // backend prose in plain words (plain_language.dart)
  if (v is double) return v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toString();
  if (v is num || v is bool) return v.toString();
  return jsonEncode(v);
}

/// Thousands separator for counts ("4426" -> "4,426"); anything else via [fmt].
String fmtCount(dynamic v) {
  if (v is int) {
    final s = v.abs().toString();
    final b = StringBuffer(v < 0 ? '-' : '');
    for (var i = 0; i < s.length; i++) {
      if (i > 0 && (s.length - i) % 3 == 0) b.write(',');
      b.write(s[i]);
    }
    return b.toString();
  }
  return fmt(v);
}

dynamic at(dynamic row, String dotted) {
  dynamic cur = row;
  for (final part in dotted.split('.')) {
    if (cur is Map && cur.containsKey(part)) {
      cur = cur[part];
    } else {
      return null;
    }
  }
  return cur;
}

Map<String, dynamic> asMap(dynamic v) => v is Map<String, dynamic> ? v : <String, dynamic>{};
List<dynamic> asList(dynamic v) => v is List ? v : const <dynamic>[];

// ====================================================================================================== motion

/// Tells the sections of a page when its scroll position or its content size changes, so each can reveal itself once
/// it comes into view.
class RevealScope extends InheritedWidget {
  const RevealScope({super.key, required this.controller, required super.child});
  final Listenable controller;

  static Listenable? of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<RevealScope>()?.controller;

  @override
  bool updateShouldNotify(RevealScope oldWidget) => oldWidget.controller != controller;
}

/// A section that rises and fades in once, when it first comes into view (the first few sections of a page together
/// form one orchestrated entrance, [order] steps apart). One controller, no timers; instant with reduced motion and
/// outside a scrolling page.
class SectionReveal extends StatefulWidget {
  const SectionReveal({super.key, required this.child, this.order = 0});
  final Widget child;
  final int order;

  @override
  State<SectionReveal> createState() => _SectionRevealState();
}

class _SectionRevealState extends State<SectionReveal> with SingleTickerProviderStateMixin {
  late final AnimationController _c;
  late final Animation<double> _t;
  Listenable? _scroll;
  bool _started = false;

  @override
  void initState() {
    super.initState();
    final delay = AppMotion.stagger * widget.order.clamp(0, 4);
    final total = delay + AppMotion.complex;
    _c = AnimationController(vsync: this, duration: total);
    _t = CurvedAnimation(
        parent: _c,
        curve: Interval(delay.inMilliseconds / total.inMilliseconds, 1.0, curve: AppMotion.emphasized));
    WidgetsBinding.instance.addPostFrameCallback((_) => _check());
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final scroll = RevealScope.of(context);
    if (AppMotion.reduced(context) || scroll == null) {
      _show(instant: true);
      return;
    }
    if (!identical(scroll, _scroll)) {
      _scroll?.removeListener(_check);
      _scroll = scroll;
      if (!_started) scroll.addListener(_check);
    }
  }

  void _show({bool instant = false}) {
    if (_started) return;
    _started = true;
    _scroll?.removeListener(_check);
    if (instant) {
      _c.value = 1;
    } else {
      _c.forward();
    }
  }

  void _check() {
    if (_started || !mounted) return;
    final box = context.findRenderObject();
    if (box is! RenderBox || !box.attached || !box.hasSize) return;
    final top = box.localToGlobal(Offset.zero).dy;
    if (top < MediaQuery.sizeOf(context).height - 24) _show();
  }

  @override
  void dispose() {
    _scroll?.removeListener(_check);
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _t,
      child: widget.child,
      builder: (context, child) =>
          Opacity(opacity: _t.value, alwaysIncludeSemantics: true, child: Transform.translate(offset: Offset(0, 14 * (1 - _t.value)), child: child)),
    );
  }
}

/// Content that fades in once when it first appears (an opened disclosure, a filtered list).
class FadeInOnce extends StatelessWidget {
  const FadeInOnce({super.key, required this.child, this.rise = 6});
  final Widget child;
  final double rise;

  @override
  Widget build(BuildContext context) {
    if (AppMotion.reduced(context)) return child;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: AppMotion.normal,
      curve: AppMotion.curve,
      child: child,
      builder: (context, t, c) => Opacity(opacity: t, child: Transform.translate(offset: Offset(0, rise * (1 - t)), child: c)),
    );
  }
}

// ====================================================================================================== page

/// Page frame: generous margins, left-aligned (the right side breathes), scrollable, every section revealed in turn.
class PageFrame extends StatefulWidget {
  const PageFrame({super.key, required this.children});
  final List<Widget> children;

  @override
  State<PageFrame> createState() => _PageFrameState();
}

class _PageFrameState extends State<PageFrame> {
  final _scroll = ScrollController();
  // bumped when the content changes size (a skeleton collapses, the window resizes), so a section brought into view
  // without a scroll is still revealed
  final _metrics = ValueNotifier<int>(0);
  late final Listenable _reveal = Listenable.merge([_scroll, _metrics]);

  @override
  void dispose() {
    _scroll.dispose();
    _metrics.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, box) {
      final pad = box.maxWidth < 600 ? AppSpacing.lg : box.maxWidth < 1000 ? AppSpacing.xxl : AppSpacing.page;
      return RevealScope(
        controller: _reveal,
        child: NotificationListener<ScrollMetricsNotification>(
          onNotification: (_) {
            _metrics.value++;
            return false;
          },
          child: ListView(
          controller: _scroll,
          padding: EdgeInsets.fromLTRB(pad, pad, pad, AppSpacing.section),
          children: [
            Align(
              alignment: Alignment.topLeft,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: AppLayout.maxWidth),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  for (var i = 0; i < widget.children.length; i++)
                    SectionReveal(order: i, child: widget.children[i]),
                ]),
              ),
            ),
          ],
          ),
        ),
      );
    });
  }
}

/// The opening of a page: a quiet eyebrow, the statement, one explanatory sentence.
class ResearchHeader extends StatelessWidget {
  const ResearchHeader({super.key, this.eyebrow, required this.title, this.sentence, this.style, this.trailing});
  final String? eyebrow;
  final String title;
  final String? sentence;
  final TextStyle? style;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final v2 = Design.current.isV2;
    return Padding(
      padding: EdgeInsets.only(bottom: v2 ? AppSpacing.xxl : AppSpacing.block),
      child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Expanded(
          child: Align(
            alignment: Alignment.bottomLeft,
            child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: AppLayout.margin + AppLayout.gutter + AppLayout.measure),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (eyebrow != null) v2 ? EyebrowPill(eyebrow!) : Eyebrow(eyebrow!),
              AccentHeadline(title, style: style ?? AppTypography.statement),
              if (sentence != null) ...[
                const SizedBox(height: AppSpacing.lg),
                ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: AppLayout.measure),
                    child: Text(sentence!, style: AppTypography.lede)),
              ],
            ]),
            ),
          ),
        ),
        if (trailing != null) trailing!,
      ]),
    );
  }
}

/// The one title of a page that has no statement of its own (tables, technical screens).
class PageHeader extends StatelessWidget {
  const PageHeader({super.key, required this.title, this.subtitle, this.trailing, this.eyebrow});
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final String? eyebrow;

  @override
  Widget build(BuildContext context) => ResearchHeader(
      eyebrow: eyebrow, title: title, sentence: subtitle, style: AppTypography.display, trailing: trailing);
}

/// Version 2 page eyebrow: a pill tag in tracked Space Mono capitals with a coral dot (read as written by screen
/// readers).
class EyebrowPill extends StatelessWidget {
  const EyebrowPill(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.lg + 2),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md + 2, vertical: 6),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadius.pill),
            border: Border.all(color: AppColors.border),
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            AccentDot(color: AppColors.primary),
            const SizedBox(width: AppSpacing.sm),
            Flexible(
              child: Text(text.toUpperCase(),
                  semanticsLabel: text, style: AppTypography.overline.copyWith(color: AppColors.textMuted)),
            ),
          ]),
        ),
      );
}

/// A Version 2 headline: Outfit, with one word set in Cormorant Garamond italic (the last word of four or more
/// letters). The text itself is unchanged; Version 1 shows it plainly.
class AccentHeadline extends StatelessWidget {
  const AccentHeadline(this.text, {super.key, required this.style});
  final String text;
  final TextStyle style;

  static (int, int)? accentRange(String text) {
    final words = RegExp(r"[A-Za-z][A-Za-z'’-]{3,}").allMatches(text).toList();
    if (words.length < 2) return null;
    final m = words.last;
    return (m.start, m.end);
  }

  @override
  Widget build(BuildContext context) {
    final r = Design.current.isV2 ? accentRange(text) : null;
    if (r == null) return Text(text, style: style);
    final italic = style.copyWith(
        fontFamily: AppFonts.accentSerif,
        fontFamilyFallback: const ['Georgia', 'serif'],
        fontStyle: FontStyle.italic,
        fontWeight: FontWeight.w400,
        letterSpacing: 0,
        fontSize: (style.fontSize ?? 40) * 1.08,
        color: AppColors.primary);
    return Text.rich(
      TextSpan(children: [
        TextSpan(text: text.substring(0, r.$1)),
        TextSpan(text: text.substring(r.$1, r.$2), style: italic),
        TextSpan(text: text.substring(r.$2)),
      ]),
      style: style,
    );
  }
}

/// Small sentence-case label above a block ("Industry signal").
class Eyebrow extends StatelessWidget {
  const Eyebrow(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.md),
        child: Text(text, style: AppTypography.overline),
      );
}

/// A stage of the report: its label sits in the margin column, its content in the reading column. Sections are
/// separated by whitespace, never by boxes. Below [AppLayout.stack] the label moves above the content.
class EditorialSection extends StatelessWidget {
  const EditorialSection({
    super.key,
    required this.label,
    this.title,
    this.intro,
    required this.child,
    this.aside,
    this.wide = false,
    this.spacing = AppSpacing.section,
  });

  final String label;
  final String? title;
  final String? intro;
  final Widget child;
  final Widget? aside; // under the label in the margin (e.g. a count)
  final bool wide; // content may use the full width instead of the reading measure
  final double spacing; // space below the section

  @override
  Widget build(BuildContext context) {
    if (Design.current.isV2) return _studio(context);
    return Padding(
      padding: EdgeInsets.only(bottom: spacing),
      child: LayoutBuilder(builder: (context, box) {
        final content = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (title != null) Text(title!, style: AppTypography.headline),
          if (intro != null) ...[
            if (title != null) const SizedBox(height: AppSpacing.sm),
            ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: AppLayout.measure),
                child: Text(intro!, style: AppTypography.muted)),
          ],
          if (title != null || intro != null) const SizedBox(height: AppSpacing.xl),
          child,
        ]);
        final margin = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: AppTypography.overline),
          if (aside != null) ...[const SizedBox(height: AppSpacing.sm), aside!],
        ]);
        if (box.maxWidth < AppLayout.stack) {
          return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [margin, const SizedBox(height: AppSpacing.md), content]);
        }
        return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: AppLayout.margin, child: Padding(padding: const EdgeInsets.only(top: 6), child: margin)),
          const SizedBox(width: AppLayout.gutter),
          Expanded(
            child: wide
                ? content
                : Align(
                    alignment: Alignment.topLeft,
                    child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: AppLayout.measure), child: content)),
          ),
        ]);
      }),
    );
  }

  /// Version 2: the stage is a card; its label (with an accent dot) and aside head the card, the content follows.
  Widget _studio(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(bottom: spacing == 0 ? 0 : AppSpacing.xxl),
      child: LayoutBuilder(builder: (context, box) {
        final narrow = box.maxWidth < 600;
        return StudioCard(
          padding: EdgeInsets.all(narrow ? AppSpacing.lg + 2 : 36),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
              const AccentRule(width: 16),
              const SizedBox(width: AppSpacing.sm),
              Expanded(child: Text(label, style: AppTypography.overline)),
              if (aside != null) aside!,
            ]),
            const SizedBox(height: AppSpacing.lg),
            if (title != null) Text(title!, style: AppTypography.headline),
            if (intro != null) ...[
              if (title != null) const SizedBox(height: AppSpacing.sm),
              ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: AppLayout.measure),
                  child: Text(intro!, style: AppTypography.muted)),
            ],
            if (title != null || intro != null) const SizedBox(height: AppSpacing.xl),
            wide
                ? child
                : ConstrainedBox(constraints: const BoxConstraints(maxWidth: AppLayout.measure + 160), child: child),
          ]),
        );
      }),
    );
  }
}

/// A number written into a sentence: "498 job postings provide the current evidence base."

class MetricStatement extends StatelessWidget {
  const MetricStatement({super.key, required this.value, required this.text, this.style});
  final dynamic value;
  final String text;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) {
    final s = style ?? AppTypography.display;
    return Text.rich(
      TextSpan(children: [
        TextSpan(text: fmtCount(value), style: s.copyWith(fontFeatures: const [FontFeature.tabularFigures()])),
        TextSpan(text: ' $text'),
      ]),
      style: s,
    );
  }
}

// ====================================================================================================== interaction

/// A text link whose underline grows on hover and keyboard focus. No button chrome.
class QuietLink extends StatefulWidget {
  const QuietLink(this.label, {super.key, required this.onTap, this.style, this.icon});
  final String label;
  final VoidCallback? onTap;
  final TextStyle? style;
  final IconData? icon; // optional trailing icon (e.g. a chevron that turns)

  @override
  State<QuietLink> createState() => _QuietLinkState();
}

class _QuietLinkState extends State<QuietLink> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) {
    final style = widget.style ?? AppTypography.link;
    return Semantics(
      button: true,
      child: InkWell(
        onTap: widget.onTap,
        onHover: (h) => setState(() => _hover = h),
        onFocusChange: (f) => setState(() => _hover = f),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
          child: IntrinsicWidth(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
              Row(mainAxisSize: MainAxisSize.min, children: [
                Flexible(child: Text(widget.label, style: style)),
                if (widget.icon != null) ...[
                  const SizedBox(width: AppSpacing.xs),
                  Icon(widget.icon, size: 16, color: style.color),
                ],
              ]),
              const SizedBox(height: 2),
              TweenAnimationBuilder<double>(
                tween: Tween(end: _hover ? 1 : 0),
                duration: AppMotion.fast,
                curve: AppMotion.curve,
                builder: (context, t, _) => Transform.scale(
                  scaleX: t,
                  alignment: Alignment.centerLeft,
                  child: Container(height: 1, color: (style.color ?? AppColors.primary).withValues(alpha: 0.8)),
                ),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Filters and view switches as quiet words; the active one is set in ink with a short brass rule that glides.
class SegmentTabs extends StatelessWidget {
  const SegmentTabs({super.key, required this.labels, required this.selected, required this.onSelect});
  final List<String> labels;
  final int selected;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    if (Design.current.isV2) return _segmentPills(this);
    return Wrap(spacing: AppSpacing.xl, runSpacing: AppSpacing.xs, children: [
      for (var i = 0; i < labels.length; i++)
        Semantics(
          selected: i == selected,
          button: true,
          child: InkWell(
            onTap: () => onSelect(i),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                AnimatedDefaultTextStyle(
                  duration: AppMotion.fast,
                  style: TextStyle(
                      fontFamily: AppFonts.body,
                      fontSize: 13.5,
                      height: 1.5,
                      fontWeight: FontWeight.w400,
                      color: i == selected ? AppColors.text : AppColors.textFaint),
                  child: Text(labels[i]),
                ),
                const SizedBox(height: 3),
                AnimatedContainer(
                  duration: AppMotion.normal,
                  curve: AppMotion.emphasized,
                  height: 1.5,
                  width: i == selected ? 18 : 0,
                  color: AppColors.primary,
                ),
              ]),
            ),
          ),
        ),
    ]);
  }
}

/// Version 2: a hairline track; the selected segment is set in ink (graphite on stone by day, pale stone at night).
Widget _segmentPills(SegmentTabs t) {
  final labels = t.labels, selected = t.selected, onSelect = t.onSelect;
  {
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(AppRadius.pill),
        border: Border.all(color: AppColors.border),
      ),
      child: Wrap(spacing: 2, runSpacing: 2, children: [
        for (var i = 0; i < labels.length; i++)
          Semantics(
            selected: i == selected,
            button: true,
            child: InkWell(
              onTap: () => onSelect(i),
              child: AnimatedContainer(
                duration: AppMotion.normal,
                curve: AppMotion.emphasized,
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md + 2, vertical: 6),
                decoration: BoxDecoration(
                  color: i == selected ? AppColors.text : Colors.transparent,
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                ),
                child: Text(labels[i],
                    style: TextStyle(
                        fontFamily: AppFonts.body,
                        fontSize: 12.5,
                        height: 1.4,
                        letterSpacing: 0.4,
                        fontWeight: i == selected ? FontWeight.w600 : FontWeight.w500,
                        color: i == selected ? AppColors.bg0 : AppColors.textMuted)),
              ),
            ),
          ),
      ]),
    );
  }
}

/// The same quiet control, named for its use as a filter.
typedef QuietFilter = SegmentTabs;

/// Progressive disclosure: a quiet toggle; the content expands from it (size and fade together). Collapsed content
/// is not built at all.
class EvidenceDisclosure extends StatefulWidget {
  const EvidenceDisclosure(
      {super.key, required this.title, this.summary, required this.children, this.initiallyExpanded = false, this.openTitle});
  final String title;
  final String? openTitle; // label while open (e.g. "Hide evidence")
  final String? summary;
  final List<Widget> children;
  final bool initiallyExpanded;

  @override
  State<EvidenceDisclosure> createState() => _EvidenceDisclosureState();
}

class _EvidenceDisclosureState extends State<EvidenceDisclosure> {
  late bool _open = widget.initiallyExpanded;

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Semantics(
        expanded: _open,
        child: InkWell(
          onTap: () => setState(() => _open = !_open),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
            child: Row(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Flexible(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                  Text(_open && widget.openTitle != null ? widget.openTitle! : widget.title, style: AppTypography.link),
                  if (widget.summary != null) Text(widget.summary!, style: AppTypography.caption),
                ]),
              ),
              const SizedBox(width: AppSpacing.xs),
              AnimatedRotation(
                turns: _open ? 0.5 : 0,
                duration: AppMotion.normal,
                curve: AppMotion.emphasized,
                child: Padding(
                  padding: EdgeInsets.only(top: 2),
                  child: Icon(Icons.expand_more, size: 18, color: AppColors.primary),
                ),
              ),
            ]),
          ),
        ),
      ),
      AnimatedSize(
        duration: AppMotion.normal,
        curve: AppMotion.resize,
        alignment: Alignment.topLeft,
        child: _open
            ? FadeInOnce(
                child: Padding(
                  padding: const EdgeInsets.only(top: AppSpacing.sm, bottom: AppSpacing.lg),
                  child: Design.current.isV2
                      ? StudioCard(
                          sunken: true,
                          padding: const EdgeInsets.all(AppSpacing.lg),
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: widget.children))
                      : Column(crossAxisAlignment: CrossAxisAlignment.start, children: widget.children),
                ),
              )
            : const SizedBox(width: double.infinity),
      ),
    ]);
  }
}

/// The older name of [EvidenceDisclosure] (same behaviour).
class EvidencePanel extends StatelessWidget {
  const EvidencePanel({super.key, required this.title, this.summary, required this.children, this.initiallyExpanded = false});
  final String title;
  final String? summary;
  final List<Widget> children;
  final bool initiallyExpanded;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: AppSpacing.sm),
        child: EvidenceDisclosure(title: title, summary: summary, initiallyExpanded: initiallyExpanded, children: children),
      );
}

// ====================================================================================================== the trail

/// One stage of an evidence trail.
class TrailStepData {
  const TrailStepData({
    required this.label,
    required this.headline,
    this.caption,
    this.lines = const [],
    this.quotes = const [],
    this.established = true,
    this.onTap,
    this.expanded = false,
    this.details = const [],
  });

  final String label; // margin label ("Industry")
  final String headline; // what the stage establishes ("23 of 498 postings")
  final String? caption; // one quiet line under the headline
  final List<String> lines; // evidence lines
  final List<String> quotes; // verbatim excerpts, set as quotations
  final bool established; // false: the link is not established by the evidence
  final VoidCallback? onTap; // a stage that opens to its evidence
  final bool expanded;
  final List<String> details; // shown while expanded
}

/// The signature device: a thin vertical line in the margin that connects the stages of a chain of evidence and
/// draws itself downward, stage by stage. A stage the evidence cannot establish is drawn hollow, its line faint.
class Trail extends StatefulWidget {
  const Trail({super.key, required this.steps, this.animate = true, this.compact = false});
  final List<TrailStepData> steps;
  final bool animate;
  final bool compact; // tighter spacing (inside a list item)

  @override
  State<Trail> createState() => _TrailState();
}

class _TrailState extends State<Trail> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: AppMotion.trail * 1.6);

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!widget.animate || AppMotion.reduced(context)) {
      _c.value = 1;
    } else if (_c.value == 0 && !_c.isAnimating) {
      _c.forward();
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  Animation<double> _phase(int i, double from, double to) {
    final n = widget.steps.length;
    final a = (i + from) / n, b = (i + to) / n;
    // a lightweight view of the one controller: no listeners are registered until it is listened to
    return _c.drive(CurveTween(curve: Interval(a.clamp(0.0, 1.0), b.clamp(0.0, 1.0), curve: AppMotion.emphasized)));
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, box) {
      final withMargin = box.maxWidth >= AppLayout.stack;
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (var i = 0; i < widget.steps.length; i++)
          _step(i, widget.steps[i], last: i == widget.steps.length - 1, withMargin: withMargin,
              contentWidth: _contentWidth(box.maxWidth, withMargin)),
      ]);
    });
  }

  /// The reading width of a stage's text: what is left after the margin label and the rail, at most one measure.
  /// It is given to the stage as a fixed width so the row's intrinsic height is measured at the width the text is
  /// laid out at (a narrower layout than measurement would wrap more lines than the rail was sized for).
  static double _contentWidth(double maxWidth, bool withMargin) {
    const rail = 28.0 + AppSpacing.lg;
    final available = (maxWidth.isFinite ? maxWidth : AppLayout.maxWidth) - rail - (withMargin ? AppLayout.margin : 0);
    return available.clamp(0.0, AppLayout.measure);
  }

  Widget _step(int i, TrailStepData s,
      {required bool last, required bool withMargin, required double contentWidth}) {
    final appear = _phase(i, 0, 0.6);
    final grow = _phase(i, 0.4, 1.0);
    final ink = s.established ? AppColors.primary : AppColors.border;
    final head = s.onTap == null
        ? Text(s.headline, style: AppTypography.title)
        : Semantics(
            button: true,
            expanded: s.expanded,
            label: '${s.label}: ${s.headline}. ${s.expanded ? 'Hide' : 'Show'} the evidence',
            child: InkWell(onTap: s.onTap, child: Text(s.headline, style: AppTypography.title.copyWith(
                decoration: TextDecoration.underline,
                decorationColor: (s.expanded ? AppColors.primary : AppColors.border),
                decorationThickness: 1))),
          );
    final content = Padding(
      padding: EdgeInsets.only(bottom: last ? 0 : (widget.compact ? AppSpacing.xl : AppSpacing.xxl)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (!withMargin) Text(s.label, style: AppTypography.overline),
        head,
        if (s.caption != null) Text(s.caption!, style: AppTypography.muted),
        if (!s.established && s.lines.isEmpty)
          Text('Evidence is insufficient to establish this relationship.', style: AppTypography.caption),
        for (final q in s.quotes)
          Padding(padding: const EdgeInsets.only(top: AppSpacing.sm), child: Text('“$q”', style: AppTypography.quote)),
        for (final l in s.lines)
          Padding(padding: const EdgeInsets.only(top: AppSpacing.xs), child: Text(l, style: AppTypography.muted)),
        AnimatedSize(
          duration: AppMotion.normal,
          curve: AppMotion.resize,
          alignment: Alignment.topLeft,
          child: s.expanded && s.details.isNotEmpty
              ? FadeInOnce(
                  child: Padding(
                    padding: const EdgeInsets.only(top: AppSpacing.sm),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      for (final d in s.details)
                        Padding(padding: const EdgeInsets.only(top: 2), child: Text(d, style: AppTypography.body)),
                    ]),
                  ),
                )
              : const SizedBox(width: double.infinity),
        ),
      ]),
    );
    final rail = SizedBox(
      width: 28,
      child: Column(children: [
        const SizedBox(height: 9),
        FadeTransition(
          opacity: appear,
          child: Container(
            width: 9,
            height: 9,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: s.established ? AppColors.primary : Colors.transparent,
              border: Border.all(color: ink, width: 1.2),
            ),
          ),
        ),
        if (!last)
          Expanded(
            child: AnimatedBuilder(
              animation: grow,
              builder: (context, _) => Transform.scale(
                scaleY: grow.value,
                alignment: Alignment.topCenter,
                child: Container(width: 1, color: s.established ? AppColors.primary.withValues(alpha: 0.55) : AppColors.border),
              ),
            ),
          ),
      ]),
    );
    return IntrinsicHeight(
      child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (withMargin)
          SizedBox(
            width: AppLayout.margin,
            child: FadeTransition(
              opacity: appear,
              child: Padding(
                padding: const EdgeInsets.only(top: 4, right: AppSpacing.lg),
                child: Text(s.label, style: AppTypography.overline, textAlign: TextAlign.right),
              ),
            ),
          ),
        rail,
        const SizedBox(width: AppSpacing.lg),
        SizedBox(width: contentWidth, child: FadeTransition(opacity: appear, child: content)),
      ]),
    );
  }
}

/// One link of an evidence chain in a compact list (kept for the older call sites; drawn as a trail stage).
class EvidenceStep extends StatelessWidget {
  const EvidenceStep({super.key, required this.label, required this.child, this.last = false});
  final String label;
  final Widget child;
  final bool last;

  @override
  Widget build(BuildContext context) {
    return IntrinsicHeight(
      child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        SizedBox(
          width: 20,
          child: Column(children: [
            Container(
                width: 7,
                height: 7,
                margin: const EdgeInsets.only(top: 7),
                decoration: BoxDecoration(color: AppColors.primary, shape: BoxShape.circle)),
            if (!last) Expanded(child: Container(width: 1, color: AppColors.primary.withValues(alpha: 0.45))),
          ]),
        ),
        const SizedBox(width: AppSpacing.md),
        Expanded(
          child: Padding(
            padding: EdgeInsets.only(bottom: last ? 0 : AppSpacing.lg),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label, style: AppTypography.overline),
              const SizedBox(height: 2),
              child,
            ]),
          ),
        ),
      ]),
    );
  }
}

// ====================================================================================================== lists

/// One entry of an editorial list: an index in the margin, a name, a reading, its evidence, a quiet state, one action,
/// and content that unfolds in place. Entries are separated by whitespace.
class InsightItem extends StatefulWidget {
  const InsightItem({
    super.key,
    this.index,
    this.kicker,
    required this.title,
    this.reading,
    this.evidence = const [],
    this.state,
    this.action,
    this.open = false,
    this.onToggle,
    this.openContent,
    this.footer,
  });

  final int? index;
  final String? kicker; // small label above the name ("Expand existing topic")
  final String title;
  final String? reading; // the interpretation, one or two sentences
  final List<MapEntry<String, String>> evidence; // label -> fact
  final String? state; // a status code shown as a quiet dot + words
  final String? action; // e.g. "View evidence →"
  final bool open;
  final VoidCallback? onToggle;
  final Widget? openContent;
  final Widget? footer;

  @override
  State<InsightItem> createState() => _InsightItemState();
}

class _InsightItemState extends State<InsightItem> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) {
    final active = _hover || widget.open;
    return MouseRegion(
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.block),
        child: LayoutBuilder(builder: (context, box) {
          final withMargin = box.maxWidth >= AppLayout.stack;
          final idx = widget.index == null
              ? null
              : AnimatedDefaultTextStyle(
                  duration: AppMotion.fast,
                  style: AppTypography.index.copyWith(color: active ? AppColors.primary : AppColors.textFaint),
                  child: Text(widget.index.toString().padLeft(2, '0')),
                );
          final body = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (!withMargin && idx != null) idx,
            if (widget.kicker != null)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                child: Text(widget.kicker!, style: AppTypography.overline.copyWith(color: AppColors.primary)),
              ),
            Text(widget.title, style: AppTypography.headline),
            if (widget.reading != null) ...[
              const SizedBox(height: AppSpacing.sm),
              ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: AppLayout.measure),
                  child: Text(widget.reading!, style: AppTypography.body.copyWith(color: AppColors.textMuted))),
            ],
            if (widget.evidence.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.md),
              for (final e in widget.evidence)
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Text.rich(TextSpan(children: [
                    TextSpan(text: '${e.key}   ', style: AppTypography.caption),
                    TextSpan(text: e.value, style: AppTypography.muted.copyWith(color: AppColors.text)),
                  ])),
                ),
            ],
            if (widget.state != null || widget.action != null) ...[
              const SizedBox(height: AppSpacing.md),
              Wrap(spacing: AppSpacing.xl, runSpacing: AppSpacing.xs, crossAxisAlignment: WrapCrossAlignment.center, children: [
                if (widget.state != null) StatusBadge(widget.state!),
                if (widget.action != null) QuietLink(widget.action!, onTap: widget.onToggle),
              ]),
            ],
            if (widget.footer != null) widget.footer!,
            AnimatedSize(
              duration: AppMotion.normal,
              curve: AppMotion.resize,
              alignment: Alignment.topLeft,
              child: widget.open && widget.openContent != null
                  ? FadeInOnce(
                      child: Padding(
                          padding: const EdgeInsets.only(top: AppSpacing.xl), child: widget.openContent!))
                  : const SizedBox(width: double.infinity),
            ),
          ]);
          if (!withMargin) return body;
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(
              width: AppLayout.margin,
              child: Padding(padding: const EdgeInsets.only(top: 2), child: idx ?? const SizedBox.shrink()),
            ),
            const SizedBox(width: AppLayout.gutter),
            Expanded(child: body),
          ]);
        }),
      ),
    );
  }
}

// ====================================================================================================== statuses

/// A status in words: a small dot in the tone's colour and the human label; the technical code in the tooltip.
class StatusBadge extends StatelessWidget {
  const StatusBadge(this.value, {super.key, this.dense = false});
  final String value;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final tone = StatusStyle.toneOf(value);
    final color = StatusStyle.color(tone);
    final label = StatusStyle.label(value);
    final text = Text.rich(
          TextSpan(children: [
            WidgetSpan(
              alignment: PlaceholderAlignment.middle,
              // Version 2: a running analysis breathes
              child: Design.current.isV2 && const {'ANALYSIS_PENDING', 'RUNNING', 'IN_PROGRESS'}.contains(value)
                  ? Padding(padding: const EdgeInsets.only(right: 3), child: PulseDot(color: color))
                  : Container(
                      width: 6,
                      height: 6,
                      margin: const EdgeInsets.only(right: 7),
                      decoration: BoxDecoration(color: color, shape: BoxShape.circle),
                    ),
            ),
            TextSpan(text: label),
          ]),
          style: TextStyle(
              fontFamily: AppFonts.body,
              color: Design.current.isV2 ? AppColors.text : AppColors.textMuted,
              fontSize: dense ? 12.5 : 13.5,
              height: 1.4,
              fontWeight: Design.current.isV2 ? FontWeight.w500 : FontWeight.w400),
        );
    return Tooltip(
      message: value,
      child: Semantics(
        label: 'status $label',
        // Version 2: the same dot and words inside a 1px frame
        child: Design.current.isV2
            ? Container(
                padding: EdgeInsets.symmetric(horizontal: dense ? 9 : 11, vertical: dense ? 2 : 4),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                  border: Border.all(color: AppColors.border),
                ),
                child: text,
              )
            : text,
      ),
    );
  }
}

/// A status statement at the top of a page (e.g. peer data): the state in words, then what it means.
class StatusBanner extends StatelessWidget {
  const StatusBanner({super.key, required this.status, required this.title, this.body, this.children = const []});
  final String status;
  final String title;
  final String? body;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xl),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        StatusBadge(status),
        const SizedBox(height: AppSpacing.sm),
        Text(title, style: AppTypography.headline),
        if (body != null) ...[
          const SizedBox(height: AppSpacing.sm),
          ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: AppLayout.measure), child: Text(body!, style: AppTypography.muted)),
        ],
        ...children,
      ]),
    );
  }
}

/// A titled block: the title in the serif, a quiet subtitle, then content. Whitespace, not a box.
class SectionCard extends StatelessWidget {
  const SectionCard({super.key, required this.title, this.subtitle, this.trailing, required this.child, this.padding});
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final Widget child;
  final EdgeInsets? padding;

  @override
  Widget build(BuildContext context) {
    final body = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: AppTypography.title),
              if (subtitle != null) ...[const SizedBox(height: AppSpacing.xs), Text(subtitle!, style: AppTypography.caption)],
            ]),
          ),
          if (trailing != null) trailing!,
        ]),
        const SizedBox(height: AppSpacing.lg),
        Padding(padding: padding ?? EdgeInsets.zero, child: child),
      ]);
    return Padding(
      padding: EdgeInsets.only(bottom: Design.current.isV2 ? AppSpacing.xl : AppSpacing.block),
      child: Design.current.isV2 ? StudioCard(child: body) : body,
    );
  }
}

/// A figure: a serif numeral and what it counts (the scope is part of the label). No box, no rule.
class KpiCard extends StatelessWidget {
  const KpiCard({super.key, required this.value, required this.label, this.caption, this.source, this.icon});
  final dynamic value;
  final String label;
  final String? caption;
  final String? source;
  final IconData? icon; // kept for API compatibility; figures do not use icons

  @override
  Widget build(BuildContext context) {
    final figure = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(fmtCount(value), style: AppTypography.metric),
        const SizedBox(height: AppSpacing.xs),
        Text(label, style: AppTypography.muted),
        if (caption != null) Text(caption!, style: AppTypography.caption, maxLines: 3, overflow: TextOverflow.ellipsis),
        if (source != null) Text(source!, style: AppTypography.caption, maxLines: 1, overflow: TextOverflow.ellipsis),
      ]);
    return SizedBox(
      width: 200,
      child: Design.current.isV2 ? StudioCard(padding: const EdgeInsets.all(AppSpacing.lg + 2), child: figure) : figure,
    );
  }
}

/// Counts written as a line of text: "106 companies   475 distinct job titles".
class InlineFigures extends StatelessWidget {
  const InlineFigures(this.items, {super.key});
  final List<MapEntry<dynamic, String>> items; // value -> scope label

  @override
  Widget build(BuildContext context) {
    return Wrap(spacing: AppSpacing.xxl, runSpacing: AppSpacing.sm, children: [
      for (final e in items)
        Text.rich(TextSpan(children: [
          TextSpan(text: fmtCount(e.key), style: AppTypography.metricSmall),
          TextSpan(text: '  ${e.value}', style: AppTypography.muted),
        ])),
    ]);
  }
}

/// The scope of a table or analysis in one quiet paragraph.
class ScopeBanner extends StatelessWidget {
  const ScopeBanner({super.key, required this.title, required this.facts, this.note, this.status});
  final String title;
  final List<String> facts;
  final String? note;
  final String? status;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xl),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: AppLayout.measure),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(title, style: AppTypography.overline)),
            if (status != null) StatusBadge(status!, dense: true),
          ]),
          const SizedBox(height: AppSpacing.xs),
          Text(facts.where((f) => f.isNotEmpty).join('; '), style: AppTypography.muted),
          if (note != null) ...[const SizedBox(height: AppSpacing.xs), Text(note!, style: AppTypography.caption)],
        ]),
      ),
    );
  }
}

// ====================================================================================================== states

/// Static skeleton block (no infinite animation, so layouts do not jump and tests can settle).
class SkeletonBlock extends StatelessWidget {
  const SkeletonBlock({super.key, this.width, this.height = 14});
  final double? width;
  final double height;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(AppRadius.sm)),
    );
  }
}

class SkeletonPage extends StatelessWidget {
  const SkeletonPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Loading',
      // shrink-wrapped and non-scrolling so a loading ApiView can also sit inside a scrolling page
      child: ListView(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.page),
          children: [
            const SkeletonBlock(width: 140, height: 12),
            const SizedBox(height: AppSpacing.lg),
            const SkeletonBlock(width: 520, height: 40),
            const SizedBox(height: AppSpacing.lg),
            const SkeletonBlock(width: 600, height: 14),
            const SizedBox(height: AppSpacing.section),
            for (var i = 0; i < 4; i++)
              const Padding(padding: EdgeInsets.only(bottom: AppSpacing.xl), child: SkeletonBlock(width: 680, height: 14)),
          ]),
    );
  }
}

/// An empty result explained in words (no illustration).
class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.title, required this.body, this.icon = Icons.inbox_outlined, this.action});
  final String title;
  final String body;
  final IconData icon; // kept for API compatibility
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.topLeft,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.xl),
          child: _frame(Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Text(title, style: AppTypography.title),
            const SizedBox(height: AppSpacing.sm),
            Text(body, style: AppTypography.muted),
            if (action != null) ...[const SizedBox(height: AppSpacing.lg), action!],
          ])),
        ),
      ),
    );
  }
}

Widget _frame(Widget child) => Design.current.isV2 ? StudioCard(child: child) : child;

/// What happened, why, and what the reader can do -- set as prose, not as a card. The original backend text is not
/// shown here; it belongs in the page's technical details.
class ExplanationText extends StatelessWidget {
  const ExplanationText(this.e, {super.key, this.showTechnical = false});
  final Explanation e;
  final bool showTechnical;

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(e.what, style: AppTypography.lede),
      for (final w in e.why)
        Padding(padding: const EdgeInsets.only(top: AppSpacing.xs), child: Text(w, style: AppTypography.body)),
      if (e.actions.isNotEmpty) ...[
        const SizedBox(height: AppSpacing.md),
        Text('What you can do', style: AppTypography.overline),
        for (final a in e.actions)
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Text('• $a', style: AppTypography.body),
          ),
      ],
      if (showTechnical && e.technical != null && e.technical!.isNotEmpty)
        EvidencePanel(title: 'Technical details', children: [SelectableText(e.technical!, style: AppTypography.mono)]),
    ]);
  }
}

/// A failed request in human words; the technical detail is one line below, never a stack trace.
class ErrorState extends StatelessWidget {
  const ErrorState({super.key, required this.what, required this.error, required this.onRetry});
  final String what;
  final Object? error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final e = error;
    final ex = e is ApiException
        ? Plain.error(e, what, statusCode: e.statusCode, code: e.code, message: e.message)
        : Plain.error(e, what);
    final technical = [
      if (ex.technical != null) ex.technical!,
      if (e is ApiException && e.requestId != null) 'request ${e.requestId}',
    ].join(' · ');
    return EmptyState(
      title: ex.what,
      body: ex.why.join(' '),
      action: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        OutlinedButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh, size: 16), label: const Text('Retry')),
        if (technical.isNotEmpty)
          EvidencePanel(title: 'Technical details', children: [SelectableText(technical, style: AppTypography.mono)]),
      ]),
    );
  }
}

/// Not produced (NOT_PRODUCED / BLOCKED / NOT_LOADED) with the backend's reason.
class DataNotAvailable extends StatelessWidget {
  const DataNotAvailable({super.key, required this.state, this.reason, this.onReload});
  final String state;
  final String? reason;
  final VoidCallback? onReload;

  @override
  Widget build(BuildContext context) {
    return EmptyState(
      title: state == 'BLOCKED' ? 'This analysis could not run yet' : 'Not available for this analysis',
      body: reason == null ? 'This part of the analysis was not produced.' : Plain.sentence(reason),
      action: onReload == null ? null : OutlinedButton(onPressed: onReload, child: const Text('Reload')),
    );
  }
}

/// Loads one endpoint and renders loading (skeleton), error (retry), not-produced and data states, crossfading.
class ApiView extends StatefulWidget {
  const ApiView({super.key, required this.api, required this.path, required this.what, required this.builder, this.query});
  final ApiClient api;
  final String path;
  final String what;
  final Map<String, String>? query;
  final Widget Function(BuildContext context, Map<String, dynamic> data, VoidCallback reload) builder;

  @override
  State<ApiView> createState() => _ApiViewState();
}

class _ApiViewState extends State<ApiView> {
  late Future<dynamic> _future;

  @override
  void initState() {
    super.initState();
    _future = _fetch();
  }

  @override
  void didUpdateWidget(covariant ApiView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.path != widget.path || jsonEncode(oldWidget.query) != jsonEncode(widget.query)) {
      _future = _fetch();
    }
  }

  Future<dynamic> _fetch() => widget.api.getJson(widget.path, query: widget.query);

  void _reload() {
    setState(() {
      _future = _fetch();
    });
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<dynamic>(
      future: _future,
      builder: (context, snap) {
        Widget child;
        if (snap.connectionState == ConnectionState.waiting) {
          child = const SkeletonPage(key: ValueKey('loading'));
        } else if (snap.hasError) {
          child = ErrorState(key: const ValueKey('error'), what: widget.what, error: snap.error, onRetry: _reload);
        } else if (snap.data is! Map<String, dynamic>) {
          child = EmptyState(
              key: const ValueKey('unexpected'),
              title: 'Unexpected response',
              body: 'The backend returned no JSON object for ${widget.path}.');
        } else {
          final data = snap.data as Map<String, dynamic>;
          final state = (data['evidence_state'] ?? 'AVAILABLE').toString();
          if (state == 'NOT_PRODUCED' || state == 'BLOCKED' || state == 'NOT_LOADED') {
            child = DataNotAvailable(
                key: const ValueKey('not-produced'), state: state, reason: data['reason']?.toString(), onReload: _reload);
          } else {
            child = KeyedSubtree(key: const ValueKey('data'), child: widget.builder(context, data, _reload));
          }
        }
        return AnimatedSwitcher(duration: AppMotion.normal, switchInCurve: AppMotion.curve, child: child);
      },
    );
  }
}

// ====================================================================================================== quiet data

/// Horizontal bars as thin rules: each bar is value / max of the rows shown (units stated by the caller).
class BarList extends StatelessWidget {
  const BarList({super.key, required this.rows, required this.unit, this.maxValue, this.tone = Tone.neutral});
  final List<BarRow> rows;
  final String unit;
  final num? maxValue;
  final Tone tone;

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) {
      return Text('No rows.', style: AppTypography.muted);
    }
    final max = maxValue ?? rows.map((r) => r.value).fold<num>(0, (a, b) => a > b ? a : b);
    final color = tone == Tone.neutral ? AppColors.textFaint : StatusStyle.color(tone);
    return Column(children: [
      for (final r in rows)
        Tooltip(
          message: '${r.label}: ${fmt(r.value)} $unit${r.detail != null ? ' · ${r.detail}' : ''}',
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 7),
            child: Row(children: [
              SizedBox(
                  width: 200,
                  child: Text(r.label, style: AppTypography.body, maxLines: 1, overflow: TextOverflow.ellipsis)),
              const SizedBox(width: AppSpacing.lg),
              Expanded(
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: FractionallySizedBox(
                    widthFactor: max <= 0 ? 0 : (r.value / max).clamp(0.0, 1.0).toDouble(),
                    child: Container(height: 2, color: color),
                  ),
                ),
              ),
              const SizedBox(width: AppSpacing.lg),
              SizedBox(
                  width: 96,
                  child: Text('${fmt(r.value)} $unit',
                      style: AppTypography.caption, textAlign: TextAlign.right)),
            ]),
          ),
        ),
    ]);
  }
}

class BarRow {
  const BarRow(this.label, this.value, {this.detail});
  final String label;
  final num value;
  final String? detail;
}

/// A distribution of categorical counts as one thin line + a legend in words (never colour alone).
class DistributionBar extends StatelessWidget {
  const DistributionBar({super.key, required this.counts, this.order});
  final Map<String, dynamic> counts;
  final List<String>? order;

  @override
  Widget build(BuildContext context) {
    final keys = (order ?? counts.keys.toList()).where((k) => counts[k] is num && (counts[k] as num) > 0).toList();
    final total = keys.fold<num>(0, (a, k) => a + (counts[k] as num));
    if (total == 0) return Text('No values.', style: AppTypography.muted);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        for (var i = 0; i < keys.length; i++)
          Expanded(
            flex: ((counts[keys[i]] as num) * 1000 ~/ total).clamp(1, 1000).toInt(),
            child: Tooltip(
              message: '${StatusStyle.label(keys[i])}: ${counts[keys[i]]} of $total',
              child: Container(
                  height: 3,
                  margin: EdgeInsets.only(right: i == keys.length - 1 ? 0 : 3),
                  color: StatusStyle.color(StatusStyle.toneOf(keys[i]))),
            ),
          ),
      ]),
      const SizedBox(height: AppSpacing.md),
      Wrap(spacing: AppSpacing.xl, runSpacing: AppSpacing.xs, children: [
        for (final k in keys)
          Text.rich(TextSpan(children: [
            TextSpan(text: '${counts[k]} ', style: AppTypography.metricSmall),
            TextSpan(text: StatusStyle.label(k).toLowerCase(), style: AppTypography.muted),
          ])),
      ]),
    ]);
  }
}

class KeyValueList extends StatelessWidget {
  const KeyValueList(this.pairs, {super.key, this.labelWidth = 170});
  final List<MapEntry<String, dynamic>> pairs;
  final double labelWidth;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, box) {
      final lw = box.maxWidth < 480 ? box.maxWidth * 0.4 : labelWidth;
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final p in pairs)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 5),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(width: lw, child: Padding(padding: const EdgeInsets.only(top: 2), child: Text(p.key, style: AppTypography.caption))),
              Expanded(
                child: p.value is String && StatusStyle.isKnown(p.value as String)
                    ? Align(alignment: Alignment.centerLeft, child: StatusBadge(p.value as String, dense: true))
                    : SelectableText(p.value is String || p.value is List ? Plain.value(p.value, fallback: fmt) : fmt(p.value),
                        style: AppTypography.muted.copyWith(color: AppColors.text)),
              ),
            ]),
          ),
      ]);
    });
  }
}

/// Two columns in a given proportion (e.g. 40/60) that stack on narrow screens.
class SplitRow extends StatelessWidget {
  const SplitRow({super.key, required this.left, required this.right, this.leftFlex = 4, this.rightFlex = 6, this.breakpoint = 860});
  final Widget left;
  final Widget right;
  final int leftFlex;
  final int rightFlex;
  final double breakpoint;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, box) {
      if (box.maxWidth < breakpoint) {
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [left, const SizedBox(height: AppSpacing.xl), right]);
      }
      return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(flex: leftFlex, child: left),
        const SizedBox(width: AppSpacing.xxl),
        Expanded(flex: rightFlex, child: right),
      ]);
    });
  }
}

/// A count that rises from zero to its real value once, when it first appears (instant with reduced motion).
/// Non-numeric values are shown as they are.
class AnimatedCount extends StatelessWidget {
  const AnimatedCount(this.value, {super.key, this.style});
  final dynamic value;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) {
    final v = value;
    if (v is! num) return Text(fmtCount(v), style: style);
    final reduce = AppMotion.reduced(context);
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: reduce ? v.toDouble() : 0, end: v.toDouble()),
      duration: reduce ? Duration.zero : AppMotion.page,
      curve: AppMotion.curve,
      builder: (context, x, _) => Text(fmtCount(v is int ? x.round() : x), style: style, semanticsLabel: fmtCount(v)),
    );
  }
}
