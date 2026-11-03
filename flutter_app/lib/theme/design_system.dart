import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'plain_language.dart';

/// Central design system. Two complete visual designs share every page and component, each in a dark and a light
/// mode, chosen at run time (see [Design] and the Appearance panel):
///
///  * Version 1 "Research report": an annotated report rather than a dashboard. A warm charcoal (or paper) ground,
///    Instrument Serif for statements, IBM Plex Sans for reading, one brass accent; hierarchy from type and
///    whitespace, not from cards.
///  * Version 2 "Atelier": a mix of the two reference designs. Night: Veloria's ink-navy ground and ivory text with
///    the Thinking Gods coral as the one interactive accent and Veloria's gold for rules and frames. Day: an ivory
///    ground, ink-navy text, a deep coral accent. Outfit for titles and interface text (tight tracking), one word of
///    a headline set in Cormorant Garamond italic, Instrument Sans for reading, Space Mono for tags and small labels;
///    pill controls, hairline-ringed cards, and motion that answers what happens (reveals, a live pulse, light
///    trails behind the overview).
///
/// Every colour, typeface, radius and shadow comes from here; widgets never hard-code visual constants. Tokens are
/// getters that read the current design, so they are never used in `const` expressions. Spacing, layout and motion
/// are shared by both designs and stay constant.
enum DesignVersion { v1, v2 }

class Palette {
  const Palette({
    required this.bg0,
    required this.bg1,
    required this.surface,
    required this.surfaceRaised,
    required this.surfaceSunken,
    required this.border,
    required this.borderSubtle,
    required this.text,
    required this.textMuted,
    required this.textFaint,
    required this.primary,
    required this.onPrimary,
    required this.accent,
    required this.fill,
    required this.onFill,
    required this.navBg,
    required this.navText,
    required this.navMuted,
    required this.navFaint,
    required this.navAccent,
    required this.navSelected,
    required this.secondary,
    required this.success,
    required this.warning,
    required this.danger,
    required this.info,
    required this.neutral,
    required this.brightness,
  });
  final Color bg0, bg1, surface, surfaceRaised, surfaceSunken, border, borderSubtle;
  final Color text, textMuted, textFaint, primary, onPrimary, secondary;
  // accent: decorative only (dots, rules, the current place); fill / onFill: the primary button
  final Color accent, fill, onFill;
  // the navigation column
  final Color navBg, navText, navMuted, navFaint, navAccent, navSelected;
  final Color success, warning, danger, info, neutral;
  final Brightness brightness;

