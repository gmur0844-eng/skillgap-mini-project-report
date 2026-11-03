import 'package:flutter/material.dart';

import '../screens/knowledge_screens.dart';

/// Navigation model: grouped destinations. Every existing screen stays reachable -- either directly, or as the
/// "Table" tab of the redesigned screen that replaced it in the navigation.
enum Dest {
  overview,
  curriculumExplorer,
  industryIntelligence,
  skillContext,
  skillGaps,
  coverage,
  trends,
  curriculumDrift,
  courseDrift,
  peers,
  recommendations,
  concepts,
  topicHierarchy,
  graph,
  semanticDecisions,
  evidenceTrace,
  contradictions,
  industryDemand,
  occupations,
  occupationsV1,
  escoAudit,
  aiEvaluation,
  evidenceStatus,
  humanReview,
  systemHealth,
  lineage,
  dataSources,
  ingestion,
  pipelineRuns,
  dataQuality,
  preprocessing,
  gapReview,
  agents,
  history,
  settings,
  assistant,
}

class NavEntry {
  const NavEntry(this.dest, this.label, this.icon, {this.spec});
  final Dest dest;
  final String label;
  final IconData icon;
  final String? spec; // title of the generic screen spec it renders (for spec-driven destinations)
}

class NavGroup {
  const NavGroup(this.title, this.entries, {this.collapsible = false});
  final String title;
  final List<NavEntry> entries;

  /// A group the sidebar keeps folded until it is opened (the underlying tables and technical views).
  final bool collapsible;
}

/// Information architecture, in the order a person works: start an analysis (or open the published one), read the
/// intelligence, compare and decide, check the evidence, then history and settings. Tables and technical views behind
/// the redesigned screens are folded into "More views", so every existing screen stays reachable without crowding
/// the primary navigation. Destinations (the [Dest] values) are unchanged; only their grouping and labels moved.
const navGroups = <NavGroup>[
  NavGroup('Start', [
    NavEntry(Dest.overview, 'Overview', Icons.space_dashboard_outlined),
    NavEntry(Dest.curriculumExplorer, 'Curricula', Icons.menu_book_outlined, spec: 'Curriculum Explorer'),
    NavEntry(Dest.ingestion, 'New analysis', Icons.add_chart_outlined),
    NavEntry(Dest.assistant, 'Assistant', Icons.forum_outlined),
  ]),
  NavGroup('Intelligence', [
    NavEntry(Dest.skillGaps, 'Skill-gap analysis', Icons.compare_arrows),
    NavEntry(Dest.industryIntelligence, 'Industry demand', Icons.business_center_outlined),
    NavEntry(Dest.courseDrift, 'Curriculum drift', Icons.alt_route, spec: 'Course Drift & Lineage'),
  ]),
  NavGroup('Decisions', [
    NavEntry(Dest.peers, 'Comparisons', Icons.account_balance_outlined),
    NavEntry(Dest.recommendations, 'Recommendations', Icons.lightbulb_outline),
  ]),
  NavGroup('Evidence & quality', [
    NavEntry(Dest.dataQuality, 'Data quality', Icons.checklist),
    NavEntry(Dest.lineage, 'Data lineage', Icons.schema_outlined),
    NavEntry(Dest.dataSources, 'Sources', Icons.source_outlined),
    NavEntry(Dest.evidenceStatus, 'Evidence status', Icons.inventory_2_outlined, spec: 'Evidence Status'),
    NavEntry(Dest.semanticDecisions, 'Semantic review', Icons.psychology_outlined),
    NavEntry(Dest.gapReview, 'Gap review (experimental)', Icons.rule_folder_outlined, spec: 'Gap Review (experimental)'),
  ]),
  NavGroup('Workspace', [
    NavEntry(Dest.history, 'History', Icons.history),
    NavEntry(Dest.settings, 'Settings', Icons.tune),
    NavEntry(Dest.systemHealth, 'System health', Icons.monitor_heart_outlined),
  ]),
  NavGroup('More views', [
    NavEntry(Dest.skillContext, 'Skills', Icons.hub_outlined, spec: 'Skill Intelligence (ESCO context)'),
    NavEntry(Dest.concepts, 'Concepts', Icons.bubble_chart_outlined, spec: 'Concept Explorer'),
    NavEntry(Dest.occupations, 'Occupations', Icons.badge_outlined),
    NavEntry(Dest.graph, 'Knowledge graph', Icons.device_hub),
    NavEntry(Dest.trends, 'Industry trends', Icons.show_chart),
    NavEntry(Dest.industryDemand, 'Demand table', Icons.trending_up, spec: 'Industry Demand'),
    NavEntry(Dest.coverage, 'Coverage depth', Icons.layers_outlined, spec: 'Coverage Depth'),
    NavEntry(Dest.curriculumDrift, 'Concept changes', Icons.timeline, spec: 'Curriculum Drift'),
    NavEntry(Dest.topicHierarchy, 'Topics', Icons.account_tree_outlined, spec: 'Topic Explorer (hierarchy)'),
    NavEntry(Dest.evidenceTrace, 'Evidence trace', Icons.travel_explore, spec: 'Evidence Trace'),
    NavEntry(Dest.aiEvaluation, 'AI evaluation', Icons.verified_outlined),
    NavEntry(Dest.humanReview, 'Human review queue', Icons.how_to_reg_outlined, spec: 'Optional Human Review'),
    NavEntry(Dest.contradictions, 'Graph checks', Icons.rule, spec: 'Contradictions / Graph Checks'),
    NavEntry(Dest.escoAudit, 'Skills reference audit', Icons.fact_check_outlined, spec: 'ESCO Audit'),
    NavEntry(Dest.occupationsV1, 'Occupation table', Icons.work_outline, spec: 'Industry Explorer (occupations)'),
    NavEntry(Dest.preprocessing, 'Preprocessing preview', Icons.compare),
    NavEntry(Dest.agents, 'Analysis agents', Icons.account_tree, spec: 'Analysis Agents'),
  ], collapsible: true),
];

List<NavEntry> get allEntries => [for (final g in navGroups) ...g.entries];

NavEntry entryOf(Dest d) => allEntries.firstWhere((e) => e.dest == d);

String groupOf(Dest d) => navGroups.firstWhere((g) => g.entries.any((e) => e.dest == d)).title;

KnowledgeScreenSpec specNamed(String title) => knowledgeScreens.firstWhere((s) => s.title == title);
