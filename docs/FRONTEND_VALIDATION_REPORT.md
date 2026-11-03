# Frontend Validation Report (Flutter)

**Final run:** `5e2416e1ac2aa587`.

## Environment

The app was compiled, tested and served on a real SDK and backend:

| Item | Value |
|---|---|
| Machine | MacBook Air M5, macOS |
| Toolchain | Flutter 3.47.2 (stable), Dart 3.13.2 |
| Project | `flutter_app/` (package `skillgap_dashboard`), with web platform files from `flutter create --platforms web` |
| Backend | full `app.main` on PostgreSQL 16, database `skillgap_5e2416e1ac2aa587`, production settings |
| Serving | single origin: `WEB_DIR=flutter_app/build/web`; the API serves the app at `http://localhost:8000/app/` (`scripts/mac/serve_demo.sh`) |

## Screens

There are 23 knowledge screens and 5 ingestion screens. Each knowledge screen reads one real endpoint. The screens are defined in `lib/screens/screen_specs.dart`, which is pure Dart, so the same specs drive the app, the static check and the live check.

| Area | Screens |
|---|---|
| Overview and health | Overview, System Health (component cards), Data Lineage, **Evidence Status** |
| Curriculum | Curriculum Explorer, Topic Explorer (hierarchy), Concept Explorer, Coverage Depth |
| Drift and comparison | Curriculum Drift, Course Drift & Lineage, Peer Benchmarking |
| Industry | Industry Explorer (occupations), Industry Demand, Industry Trends, Skill Intelligence (ESCO context), ESCO Audit |
| Gaps and recommendations | Skill Gap (v2), Recommendations, Evidence Trace (skill-key input) |
| Semantics | Knowledge Graph, Semantic Decisions, Contradictions / Graph Checks, Optional Human Review |

States each screen renders:
- loading;
- error with Retry, showing the HTTP status, the error `code` and the `request_id` from the structured API error;
- **DATA NOT AVAILABLE** (`NOT_PRODUCED`, `BLOCKED`, `NOT_LOADED`) with the backend's reason;
- empty list;
- partial page ("showing N of total");
- status badges (for example `PARTIAL`, `SOURCE_UNAVAILABLE`, `REVIEW_REQUIRED`, `SAFE_MODE`, `INSUFFICIENT_EVIDENCE`);
- the representativeness warning on industry-derived screens.

A `null` value is shown as "—", never as 0. The client computes nothing.

The layout is responsive:
- At 1000 px and wider, the app has a sidebar and tables.
- Below 1000 px, navigation moves into a drawer opened by the menu button.
- Below 720 px, rows become cards.

## Automated results

| Check | Result |
|---|---|
| `flutter analyze` | **No issues found** on the release sources (sha256 recorded in `artifacts/mac_final/flutter_final_sources.sha256`). A stray `@override` found on the demo build was fixed. |
| `flutter test` | **4/4 passed** on the release sources: wide shell, narrow drawer, backend unreachable, input-driven screen (`artifacts/mac_final/flutter_test_final.txt`). |
| `flutter build web --release --base-href /app/` | Built. The only notice is a harmless one about CupertinoIcons fonts. |
| Static contract check (`scripts/frontend/static_validate_flutter.py`) | **23/23 screens**: every endpoint is a real GET route; every column and summary key exists in the response. |
| Live check (`tool/live_api_check.dart`) | **23/23 screens** against the running full app: HTTP 200, with the expected list and summary keys present. |

## Manual walkthrough (built-in browser on the Mac, against the running system)

Every value below was compared with the API response for run `5e2416e1ac2aa587`.

| Screen | What was seen | Matches API |
|---|---|---|
| Overview | run id, digest, document health PASS chips, funnel chips | yes |
| System Health | DATABASE HEALTHY, MODEL CONNECTED (qwen2.5:7b-instruct), SEMANTIC **SAFE_MODE** with its reason, effects blocked 42 | yes |
| Industry Demand | SQL 5/5/5 etc., with the representativeness warning | yes |
| Semantic Decisions | 274 decisions | yes |
| Skill Gap (v2) | COVERED / PARTIAL / INSUFFICIENT_EVIDENCE, no MISSING | yes |
| Course Drift & Lineage | status chips (ADDED 15, EVOLVED 4, REMOVED 14, RETAINED 12, RETAINED_RECODED 6), 76 excluded | yes |
| Recommendations | SQL, EXPAND_EXISTING_TOPIC, courses 22CSC11N / 22CSE05 / 22CSE32 / 22CSO02, `MODEL_SUGGESTED` badge, uncertainty shown | yes |
| Evidence Trace | the SQL ESCO key traced to page-level curriculum evidence (course, page, span, raw text) | yes |
| Evidence Status | TEMPORAL_TREND PARTIAL (1 of 2 periods, next action shown), PEER_BENCHMARK SOURCE_UNAVAILABLE, OCCUPATION_MAPPING PARTIAL, INDEPENDENT_SEMANTIC_LABELS REVIEW_REQUIRED | yes |
| Peer Benchmarking | comparison basis states "REFERENCE (model/regulatory curriculum), not a peer institution"; `peer_status` PEER_DATA_NOT_AVAILABLE is in the payload | yes |
| Narrow layout | menu button opens the drawer, and selecting an entry navigates and closes it | yes |

Two walkthrough defects were found and fixed:
- Tables were cut off at narrow widths; they now switch to cards.
- Summary maps were collapsed; they now show as chips or expandable JSON.

An earlier note said "the drawer does not open". That was caused by the browser's emulated viewport, which offset synthetic clicks; at the pane's native size the drawer works. It is also covered by a widget test.

## Observations (not defects)

- The **Peer Benchmarking** screen shows the benchmark payload as expandable JSON. The `PEER_DATA_NOT_AVAILABLE` status sits inside that payload, not as a headline badge. The screen is accurate and states that the comparison is against the reference curriculum, but a headline badge would make the status easier to see.
- The app has not been tested on iOS or Android, only on the web target.
