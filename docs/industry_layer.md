# Industry / ESCO layer — method, safeguards and results

Code: `backend/app/knowledge_engine/{esco_delta,jobs,industry,industry_stage,evidence_guard}.py`, wired into the same
`scripts/pipeline/run_knowledge_pipeline.py` run as the curriculum engine. Config: `engine_config.json → industry`
(declared before the first run on the real postings) plus the project's existing thresholds from `app.core.config`
(`high_demand_threshold` 0.15, `partial_coverage_threshold` 0.4, trend minima), hashed into every run.
Numbers below are from run `81c8820d2bdaa681`.

> **Scope warning (carried in every GOLD file, API response and export):** these results describe the 100 supplied
> job postings (4 files, all posted 2026-09-22, country code IN, 95 companies, 97 distinct titles). They are not
> necessarily representative of the entire labour market, of India, or of any occupation.

## 1. Inputs

| Source | Content | Verified |
|---|---|---|
| `data/raw/jobs/jobs_20260922_054207_ac078854.xlsx` (+ `…054558…`, `…054917…`, `…054942…`) | 25 rows each, 24 columns, sheet `Jobs` | SHA-256 against manifest; 4/4 |
| `data/raw/esco/ESCO_dataset_v1.2.1_delta_csv.zip` | one file `delta.csv`, 163,559 rows | SHA-256 against manifest; CSV header checked |

Job files: 100 unique URLs, 0 missing descriptions (221–9,533 characters, median 1,708), 1 posting date
(2026-09-22), 95 company names, company industry present for 35 postings only. Hiring-manager columns (personal
data) are not carried past RAW.

## 2. ESCO delta — what it is and what can be reconstructed

`delta.csv` columns: concept URI, concept prefLabel, field, old value, new value, action, language.
Actions: Added 106,095 · Removed 52,465 · Updated 4,999. 29 language codes. Concept types by URI:
occupation 88,632 rows, skill 70,857, skill-group codes (`…/skill/A1.9.0`) 40, non-ESCO URIs (NACE 2.1) 4,030;
14,163 distinct URIs; 0 unresolvable action values.

Semantics applied (`esco_delta.py`): the `concept prefLabel` column is the concept's current English label (all 111
English prefLabel updates have new value = that column; 98 are whitespace-only, 3 substantive). English altLabels:
Added → active; Updated → new value active, old value retired; Removed → retired. Nothing depends on row order.

Reconstructed for mapping: **9,298 skill concepts** (URI + prefLabel), **2,283 active English altLabels**, 26
qualifier-stripped labels, **1,058 retired English altLabels** (never matched). Concept level: 0 English skill
concepts added, 0 removed, 9,298 changed; unchanged baseline concepts: **unknown** (not in the file).

Not reconstructable without the full v1.2.x baseline (not supplied): skills the delta does not touch, unchanged
altLabels, skill type (known for 2 concepts), hierarchy and occupation–skill links. So **UNMAPPED means "not in the
supplied delta subset", never "not in ESCO"** — e.g. "Docker", "Linux" and "Excel" labels are absent from it.

## 3. Postings RAW → BRONZE → SILVER

Identity = platform + external id from the URL (LinkedIn job id, Indeed `jk`/hex id, Naukri numeric id), else the
canonical URL; no URL → QUARANTINED. Validation (`validate_job_posting_row`), cleaning (`clean_job_description`) and
near-duplicate detection (same title + company **and** Jaccard ≥ 0.75, `find_near_duplicates`) are the project's
existing functions. Result: **100 ACCEPTED, 0 DUPLICATE, 0 REJECTED, 0 QUARANTINED** (98 ids parsed from URLs — Naukri 46, LinkedIn 32, Indeed 20 — and 2 canonical company-site URLs).

## 4. Skill extraction and ESCO normalization

Vocabulary = the ESCO subset above + the existing curated `TECHNICAL_TOKENS`; matching = the existing
controlled-vocabulary extractor (an indexed variant with regression-tested identical output). Spans and 60-character
context windows are kept for every mention.

Two generic evidence rules (no word lists):

* **Label evidence** — a match on a single ordinary word ("communication", "plan", "Angular"), on the bare word of a
  qualified ESCO prefLabel ("Python" from "Python (computer programming)") or on a 1-character label ("R") does not
  establish the skill sense → ESCO status `INSUFFICIENT_EVIDENCE`, kept visible, excluded from demand.
* **Qualification context** — a skill word inside an education requirement ("Bachelor's degree in Computer Science")
  is recorded as `QUALIFICATION_REQUIREMENT`, not skill demand (20 mentions; "computer science" in 8 postings).

| | count |
|---|---|
| posting skill mentions | 339 (319 SKILL role, 20 qualification) |
| mentions by method | exact_label 207 · normalized_label 73 · alias 40 · technical_token 19 |
| normalized skills | 136 |
| ESCO status of skills | EXACT 58 · NORMALIZED 26 · SEMANTIC_MATCH 0 · AMBIGUOUS 1 · UNMAPPED 8 · INSUFFICIENT_EVIDENCE 43 |
| analytics-eligible skills | 93 (ESCO-mapped 84, unmapped curated tokens 8, ambiguous 1) |
| mentions counted as demand | 163 in 64 postings |
| categories | TECHNOLOGY_TOOL 8 (curated tokens); 128 UNCATEGORIZED — ESCO skill type is not in the delta |

UNMAPPED: aws, azure, docker, gcp, kubernetes, node.js, react.js, tensorflow. AMBIGUOUS: "solving problems" (two
ESCO concepts). `similarity_score` is never called confidence; `score_is_calibrated` is always false.

## 5. Industry demand (posting and company prevalence)