  // every foreground colour reaches 4.5:1 on every background of its palette (test/workflow_test.dart)
  static const v1Dark = Palette(
      bg0: Color(0xFF121110), bg1: Color(0xFF121110), surface: Color(0xFF191816), surfaceRaised: Color(0xFF201E1B),
      surfaceSunken: Color(0xFF0E0D0C), border: Color(0xFF2A2723), borderSubtle: Color(0xFF211F1C),
      text: Color(0xFFECE6DC), textMuted: Color(0xFFA9A296), textFaint: Color(0xFF8E887C),
      primary: Color(0xFFC8AD79), onPrimary: Color(0xFF121110), secondary: Color(0xFF9DB2A4),
      accent: Color(0xFFC8AD79), fill: Color(0xFFC8AD79), onFill: Color(0xFF121110),
      navBg: Color(0xFF121110), navText: Color(0xFFECE6DC), navMuted: Color(0xFFA9A296), navFaint: Color(0xFF8E887C),
      navAccent: Color(0xFFC8AD79), navSelected: Color(0xFF191816),
      success: Color(0xFF94AF98), warning: Color(0xFFD0A565), danger: Color(0xFFD4968B), info: Color(0xFFA0B3C3),
      neutral: Color(0xFFA7A195), brightness: Brightness.dark);
  static const v1Light = Palette(
      bg0: Color(0xFFF5F1EA), bg1: Color(0xFFF5F1EA), surface: Color(0xFFEDE7DD), surfaceRaised: Color(0xFFE6DFD3),
      surfaceSunken: Color(0xFFFAF7F2), border: Color(0xFFD3CABB), borderSubtle: Color(0xFFE3DCD0),
      text: Color(0xFF221F1A), textMuted: Color(0xFF4F4A41), textFaint: Color(0xFF655F55),
      primary: Color(0xFF7A5A22), onPrimary: Color(0xFFFBF8F3), secondary: Color(0xFF4B6656),
      accent: Color(0xFF7A5A22), fill: Color(0xFF7A5A22), onFill: Color(0xFFFBF8F3),
      navBg: Color(0xFFF5F1EA), navText: Color(0xFF221F1A), navMuted: Color(0xFF4F4A41), navFaint: Color(0xFF655F55),
      navAccent: Color(0xFF7A5A22), navSelected: Color(0xFFEDE7DD),
      success: Color(0xFF2F6842), warning: Color(0xFF875811), danger: Color(0xFF9E3F33), info: Color(0xFF37607E),
      neutral: Color(0xFF5E594F), brightness: Brightness.light);
  // Version 2 night: ink and ivory (Veloria) with a coral accent (Thinking Gods) and gold rules
  static const v2Dark = Palette(
      bg0: Color(0xFF05090E), bg1: Color(0xFF05090E), surface: Color(0xFF0B121A), surfaceRaised: Color(0xFF121B25),
      surfaceSunken: Color(0xFF03060A), border: Color(0xFF1E2833), borderSubtle: Color(0xFF141C26),
      text: Color(0xFFF4EFE6), textMuted: Color(0xFFBDB8B0), textFaint: Color(0xFF8F8C87),
      primary: Color(0xFFFC4778), onPrimary: Color(0xFF05090E), secondary: Color(0xFFC9A96E),
      accent: Color(0xFFC9A96E), fill: Color(0xFFF4EFE6), onFill: Color(0xFF0B1622),
      navBg: Color(0xFF05090E), navText: Color(0xFFF4EFE6), navMuted: Color(0xFFBDB8B0), navFaint: Color(0xFF8F8C87),
      navAccent: Color(0xFFFC4778), navSelected: Color(0xFF0B121A),
      success: Color(0xFF7CC79A), warning: Color(0xFFE3B566), danger: Color(0xFFFF7A85), info: Color(0xFF8FB8E8),
      neutral: Color(0xFFA7ADB8), brightness: Brightness.dark);
  // Version 2 day: an ivory ground, ink-navy text, a deep coral accent and deep-gold rules
  static const v2Light = Palette(
      bg0: Color(0xFFF4EFE6), bg1: Color(0xFFF4EFE6), surface: Color(0xFFFBF8F2), surfaceRaised: Color(0xFFEDE6DA),
      surfaceSunken: Color(0xFFF8F4EC), border: Color(0xFFDCD3C4), borderSubtle: Color(0xFFE8E1D5),
      text: Color(0xFF0B1622), textMuted: Color(0xFF3E4651), textFaint: Color(0xFF5A616B),
      primary: Color(0xFFB8233F), onPrimary: Color(0xFFFBF8F2), secondary: Color(0xFF7A5C22),
      accent: Color(0xFFB08D4E), fill: Color(0xFF0B1622), onFill: Color(0xFFF4EFE6),
      navBg: Color(0xFFF4EFE6), navText: Color(0xFF0B1622), navMuted: Color(0xFF3E4651), navFaint: Color(0xFF5A616B),
      navAccent: Color(0xFFB8233F), navSelected: Color(0xFFFBF8F2),
      success: Color(0xFF2F6B4A), warning: Color(0xFF855A16), danger: Color(0xFFB3263A), info: Color(0xFF2D5A8A),
      neutral: Color(0xFF555B66), brightness: Brightness.light);

  static Palette of(DesignVersion v, Brightness b) => switch ((v, b)) {
        (DesignVersion.v1, Brightness.dark) => v1Dark,
        (DesignVersion.v1, Brightness.light) => v1Light,
        (DesignVersion.v2, Brightness.dark) => v2Dark,
        (DesignVersion.v2, Brightness.light) => v2Light,
      };
}

/// The design in use: version and brightness, and whether a version has been finalised (Appearance panel). One
/// instance for the app; the root widget listens and rebuilds every element when it changes.
class Design extends ChangeNotifier {
  Design._();
  static final Design current = Design._();

  DesignVersion version = DesignVersion.v2;
  Brightness brightness = Brightness.dark;

  /// The version recorded as final (null while the two are still being compared) and when.
  DesignVersion? finalised;
  String? finalisedAt;

  Palette get palette => Palette.of(version, brightness);
  bool get isV2 => version == DesignVersion.v2;
  bool get isDark => brightness == Brightness.dark;

