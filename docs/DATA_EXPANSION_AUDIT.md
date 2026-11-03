# Data expansion audit

Can legitimate, official evidence make the curriculum intelligence more reliable, broader or temporally meaningful?
This document lists every candidate source and what was decided about it, how the acquired evidence entered the
pipeline, and what changed compared with the release run `84d7737ccb8e4d87`.

Rules followed: official publishers only; no scraping of pages that are not meant for programmatic reading, no login,
no key; dates only as the source states them; nothing fabricated; the release manifest is not edited; an expanded run is
kept only if it materially improves the evidence and passes the same validation.

## 1. Where more evidence would matter

| Dimension | Release state | What more evidence could change |
|---|---|---|
| Industry postings | 100 postings, one collection (user-supplied export, India, 2026-09-22) | demand support of more skills, more confirmed or refuted gaps |
| Time periods | 1 qualifying period → no trend | trends need the same population observed in ≥ 2 periods of ≥ 30 postings |
| Peer curricula | 2 of 6 requested (IIT Kanpur, NIT Warangal) | broader peer perspective |
| Occupations | 22 of 100 postings established | occupation-level demand |
| Reference / taxonomy | AICTE model curriculum, ESCO v1.2.1 full | — (already sufficient for the current discipline) |

## 2. Candidate sources

### Peer curricula (official institution documents)

| Source | Publisher | Topic-level content | Decision | Reason |
|---|---|---|---|---|
| NIT Tiruchirappalli B.Tech CSE, Curriculum and Syllabus (Feb 2025, batches 2024-25) | nitt.edu (CSE department) | yes — units, topics, course outcomes | **USE** | official; one of the four missing requested peers |
| IIT Delhi Courses of Study 2024 — Course Descriptions | home.iitd.ac.in | institute-wide catalogue | HOLD | the B.Tech CSE course list is a separate volume; a whole-institute catalogue must not be compared with one programme |
| IIT Bombay B.Tech CSE (2022) | cse.iitb.ac.in | no — codes and credits only | NOT AVAILABLE | nothing to compare at topic level; the 2013 document with topics is "proposed" |
| IIT Madras B.Tech (2024 batch) | iitm.ac.in | no — codes and credits only | NOT AVAILABLE | same |

### Industry postings (employers' own job boards)

| Source | Access | Dates | Licence / terms | Decision |
|---|---|---|---|---|
| Employer job boards on Greenhouse (Groww, Druva, InMobi, Rubrik, Databricks, MongoDB, Twilio, Stripe) | Greenhouse Job Board API — documented public read API, "authentication is not required for any GET endpoints" | `first_published` per posting | postings published by the employer; used for research analysis with attribution, raw text not redistributed | **USE** (India postings only) |
| Employer job boards on Lever (CRED, Meesho, Zeta) | Lever Postings API — GET needs no key; published postings are publicly viewable | `createdAt` per posting | same | **USE** (India postings only) |
| National Career Service (ncs.gov.in) | encrypted client API; no published documentation | — | — | REJECT (see `ncs_data_source.md`) |
| data.gov.in NCS vacancy statistics | open data | year-wise aggregates | GODL expected | HOLD — counts, not postings; cannot carry skills |
| LinkedIn / Naukri / Indeed listings | websites | — | terms prohibit automated collection | REJECT |
| Hugging Face / Kaggle posting dumps | third-party uploads | unverified | unverified | REJECT |

Every board was checked on 2026-10-01 to answer with India postings and posting dates
(`data/metadata/official_sources.json`, field `verified_on`).

### Occupation evidence

| Source | Decision | Reason |
|---|---|---|
| ESCO v1.2.1 occupations + occupation–skill relations | already used | — |
| NCO-2015 (DGE, MoLE) | HOLD | PDF only; no official machine-readable release |
| O*NET 31.0 | HOLD | US scope; a separate scope at most, never mixed with Indian postings |

No occupation evidence was added: no legitimate machine-readable Indian occupation source exists, and the resolver must
not be forced.

## 3. How the evidence enters

1. `scripts/mac/acquire_official_evidence.sh` (runs `scripts/acquisition/fetch_official_sources.py` on a machine that can
   reach the sites) writes each file to a drop folder with a `.source.json` sidecar: source URL, licence note,
   retrieval time, SHA-256, counts kept and dropped, the date basis.
2. `scripts/acquisition/build_expanded_manifest.py` registers valid files in a **copy** of the manifest
   (`data/metadata/expanded_sources.json`) through the existing drop-folder connector (sidecar validation, duplicate
   detection by SHA-256). The release manifest is unchanged.
