# Analytics Methodology: Industry Demand, Curriculum Coverage, Alignment

This phase turns `ExtractedSkill` evidence into GOLD-layer metrics. Every
number below is one of four kinds — keep them distinct when reading results:

- **OBSERVED DATA**: a raw fact from the source (e.g. "this posting mentions Python").
- **CALCULATED METRIC**: a deterministic function of observed data (e.g. demand_percentage).
- **METHODOLOGICAL THRESHOLD**: a configured cutoff used to label a metric (e.g. `high_demand_threshold`).
- **INTERPRETATION**: a human reading of the above — this document's prose, never the API's numbers.

## Industry demand

```
demand_percentage = postings_with_skill / eligible_job_postings * 100
```
- **eligible_job_postings**: all `JobPosting` rows with `is_duplicate = 0` at the time of the run — i.e. the analyzed dataset, not "the Indian job market". `total_relevant_postings` on every `SkillDemand` row records this exact denominator.
- **postings_with_skill**: DISTINCT postings with at least one `ExtractedSkill` row for that skill (`mapping_status = "mapped"`). A skill mentioned 8 times in one posting counts that posting once — see `app/analytics/industry_demand.py::compute_skill_demand`.
- Only mentions with `job_posting_id` set and `mapping_status = "mapped"` are counted. Unmapped mentions carry no canonical skill to attribute demand to.
- **Correct phrasing**: "Python appeared in X% of eligible job postings in the analyzed dataset." **Never**: "Python is demanded by X% of Indian jobs" — the dataset is a sample, not a census.
- ESCO is never a demand source. ESCO only supplies the canonical skill a mention resolves to.

## Curriculum coverage

```
coverage_percentage = courses_with_skill / eligible_courses * 100
```
- **eligible_courses**: all `Course` rows at the level requested (`level="overall"` = every course in the DB; programme/institution-level slicing is supported by the same function with a filtered `eligible_course_ids` set, but is not run automatically — see "Known limitations" below).
- **courses_with_skill**: DISTINCT courses with at least one mapped mention, resolved from any of: the course title itself, a `CurriculumTopic` under one of its modules, or a `CourseLearningOutcome` belonging to it. A skill mentioned 5 times in one course's topics counts that course once.
- `topics_with_skill` / `outcomes_with_skill` are similarly deduped by distinct topic/outcome id, not raw mention count.

## Skill-set alignment (Jaccard)

```
jaccard_alignment_score = |industry_skills ∩ curriculum_skills| / |industry_skills ∪ curriculum_skills|
```
- `industry_skills` = the set of canonical skill ids with a `SkillDemand` row in the selected demand run.
- `curriculum_skills` = the set of canonical skill ids with a `CurriculumSkillCoverage` row in the selected coverage run.
- This is a documented, transparent set-overlap measure — not fuzzy, not learned. See `app/analytics/skill_set_alignment.py`.

## TF-IDF text alignment

- Per course: `text_alignment_score` = cosine similarity between a TF-IDF vector of that course's (title + topics + outcomes) text and a TF-IDF vector of the aggregate reference corpus (all eligible job postings' `clean_description`, concatenated).
- Vectorizer config (`ngram_range=(1,2), min_df=1, stop_words="english"` by default) is stored on every `AlignmentResult` row (`method_config_json`) along with `vocabulary_size` and `reference_doc_length` — so the exact configuration behind any score is always reconstructable.
- **CALCULATED METRIC, not causal**: a high `text_alignment_score` means the course's text shares vocabulary with the job-posting corpus. It says nothing about teaching quality, depth, or currency.
- Courses with no extracted text are skipped, not scored as 0 — see `skipped_entity_ids` in the raw result / `courses_skipped` in the CLI output.

**Population fields, precisely defined** (fixed after an audit found `source_population_size` had been set to the broader eligible count rather than the actual TF-IDF corpus contributor count):

| Field | Meaning |
|---|---|
| `AlignmentResult.eligible_source_population_size` | The broader eligible population *before* filtering for usable text — e.g. every non-duplicate `JobPosting`, including ones with an empty/null `clean_description`. |
| `AlignmentResult.source_population_size` | The actual number of source documents that contributed non-empty text to the TF-IDF corpus — i.e. `eligible_source_population_size` minus postings with no usable text. This is what "the reference corpus was built from N documents" should cite. |
| `AlignmentResult.target_population_size` | The number of target-side documents (courses) that actually contributed text and received a score — courses skipped for having no text are excluded, so this is already an "actual contributor" count, not a broader eligible count. |

These two counts (`eligible_source_population_size` vs `source_population_size`) are not interchangeable and must never be conflated — a dataset with many postings but few having usable cleaned text would otherwise silently overstate how much real text backed a given `text_alignment_score`.

## Threshold-based classification (NOT a recommendation)

