import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../theme/design_system.dart';
import '../widgets/ui_kit.dart';

/// Appearance: the two visual designs, the light / dark mode, and the design finalised for this workspace.
///
/// The choice is stored by the analysis service (GET / POST /api/v1/settings/appearance), so it survives reloads
/// and is the same on every device. It changes only how the app looks; no analysis is affected. When the service
/// cannot be reached the choice still applies in this window, and the panel says it was not saved.
class Appearance {
  Appearance._();
  static const path = '/api/v1/settings/appearance';

  /// Apply the stored choice (silently keeps the current design when the service has none or is unreachable).
  static Future<void> load(ApiClient api) async {
    try {
      final r = await api.getJson(path);
      if (r is! Map) return;
      Design.current.set(
        version: designVersionOf(r['version']),
        brightness: r['theme'] == 'light' ? Brightness.light : r['theme'] == 'dark' ? Brightness.dark : null,
        finalised: designVersionOf(r['finalised']),
        finalisedAt: r['finalised_at']?.toString(),
      );
    } catch (_) {
      // not stored or unreachable: the default design stays
    }
  }

  /// Store the current choice; true when the service saved it.
  static Future<bool> save(ApiClient api, {bool finalise = false, bool clearFinal = false}) async {
    final d = Design.current;
    try {
      final r = await api.postJson(path, {
        'version': d.version.name,
        'theme': d.isDark ? 'dark' : 'light',
        if (finalise) 'finalise': true,
        if (clearFinal) 'clear_final': true,
      });
      if (r is Map) {
        d.set(finalised: designVersionOf(r['finalised']), finalisedAt: r['finalised_at']?.toString(),
            clearFinal: r['finalised'] == null);
      }
      return true;
    } catch (_) {
      if (finalise) d.set(finalised: d.version);
      if (clearFinal) d.set(clearFinal: true);
      return false;
    }
  }

  static Future<bool> toggleMode(ApiClient api) {
    final d = Design.current;
    d.set(brightness: d.isDark ? Brightness.light : Brightness.dark);
    return save(api);
  }
}

/// Opens the Appearance panel from the right edge.
Future<void> showAppearancePanel(BuildContext context, ApiClient api) {
  return showGeneralDialog(
    context: context,
    barrierDismissible: true,
    barrierLabel: 'Close appearance',
    barrierColor: Colors.black.withValues(alpha: 0.35),
    transitionDuration: AppMotion.reduced(context) ? Duration.zero : AppMotion.normal,
    pageBuilder: (context, _, __) => Align(alignment: Alignment.centerRight, child: AppearancePanel(api: api)),
    transitionBuilder: (context, anim, _, child) => SlideTransition(
      position: Tween(begin: const Offset(0.08, 0), end: Offset.zero)
          .animate(CurvedAnimation(parent: anim, curve: AppMotion.emphasized)),
      child: FadeTransition(opacity: anim, child: child),
    ),
  );
}

class AppearancePanel extends StatefulWidget {
  const AppearancePanel({super.key, required this.api});
  final ApiClient api;

  @override
  State<AppearancePanel> createState() => _AppearancePanelState();
}

class _AppearancePanelState extends State<AppearancePanel> {
  bool? _saved; // null: nothing saved yet in this panel

  @override
  void initState() {
    super.initState();
    Design.current.addListener(_changed);
  }