  void set({DesignVersion? version, Brightness? brightness, DesignVersion? finalised, String? finalisedAt,
      bool clearFinal = false}) {
    final before = (this.version, this.brightness, this.finalised, this.finalisedAt);
    this.version = version ?? this.version;
    this.brightness = brightness ?? this.brightness;
    if (clearFinal) {
      this.finalised = null;
      this.finalisedAt = null;
    } else {
      this.finalised = finalised ?? this.finalised;
      this.finalisedAt = finalisedAt ?? this.finalisedAt;
    }
    if (before != (this.version, this.brightness, this.finalised, this.finalisedAt)) notifyListeners();
  }

  static String label(DesignVersion v) => v == DesignVersion.v1 ? 'Version 1 · Research report' : 'Version 2 · Atelier';
}

DesignVersion? designVersionOf(dynamic v) => v == 'v1' ? DesignVersion.v1 : v == 'v2' ? DesignVersion.v2 : null;

class AppColors {
  AppColors._();
  static Palette get _p => Design.current.palette;

  static Color get bg0 => _p.bg0; // page
  static Color get bg1 => _p.bg1; // navigation / top bar
  static Color get surface => _p.surface; // a card (V2) or a disclosed evidence well (V1)
  static Color get surfaceRaised => _p.surfaceRaised; // hover
  static Color get surfaceSunken => _p.surfaceSunken; // code
  static Color get border => _p.border; // the few rules that separate content
  static Color get borderSubtle => _p.borderSubtle; // hairlines

  static Color get text => _p.text;
  static Color get textMuted => _p.textMuted;
  static Color get textFaint => _p.textFaint;

  static Color get primary => _p.primary; // interaction and the evidence trail only
  static Color get onPrimary => _p.onPrimary;
  static Color get accent => _p.accent; // decorative: dots, rules, the current place
  static Color get fill => _p.fill; // the primary button
  static Color get onFill => _p.onFill;
  static Color get navBg => _p.navBg;
  static Color get navText => _p.navText;
  static Color get navMuted => _p.navMuted;
  static Color get navFaint => _p.navFaint;
  static Color get navAccent => _p.navAccent;
  static Color get navSelected => _p.navSelected;
  static Color get secondary => _p.secondary;

  // semantic: always paired with words (a small dot, never colour alone)
  static Color get success => _p.success;
  static Color get warning => _p.warning;
  static Color get danger => _p.danger;
  static Color get info => _p.info;
  static Color get neutral => _p.neutral;

  /// The decorative accent at a given opacity (quiet highlights).
  static Color tint(double opacity) => _p.accent.withValues(alpha: opacity);

  /// WCAG relative luminance contrast ratio (used by the accessibility test).
  static double contrast(Color a, Color b) {
    double lum(Color c) {
      double ch(double v) => v <= 0.03928 ? v / 12.92 : math.pow((v + 0.055) / 1.055, 2.4).toDouble();
      return 0.2126 * ch(c.r) + 0.7152 * ch(c.g) + 0.0722 * ch(c.b);
    }

    final la = lum(a), lb = lum(b);
    return (math.max(la, lb) + 0.05) / (math.min(la, lb) + 0.05);
  }
}

class AppSpacing {
  AppSpacing._();
  static const xxs = 2.0;
  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 12.0;
  static const lg = 16.0;
  static const xl = 24.0;
  static const xxl = 40.0;
  static const block = 56.0; // between blocks inside a section
  static const section = 120.0; // between the stages of a page: the page breathes here
  static const page = 56.0;
}

/// The report layout: a margin column for labels, indices and the trail; a reading column for sentences.
class AppLayout {
  AppLayout._();
  static const margin = 168.0; // margin column
  static const gutter = 40.0; // between margin and reading column
  static const measure = 720.0; // reading column
  static const maxWidth = 1120.0; // whole page
  static const stack = 860.0; // below this width the margin moves above its content
}

class AppRadius {
  AppRadius._();
  static bool get _v2 => Design.current.isV2;
  static double get sm => 2.0;
  static double get md => _v2 ? 12.0 : 3.0;
  static double get lg => _v2 ? 22.0 : 4.0;
  static const pill = 999.0;
  static BorderRadius get card => BorderRadius.circular(lg);
  static BorderRadius get control => _v2 ? BorderRadius.circular(pill) : BorderRadius.circular(md);
  static BorderRadius get field => BorderRadius.circular(md);
}

class AppShadows {
  AppShadows._();
  // flat in both designs: depth comes from whitespace, 1px rules and type, never shadows or glows
  static List<BoxShadow> get card => const <BoxShadow>[];
  static List<BoxShadow> get glow => const <BoxShadow>[];
}

