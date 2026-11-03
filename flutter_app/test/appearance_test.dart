// The two designs (Version 1 "Research report", Version 2 "Atelier"), light / dark mode, the Appearance panel and its
// stored choice. The fake API answers the real endpoint paths (TEST FIXTURES only).
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:skillgap_dashboard/main.dart';
import 'package:skillgap_dashboard/services/api_client.dart';
import 'package:skillgap_dashboard/shell/appearance_panel.dart';
import 'package:skillgap_dashboard/theme/design_system.dart';
import 'package:skillgap_dashboard/widgets/motion.dart';
import 'package:skillgap_dashboard/widgets/ui_kit.dart';

class _Api extends ApiClient {
  _Api({this.stored});
  final Map<String, dynamic>? stored;
  final List<Map<String, dynamic>> saves = [];
  String? finalised;
  String? finalisedAt;

  @override
  Future<dynamic> getJson(String path, {Map<String, String>? query}) {
    if (path == Appearance.path && stored != null) return Future.value(stored);
    return Future.error(ApiException('no route in test', statusCode: 404));
  }

  @override
  Future<dynamic> postJson(String path, Map<String, dynamic> body) {
    if (path != Appearance.path) return Future.error(ApiException('no route in test', statusCode: 404));
    saves.add(body);
    // like the service: the finalised design is kept until it is finalised again or cleared
    if (body['finalise'] == true) {
      finalised = body['version'] as String?;
      finalisedAt = '2026-10-16T03:00:00+00:00';
    }
    if (body['clear_final'] == true) {
      finalised = null;
      finalisedAt = null;
    }
    return Future.value(
        {'version': body['version'], 'theme': body['theme'], 'finalised': finalised, 'finalised_at': finalisedAt});
  }
}

