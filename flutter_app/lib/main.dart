import 'package:flutter/material.dart';

import 'services/api_client.dart';
import 'shell/app_shell.dart';
import 'theme/design_system.dart';

export 'shell/app_shell.dart' show HomeShell;

void main() {
  runApp(const SkillGapApp());
}

/// Skill-Gap Intelligence dashboard. Every screen reads a real backend endpoint; nothing is invented
/// on the client. The shell (grouped, collapsible sidebar, top bar with search, freshness and status)
/// lives in shell/app_shell.dart.
///
/// The design in use (Version 1 or 2, dark or light; see theme/design_system.dart) can change while the app runs:
/// the theme is rebuilt and every element is asked to rebuild, so pages keep their state (forms, filters, the
/// analysis in progress) while their look changes.
class SkillGapApp extends StatefulWidget {
  const SkillGapApp({super.key, this.apiClient});

  /// Injected in tests; defaults to `ApiClient()` (API_URL dart-define, else http://localhost:8000).
  final ApiClient? apiClient;

  @override
  State<SkillGapApp> createState() => _SkillGapAppState();
}

class _SkillGapAppState extends State<SkillGapApp> {
  @override
  void initState() {
    super.initState();
    Design.current.addListener(_designChanged);
  }

  @override
  void dispose() {
    Design.current.removeListener(_designChanged);
    super.dispose();
  }

  void _designChanged() {
    if (!mounted) return;
    setState(() {});
    // tokens are read while building: rebuild every element (also const ones) with the new design, keeping state
    void rebuild(Element e) {
      e.markNeedsBuild();
      e.visitChildren(rebuild);
    }

    (context as Element).visitChildren(rebuild);
  }

  @override
  Widget build(BuildContext context) {
    final theme = buildAppTheme();
    return MaterialApp(
      title: 'Skill-Gap Intelligence',
      debugShowCheckedModeBanner: false,
      theme: theme,
      darkTheme: theme,
      themeMode: Design.current.isDark ? ThemeMode.dark : ThemeMode.light,
      // the two designs use different typefaces: switch at once rather than interpolating between them
      themeAnimationDuration: Duration.zero,
      home: HomeShell(apiClient: widget.apiClient),
    );
  }
}
