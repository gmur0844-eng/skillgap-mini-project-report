# Dataset Discovery Report

*Researched on 2026-09-27. No dataset was downloaded or ingested. Every fact below was read from the cited page; anything that could not be verified is marked **not verified**.*

## 1. Executive summary

No freely usable, clearly licensed dataset of **individual Indian job postings across several periods** was found. That is the one input that would unlock trends. The sources fall into four groups.

**Usable now (clear licence, official publisher):**
- **O\*NET 31.0**: CC BY 4.0. A US occupation taxonomy, to be kept as a separate scope.
- **ESCO–O\*NET crosswalk**: published by the European Commission.
- **Indian government aggregate statistics**: NCS vacancy counts, PLFS, NCO-2015. These describe the labour market in aggregate; they are not postings.
- **Official IIT curricula**: IIT Madras, IIT (BHU) and IIT Kanpur publish them on their own websites. They can be used as peer documents, but see §10 for the limits.

**Requires access / terms:** Adzuna API (key required; only a 14-day trial for academic use without written consent), Jooble API (key required), Lightcast (access by request form).

**Licence unclear or unsuitable:**
- Kaggle Naukri/LinkedIn scrapes. They are also excluded by the project rule "no Kaggle".
- freehire 6M postings on Hugging Face: no licence stated.
- Hugging Face `lukebarousse/data_jobs`. It is Apache-2.0, but it covers a single year (2023), is aggregated from job boards, and is a global data-jobs scope.

## 2. Current project data limitations

- 100 postings from one date (2026-09-22), so trends are INSUFFICIENT_EVIDENCE.
- 64/100 titles have no ESCO occupation match.
- No peer curriculum.
- Evidence status is published in GOLD (`intelligence/evidence_status.json`).

## 3. Search methodology

- **Web searches:** NCS, data.gov.in, Kaggle Naukri, Adzuna India, Jooble API, O\*NET licence, ESCO–O\*NET crosswalk, NCO-2015, ESCO versions, IIT Bombay, Madras, Kanpur and BHU curricula, Hugging Face India job postings, Indeed Hiring Lab, ILOSTAT, Lightcast, PLFS, GODL.
- **Pages read directly:** each candidate's own page.
- **Blocked:** data.gov.in catalogue pages (robots.txt). Kaggle dataset pages render no licence or row data to a non-browser fetch, so those facts are **not verified**.

## 4. Dataset candidates — factual table