`classify_demand_coverage()` labels each skill using two configured thresholds (`high_demand_threshold`, `high_coverage_threshold` — both in `app/core/config.py` / `.env`, both `0.15` by default, i.e. 15%). The threshold values actually used are stored per-row (`SkillAlignment.thresholds_used_json`) so a later config change never makes an old result ambiguous. This classification is descriptive, not prescriptive — it is explicitly not called a "recommendation" anywhere in the code.

**Seven possible classifications, not four** — evidence-availability states come first:

| Classification | Meaning |
|---|---|
| `INSUFFICIENT_EVIDENCE` | Neither an industry population nor a curriculum population exists for this skill/run. |
| `NO_INDUSTRY_EVIDENCE` | No industry population existed for this run (e.g. zero eligible job postings) — curriculum evidence may still be present. |
| `NO_CURRICULUM_EVIDENCE` | No curriculum population existed for this run — industry evidence may still be present. |
| `HIGH_DEMAND_LOW_COVERAGE` / `HIGH_DEMAND_HIGH_COVERAGE` / `LOW_DEMAND_HIGH_COVERAGE` / `LOW_DEMAND_LOW_COVERAGE` | Both sides have a real population; the two measured percentages (each possibly a genuine 0%) are compared against the thresholds normally. |

**Why this matters — None is not zero.** A skill can be genuinely absent from `SkillDemand` for two entirely different reasons: (a) the industry population existed (e.g. 500 eligible postings) and this specific skill simply had zero matches — a real, informative measurement — or (b) there was no industry population at all this run (e.g. 0 eligible postings, nothing was ever checked). Silently doing `value = value or 0.0` collapses these into the same number and produces a false claim ("this skill has 0% demand") in case (b), where the honest answer is "we don't know — no data was available." `app/analytics/skill_set_alignment.py::resolve_evidence_value()` makes this decision explicitly and is unit-tested (`test_resolve_evidence_value_*` in `test_skill_set_alignment.py`), and `classify_demand_coverage()` never performs a None→0.0 substitution itself — a caller passing `None` always yields one of the three evidence-status labels above, never a HIGH/LOW classification.

## No arbitrary composite score

TF-IDF text alignment and skill-set (Jaccard) alignment are **never combined** into one weighted number. `AlignmentResult.combined_alignment` exists as a column but is intentionally left `NULL` this phase — a unified score, if ever needed, requires its own validated methodology, decided separately.

## GOLD artifacts (RAW → BRONZE → SILVER → GOLD)

Every analysis function writes a `records.jsonl` GOLD artifact via the existing `artifact_writer`, at:
```
data/gold/industry_demand/<run_id>/records.jsonl
data/gold/curriculum_coverage/<run_id>/records.jsonl
data/gold/skill_alignment/<run_id>/records.jsonl
data/gold/tfidf_alignment/<run_id>/records.jsonl
```

## Re-run / idempotency behavior

GOLD analysis functions use **versioned-snapshot** semantics, not skip/replace: every run creates a new `AnalysisRun` and a fresh set of GOLD rows tagged with that run's id. Nothing is deduplicated or overwritten across runs — old snapshots remain for audit (e.g. comparing a metric across two points in time). The API and CLI never scan all historical GOLD rows; they always resolve "the current answer" via `select_latest_successful_run()` (`app/analytics/run_selection.py`, unit-tested), which picks the most recently *succeeded* run for a given `dataset_name` — a failed re-run never shadows a prior good result. This is a deliberately different idempotency model from ingestion/extraction (which use content-hash skip-if-exists, because re-ingesting raw data would be a genuine unwanted duplicate); GOLD results are derived, not primary.

## Known limitations

- Programme/institution-level coverage slicing is implemented in the pure function but not invoked automatically — running it today, with only demo/fixture-scale data, would produce misleadingly precise-looking percentages over tiny populations.
- No time-series/segmented demand yet (`SkillDemand.time_bucket = "overall"` always) — segmentation by role/location/experience is supported by the schema but not computed this phase, per the "don't over-engineer without real data" guidance.
- All of the above is unit-tested with small fixtures only. **REAL-DATA ANALYTICS PENDING** — see the final report for exact commands once real ESCO/Naukri/curriculum data and a live database are available.

## Test commands

```bash
cd backend
python3 -c "
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
mods = ['test_industry_demand','test_curriculum_coverage','test_skill_set_alignment','test_tfidf_alignment','test_run_selection']
for m in mods:
    mod = __import__(m)
    for n in dir(mod):
        if n.startswith('test_'): getattr(mod, n)()
print('ok')
"
```

## Real-data execution commands (once data is available)

```bash
python scripts/analysis/run_analytics.py --all
# or individually, in dependency order:
python scripts/analysis/run_analytics.py --stage demand
python scripts/analysis/run_analytics.py --stage coverage
python scripts/analysis/run_analytics.py --stage alignment
python scripts/analysis/run_analytics.py --stage tfidf
```