  @override
  void dispose() {
    Design.current.removeListener(_changed);
    super.dispose();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  Future<void> _apply({DesignVersion? version, Brightness? brightness, bool finalise = false, bool clearFinal = false}) async {
    Design.current.set(version: version, brightness: brightness);
    final ok = await Appearance.save(widget.api, finalise: finalise, clearFinal: clearFinal);
    if (mounted) setState(() => _saved = ok);
  }

  @override
  Widget build(BuildContext context) {
    final d = Design.current;
    final width = math.min(MediaQuery.sizeOf(context).width - 24, 460.0);
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Material(
        color: AppColors.bg1,
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(4), side: BorderSide(color: AppColors.border)),
        clipBehavior: Clip.antiAlias,
        child: SizedBox(
          width: width,
          height: double.infinity,
          child: ListView(padding: const EdgeInsets.all(AppSpacing.xl), children: [
            Row(children: [
              Expanded(child: Text('Appearance', style: AppTypography.headline)),
              IconButton(
                  tooltip: 'Close appearance',
                  icon: const Icon(Icons.close, size: 20),
                  onPressed: () => Navigator.of(context).maybePop()),
            ]),
            const SizedBox(height: AppSpacing.xs),
            Text('Compare the two designs on any page, then finalise the one to keep. Every page shows the same '
                'content in both; only the look changes.', style: AppTypography.muted),
            const SizedBox(height: AppSpacing.xl),
            Text('Design', style: AppTypography.overline),
            const SizedBox(height: AppSpacing.md),
            for (final v in DesignVersion.values) ...[
              _DesignChoice(
                version: v,
                brightness: d.brightness,
                selected: d.version == v,
                finalised: d.finalised == v,
                onTap: () => _apply(version: v),
              ),
              const SizedBox(height: AppSpacing.md),
            ],
            const SizedBox(height: AppSpacing.md),
            Text('Mode', style: AppTypography.overline),
            const SizedBox(height: AppSpacing.md),
            SegmentTabs(
              labels: const ['Dark', 'Light'],
              selected: d.isDark ? 0 : 1,
              onSelect: (i) => _apply(brightness: i == 0 ? Brightness.dark : Brightness.light),
            ),
            const SizedBox(height: AppSpacing.xxl),
            Text('Final design', style: AppTypography.overline),
            const SizedBox(height: AppSpacing.md),
            ..._finalSection(d),
            if (_saved != null) ...[
              const SizedBox(height: AppSpacing.lg),
              Text(
                  _saved!
                      ? 'Saved. The workspace opens in this design on every device.'
                      : 'Could not save the choice (the analysis service is unreachable); it applies in this window '
                          'until it is reloaded.',
                  style: AppTypography.caption.copyWith(color: _saved! ? AppColors.textFaint : AppColors.warning)),
            ],
          ]),
        ),
      ),
    );
  }

  List<Widget> _finalSection(Design d) {
    final current = Design.label(d.version);
    if (d.finalised == null) {
      return [
        Text('No design has been finalised yet. You are viewing $current.', style: AppTypography.muted),
        const SizedBox(height: AppSpacing.md),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton.icon(
            onPressed: () => _apply(finalise: true),
            icon: const Icon(Icons.check, size: 16),
            label: Text('Finalise ${d.version == DesignVersion.v1 ? 'Version 1' : 'Version 2'}'),
          ),
        ),
      ];
    }
    final date = (d.finalisedAt ?? '').split('T').first;
    return [
      Text('${Design.label(d.finalised!)} is the final design${date.isEmpty ? '' : ' (finalised $date)'}.',
          style: AppTypography.body),
      if (d.finalised != d.version) ...[
        const SizedBox(height: AppSpacing.sm),
        Text('You are previewing $current.', style: AppTypography.muted),
        const SizedBox(height: AppSpacing.md),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton(
            onPressed: () => _apply(finalise: true),
            child: Text('Finalise ${d.version == DesignVersion.v1 ? 'Version 1' : 'Version 2'} instead'),
          ),
        ),
      ],
      const SizedBox(height: AppSpacing.sm),
      Align(
        alignment: Alignment.centerLeft,
        child: TextButton(onPressed: () => _apply(clearFinal: true), child: const Text('Reopen the comparison')),
      ),
    ];
  }
}

/// One design as a choice: a small live sketch of a page in that design (its own palette and typefaces), its name and
/// what characterises it.
class _DesignChoice extends StatelessWidget {
  const _DesignChoice(
      {required this.version, required this.brightness, required this.selected, required this.finalised, required this.onTap});
  final DesignVersion version;
  final Brightness brightness;
  final bool selected;
  final bool finalised;
  final VoidCallback onTap;

  static const _about = {
    DesignVersion.v1: 'An annotated research report: serif statements, a margin column, whitespace instead of boxes, '
        'one brass accent.',
    DesignVersion.v2: 'Ink and ivory with a coral accent: Outfit titles with one serif-italic word, Space Mono '
        'tags, pill controls, rounded cards, light trails and a live pulse.',
  };

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      selected: selected,
      label: '${Design.label(version)}${finalised ? ', finalised' : ''}',
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(4),
        child: AnimatedContainer(
          duration: AppMotion.normal,
          padding: const EdgeInsets.all(AppSpacing.md),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(4),
            border: Border.all(color: selected ? AppColors.accent : AppColors.border, width: selected ? 1.5 : 1),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            DesignSketch(version: version, brightness: brightness),
            const SizedBox(height: AppSpacing.md),
            Row(children: [
              Expanded(child: Text(Design.label(version), style: AppTypography.section)),
              if (finalised)
                Padding(
                  padding: const EdgeInsets.only(right: AppSpacing.sm),
                  child: Text('Final', style: AppTypography.caption.copyWith(color: AppColors.success)),
                ),
              if (selected) ...[
                const SizedBox(width: AppSpacing.sm),
                Icon(Icons.radio_button_checked, size: 18, color: AppColors.primary),
              ] else
                Icon(Icons.radio_button_off, size: 18, color: AppColors.textFaint),
            ]),
            const SizedBox(height: AppSpacing.xs),
            Text(_about[version]!, style: AppTypography.caption),
          ]),
        ),
      ),
    );
  }
}