`industry_demand.compute_skill_demand` unchanged: distinct eligible postings mentioning the skill / eligible postings.
Company prevalence (distinct companies / 95 eligible companies) is a separate measure. Support states (config):
OBSERVED ≥ 3 postings; SUPPORTED ≥ 5 postings at ≥ 3 companies; HIGH_SUPPORT ≥ 10 at ≥ 5.

89 skills have demand: SUPPORTED 7, OBSERVED 13, INSUFFICIENT_EVIDENCE 69, HIGH_SUPPORT 0. Highest observed:
use spreadsheets software 7/100; SQL 6/100; Visual Basic (via the ESCO altLabel ".NET"), aws, azure, customer
service, quality standards 5/100 each. No skill reaches the existing 15 % high-demand threshold.

Temporal: one period (2026-09, 100 postings) → trend `INSUFFICIENT_EVIDENCE`, no recency weighting.
Segments: KMeans on posting TF-IDF, k = 8 chosen by silhouette 0.013 (k at the top of the range — essentially no
cluster structure); sizes 19/18/16/14/11/10/9/3, all below 30 → segment gap classification `INSUFFICIENT_EVIDENCE`.

## 6. Curriculum coverage

The same extractor over TOPIC-labelled topic text (never course titles) of each curriculum document;
`curriculum_coverage.compute_curriculum_coverage` unchanged: courses with the skill / valid courses of that document
(target 113, previous version 36, reference 40). Evidence classes kept apart: direct textual vs normalized-only
course counts; concept membership of matching topics (semantic inference, not counted); reference-document coverage
reported separately; human-validated 0. Coverage rows for demanded skills: target 20, reference 7, previous 5.

## 7. Gaps

`gap_classification.classify_skill_gap` unchanged, with `resolve_evidence_value` for None vs zero, plus one guard:
the 100 postings are a mixed-occupation population, so a MISSING result for a skill that **no** curriculum document
of the discipline mentions (target, previous version, reference) becomes `INSUFFICIENT_EVIDENCE /
DISCIPLINE_RELEVANCE_UNESTABLISHED` and goes to review.

89 gaps: **MISSING 1 · PARTIAL 20 · COVERED 0 · INSUFFICIENT_EVIDENCE 68** (all DISCIPLINE_RELEVANCE_UNESTABLISHED).
With the existing 40 %-of-courses partial threshold, any skill taught in fewer than 46 of 113 courses is PARTIAL.

## 8. Recommendations

The existing rule engine (`generate_recommendation`) runs only when the gap is MISSING/PARTIAL, support is SUPPORTED
or HIGH_SUPPORT and the ESCO mapping is not AMBIGUOUS. Every gap gets either a recommendation or a structured
suppression. Result: **1 recommendation** — SQL, EXPAND_EXISTING_TOPIC in 22CSC11N, 22CSE05, 22CSE32, 22CSO02
(uncertainty: support SUPPORTED, not HIGH_SUPPORT) — and **88 suppressions** (reason codes, a gap can have several:
INDUSTRY_SUPPORT_BELOW_THRESHOLD 82, GAP_INSUFFICIENT_EVIDENCE 68, ESCO_MAPPING_AMBIGUOUS 1).
Recommendations are `MODEL_SUGGESTED`, `is_source_evidence = false`.

## 9. Circular evidence

`evidence_guard.py`: manifest sources must be original files under `data/raw/{curricula,jobs,esco}` (or the human
decisions file) and never under `data/bronze|silver|gold`; records entering extraction/coverage must be EXTRACTED
(or HUMAN_VALIDATED). Tests prove a recommendations file and recommendation records are refused. The database
enforces `is_source_evidence = false`.

## 10. Health gate (industry)

Checks and final values: hashes 4/4 · postings 100 (≥ 30) · duplicate rate 0.0 (≤ 0.2) · missing descriptions 0.0
(≤ 0.05) · eligible 100 (≥ 30) · extraction yield 0.64 (≥ 0.5) · eligible skills 93 (≥ 10) · ESCO mapping yield 0.903
(≥ 0.2) · ambiguous ratio 0.007 (≤ 0.2) · provenance 1.0 · ESCO concepts 9,298 · baseline regression 0 drop → **PASS**.
A FAIL blocks `industry_demand`, `industry_gap` and `recommendations` (tested with a simulated collapse).

## 11. Evaluation

No human-labelled ESCO benchmark exists (`NO_HUMAN_LABELLED_BENCHMARK`). Assistant-labelled sample of 60 posting
mentions (`data/evaluation/industry_mention_sample.json`): counted-as-demand precision **0.968** (30/31), recall
**0.698** (30/43), accuracy 0.767; 13 genuine skill mentions excluded by the label evidence rule (e.g. "communication
skills", "accounting", "typography", "Chef"); sense of the ESCO concept / token correct for **24 of 28** counted
mentions ("control systems" inside "version control systems", ESCO "architectural design" = buildings, "GCP" =
Good Clinical Practice, "build trust" in a company tagline). One rule was widened after labelling (see the file's
caveat); no threshold was changed.

## 12. Limitations

* 100 postings from one day, mostly non-software roles; prevalences of 5–7 % rest on 5–7 postings.
* ESCO is a partial delta subset; 8 skills unmapped for that reason; skill types unknown.
* Exact label matching has no context model: mentions in company descriptions count (2 of 5 "AWS" mentions are an
  investor list and a service-line list), and word-sense errors remain (above).
* The label evidence rule trades recall for precision (43 skills held back, incl. "communication" in 52 postings, "plan" 12, "accounting" 8, "agile" 6).
* The discipline guard uses textual mentions in curriculum documents; a relevant skill named differently is held back.
* No trend (single date); segments have no real structure; no human has reviewed any item (review queue: 14 items).