3. The pipeline runs on the copy into a separate GOLD root: RAW → BRONZE → SILVER → health gates → GOLD, then all
   analytics.
4. `scripts/audit/compare_runs.py` compares the expanded run with the release: changed outputs (run-scoped ids
   normalised) and every evidence metric before and after, with a verdict.

### Dates of job-board postings

A job board shows the postings that are **open today**. Their publication dates say which postings were still open on
the snapshot day, not how demand changed: older postings that closed are missing. Using those dates as periods would
produce trends of survival, not demand. So a job-board collection is declared `OPEN_POSTINGS_SNAPSHOT`: its postings are
placed in time by the **snapshot date**. One snapshot is one period, so it can never show a trend by itself; repeating
the acquisition on later dates adds periods of the same population. The publication date is kept on every posting for
reading. The supplied export keeps its own publication dates. The two collections are separate populations and their
periods are never compared with each other (the per-population trend rule; the older single-series view now refuses to
mix populations). Tests: `backend/tests/test_official_sources.py`.

**Snapshots on several dates** (`jobs.py`, `industry_intel.py`, `health.py`; tests `test_snapshot_repeats.py`):

* A posting still open on a later snapshot date is the same posting. It is kept once, marked
  `duplicate_kind: SNAPSHOT_REPEAT` on the later record, and its dates are listed in `open_on_snapshots`.
  Other duplicates are `SAME_IDENTITY` or `NEAR_DUPLICATE`.
* The duplicate-rate health check leaves repeats out of both counts and reports how many there were. Otherwise
  collecting more often would fail the check: the first two snapshots had 329 repeats in 1,533 records, so the old
  measure read 25.1 % against a 20 % limit, while real duplicates were 56 of 1,204 distinct records. The limit is
  unchanged.
* Trends count a posting in every snapshot it was open on.
* Trends compare only the boards collected on every date (`board_panel` in the population scope). A board first
  collected on a later date would otherwise show up as a rise in demand. Those boards still count everywhere else.

**Employer text** (`jobs.employer_boilerplate`; settings `industry.employer_boilerplate`; tests
`test_employer_boilerplate.py`):

* Job-board postings carry the employer's own text: an about-us paragraph, values, benefits, equal-opportunity
  wording and social links. Before this change, skills were read from that text too. In the first run over both
  snapshots, "social media management" appeared in 37 % of postings, matched from lines like "follow us on…". "Make
  decisions" became a confirmed gap, with 92 of its matches coming from one employer's values paragraph.
* Two rules decide what is employer text. Such sentences are blanked out before skills are read; offsets are kept, so
  every remaining mention still points at its text, and the raw description is kept as read.
  * **Repeated:** a sentence in at least 80 % of one employer's postings, under at least three job titles, for an
    employer with at least five postings. Employers are never compared with each other, so a requirement line that
    several employers happen to share ("Strong knowledge of SQL") is never touched. Requirements shared by a few
    related roles stay.
  * **Statement:** a sentence with equal-opportunity, accommodation or follow-us wording, in any posting
    (`jobs.EMPLOYER_STATEMENT`). This catches the same statement worded differently across one employer's postings.
    One employer's accessibility paragraph exists in two versions (in 32 and 12 of its 44 postings), so neither
    version reaches 80 %, and each counted "sign language" and "application process" as skills.
