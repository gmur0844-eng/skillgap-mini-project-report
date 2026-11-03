# Demo Guide (5–10 minutes)

> **Historical demo script for run `5e2416e1ac2aa587` (100 postings).** The current release is `c066b227857f9eaf`
> (498 postings, 11 evidence-supported gaps). Use the figures in [FINAL_RELEASE_REPORT.md](FINAL_RELEASE_REPORT.md)
> when presenting; the screen order below still applies.

Every number below comes from the published run **`5e2416e1ac2aa587`**. The job-posting figures describe the 100 supplied postings (India, collected 2026-09-22); they are not necessarily representative of the whole labour market.

## Before the demo (once)

```
# terminal 1 -- API (full app on the validated PostgreSQL database)
cd skillgap-final/backend
ENVIRONMENT=production DATABASE_URL=postgresql+psycopg2://localhost/skillgap_5e2416e1ac2aa587 \
CORS_ORIGINS=http://localhost:8080 ../.venv/bin/uvicorn app.main:app --port 8000
# terminal 2 -- Flutter web build
cd skillgap-final && python3 -m http.server 8080 -d flutter_app/build/web
# Ollama running (optional: without it the app shows MODEL = UNAVAILABLE and keeps working in SAFE_MODE)
```

Open http://localhost:8080. Check `curl localhost:8000/ready` → `READY`.

## The story

| # | Screen | What to show | Real values in this run |
|---|---|---|---|
| 1 | **Overview** | The problem: does a curriculum teach what the job market asks for, and how did it change between versions? | run `5e2416e1ac2aa587`; 3 curriculum PDFs, all health PASS; all 7 analytics gates ALLOWED |
| 2 | **Data Lineage** | Real data only, hash-verified: AICTE model curriculum, CBIT R22 and R22A PDFs, 100 postings, ESCO v1.2.1 | code fingerprint, config hash and content digest shown |
| 3 | **Curriculum Explorer / Topic Explorer** | Decoding the PDFs: every topic has document, course, unit and page | 189 courses, 662 units, 7,625 clean topics (47 misattributed topics quarantined, not guessed) |
| 4 | **Industry Demand** | Observed prevalence (not importance), with the representativeness warning | e.g. **SQL: 5 of 100 postings, 5 companies → SUPPORTED**; 115 demand skills: 5 SUPPORTED, 20 OBSERVED, 90 INSUFFICIENT_EVIDENCE |
| 5 | **Skill Intelligence (ESCO)** | Each skill mapped to ESCO (type, reuse level, groups) | 106 skills mapped to ESCO |
| 6 | **Coverage Depth** | How deeply the target curriculum covers a skill | SQL in R22A: **SUBSTANTIAL** ("2 DIRECT/PARTIAL topics in 2 units") |
| 7 | **Skill Gap (v2)** | Gaps only where evidence allows | 10 COVERED, 13 PARTIAL, 92 INSUFFICIENT_EVIDENCE, 0 MISSING (MISSING needs supported demand) |
| 8 | **Recommendations** | Deterministic rule and full evidence block | **1 recommendation: SQL → EXPAND_EXISTING_TOPIC in 22CSC11N, 22CSE05, 22CSE32, 22CSO02**; 114 suppressed with reasons (WHY_NOT via Evidence Trace) |
| 9 | **Course Drift & Lineage / Curriculum Drift** | What changed R22 → R22A | Courses: 12 retained, 6 recoded, **4 evolved** (e.g. *Formal Language and Automata Theory → Theory of Computation*), 15 added, 14 removed. Concepts: 283 persistent, 185 reworded, 46 added, 18 removed, 34 expanded, 18 reduced |
| 10 | **Evidence Trace** | Enter the SQL skill key (copy it from Industry Demand). It shows the postings → ESCO concept → curriculum topics and pages → coverage → gap → recommendation, with the run id | full provenance chain |
| 11 | **Semantic Decisions / System Health** | Semantic safety | MODEL: CONNECTED (qwen2.5:7b). SEMANTIC: **SAFE_MODE**, because the pre-declared gate failed on the internal benchmark. 42 effects and 21 graph edges blocked; 0 human-validated decisions |
| 12 | **Evidence Status** | Honest limits and what would lift them | TEMPORAL_TREND PARTIAL (1 of 2 periods); PEER_BENCHMARK SOURCE_UNAVAILABLE (IIT curriculum not supplied); OCCUPATION_MAPPING PARTIAL (22%); INDEPENDENT_SEMANTIC_LABELS REVIEW_REQUIRED. Each lists the sources tried and the next action |

## Talking points on safety

- The LLM is an adjudicator, not ground truth. The evidence validator can overrule it. If the model is stopped, System Health shows **MODEL: UNAVAILABLE** and nothing else changes.
- "Insufficient evidence" is never shown as zero, and zero is never shown as missing.
- Nothing is fabricated: no trends from one period, no peer comparison without a peer curriculum, no accuracy claims without independent labels.

## If something is down

| Symptom | Meaning |
|---|---|
| `/ready` 503 `DATABASE_UNAVAILABLE` | PostgreSQL is stopped. Knowledge screens still load (they read GOLD files). |
| Flutter screen "Could not load … · HTTP 5xx · CODE · (request id)" | The API's structured error; the request id is in the API log. |
