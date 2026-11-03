# Frontend Redesign Report (Flutter, improvement release)

The dashboard was redesigned inside the existing Flutter app:

- Flutter was not replaced, and no API contract changed. One field was added to `/api/v1/semantic/evidence`, and it is additive.
- There are no static mockups and no invented data. Every number on screen comes from a backend endpoint that reads the published GOLD run.
- Every existing screen is still reachable. Most are reachable directly; the rest are the "table" tab of the redesigned screen that replaced them in the navigation.
- The 4 original widget tests are kept unchanged.

## 1. Design system — `lib/theme/design_system.dart`

- **Tokens:**
  - `AppColors`: dark-first palette (backgrounds `bg0/bg1`, `surface`/`surfaceRaised`/`surfaceSunken`, `border`, `text`/`textMuted`/`textFaint`, and `primary`, `secondary`, `success`, `warning`, `danger`, `info`, `neutral`);
  - `AppTypography`: display, title, section, body, muted, caption, overline, metric and mono styles;
  - `AppSpacing` (2–32 px), `AppRadius`, `AppShadows` (card, glow), and `AppMotion` (150 / 250 / 380 ms, ease-out cubic).
- **Status visuals:** `StatusStyle` maps every status the backend emits to a tone (good / warning / danger / info / neutral), an icon and a human label.
  - Examples: `SAFE_MODE`, `PEER_DATA_PARTIAL`, `INSUFFICIENT_DATA`, `SUPPORTED`, `MODEL_SUGGESTED`, `CONTRADICTED` and others.
  - A status is never shown by colour alone. Every badge carries icon, text and colour, plus a `Semantics` label (`status …`).
- **Theme:** `buildAppTheme()` provides a Material 3 dark theme (cards, inputs, chips, data tables, dividers). `SkillGapApp` uses it.

## 2. Components — `lib/widgets/ui_kit.dart`