* Broader statement cues were tried and dropped because they also matched job lines: "regardless of" ("decisive
  feedback regardless of seniority"), a bare "accommodation" ("travel and accommodation bookings") and "follow … on"
  ("follow up on outstanding receivables"). Tests keep those lines.
* A third rule was tried and dropped: matching runs of five words, to catch near-identical sentences. It removed only
  6 more mentions than whole-sentence matching.
* On the 2026-10 postings, the two rules blank 27 % of the description text in 865 postings. A sample of the removed
  sentences of six employers, every removed sentence that held a technology skill and a random sample of the
  statement sentences were all employer text or section headings. The statement rule's own 136 removed mentions all
  come from equal-opportunity or accommodation sentences. For example, "machine learning" came from company
  descriptions, and Azure from one database vendor's "available across AWS, Google Cloud and Microsoft Azure".
* Kept on purpose: one employer's "Experience in … how to integrate AI into work processes, decision-making…" is in 34
  of its 59 postings. It is a requirement, not a statement.

### Code changes and the release analysis

The changes (CSV posting files, snapshot dates, the population guard) were run on the **release** manifest: 76 of 79
outputs are identical, `temporal_populations.json` gains a `date_basis` field, and two files differ only by run-scoped
ids in example ordering; every metric is unchanged.

## 4. What was acquired (2026-10-01)

| Source | Result |
|---|---|
| 11 employer job boards | 416 India postings (CRED 8, Meesho 56, Zeta 22, Groww 7, Druva 12, InMobi 44, Rubrik 32, Databricks 94, MongoDB 83, Twilio 12, Stripe 46); every posting carries a source date; 0 undated |
| NIT Tiruchirappalli curriculum | fetched (Python's certificate store could not verify the site; the fallback used the system `curl` with normal verification) |
| IIT Bombay, IIT Madras | not available (no topic content in the official documents) |
| IIT Delhi | held (institute-wide catalogue) |

After the pipeline's own gates: 398 of the 416 job-board postings are eligible (18 removed as duplicates of the same
job listed twice).

## 5. Defects the expansion exposed, and their fixes

More evidence is only better if it is read correctly. The first expanded run was checked skill by skill before any of
its findings were trusted; it exposed defects that the 100-posting baseline had been too small to show:

| Defect | Example | Fix | Effect on the release run |
|---|---|---|---|
| Posting identity ignored a job id in the query string | 3 Greenhouse employers' careers pages identify jobs only by `?gh_jid=`: 223 different jobs collapsed into 3 "duplicates", the health gate failed | `gh_jid` is a posting identity (`jobs.posting_identity`) | none (no such URL in the supplied export) |
| A lower-case word matched an all-caps product label | "spend **less** time" → LESS (CSS); "a **spark** of inspiration" (Meesho boilerplate in 56 postings) → SPARK | a lower-case surface of an all-caps taxonomy label is `CASE_SENSE_REVIEW_REQUIRED`, not established | 4 curriculum mentions move to review (incl. one genuine "Apache spark" -- the rule is conservative) |
| Degree abbreviations not read as qualifications | "BS in Computer Science", "MS or Ph.D. in …", "a quantitative discipline such as …" counted as skill demand | qualification context includes BS/MS/BA before "in/or/degree", "Ph.D.", "discipline such as" | none |
| A skill with an ambiguous identity produced a gap | "ML" (label of several taxonomy concepts) MISSING while *machine learning* is COVERED | PARTIAL/MISSING with an AMBIGUOUS identity becomes INSUFFICIENT_EVIDENCE | none |
| The discipline itself treated as a skill | "computer science" recommended to a Computer Science programme | a skill named by the target's discipline is not a gap (`GAP_NOT_ESTABLISHED`) | none |
| Course titles ignored when topic text is thin | "operating systems" PARTIAL although 22CSC15N/22CSC18N are Operating Systems courses | a PARTIAL/MISSING gap whose skill names a target course is kept but marked REVIEW_REQUIRED; its recommendation is withheld (`COURSE_TITLE_CONFLICT_REVIEW_REQUIRED`); it is not a confirmed gap | 3 PARTIAL rows (data analytics, Internet of Things, operating systems) marked for review; no headline changes (none had supported demand) |
| Memory | densifying the posting matrix to count distinct vectors needed > 6 GB at 500 postings | counted on the sparse rows | none |
| Tie order from a hash set | occupation top-skill lists differed between two identical runs | ties ordered by label, then key | none |

Each fix is a regression test (`test_official_sources.py`, `test_consistency_fixes.py`). With the fixes, the release
manifest still reproduces the release analysis except the changes listed in the last column.

## 6. Baseline vs expanded

Release `84d7737ccb8e4d87` vs expanded `c066b227857f9eaf` (`data/evaluation/expansion_comparison.json`):

| | Release | Expanded |
|---|---|---|
| Eligible postings | 100 (one export) | **498** (100 export + 398 employer boards) |
| Companies | 95 | 106 |
| Job-posting populations | 1 | 2 (never compared with each other over time) |
| Qualifying time periods | 1 | 1 per population -- **no trend** (the boards are a single snapshot) |
| Skills eligible for analysis | 120 | 247 |
| Skills with supported demand | 5 | **68** (27 supported, 41 high support) |
| Gap classes (v2) | 10 covered · 13 partial · 0 missing · 92 insufficient | 17 covered · 20 partial · 4 missing · 202 insufficient |
| Confirmed gaps | 0 | **11** |
| Gaps needing review (evidence disagrees) | -- | 5 |
| Recommendations issued | 0 | **11** |
| Withheld for review | 1 (SQL) | 14 |
| Peer curricula | 2 | **3** (+ NIT Tiruchirappalli) |
| Postings with an established occupation | 22 of 100 | **61 of 498** |
| Concepts, topic mappings | 1,318 · 4,426 | unchanged (curriculum evidence unchanged) |

Issued recommendations: expand existing topics for **docker, NoSQL, MySQL, node.js, SPARK, data models, system
design, Agile development**; and **make decisions, financial analysis**, plus an elective for **lead others**.

**Verdict: the expansion materially improves the evidence** -- five times the postings, 68 instead of 5 skills with
enough demand to judge, a third peer, almost three times as many resolved occupations -- and it is kept as the release
candidate once it passes the same validation.

What it does **not** improve, stated plainly:

* **Trends.** Still not established: one snapshot is one period. Repeat `scripts/mac/acquire_official_evidence.sh` on
  later dates; two or more snapshots of ≥ 30 postings each make trends computable.
* **Population mix.** The employer boards list every function (sales, finance, HR) as well as engineering roles, and
  demand is counted over all postings. Three issued recommendations follow from that mix -- *make decisions*,
  *lead others* (transversal competences) and *financial analysis* -- and are correct under the definitions but
  deserve a reviewer's judgement before they reach a curriculum committee.
* **Occupations.** 61 of 498 established (12 %): the share fell because the boards bring many titles the ESCO
  resolver cannot place with confidence; nothing is forced.

## 7. Reproducibility

The expanded manifest was run twice, in separate GOLD roots, with the same code. Both runs produced:

| | Run A | Run B |
|---|---|---|
| Run id | `c066b227857f9eaf` | `c066b227857f9eaf` |
| Content digest | `b5d572db06f48d32…29c8c` | `b5d572db06f48d32…29c8c` |

The full digest of both is `b5d572db06f48d323b9e91e81e0ab6976c2b5ea19e2cff84d549c334bd029c8c`. The two runs are
identical. Before the tie-ordering fix (section 5), a pair of runs had the same id but different digests. That fix is
what makes them identical now.

## 8. Adoption

The expanded manifest replaced `data/metadata/curriculum_sources.json` on 2026-10-02. The release manifest is
archived at `artifacts/archive/manifests/curriculum_sources_release_84d7737ccb8e4d87.json`. The change is purely
additive:
* 1 peer document (NIT Tiruchirappalli);
* 11 job-posting sources;
* the NITT request marked SUPPLIED.

Nothing was removed or edited. The official run was rebuilt from it with `scripts/acquisition/recompute.py --parent
84d7737ccb8e4d87`, so its lineage records the parent, the source changes and the changed outputs
(`data/gold/knowledge/lineage/<run>.json`). The release run directory is not modified. Results:
[FINAL_HARDENING_REPORT.md](FINAL_HARDENING_REPORT.md), section O.

**Default analysis since 2026-10-22: `a6af6bfb7330bdff`** (both job-board snapshots, both employer-text rules). All
gates allowed; 1,148 eligible postings; 16 confirmed gaps (Agile development, CSS, ICT encryption, MySQL, NoSQL, Spark,
data models, distributed computing, Docker, financial analysis, lead others, make decisions, Node.js, risk
identification, system design, web services). The pointer to the previous default (`0534d6e1d06a617f`, 11 confirmed
gaps over 498 postings) is kept in `data/gold/knowledge/previous_default_run.0534d6e1d06a617f.json`; that run and its published copy are
unchanged. Presentation documents and reports dated before 2026-10-22 describe the previous default.

**Default analysis since 2026-10-22 (evening): `2d1f2ebc468fad44`.** The same inputs as `a6af6bfb7330bdff`, run after
the parser learned the AICTE ECE / Mechanical / Civil / Electrical layouts (`docs/DISCIPLINE_SUPPORT.md`). Its only
input difference is the AICTE CSE reference: 30 more clean topics (Engineering Graphics, 2,242 → 2,272). Skill gaps (the
same 16 confirmed), recommendations, courses and course drift are identical (`compare_run_outputs.py`); concepts
1,318 → 1,324, reference-supported concepts 422 → 429, concept-drift counts unchanged (two concept labels reworded), and
the 24 course families regrouped around the new drafting content (28 courses changed family). The pointer to
`a6af6bfb7330bdff` is kept in `data/gold/knowledge/previous_default_run.a6af6bfb7330bdff.json`; that run is unchanged.