/// Motion system: small interactions 120-180 ms, transitions 200-300 ms, section and page reveals 350-500 ms.
/// Everything respects the platform's reduced-motion setting.
class AppMotion {
  AppMotion._();
  static const fast = Duration(milliseconds: 150); // hover, press, underline
  static const normal = Duration(milliseconds: 260); // disclosure, filter, tab
  static const complex = Duration(milliseconds: 420); // section reveal
  static const page = Duration(milliseconds: 480); // page entrance
  static const trail = Duration(milliseconds: 520); // evidence trail drawing itself
  static const stagger = Duration(milliseconds: 70); // between the first sections of a page
  static const curve = Curves.easeOutCubic; // entrances
  static const emphasized = Cubic(0.2, 0.0, 0.0, 1.0); // reveals: quick start, long gentle settle
  static const resize = Curves.easeInOutCubic; // size changes (expanding evidence)

  static bool reduced(BuildContext context) => MediaQuery.maybeDisableAnimationsOf(context) ?? false;
}

class AppFonts {
  AppFonts._();
  static bool get _v2 => Design.current.isV2;
  static String get display => _v2 ? 'Outfit' : 'InstrumentSerif';
  /// The one word of a Version 2 headline set in a serif italic.
  static const accentSerif = 'CormorantGaramond';
  static String get body => _v2 ? 'InstrumentSans' : 'IBMPlexSans';
  static String get mono => _v2 ? 'SpaceMono' : 'IBMPlexMono';
  static List<String> get displayFallback =>
      _v2 ? const ['Helvetica Neue', 'Arial', 'sans-serif'] : const ['Georgia', 'Times New Roman', 'serif'];
  static List<String> get bodyFallback => const ['Helvetica Neue', 'Arial', 'sans-serif'];
}

/// Typographic rhythm: eyebrow -> title -> explanatory sentence -> evidence -> detail. Version 1 sets statements in
/// Instrument Serif; Version 2 in Outfit with tight tracking (one word in Cormorant italic, see [accentHeadline]) and
/// small labels in Space Mono, tracked wide.
class AppTypography {
  AppTypography._();
  static const _tab = [FontFeature.tabularFigures()];
  static const _old = [FontFeature.oldstyleFigures()];
  static bool get _v2 => Design.current.isV2;

  static TextStyle _d(double size, double height, {double spacing = 0, FontWeight? weight, Color? color,
          FontStyle? style, List<FontFeature>? features}) =>
      TextStyle(
          fontFamily: AppFonts.display,
          fontFamilyFallback: AppFonts.displayFallback,
          fontSize: size,
          height: height,
          letterSpacing: spacing,
          fontWeight: weight,
          fontStyle: style,
          color: color ?? AppColors.text,
          fontFeatures: features);

  static TextStyle _b(double size, double height, {FontWeight? weight, Color? color, double? spacing}) => TextStyle(
      fontFamily: AppFonts.body,
      fontFamilyFallback: AppFonts.bodyFallback,
      fontSize: size,
      height: height,
      fontWeight: weight,
      letterSpacing: spacing,
      color: color ?? AppColors.text);

  // display: statements and names
  static TextStyle get statement =>
      _v2 ? _d(54, 1.02, spacing: -2.4, weight: FontWeight.w500) : _d(46, 1.12, spacing: -0.6);
  static TextStyle get hero => statement; // the one statement a page opens with
  static TextStyle get display =>
      _v2 ? _d(42, 1.06, spacing: -1.7, weight: FontWeight.w500) : _d(38, 1.14, spacing: -0.4);
  static TextStyle get headline =>
      _v2 ? _d(28, 1.14, spacing: -0.9, weight: FontWeight.w500) : _d(27, 1.22, spacing: -0.2);
  static TextStyle get title => _v2 ? _d(21, 1.25, spacing: -0.5, weight: FontWeight.w500) : _d(22, 1.27);
  static TextStyle get quote => _v2
      ? TextStyle(fontFamily: AppFonts.accentSerif, fontStyle: FontStyle.italic, fontSize: 20, height: 1.45,
          color: AppColors.textMuted, fontFamilyFallback: const ['Georgia', 'serif'])
      : _d(17, 1.5, style: FontStyle.italic, color: AppColors.textMuted);
  // a number used as a typographic anchor
  static TextStyle get numeral => _v2
      ? _d(50, 1.0, spacing: -2, weight: FontWeight.w400, features: _tab)
      : _d(46, 1.0, spacing: -0.6, features: _tab);
  static TextStyle get index =>
      _v2 ? _mono(13, color: AppColors.textFaint, spacing: 1) : _d(22, 1.27, color: AppColors.textFaint, features: _old);