| Component | What it does |
|---|---|
| `ApiView` | Loads one endpoint and renders four states: loading (static skeleton, `Semantics('Loading')`), error, not produced (`DATA NOT AVAILABLE (state)` with the backend's reason), and data. The error state shows "Could not load X", the HTTP status / code / message and a Retry button; raw exceptions are never shown. |
| `StatusBadge`, `StatusBanner` | Badge and prominent banner (the peer badge sits at the top of its page and is never inside an expansion). |
| `KpiCard` | Value, label, caption, source and icon. No invented deltas. |
| `ScopeBanner` | Population, geography, postings, date range, granularity and sources. |
| `SectionCard`, `PageHeader`, `PageFrame` | Layout: max width 1280, 16 px gutter under 600 px width. |
| `SegmentTabs`, `TabbedPage` | Tabbed screens. |
| `BarList`, `DistributionBar` | Categorical distributions, always with text labels. |
| `KeyValueList` | Labelled facts. |
| `EvidencePanel`, `EvidenceStep` | Progressive disclosure of evidence chains. |
| `EmptyState`, `ErrorState`, `DataNotAvailable`, `SkeletonPage` | The polished non-data states. |

## 3. Shell and navigation

- **Shell** (`lib/shell/app_shell.dart`):
  - **Wide screens (≥ 1000 px):** a collapsible sidebar (272 ↔ 76 px, animated). In the collapsed state each item is an icon with a tooltip.
  - **Narrow screens:** a drawer opened from the "Menu" button.
  - **Top bar:** breadcrumb (`Group / Screen`), page title, global search, a data-freshness chip and the semantic-mode badge. The chip reads "Run … · N postings" from `/api/v1/overview`, shows "Checking status…" while loading, and "Status unavailable" if that fails.
  - **Page changes:** animated with `AnimatedSwitcher` (250 ms).
- **Navigation** (`lib/shell/navigation.dart`) — six groups:

| Group | Screens |
|---|---|
| Overview | Overview, Curriculum Explorer, Industry Intelligence, Skill Intelligence |
| Intelligence | Skill Gaps, Coverage Depth, Industry Trends, Curriculum Drift, Course Drift & Lineage, Peer Benchmarking, Recommendations |
| Knowledge | Concept Explorer, Topic Explorer, Knowledge Graph, Semantic Decisions, Evidence Trace, Contradictions / Graph Checks |
| Industry | Industry Demand, Occupations, Industry Explorer (occupations v1), ESCO Audit |
| Governance / Validation | AI Evaluation, Evidence Status, Optional Human Review |
| System | System Health, Data Lineage, Data Sources, Dataset Upload / Ingestion, Pipeline Run Status, Data Quality, Preprocessing Preview |

- **Global search** (`lib/shell/search_dialog.dart`):
  - Debounced call to `GET /api/v1/search`.
  - Result types: COURSE, TOPIC, CONCEPT, SKILL, ESCO, OCCUPATION, COMPANY, JOB.
  - Routing: concepts, courses and topics open the graph explorer on that node; skills open the evidence trace; occupations open Occupations.

## 4. Redesigned screens — `lib/screens/premium/`

| Screen | Endpoints | Notes |
|---|---|---|
| Overview | `/api/v1/overview` | Hero (last run, target curriculum, industry scope), KPI cards with source, and questions: where are the gaps, what is changing, industry trends, how trustworthy is the evidence, peers, occupations. |
| Industry Intelligence | `/industry/intelligence`, `/dimensions`, `/clusters`, demand table | The denominator (distinct eligible postings) is always stated. Clusters show an empty state when none pass the thresholds (0 in the final run). |
| Industry Trends | `/industry/temporal-trends` | Population banner per population. With one period the screen shows **"Temporal evidence required"**: what exists, what is required, why, and which sources can provide it, with a "View data sources" button. No trend arrow is drawn. Tabs: Emerging / Declining / Persistent / Trend table. |
| Skill Gaps | `/intelligence/gaps`, `/evidence-trace` | Gap cards with filter chips. "Why?" expands the evidence chain: industry → ESCO → curriculum → gap → recommendation. No confidence %. |
| Recommendations | `/intelligence/recommendations` | Action + skill, recommendation / support / evidence states, target courses, reasons, and the evidence chain on demand. Never a confidence %. |
| Peer Benchmarking | `/peers/status`, `/benchmark`, `/differences` | The **PEER DATA** banner comes first: available peers, missing peers with reasons, and how to add one. Target and comparison document cards show institution, programme, version, academic year and source. Five separate coverage levels (never one score, never a ranking), a skill card and a depth card, difference views with page evidence, and industry alignment. |
| Knowledge Graph | `/search`, `/semantic/evidence` | Explorer over real edges only: relationship filter, click a neighbour to recentre, Back, and each edge shows its method and evidence status. With no node selected there is an empty state, never a decorative graph. The table tab is the original spec. |
| Semantic Decisions | `/semantic/decisions` | Shown as trust information. The SAFE MODE banner appears when no decision is applied; KPIs cover model-seen, applied, blocked and human-validated counts. Each card shows left ⇄ right, kind, relationship, decision / validated states, whether the decision was applied, and the evidence and provenance. Paged, 50 per page. |
| Occupations | `/occupations/resolution`, `/analysis` | Resolution states, context support (CONFIRMED / CONTRADICTED / …), and profile candidates; analysis per occupation and per ISCO group. |
| AI Evaluation | `/evaluation/semantic` | Pending-independent-labels banner and the promotion gate criteria. Any preview is labelled **INTERNAL DEVELOPMENT PREVIEW — not independent**. |
| System Health | `/health` | Component cards (API, database, model, semantic, data, pipeline). A model in SAFE MODE does not make the system unready. |
| Data Lineage | `/intelligence/lineage`, `/lineage/recompute` | SOURCE → RAW → BRONZE → SILVER → GOLD → ANALYTICS, built from the stages the run actually executed; fingerprints; sources with sha256; a recomputation card (source changes, affected analytics, outputs changed / added / unchanged vs the parent run). |

Legacy screens (Data Sources, Ingestion, Pipeline Runs, Data Quality, Preprocessing) are embedded unchanged. Some still render their own app bar inside the shell; this is noted as a remaining UX issue.

## 5. States and accessibility

- **States:** every data view has loading (skeleton), error (message plus Retry), empty (explanation) and not-produced (`DATA NOT AVAILABLE` plus the backend's reason) states.
- **Motion:** 150–380 ms, within the 120–450 ms target.
- **Accessibility:**
  - status never relies on colour alone;
  - icons have semantic labels where they carry meaning (edge direction, "compared with");
  - tooltips on every icon-only control;
  - text contrast follows the dark palette.
- **Data handling:** search, filter chips, sorting (spec tables) and pagination (semantic decisions, differences).

## 6. Tests

- **`test/widget_test.dart`** — the 4 original tests, unchanged:
  - wide layout;
  - narrow drawer;
  - unreachable backend shows "Could not load" and Retry exactly once;
  - input-driven screen waits for a key.
- **`test/premium_ui_test.dart`** — 13 new tests. They use a `FakeApi` subclass of `ApiClient` whose small fixed payloads are shaped like the backend responses; these are test fixtures, never used by the app. They cover:

| Area | What is checked |
|---|---|
| Overview | KPIs, SAFE MODE badge, freshness chip |
| Loading | skeleton shown, no numbers |
| Navigation | tapping in the sidebar changes the breadcrumb, and the target screen shows its own error state |
| Collapsed sidebar | every destination still reachable by tooltip |
| Responsive | phone width (390 px) renders without overflow; Menu and Search are present |
| Semantic decisions | a blocked effect is shown as SAFE MODE, not as a failure; "not human-validated" is shown |
| Peer unavailable | PEER DATA NOT AVAILABLE banner at the top, naming the missing peer and how to add one |
| Trends | one period shows "Temporal evidence required", with no trend icons |
| Recommendation details | states shown, no confidence %, evidence expands |
| Empty | recommendations explain why the list is empty |
| Not produced | lineage recomputation shows DATA NOT AVAILABLE with the reason |
| Unit tests | stage → lineage-layer mapping; status labels never use raw underscores |

- **Static validator (no SDK needed)** — `scripts/frontend/static_validate_flutter.py` now also checks that every endpoint literal in the redesigned screens and shell is a real GET route. Result:
  - 23 / 23 spec screens pass;
  - 22 / 22 redesigned endpoints exist;
  - 0 placeholder words.
- **Live check** — `tool/live_api_check.dart` now also calls every endpoint the redesigned screens read, the peer differences for a real comparison, and the graph evidence for a real concept.

## 7. Mac validation

See `IMPROVEMENT_RELEASE_REPORT.md §13`: `flutter analyze`, `flutter test`, `flutter build web`, the live API check, and the browser walkthrough.

## 8. What was not changed

- No analytics were changed for visual reasons.
- No endpoints were removed.
- No screens or tests were removed.
- No confidence percentages or rankings were introduced.
