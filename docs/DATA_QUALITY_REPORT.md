# Data Quality Report — run d658c97abebca9f5

> The job-posting results describe the supplied job-posting dataset. They are not necessarily
> representative of the entire labour market.

## 1. Sources (all hash-verified against the manifest)

| Source | Role | Pages / rows | Health |
|---|---|---|---|
| AICTE UG CSE model curriculum (2022 revised) | REFERENCE | 214 pages | PASS |
| CBIT B.E. CSE R22 (2022-23; semesters I–IV only) | PREVIOUS_VERSION | 67 pages | PASS |
| CBIT B.E. CSE R22A (2024-25; semesters I–VIII) | TARGET | 246 pages | PASS |
| 4 supplied job-posting exports (India, collected 2026-09-22) | industry | 100 postings | PASS (10/10 checks) |
| ESCO v1.2.1 English, full taxonomy plus delta | taxonomy | 13,939 skill concepts | loaded |

- **Peer institution:** none was supplied. The IIT curriculum requested in the brief is listed in the manifest as `NOT_SUPPLIED`, and peer benchmarking reports `PEER_DATA_NOT_AVAILABLE`. The comparison shown is against the AICTE REFERENCE document only.
- **No Kaggle data** is used, and there is no scraping beyond the supplied files.

## 2. Curriculum extraction

Topics were extracted and then cleaned:
- 8,935 topics extracted.
- 7,625 clean topics.
- 1,310 labelled as noise and kept for audit, not deleted. Noise categories: bibliography, empty, fragment, layout-interleaved, URL, administrative, long prose, outcome statement.

Other extraction counts:
- 189 valid courses, 662 units.
- Outcomes are extracted with page provenance, and every topic has a document, course, unit and page.

Quarantine (1,187 records, all kept with their reason):

| Reason | Count | Meaning |
|---|---|---|
| ORPHAN_ATTRIBUTION | 1,132 | The topic belongs to a course that failed validation. |
| ATTRIBUTION_CONFLICT | 47 topics + 5 outcomes | New in this release. See §3. |
| NO_STRUCTURAL_EVIDENCE | 2 | The course code appears once, under no semester. |
| UNRESOLVED_TITLE | 1 | No occurrence of the course carries a title. |

## 3. Defects found and fixed in this release

### 3.1 Topic misattribution (found by the new course-lineage check)

- **What happened:**
  - The R22 syllabus header for a mathematics course has a truncated code in the PDF text layer ("2MTC04"). The parser therefore carried that syllabus page's topics over to the previous code on the page, a laboratory course (22CSC04).
  - Course lineage then "matched" that lab to the R22A mathematics course with 97% shared content.
- **Generic rule added in SILVER:**
  - A topic or outcome is **quarantined** if two things are true: its page comes before its course's own header, and the course does not occur on that page.
  - The topic is **not** reassigned to another course, because that would be a guess.
  - The rule affects exactly this case in the current data: 47 topics and 5 outcomes. It is regression-tested with invented codes.

### 3.2 Unicode apostrophes (previous phase, retained)

- Curly apostrophes no longer create free-standing contraction tails. For example, "We’re" no longer yields a skill "re".
- Skill mentions fell from 1,016 to 1,006.
- 7 regression tests cover this.

## 4. Industry data

| Check | Value | Threshold |
|---|---|---|
| Postings read / eligible | 100 / 100 | ≥ 30 |
| Duplicate rate | 0.0 | ≤ 0.2 |
| Missing descriptions | 0.0 | ≤ 0.05 |
| Postings with ≥ 1 eligible skill | 0.68 | ≥ 0.5 |
| ESCO mapping yield (eligible skills) | 0.883 | ≥ 0.2 |
| Ambiguous skill ratio | 0.028 | ≤ 0.2 |
| Provenance completeness (file, row, URL, date, SHA-256) | 1.0 | 1.0 |

- **Skill mentions:** 1,006 in total. Their sense states are:
  - ESTABLISHED 764
  - ESTABLISHED_BY_CONTEXT 39
  - ALIAS_SENSE_REVIEW_REQUIRED 202
  - ACRONYM_SENSE_REVIEW_REQUIRED 1
- **Model sense decisions:** none of these mentions was changed by a model decision, because the V3 promotion gate failed (see `SEMANTIC_EVALUATION_REPORT.md`).
- **Demand support states (115 skills):**
  - INSUFFICIENT_EVIDENCE 90
  - OBSERVED 20
  - SUPPORTED 5
- **Trends:** all 115 are INSUFFICIENT_EVIDENCE. There is one collection date, and a trend needs at least two periods.

## 5. Known limitations (not fixed; disclosed)

- **Small posting set.** With 100 postings, 90 of the 115 demand skills cannot support a gap classification. As a result there is 1 recommendation, and 114 are suppressed with explicit reasons.
- **Course families are weakly separated.** KMeans silhouette is 0.108, and the chosen k = 24 sits at the configured upper bound. Concept identity across versions depends on family membership, so a small upstream change can move a course between families. Course lineage deliberately does **not** depend on families: it uses topic-level matching.
- **R22 covers semesters I–IV only.** 76 R22A courses (semesters V–VIII) are outside the comparable drift scope and are counted, not compared.
- **Occupations:** 64 of 100 job titles have no ESCO occupation match (OCCUPATION_UNMAPPED). Only EXACT or VARIANT title matches are established.
- **Lineage thresholds are not calibrated.** The share thresholds (0.25 related, 0.6 renamed) are set from observed separation on this data: related pairs 0.28–0.60, unrelated ≤ 0.13. They are not tuned against labels, because no labelled lineage set exists.