| Dataset | Source / publisher | Geography | Date range | Records | Job descriptions | Skills | Occupations | Provenance | Licence | Access | Temporal usefulness | Integration effort | Class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| O\*NET 31.0 database | U.S. DOL / ETA (onetcenter.org) | US (SOC) | current release | not verified | occupation descriptions | technology & skills tables | yes (SOC) | official | CC BY 4.0 (attribution to O\*NET 31.0 and USDOL/ETA) | open download | none (taxonomy) | low (loader exists: `ingest_onet`) | DATASET_USABLE |
| ESCO–O\*NET crosswalk | European Commission (ESCO portal) | EU↔US | ESCO v1.2.1 | every ESCO occupation mapped | – | – | yes | official | not stated on page (ESCO portal reuse terms) | free download ("Other Mapping Tables") | none | low | DATASET_FOUND (licence to confirm) |
| NCO-2015 (Vol I code structure, Vol II descriptions) | DGE, Ministry of Labour (PDFs on ncs.gov.in) | India | 2015 | not verified | occupation descriptions | – | yes (NCO, ISCO-08 aligned) | official PDF | not stated | open PDF | none | high (PDF parsing) | DATASET_FOUND |
| NCS vacancies registered (year-wise / quarterly, via Rajya Sabha answer) | OGD Platform India (data.gov.in) | India | 2015-16 to 2023-24 | aggregate counts | no | no | no | parliamentary answer | not stated on the resource; platform uses GODL | open | aggregate totals only | low | DATASET_FOUND (aggregate only) |
| PLFS unit-level data | MoSPI (microdata.gov.in) | India | 2017-18 to 2023-24 and CY 2021–2023 | not verified | no | no | NCO codes not verified | official survey | not verified | catalogue (terms not verified) | yes, but for employment, not postings | high | DATASET_REQUIRES_ACCESS |
| ILOSTAT employment by occupation (ISCO) | ILO | multi-country (India coverage not verified) | annual/quarterly | aggregates | no | no | ISCO | official | not verified | open portal | yes (aggregate) | medium | DATASET_FOUND |
| Indeed Hiring Lab job postings index | Indeed Hiring Lab (GitHub) | US, CA, UK, IE, DE, FR, JP, AU. **Not India** | 2020-02 onwards, daily | index values | no | no | sector categories | documented | CC BY 4.0 | open | yes, but not India | low | DATASET_UNSUITABLE (geography) |
| Adzuna API | Adzuna | country list not verified (India not confirmed) | live + monthly salary history | – | yes (search) | no | categories | API | Adzuna terms: academic use limited to a 14-day trial without written consent; attribution required; 25 req/min | app_id + app_key | limited | medium | DATASET_REQUIRES_ACCESS |
| Jooble REST API (in.jooble.org) | Jooble | India | live only | – | snippets (not verified) | no | no | API | terms not verified | API key by request | none historically | medium | DATASET_REQUIRES_ACCESS |
| Lightcast Open Skills | Lightcast | global | – | – | – | skills taxonomy | – | vendor | not stated; reports say free API access ended | request form | none | medium | DATASET_REQUIRES_ACCESS |
| freehire-jobs (Hugging Face `istrelov/freehire-jobs`) | freehire.me | global incl. some India | ~2026-06 to 2026-08 (preview) | 6,041,471 | yes | derived (LLM) | category | ATS aggregation | **not stated** | open download | 2–3 months | high (size, LLM-derived fields) | DATASET_LICENSE_UNCLEAR |
| `lukebarousse/data_jobs` (Hugging Face) | individual author | 160 countries incl. India | 2023-01 to 2023-12 | 786,000 | no full description | parsed skills | titles | aggregated from job boards | Apache-2.0 (card) | open | one year, data jobs only | medium | DATASET_UNSUITABLE (scope, source ToS unclear) |
| Kaggle Naukri datasets (PromptCloud etc.) | Kaggle uploaders | India | not verified | not verified | yes | partial | no | web scrapes | not verified | Kaggle login | not verified | medium | DATASET_UNSUITABLE (project rule: no Kaggle; scraping ToS risk) |
| IIT Madras B.Tech curricula (2013–2024 batches) | IIT Madras (iitm.ac.in) | India | batch curricula | PDFs | – | – | – | official | "© IIT Madras – all rights reserved" | open PDF | versions for drift | medium | DATASET_FOUND (use as reference evidence only) |
| IIT (BHU) CSE B.Tech course structure 2024-25 | IIT (BHU) | India | 2024-25 | ~60 courses | – | – | – | official | not stated | open PDF | – | structure only (no topics) | DATASET_FOUND (structure only) |
| IIT Kanpur CSE B.Tech programme page | IIT Kanpur | India | Y18–Y21, Y22+ | course list | – | – | – | official HTML | not stated | open | – | few course syllabi linked | DATASET_FOUND (partial) |
| IIT Madras CSE course list (cse.iitm.ac.in) | IIT Madras CSE | India | undated | 200+ courses | – | – | – | official HTML | not stated | open | – | syllabus content not populated | DATASET_UNSUITABLE (no topics) |

## 5. Job-posting datasets

None combines individual postings, India, multiple periods and a clear licence.
- **freehire:** the closest in size and recency, but no licence and mostly US/global.
- **Adzuna / Jooble:** can provide *new* postings over time if the owner obtains keys and accepts the terms. That is the legitimate way to build a multi-period India population going forward.

## 6. India-specific

