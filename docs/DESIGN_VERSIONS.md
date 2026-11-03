# Two designs, one application

*Written 2026-10-16. Describes `flutter_app/lib/theme/design_system.dart`, `lib/shell/appearance_panel.dart` and the
Version 2 branches in `lib/widgets/ui_kit.dart` and `lib/shell/app_shell.dart`.*

Every page, component and piece of content is the same in both designs; only the look changes. Each design has a
dark and a light mode. The person switches between them in the **Appearance** panel (palette icon in the top bar, or
Settings → Appearance) and finalises the one to keep. A sun / moon button in the top bar switches the mode.

| | Version 1 · Research report | Version 2 · Atelier |
|---|---|---|
| Idea | an annotated research report | a mix of the two references chosen by the project owner: the Thinking Gods prompt library (dark UI, coral accent, tags, light trails) and the Veloria page (ink and ivory, gold rules, a serif italic word, staged reveals) |
| Night | warm charcoal, brass | ink `#05090E`, cards `#0B121A`, ivory text `#F4EFE6`, coral `#FC4778` for interaction, gold `#C9A96E` for rules and frames, ivory primary button |
| Day | warm paper, brass | ivory `#F4EFE6`, cards `#FBF8F2`, ink-navy text `#0B1622`, deep coral `#B8233F`, deep-gold rules, ink primary button |
| Type | Instrument Serif statements, IBM Plex Sans, IBM Plex Mono | Outfit titles with tight tracking and one word in Cormorant Garamond italic (coral), Instrument Sans reading, Space Mono tags and labels; page eyebrows are capital tags |
| Structure | margin column + reading column, whitespace instead of boxes | each section a rounded card on a hairline ring (it warms to the accent under the pointer); the overview opens in a hero band |
| Navigation | quiet typographic sidebar | sidebar on the page ground with a hairline; the current page on the card tone with a coral dot; a monogram in a gold frame |
| Controls | underlined fields, text tabs | pill buttons, pill filters (selected in ink), pill fields and status labels |
| Motion | section reveals | the same reveals, rules that draw in, light trails behind the overview, a breathing dot on a running analysis, hover rings. Continuous motion runs only in the real application and never with reduced motion |

Pure black and pure white are never used together.

All four palettes meet WCAG AA (4.5:1) for every text and status colour on every background
(`test/workflow_test.dart`).

## How it works

* Design tokens (`AppColors`, `AppTypography`, `AppFonts`, `AppRadius`, `AppShadows`) are getters that read
  `Design.current` (version, brightness). Spacing, layout and motion are shared constants.
* When the design changes, the root widget rebuilds the theme and asks every element to rebuild, so pages keep their
  state (form drafts, filters, an analysis in progress) while their look changes.
* Because tokens are read at build time, expressions that use them are not `const`
  (`scripts/frontend/deconst_tokens.py` made that change mechanically; the `prefer_const_*` lints are off for that
  reason in `analysis_options.yaml`).
* The choice is stored by the backend: `GET / POST /api/v1/settings/appearance`
  (`data/metadata/ui_preferences.json`), so it is the same after a reload and on every device. It has no effect on
  any analysis. If the service cannot be reached, the choice applies in that window and the panel says so.
* Typefaces are bundled (`flutter_app/assets/fonts`, SIL Open Font License, licence texts alongside). Static weights
  were cut from the variable fonts so each declared weight renders as intended; Cormorant Garamond (italic only, for the accent word) is subset to Latin. Before this change no font files
  were bundled, so Version 1 fell back to the platform default font; it now renders with its intended typefaces.

## After finalising

Finalising records the decision; both designs stay in the code until you ask for the other one to be removed.
