# Data Sources, Licensing, and Provenance

Every dataset used by the analytical pipeline must be traceable to one of the sources
below. Nothing in this table is fabricated; where I could not verify a fact (e.g. an
exact current row count), I've left it unspecified rather than guessed.

## 1. ESCO — primary skill/occupation taxonomy

- **Source:** European Commission, `https://esco.ec.europa.eu/en/use-esco/download`
- **License:** Free to download and reuse; EU classification, published under an open
  reuse policy (confirm exact license text shown on the download page at time of
  download — it is attached to each release).
- **Format:** CSV (also RDF/TTL/XML/JSON-LD available). Choose a specific version
  (e.g. v1.2.1) and a language.
- **What to download:** occupations, skills/competences, skill hierarchy,
  occupation-skill relations, skill-skill relations.
- **How to get it:** the ESCO portal gates the download behind an email + privacy
  acknowledgement (you enter an email, they send a download link). This cannot be
  automated from a sandboxed environment — download it manually once on your machine
  and place the CSVs in `data/raw/esco/`.
- **Backup mirror (dev-only, document if used):**
  `github.com/tabiya-tech/tabiya-open-dataset` — a CSV-formatted mirror of ESCO v1.1.1.
  If you use this instead of the official download, **record `source_name =
  "ESCO via tabiya-open-dataset mirror"` in provenance**, not `"ESCO official"` — the
  version may lag the official release.
- **Retrieval date, version, and file hashes** must be recorded in
  `data/metadata/esco_manifest.json` by `scripts/ingestion/ingest_esco.py`.

## 2. O*NET — occupational/skill reference

- **Source:** `https://www.onetcenter.org/database.html`
- **License:** Creative Commons (stated directly on the download page).
- **Format:** individual tab-delimited `.txt`/`.csv` files, or a single ZIP of the
  whole database.
- **Files this project uses initially:** `Skills.txt`, `Technology Skills.txt`,
  `Knowledge.txt`, `Abilities.txt`, `Task Statements.txt`, `Occupation Data.txt`.
- **Why O*NET in addition to ESCO:** O*NET's "Hot Technology" / "In Demand" flags on
  the Technology Skills file are independently curated by the O*NET program from
  real employer job postings, so they're used as a **cross-check** against this
  project's own job-posting-derived demand statistics (Section 14/54 of the spec) —
  not as the primary taxonomy.
- **ESCO ↔ O*NET crosswalk:** no official crosswalk exists. This project builds its
  own crosswalk table (`skill_crosswalk`) using alias/embedding matching — see
  `docs/methodology.md` (Phase 6+) — and stores a `confidence` and `method` per
  mapping rather than treating the two ID spaces as interchangeable.

## 3. Real job-posting data (labour-market signal) — PRIMARY: India-focused

The project targets the **Indian job market** as primary. O*NET (Section 2) is
kept strictly as a **secondary/backup occupational-skill reference** — it is a
US-government taxonomy, not a labour-market demand source, and its "Hot
Technology" flags are used only as an independent cross-check, never as the
primary Indian demand signal.

| Dataset | Source | Rows | Fields (as listed on the dataset page) | Notes |
|---|---|---|---|---|
| **Jobs on Naukri.com (PRIMARY)** | Kaggle, `PromptCloudHQ/jobs-on-naukricom` | ~22,000 | `company, education, experience, industry, job description, jobid, joblocation_address, job title, number of positions, pay rate, postdate, site_name, skills` | Real postings crawled from Naukri.com, India's largest job board. Has real post dates (`postdate`) → supports the time-series/drift analysis. **License: CC BY-NC-SA 4.0 (non-commercial, share-alike)** — fine for a research/course prototype; flag this explicitly if the project is ever positioned commercially. **Caveat on exact column headers:** the dataset page lists human-readable field names; the literal CSV header casing/spacing may differ slightly (e.g. `Job Title` vs `job title` vs `jobtitle`). Always run `df.columns.tolist()` on the actual downloaded file before trusting the column map in `ingest_job_postings.py` — I have not been able to download and verify the literal file from this sandbox (no internet access here). |
| Naukri Job Listing Dataset (supplementary) | Kaggle, `promptcloud/naukri-job-listing-dataset` | ~24,600 | `job_title, company_name, city, state, country, post_date, job_description, salary_offered, ...` | CC0 (public domain), more recent crawl window (Oct–Dec 2020), useful as a second India-market sample to cross-check demand numbers once the primary is loaded. |
| LinkedIn Job Postings (optional, global comparison only) | Kaggle, `arshkon/linkedin-job-postings` | ~124,000 | job_title, company_name, job_location, job_description, salary, post_date | Kept only as an optional **global** comparison set if you want to contrast India-specific demand against a broader/US-heavy market. Not used by default. Same scraping-provenance caveat as before — a widely-used academic Kaggle dataset, not an official LinkedIn export. |

- **Explicitly excluded:** several Kaggle "job description" datasets are labeled
  by their own authors as **synthetically generated** (e.g. "Job Descriptions
  2025 – Tech & Non-Tech Roles", "Global AI Job Market Trends 2025"). These must
  never be used as the primary analytical dataset per Section 47/48 — at most as a
  clearly labeled DEMO fixture.
- **Pluggability:** `scripts/ingestion/ingest_job_postings.py` now supports a
  `--dataset naukri|linkedin|fixture` flag, each with its own column mapping in
  `app/pipelines/ingestion/job_postings.py`. Adding another real dataset means
  adding one more named column-map dict, not rewriting the pipeline.
- **Currency/salary note:** Naukri salaries are typically strings like
  `"3,00,000 - 5,00,000 PA"` (Indian lakh formatting) or `"Not Disclosed"`.
  `salary_raw` is stored as-is (a string) precisely because of this — no
  numeric parsing/assumption is made at ingestion time.

## 4. University curricula

No ready-made dataset exists; this requires sourcing real, publicly published
curriculum/syllabus documents per institution. **This step needs your input** — either
upload real curriculum PDFs/pages you have the right to use, or tell me which
universities/programmes to target so I fetch their public curriculum pages via search
and web_fetch. Every document ingested is stored with:
`source_name, source_url, retrieval_date, institution, programme, country,
time_period, file_hash`.

## Data source table (as modeled in the DB)

Each row above is registered as a `data_sources` record (see
`backend/app/models/data_source.py`) with `source_type`
(`taxonomy` / `labour_market` / `curriculum`), `license`, `version`, and
`retrieval_date` — this is what powers the "Data Sources" and "Data Lineage" dashboard
views, and answers "where did this data come from?" for any record.