- **NCS / data.gov.in:** aggregate vacancy counts.
- **PLFS:** survey microdata on employment, not postings.
- **NCO-2015:** occupation taxonomy.
- **Jooble India:** API.
- **Kaggle Naukri scrapes:** excluded.

## 7. Temporal

Only aggregate series are available (NCS quarterly counts, PLFS rounds, ILOSTAT). Each can describe India-level context over time, but none can produce *skill* trends. Skill trends still need postings from ≥ 2 periods with ≥ 30 postings each.

## 8. Occupation datasets

- **Mapping chain:** ESCO v1.2.1 (loaded), then the ESCO–O\*NET crosswalk, then O\*NET 31.0 (CC BY 4.0). O\*NET's alternate titles could raise title matching, but only as a *separate US-SOC scope*. It is never silently mixed with the India population.
- **NCO-2015:** India's own classification (ISCO-08 aligned), but it is only available as PDFs.

## 9–10. Curricula and peer curricula

- **Official IIT pages exist.**
  - IIT Madras curriculum PDFs are all-rights-reserved.
  - IIT (BHU) and IIT Kanpur publish course structures.
  - Detailed per-course topic syllabi are sparse (IIT Kanpur links a few; the IIT Madras CSE course pages hold template text).
- **Peer benchmarking in this engine needs topic-level syllabi.** A structure-only document would give course-level comparison only.
- **Next step:** the owner downloads the official PDF, puts it in `data/raw/curricula/incoming/` with a `.source.json` sidecar (source URL, licence, institution, programme, version, role), then runs `scripts/acquisition/acquire_evidence.py --register`.

## 11. Licensing / access