Future<void> _wide(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1400, 1000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

void _reset() => Design.current.set(version: DesignVersion.v2, brightness: Brightness.dark, clearFinal: true);

void main() {
  setUp(_reset);
  tearDown(_reset);

  test('each design has its own palette in each mode, and changes notify', () {
    expect(Palette.of(DesignVersion.v1, Brightness.dark), Palette.v1Dark);
    expect(Palette.of(DesignVersion.v2, Brightness.light), Palette.v2Light);
    var notified = 0;
    void count() => notified++;
    Design.current.addListener(count);
    Design.current.set(version: DesignVersion.v1);
    Design.current.set(version: DesignVersion.v1); // no change, no notification
    Design.current.set(brightness: Brightness.light);
    Design.current.removeListener(count);
    expect(notified, 2);
    expect(AppColors.bg0, Palette.v1Light.bg0); // tokens follow the design in use
    expect(AppFonts.display, 'InstrumentSerif');
    Design.current.set(version: DesignVersion.v2);
    expect(AppFonts.display, 'Outfit');
    expect(AppRadius.control, BorderRadius.circular(AppRadius.pill)); // Version 2: pill controls
  });

  test('one word of a Version 2 headline is set in the serif italic, and the text is unchanged', () {
    const t = 'No evidence-supported curriculum gap yet';
    final r = AccentHeadline.accentRange(t)!;
    expect(t.substring(r.$1, r.$2), 'curriculum');
    expect(AccentHeadline.accentRange('Overview'), isNull); // a single word stays plain
  });

  testWidgets('ambient motion keeps still under test, so pages settle; the headline reads as written', (tester) async {
    await tester.pumpWidget(MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: Column(children: [
            const SizedBox(height: 200, child: HeroBand(child: Text('hero'))),
            AccentHeadline('Every agent, one clean handoff', style: AppTypography.statement),
            const PulseDot(color: Colors.red),
          ]),
        )));
    await tester.pumpAndSettle(); // would time out if the trails or the pulse kept animating
    expect(find.text('Every agent, one clean handoff'), findsOneWidget);
    expect(find.byType(LightTrails), findsOneWidget);
  });

  test('the stored choice is applied when the app starts', () async {
    await Appearance.load(_Api(stored: {'version': 'v1', 'theme': 'light', 'finalised': 'v1', 'finalised_at': 'x'}));
    expect((Design.current.version, Design.current.brightness, Design.current.finalised),
        (DesignVersion.v1, Brightness.light, DesignVersion.v1));
  });

  test('nothing stored or the service unreachable: the default design stays', () async {
    await Appearance.load(_Api());
    expect((Design.current.version, Design.current.brightness), (DesignVersion.v2, Brightness.dark));
  });

  testWidgets('switching design and mode keeps the page in view and is saved', (tester) async {
    await _wide(tester);
    final api = _Api();
    await tester.pumpWidget(SkillGapApp(apiClient: api));
    await tester.pumpAndSettle();
    expect(find.text('Curriculum intelligence'), findsOneWidget); // Version 2 brand
    final nav = find.widgetWithText(ListTile, 'History');
    await tester.ensureVisible(nav);
    await tester.pumpAndSettle();
    await tester.tap(nav);
    await tester.pumpAndSettle();
    expect(find.textContaining('/ History'), findsOneWidget);

    await tester.tap(find.byTooltip('Switch to light mode'));
    await tester.pumpAndSettle();
    expect(Design.current.brightness, Brightness.light);
    expect(api.saves.last, {'version': 'v2', 'theme': 'light'});
    expect(Theme.of(tester.element(find.byType(Scaffold).first)).brightness, Brightness.light);
    expect(find.textContaining('/ History'), findsOneWidget); // same page

    Design.current.set(version: DesignVersion.v1);
    await tester.pumpAndSettle();
    expect(find.text('Curriculum\nintelligence'), findsOneWidget); // Version 1 brand, rebuilt live
    expect(find.textContaining('/ History'), findsOneWidget);
    expect(find.byTooltip('Switch to dark mode'), findsOneWidget);
    expect(find.byType(CustomPaint), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('the appearance panel compares the designs and finalises one', (tester) async {
    // tall enough that the whole panel (a scrolling list) is built
    tester.view.physicalSize = const Size(1400, 2200);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    final api = _Api();
    await tester.pumpWidget(SkillGapApp(apiClient: api));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Appearance'));
    await tester.pumpAndSettle();
    expect(find.text('Appearance'), findsOneWidget);
    expect(find.text('Version 1 · Research report'), findsOneWidget);
    expect(find.text('Version 2 · Atelier'), findsOneWidget);
    expect(find.textContaining('No design has been finalised yet'), findsOneWidget);

    await tester.tap(find.text('Version 1 · Research report'));
    await tester.pumpAndSettle();
    expect(Design.current.version, DesignVersion.v1);
    expect(api.saves.last['version'], 'v1');

    await tester.tap(find.text('Light'));
    await tester.pumpAndSettle();
    expect(Design.current.brightness, Brightness.light);

    await tester.tap(find.text('Finalise Version 1'));
    await tester.pumpAndSettle();
    expect(api.saves.last, {'version': 'v1', 'theme': 'light', 'finalise': true});
    expect(Design.current.finalised, DesignVersion.v1);
    expect(find.textContaining('is the final design (finalised 2026-10-16)'), findsOneWidget);
    expect(find.textContaining('Saved.'), findsOneWidget);

    // previewing the other design after finalising offers to finalise it instead
    await tester.tap(find.text('Version 2 · Atelier'));
    await tester.pumpAndSettle();
    expect(find.text('Finalise Version 2 instead'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('both designs render the overview at phone width without overflow, in both modes', (tester) async {
    tester.view.physicalSize = const Size(390, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    for (final v in DesignVersion.values) {
      for (final b in Brightness.values) {
        Design.current.set(version: v, brightness: b);
        await tester.pumpWidget(SkillGapApp(key: ValueKey('$v$b'), apiClient: _Api()));
        await tester.pumpAndSettle();
        expect(find.byTooltip('Menu'), findsOneWidget);
        expect(tester.takeException(), isNull, reason: '$v $b');
      }
    }
  });
}