  // reading
  static TextStyle get lede => _b(_v2 ? 17 : 17.5, 1.7, color: AppColors.textMuted);
  static TextStyle get section => _b(15, 1.5, weight: FontWeight.w500);
  static TextStyle get body => _b(15, 1.65);
  static TextStyle get muted => _b(14, 1.6, color: AppColors.textMuted);
  static TextStyle get caption => _b(12.5, 1.5, color: AppColors.textFaint);
  // the eyebrow / margin label: small and never shouting (V2: Space Mono, tracked)
  static TextStyle get overline => _v2
      ? _mono(11, color: AppColors.textFaint, spacing: 1.4)
      : _b(12.5, 1.5, weight: FontWeight.w500, color: AppColors.textFaint, spacing: 0.2);
  static TextStyle get metric => _v2
      ? _d(34, 1.0, spacing: -1.2, weight: FontWeight.w400, features: _tab)
      : _d(30, 1.05, features: _tab);
  static TextStyle get metricSmall =>
      _b(15, 1.4, weight: FontWeight.w500).copyWith(fontFeatures: _tab);
  static TextStyle get link => _b(14, 1.5, weight: FontWeight.w500, color: AppColors.primary);
  static TextStyle get mono => _mono(12, color: AppColors.textMuted);

  static TextStyle _mono(double size, {Color? color, double spacing = 0}) => TextStyle(
      fontFamily: AppFonts.mono,
      fontFamilyFallback: const ['Menlo', 'monospace'],
      fontSize: size,
      height: 1.5,
      letterSpacing: spacing,
      color: color ?? AppColors.textMuted);
}


/// Semantic tone of a status value. The same status looks the same everywhere, and state is always carried by
/// icon + words + colour together (never colour alone).
enum Tone { good, warning, danger, info, neutral }

class StatusStyle {
  StatusStyle._();

  static const _good = {
    'AVAILABLE', 'ALLOWED', 'PASS', 'HEALTHY', 'READY', 'CONNECTED', 'ALIVE', 'COVERED', 'SUPPORTED', 'HIGH_SUPPORT',
    'RECOMMENDATION_SUPPORTED', 'MODEL_SUPPORTED', 'ESTABLISHED', 'PEER_DATA_AVAILABLE', 'SAME_CONCEPT', 'COMPUTED',
    'SUFFICIENT', 'EXACT', 'CONFIRMED', 'INDEPENDENTLY_EVALUATED', 'ok', 'OK', 'UNANIMOUS', 'PROMOTED',
    'SUCCESSFUL_AND_USABLE', 'ANALYSIS_READY', 'EXTRACTED', 'NOT_REQUIRED', 'REFERENCE_MAPPED', 'CONFIGURED',
    'REGISTERED_AS_REFERENCE'
  };
  static const _warning = {
    'SAFE_MODE', 'DEGRADED', 'PARTIAL', 'VALIDATING', 'ACQUIRING', 'REVIEW_REQUIRED', 'INSUFFICIENT_EVIDENCE',
    'INSUFFICIENT', 'INSUFFICIENT_DATA', 'MODEL_SUGGESTED', 'SUPPRESSED', 'PEER_DATA_PARTIAL', 'WARN', 'AMBIGUOUS',
    'CANDIDATE', 'PENDING_INDEPENDENT_LABELS', 'NOT_ASSESSABLE', 'NOT_CONFIRMED', 'BORDERLINE', 'MENTION',
    'INTRODUCTORY', 'ADJUDICATED', 'RULE_VERDICT_NO_MODEL', 'NEEDS_REVIEW', 'EXECUTION_SUCCEEDED_BUT_NO_USABLE_CONTENT',
    'NO_USABLE_CONTENT', 'PARTIAL_EXTRACTION', 'ANALYSIS_PENDING', 'LOW_CONFIDENCE', 'NOT_CONFIGURED', 'MISSING'
  };
  static const _danger = {
    'UNAVAILABLE', 'NOT_READY', 'FAIL', 'FAILED', 'BLOCKED', 'NOT_PRODUCED', 'SOURCE_UNAVAILABLE',
    'LICENSE_RESTRICTED', 'ACQUISITION_FAILED', 'MODEL_FAILURE', 'NOT_LOADED', 'PEER_DATA_NOT_AVAILABLE', 'ERROR',
    'DATA_NOT_AVAILABLE', 'CONTRADICTED', 'UNRESOLVED', 'EXECUTION_FAILED', 'EXTRACTION_FAILED', 'ANALYSIS_FAILED',
    'INVALID_DOCUMENT'
  };
  static const _info = {
    'OBSERVED', 'RELATED', 'PARTIAL_OVERLAP', 'VARIANT', 'PARENT', 'CHILD', 'TRENDING_UP', 'TRENDING_DOWN', 'STABLE',
    'EMERGING', 'DECLINING', 'PERSISTENT', 'SUBSTANTIAL', 'ADVANCED', 'REFERENCE', 'PEER', 'TARGET', 'INFERRED',
    'REPLAY_VERIFIED_RUN', 'AI_PROVIDER_REPLAYED', 'UNMAPPED', 'ABSENT', 'DISABLED', 'PREVIOUS_VERSION', 'NOT_APPLICABLE',
    'NOT_REQUESTED'
  };