| Status | Sources |
|---|---|
| Clear | O\*NET (CC BY 4.0); Indeed Hiring Lab (CC BY 4.0, not India); `data_jobs` (Apache-2.0 on the card, but the underlying boards' terms are unknown) |
| Not stated | ESCO–O\*NET crosswalk, NCO PDFs, NCS resource, IIT PDFs |
| Restrictive | Adzuna (14-day academic trial) |
| Unclear | freehire, Kaggle scrapes |

## 12. Schema compatibility

**Job postings:**

| Source field | Target |
|---|---|
| external id | `posting.url` / `source_row` |
| title | `job_title` |
| description | `description` |
| posted date | `posted_date` (this is what enables periods) |
| company | `company` |
| location | `location` |
| skills | recomputed by the engine's own extraction (vendor skill labels are never used as evidence) |
| occupation | recomputed via ESCO; a vendor occupation code is kept as metadata |

**Curricula:** each becomes a manifest `documents[]` entry with a role, then passes through the normal parse → SILVER → health gate.

**Taxonomies:** O\*NET files are read by `app/pipelines/ingestion/onet.py`, as a separate scope.

## 13–19. Provenance, dates, geography, counts, completeness, skills, complexity

These are summarised in the §4 table. Where a record count or date range is shown as **not verified**, it was not confirmed and must be checked on download.

## 20. Risks

- **Scraping and terms of service:** job-board scrapes and Kaggle mirrors.
- **Mixing populations:** US/EU/global data must stay in separate scopes, never merged with the India 2026 population.
- **LLM-derived fields:** freehire skills and categories are model output, not evidence.
- **All-rights-reserved PDFs:** IIT PDFs may be used for analysis with attribution, but not redistributed.
- **Synthetic postings:** allowed only for testing.

## 21. Recommended acquisition order

1. **O\*NET 31.0 + ESCO–O\*NET crosswalk** (clear licence, loader exists), as a separate occupation scope.
2. **Official IIT peer curriculum PDFs**, placed by the owner with a sidecar. Prefer documents with topic-level syllabi.
3. **Jooble or Adzuna keys** (owner accepts the terms). Collect monthly snapshots of India postings as new periods, stored with their own provenance, so that trends become computable after ≥ 2 periods.
4. **NCS / PLFS aggregates** as descriptive context only.

## Final decision table

| Group | Datasets |
|---|---|
| **A. Worth acquiring now** | O\*NET 31.0 (CC BY 4.0); ESCO–O\*NET crosswalk (confirm reuse terms on the ESCO portal); official IIT curricula placed manually with provenance |
| **B. Future sources** | Jooble API, Adzuna API (need keys and terms); NCS/PLFS/ILOSTAT aggregates (context); NCO-2015 (PDF parsing needed); Lightcast (request) |
| **C. Unsuitable** | Kaggle Naukri/LinkedIn scrapes (project rule, ToS); freehire (no licence); `data_jobs` (single year, global data-jobs scope); Indeed Hiring Lab (no India); IIT Madras CSE course list (no syllabus content) |

## Sources

- [O\*NET 31.0 Database Content License](https://www.onetcenter.org/license_db.html) · [O\*NET Database](https://www.onetcenter.org/database.html)
- [ESCO – crosswalk between ESCO and O\*NET](https://esco.ec.europa.eu/en/about-esco/data-science-and-esco/crosswalk-between-esco-and-onet) · [ESCO v1.2.1 is live](https://esco.ec.europa.eu/en/news/esco-v121-live)
- [NCO-2015 Vol I](https://www.ncs.gov.in/documents/national%20classification%20of%20occupations%20_vol%20i-%202015.pdf) · [NCO-2015 Vol II-A](https://www.ncs.gov.in/Documents/National%20Classification%20of%20Occupations%20_Vol%20II-A-%202015.pdf)
- [NCS vacancies registered (OGD)](https://odisha.data.gov.in/resource/year-wise-data-number-vacancies-registered-national-career-service-ncs-portal-20-11-2023) · [OGD NCS catalogue](https://www.data.gov.in/catalog/national-career-service-ncs) · [GODL](https://www.data.gov.in/Godl)
- [PLFS catalogue (microdata.gov.in)](https://microdata.gov.in/NADA/index.php/catalog/PLFS) · [MoSPI PLFS](https://mospi.gov.in/plfs)
- [ILOSTAT data](https://ilostat.ilo.org/data/) · [ILOSTAT India profile](https://ilostat.ilo.org/data/country-profiles/ind/)
- [Indeed Hiring Lab job_postings_tracker](https://github.com/hiring-lab/job_postings_tracker/blob/master/README.md)
- [Adzuna API overview](https://developer.adzuna.com/overview) · [Adzuna terms](https://developer.adzuna.com/docs/terms_of_service) · [Adzuna historical](https://developer.adzuna.com/docs/historical)
- [Jooble REST API](https://jooble.org/api/about) · [Jooble API documentation](https://help.jooble.org/en/support/solutions/articles/60001448238-rest-api-documentation)
- [Lightcast Open Skills access](https://lightcast.io/open-skills/access) · [Lightcast free access ended (post)](https://www.linkedin.com/posts/nick-renner_skillstaxonomy-workforceintelligence-opendata-activity-7431704170384109568-jwkK)
- [freehire dataset announcement](https://freehire.me/blog/2026-08-07-freehire-jobs-dataset-on-hugging-face) · [istrelov/freehire-jobs](https://huggingface.co/datasets/istrelov/freehire-jobs)
- [lukebarousse/data_jobs](https://huggingface.co/datasets/lukebarousse/data_jobs)
- [Kaggle Naukri job listing (PromptCloud)](https://www.kaggle.com/datasets/promptcloud/naukri-job-listing-dataset)
- [IIT Madras academic curricula](https://www.iitm.ac.in/academics/academic-curricula) · [IIT Madras CSE courses](https://www.cse.iitm.ac.in/courses.php?full=1) · [IIT (BHU) CSE course structure 2024-25](https://iitbhu.ac.in/contents/cse/doc/cse_btech_course_2024-25.pdf) · [IIT Kanpur CSE B.Tech](https://www.cse.iitk.ac.in/pages/ProgramBTech.html)