/// A miniature page drawn in a given design and mode, independent of the design in use (its own palette and fonts).
class DesignSketch extends StatelessWidget {
  const DesignSketch({super.key, required this.version, required this.brightness, this.height = 132});
  final DesignVersion version;
  final Brightness brightness;
  final double height;

  @override
  Widget build(BuildContext context) {
    final p = Palette.of(version, brightness);
    final v2 = version == DesignVersion.v2;
    final display = v2 ? 'Outfit' : 'InstrumentSerif';
    final body = v2 ? 'InstrumentSans' : 'IBMPlexSans';
    Widget line(double w, Color c) =>
        Container(width: w, height: 5, decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(3)));
    return ExcludeSemantics(
      child: Container(
        height: height,
        decoration: BoxDecoration(
            color: p.bg0, borderRadius: BorderRadius.circular(3), border: Border.all(color: p.border)),
        clipBehavior: Clip.antiAlias,
        child: Stack(children: [
          Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            // navigation
            Container(
              width: 58,
              padding: const EdgeInsets.all(7),
              decoration: BoxDecoration(color: p.navBg, border: Border(right: BorderSide(color: p.borderSubtle))),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Ci', style: TextStyle(fontFamily: display, fontSize: 12, color: p.navText, height: 1)),
                const SizedBox(height: 8),
                for (var i = 0; i < 4; i++) ...[
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 3, vertical: 2),
                    decoration: BoxDecoration(
                        color: i == 1 && v2 ? p.navSelected : null, borderRadius: BorderRadius.circular(1)),
                    child: line(i == 1 ? 34 : 28, i == 1 ? p.navText : p.navFaint.withValues(alpha: 0.7)),
                  ),
                  const SizedBox(height: 5),
                ],
              ]),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(10, 10, 10, 8),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    if (v2) ...[
                      Container(width: 4, height: 4, decoration: BoxDecoration(color: p.primary, shape: BoxShape.circle)),
                      const SizedBox(width: 3)
                    ],
                    Text(v2 ? 'SKILL-GAP ANALYSIS' : 'Skill-gap analysis',
                        style: TextStyle(
                            fontFamily: v2 ? 'SpaceMono' : body, fontSize: 6.5, color: p.textFaint, letterSpacing: v2 ? 0.9 : 0,
                            height: 1)),
                  ]),
                  const SizedBox(height: 5),
                  Text('Curriculum intelligence',
                      maxLines: 1,
                      overflow: TextOverflow.clip,
                      style: TextStyle(
                          fontFamily: display,
                          fontSize: 15,
                          height: 1.05,
                          fontWeight: v2 ? FontWeight.w500 : null,
                          letterSpacing: v2 ? -0.6 : -0.1,
                          color: p.text)),
                  const SizedBox(height: 7),
                  Expanded(
                    child: Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(7),
                      decoration: v2
                          ? BoxDecoration(
                              color: p.surface,
                              borderRadius: BorderRadius.circular(9),
                              border: Border.all(color: p.border))
                          : BoxDecoration(border: Border(top: BorderSide(color: p.borderSubtle))),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        line(90, p.textMuted.withValues(alpha: 0.7)),
                        const SizedBox(height: 4),
                        line(70, p.textFaint.withValues(alpha: 0.6)),
                        const Spacer(),
                        Row(children: [
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                            decoration: BoxDecoration(color: p.fill, borderRadius: BorderRadius.circular(v2 ? 99 : 1)),
                            child: Text('Open',
                                style: TextStyle(fontFamily: body, fontSize: 7, color: p.onFill, height: 1)),
                          ),
                          const SizedBox(width: 5),
                          Container(width: 5, height: 5, decoration: BoxDecoration(color: p.success, shape: BoxShape.circle)),
                          const SizedBox(width: 3),
                          line(24, p.textFaint.withValues(alpha: 0.6)),
                        ]),
                      ]),
                    ),
                  ),
                ]),
              ),
            ),
          ]),
        ]),
      ),
    );
  }
}