  /// Human wording for the primary UI. The technical code stays available in tooltips, evidence and methodology.
  static const human = {
    // curriculum actions: a recommendation is a consideration for the institution, never an automatic decision
    'EXPAND_EXISTING_TOPIC': 'Expand an existing topic',
    'STRENGTHEN_EXISTING_COURSE': 'Strengthen an existing course',
    'REVIEW_BEFORE_CHANGE': 'Review the curriculum before recommending a change',
    'REVIEW_EXISTING_COURSE': 'Review an existing course',
    'ADD_MODULE': 'Consider adding a module to an existing course',
    'ADD_ELECTIVE': 'Consider a new elective',
    'CONSIDER_ELECTIVE': 'Consider a new elective',
    'ADD_NEW_SUBJECT': 'Consider a new standalone course',
    'CONSIDER_STANDALONE_COURSE': 'Consider a new standalone course',
    'NO_ACTION_INDICATED': 'No change indicated',
    'NOT_APPLICABLE': 'Not applicable',
    'NOT_REQUESTED': 'Not requested',
    'TARGET': 'Current curriculum',
    'PREVIOUS_VERSION': 'Earlier curriculum',
    'SAFE_MODE': 'AI interpretation is advisory',
    'DEGRADED': 'Evidence coverage is limited',
    'INSUFFICIENT_EVIDENCE': 'Not enough evidence',
    'INSUFFICIENT_DATA': 'Not enough time periods',
    'REVIEW_REQUIRED': 'Needs review',
    'NEEDS_REVIEW': 'Needs review',
    // MODEL_SUGGESTED is the contract's generic "inferred, not validated" state: concept clustering, drift, mapping,
    // peer relations and rule-based recommendations use it as well as the advisory AI decisions, so the wording must
    // not attribute those results to AI.
    'MODEL_SUGGESTED': 'Inferred, not independently validated',
    'MODEL_SUPPORTED': 'AI-supported, validated',
    'SAME_CONCEPT': 'Equivalent concept',
    'PARENT': 'Broader concept',
    'CHILD': 'More specific concept',
    'RELATED': 'Related concept',
    'PARTIAL_OVERLAP': 'Partial overlap',
    'UNRELATED': 'Unrelated',
    'AMBIGUOUS': 'Ambiguous',
    'PEER_DATA_PARTIAL': 'Peer data partial',
    'PEER_DATA_AVAILABLE': 'Peer data available',
    'PEER_DATA_NOT_AVAILABLE': 'No peer data yet',
    'RECOMMENDATION_SUPPORTED': 'Recommendation supported',
    'SUPPRESSED': 'Withheld',
    'PENDING_INDEPENDENT_LABELS': 'Independent validation pending',
    'RULE_VERDICT_NO_MODEL': 'Rule verdict',
    'NOT_PRODUCED': 'Not produced',
    'REFERENCE_MAPPED': 'Mapped to reference',
    'SUCCESSFUL_AND_USABLE': 'Ready for analysis',
    'EXECUTION_SUCCEEDED_BUT_NO_USABLE_CONTENT': 'No usable content',
    'EXECUTION_FAILED': 'Processing failed',
    'REGISTERED_AS_REFERENCE': 'Registered as reference',
    'ANALYSIS_PENDING': 'Analysis being prepared',
    'ANALYSIS_READY': 'Analysis ready',
    'ANALYSIS_FAILED': 'Analysis failed',
    'HIGH_SUPPORT': 'High support',
    'OBSERVED': 'Observed',
    'INTRODUCTORY': 'Introductory',
    'SUBSTANTIAL': 'Substantial',
    'MENTION': 'Mention only',
    'ABSENT': 'Absent',
  };

