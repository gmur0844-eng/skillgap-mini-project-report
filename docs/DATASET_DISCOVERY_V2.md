# Dataset Discovery V2 (improvement release)

**Baseline:** `5e2416e1ac2aa587`. This is research only. The only acquisition covered here is of documents that are both official and verified to contain topic-level content, and nothing is added to the analysis without a provenance sidecar. It builds on `DATASET_DISCOVERY_REPORT.md` (V1). Every rejection from V1 still stands.

**Method.**
- **Tools:** WebSearch plus WebFetch. No scraping, no Kaggle, and no workaround when a site refused access.
- **Session limit:** part-way through, WebFetch hit its session limit. Every row that could not be opened is marked **not verified**.

## A. Multi-period India job postings

| Dataset | Source | Licence | Geography | Temporal range | Records | Useful fields | Limitations | Legal / access | Integration | Recommendation |
|---|---|---|---|---|---|---|---|---|---|---|
| Supplied snapshot (baseline) | user-supplied export, 4 files | as supplied (owner's responsibility) | IN | 2026-09-22 (1 day) | 100 | title, description, date, company, location, seniority, employment type, URL | a single period | – | integrated | **USE** (population `CURRENT_JOB_DATASET_2026_09`) |
| NCS vacancies registered | OGD India (data.gov.in), MoLE | GODL-India expected; not verified | IN | year-wise to Nov 2023 | aggregate counts | counts only | not posting-level | open | low | **HOLD** (context only, never a skill trend) |
| Naukri JobSpeak index | Info Edge (press releases) | proprietary | IN | monthly to Aug 2026 | aggregate index | sector / role / city growth % | aggregate; methodology proprietary | public web | low | **HOLD** (external context only) |
| Hugging Face Naukri datasets (`muhammetakkurt/naukri-jobs-dataset`, `logiover/naukri-job-scraper-sample-data`) | individual uploaders | not verified | IN | not verified | not verified | not verified | Naukri scrapes; one is a Kaggle mirror | ToS risk | – | **REJECT** |
| `Prakash1709/data_jobs` | individual uploader | not verified | global | not verified | not verified | – | appears to be a copy of `lukebarousse/data_jobs` (rejected in V1) | – | – | **REJECT** |
| Other HF "tech hiring snapshot" datasets | individual uploaders | not verified | not verified | not verified | not verified | – | India coverage and dates unknown | – | – | **HOLD** (card not checked) |
| Zenodo 18086430 "Indian Job Market 2025" | Zenodo depositor | not verified | IN | 2025 | not verified | not verified | may be a report, not postings | – | – | **HOLD** |
| Commercial feeds (Mantiks, Techmap, Bright Data) | vendors | commercial | IN | historical | – | – | paid | contract | – | **REJECT** (not open) |
| Adzuna / Jooble APIs (V1) | vendors | vendor terms | IN (Jooble) | live only | – | search results | keys + terms | owner must accept the terms | medium | **HOLD** (a registered connector in the Source Registry; disabled) |

**Conclusion.** No legitimate, openly licensed, posting-level, multi-period India dataset was found. Multi-period data is **documented as unavailable**. Temporal analysis runs, but on the current population it reports `INSUFFICIENT_DATA` and shows what is missing: at least 2 periods of at least 30 eligible postings each. The acquisition path is the drop folder with a `.source.json` licence sidecar, or a credentialed connector once the owner holds keys.

## B. Official peer curricula (topic-level)

| Dataset | Source | Licence | Regulation / year | Topic-level content | Limitations | Access | Integration | Recommendation |
|---|---|---|---|---|---|---|---|---|
| NIT Warangal B.Tech CSE Curriculum & Syllabi | nitw.ac.in (official) | no licence statement (all rights reserved by default) | 2024-25 | **Yes**: course → topics, with course outcomes (e.g. CS1106 graph traversal: BFS, DFS) | topics are not always grouped into numbered units | public PDF, about 160 pp | generic decoder | **USE** (peer; analysis with attribution, not redistributed) |
| IIT Kanpur Courses of Study 2024: CSE | iitk.ac.in DOAA (official) | none stated | 2024 | **Yes**: a topic paragraph per course (e.g. CS220 pipelining) | paragraph form, no units | public PDF | generic decoder | **USE** (peer; same terms) |
| IIT Delhi CSE course pages | homecse.iitd.ac.in | no notice seen | page dated 2024-12 | one-paragraph description per course | many HTML pages; curriculum year not stated | public HTML | medium | **HOLD** |
| IIT Delhi Courses of Study 2025-26 | home.iitd.ac.in | not verified | 2025-26 | not verified (only the General Rules volume was found) | – | – | – | **HOLD** |
| IIT Madras B.Tech curriculum 2024 batch | iitm.ac.in | none stated | 2024 | **No** (codes and credits only) | – | public PDF | – | **REJECT** (for topic comparison) |
| IIT Bombay CSE curriculum 2022 | cse.iitb.ac.in | none stated | 2022 | **No** (codes and credits) | – | public PDF | – | **REJECT** (for topic comparison) |
| IIT Bombay proposed 2013 curriculum | cse.iitb.ac.in | none stated | 2013, "proposed" | yes | old and not final | public PDF | – | **HOLD** (historical only) |
| IIT Bombay ASC catalogue | portal.iitb.ac.in | – | – | not verified | TLS failure | – | – | **HOLD** |
| NIT Trichy CSE (Feb 2025; 2022) | nitt.edu | not verified | 2025 / 2022 | not verified | not reachable by WebFetch | browser | – | **HOLD** |
| NITK Surathkal B.Tech 2023 | nitk.ac.in | not verified | 2023 | not verified | – | – | – | **HOLD** |
| IIIT Hyderabad CSE | iiit.ac.in | – | 2018-V2 | no (structure only) | – | – | – | **HOLD** |
| Osmania University BE (CSE) | osmania.ac.in | not verified | 2020-21 | not verified | cert error | – | – | **HOLD** |

**Scope rule.** Each peer is its own data entity (institution → programme → curriculum version) with its source URL, SHA-256, academic year, retrieval date and page provenance. Peers are never merged with CBIT or with the AICTE reference. Both chosen documents are parsed by the same generic decoder, with no institution-specific branches.

## C. Occupation taxonomies

| Dataset | Source | Licence | Geography | Version | Useful fields | Limitations | Integration | Recommendation |
|---|---|---|---|---|---|---|---|---|
| ESCO v1.2.1 occupations + **occupation–skill relations** (already in RAW) | European Commission | ESCO reuse terms | EU taxonomy | v1.2.1 | 3,000+ occupations, alternative labels, ISCO groups, essential/optional skills per occupation | EU labels | **already loaded**: the new occupation resolver uses the skill relations as context evidence | **USE** |
| NCO-2015 (Vol I, Vol II-A) | DGE, MoLE | not verified | IN | 2015 (ISCO-08 aligned) | codes, titles, descriptions | PDF only; no official machine-readable file found | high | **HOLD** |
| NCO-2015 third-party data file | R-bloggers post (2025) | not verified | IN | 2015 | machine-readable | unofficial provenance | low | **HOLD** |
| ESCO–O\*NET crosswalk | European Commission | not verified | EU↔US | Dec 2022 | ESCO URI ↔ O\*NET-SOC | may predate ESCO v1.2.1 | medium | **HOLD** (terms to confirm) |
| O\*NET 31.0 (Alternate Titles, Reported Titles) | O\*NET Center, US DOL | CC BY 4.0 expected; licence text not verified this session | US | 31.0 | alternate job titles | US scope; must stay a **separate scope** and never make Indian postings "US-representative" | low (loader exists) | **HOLD** until the owner places the release (registered connector) |

**Conclusion.** Occupation mapping is improved with data that is **already legitimately present**. The ESCO occupation–skill relations let the resolver check the title against the posting's own extracted skills: it confirms or contradicts title candidates and never forces a single occupation. O\*NET and NCO stay registered but disabled sources, each with its next action.

## Acquisition order

1. **NIT Warangal 2024-25 and IIT Kanpur 2024** (official PDFs): the owner downloads them, then they go through the drop folder with a sidecar and are registered as `PEER` documents.
2. **Postings from a second period**, only if legitimately collected. They enter as a separate population with their own provenance.
3. **O\*NET 31.0**, as a separate occupation scope, once the owner places the release.
4. **NCO-2015**, if an official machine-readable version appears.

## Sources

- https://nitw.ac.in/api/static/files/1_B.Tech_Computer_Science_and_Engineering-Curriculum-new-2024-25_2024-7-19-15-40-32.pdf
- https://www.iitk.ac.in/doaa/data/courses-of-study/CSE-CoS.pdf
- https://homecse.iitd.ac.in/all-courses/
- https://curriculum.iitd.ac.in/
- https://www.iitm.ac.in/sites/default/files/Academic%20Curricula%20Files/Curriculum_-_2024_Batch_B.Tech_Version_1.pdf
- https://www.cse.iitb.ac.in/infoczar/lib/exe/fetch.php?media=public%3Adugc%3Acurriculum_format_-_cse_2022_dean_ap_-_semester-wise_curriculum.pdf
- https://www.cse.iitb.ac.in/infoczar/lib/exe/fetch.php?media=public%3Adugc%3Abtech2013curriculum-after-ugpc-comments.pdf
- https://www.iiit.ac.in/curriculum-cse/
- https://www.data.gov.in/catalog/national-career-service-ncs
- https://www.naukri.com/blog/tag/naukri-jobspeak
- https://zenodo.org/records/18086430 (not opened)
- https://huggingface.co/datasets/muhammetakkurt/naukri-jobs-dataset (not opened)
- https://www.ncs.gov.in/documents/national%20classification%20of%20occupations%20_vol%20i-%202015.pdf (not opened)
- https://esco.ec.europa.eu/en/about-esco/data-science-and-esco/crosswalk-between-esco-and-onet (not opened)
- https://www.onetcenter.org/database.html (not opened)
