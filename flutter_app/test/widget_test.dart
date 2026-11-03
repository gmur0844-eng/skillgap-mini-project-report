// Widget smoke tests. No backend runs under `flutter test` (every HTTP request fails), so these
// check the shell, the navigation list and the backend-unreachable state -- never invented data.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:skillgap_dashboard/main.dart';
import 'package:skillgap_dashboard/screens/knowledge_screens.dart';
import 'package:skillgap_dashboard/services/api_client.dart';

void main() {
  testWidgets('wide layout: sidebar lists every knowledge screen and opens on Overview', (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(const SkillGapApp());
    await tester.pumpAndSettle();
    expect(knowledgeScreens.length, greaterThanOrEqualTo(20));
    expect(find.text('Overview'), findsWidgets);
    expect(find.byType(ListTile), findsWidgets);
  });

  testWidgets('narrow layout: navigation moves into a drawer opened from the menu button', (tester) async {
    tester.view.physicalSize = const Size(600, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(const SkillGapApp());
    await tester.pumpAndSettle();
    expect(find.byType(ListTile), findsNothing);
    await tester.tap(find.byTooltip('Menu'));
    await tester.pumpAndSettle();
    // tables behind the redesigned screens are folded under "More views"
    expect(find.text('Demand table'), findsNothing);
    await tester.ensureVisible(find.text('More views'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('More views'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Demand table'));
    await tester.pumpAndSettle();
    expect(find.text('Demand table'), findsOneWidget);
    await tester.tap(find.text('Demand table'));
    await tester.pumpAndSettle();
    expect(find.text('Demand table'), findsWidgets);   // now the screen title
  });

  testWidgets('an unreachable backend shows an error with a retry, not numbers', (tester) async {
    await tester.pumpWidget(const SkillGapApp());
    await tester.pumpAndSettle();
    expect(find.textContaining('Could not load'), findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);
  });

  testWidgets('input-driven screen waits for a key before calling the backend', (tester) async {
    final spec = knowledgeScreens.firstWhere((s) => s.inputParam != null);
    await tester.pumpWidget(MaterialApp(home: KnowledgeScreen(apiClient: ApiClient(), spec: spec)));
    await tester.pumpAndSettle();
    expect(find.text('Enter a skill to load this view.'), findsOneWidget); // the input named in words
    expect(find.textContaining(spec.inputParam!), findsNothing); // never the query parameter (skill_key)
  });
}