  static Tone toneOf(String? value) {
    final v = (value ?? '').trim();
    if (_good.contains(v)) return Tone.good;
    if (_warning.contains(v)) return Tone.warning;
    if (_danger.contains(v)) return Tone.danger;
    if (_info.contains(v)) return Tone.info;
    return Tone.neutral;
  }

  static bool isKnown(String? value) => toneOf(value) != Tone.neutral;

  static Color color(Tone t) {
    switch (t) {
      case Tone.good:
        return AppColors.success;
      case Tone.warning:
        return AppColors.warning;
      case Tone.danger:
        return AppColors.danger;
      case Tone.info:
        return AppColors.info;
      case Tone.neutral:
        return AppColors.neutral;
    }
  }

  static IconData icon(Tone t, [String? value]) {
    if (value == 'SAFE_MODE') return Icons.shield_outlined;
    switch (t) {
      case Tone.good:
        return Icons.check;
      case Tone.warning:
        return Icons.priority_high;
      case Tone.danger:
        return Icons.close;
      case Tone.info:
        return Icons.remove;
      case Tone.neutral:
        return Icons.circle_outlined;
    }
  }

  /// Methods in words (the method code stays in technical views).
  static const methods = {
    'tfidf_cosine': 'Textual similarity',
    'tfidf_cosine+token_containment': 'Textual similarity and shared words',
    'tfidf_concept_clustering': 'Grouped by textual similarity',
    'normalized_text_identity': 'Identical wording',
    'document_structure': 'Document structure',
    'colon_head_list_structure': 'Heading and list structure',
    'alias': 'Taxonomy alias',
    'exact_label': 'Exact taxonomy label',
    'normalized_label': 'Normalized taxonomy label',
    'prefLabel_exact': 'Taxonomy preferred label',
    'esco_broader_relation': 'Taxonomy hierarchy',
    'posting_prevalence': 'Share of job postings',
    'esco_occupation_label_match': 'Occupation title match',
  };

  static String method(String code) => methods[code] ?? code.replaceAll('_', ' ');

  /// Human label: the curated wording, else the user-facing term (plain_language.dart), else sentence case of the
  /// code ("PEER_DATA_PARTIAL" -> "Peer data partial"). A backend code is never shown as it is.
  static String label(String value) {
    final h = human[value];
    if (h != null) return h;
    final t = Plain.terms[value];
    if (t != null) return t;
    final words = value.replaceAll('_', ' ').trim();
    if (words.isEmpty || words != words.toUpperCase()) return Plain.isCode(value) ? Plain.words(value) : words;
    final lower = words.toLowerCase();
    return lower[0].toUpperCase() + lower.substring(1);
  }
}


