import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../shell/navigation.dart';
import '../../theme/design_system.dart';
import '../../widgets/ui_kit.dart';
import '../ingestion_screen.dart';
import '../knowledge_screens.dart';
import '../pipeline_runs_screen.dart';
import '../preprocessing_preview_screen.dart';
import 'assistant_screen.dart';
import 'data_quality_screen.dart';
import 'drift_screen.dart';
import 'evaluation_screen.dart';
import 'graph_screen.dart';
import 'history_screen.dart';
import 'industry_screen.dart';
import 'lineage_screen.dart';
import 'occupations_screen.dart';
import 'overview_screen.dart';
import 'peer_screen.dart';
import 'recommendations_screen.dart';
import 'semantic_screen.dart';
import 'settings_screen.dart';
import 'skill_gaps_screen.dart';
import 'system_health_screen.dart';
import 'trends_screen.dart';

typedef Navigate = void Function(Dest dest, {String? arg});

/// A spec-driven data view embedded in the shell (no own app bar).
Widget specView(ApiClient api, String title, {String? input, String? label}) =>
    KnowledgeScreen(key: ValueKey('spec:$title:${input ?? ''}'), apiClient: api, spec: specNamed(title),
        showHeader: false, initialInput: input, label: label ?? _labelOf(title));

/// The navigation label of a spec-driven view ("Course Drift & Lineage" -> "Curriculum changes").
String? _labelOf(String specTitle) {
  for (final e in allEntries) {
    if (e.spec == specTitle) return e.label;
  }
  return null;
}

Widget buildPage(Dest dest, ApiClient api, {String? arg, required Navigate navigate}) {
  switch (dest) {
    case Dest.overview:
      return OverviewScreen(api: api, navigate: navigate);
    case Dest.industryIntelligence:
      return IndustryScreen(api: api);
    case Dest.trends:
      return TrendsScreen(api: api, navigate: navigate);
    case Dest.skillGaps:
      return SkillGapsScreen(api: api);
    case Dest.recommendations:
      return RecommendationsScreen(api: api);
    case Dest.peers:
      return PeerScreen(api: api);
    case Dest.graph:
      return GraphScreen(api: api, initialNode: arg);
    case Dest.semanticDecisions:
      return SemanticScreen(api: api);
    case Dest.occupations:
      return OccupationsScreen(api: api);
    case Dest.aiEvaluation:
      return EvaluationScreen(api: api);
    case Dest.systemHealth:
      return SystemHealthScreen(api: api);
    case Dest.lineage:
      return LineageScreen(api: api);
    case Dest.evidenceTrace:
      return TitledPage(title: entryOf(dest).label, child: specView(api, 'Evidence Trace', input: arg));
    case Dest.dataSources:
      // the run-scoped source registry (the phase-1 data-sources table is not used by the knowledge engine)
      return TitledPage(
          title: 'Sources',
          subtitle: 'Where evidence can come from, and how each source is accessed.',
          child: specView(api, 'Source Registry'));
    case Dest.ingestion:
      return IngestionScreen(apiClient: api, navigate: navigate);
    case Dest.pipelineRuns:
      return TitledPage(title: entryOf(dest).label, child: PipelineRunsScreen(apiClient: api, embedded: true));
    case Dest.dataQuality:
      // the current run's validation checks (the phase-1 data-quality table is not used by the knowledge engine)
      return DataQualityReport(api: api);
    case Dest.courseDrift:
      return CurriculumDriftScreen(api: api);
    case Dest.history:
      return HistoryScreen(api: api, navigate: navigate);
    case Dest.settings:
      return SettingsScreen(api: api, navigate: navigate);
    case Dest.assistant:
      return AssistantScreen(api: api);
    case Dest.preprocessing:
      return TitledPage(
          title: entryOf(dest).label, child: PreprocessingPreviewScreen(apiClient: api, embedded: true));
    default:
      final spec = entryOf(dest).spec;
      return spec == null ? const SizedBox.shrink() : TitledPage(title: entryOf(dest).label, child: specView(api, spec));
  }
}

/// The page title for screens that do not draw their own (tables, technical screens): the shell's top bar carries
/// only the breadcrumb, so each page has exactly one title.
class TitledPage extends StatelessWidget {
  const TitledPage({super.key, required this.title, this.subtitle, required this.child});
  final String title;
  final String? subtitle;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, box) {
      final pad = box.maxWidth < 600 ? AppSpacing.lg : AppSpacing.page;
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(
          padding: EdgeInsets.fromLTRB(pad, pad, pad, 0),
          child: PageHeader(title: title, subtitle: subtitle),
        ),
        Expanded(child: child),
      ]);
    });
  }
}

/// Tabs for a redesigned screen, the last one usually the original data table (kept, never removed).
class TabbedPage extends StatefulWidget {
  const TabbedPage({super.key, required this.labels, required this.builder});
  final List<String> labels;
  final Widget Function(BuildContext context, int index) builder;

  @override
  State<TabbedPage> createState() => _TabbedPageState();
}

class _TabbedPageState extends State<TabbedPage> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    // the view switch sits quietly at the top right; the page's own header (inside the view) stays the one title
    final pad = MediaQuery.sizeOf(context).width < 600 ? AppSpacing.lg : AppSpacing.page;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(
        padding: EdgeInsets.fromLTRB(pad, AppSpacing.xs, pad, 0),
        child: Align(
          alignment: Alignment.centerRight,
          child: SegmentTabs(labels: widget.labels, selected: _index, onSelect: (i) => setState(() => _index = i)),
        ),
      ),
      Expanded(
        child: AnimatedSwitcher(
          duration: AppMotion.normal,
          switchInCurve: AppMotion.curve,
          child: KeyedSubtree(key: ValueKey(_index), child: widget.builder(context, _index)),
        ),
      ),
    ]);
  }
}