ThemeData buildAppTheme() {
  final p = Design.current.palette;
  final v2 = Design.current.isV2;
  final scheme = (p.brightness == Brightness.dark ? const ColorScheme.dark() : const ColorScheme.light()).copyWith(
    surface: p.bg0,
    primary: p.primary,
    onPrimary: p.onPrimary,
    secondary: p.secondary,
    error: p.danger,
    onSurface: p.text,
    outline: p.border,
  );
  final base = ThemeData(
    useMaterial3: true,
    brightness: p.brightness,
    fontFamily: AppFonts.body,
    colorScheme: scheme,
    scaffoldBackgroundColor: p.bg0,
    splashFactory: NoSplash.splashFactory, // no ink ripples: interaction is shown by type and the accent
    hoverColor: Colors.transparent,
    highlightColor: Colors.transparent,
    focusColor: p.surfaceRaised,
  );
  final underline = UnderlineInputBorder(borderSide: BorderSide(color: p.border));
  final outline = OutlineInputBorder(borderRadius: AppRadius.field, borderSide: BorderSide(color: p.border));
  return base.copyWith(
    textTheme: base.textTheme.apply(bodyColor: p.text, displayColor: p.text, fontFamily: AppFonts.body),
    cardTheme: const CardThemeData(color: Colors.transparent, elevation: 0, margin: EdgeInsets.zero),
    dividerTheme: DividerThemeData(color: p.borderSubtle, space: 1, thickness: 1),
    appBarTheme: AppBarTheme(backgroundColor: p.bg0, foregroundColor: p.text, elevation: 0),
    drawerTheme: DrawerThemeData(backgroundColor: v2 ? p.navBg : p.bg0),
    dialogTheme: DialogThemeData(
        backgroundColor: v2 ? p.surface : p.bg0,
        shape: RoundedRectangleBorder(borderRadius: AppRadius.card, side: BorderSide(color: p.border))),
    listTileTheme: ListTileThemeData(textColor: p.textMuted, iconColor: p.textFaint),
    checkboxTheme: CheckboxThemeData(
      fillColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? p.fill : Colors.transparent),
      checkColor: WidgetStatePropertyAll(p.onFill),
      side: BorderSide(color: p.textFaint, width: 1.4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(2)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: v2,
      fillColor: v2 ? p.surface : null,
      isDense: true,
      hintStyle: AppTypography.caption,
      labelStyle: AppTypography.muted,
      prefixIconColor: p.textFaint,
      contentPadding: v2
          ? const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.md)
          : const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      border: v2 ? outline : underline,
      enabledBorder: v2 ? outline : underline,
      focusedBorder: v2
          ? OutlineInputBorder(borderRadius: AppRadius.field, borderSide: BorderSide(color: p.primary, width: 1.4))
          : UnderlineInputBorder(borderSide: BorderSide(color: p.primary)),
    ),
    chipTheme: base.chipTheme.copyWith(
      backgroundColor: Colors.transparent,
      side: v2 ? BorderSide(color: p.border) : BorderSide.none,
      shape: v2 ? const StadiumBorder() : null,
      labelStyle: AppTypography.caption,
      padding: v2 ? const EdgeInsets.symmetric(horizontal: AppSpacing.xs) : EdgeInsets.zero,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: p.fill,
        foregroundColor: p.onFill,
        elevation: 0,
        padding: v2
            ? const EdgeInsets.symmetric(horizontal: AppSpacing.lg + 4, vertical: AppSpacing.sm + 4)
            : const EdgeInsets.symmetric(horizontal: AppSpacing.xl, vertical: AppSpacing.md),
        shape: v2 ? const StadiumBorder() : RoundedRectangleBorder(borderRadius: AppRadius.control),
        textStyle: TextStyle(
            fontFamily: AppFonts.body, fontWeight: v2 ? FontWeight.w600 : FontWeight.w500, fontSize: v2 ? 13.5 : null),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: p.text,
        side: BorderSide(color: v2 ? p.text.withValues(alpha: 0.22) : p.border),
        padding: v2
            ? const EdgeInsets.symmetric(horizontal: AppSpacing.lg + 2, vertical: AppSpacing.sm + 4)
            : const EdgeInsets.symmetric(horizontal: AppSpacing.xl, vertical: AppSpacing.md),
        shape: v2 ? const StadiumBorder() : RoundedRectangleBorder(borderRadius: AppRadius.control),
        textStyle: v2 ? TextStyle(fontFamily: AppFonts.body, fontWeight: FontWeight.w500, fontSize: 13.5) : null,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: p.primary,
        overlayColor: Colors.transparent,
        textStyle: AppTypography.link,
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(
            foregroundColor: p.textFaint, hoverColor: Colors.transparent, highlightColor: Colors.transparent)),
    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(color: p.surfaceRaised, borderRadius: BorderRadius.circular(3)),
      textStyle: AppTypography.muted.copyWith(color: p.text),
      waitDuration: const Duration(milliseconds: 400),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: p.surfaceRaised,
      contentTextStyle: AppTypography.body,
      behavior: v2 ? SnackBarBehavior.floating : null,
      shape: v2 ? RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)) : null,
    ),
    dataTableTheme: DataTableThemeData(
      headingTextStyle: AppTypography.caption,
      dataTextStyle: TextStyle(fontFamily: AppFonts.body, color: p.text, fontSize: 13.5, height: 1.5),
      dividerThickness: 0.5,
      horizontalMargin: 0,
      columnSpacing: AppSpacing.xxl,
      headingRowHeight: 40,
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(color: p.primary, linearTrackColor: p.border),
    pageTransitionsTheme: const PageTransitionsTheme(builders: {
      TargetPlatform.android: FadeUpwardsPageTransitionsBuilder(),
      TargetPlatform.iOS: FadeUpwardsPageTransitionsBuilder(),
      TargetPlatform.macOS: FadeUpwardsPageTransitionsBuilder(),
      TargetPlatform.linux: FadeUpwardsPageTransitionsBuilder(),
      TargetPlatform.windows: FadeUpwardsPageTransitionsBuilder(),
    }),
  );
}
